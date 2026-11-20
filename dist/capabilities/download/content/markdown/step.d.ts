import type { Searchers } from "../../../../core/searchers.js";
import { type NetworkWatch } from "../../batch/networkLoss.js";
import type { CapturedFulltextPage, DownloadWithFallbackOptions, DownloadWithFallbackResult, FulltextSummary } from "../../types.js";
/**
 * A visit for an article's full-text page alone, no PDF (the school backend's
 * ``fulltext: "only"``): its page, if one was saved, and the backend's record.
 */
export type FulltextPageVisit = (doi: string, outputDir: string, diagnosticsDir: string) => Promise<{
    page?: CapturedFulltextPage;
    trace?: Record<string, unknown>;
    code?: string;
    message?: string;
    /** rate_limited: seconds until the publisher's hourly limit lets the page be read. */
    retryAfterSec?: number;
    /** rate_limited: whose hourly limit it is, as the school backend counts it. */
    hourlyPublisher?: string;
} | undefined>;
/**
 * The Markdown asked for without the PDF (content "markdown", or "supplements" with the
 * Markdown): its package, and nothing in its place. No source with the whole full text
 * (one missing figures is not kept) leaves the paper without it, saying why, for 接着下
 * to fetch it again (user, 2026-11-16; until then the PDF stood in). ``result``: what was
 * fetched so far (the supplementary files, or nothing). For content "markdown" the result's
 * status is the Markdown's; for supplementary files it stays theirs, the Markdown being in
 * ``markdown``.
 */
export declare function fulltextAlone(result: DownloadWithFallbackResult, request: DownloadWithFallbackOptions, searchers: Searchers | undefined, visitPage: FulltextPageVisit | undefined): Promise<DownloadWithFallbackResult>;
/**
 * 接着下 (resume.ts): the Markdown of a paper whose PDF a batch saved before (``mainPath``),
 * beside it; the PDF is not downloaded again. ok when the Markdown, or the files ``result``
 * went for, were saved.
 */
export declare function markdownBeside(result: DownloadWithFallbackResult, mainPath: string, request: DownloadWithFallbackOptions, searchers: Searchers | undefined, visitPage: FulltextPageVisit | undefined): Promise<DownloadWithFallbackResult>;
/**
 * Adds the paper's full-text package to its result, when the request asks for one. When no
 * source has it and the browser did not open the article (its PDF came from an open stage),
 * its page gets a visit alone (user, 2026-11-14): a site with rules, or one not yet supported
 * that the checks try (user, 2026-11-16), unless this batch gave up the site its DOI's prefix
 * leads to.
 * ``visitPage`` "later": a batch's open lane, which has no browser; such a paper is left as
 * it was ("later": nothing recorded) for the browser's lane to call this again with the visit.
 */
export declare function fulltextForItem(result: DownloadWithFallbackResult, request: DownloadWithFallbackOptions, searchers?: Searchers, visitPage?: FulltextPageVisit): Promise<FulltextSummary | undefined>;
export declare function fulltextForItem(result: DownloadWithFallbackResult, request: DownloadWithFallbackOptions, searchers: Searchers | undefined, visitPage: "later"): Promise<FulltextSummary | "later" | undefined>;
/**
 * fulltextForItem, asked again after a network loss: the Markdown's attempt the lost network
 * failed is taken back and the Markdown fetched anew once it is back.
 */
export declare function markdownPastNetworkLoss(result: DownloadWithFallbackResult, request: DownloadWithFallbackOptions, searchers: Searchers, visit: FulltextPageVisit | undefined, watch: NetworkWatch): Promise<void>;
//# sourceMappingURL=step.d.ts.map