import { z } from 'zod';
export declare const SearchPapersSchema: z.ZodEffects<z.ZodObject<{
    query: z.ZodString;
    platform: z.ZodDefault<z.ZodOptional<z.ZodUnion<[z.ZodEffects<z.ZodString, string, string>, z.ZodLiteral<"all">]>>>;
    sources: z.ZodOptional<z.ZodString>;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    category: z.ZodOptional<z.ZodString>;
    days: z.ZodOptional<z.ZodNumber>;
    fetchDetails: z.ZodOptional<z.ZodBoolean>;
    fieldsOfStudy: z.ZodOptional<z.ZodArray<z.ZodString, "many">>;
    sortBy: z.ZodDefault<z.ZodOptional<z.ZodEnum<["relevance", "date", "citations"]>>>;
    sortOrder: z.ZodDefault<z.ZodOptional<z.ZodEnum<["asc", "desc"]>>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    sortBy: "relevance" | "date" | "citations";
    sortOrder: "asc" | "desc";
    query: string;
    platform: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    category?: string | undefined;
    days?: number | undefined;
    fetchDetails?: boolean | undefined;
    fieldsOfStudy?: string[] | undefined;
    sources?: string | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    category?: string | undefined;
    sortBy?: "relevance" | "date" | "citations" | undefined;
    sortOrder?: "asc" | "desc" | undefined;
    days?: number | undefined;
    fetchDetails?: boolean | undefined;
    fieldsOfStudy?: string[] | undefined;
    platform?: string | undefined;
    sources?: string | undefined;
}>, {
    maxResults: number;
    sortBy: "relevance" | "date" | "citations";
    sortOrder: "asc" | "desc";
    query: string;
    platform: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    category?: string | undefined;
    days?: number | undefined;
    fetchDetails?: boolean | undefined;
    fieldsOfStudy?: string[] | undefined;
    sources?: string | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    category?: string | undefined;
    sortBy?: "relevance" | "date" | "citations" | undefined;
    sortOrder?: "asc" | "desc" | undefined;
    days?: number | undefined;
    fetchDetails?: boolean | undefined;
    fieldsOfStudy?: string[] | undefined;
    platform?: string | undefined;
    sources?: string | undefined;
}>;
export declare const GetPaperByDoiSchema: z.ZodObject<{
    doi: z.ZodString;
    platform: z.ZodDefault<z.ZodOptional<z.ZodEnum<["arxiv", "webofscience", "pubmed", "crossref", "openalex", "unpaywall", "pmc", "europepmc", "core", "all"]>>>;
}, "strip", z.ZodTypeAny, {
    doi: string;
    platform: "arxiv" | "webofscience" | "pubmed" | "core" | "crossref" | "openalex" | "unpaywall" | "pmc" | "europepmc" | "all";
}, {
    doi: string;
    platform?: "arxiv" | "webofscience" | "pubmed" | "core" | "crossref" | "openalex" | "unpaywall" | "pmc" | "europepmc" | "all" | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map