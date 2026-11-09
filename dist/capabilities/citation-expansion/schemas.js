import { z } from 'zod';
/** A paper to look up, by Semantic Scholar id, DOI or arXiv id. Both tools return everything they find: no limit. */
export const CitationLookupSchema = z
    .object({
    paperId: z.coerce.string().min(1).optional(),
    doi: z.coerce.string().min(1).optional(),
    arxivId: z.coerce.string().min(1).optional()
})
    .strip()
    .refine(value => Boolean(value.paperId || value.doi || value.arxivId), {
    message: 'Provide paperId, doi, or arxivId'
});
//# sourceMappingURL=schemas.js.map