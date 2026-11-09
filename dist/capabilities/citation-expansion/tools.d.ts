export declare const GET_PAPER_CITATIONS_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            paperId: {
                type: string;
                description: string;
            };
            doi: {
                type: string;
                description: string;
            };
            arxivId: {
                type: string;
                description: string;
            };
        };
    };
};
export declare const GET_PAPER_REFERENCES_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            paperId: {
                type: string;
                description: string;
            };
            doi: {
                type: string;
                description: string;
            };
            arxivId: {
                type: string;
                description: string;
            };
        };
    };
};
export declare const CITATION_EXPANSION_TOOLS: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            paperId: {
                type: string;
                description: string;
            };
            doi: {
                type: string;
                description: string;
            };
            arxivId: {
                type: string;
                description: string;
            };
        };
    };
}[];
//# sourceMappingURL=tools.d.ts.map