import type { BatchCitationRequest, CitationData } from './types.js';
export type { BatchCitationRequest, CitationData } from './types.js';
export declare class CitationService {
    private client;
    private cache;
    private rateLimiter;
    private apiKey?;
    constructor(apiKey?: string);
    /**
     * Get citation data for a single paper by ID
     */
    getCitationData(paperId: string, forceRefresh?: boolean): Promise<CitationData | null>;
    /**
     * Get citation data by DOI
     */
    getCitationDataByDoi(doi: string, forceRefresh?: boolean): Promise<CitationData | null>;
    /**
     * Get citation data by arXiv ID
     */
    getCitationDataByArxiv(arxivId: string, forceRefresh?: boolean): Promise<CitationData | null>;
    /**
     * Batch lookup citations for multiple papers
     */
    batchLookup(requests: BatchCitationRequest[]): Promise<Map<string, CitationData | null>>;
    /**
     * Get references for a paper
     */
    getReferences(paperId: string, limit?: number): Promise<CitationData[]>;
    /**
     * References for a paper, and whether the publisher has Semantic Scholar withhold them
     * (it then answers with no list and a disclaimer naming the elided field).
     */
    getReferenceList(paperId: string, limit?: number): Promise<{
        papers: CitationData[];
        withheld: boolean;
    }>;
    /**
     * Get citations for a paper
     */
    getCitations(paperId: string, limit?: number): Promise<CitationData[]>;
    /**
     * Parse Semantic Scholar response to CitationData
     */
    private parseCitationData;
    /**
     * Get cache statistics
     */
    getCacheStats(): import("../../infrastructure/cache/RequestCache.js").CacheStats;
    /**
     * Clear cache
     */
    clearCache(): void;
}
export default CitationService;
//# sourceMappingURL=CitationService.d.ts.map