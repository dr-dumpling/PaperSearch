import type { Searchers } from "../../../core/searchers.js";
import { type FailureClass } from "../../../infrastructure/runlog/failureClass.js";
import type { DownloadTier } from "../content/pdf/DownloadTier.js";
import type { SchoolBackend } from "../../../infrastructure/school/index.js";
import { type BatchFolderRecord } from "./batchFolder.js";
import type { DownloadContent, DownloadBatchPosition, DownloadWithFallbackOptions, DownloadWithFallbackResult } from "../types.js";
/** From this many items the progress window opens at the start, in the open-access stretch. */
export declare const OPEN_PROGRESS_MIN_ITEMS = 5;
export interface DownloadBatchItem {
    source?: string;
    paperId?: string;
    doi?: string;
    title?: string;
    /** Overrides the batch savePath for this item. */
    savePath?: string;
    /** Going on with a batch (resume.ts): the paper's main text saved earlier, its files go beside it. */
    mainPath?: string;
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
    /** main (default) / supplements / both / markdown (see DownloadContent). */
    content?: DownloadContent;
    /** Each paper's Markdown too (see ../content/markdown/step.ts); always for content "markdown". */
    fulltext?: boolean;
    /**
     * Another saved school for this batch alone, as the user asked (``paper-search-school
     * schools``); the configured one stays (user, 2026-11-17).
     */
    school?: string;
    /** The batch this one goes on with (resume.ts): its run ledger names it. */
    resumeOf?: string;
    /** The records kept in the batch's folder (batchFolder.ts), set by downloadBatch. */
    folderRecord?: BatchFolderRecord;
}
export interface DownloadBatchItemResult extends Omit<DownloadWithFallbackResult, "status"> {
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
    /** Of the failed ones, those the user's stop left undone (not tried, or cut short). */
    stoppedItems?: number;
    /** Directory of the local run ledger (run.json, items.jsonl, timeline.log). */
    runLog?: string;
    /** Failed institutional downloads by class (ADR 0012). */
    failureClasses?: Partial<Record<FailureClass, number>>;
    /** two_phase: the user pressed 终止 in the window before every paper was done. */
    stopped?: boolean;
    items: DownloadBatchItemResult[];
}
/**
 * One item of a serial batch. When the item reaches the entitled-access
 * backend, the backend records it in its progress window itself; items that
 * finish earlier (open access, Sci-Hub) and the last item are reported with
 * the batch totals so the window always shows "k / N" for the whole batch.
 */
export declare function downloadBatchItem(searchers: Searchers, options: DownloadWithFallbackOptions & {
    batch: DownloadBatchPosition;
}, tiers: DownloadTier[], backend?: SchoolBackend): Promise<DownloadWithFallbackResult>;
/**
 * How long a publisher's papers wait after its site blocked one of them (被网站拦截: its human verification not passed,
 * its block page): the batch goes on with the other publishers meanwhile, then tries them once more (user, 2026-11-23).
 * Ten minutes: JAMA's first block in the publisher sweep had cleared within five (the re-check interval the user set for
 * a blocked journal, 2026-11-16), its second held for the 47 minutes the batch went on hitting it; with one retry only,
 * twice that interval. Shorter than the half hour after which a publisher's school session lapsed unused (Wiley,
 * 2026-11-12), so nothing is loaded from the blocking site to keep it.
 */
export declare const BLOCKED_PAUSE_MS: number;
/**
 * Without 失败后自动重试: a publisher's papers its site blocks in a row before its others are given up for the batch
 * (user, 2026-11-24: Wiley's one verification not passed, paper 85, gave its other 40 up untried). Each one blocked
 * fails on its own; one not blocked starts the count again.
 */
export declare const BLOCKED_IN_ROW = 3;
/**
 * How often a batch waiting for the hourly limit keeps the publisher's session alive:
 * Wiley's institutional session lapsed after about half an hour without a request,
 * and the school's login had expired by then too (Windows, 2026-11-12).
 */
export declare const KEEP_SESSION_EVERY_MS: number;
/**
 * How often a batch waiting for the hourly limit asks the backend how long it still waits: with
 * the settings window's 马上生效 on, a limit raised there, or none, goes on at once (the user,
 * 2026-11-19). Each ask reads the backend's settings and count only.
 */
export declare const HOURLY_RECHECK_EVERY_MS = 10000;
/** The user pressed 终止 in the batch's window (papers not reached, or still paused, show it). */
export declare function batchStopped(result: DownloadBatchResult): boolean;
/** Download a list serially; one batch id ties it to one progress window. */
export declare function downloadBatch(searchers: Searchers, options: DownloadBatchOptions, backend?: SchoolBackend, log?: (line: string) => void, createTiers?: (backend?: SchoolBackend) => DownloadTier[], pause?: (ms: number) => Promise<void>, online?: () => Promise<boolean>, now?: () => number): Promise<DownloadBatchResult>;
//# sourceMappingURL=batch.d.ts.map