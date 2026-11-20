import type { SchoolBackend, SchoolBatchPaper, SchoolBatchResults } from "../../../infrastructure/school/index.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "./batch.js";
import type { DownloadWithFallbackOptions, DownloadWithFallbackResult } from "../types.js";
/** Not saved because the user stopped the batch: not a failure of the paper (2026-11-16). */
export declare function stoppedItem(item: DownloadBatchItemResult): boolean;
/**
 * Tell the progress window how the whole batch ended: what was saved, and
 * each failure's class and reason in a few words. Sent once, after every
 * stage (open, institutional, supplementary files); the window is optional,
 * so this never changes the batch result.
 */
export declare function reportBatchResults(result: DownloadBatchResult, backend: SchoolBackend | undefined, startedAt: number, folder: string): Promise<void>;
/**
 * One download outside a batch, run as a batch of one so the progress window
 * ends with the same finished card (its reason when it failed). Reported only
 * when the download reached the backend; an open-access copy opens no window.
 */
export declare function asWindowBatch(options: DownloadWithFallbackOptions & {
    savePath: string;
}, backend: SchoolBackend | undefined, download: (options: DownloadWithFallbackOptions) => Promise<DownloadWithFallbackResult>): Promise<DownloadWithFallbackResult>;
export declare function batchResults(result: DownloadBatchResult, startedAt: number, folder: string): SchoolBatchResults;
/**
 * A paper for the window's lists (成功, 失败, 剩余): waiting in a lane, or its
 * result as the finished card tells it (the way it came, or why it failed).
 */
export declare function batchPaper(request: DownloadWithFallbackOptions, item: DownloadBatchItemResult | undefined, waiting: "open" | "school" | undefined, content: DownloadBatchResult["content"], mainPath?: string): Omit<SchoolBatchPaper, "index">;
/** The failure's class (ADR 0012) and its reason in a few words, as the lists and the end line say it. */
export declare function failure(item: DownloadBatchItemResult, content: DownloadBatchResult["content"]): Pick<SchoolBatchResults["failures"][number], "cls" | "reason">;
//# sourceMappingURL=batchSummary.d.ts.map