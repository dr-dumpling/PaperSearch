import type { DownloadBatchItem } from "./batch.js";
/** The content kinds a batch asked for, as the ledger keeps them. */
export type ResumeContent = "main" | "supplements" | "both";
export interface ResumePlan {
    /** The batch gone on with (the first of its chain). */
    runId: string;
    /** Its download folder: the new files go there too. */
    folder: string;
    content: ResumeContent;
    /** Papers not saved: downloaded again with ``content``. */
    retry: DownloadBatchItem[];
    /** Papers saved without all their supplementary files: those only, beside ``mainPath``. */
    files: DownloadBatchItem[];
    /** Papers with nothing missing. */
    complete: number;
}
/**
 * What ``which`` ("latest", or a run id as ``paper-search failures`` names it) left undone;
 * a string saying why there is nothing to go on with otherwise.
 */
export declare function planResume(which: string, env?: Record<string, string | undefined>): ResumePlan | string;
//# sourceMappingURL=resume.d.ts.map