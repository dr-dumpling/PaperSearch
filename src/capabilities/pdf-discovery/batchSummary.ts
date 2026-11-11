import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { sanitizeDoi } from "../../infrastructure/security/SecurityUtils.js";
import { classifyFailureCode } from "../../infrastructure/runlog/failureClass.js";
import { carsiShortReason } from "./carsi/index.js";
import type { CarsiBackend, CarsiBatchPaper, CarsiBatchResults } from "./carsi/index.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "./batch.js";
import type { DownloadWithFallbackOptions, DownloadWithFallbackResult } from "./types.js";

/**
 * Where a saved main text came from, as the finished window names it: the two
 * ways of downloading (the guide's 开放下载 and 机构下载, the batch's two lanes),
 * the open one's sources other than open access in brackets (user, 2026-11-10).
 */
const OPEN_DOWNLOAD = "开放下载";
const ENTITLED_DOWNLOAD = "机构下载";
const OPEN_DETAILS: Readonly<Record<string, string>> = {
  publisher_api: "出版社 API",
  scihub: "Sci-Hub",
  preprint: "预印本",
};
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
  const details = new Map<string, number>();
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
      const missing = supplementsMissing(item, result.content);
      if (missing) {
        summary.supplement_failures.push({
          ...missing,
          ...(item.title ? { title: item.title } : {}),
          ...(item.journal ? { journal: item.journal } : {}),
          ...(item.doi ? { doi: item.doi } : {}),
        });
      }
      if (result.content === "supplements" || !item.path) continue;
      summary.main += 1;
      const [label, detail] = sourceLabel(item);
      sources.set(label, (sources.get(label) ?? 0) + 1);
      if (detail) details.set(detail, (details.get(detail) ?? 0) + 1);
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
  if (details.size) summary.source_details = [[OPEN_DOWNLOAD, [...details].map(([name, n]) => `${name} ${n}`).join("、")]];
  return summary;
}

/**
 * A paper for the window's lists (成功, 失败, 剩余): waiting in a lane, or its
 * result as the finished card tells it (the way it came, or why it failed).
 */
export function batchPaper(
  request: DownloadWithFallbackOptions,
  item: DownloadBatchItemResult | undefined,
  waiting: "open" | "school" | undefined,
  content: DownloadBatchResult["content"],
): Omit<CarsiBatchPaper, "index"> {
  const paper = { doi: item?.doi ?? request.doi ?? "", title: item?.title ?? request.title ?? "", journal: item?.journal ?? "" };
  if (waiting || !item) return { ...paper, state: waiting ?? "open" };
  if (item.status !== "ok") return { ...paper, state: "failed", ...failure(item, content) };
  const [via, detail] = sourceLabel(item);
  // The window's 失败 list also shows a saved paper still missing supplementary files (user, 2026-11-11).
  const missing = supplementsMissing(item, content);
  return {
    ...paper, state: "ok", via, ...(detail ? { detail } : {}), ...(item.path ? { path: item.path } : {}),
    ...(missing ? { supplement_cls: missing.cls, supplement_reason: missing.reason } : {}),
  };
}

/** Supplementary files a saved paper is missing (content "both"): the class and the reason in a few words. */
function supplementsMissing(
  item: DownloadBatchItemResult,
  content: DownloadBatchResult["content"],
): Pick<CarsiBatchResults["supplement_failures"][number], "cls" | "reason"> | undefined {
  const shortfall = content === "both" ? supplementShortfall(item) : undefined;
  return shortfall ? { cls: classifyFailureCode(shortfall), reason: carsiShortReason(shortfall, "附录没下载成功") } : undefined;
}

/** The way a main text came (and, for the open one, its source when not open access). */
function sourceLabel(item: DownloadBatchItemResult): [string, string?] {
  if (item.version === "preprint") return [OPEN_DOWNLOAD, OPEN_DETAILS.preprint];
  const saved = [...item.attempts].reverse().find((attempt) => attempt.status === "ok");
  if (saved?.stage === "entitled_access") return [ENTITLED_DOWNLOAD];
  return [OPEN_DOWNLOAD, saved ? OPEN_DETAILS[saved.stage] : undefined];
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
