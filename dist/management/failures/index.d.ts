import { type FailureClass } from "../../infrastructure/runlog/failureClass.js";
/**
 * Failure summary from the run ledgers (ADR 0012): every failed institutional
 * download by class, publisher, site and code, with the evidence for "no
 * access" and, for each unexplained failure, where it stopped and its
 * diagnostic file. Run after a batch; the unexplained ones are what to look into.
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
    /** Only present for a supplementary-file failure. */
    part?: "supplements";
}
export interface FailureGroup {
    failureClass: FailureClass;
    publisher: string;
    site: string;
    code: string;
    count: number;
    /** no_access: the evidence of the first item. */
    evidence?: string;
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
}
export interface ExportFailure extends FailureItem {
    publisher: string;
    site: string;
    code: string;
    failureClass: FailureClass;
    record?: string;
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
export declare function renderFailuresText(summary: FailureSummary, options?: {
    all?: boolean;
}): string;
//# sourceMappingURL=index.d.ts.map