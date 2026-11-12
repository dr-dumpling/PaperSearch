import { resolveDownloadPath } from "../../config/ConfigService.js";
import { dirname } from "node:path";
import { createOutputLayout, inPaperDir, isInside, lookupOutputMetadata, moveIntoPaperDir, organizeFiles, removeWorkFolder } from "./outputLayout.js";
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
import { schoolShortReason } from "./school/index.js";
import type { SchoolBackend } from "./school/index.js";
import { fetchSupplementsOnly } from "./tiers/entitledAccess.js";
import { batchPaper, reportBatchResults, supplementShortfall } from "./batchSummary.js";
import { PaperList } from "./batchPapers.js";
import type {
  DownloadContent,
  DownloadBatchPosition,
  DownloadWithFallbackOptions,
  DownloadWithFallbackResult,
} from "./types.js";

export const MAX_BATCH_ITEMS = 1000;
/** From this many items the progress window opens at the start, in the open-access stretch. */
export const OPEN_PROGRESS_MIN_ITEMS = 5;
/** Every source that needs no browser: open access, publisher APIs, Sci-Hub when on (the guide's 开放下载). */
const OPEN_CHANNEL = "开放下载";

export interface DownloadBatchItem {
  source?: string;
  paperId?: string;
  doi?: string;
  title?: string;
  /** Overrides the batch savePath for this item. */
  savePath?: string;
}

/**
 * two_phase (default): every item first tries the open stages; the items they
 * miss go through entitled access one after another, starting with the first
 * one missed while the open stages go on with the rest (the browser and the
 * school's login come within seconds, not after the whole open stretch).
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
  backend?: SchoolBackend,
): Promise<DownloadWithFallbackResult> {
  const result = await downloadWithFallback(searchers, options, tiers);
  await reportBatchItem(options, result, backend);
  return result;
}

async function reportBatchItem(
  options: DownloadWithFallbackOptions & { batch: DownloadBatchPosition },
  result: DownloadWithFallbackResult,
  backend?: SchoolBackend,
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
    preprintIds: [],
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
  const files = await fetchSupplementsOnly(backend, {
    identifier: request.doi || request.paperId,
    outputDir: layout.paperDir,
    diagnosticsDir: layout.workDiagnosticsDir,
    ...(request.batch ? { batch: request.batch } : {}),
    ...(request.shortUserWait ? { userWait: "short" as const } : {}),
  }, value => { trace = value; });
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
  };
}

/** content "both": supplementary files for an item whose main text came from an open stage. */
async function supplementsForOpenItem(
  result: DownloadBatchItemResult,
  request: DownloadWithFallbackOptions,
  backend: SchoolBackend | undefined,
  searchers: Searchers,
): Promise<DownloadWithFallbackResult | undefined> {
  if (request.content !== "both" || result.status !== "ok" || result.supplements) return;
  const extra = await downloadSupplementsOnly({ ...request, ...(result.publishedDoi ? { doi: result.publishedDoi } : {}) }, backend, searchers, result.path && !result.version ? result.path : undefined);
  if (extra.supplements) result.supplements = extra.supplements;
  if (extra.path) result.path = extra.path;  // moved into its folder beside the files
  return extra;
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
/** The user pressed "终止任务" in the progress window: the batch ends after this item. */
function stoppedByUser(result: DownloadWithFallbackResult): boolean {
  return result.attempts.some((attempt) => attempt.code === "batch_stopped") ||
    !!result.supplements?.some((file) => file.reason === "batch_stopped");
}

const STOP_NOTICE = "[批量] 已在进度窗口终止任务，剩下的篇目不再下载";

/** The attempt recorded for an item the batch did not reach because the user stopped it. */
function notReached(): DownloadWithFallbackResult["attempts"][number] {
  return { stage: "entitled_access", status: "skipped", message: "已终止任务，未下载", code: "batch_stopped" };
}

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
  return ledger
    ? { ...request, onStage: (record) => ledger.stage(item, record), recordsDir: ledger.records, diagnosticsDir: ledger.diagnostics }
    : request;
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
  backend?: SchoolBackend,
  log: (line: string) => void = (line) => process.stderr.write(`${line}\n`),
  createTiers: (backend?: SchoolBackend) => DownloadTier[] = createDefaultDownloadTiers,
  pause: (ms: number) => Promise<void> = wait,
): Promise<DownloadBatchResult> {
  options = { ...options, savePath: resolveDownloadPath(options.savePath) };
  const startedAt = Date.now();
  const run = async (backend?: SchoolBackend) => {
    const result = await (options.content === "supplements"
      ? downloadSupplementsBatch(options, backend, log, searchers)
      : options.mode === "per_item"
        ? downloadPerItem(searchers, options, backend, log, createTiers, pause)
        : downloadTwoPhase(searchers, options, backend, log, createTiers,
            options.mode === "entitled_only" ? "entitled_only" : "two_phase", pause));
    await reportBatchResults(result, backend, startedAt, options.savePath!);
    return result;
  };
  const result = await (backend?.withBatchSession ? backend.withBatchSession(run) : run(backend));
  const byClass = Object.entries(result.failureClasses ?? {})
    .map(([failureClass, count]) => `${FAILURE_CLASS_NAMES[failureClass as FailureClass]} ${count}`)
    .join("、");
  // Main text and supplementary files apart: "附录未下全 2 篇：网站人机验证拦截 2".
  const shortfalls = new Map<string, number>();
  for (const item of result.content === "both" ? result.items : []) {
    const code = supplementShortfall(item);
    if (!code) continue;
    const reason = schoolShortReason(code, "附录没下载成功");
    shortfalls.set(reason, (shortfalls.get(reason) ?? 0) + 1);
  }
  const missed = [...shortfalls.values()].reduce((sum, n) => sum + n, 0);
  log(`[批量] 完成：成功 ${result.succeeded}，失败 ${result.failed}，共 ${result.total} 篇` +
    (byClass ? `。失败分类：${byClass}；详情：paper-search failures --format text` : "") +
    (missed ? `。附录未下全 ${missed} 篇：${[...shortfalls].map(([reason, n]) => `${reason} ${n}`).join("、")}` : ""));
  return result;
}

