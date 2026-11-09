import type { CitationData } from './types.js';
type Provider = 'crossref' | 'openalex' | 'semantic_scholar';
export declare function resolveCitationTarget(args: {
    paperId?: string;
    doi?: string;
    arxivId?: string;
}): string;
/** One source per answer (provider); notes say why when it is not the usual one, or what is missing. */
export declare function citationResponse(target: string, relation: 'citations' | 'references', provider: Provider, papers: CitationData[], extra?: Record<string, unknown>, notes?: string[]): {
    notes?: string[] | undefined;
    papers: CitationData[];
    target: string;
    relation: "references" | "citations";
    provider: Provider;
    total: number;
};
/** Semantic Scholar answers at most this many in one request; it is asked only when the others have nothing. */
export declare const SEMANTIC_SCHOLAR_MAX = 1000;
/** Every citing paper OpenAlex knows, newest first; Semantic Scholar only when OpenAlex has no record of the paper. */
export declare function handleGetPaperCitations(args: {
    paperId?: string;
    doi?: string;
    arxivId?: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
/**
 * One source for the whole list: the publisher's own list from Crossref when it says what each reference is (numbered
 * as in the paper); OpenAlex's when the publisher deposited no more than DOIs, or nothing; Semantic Scholar's last.
 */
export declare function handleGetPaperReferences(args: {
    paperId?: string;
    doi?: string;
    arxivId?: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export {};
//# sourceMappingURL=handler.d.ts.map