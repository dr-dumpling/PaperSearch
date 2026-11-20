import type { DownloadBatchItem, DownloadBatchMode } from "./batch.js";
import type { SupplementFile } from "../types.js";
/** The content kinds a batch asked for, as the ledger keeps them. */
export type ResumeContent = "main" | "supplements" | "both" | "markdown";
export interface ResumePlan {
    /** The batch gone on with (the first of its chain). */
    runId: string;
    /** Its download folder: the new files go there too. */
    folder: string;
    content: ResumeContent;
    /** Each paper's Markdown too (always for content "markdown"). */
    fulltext: boolean;
    /** The saved school the batch's latest run used, as the user asked: the same again. */
    school?: string;
    /** How the batch's latest run went (entitled_only: through the school alone, its Markdown too): the same again. */
    mode?: DownloadBatchMode;
    /** Papers not saved: downloaded again with ``content``. */
    retry: DownloadBatchItem[];
    /** Of ``retry``, the papers of the batch's list no run recorded (a batch killed outright). */
    unreached?: number;
    /** Papers saved without all their supplementary files: those only, beside ``mainPath``. */
    files: DownloadBatchItem[];
    /** Papers saved without their Markdown: it only, beside ``mainPath`` (some are in ``files`` too). */
    markdown: DownloadBatchItem[];
    /** Papers with nothing missing. */
    complete: number;
}
export interface LedgerPaper {
    index: number;
    doi: string;
    paperId: string;
    title: string;
    status: string;
    path: string;
    supplements?: SupplementFile[];
    /** How its Markdown went: its run's last "markdown" stage (the site it named, when one). */
    markdown?: {
        status: string;
        code?: string;
        host?: string;
        untried?: boolean;
        possiblyMissing?: {
            figures?: number;
            references?: number;
            text?: number;
            tables?: boolean;
        };
    };
    /** Its PDF came from the institutional visit, which also checks the supplementary files. */
    byVisit?: boolean;
    /** The stage that saved its PDF (unpaywall, entitled_access, …). */
    source?: string;
    /** A paper not saved: the code of its last failed stage. */
    reason?: string;
    /** Its article.md, when its Markdown was saved. */
    markdownFile?: string;
}
/**
 * The latest record of each paper over the runs in ``dirs`` (oldest first). A saved paper is
 * gone on with only for its files or Markdown: those runs change what they got, the saved PDF
 * stands.
 */
export declare function latestPapers(dirs: string[]): Map<string, LedgerPaper>;
/**
 * What ``which`` ("latest", or a run id as ``paper-search failures`` names it) left undone;
 * a string saying why there is nothing to go on with otherwise.
 */
/**
 * ``markdownAgain: "possibly_short"``: the Markdown saved with a note of what it may lack
 * (possiblyMissing) is made again too, e.g. after the rules were fixed (user, 2026-11-18: 94
 * Cell papers saved before the tables' fix); a whole new package replaces it in the paper's folder.
 */
export declare function planResume(which: string, env?: Record<string, string | undefined>, options?: {
    markdownAgain?: "possibly_short";
}): ResumePlan | string;
//# sourceMappingURL=resume.d.ts.map