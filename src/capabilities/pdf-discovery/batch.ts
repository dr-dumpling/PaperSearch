import { randomUUID } from "node:crypto";
import type { Searchers } from "../../core/searchers.js";
import { RunLedger, type RunItem } from "../../infrastructure/runlog/RunLedger.js";
import {
  classifyFailureCode,
  FAILURE_CLASS_NAMES,
  type FailureClass,
} from "../../infrastructure/runlog/failureClass.js";
import type { DownloadTier } from "./DownloadTier.js";
import {
  createDefaultDownloadTiers,
  downloadWithFallback,
} from "./OpenAccessFallbackService.js";
import type { CarsiBackend } from "./carsi/index.js";
import { fetchSupplementsOnly } from "./tiers/entitledAccess.js";
import type {
  DownloadContent,
  DownloadBatchPosition,
  DownloadWithFallbackOptions,
  DownloadWithFallbackResult,
} from "./types.js";

export const MAX_BATCH_ITEMS = 1000;

export interface DownloadBatchItem {
  source?: string;
  paperId?: string;
  doi?: string;
  title?: string;
  /** Overrides the batch savePath for this item. */
  savePath?: string;
}

/**
 * two_phase (default): every item first tries the open stages; only the items
 * still missing then go through entitled access, one after another, so the
 * browser and logins are needed in one stretch at the end.
 * per_item: each item runs the whole funnel before the next one starts.
 * entitled_only: skip the open stages; every item goes straight to entitled
 * access (testing the institutional route, or a list already known closed).
 */
export type DownloadBatchMode = "two_phase" | "per_item" | "entitled_only";

export interface DownloadBatchOptions {
  items: DownloadBatchItem[];
  savePath?: string;
  useEntitledAccess?: boolean;
  useSciHub?: boolean;
  mode?: DownloadBatchMode;
  /** main (default) / supplements / both (see DownloadWithFallbackOptions). */
  content?: DownloadContent;
}

export interface DownloadBatchItemResult
  extends Omit<DownloadWithFallbackResult, "status"> {
  index: number;
  paperId: string;
  doi?: string;
  status: "ok" | "error";
}

export interface DownloadBatchResult {
  /** ok: every item succeeded; partial: some did; error: none did. */
  status: "ok" | "partial" | "error";
  mode: DownloadBatchMode;
  /** What was downloaded; "main" unless requested otherwise. */
  content: DownloadContent;
  batchId: string;
  /** two_phase only: items that went on to entitled access. */
  entitledAccessItems?: number;
  total: number;
  succeeded: number;
  failed: number;
  /** Directory of the local run ledger (run.json, items.jsonl, timeline.log). */
  runLog?: string;
  /** Failed institutional downloads by class (ADR 0012). */
  failureClasses?: Partial<Record<FailureClass, number>>;
  items: DownloadBatchItemResult[];
}

/**
 * One item of a serial batch. When the item reaches the entitled-access
 * backend, the backend records it in its progress window itself; items that
 * finish earlier (open access, Sci-Hub) and the last item are reported with
 * the batch totals so the window always shows "k / N" for the whole batch.
 */
export async function downloadBatchItem(
  searchers: Searchers,
  options: DownloadWithFallbackOptions & { batch: DownloadBatchPosition },
  tiers: DownloadTier[],
  backend?: CarsiBackend,
): Promise<DownloadWithFallbackResult> {
  const result = await downloadWithFallback(searchers, options, tiers);
  await reportBatchItem(options, result, backend);
  return result;
}

async function reportBatchItem(
  options: DownloadWithFallbackOptions & { batch: DownloadBatchPosition },
  result: DownloadWithFallbackResult,
  backend?: CarsiBackend,
): Promise<void> {
  const { batch } = options;
  if (!backend?.reportBatchProgress || rateLimitWait(result)) return;  // a waiting item runs again
  const reachedBackend = result.attempts.some(
    (attempt) =>
      attempt.stage === "entitled_access" && attempt.status !== "skipped",
  );
  const finished = batch.index >= batch.total;
  if (reachedBackend && !finished) return;
  const ok = result.status === "ok";
  try {
    await backend.reportBatchProgress({
      id: batch.id,
      total: batch.total,
      done: batch.done + 1,
      succeeded: batch.succeeded + (ok ? 1 : 0),
      failed: batch.failed + (ok ? 0 : 1),
      current: options.doi || options.paperId,
      finished,
    });
  } catch {
    // The progress window is optional; it never changes a download outcome.
  }
}

