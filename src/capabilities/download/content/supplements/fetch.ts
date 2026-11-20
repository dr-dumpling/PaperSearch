/**
 * 补充材料怎么拿（TS 这一侧）。补充材料只在出版社的文章页上列出，在页面上找、下载都由学校订阅下载
 * 后端在浏览器里完成（school/paper_search_school/engine/supplements.py 和各出版社的 adapters/）；
 * 这里向后端要补充材料、把下到的文件放进论文的文件夹、批量中正文来自开放来源的篇目再补补充材料、
 * 断网后重补。
 */
import { dirname } from "node:path";
import { resolveDownloadPath } from "../../../../config/ConfigService.js";
import type { Searchers } from "../../../../core/searchers.js";
import { createOutputLayout, inPaperDir, isInside, lookupOutputMetadata, moveIntoPaperDir, organizeFiles, removeWorkFolder } from "../../outputLayout.js";
import { schoolAttemptDetails, type SchoolBackend, type SchoolDownloadRequest } from "../../../../infrastructure/school/index.js";
import { pastNetworkLoss, type NetworkWatch } from "../../batch/networkLoss.js";
import type { DownloadBatchItemResult } from "../../batch/batch.js";
import type { CapturedFulltextPage, DownloadWithFallbackOptions, DownloadWithFallbackResult, SupplementFile } from "../../types.js";

/**
 * Supplementary files only, for an article whose main text came from another
 * stage. Undefined when no backend can do it.
 */
export async function fetchSupplementsOnly(
  backend: SchoolBackend | undefined,
  request: Omit<SchoolDownloadRequest, "supplements">,
  onTrace?: (trace: Record<string, unknown>) => void,
  onFulltextPage?: (page: CapturedFulltextPage) => void,
): Promise<SupplementFile[] | undefined> {
  if (!backend) return undefined;
  try {
    const outcome = await backend.downloadLegalDoi({ ...request, supplements: "only" });
    if (outcome.kind === "backend_unavailable") return undefined;
    if (outcome.trace) onTrace?.({ ...outcome.trace });
    // --fulltext: the article page that visit opened.
    if (outcome.fulltextPage) onFulltextPage?.(outcome.fulltextPage);
    if (outcome.kind === "attempt_error" && (!outcome.supplements ||
        (outcome.supplements.length === 0 && outcome.code !== "supplements_only"))) {
      const { code } = schoolAttemptDetails(outcome.code);
      return [{ label: "", status: code === "batch_stopped" || code === "user_skipped" ? "skipped" : "failed", reason: code }];
    }
    return outcome.supplements ?? [{ label: "", status: "failed", reason: "supplements_not_reported" }];
  } catch (error) {
    return [
      {
        label: "",
        status: "failed",
        reason: error instanceof Error ? error.name : "backend_error",
      },
    ];
  }
}

/**
 * Supplementary files only: the entitled-access backend visits the article
 * page for them. An empty completed check is also ok; it is not a failed download,
 * nor is a site without a supplementary-file rule (user, 2026-11-11). Reported to
 * the run ledger through ``request.onStage`` as the "supplements" stage.
 * ``mainPath``: the paper's main text, saved before; once a file is saved it moves
 * into the paper's folder beside them (the returned ``path``).
 */
