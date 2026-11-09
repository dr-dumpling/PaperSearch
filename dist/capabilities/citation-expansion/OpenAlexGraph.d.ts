import type { CitationData } from './types.js';
/** How far OpenAlex lets requests without a key page: its first 10,000 results. */
export declare const KEYLESS_PAGING_LIMIT = 10000;
/** A DOI without its resolver prefix, lower case. */
export declare function doiKey(doi?: string | null): string;
/** Newest first, then by title. */
export declare const newestFirst: (a: CitationData, b: CitationData) => number;
/**
 * A paper's citing works and references from OpenAlex: open, works without a key (the mailto puts requests in its
 * polite pool); OPENALEX_API_KEY, free, raises the daily allowance and lets citing papers page past 10,000.
 * In our checks against the citing papers' own reference lists it listed 97% of the real citing papers and none that
 * were not.
 */
export declare class OpenAlexGraph {
    private readonly mailto;
    private readonly apiKey;
    private readonly client;
    constructor(mailto?: string, apiKey?: string);
    /** Whether requests carry an API key (and citing papers are therefore listed without the 10,000 cut). */
    get keyed(): boolean;
    private auth;
    /** The record for a DOI: its id, how often it is cited, and the ids of the works it cites. */
    work(doi: string): Promise<{
        id: string;
        citedByCount: number;
        referencedWorks: string[];
    } | null>;
    /** Works by id, with their details, 50 a request. An id OpenAlex no longer has a record for is left out. */
    works(ids: string[]): Promise<CitationData[]>;
    /**
     * Every work that cites a work, newest first, 200 a page. With a key OpenAlex's cursor pages through all of them;
     * without one it pages by number, and only through its first 10,000 results.
     */
    citedBy(id: string): Promise<CitationData[]>;
}
//# sourceMappingURL=OpenAlexGraph.d.ts.map