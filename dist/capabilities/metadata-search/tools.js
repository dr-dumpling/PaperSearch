import { SEARCH_PLATFORM_VALUES } from '../../registry/platformMetadata.js';
export const SEARCH_PAPERS_TOOL = {
    name: 'search_papers',
    description: 'Search academic papers from multiple sources including Web of Science, etc.',
    inputSchema: {
        type: 'object',
        properties: {
            query: { type: 'string', description: 'Search query string' },
            platform: {
                type: 'string',
                enum: [...SEARCH_PLATFORM_VALUES, 'all'],
                description: 'Platform to search (default: crossref). Use --sources for comma-separated multi-source search.'
            },
            sources: {
                type: 'string',
                description: 'Comma-separated source list for multi-source search. Use all for the broad registered set, or no-key (aliases: free, no_key) for Crossref, PubMed, Europe PMC, arXiv, and OpenReview without user API keys. Failed or unconfigured sources are reported in failed_sources/errors. Example: crossref,openalex,pubmed,pmc'
            },
            maxResults: {
                type: 'number',
                minimum: 1,
                maximum: 100,
                description: 'Maximum number of results to return'
            },
            year: { type: 'string', description: 'Year filter (e.g., "2023", "2020-2023", "2020-")' },
            author: { type: 'string', description: 'Author name filter' },
            journal: { type: 'string', description: 'Journal name filter' },
            category: { type: 'string', description: 'Category filter (e.g., a bioRxiv subject such as neuroscience)' },
            days: {
                type: 'number',
                description: 'Number of days to search back (bioRxiv/medRxiv only)'
            },
            fetchDetails: {
                type: 'boolean',
                description: 'Fetch detailed information (IACR only)'
            },
            fieldsOfStudy: {
                type: 'array',
                items: { type: 'string' },
                description: 'Fields of study filter (Semantic Scholar only)'
            },
            sortBy: {
                type: 'string',
                enum: ['relevance', 'date', 'citations'],
                description: 'Sort results by relevance, date, or citations'
            },
            sortOrder: {
                type: 'string',
                enum: ['asc', 'desc'],
                description: 'Sort order: ascending or descending'
            }
        },
        required: ['query']
    }
};
export const GET_PAPER_BY_DOI_TOOL = {
    name: 'get_paper_by_doi',
    description: 'Look up papers by DOI to check they exist and read their metadata. One DOI (doi) or up to 100 in one call (dois). The result lists every paper in data.papers, the DOIs not found in data.not_found and those no source could answer for in data.lookup_failed.',
    inputSchema: {
        type: 'object',
        properties: {
            doi: {
                type: 'string',
                description: 'One DOI (Digital Object Identifier)'
            },
            dois: {
                type: 'array',
                items: { type: 'string' },
                maxItems: 100,
                description: 'Several DOIs, looked up in one call (also a single string with commas, semicolons or spaces between them)'
            },
            platform: {
                type: 'string',
                enum: ['auto', 'crossref', 'openalex', 'pubmed', 'pmc', 'europepmc', 'unpaywall', 'core', 'webofscience', 'all'],
                description: 'auto (default): Crossref first, the other sources only for a DOI Crossref does not know; all: every source, each record kept; or one source'
            }
        },
        required: []
    }
};
export const METADATA_SEARCH_TOOLS = [SEARCH_PAPERS_TOOL, GET_PAPER_BY_DOI_TOOL];
//# sourceMappingURL=tools.js.map