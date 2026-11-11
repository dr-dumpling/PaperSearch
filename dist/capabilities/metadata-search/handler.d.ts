import type { Searchers } from '../../core/searchers.js';
export declare function handleGenericSearch(platform: string, args: any, searchers: Searchers): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleSearchPapers(args: any, searchers: Searchers): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
/**
 * ``get_paper_by_doi``: one DOI (``doi``) or many (``dois``) in one call. The answer
 * has one shape whatever the platform (user, 2026-11-11): every paper in ``papers``;
 * ``not_found`` for DOIs the sources answered for without the paper, ``lookup_failed``
 * for DOIs no source could answer for; ``warnings`` for sources that failed. One DOI
 * also gets its ``doi`` and per-source ``source_results``, ``errors``, ``failed_sources``.
 */
export declare function handleGetPaperByDoi(args: {
    doi?: string;
    dois?: string[];
    platform?: string;
}, searchers: Searchers): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
//# sourceMappingURL=handler.d.ts.map