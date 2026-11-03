import { SEARCH_PLATFORM_VALUES } from "../../registry/platformMetadata.js";
export const DOWNLOAD_PAPER_TOOL = {
    name: "download_paper",
    description: "Download PDF file through one funnel: native and open-access sources first, then PaperSearch Sci-Hub, and finally the configured entitled-access integration.",
    inputSchema: {
        type: "object",
        properties: {
            paperId: {
                type: "string",
                description: "Paper ID (e.g., PMCID, DOI)",
            },
            platform: {
                type: "string",
                enum: [...SEARCH_PLATFORM_VALUES],
                description: "Platform where the paper is from. If native download is unsupported or fails, the fallback funnel is used.",
            },
            savePath: {
                type: "string",
                description: "Directory to save the PDF file",
            },
            useEntitledAccess: {
                type: "boolean",
                default: true,
                description: "Try the configured entitled-access integration. Default: true. Set false to skip it for this request.",
            },
        },
        required: ["paperId", "platform"],
    },
};
export const DOWNLOAD_WITH_FALLBACK_TOOL = {
    name: "download_with_fallback",
    description: "Download with a funnel fallback chain: source-native download, metadata PDF URL, PMC/Europe PMC/CORE/OpenAIRE discovery, Unpaywall DOI resolution, PaperSearch Sci-Hub unless useSciHub=false, then the configured entitled-access integration as the final fallback.",
    inputSchema: {
        type: "object",
        properties: {
            source: {
                type: "string",
                description: "Primary source name, e.g. crossref, pmc, core",
            },
            paperId: {
                type: "string",
                description: "Source-native paper identifier",
            },
            doi: {
                type: "string",
                description: "Optional DOI for OA fallback resolution",
            },
            title: {
                type: "string",
                description: "Optional title for repository discovery fallback",
            },
            savePath: {
                type: "string",
                description: "Directory to save the PDF file",
            },
            useEntitledAccess: {
                type: "boolean",
                default: true,
                description: "Try the configured entitled-access integration. Default: true. Set false to skip it for this request.",
            },
            useSciHub: {
                type: "boolean",
                description: "Use PaperSearch Sci-Hub after open-access routes and before entitled access. Default: true. Set false to skip this stage.",
            },
            content: {
                type: "string",
                enum: ["main", "supplements", "both"],
                default: "main",
                description: "What to download: main (default) the main text only; supplements only the article's supplementary files (no main-text stages; the entitled-access backend visits the article page); both the main text and its supplementary files (items whose main text came from an open stage get a supplements-only backend visit). Supplementary files are saved under <savePath>/<DOI>_supplements/ and listed in the result's supplements.",
            },
            batch: {
                type: "object",
                description: "Optional: this download is item `index` of a serial batch of `total` items. The entitled-access backend then shows the whole batch (k / N) in its progress window. done/succeeded/failed are the batch totals before this item (default index-1, 0, 0). Prefer download_batch for whole lists.",
                properties: {
                    id: { type: "string", description: "Same id for every item of one batch" },
                    index: { type: "integer", minimum: 1 },
                    total: { type: "integer", minimum: 1 },
                    done: { type: "integer", minimum: 0 },
                    succeeded: { type: "integer", minimum: 0 },
                    failed: { type: "integer", minimum: 0 },
                },
                required: ["id", "index", "total"],
            },
        },
        required: ["source", "paperId"],
    },
};
export const DOWNLOAD_BATCH_TOOL = {
    name: "download_batch",
    description: "Download a list of papers serially (up to 1000) through the same funnel as download_with_fallback. By default in two phases: open stages for every item first, then entitled access only for the items still missing, with one backend progress window (k / M) for that stretch. Returns per-item results and totals.",
    inputSchema: {
        type: "object",
        properties: {
            items: {
                type: "array",
                minItems: 1,
                maxItems: 1000,
                description: "Papers to download, in order. Each needs a doi or a paperId.",
                items: {
                    type: "object",
                    properties: {
                        doi: { type: "string" },
                        title: { type: "string", description: "Optional, improves repository discovery and identity checks" },
                        source: { type: "string", description: "Primary source name; default crossref" },
                        paperId: { type: "string", description: "Source-native id; defaults to the DOI" },
                        savePath: { type: "string", description: "Optional per-item directory" },
                    },
                },
            },
            savePath: {
                type: "string",
                description: "Directory to save the PDF files",
            },
            useEntitledAccess: {
                type: "boolean",
                default: true,
                description: "Try the configured entitled-access integration for each item. Default: true.",
            },
            useSciHub: {
                type: "boolean",
                description: "Use PaperSearch Sci-Hub for each item. Default: true.",
            },
            content: {
                type: "string",
                enum: ["main", "supplements", "both"],
                default: "main",
                description: "What to download: main (default) the main text only; supplements only the article's supplementary files (no main-text stages; the entitled-access backend visits the article page); both the main text and its supplementary files (items whose main text came from an open stage get a supplements-only backend visit). Supplementary files are saved under <savePath>/<DOI>_supplements/ and listed in the result's supplements.",
            },
            mode: {
                type: "string",
                enum: ["two_phase", "per_item", "entitled_only"],
                default: "two_phase",
                description: "two_phase (default): open stages for every item first, then entitled access only for the items still missing, so browser logins happen in one stretch at the end. per_item: the whole funnel per item. entitled_only: skip the open stages; every item goes straight to entitled access.",
            },
        },
        required: ["items"],
    },
};
export const PDF_DISCOVERY_TOOLS = [
    DOWNLOAD_PAPER_TOOL,
    DOWNLOAD_WITH_FALLBACK_TOOL,
    DOWNLOAD_BATCH_TOOL,
];
//# sourceMappingURL=tools.js.map