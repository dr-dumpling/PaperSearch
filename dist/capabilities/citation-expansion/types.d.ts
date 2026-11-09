export interface CitationData {
    paperId: string;
    title: string;
    citationCount: number;
    referenceCount: number;
    influentialCitationCount?: number;
    year?: number;
    authors?: Array<{
        name: string;
        authorId?: string;
    }>;
    venue?: string;
    doi?: string;
    url?: string;
    /** set when the paper came from OpenAlex or Crossref rather than Semantic Scholar */
    source?: 'openalex' | 'crossref';
    /** a reference's number in the paper's own list, when the publisher's deposit shows it */
    number?: number;
}
export interface BatchCitationRequest {
    paperId?: string;
    doi?: string;
    arxivId?: string;
    title?: string;
}
//# sourceMappingURL=types.d.ts.map