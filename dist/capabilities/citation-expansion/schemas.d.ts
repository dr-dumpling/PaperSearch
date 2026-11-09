import { z } from 'zod';
/** A paper to look up, by Semantic Scholar id, DOI or arXiv id. Both tools return everything they find: no limit. */
export declare const CitationLookupSchema: z.ZodEffects<z.ZodObject<{
    paperId: z.ZodOptional<z.ZodString>;
    doi: z.ZodOptional<z.ZodString>;
    arxivId: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    paperId?: string | undefined;
    doi?: string | undefined;
    arxivId?: string | undefined;
}, {
    paperId?: string | undefined;
    doi?: string | undefined;
    arxivId?: string | undefined;
}>, {
    paperId?: string | undefined;
    doi?: string | undefined;
    arxivId?: string | undefined;
}, {
    paperId?: string | undefined;
    doi?: string | undefined;
    arxivId?: string | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map