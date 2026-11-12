import type { SchoolBackend, SchoolBatchPaper, SchoolBatchResults } from "./school/index.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "./batch.js";
import type { DownloadWithFallbackOptions, DownloadWithFallbackResult } from "./types.js";
/**
 * The reason a paper whose main text was saved still lacks supplementary files:
 * its first file not saved, a real failure before "no rule for this site".
 * A paper without its main text is told by its main text's reason instead.
 */
export declare function supplementShortfall(item: DownloadBatchItemResult): string | undefined;
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
export declare function batchPaper(request: DownloadWithFallbackOptions, item: DownloadBatchItemResult | undefined, waiting: "open" | "school" | undefined, content: DownloadBatchResult["content"]): Omit<SchoolBatchPaper, "index">;
//# sourceMappingURL=batchSummary.d.ts.map