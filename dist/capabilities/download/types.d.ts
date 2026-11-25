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
/**
 * What a download fetches: the main text's PDF (default), only supplementary files, both,
 * or only the Markdown (the full-text package; the PDF when no source has one). Each kind
 * is fetched on its own (user, 2026-11-14): the Markdown beside the PDF or the
 * supplementary files is ``fulltext: true`` beside "main", "supplements" or "both"
 * (schemas.ts reads "supplements,markdown" and the like into that).
 */
export type DownloadContent = "main" | "supplements" | "both" | "markdown";
/** The kinds a download asked for, as the caller names them: "pdf", "supplements,markdown"… */
export declare function contentKinds(content: DownloadContent | undefined, markdown?: boolean): string;
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
    /** The Markdown's stage: what a registered site's saved page may lack (the batch's index says it). */
    possiblyMissing?: {
        figures?: number;
        references?: number;
        text?: number;
        tables?: boolean;
    };
    /** The Markdown's stage: the figures it was saved without, marked in article.md (the batch's index says them). */
    missingFigures?: string[];
    /** The Markdown's stage: a registered site's page converted by other rules than its listed ones. */
    rulesFallback?: {
        host: string;
        listed: string;
        listedResult: string;
        used: string;
        matchedBy: string;
        basis?: string;
        report?: string;
    };
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
    /** Another saved school for this download alone, as the user asked; the configured one stays. */
    school?: string;
    /** Called after every stage (run ledger). */
    onStage?: (record: DownloadStageRecord) => void;
    /**
     * Where a download that went fine keeps the backend's record and screenshots: its
     * run's folder (user, 2026-11-10).
     */
    recordsDir?: string;
    /** Where a paper that did not go fine keeps its diagnostics: the run's folder too (user, 2026-11-11). */
    diagnosticsDir?: string;
    /** main (default) / supplements / both / markdown; see DownloadContent. */
    content?: DownloadContent;
    /** The paper's Markdown, its full-text package (original full text, article.md, figures); see content/markdown/step.ts. Always true for content "markdown". */
    fulltext?: boolean;
    /**
     * The Markdown from the article page the school's visit read alone, as the PDF in a batch's
     * entitled_only mode: no PubMed Central, no publisher API (user, 2026-11-17: Cell, "全部通过机构").
     */
    fulltextPageOnly?: boolean;
}
/** The Markdown of a download: its full-text package (content markdown, or --markdown). */
export interface FulltextSummary {
    /**
     * ok: saved (missingFigures: without some figures, marked in it); incomplete: a full text
     * missing figures or a table, not kept (code figures_missing, tables_missing);
     * abstract_only / unavailable: no full text found; error: it failed.
     */
    status: "ok" | "incomplete" | "abstract_only" | "unavailable" | "error";
    source?: string;
    /** article.md */
    file?: string;
    /** The original full text it was made from (source/article.xml or .html). */
    original?: string;
    /** source/fulltext.json: the source, the DOI check, each figure's status. */
    manifest?: string;
    figures?: {
        saved: number;
        total: number;
    };
    code?: string;
    message: string;
    /** What the conversion missed or the source said (formula_missing, author_manuscript…). */
    warnings?: string[];
    /**
     * From a site not yet supported (no rules written and checked for it): its host, the rules
     * tried, what they lacked, and the saved page and check results kept for a report.
     */
    unverified?: {
        host: string;
        template?: string;
        shortfall?: {
            figures?: number;
            references?: number;
            text?: number;
            tables?: boolean;
        };
        report?: string;
        skipped?: boolean;
        matchedBy?: "publisher" | "platform" | "other";
        basis?: string;
    };
    /**
     * Saved from a registered site's page whose checks against the page found something short
     * (user, 2026-11-17): the Markdown is kept, this says what it may lack.
     */
    possiblyMissing?: {
        figures?: number;
        references?: number;
        text?: number;
        tables?: boolean;
    };
    /**
     * Saved without these figures (their labels), which did not download: each is marked at its
     * place in article.md; a batch tries them once more at its end (user, 2026-11-23).
     */
    missingFigures?: string[];
    /**
     * A registered site's page its listed rules did not convert (abstract only, figures or tables
     * left out), converted completely by other rules (user, 2026-11-18): which, and why.
     */
    rulesFallback?: {
        host: string;
        listed: string;
        listedResult: string;
        used: string;
        matchedBy: string;
        basis?: string;
        report?: string;
    };
}
/**
 * The article's full-text page the browser saved while on it (--fulltext): the page's
 * HTML and the figure images it fetched in the same session. Only the full-text step
 * reads it, and removes it from the result.
 */
export interface CapturedFulltextPage {
    file: string;
    /** The page's address. */
    url: string;
    images: {
        url: string;
        file: string;
    }[];
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
    /** The Markdown (full-text package), when asked for. */
    markdown?: FulltextSummary;
    /** For the full-text step only (see CapturedFulltextPage). */
    fulltextPage?: CapturedFulltextPage;
    /** For the full-text step only: the visit that took the PDF read the article page and saw no full text. */
    fulltextNotShown?: boolean;
    attempts: Array<{
        stage: string;
        status: "ok" | "error" | "skipped";
        message: string;
        code?: string;
        /** rate_limited: seconds until this item can be tried again. */
        retryAfterSec?: number;
        /** rate_limited: whose hourly limit it is, as the school backend counts it. */
        hourlyPublisher?: string;
        /** entitled_access: the saved school it was got through, when not the default one (没权限时换下一所学校). */
        school?: string;
        /** entitled_access: no access with any of this many saved schools (没权限时换下一所学校). */
        schools?: number;
    }>;
}
//# sourceMappingURL=types.d.ts.map