function itemOptions(
  item: DownloadBatchItem,
  options: DownloadBatchOptions,
): DownloadWithFallbackOptions & { doi: string } {
  const doi = item.doi?.trim() || "";
  return {
    source: item.source?.trim() || "crossref",
    paperId: item.paperId?.trim() || doi,
    doi,
    title: item.title?.trim() || "",
    savePath: item.savePath?.trim() || options.savePath,
    useEntitledAccess: options.useEntitledAccess,
    useSciHub: options.useSciHub,
    ...(options.content && options.content !== "main" ? { content: options.content } : {}),
  };
}

/**
 * Supplementary files only: the entitled-access backend visits the article
 * page for them. ok when at least one file was saved. Reported to the run
 * ledger through ``request.onStage`` as the "supplements" stage.
 */
export async function downloadSupplementsOnly(
  request: DownloadWithFallbackOptions,
  backend: CarsiBackend | undefined,
): Promise<DownloadWithFallbackResult> {
  const startedAt = Date.now();
  const files = await fetchSupplementsOnly(backend, {
    identifier: request.doi || request.paperId,
    outputDir: request.savePath || "./downloads",
  });
  const saved = files?.filter((f) => f.status === "saved").length ?? 0;
  const attempt: DownloadWithFallbackResult["attempts"][number] =
    files === undefined
      ? { stage: "supplements", status: "skipped", message: "No entitled-access backend for supplementary files." }
      : {
          stage: "supplements",
          status: saved ? "ok" : "error",
          message: `${saved}/${files.length} supplementary files saved.`,
          ...(saved ? {} : { code: files.length ? "supplements_failed" : "no_supplements" }),
        };
  request.onStage?.({ ...attempt, startedAt: new Date(startedAt).toISOString(), durationMs: Date.now() - startedAt });
  return {
    status: saved ? "ok" : "error",
    attempts: [attempt],
    ...(files ? { supplements: files } : {}),
  };
}

/** content "both": supplementary files for an item whose main text came from an open stage. */
async function supplementsForOpenItem(
  result: DownloadBatchItemResult,
  request: DownloadWithFallbackOptions,
  backend: CarsiBackend | undefined,
): Promise<void> {
  if (request.content !== "both" || result.status !== "ok" || result.supplements) return;
  const extra = await downloadSupplementsOnly(request, backend);
  if (extra.supplements) result.supplements = extra.supplements;
}

const AWAY_NOTICE =
  "[批量] 这一篇等你登录或验证已到时限；后面的篇目遇到登录或验证只等 60 秒，你在登录页开始输入就照常等";

/**
 * Entitled access waited on the user (school login, verification) until its
 * time was up: the user seems away, so later articles of the batch wait briefly.
 */
function waitedOutOnUser(result: DownloadWithFallbackResult): boolean {
  return (
    result.status !== "ok" &&
    result.attempts.some(
      (attempt) =>
        attempt.stage === "entitled_access" &&
        (attempt.code === "login_timeout" || attempt.code === "download_timeout"),
    )
  );
}

/**
 * Seconds the backend asked this article to wait: the publisher's hourly
 * limit was reached before it opened (dependencies section 6, state L).
 */
function rateLimitWait(result: DownloadWithFallbackResult): number {
  if (result.status === "ok") return 0;
  const attempt = result.attempts.find(
    (a) => a.stage === "entitled_access" && a.code === "rate_limited",
  );
  return attempt ? Math.max(1, Math.min(3600, attempt.retryAfterSec ?? 60)) : 0;
}