/** content "supplements": every item, one after another, supplementary files only. */
async function downloadSupplementsBatch(
  options: DownloadBatchOptions,
  backend: SchoolBackend | undefined,
  log: (line: string) => void,
  searchers: Searchers,
): Promise<DownloadBatchResult> {
  const batchId = randomUUID();
  const total = options.items.length;
  const ledger = openLedger("supplements", batchId, options, log);
  const items: DownloadBatchItemResult[] = [];
  let succeeded = 0;
  let failed = 0;
  for (const [offset, item] of options.items.entries()) {
    const batch = { id: batchId, index: offset + 1, total, done: offset, succeeded, failed };
    const request = { ...itemOptions(item, options), batch };
    const entry = runItem(offset + 1, request);
    log(`[批量] 补充材料 ${offset + 1}/${total}：${request.doi || request.paperId}`);
    const result = await downloadSupplementsOnly(recorded(request, ledger, entry), backend, searchers);
    await reportBatchItem(request, result, backend);
    if (result.status === "ok") succeeded += 1;
    else failed += 1;
    ledger?.item(entry, result);
    items.push(itemResult(result, offset + 1, request));
    if (stoppedByUser(result)) {
      for (const [rest, item] of options.items.entries()) {
        if (rest <= offset) continue;
        const request = itemOptions(item, options);
        const skipped = itemResult({ status: "error", attempts: [notReached()],
          supplements: [{ status: "skipped", label: "", reason: "batch_stopped" }] }, rest + 1, request);
        items.push(skipped);
        ledger?.item(runItem(rest + 1, request), skipped);
      }
      log(STOP_NOTICE);
      break;
    }
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
  backend: SchoolBackend | undefined,
  log: (line: string) => void,
  createTiers: (backend?: SchoolBackend) => DownloadTier[],
  pause: (ms: number) => Promise<void>,
): Promise<DownloadBatchResult> {
  const batchId = randomUUID();
  const total = options.items.length;
  const ledger = openLedger("per_item", batchId, options, log);
  const content = options.content ?? "main";
  const papers = new PaperList(backend, batchId, options.savePath!,
    options.items.map((item) => batchPaper(itemOptions(item, options), undefined, "open", content)));
  await papers.send();
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
        downloadWithFallback(
          searchers,
          recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entry),
          createTiers(backend),
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
    if (!stoppedByUser(result)) await supplementsForOpenItem(finished, recorded({ ...request, batch }, ledger, entry), backend, searchers);
    await reportBatchItem({ ...request, batch }, finished, backend);
    ledger?.item(entry, finished);
    items.push(finished);
    papers.set(offset, batchPaper(request, finished, undefined, content));
    if (publisherBlocked(result)) log(blockedNotice(request.doi || request.paperId));
    if (stoppedByUser(finished)) {
      for (const [rest, restItem] of options.items.entries()) {
        if (rest <= offset) continue;
        const restRequest = itemOptions(restItem, options);
        const restFinished = itemResult({ status: "error", attempts: [notReached()] }, rest + 1, restRequest);
        ledger?.item(runItem(rest + 1, restRequest), restFinished);
        items.push(restFinished);
        papers.set(rest, batchPaper(restRequest, restFinished, undefined, content));
      }
      log(STOP_NOTICE);
      break;
    }
    await papers.send();
  }
  await papers.send(true);
  ledger?.close();
  return summary("per_item", batchId, items, {
    content: options.content ?? "main",
    ...(ledger ? { runLog: ledger.dir } : {}),
  });
}

