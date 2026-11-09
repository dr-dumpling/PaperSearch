const CITATION_LOOKUP_PROPERTIES = {
    paperId: {
        type: 'string',
        description: 'Semantic Scholar paper id or external id such as DOI:10.xxxx/xxxxx'
    },
    doi: {
        type: 'string',
        description: 'DOI for the target paper; converted to DOI:<doi>'
    },
    arxivId: {
        type: 'string',
        description: 'arXiv id for the target paper; converted to ARXIV:<id>'
    }
};
export const GET_PAPER_CITATIONS_TOOL = {
    name: 'get_paper_citations',
    description: 'Get every paper citing a target paper, newest first, from OpenAlex (Semantic Scholar when OpenAlex has no record of it). Provide one of paperId, doi, or arxivId.',
    inputSchema: {
        type: 'object',
        properties: {
            ...CITATION_LOOKUP_PROPERTIES
        }
    }
};
export const GET_PAPER_REFERENCES_TOOL = {
    name: 'get_paper_references',
    description: "Get a paper's whole reference list from one source: the publisher's own list from Crossref, numbered as in the paper, when it describes each reference; otherwise OpenAlex's list; Semantic Scholar's last. Provide one of paperId, doi, or arxivId.",
    inputSchema: {
        type: 'object',
        properties: {
            ...CITATION_LOOKUP_PROPERTIES
        }
    }
};
export const CITATION_EXPANSION_TOOLS = [GET_PAPER_CITATIONS_TOOL, GET_PAPER_REFERENCES_TOOL];
//# sourceMappingURL=tools.js.map