/** Runs the item again after each wait the publisher's hourly limit asks for. */
async function pastHourlyLimit(
  run: () => Promise<DownloadWithFallbackResult>,
  log: (line: string) => void,
  pause: (ms: number) => Promise<void>,
): Promise<DownloadWithFallbackResult> {
  let result = await run();
  for (let wait = rateLimitWait(result); wait; wait = rateLimitWait(result)) {
    const resume = new Date(Date.now() + wait * 1000).toTimeString().slice(0, 5);
    log(`[批量] 这家出版社一小时内的下载已到上限（防止学校被暂停访问），${resume} 继续这一篇`);
    await pause(wait * 1000);
    result = await run();
  }
  return result;
}

/** The journal's site blocked the current network (state L): a protection page,
 * or the school paused for downloading too much. The backend answers the
 * journal's later items at once; every other item goes on (the user, 2026-11-02). */
function publisherBlocked(result: DownloadWithFallbackResult): boolean {
  return (
    result.status !== "ok" &&
    result.attempts.some((a) => a.stage === "entitled_access" && a.code === "access_blocked")
  );
}

function blockedNotice(doi: string): string {
  return (
    `[批量] 出版社网站拦截了当前网络（${doi}）：可能是当前网络被网站防护拦截，也可能是下载过多被暂停；` +
    "同一期刊的后续文章直接跳过，其他照常继续。可换网络或稍后再试"
  );
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function runItem(index: number, request: DownloadWithFallbackOptions): RunItem {
  return {
    index,
    paperId: request.paperId,
    ...(request.doi ? { doi: request.doi } : {}),
    ...(request.title ? { title: request.title } : {}),
  };
}

/** Request options that report each stage of ``item`` to the ledger. */
function recorded<T extends DownloadWithFallbackOptions>(
  request: T,
  ledger: RunLedger | null,
  item: RunItem,
): T {
  return ledger ? { ...request, onStage: (record) => ledger.stage(item, record) } : request;
}

function openLedger(
  mode: string,
  batchId: string,
  options: DownloadBatchOptions,
  log: (line: string) => void,
): RunLedger | null {
  const ledger = RunLedger.open({
    kind: "download_batch",
    mode,
    batchId,
    total: options.items.length,
    ...(options.savePath ? { savePath: options.savePath } : {}),
  });
  if (ledger) log(`[批量] 运行记录：${ledger.dir}`);
  return ledger;
}

function itemResult(
  result: DownloadWithFallbackResult,
  index: number,
  options: DownloadWithFallbackOptions & { doi: string },
): DownloadBatchItemResult {
  return {
    ...result,
    index,
    paperId: options.paperId,
    ...(options.doi ? { doi: options.doi } : {}),
  };
}

function summary(
  mode: DownloadBatchMode,
  batchId: string,
  items: DownloadBatchItemResult[],
  extra: Partial<DownloadBatchResult> = {},
): DownloadBatchResult {
  const succeeded = items.filter((item) => item.status === "ok").length;
  const failed = items.length - succeeded;
  const failureClasses: Partial<Record<FailureClass, number>> = {};
  for (const item of items) {
    const entitled = [...item.attempts].reverse().find((attempt) => attempt.stage === "entitled_access");
    if (item.status === "ok" || entitled?.status !== "error") continue;
    const failureClass = classifyFailureCode(entitled.code);
    failureClasses[failureClass] = (failureClasses[failureClass] ?? 0) + 1;
  }
  return {
    status: failed === 0 ? "ok" : succeeded === 0 ? "error" : "partial",
    mode,
    content: "main",
    batchId,
    total: items.length,
    succeeded,
    failed,
    ...(Object.keys(failureClasses).length ? { failureClasses } : {}),
    ...extra,
    items,
  };
}

/** Download a list serially; one batch id ties it to one progress window. */
export async function downloadBatch(
  searchers: Searchers,
  options: DownloadBatchOptions,
  backend?: CarsiBackend,
  log: (line: string) => void = (line) => process.stderr.write(`${line}\n`),
  createTiers: (backend?: CarsiBackend) => DownloadTier[] = createDefaultDownloadTiers,
  pause: (ms: number) => Promise<void> = wait,
): Promise<DownloadBatchResult> {
  const result =
    options.content === "supplements"
      ? await downloadSupplementsBatch(options, backend, log)
      : options.mode === "per_item"
        ? await downloadPerItem(searchers, options, backend, log, createTiers, pause)
        : await downloadTwoPhase(searchers, options, backend, log, createTiers,
            options.mode === "entitled_only" ? "entitled_only" : "two_phase", pause);
  const byClass = Object.entries(result.failureClasses ?? {})
    .map(([failureClass, count]) => `${FAILURE_CLASS_NAMES[failureClass as FailureClass]} ${count}`)
    .join("、");
  log(`[批量] 完成：成功 ${result.succeeded}，失败 ${result.failed}，共 ${result.total} 篇` +
    (byClass ? `。失败分类：${byClass}；详情：paper-search failures --format text` : ""));
  return result;
}

/** content "supplements": every item, one after another, supplementary files only. */
async function downloadSupplementsBatch(
  options: DownloadBatchOptions,
  backend: CarsiBackend | undefined,
  log: (line: string) => void,
): Promise<DownloadBatchResult> {
  const batchId = randomUUID();
  const total = options.items.length;
  const ledger = openLedger("supplements", batchId, options, log);
  const items: DownloadBatchItemResult[] = [];
  for (const [offset, item] of options.items.entries()) {
    const request = itemOptions(item, options);
    const entry = runItem(offset + 1, request);
    log(`[批量] 补充材料 ${offset + 1}/${total}：${request.doi || request.paperId}`);
    const result = await downloadSupplementsOnly(recorded(request, ledger, entry), backend);
    ledger?.item(entry, result);
    items.push(itemResult(result, offset + 1, request));
  }
  ledger?.close();
  return summary(options.mode ?? "two_phase", batchId, items, {
    content: "supplements",
    ...(ledger ? { runLog: ledger.dir } : {}),
  });
}

async function downloadPerItem(
  searchers: Searchers,
  options: DownloadBatchOptions,
  backend: CarsiBackend | undefined,
  log: (line: string) => void,
  createTiers: (backend?: CarsiBackend) => DownloadTier[],
  pause: (ms: number) => Promise<void>,
): Promise<DownloadBatchResult> {
  const batchId = randomUUID();
  const total = options.items.length;
  const ledger = openLedger("per_item", batchId, options, log);
  const items: DownloadBatchItemResult[] = [];
  let succeeded = 0;
  let failed = 0;
  let away = false;
  for (const [offset, item] of options.items.entries()) {
    const index = offset + 1;
    const request = itemOptions(item, options);
    const entry = runItem(index, request);
    log(`[批量] 第 ${index}/${total} 篇：${request.doi || request.paperId}`);
    const batch = { id: batchId, index, total, done: offset, succeeded, failed };
    const result = await pastHourlyLimit(
      () =>
        downloadBatchItem(
          searchers,
          recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entry),
          createTiers(backend),
          backend,
        ),
      log,
      pause,
    );
    if (result.status === "ok") succeeded += 1;
    else failed += 1;
    if (!away && waitedOutOnUser(result)) {
      away = true;
      log(AWAY_NOTICE);
    }
    const finished = itemResult(result, index, request);
    await supplementsForOpenItem(finished, recorded(request, ledger, entry), backend);
    ledger?.item(entry, finished);
    items.push(finished);
    if (publisherBlocked(result)) log(blockedNotice(request.doi || request.paperId));
  }
  ledger?.close();
  return summary("per_item", batchId, items, {
    content: options.content ?? "main",
    ...(ledger ? { runLog: ledger.dir } : {}),
  });
}

