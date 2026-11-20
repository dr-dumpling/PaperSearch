import { SEARCH_PLATFORM_VALUES } from "../../registry/platformMetadata.js";
import { proFeatures } from "../../config/edition.js";
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
            content: {
                type: "string",
                enum: ["pdf", "markdown", "pdf,markdown"],
                default: "pdf",
                description: "pdf (default) the PDF; markdown the Markdown alone (the full-text package, kept only whole; no PDF in its place); pdf,markdown both. Supplementary files: download_with_fallback.",
            },
            markdown: {
                type: "boolean",
                default: false,
                description: "Also make the paper's Markdown (same as adding markdown to content): article.md and its figures/ in markdown/ inside the paper's own folder, the original full text and fulltext.json in markdown/source/; see download_with_fallback.",
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
                default: "pdf",
                description: "What to download: three kinds, each fetched on its own, in any combination. pdf (default) the main text's PDF; supplements the article's supplementary files (no main-text stages; the entitled-access backend visits the article page); markdown the Markdown, i.e. the full-text package with article.md (see the markdown field; only a whole full text is kept: one missing any figure is not, its markdown.status being incomplete, to fetch again later; asked for without pdf, no PDF is downloaded in its place). Several kinds together: \"supplements,markdown\", \"pdf,supplements\", \"pdf,markdown\", \"pdf,supplements,markdown\". Supplementary files are saved in the paper's own folder and listed in the result's supplements. With markdown alone the result's status is the Markdown's; with supplements it stays the supplementary files', the Markdown being in markdown.",
            },
            markdown: {
                type: "boolean",
                default: false,
                description: "Also make the paper's Markdown (the same as adding markdown to content): its full-text package in markdown/ inside the paper's own folder: article.md (sections, figures before their captions, tables as one-line HTML, formulas as LaTeX, references) and the body's figures in figures/, made from the full text of PubMed Central (JATS XML), Elsevier's API (XML) or the publisher's page the entitled-access backend saved; that original and fulltext.json (the source, the DOI check, each figure's status) in markdown/source/, to trace a result back. An abstract-only record writes nothing. The result's markdown says what was saved (markdown.file is article.md; markdown.warnings what the conversion missed); beside the PDF it never changes the paper's status.",
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
    description: "Download a list of papers, any number, through the same funnel as download_with_fallback. By default in two phases: open stages for every item first, then entitled access only for the items still missing, with one backend progress window (k / M) for that stretch. Returns the batch's totals, how many papers lack their Markdown or supplementary files, its folder, and index: the list of every paper's result (_run/article_index.csv); not each paper.",
    inputSchema: {
        type: "object",
        properties: {
            items: {
                type: "array",
                description: "Papers to download, in order. Each needs a doi or a paperId. Leave out with resume.",
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
            folderName: {
                type: "string",
                description: "Name of this batch's own folder inside savePath (or the default download folder), named for what it holds, e.g. Osteoarthritis Cartilage_2024-2026 for a journal's 2024 to 2026 papers (the journal's abbreviation as each paper's folder begins, not initials). Each paper's folder goes straight into it, beside _run/: what the batch was asked, its progress log, each run's records (resume runs too) and article_index.csv (every paper and how it went). Without it the batch gets a new <time>_PaperSearchDownload folder, laid out the same.",
            },
            school: {
                type: "string",
                description: "Only when the user names a school for this batch: one of the schools saved for the entitled-access backend (paper-search-school schools), by its name, English name, domain or entityID. Used for this batch alone (and its resume); the configured school is not changed. Never chosen on your own.",
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
                default: "pdf",
                description: "What to download: three kinds, each fetched on its own, in any combination. pdf (default) the main text's PDF; supplements the article's supplementary files (no main-text stages; the entitled-access backend visits the article page); markdown the Markdown, i.e. the full-text package with article.md (see the markdown field; only a whole full text is kept: one missing any figure is not, its markdown.status being incomplete, to fetch again later; asked for without pdf, no PDF is downloaded in its place). Several kinds together: \"supplements,markdown\", \"pdf,supplements\", \"pdf,markdown\", \"pdf,supplements,markdown\". Supplementary files are saved in the paper's own folder and listed in the result's supplements. With markdown alone the result's status is the Markdown's; with supplements it stays the supplementary files', the Markdown being in markdown.",
            },
            markdown: {
                type: "boolean",
                default: false,
                description: "Also make the paper's Markdown (the same as adding markdown to content): its full-text package in markdown/ inside the paper's own folder: article.md (sections, figures before their captions, tables as one-line HTML, formulas as LaTeX, references) and the body's figures in figures/, made from the full text of PubMed Central (JATS XML), Elsevier's API (XML) or the publisher's page the entitled-access backend saved; that original and fulltext.json (the source, the DOI check, each figure's status) in markdown/source/, to trace a result back. An abstract-only record writes nothing. The result's markdown says what was saved (markdown.file is article.md; markdown.warnings what the conversion missed); beside the PDF it never changes the paper's status.",
            },
            mode: {
                type: "string",
                enum: ["two_phase", "per_item", "entitled_only"],
                default: "two_phase",
                description: "two_phase (default): open stages for every item first, then entitled access only for the items still missing, so browser logins happen in one stretch at the end. per_item: the whole funnel per item. entitled_only: through the school alone: every item goes straight to entitled access, the open stages skipped, and its Markdown made from the article page that visit read (no PubMed Central, no publisher API). 接着下 (resume) goes on with the batch's own mode unless one is given.",
            },
            resume: {
                type: "string",
                description: "Go on with an earlier batch (the user says 接着下, 继续下载, 重试失败的): \"latest\" or a run id as paper-search failures names it. Its papers not saved are downloaded again with its content, those saved without all their supplementary files or without their Markdown (not reached, failed, login lapsed) get only those, beside their PDF, never the PDF again; everything goes into the earlier batch's download folder, and items and content are taken from its run ledger. Run it with the same environment as the earlier batch (its XDG_DATA_HOME, if one was set).",
            },
        },
    },
};
export const PDF_DISCOVERY_TOOLS = [
    DOWNLOAD_PAPER_TOOL,
    DOWNLOAD_WITH_FALLBACK_TOOL,
    DOWNLOAD_BATCH_TOOL,
];
// Without PaperSearch Pro's features (config/edition.ts) the tools have no markdown kind or field.
const OPEN_CONTENT = "What to download: two kinds, each fetched on its own, alone or together. pdf (default) the main text's PDF; supplements the article's supplementary files (no main-text stages; the entitled-access backend visits the article page); both together: \"pdf,supplements\". Supplementary files are saved in the paper's own folder and listed in the result's supplements.";
function withoutMarkdown(tool, description, fields) {
    const { markdown: _markdown, ...properties } = tool.inputSchema.properties;
    for (const [name, change] of Object.entries(fields))
        properties[name] = { ...properties[name], ...change };
    return { ...tool, description, inputSchema: { ...tool.inputSchema, properties } };
}
/** The download tools as this edition offers them: with PaperSearch Pro's features, the Markdown too. */
export function downloadTools(pro = proFeatures()) {
    if (pro)
        return PDF_DISCOVERY_TOOLS;
    return [
        withoutMarkdown(DOWNLOAD_PAPER_TOOL, DOWNLOAD_PAPER_TOOL.description, {
            content: { enum: ["pdf"], description: "pdf (default) the PDF. Supplementary files: download_with_fallback." },
        }),
        withoutMarkdown(DOWNLOAD_WITH_FALLBACK_TOOL, DOWNLOAD_WITH_FALLBACK_TOOL.description, { content: { description: OPEN_CONTENT } }),
        withoutMarkdown(DOWNLOAD_BATCH_TOOL, "Download a list of papers, any number, through the same funnel as download_with_fallback. By default in two phases: open stages for every item first, then entitled access only for the items still missing, with one backend progress window (k / M) for that stretch. Returns the batch's totals, how many papers lack their supplementary files, its folder, and index: the list of every paper's result (_run/article_index.csv); not each paper.", {
            content: { description: OPEN_CONTENT },
            mode: { description: "two_phase (default): open stages for every item first, then entitled access only for the items still missing, so browser logins happen in one stretch at the end. per_item: the whole funnel per item. entitled_only: through the school alone: every item goes straight to entitled access, the open stages skipped. 接着下 (resume) goes on with the batch's own mode unless one is given." },
            resume: { description: "Go on with an earlier batch (the user says 接着下, 继续下载, 重试失败的): \"latest\" or a run id as paper-search failures names it. Its papers not saved are downloaded again with its content, those saved without all their supplementary files (not reached, failed, login lapsed) get only those, beside their PDF, never the PDF again; everything goes into the earlier batch's download folder, and items and content are taken from its run ledger. Run it with the same environment as the earlier batch (its XDG_DATA_HOME, if one was set)." },
        }),
    ];
}
//# sourceMappingURL=tools.js.map