/** An item a lane could not finish: the error stands as its result; the other lane goes on. */
function laneError(stage: string, error: unknown): DownloadWithFallbackResult {
  return {
    status: "error",
    attempts: [{ stage, status: "error", code: "stage_exception",
      message: error instanceof Error ? `${error.name}: ${error.message}` : String(error) }],
  };
}

async function downloadTwoPhase(
  searchers: Searchers,
  options: DownloadBatchOptions,
  backend: SchoolBackend | undefined,
  log: (line: string) => void,
  createTiers: (backend?: SchoolBackend) => DownloadTier[],
  mode: "two_phase" | "entitled_only" = "two_phase",
  pause: (ms: number) => Promise<void> = wait,
): Promise<DownloadBatchResult> {
  const batchId = randomUUID();
  const total = options.items.length;
  const ledger = openLedger(mode, batchId, options, log);
  const requests = options.items.map((item) => itemOptions(item, options));
  const entries = requests.map((request, offset) => runItem(offset + 1, request));
  const results: Array<DownloadBatchItemResult | undefined> = new Array(total);
  const content = options.content ?? "main";
  const papers = new PaperList(backend, batchId, options.savePath!, requests.map((request) =>
    batchPaper(request, undefined, mode === "entitled_only" ? "school" : "open", content)));
  const recordedOffsets = new Set<number>();
  /** An item goes to the run record once, when it has settled. */
  const record = (offset: number) => {
    if (recordedOffsets.has(offset)) return;
    recordedOffsets.add(offset);
    ledger?.item(entries[offset], results[offset]!);
  };
  const id = (offset: number) => requests[offset].doi || requests[offset].paperId;

  // Two lanes at once. The open lane checks every item in turn, needing no
  // browser; each item it misses joins the queue of the entitled lane, which
  // starts on the first one at once and takes them one after another (one
  // browser, one school login). A large batch shows the window from the start:
  // one count for the whole batch, where an item counts once its result is
  // settled (with supplementary files too, an open-access item settles only
  // after its files, after both lanes).
  const settlesInOpen = options.content !== "both";
  const openProgress = mode !== "entitled_only" && total >= OPEN_PROGRESS_MIN_ITEMS && !!backend?.reportBatchProgress;
  const missed: number[] = [];
  const queue: number[] = [];
  let openRunning = mode !== "entitled_only";
  let checked = 0;
  let openFound = 0;
  let succeeded = 0;
  let failed = 0;
  /** Of the entitled lane's 成功: arXiv copies, open ones (as the finished card counts them). */
  let preprints = 0;
  let away = false;
  let stopped = false;
  let wake: (() => void) | undefined;
  const notify = () => {
    const resume = wake;
    wake = undefined;
    resume?.();
  };
  const settledOk = () => (settlesInOpen ? openFound : 0) + succeeded;

  // The window's lines while the lanes run, one report after another so that
  // the counts never go back. Beside a running download only the counts and
  // the lanes lines change (a backend that cannot do that gets none of these).
  // One line in the window: the papers each lane got, which add up to its 成功
  // (失败 and 剩余 are the batch's alone; a lane's "left" read as all going to
  // the school, the user's review 2026-11-10).
  const lanes = () => `${OPEN_CHANNEL} ${openFound + preprints} 篇 · 机构下载 ${succeeded - preprints} 篇`;
  let reports: Promise<unknown> = Promise.resolve();
  const reportProgress = (current: string) => {
    if (!openProgress) return reports;
    const update = {
      id: batchId, total, done: settledOk() + failed, succeeded: settledOk(), failed, current, finished: false,
      ...(openRunning ? { phase: `${OPEN_CHANNEL}：已查 ${checked}/${total} 篇，找到 ${openFound} 篇`, channel: OPEN_CHANNEL } : {}),
      ...(missed.length ? { lanes: lanes() } : {}),
    };
    reports = reports.then(() => backend!.reportBatchProgress!(update)).catch(() => false);
    return reports;
  };
  // The window's lists, queued behind the progress reports in the order things happened.
  const sendPapers = (last = false) => {
    reports = reports.then(() => papers.send(last));
    return reports;
  };
  const settle = (offset: number, waiting?: "school") =>
    papers.set(offset, batchPaper(requests[offset], results[offset], waiting, content));

  const openLane = async () => {
    try {
      for (const [offset, request] of requests.entries()) {
        if (stopped) break;
        log(`[批量] 开放来源 ${offset + 1}/${total}：${id(offset)}`);
        const tiers = createTiers(backend).filter((tier) => tier.stage !== "entitled_access" && tier.stage !== "preprint");
        let result: DownloadWithFallbackResult;
        try {
          result = await downloadWithFallback(searchers, recorded(request, ledger, entries[offset]), tiers);
        } catch (error) {
          result = laneError("open_access", error);
          log(`[批量] 开放来源出错（${id(offset)}）：${result.attempts[0].message}；这一篇转机构下载`);
        }
        results[offset] = itemResult(result, offset + 1, request);
        checked = offset + 1;
        settle(offset, result.status === "ok" ? undefined : "school");
        if (result.status === "ok") {
          openFound += 1;
          if (settlesInOpen) record(offset);
        } else {
          if (!missed.length) {
            log(`[批量] 开放来源没有找到 ${id(offset)}，机构下载同时开始`);
            ledger?.phase("机构下载开始，开放来源同时进行");
          }
          missed.push(offset);
          queue.push(offset);
          notify();
        }
        await reportProgress(id(offset));
        await sendPapers();
      }
    } finally {
      openRunning = false;
      notify();
    }
    if (!stopped) {
      log(`[批量] 开放来源查完：获取 ${openFound}/${total} 篇；` +
        (missed.length ? `${missed.length} 篇转机构下载` : "无需机构下载"));
      ledger?.phase(`开放来源查完：${missed.length} 篇转机构下载`);
    }
  };

  const entitledLane = async () => {
    for (;;) {
      while (!queue.length && openRunning && !stopped) await new Promise<void>((resume) => { wake = resume; });
      const offset = stopped ? undefined : queue.shift();
      if (offset === undefined) return;
      const request = requests[offset];
      const step = succeeded + failed + 1;
      log(openRunning
        ? `[批量] 机构下载第 ${step} 篇（开放来源还在查）：${id(offset)}`
        : `[批量] 机构下载 ${step}/${missed.length}：${id(offset)}`);
      const done = settledOk() + failed;
      const batch = { id: batchId, index: done + 1, total, done, succeeded: settledOk(), failed };
      let result: DownloadWithFallbackResult;
      try {
        result = await pastHourlyLimit(
          () =>
            downloadBatchItem(
              searchers,
              recorded({ ...request, batch, ...(away ? { shortUserWait: true } : {}) }, ledger, entries[offset]),
              createTiers(backend).filter((tier) => tier.stage === "entitled_access" || mode !== "entitled_only" && tier.stage === "preprint"),
              backend,
            ),
          log,
          pause,
        );
      } catch (error) {
        result = laneError("entitled_access", error);
        log(`[批量] 机构下载出错（${id(offset)}）：${result.attempts[0].message}`);
      }
      if (result.status === "ok") succeeded += 1;
      else failed += 1;
      if (result.status === "ok" && result.version === "preprint") preprints += 1;
      if (!away && waitedOutOnUser(result)) {
        away = true;
        log(AWAY_NOTICE);
      }
      const open = results[offset]!;
      results[offset] = itemResult(
        {
          ...result,
          attempts: [...open.attempts, ...result.attempts],
          ...(result.review ?? open.review ? { review: result.review ?? open.review } : {}),
        },
        offset + 1,
        request,
      );
      record(offset);
      settle(offset);
      if (publisherBlocked(result)) log(blockedNotice(id(offset)));
      if (stoppedByUser(result)) {
        stopped = true;
        return;
      }
      // More to come: the lanes line goes on (after the last item the window has its end).
      if (openRunning || queue.length) await reportProgress("");
      await sendPapers();
    }
  };

  if (mode === "entitled_only") {
    for (const [offset, request] of requests.entries()) {
      results[offset] = itemResult({ status: "error", attempts: [] }, offset + 1, request);
      missed.push(offset);
      queue.push(offset);
    }
    log(`[批量] 跳过开放来源，${total} 篇直接进入机构下载`);
    ledger?.phase(`机构下载 ${total} 篇`);
  } else ledger?.phase(`开放来源 ${total} 篇`);
  void sendPapers();
  await Promise.all([mode === "entitled_only" ? undefined : openLane(), entitledLane()]);
  await reports;

  // Stopped in the window: the items neither lane reached end as not downloaded.
  if (stopped) {
    for (const [offset, request] of requests.entries()) {
      const item = results[offset];
      if (!item) results[offset] = itemResult({ status: "error", attempts: [notReached()] }, offset + 1, request);
      else if (queue.includes(offset)) {
        results[offset] = itemResult({ ...item, status: "error", attempts: [...item.attempts, notReached()] }, offset + 1, request);
      } else if (!recordedOffsets.has(offset) && item.status === "ok") {
        item.supplements = [{ status: "skipped", label: "", reason: "batch_stopped" }];
      }
      record(offset);
    }
    log(STOP_NOTICE);
  }
  const items = results as DownloadBatchItemResult[];
  const remaining = missed.length;

  // Then supplementary files for the items the open stages already got.
  if (options.content === "both" && !stopped) {
    const open = requests.map((_, offset) => offset).filter((offset) => !missed.includes(offset));
    if (open.length) ledger?.phase(`补充材料 ${open.length} 篇`);
    let supplementsSucceeded = 0;
    let supplementsFailed = 0;
    for (const [step, offset] of open.entries()) {
      log(`[批量] 补充材料 ${step + 1}/${open.length}：${id(offset)}`);
      // Every item of the entitled lane has settled; these come after them.
      const batch = { id: batchId, index: remaining + step + 1, total, done: remaining + step,
        succeeded: succeeded + supplementsSucceeded, failed: failed + supplementsFailed };
      const request = { ...requests[offset], batch };
      const extra = await supplementsForOpenItem(items[offset], recorded(request, ledger, entries[offset]), backend, searchers);
      if (extra) {
        await reportBatchItem(request, extra, backend);
        if (extra.status === "ok") supplementsSucceeded += 1;
        else supplementsFailed += 1;
      }
      record(offset);
      // The window's 失败 list shows a missing supplementary file as it happens (user, 2026-11-11).
      settle(offset);
      await sendPapers();
      if (stoppedByUser(items[offset])) {
        for (const rest of open.slice(step + 1)) {
          items[rest].supplements = [{ status: "skipped", label: "", reason: "batch_stopped" }];
          record(rest);
        }
        log(STOP_NOTICE);
        break;
      }
    }
  }
  // Every paper as it ended, before the window's finished card.
  requests.forEach((_, offset) => settle(offset));
  await sendPapers(true);
  ledger?.close({ entitledAccessItems: remaining });
  return summary(mode, batchId, items, {
    content: options.content ?? "main",
    entitledAccessItems: remaining,
    ...(ledger ? { runLog: ledger.dir } : {}),
  });
}
