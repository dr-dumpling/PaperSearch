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
/**
 * An offline backend command fed ``input`` on stdin: its JSON reply ({ok: false, error} when
 * it failed). ``what`` names the export in the messages ("失败记录导出"); ``outdated``, what
 * to say when a backend gave no reply (one without the command).
 */
export declare function runBackendExport(command: string, args: string[], input: string, what: string, outdated: string): Promise<Record<string, unknown>>;
//# sourceMappingURL=exportReport.d.ts.map