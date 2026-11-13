import type { Searchers } from "../../core/searchers.js";
import { type FailureClass } from "../../infrastructure/runlog/failureClass.js";
import type { DownloadTier } from "./DownloadTier.js";
import type { SchoolBackend } from "./school/index.js";
import type { DownloadContent, DownloadBatchPosition, DownloadWithFallbackOptions, DownloadWithFallbackResult } from "./types.js";
export declare const MAX_BATCH_ITEMS = 1000;
/** From this many items the progress window opens at the start, in the open-access stretch. */
export declare const OPEN_PROGRESS_MIN_ITEMS = 5;
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
export declare function downloadBatchItem(searchers: Searchers, options: DownloadWithFallbackOptions & {
    batch: DownloadBatchPosition;
}, tiers: DownloadTier[], backend?: SchoolBackend): Promise<DownloadWithFallbackResult>;
/**
 * Supplementary files only: the entitled-access backend visits the article
 * page for them. An empty completed check is also ok; it is not a failed download,
 * nor is a site without a supplementary-file rule (user, 2026-11-11). Reported to
 * the run ledger through ``request.onStage`` as the "supplements" stage.
 * ``mainPath``: the paper's main text, saved before; once a file is saved it moves
 * into the paper's folder beside them (the returned ``path``).
 */
export declare function downloadSupplementsOnly(request: DownloadWithFallbackOptions, backend: SchoolBackend | undefined, searchers?: Searchers, mainPath?: string): Promise<DownloadWithFallbackResult>;
/**
 * How often a batch waiting for the hourly limit keeps the publisher's session alive:
 * Wiley's institutional session lapsed after about half an hour without a request,
 * and the school's login had expired by then too (Windows, 2026-11-12).
 */
export declare const KEEP_SESSION_EVERY_MS: number;
/** Download a list serially; one batch id ties it to one progress window. */
export declare function downloadBatch(searchers: Searchers, options: DownloadBatchOptions, backend?: SchoolBackend, log?: (line: string) => void, createTiers?: (backend?: SchoolBackend) => DownloadTier[], pause?: (ms: number) => Promise<void>): Promise<DownloadBatchResult>;
//# sourceMappingURL=batch.d.ts.map