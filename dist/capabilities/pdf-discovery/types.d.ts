/**
 * Position of one download inside a caller's serial batch. The counts are the
 * batch totals before this item; the backend's progress window uses them to
 * show "k / N" for the whole batch.
 */
export interface DownloadBatchPosition {
    id: string;
    /** 1-based. */
    index: number;
    total: number;
    done: number;
    succeeded: number;
    failed: number;
}
/** What a download fetches: the main text (default), only supplementary files, or both. */
export type DownloadContent = "main" | "supplements" | "both";
/** One supplementary file of an article, as collected by the entitled-access backend. */
export interface SupplementFile {
    /** The link's description on the article page. */
    label: string;
    status: "saved" | "failed" | "skipped";
    /** Saved file, inside the item's save directory. */
    file?: string;
    size?: number;
    /** Code for a failed or skipped file (http_404, html_page, too_large, ...). */
    reason?: string;
}
/** One finished funnel stage, for the local run ledger; never part of tool output. */
export interface DownloadStageRecord {
    stage: string;
    status: "ok" | "error" | "skipped";
    message: string;
    code?: string;
    path?: string;
    /** ISO time the stage started. */
    startedAt: string;
    durationMs: number;
    /** Backend details: driver, publisher, state, record/diagnostic files, identity verdict. */
    trace?: Record<string, unknown>;
}
export interface DownloadWithFallbackOptions {
    /** Internal shared candidates across the two batch phases; not a tool argument. */
    preprintIds?: string[];
    source: string;
    paperId: string;
    doi?: string;
    title?: string;
    savePath?: string;
    /** When false, suppress the optional entitled-access tier. Default is true. */
    useEntitledAccess?: boolean;
    /** When false, skip Sci-Hub and continue to optional entitled access. Default is true. */
    useSciHub?: boolean;
    /** Set when this download is one item of a serial batch. */
    batch?: DownloadBatchPosition;
    /**
     * Set by the batch once an article waited on the user (login, verification)
     * until its time was up: later articles wait on the user only briefly.
     */
    shortUserWait?: boolean;
    /** Called after every stage (run ledger). */
    onStage?: (record: DownloadStageRecord) => void;
    /**
     * Where a download that went fine keeps the backend's record and screenshots: its
     * run's folder (user, 2026-11-10).
     */
    recordsDir?: string;
    /** Where a paper that did not go fine keeps its diagnostics: the run's folder too (user, 2026-11-11). */
    diagnosticsDir?: string;
    /** main (default) / supplements / both; see DownloadContent. */
    content?: DownloadContent;
}
export interface DownloadWithFallbackResult {
    /** Present when all earlier routes failed and an arXiv preprint was saved. */
    version?: "preprint";
    arxivId?: string;
    publishedDoi?: string;
    status: "ok" | "error";
    /** The paper's title and journal as looked up for naming its folder, when known. */
    title?: string;
    journal?: string;
    path?: string;
    /** Present only when the saved full text is not a PDF (e.g. Springer TDM JATS XML). */
    format?: "jats-xml";
    /** Retained file requiring review; never a successful download path. */
    review?: {
        path: string;
        reason: string;
    };
    /** Directory of the local run ledger for this call. */
    runLog?: string;
    /** Supplementary files, when content is "supplements" or "both". */
    supplements?: SupplementFile[];
    attempts: Array<{
        stage: string;
        status: "ok" | "error" | "skipped";
        message: string;
        code?: string;
        /** rate_limited: seconds until this item can be tried again. */
        retryAfterSec?: number;
    }>;
}
//# sourceMappingURL=types.d.ts.map