async function downloadTwoPhase(
  searchers: Searchers,
  options: DownloadBatchOptions,
  backend: CarsiBackend | undefined,
  log: (line: string) => void,
  createTiers: (backend?: CarsiBackend) => DownloadTier[],
  mode: "two_phase" | "entitled_only" = "two_phase",
  pause: (ms: number) => Promise<void> = wait,
): Promise<DownloadBatchResult> {
  const batchId = randomUUID();
  const total = options.items.length;
  const ledger = openLedger(mode, batchId, options, log);
  const requests = options.items.map((item) => itemOptions(item, options));
  const entries = requests.map((request, offset) => runItem(offset + 1, request));
  const items: DownloadBatchItemResult[] = new Array(total);
  const pending: number[] = [];

  // Phase 1: open stages for every item; no browser is needed yet.
  if (mode === "entitled_only") {
    for (const [offset, request] of requests.entries()) {
      items[offset] = itemResult({ status: "error", attempts: [] }, offset + 1, request);
      pending.push(offset);
    }
  } else ledger?.phase(`开放来源 ${total} 篇`);
  for (const [offset, request] of mode === "entitled_only" ? [] : requests.entries()) {
    log(`[批量] 开放来源 ${offset + 1}/${total}：${request.doi || request.paperId}`);
    const tiers = createTiers(backend).filter((tier) => tier.stage !== "entitled_access");
    const result = await downloadWithFallback(searchers, recorded(request, ledger, entries[offset]), tiers);
    items[offset] = itemResult(result, offset + 1, request);
    if (result.status !== "ok") pending.push(offset);
    else if (options.content !== "both") ledger?.item(entries[offset], result);
  }

  // Phase 2: entitled access only, for the items still missing; the backend
  // window counts this stretch (k / M).
  const remaining = pending.length;
  log(
    mode === "entitled_only"
      ? `[批量] 跳过开放来源，${remaining} 篇直接进入机构下载`
      : `[批量] 开放来源获取 ${total - remaining}/${total} 篇；` +
          (remaining ? `剩余 ${remaining} 篇进入机构下载` : "无需机构下载"),
  );
  ledger?.phase(`机构下载 ${remaining} 篇`);
  let succeeded = 0;
  let failed = 0;
  let away = false;
  for (const [step, offset] of pending.entries()) {
    const request = requests[offset];
    log(`[批量] 机构下载 ${step + 1}/${remaining}：${request.doi || request.paperId}`);
    const batch = { id: batchId, index: step + 1, total: remaining, done: step, succeeded, failed };
    const result = await pastHourlyLimit(
      () =>
        downloadBatchItem(
          searchers,
          recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entries[offset]),
          createTiers(backend).filter((tier) => tier.stage === "entitled_access"),
          backend,
        ),
      log,
      pause,
    );
    if (result.status === "ok") succeeded += 1;
    else failed += 1;
    if (!away && waitedOutOnUser(result)) {
      away = true;
      log(AWAY_NOTICE);
    }
    const open = items[offset];
    items[offset] = itemResult(
      {
        ...result,
        attempts: [...open.attempts, ...result.attempts],
        ...(result.review ?? open.review ? { review: result.review ?? open.review } : {}),
      },
      offset + 1,
      request,
    );
    ledger?.item(entries[offset], items[offset]);
    if (publisherBlocked(result)) log(blockedNotice(request.doi || request.paperId));
  }

  // Phase 3: supplementary files for the items the open stages already got.
  if (options.content === "both") {
    const open = requests.map((_, offset) => offset).filter((offset) => !pending.includes(offset));
    if (open.length) ledger?.phase(`补充材料 ${open.length} 篇`);
    for (const [step, offset] of open.entries()) {
      log(`[批量] 补充材料 ${step + 1}/${open.length}：${requests[offset].doi || requests[offset].paperId}`);
      await supplementsForOpenItem(items[offset], recorded(requests[offset], ledger, entries[offset]), backend);
      ledger?.item(entries[offset], items[offset]);
    }
  }
  ledger?.close({ entitledAccessItems: remaining });
  return summary(mode, batchId, items, {
    content: options.content ?? "main",
    entitledAccessItems: remaining,
    ...(ledger ? { runLog: ledger.dir } : {}),
  });
}
