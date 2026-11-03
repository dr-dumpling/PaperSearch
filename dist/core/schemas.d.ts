import { z } from 'zod';
import { SearchSemanticSnippetsSchema } from '../capabilities/body-snippet-search/schemas.js';
import { CitationLookupSchema } from '../capabilities/citation-expansion/schemas.js';
import { GetPaperByDoiSchema, SearchPapersSchema } from '../capabilities/metadata-search/schemas.js';
import { QueryJournalMetricsSchema } from '../capabilities/journal-metrics/schemas.js';
import { DownloadBatchSchema, DownloadPaperSchema, DownloadWithFallbackSchema } from '../capabilities/pdf-discovery/schemas.js';
export { CitationLookupSchema };
export { DownloadBatchSchema, DownloadPaperSchema, DownloadWithFallbackSchema };
export { GetPaperByDoiSchema, SearchPapersSchema };
export { QueryJournalMetricsSchema };
export { SearchSemanticSnippetsSchema };
export declare const SearchWebOfScienceSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    sortBy: z.ZodOptional<z.ZodEnum<["relevance", "date", "citations", "title", "author", "journal"]>>;
    sortOrder: z.ZodOptional<z.ZodEnum<["asc", "desc"]>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    sortBy?: "title" | "journal" | "relevance" | "date" | "citations" | "author" | undefined;
    sortOrder?: "asc" | "desc" | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    sortBy?: "title" | "journal" | "relevance" | "date" | "citations" | "author" | undefined;
    sortOrder?: "asc" | "desc" | undefined;
}>;
export declare const SearchPubMedSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    publicationType: z.ZodOptional<z.ZodArray<z.ZodString, "many">>;
    sortBy: z.ZodOptional<z.ZodEnum<["relevance", "date"]>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    sortBy?: "relevance" | "date" | undefined;
    publicationType?: string[] | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    sortBy?: "relevance" | "date" | undefined;
    publicationType?: string[] | undefined;
}>;
export declare const SearchBioRxivSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    days: z.ZodOptional<z.ZodNumber>;
    category: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    category?: string | undefined;
    days?: number | undefined;
}, {
    query: string;
    maxResults?: number | undefined;
    category?: string | undefined;
    days?: number | undefined;
}>;
export declare const SearchMedRxivSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    days: z.ZodOptional<z.ZodNumber>;
    category: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    category?: string | undefined;
    days?: number | undefined;
}, {
    query: string;
    maxResults?: number | undefined;
    category?: string | undefined;
    days?: number | undefined;
}>;
export declare const SearchSemanticScholarSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    fieldsOfStudy: z.ZodOptional<z.ZodArray<z.ZodString, "many">>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    year?: string | undefined;
    fieldsOfStudy?: string[] | undefined;
}, {
    query: string;
    year?: string | undefined;
    maxResults?: number | undefined;
    fieldsOfStudy?: string[] | undefined;
}>;
export declare const SearchIACRSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    fetchDetails: z.ZodOptional<z.ZodBoolean>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    fetchDetails?: boolean | undefined;
}, {
    query: string;
    maxResults?: number | undefined;
    fetchDetails?: boolean | undefined;
}>;
export declare const SearchGoogleScholarSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    yearLow: z.ZodOptional<z.ZodNumber>;
    yearHigh: z.ZodOptional<z.ZodNumber>;
    author: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    author?: string | undefined;
    yearLow?: number | undefined;
    yearHigh?: number | undefined;
}, {
    query: string;
    maxResults?: number | undefined;
    author?: string | undefined;
    yearLow?: number | undefined;
    yearHigh?: number | undefined;
}>;
export declare const SearchSciHubSchema: z.ZodObject<{
    doiOrUrl: z.ZodString;
    downloadPdf: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
    savePath: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    doiOrUrl: string;
    downloadPdf: boolean;
    savePath?: string | undefined;
}, {
    doiOrUrl: string;
    savePath?: string | undefined;
    downloadPdf?: boolean | undefined;
}>;
export declare const CheckSciHubMirrorsSchema: z.ZodObject<{
    forceCheck: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
}, "strip", z.ZodTypeAny, {
    forceCheck: boolean;
}, {
    forceCheck?: boolean | undefined;
}>;
export declare const SearchScienceDirectSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    openAccess: z.ZodOptional<z.ZodBoolean>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    openAccess?: boolean | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    openAccess?: boolean | undefined;
}>;
export declare const SearchSpringerSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    subject: z.ZodOptional<z.ZodString>;
    openAccess: z.ZodOptional<z.ZodBoolean>;
    type: z.ZodOptional<z.ZodEnum<["Journal", "Book", "Chapter"]>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    openAccess?: boolean | undefined;
    subject?: string | undefined;
    type?: "Journal" | "Book" | "Chapter" | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    openAccess?: boolean | undefined;
    subject?: string | undefined;
    type?: "Journal" | "Book" | "Chapter" | undefined;
}>;
export declare const SearchScopusSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    affiliation: z.ZodOptional<z.ZodString>;
    subject: z.ZodOptional<z.ZodString>;
    openAccess: z.ZodOptional<z.ZodBoolean>;
    documentType: z.ZodOptional<z.ZodEnum<["ar", "cp", "re", "bk", "ch"]>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    openAccess?: boolean | undefined;
    subject?: string | undefined;
    affiliation?: string | undefined;
    documentType?: "ar" | "cp" | "re" | "bk" | "ch" | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    openAccess?: boolean | undefined;
    subject?: string | undefined;
    affiliation?: string | undefined;
    documentType?: "ar" | "cp" | "re" | "bk" | "ch" | undefined;
}>;
export declare const SearchCrossrefSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    sortBy: z.ZodDefault<z.ZodOptional<z.ZodEnum<["relevance", "date", "citations"]>>>;
    sortOrder: z.ZodDefault<z.ZodOptional<z.ZodEnum<["asc", "desc"]>>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    sortBy: "relevance" | "date" | "citations";
    sortOrder: "asc" | "desc";
    query: string;
    year?: string | undefined;
    author?: string | undefined;
}, {
    query: string;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    sortBy?: "relevance" | "date" | "citations" | undefined;
    sortOrder?: "asc" | "desc" | undefined;
}>;
export declare const SearchOpenAlexSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    year?: string | undefined;
}, {
    query: string;
    year?: string | undefined;
    maxResults?: number | undefined;
}>;
export declare const SearchUnpaywallSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
}, {
    query: string;
    maxResults?: number | undefined;
}>;
export declare const SearchPMCStyleSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    year?: string | undefined;
}, {
    query: string;
    year?: string | undefined;
    maxResults?: number | undefined;
}>;
export declare const SearchCoreSchema: z.ZodEffects<z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    query: string;
    year?: string | undefined;
}, {
    query: string;
    year?: string | undefined;
    maxResults?: number | undefined;
}>, {
    maxResults: number;
    query: string;
    year?: string | undefined;
}, {
    query: string;
    year?: string | undefined;
    maxResults?: number | undefined;
}>;
export declare const GenericPlatformSearchSchema: z.ZodObject<{
    query: z.ZodString;
    maxResults: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
    year: z.ZodOptional<z.ZodString>;
    author: z.ZodOptional<z.ZodString>;
    journal: z.ZodOptional<z.ZodString>;
    venue: z.ZodOptional<z.ZodString>;
    articleTitle: z.ZodOptional<z.ZodString>;
    startRecord: z.ZodOptional<z.ZodNumber>;
    sortBy: z.ZodDefault<z.ZodOptional<z.ZodEnum<["relevance", "date", "citations"]>>>;
    sortOrder: z.ZodDefault<z.ZodOptional<z.ZodEnum<["asc", "desc"]>>>;
}, "strip", z.ZodTypeAny, {
    maxResults: number;
    sortBy: "relevance" | "date" | "citations";
    sortOrder: "asc" | "desc";
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    author?: string | undefined;
    venue?: string | undefined;
    articleTitle?: string | undefined;
    startRecord?: number | undefined;
}, {
    query: string;
    journal?: string | undefined;
    year?: string | undefined;
    maxResults?: number | undefined;
    author?: string | undefined;
    venue?: string | undefined;
    sortBy?: "relevance" | "date" | "citations" | undefined;
    sortOrder?: "asc" | "desc" | undefined;
    articleTitle?: string | undefined;
    startRecord?: number | undefined;
}>;
export declare const GetPlatformStatusSchema: z.ZodObject<{
    validate: z.ZodDefault<z.ZodOptional<z.ZodBoolean>>;
}, "strip", z.ZodTypeAny, {
    validate: boolean;
}, {
    validate?: boolean | undefined;
}>;
export type ToolName = string | 'search_papers' | 'search_webofscience' | 'search_pubmed' | 'search_biorxiv' | 'search_medrxiv' | 'search_semantic_scholar' | 'search_semantic_snippets' | 'get_paper_citations' | 'get_paper_references' | 'search_iacr' | 'download_paper' | 'search_google_scholar' | 'get_paper_by_doi' | 'search_scihub' | 'check_scihub_mirrors' | 'get_platform_status' | 'search_sciencedirect' | 'search_springer' | 'search_scopus' | 'search_crossref' | 'search_openalex' | 'search_unpaywall' | 'search_pmc' | 'search_europepmc' | 'search_core' | 'search_openaire' | 'download_with_fallback' | 'download_batch' | 'query_journal_metrics';
export declare function parseToolArgs(toolName: ToolName, args: unknown): any;
//# sourceMappingURL=schemas.d.ts.map