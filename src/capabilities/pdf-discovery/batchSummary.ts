import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { sanitizeDoi } from "../../infrastructure/security/SecurityUtils.js";
import { classifyFailureCode } from "../../infrastructure/runlog/failureClass.js";
import { carsiShortReason } from "./carsi/index.js";
import type { CarsiBackend, CarsiBatchResults } from "./carsi/index.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "./batch.js";
import type { DownloadWithFallbackOptions, DownloadWithFallbackResult } from "./types.js";

/** Where a saved main text came from, as the finished window names it. */
const SOURCE_LABELS: Readonly<Record<string, string>> = {
  entitled_access: "机构订阅",
  preprint: "预印本",
  publisher_api: "出版社 API",
  scihub: "Sci-Hub",
};
const OPEN_ACCESS = "开放获取";
/** Supplement outcomes that are no shortfall: the user or the batch ended them. */
const NOT_A_SHORTFALL = new Set(["batch_stopped", "user_skipped", "cancelled"]);

/**
 * The reason a paper whose main text was saved still lacks supplementary files:
 * its first file not saved, a real failure before "no rule for this site".
 * A paper without its main text is told by its main text's reason instead.
 */
export function supplementShortfall(item: DownloadBatchItemResult): string | undefined {
  if (item.status !== "ok") return undefined;
  const missed = (item.supplements ?? []).filter((file) =>
    file.status !== "saved" && file.reason && !NOT_A_SHORTFALL.has(file.reason));
  return (missed.find((file) => file.reason !== "supplements_not_supported") ?? missed[0])?.reason;
}

/**
 * Tell the progress window how the whole batch ended: what was saved, and
 * each failure's class and reason in a few words. Sent once, after every
 * stage (open, institutional, supplementary files); the window is optional,
 * so this never changes the batch result.
 */
export async function reportBatchResults(
  result: DownloadBatchResult,
  backend: CarsiBackend | undefined,
  startedAt: number,
  folder: string,
): Promise<void> {
  if (!backend?.reportBatchProgress || result.total < 1) return;
  try {
    await backend.reportBatchProgress({
      id: result.batchId,
      total: result.total,
      done: result.total,
      succeeded: result.succeeded,
      failed: result.failed,
      finished: true,
      results: batchResults(result, startedAt, folder),
    });
  } catch {
    // The progress window is optional; it never changes a download outcome.
  }
}

/** A batch's folder for the window's button: every paper of the batch, not the last one's folder. */
export function batchFolder(savePath: string): string {
  const papers = join(savePath, "papers");
  return existsSync(papers) ? papers : savePath;
}

/**
 * One download outside a batch, run as a batch of one so the progress window
 * ends with the same finished card (its reason when it failed). Reported only
 * when the download reached the backend; an open-access copy opens no window.
 */
export async function asWindowBatch(
  options: DownloadWithFallbackOptions & { savePath: string },
  backend: CarsiBackend | undefined,
  download: (options: DownloadWithFallbackOptions) => Promise<DownloadWithFallbackResult>,
): Promise<DownloadWithFallbackResult> {
  if (!backend?.reportBatchProgress) return download(options);
  const startedAt = Date.now();
  const batch = { id: randomUUID(), index: 1, total: 1, done: 0, succeeded: 0, failed: 0 };
  const result = await download({ ...options, batch });
  const reachedBackend = result.supplements !== undefined || result.attempts.some(
    (attempt) => attempt.stage === "entitled_access" && attempt.status !== "skipped");
  if (!reachedBackend) return result;
  const ok = result.status === "ok";
  await reportBatchResults({
    status: ok ? "ok" : "error",
    mode: "per_item",
    content: options.content ?? "main",
    batchId: batch.id,
    total: 1,
    succeeded: ok ? 1 : 0,
    failed: ok ? 0 : 1,
    items: [{ ...result, index: 1, paperId: options.paperId, ...(options.doi ? { doi: options.doi } : {}) }],
  }, backend, startedAt, result.path && !result.version ? dirname(result.path) : batchFolder(options.savePath));
  return result;
}

export function batchResults(result: DownloadBatchResult, startedAt: number, folder: string): CarsiBatchResults {
  const sources = new Map<string, number>();
  const summary: CarsiBatchResults = {
    content: result.content,
    folder,
    started: Math.floor(startedAt / 1000),
    stopped: false,
    main: 0,
    supplements: 0,
    no_supplements: 0,
    sources: [],
    failures: [],
    supplement_failures: [],
  };
  for (const item of result.items) {
    const saved = item.supplements?.filter((file) => file.status === "saved").length ?? 0;
    summary.supplements += saved;
    if (item.attempts.some((attempt) => attempt.code === "batch_stopped")) summary.stopped = true;
    if (item.status === "ok") {
      if (item.attempts.some((attempt) => attempt.code === "no_supplements")) summary.no_supplements += 1;
      const shortfall = result.content === "both" ? supplementShortfall(item) : undefined;
      if (shortfall) {
        summary.supplement_failures.push({
          cls: classifyFailureCode(shortfall),
          reason: carsiShortReason(shortfall, "附录没下载成功"),
          ...(item.title ? { title: item.title } : {}),
          ...(item.journal ? { journal: item.journal } : {}),
          ...(item.doi ? { doi: item.doi } : {}),
        });
      }
      if (result.content === "supplements" || !item.path) continue;
      summary.main += 1;
      const label = sourceLabel(item);
      sources.set(label, (sources.get(label) ?? 0) + 1);
      continue;
    }
    summary.failures.push({
      ...failure(item, result.content),
      ...(item.title ? { title: item.title } : {}),
      ...(item.journal ? { journal: item.journal } : {}),
      ...(item.doi ? { doi: item.doi } : {}),
      ...(saved ? { note: `附录 ${saved} 个已保存` } : {}),
    });
  }
  summary.sources = [...sources].sort((a, b) => b[1] - a[1]);
  return summary;
}

function sourceLabel(item: DownloadBatchItemResult): string {
  if (item.version === "preprint") return SOURCE_LABELS.preprint;
  const saved = [...item.attempts].reverse().find((attempt) => attempt.status === "ok");
  return (saved && SOURCE_LABELS[saved.stage]) || OPEN_ACCESS;
}

/** The failure's class (ADR 0012) and its reason in a few words. */
function failure(
  item: DownloadBatchItemResult,
  content: DownloadBatchResult["content"],
): Pick<CarsiBatchResults["failures"][number], "cls" | "reason"> {
  if (content === "supplements") {
    const code = item.supplements?.find((file) => file.status !== "saved" && file.reason)?.reason;
    return { cls: classifyFailureCode(code), reason: carsiShortReason(code, "附录没下载成功") };
  }
  const entitled = [...item.attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
  if (entitled && (entitled.status === "error" || entitled.code === "batch_stopped")) {
    return { cls: classifyFailureCode(entitled.code), reason: carsiShortReason(entitled.code) };
  }
  // Institutional access never ran for this item.
  return item.doi && sanitizeDoi(item.doi).valid
    ? { cls: "user_or_external", reason: "没有进行机构下载" }
    : { cls: "unsupported", reason: "没有有效 DOI" };
}
