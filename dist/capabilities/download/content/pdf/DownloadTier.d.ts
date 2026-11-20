import type { Searchers } from "../../../../core/searchers.js";
import type { CapturedFulltextPage, DownloadBatchPosition, SupplementFile } from "../../types.js";
export interface DownloadTier {
    id: string;
    stage: string;
    run(context: DownloadTierContext): Promise<DownloadTierResult>;
}
export interface DownloadTierContext {
    arxivId?: string;
    arxivPaper?: import('../../../../models/Paper.js').Paper;
    arxivOnly?: boolean;
    arxivConflict?: boolean;
    arxivLookupError?: string;
    preprintIds?: string[];
    /** Set once the funnel has asked Crossref for a missing title. */
    titleLookedUp?: boolean;
    searchers: Searchers;
    source: string;
    paperId: string;
    doi?: string;
    title?: string;
    savePath: string;
    diagnosticsDir?: string;
    outputMetadata?: import("../../outputLayout.js").OutputMetadata;
    useEntitledAccess: boolean;
    useSciHub: boolean;
    batch?: DownloadBatchPosition;
    withSupplements?: boolean;
    /** Entitled access also saves the article's full-text page (--fulltext). */
    withFulltext?: boolean;
    /** The user seems away: entitled access waits on them only briefly. */
    shortUserWait?: boolean;
    /** Another saved school for this download alone (DownloadWithFallbackOptions.school). */
    school?: string;
}
export interface DownloadTierResult {
    version?: "preprint";
    arxivId?: string;
    publishedDoi?: string;
    status: "ok" | "error" | "skipped";
    path?: string;
    message: string;
    code?: string;
    /** Set when the saved artifact is not a PDF (publisher_api Springer JATS). */
    format?: "pdf" | "jats-xml";
    review?: {
        path: string;
        reason: string;
    };
    /** The tier already checked the PDF's identity (publisher_api, entitled_access). */
    verified?: boolean;
    /** The tier can run this item again after this many seconds (publisher's hourly limit). */
    retryAfterSec?: number;
    /** Whose hourly limit it is, as the school backend counts it. */
    hourlyPublisher?: string;
    /** Details for the local run ledger only; never copied into attempts. */
    trace?: Record<string, unknown>;
    supplements?: SupplementFile[];
    fulltextPage?: CapturedFulltextPage;
    /** The article page was read on the visit that took the PDF and showed no full text. */
    fulltextNotShown?: boolean;
}
//# sourceMappingURL=DownloadTier.d.ts.map