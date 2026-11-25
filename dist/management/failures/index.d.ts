import { type FailureClass } from "../../infrastructure/runlog/failureClass.js";
/**
 * Failure summary from the run ledgers (ADR 0012): every failed institutional
 * download by class, publisher, site and code, with the evidence for "no
 * access" and, for each failure PaperSearch is to look into (unexplained, a site not
 * supported yet), where it stopped, its diagnostic file and its screenshots. Run
 * after a batch; those are what to look into.
 */
export interface FailureQuery {
    /** A run id, or "latest" (the default when nothing else is given). */
    run?: string;
    /** Runs started on or after this day (YYYY-MM-DD). */
    since?: string;
    /** The last N runs. */
    runs?: number;
    doi?: string;
}
export interface FailureItem {
    doi: string;
    runId: string;
    evidence?: string;
    stoppedAt?: string;
    diagnostic?: string;
    /** The pages the backend kept as pictures when the item failed (the diagnostic's ``screenshots``). */
    screenshots?: string[];
    /** Only present for a supplementary-file failure. */
    part?: "supplements";
}
export interface FailureGroup {
    failureClass: FailureClass;
    publisher: string;
    site: string;
    code: string;
    /** The kind of verification that stopped these papers (a key of CHALLENGE_TYPE_LABELS), when recorded. */
    challengeType?: string;
    count: number;
    /** no_access: the evidence of the first item. */
    evidence?: string;
    items: FailureItem[];
}
/**
 * Papers saved (the batch counts them succeeded) with some supplementary files missing: not
 * failures, told apart as the batch's last line does ("附录未下全"), each reason phrased as the
 * window's list phrases it (附录没下载成功 for a code without a phrasing of its own).
 */
export interface SupplementShortfallGroup {
    failureClass: FailureClass;
    publisher: string;
    site: string;
    code: string;
    reason: string;
    count: number;
    items: FailureItem[];
}
export interface FailureSummary {
    root: string;
    runs: string[];
    /** Failed items whose institutional download ran and failed. */
    failed: number;
    /** Failed items that never reached the institutional download. */
    notAttempted: number;
    classes: Record<FailureClass, number>;
    groups: FailureGroup[];
    /** Papers saved without all their supplementary files (not in ``failed``). */
    supplementsMissing: number;
    supplementGroups: SupplementShortfallGroup[];
}
export interface ExportFailure extends FailureItem {
    publisher: string;
    site: string;
    code: string;
    /** The kind of the last verification page the paper waited on (trace.challengeType), when recorded. */
    challengeType?: string;
    failureClass: FailureClass;
    record?: string;
    /** part "supplements": the paper itself was saved (the batch counts it succeeded). */
    paperSaved?: true;
    detail: Record<string, unknown>;
    outcome: Record<string, unknown>;
}
/** One entry per failed paper, including a saved main text with incomplete attachments. */
export declare function selectFailures(root: string, query?: FailureQuery, options?: {
    forExport?: boolean;
}): {
    runs: string[];
    papers: ExportFailure[];
    notAttempted: number;
};
export declare function summarizeFailures(root: string, query?: FailureQuery): FailureSummary;
/** Run directories are named <yyyymmdd>-<hhmmss>-<id>, so names sort by start time. */
export declare function selectRuns(root: string, query: FailureQuery): string[];
export declare function readItems(file: string): Array<Record<string, unknown>>;
export declare function renderFailuresText(summary: FailureSummary, options?: {
    all?: boolean;
}): string;
//# sourceMappingURL=index.d.ts.map