export async function downloadSupplementsOnly(
  request: DownloadWithFallbackOptions,
  backend: SchoolBackend | undefined,
  searchers?: Searchers,
  mainPath?: string,
): Promise<DownloadWithFallbackResult> {
  request = { ...request, savePath: resolveDownloadPath(request.savePath) };
  const startedAt = Date.now();
  const metadata = searchers ? await lookupOutputMetadata(searchers, request.doi ? "crossref" : request.source, request.doi || request.paperId) : {};
  let layout = createOutputLayout(request.savePath!, request.doi || request.paperId,
    { ...metadata, title: request.title || metadata.title }, false, { diagnosticsDir: request.diagnosticsDir });
  // A main text already in a folder of its own (an earlier download): its files go beside it.
  const mainDir = mainPath ? dirname(mainPath) : "";
  if (mainDir && isInside(mainDir, request.savePath!)) layout = inPaperDir(layout, mainDir);
  let trace: Record<string, unknown> | undefined;
  let fulltextPage: DownloadWithFallbackResult["fulltextPage"];
  const files = await fetchSupplementsOnly(backend, {
    identifier: request.doi || request.paperId,
    outputDir: layout.paperDir,
    diagnosticsDir: layout.workDiagnosticsDir,
    ...(request.batch ? { batch: request.batch } : {}),
    ...(request.shortUserWait ? { userWait: "short" as const } : {}),
    ...(request.school ? { school: request.school } : {}),
    // The Markdown: the article page this visit opens is read too (no second visit).
    ...(request.fulltext ? { fulltext: "with" as const } : {}),
  }, value => { trace = value; }, page => { fulltextPage = page; });
  const saved = files?.filter((f) => f.status === "saved").length ?? 0;
  const noneListed = files?.length === 0;
  // No rule for the site's supplementary files: not known whether there are any, and no fault to diagnose.
  const unsupported = !!files?.length && files.every((file) => file.reason === "supplements_not_supported");
  let filingFailed = false;
  let movedMain: string | undefined;
  try {
    const status = files?.every((file) => file.status === "saved") || unsupported ? "ok" : "error";
    if (files) organizeFiles({ supplements: files, trace, status }, layout, layout.paperDir, undefined, request.recordsDir);
    if (saved && mainPath) {
      const moved = moveIntoPaperDir(mainPath, layout);
      if (moved !== mainPath) movedMain = moved;
    }
    removeWorkFolder(layout);
  }
  catch { filingFailed = true; } // Preserve saved files and report filing separately below.
  const attempt: DownloadWithFallbackResult["attempts"][number] =
    files === undefined
      ? { stage: "supplements", status: "skipped", message: "No entitled-access backend for supplementary files." }
      : noneListed
        ? { stage: "supplements", status: "skipped", code: "no_supplements",
            message: "Article page checked; no supplementary files were listed." }
      : unsupported
        ? { stage: "supplements", status: "skipped", code: "supplements_not_supported",
            message: "No supplementary-file rule for this site yet; get them from the article page by hand." }
      : {
          stage: "supplements",
          status: saved ? "ok" : "error",
          message: `${saved}/${files.length} supplementary files saved.`,
          ...(saved ? {} : { code: "supplements_failed" }),
        };
  request.onStage?.({ ...attempt, ...(trace ? { trace } : {}), startedAt: new Date(startedAt).toISOString(), durationMs: Date.now() - startedAt });
  const title = request.title || metadata.title;
  return {
    status: saved || noneListed || unsupported ? "ok" : "error",
    ...(movedMain ? { path: movedMain } : {}),
    ...(title ? { title } : {}),
    ...(metadata.journal ? { journal: metadata.journal } : {}),
    attempts: [attempt, ...(filingFailed ? [{ stage: "output_layout", status: "error" as const,
      code: "output_layout_failed", message: "File organization failed; use the returned file paths." }] : [])],
    ...(files ? { supplements: files } : {}),
    ...(fulltextPage ? { fulltextPage } : {}),
  };
}

/** content "both": supplementary files for an item whose main text came from an open stage. */
export async function supplementsForOpenItem(
  result: DownloadBatchItemResult,
  request: DownloadWithFallbackOptions,
  backend: SchoolBackend | undefined,
  searchers: Searchers,
): Promise<DownloadWithFallbackResult | undefined> {
  if (request.content !== "both" || result.status !== "ok" || result.supplements) return;
  const extra = await downloadSupplementsOnly({ ...request, ...(result.publishedDoi ? { doi: result.publishedDoi } : {}) }, backend, searchers, result.path && !result.version ? result.path : undefined);
  if (extra.supplements) result.supplements = extra.supplements;
  if (extra.path) result.path = extra.path;  // moved into its folder beside the files
  if (extra.fulltextPage) result.fulltextPage = extra.fulltextPage;
  return extra;
}

/**
 * supplementsForOpenItem, asked again after a network loss: the files the lost network
 * failed are fetched anew once it is back (those a first visit found stand otherwise).
 */
export async function filesPastNetworkLoss(
  result: DownloadBatchItemResult,
  request: DownloadWithFallbackOptions,
  backend: SchoolBackend | undefined,
  searchers: Searchers,
  watch: NetworkWatch,
): Promise<DownloadWithFallbackResult | undefined> {
  let extra: DownloadWithFallbackResult | undefined;
  let again = false;
  await pastNetworkLoss(async () => {
    if (again) delete result.supplements;
    again = true;
    extra = await supplementsForOpenItem(result, request, backend, searchers);
    return extra ?? { status: "ok", attempts: [] };
  }, watch);
  return extra;
}
