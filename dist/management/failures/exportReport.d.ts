import { type FailureQuery } from "./index.js";
export interface ExportReportResult {
    ok: true;
    schemaVersion: 1;
    path: string;
    papers: number;
    files: number;
    bytes: number;
    reviewRequired: true;
    incompletePapers: number;
}
/** Offline backend command: no readiness probe, profile, login or download. */
export declare function exportFailureReport(options: {
    root: string;
    query: FailureQuery;
    output: string;
    version: string;
    command: string;
}): Promise<ExportReportResult>;
//# sourceMappingURL=exportReport.d.ts.map