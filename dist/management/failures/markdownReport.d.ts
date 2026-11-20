import { type FailureQuery } from "./index.js";
/**
 * Pages from sites not yet supported (user, 2026-11-16): the download keeps each with its
 * check results in the run's records (<DOI>_markdown-report.json beside
 * <DOI>_markdown-page.html), those another site's rules converted completely and saved too
 * (user, 2026-11-17: one report, saying which rules did). Listed by site here, and exported
 * by the school backend (markdown-report-export) into a ZIP to look over and attach to an
 * issue; nothing is uploaded.
 */
export interface MarkdownSitePage {
    runId: string;
    doi: string;
    title?: string;
    host: string;
    /** The report's path (absolute). */
    report: string;
    /** Converted completely (by another site's rules) and saved. */
    saved: boolean;
    /** Whose rules converted it, or came closest ("Atypon"). */
    rules?: string;
    /** What the closest rules lacked, in the window's words; none when saved. */
    lacks: string[];
}
export interface MarkdownSite {
    host: string;
    papers: number;
    saved: number;
    /** Whose rules its pages went by, most papers first. */
    rules: string[];
    lacks: Record<string, number>;
}
/** The pages kept in the runs the query names (the latest by default). */
export declare function markdownPages(root: string, query?: FailureQuery): MarkdownSitePage[];
/** By site, most papers first, with whose rules they went by and what the unsaved lacked. */
export declare function markdownSites(pages: MarkdownSitePage[]): MarkdownSite[];
export declare function renderMarkdownSitesText(sites: MarkdownSite[]): string;
export interface MarkdownReportResult {
    ok: true;
    path: string;
    name: string;
    papers: number;
    sites: string[];
    bytes: number;
    /** GitHub's new issue page with the Markdown site template filled in (no DOI or title). */
    issueUrl: string;
}
/** The ZIP: at ``output`` (a new .zip) or as PaperSearch-Markdown报告-<date>.zip in ``folder``. */
export declare function exportMarkdownReport(options: {
    pages: MarkdownSitePage[];
    folder: string;
    output?: string;
    version: string;
    command: string;
}): Promise<MarkdownReportResult>;
//# sourceMappingURL=markdownReport.d.ts.map