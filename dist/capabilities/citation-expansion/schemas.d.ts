import { z } from 'zod';
export declare const CitationLookupSchema: z.ZodEffects<z.ZodObject<{
    paperId: z.ZodOptional<z.ZodString>;
    doi: z.ZodOptional<z.ZodString>;
    arxivId: z.ZodOptional<z.ZodString>;
    limit: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
}, "strip", z.ZodTypeAny, {
    limit: number;
    paperId?: string | undefined;
    doi?: string | undefined;
    arxivId?: string | undefined;
}, {
    paperId?: string | undefined;
    doi?: string | undefined;
    limit?: number | undefined;
    arxivId?: string | undefined;
}>, {
    limit: number;
    paperId?: string | undefined;
    doi?: string | undefined;
    arxivId?: string | undefined;
}, {
    paperId?: string | undefined;
    doi?: string | undefined;
    limit?: number | undefined;
    arxivId?: string | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map