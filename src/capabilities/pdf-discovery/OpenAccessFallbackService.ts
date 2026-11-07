import { resolveDownloadPath } from "../../config/ConfigService.js";
import { createOutputLayout, lookupOutputMetadata, organizeFiles } from "./outputLayout.js";
import { prepareArxiv } from "./arxiv.js";
import { createPreprintTier } from "./tiers/preprint.js";
import type { Searchers } from "../../core/searchers.js";
import { TIMEOUTS } from "../../config/constants.js";
import { unlinkSync } from "node:fs";
import { verifyPdfIdentity, type PdfIdentityStatus } from "../../infrastructure/pdf/PdfIdentity.js";
import { sanitizeDoi, withTimeout } from "../../infrastructure/security/SecurityUtils.js";
import { identityRejection } from "./identity.js";
import type {
  DownloadTier,
  DownloadTierContext,
  DownloadTierResult,
} from "./DownloadTier.js";
import type {
  DownloadWithFallbackOptions,
  DownloadWithFallbackResult,
} from "./types.js";
import type { CarsiBackend } from "./carsi/index.js";
import { createDirectPdfUrlTier } from "./tiers/directPdfUrl.js";
import { createEntitledAccessTier } from "./tiers/entitledAccess.js";
import { createPrimaryTier } from "./tiers/primary.js";
import { createPublisherApiTier } from "./tiers/publisherApi.js";
import { createRepositoryTier } from "./tiers/repositories.js";
import { createSciHubTier } from "./tiers/scihub.js";
import { createUnpaywallTier } from "./tiers/unpaywall.js";

export type {
  DownloadTier,
  DownloadTierContext,
  DownloadTierResult,
} from "./DownloadTier.js";
export type {
  DownloadWithFallbackOptions,
  DownloadWithFallbackResult,
} from "./types.js";

export function createDefaultDownloadTiers(
  carsiBackend?: CarsiBackend,
): DownloadTier[] {
  return [
    createPrimaryTier(),
    createDirectPdfUrlTier(),
    createRepositoryTier(),
    createUnpaywallTier(),
    createPublisherApiTier(),
    createSciHubTier(),
    createEntitledAccessTier(carsiBackend),
    createPreprintTier(),
  ];
}

export function insertDownloadTierBefore(
  tiers: DownloadTier[],
  beforeStage: string,
  tier: DownloadTier,
): DownloadTier[] {
  const index = tiers.findIndex((item) => item.stage === beforeStage);
  if (index < 0) return [...tiers, tier];
  return [...tiers.slice(0, index), tier, ...tiers.slice(index)];
}

export interface DownloadFallbackLimits {
  /** Wall-clock cap per non-entitled stage (entitled access has its own). */
  stageTimeoutMs?: number;
}

const STAGE_TIMEOUT = "paper-search-stage-timeout";

/** A stage that outlives its deadline is recorded and skipped, never awaited. */
async function runStage(
  tier: DownloadTier,
  context: DownloadTierContext,
  timeoutMs: number,
): Promise<DownloadTierResult> {
  if (tier.stage === "entitled_access") return tier.run(context);
  try {
    return await withTimeout(tier.run(context), timeoutMs, STAGE_TIMEOUT);
  } catch (error) {
    if (error instanceof Error && error.message === STAGE_TIMEOUT) {
      return {
        status: "error",
        code: "stage_timeout",
        message: `${tier.stage} did not finish within ${Math.round(timeoutMs / 1000)}s and was skipped.`,
      };
    }
    throw error;
  }
}

