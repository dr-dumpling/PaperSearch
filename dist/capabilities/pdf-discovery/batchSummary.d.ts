import type { CarsiBackend, CarsiBatchResults } from "./carsi/index.js";
import type { DownloadBatchResult } from "./batch.js";
import type { DownloadWithFallbackOptions, DownloadWithFallbackResult } from "./types.js";
/**
 * Tell the progress window how the whole batch ended: what was saved, and
 * each failure's class and reason in a few words. Sent once, after every
 * stage (open, institutional, supplementary files); the window is optional,
 * so this never changes the batch result.
 */
export declare function reportBatchResults(result: DownloadBatchResult, backend: CarsiBackend | undefined, startedAt: number, folder: string): Promise<void>;
/** A batch's folder for the window's button: every paper of the batch, not the last one's folder. */
export declare function batchFolder(savePath: string): string;
/**
 * One download outside a batch, run as a batch of one so the progress window
 * ends with the same finished card (its reason when it failed). Reported only
 * when the download reached the backend; an open-access copy opens no window.
 */
export declare function asWindowBatch(options: DownloadWithFallbackOptions & {
    savePath: string;
}, backend: CarsiBackend | undefined, download: (options: DownloadWithFallbackOptions) => Promise<DownloadWithFallbackResult>): Promise<DownloadWithFallbackResult>;
export declare function batchResults(result: DownloadBatchResult, startedAt: number, folder: string): CarsiBatchResults;
//# sourceMappingURL=batchSummary.d.ts.map