export async function downloadWithFallback(
  searchers: Searchers,
  options: DownloadWithFallbackOptions,
  tiers: DownloadTier[] = createDefaultDownloadTiers(),
  limits: DownloadFallbackLimits = {},
  verifyIdentity: PdfIdentityCheck = verifyPdfIdentity,
): Promise<DownloadWithFallbackResult> {
  const stageTimeoutMs = limits.stageTimeoutMs ?? TIMEOUTS.FALLBACK_STAGE;
  const savePath = resolveDownloadPath(options.savePath);
  const attempts: DownloadWithFallbackResult["attempts"] = [];
  let review: DownloadWithFallbackResult["review"];
  const reviewPaths: string[] = [];
  const context: DownloadTierContext = {
    searchers,
    preprintIds: options.preprintIds || [],
    source: normalizeSource(options.source),
    paperId: options.paperId,
    doi: options.doi,
    title: options.title,
    savePath,
    useEntitledAccess: options.useEntitledAccess !== false,
    useSciHub: options.useSciHub !== false,
    ...(options.batch ? { batch: options.batch } : {}),
    ...(options.content === "both" ? { withSupplements: true } : {}),
    ...(options.shortUserWait ? { shortUserWait: true } : {}),
  };
  let supplements: DownloadWithFallbackResult["supplements"];
  await prepareArxiv(context);
  context.outputMetadata = context.arxivOnly ? context.arxivPaper || {} : await lookupOutputMetadata(
    searchers, context.doi ? "crossref" : context.source, context.doi || context.paperId);
  context.title ||= context.outputMetadata.title;
  context.titleLookedUp = true;
  const layout = createOutputLayout(savePath, context.doi || context.paperId,
    { ...context.outputMetadata, title: context.title }, !!context.arxivOnly);
  const paper = {
    ...(context.title ? { title: context.title } : {}),
    ...(context.outputMetadata.journal ? { journal: context.outputMetadata.journal } : {}),
  };
  context.savePath = layout.paperDir;
  context.diagnosticsDir = layout.diagnosticsDir;

  for (const tier of tiers) {
    const startedAt = Date.now();
    let result: DownloadTierResult;
    if (SELF_VERIFYING_STAGES.has(tier.stage)) {
      // These tiers check identity themselves; give them the title first.
      const doi = context.doi && sanitizeDoi(context.doi).valid ? context.doi : "";
      if (doi) await fillTitle(context, doi);
    }
    try {
      result = context.arxivOnly && tier.stage !== "preprint"
        ? { status: "skipped", message: context.arxivLookupError
            ? "arXiv publication metadata unavailable; published DOI could not be resolved."
            : "No published DOI is linked to this arXiv identifier." }
        : await runStage(tier, context, stageTimeoutMs);
    } catch (error) {
      notifyStage(options, tier.stage, startedAt, {
        status: "error",
        code: "stage_exception",
        message: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
      });
      throw error;
    }
    result = await identityGate(result, context, verifyIdentity);
    try {
      const destination = result.version === "preprint"
        ? createOutputLayout(savePath, `arxiv:${result.arxivId}`, context.arxivPaper || {}, true) : layout;
      organizeFiles(result, destination, context.savePath);
    } catch (error) {
      // Keep the retrieved file and report a concrete filing failure.
      attempts.push({ stage: "output_layout", status: "error", code: "output_layout_failed",
        message: `File organization failed (${error instanceof Error ? error.name : "Error"}); use the returned file paths.` });
    }
    notifyStage(options, tier.stage, startedAt, result);
    attempts.push({
      stage: tier.stage,
      status: result.status,
      message: result.message,
      ...(result.code ? { code: result.code } : {}),
      ...(result.retryAfterSec ? { retryAfterSec: result.retryAfterSec } : {}),
    });
    if (result.review) {
      review = result.review;
      reviewPaths.push(result.review.path);
    }
    if (result.supplements?.length) supplements = result.supplements;
    if (result.status === "ok" && result.path) {
      discardReviews(reviewPaths, result.path);
      return {
        status: "ok",
        ...paper,
        path: result.path,
        ...(result.version ? { version: result.version, arxivId: result.arxivId } : {}),
        ...(result.publishedDoi || context.arxivId && context.doi ? { publishedDoi: result.publishedDoi || context.doi } : {}),
        ...(result.format && result.format !== "pdf"
          ? { format: result.format }
          : {}),
        attempts,
        ...(supplements ? { supplements } : {}),
      };
    }
    if (["batch_stopped", "user_skipped"].includes(result.code || "")) break;
  }

  return {
    status: "error",
    ...paper,
    attempts,
    ...(review ? { review } : {}),
    ...(supplements ? { supplements } : {}),
  };
}

/** Tiers that verify the PDF's identity themselves (publisher APIs, the browser backend). */
const SELF_VERIFYING_STAGES = new Set(["publisher_api", "entitled_access"]);

export type PdfIdentityCheck = (
  path: string,
  identifier: string,
  title?: string,
) => Promise<PdfIdentityStatus>;

/**
 * Every PDF must be this article before the funnel stops: tiers that did not
 * check it themselves are checked here. A PDF that fails is kept for review and
 * the next tier runs. Without a DOI the current rules cannot check, so the PDF
 * is accepted as before and marked "not_checked" in the ledger trace.
 */
async function identityGate(
  result: DownloadTierResult,
  context: DownloadTierContext,
  verifyIdentity: PdfIdentityCheck,
): Promise<DownloadTierResult> {
  if (result.status !== "ok" || !result.path || result.verified || (result.format && result.format !== "pdf")) {
    return result;
  }
  const doi = context.doi && sanitizeDoi(context.doi).valid ? context.doi : "";
  if (!doi) return { ...result, trace: { ...result.trace, identity: "not_checked" } };
  await fillTitle(context, doi);
  const identity = await verifyIdentity(result.path, doi, context.title);
  const rejection = identityRejection(identity, result.path);
  return rejection
    ? { ...rejection, trace: { ...result.trace, identity } }
    : { ...result, verified: true, trace: { ...result.trace, identity } };
}

/**
 * The title is evidence of its own (PdfIdentity): it settles a PDF that also
 * prints other DOIs. Requests that name only a DOI get the title from Crossref
 * once, for this check and for the tiers that follow.
 */
async function fillTitle(context: DownloadTierContext, doi: string): Promise<void> {
  if (context.title?.trim() || context.titleLookedUp) return;
  context.titleLookedUp = true;
  const crossref = (context.searchers as any)?.crossref;
  if (!crossref?.getPaperByDoi) return;
  try {
    const paper = (await withTimeout(crossref.getPaperByDoi(doi), 10_000, "title lookup timed out")) as { title?: string } | null;
    if (paper?.title) context.title = String(paper.title);
  } catch {
    // Without a title the check still runs on the DOI evidence alone.
  }
}

/** A later tier succeeded: files kept for review by earlier tiers are not needed. */
function discardReviews(paths: string[], keep: string): void {
  for (const path of paths) {
    if (path === keep) continue;
    try {
      unlinkSync(path);
    } catch {
      // Already gone or not ours to remove; the download result is unaffected.
    }
  }
}

function notifyStage(
  options: DownloadWithFallbackOptions,
  stage: string,
  startedAt: number,
  result: DownloadTierResult,
): void {
  options.onStage?.({
    stage,
    status: result.status,
    message: result.message,
    ...(result.code ? { code: result.code } : {}),
    ...(result.path ? { path: result.path } : {}),
    startedAt: new Date(startedAt).toISOString(),
    durationMs: Date.now() - startedAt,
    ...(result.trace ? { trace: result.trace } : {}),
  });
}

function normalizeSource(source: string): string {
  const normalized = source.trim().toLowerCase();
  if (normalized === "google_scholar") return "googlescholar";
  if (normalized === "pubmed_central") return "pmc";
  if (normalized === "europe_pmc") return "europepmc";
  return normalized;
}
