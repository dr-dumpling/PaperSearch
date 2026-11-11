export declare const SEARCH_PAPERS_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            query: {
                type: string;
                description: string;
            };
            platform: {
                type: string;
                enum: string[];
                description: string;
            };
            sources: {
                type: string;
                description: string;
            };
            maxResults: {
                type: string;
                minimum: number;
                maximum: number;
                description: string;
            };
            year: {
                type: string;
                description: string;
            };
            author: {
                type: string;
                description: string;
            };
            journal: {
                type: string;
                description: string;
            };
            category: {
                type: string;
                description: string;
            };
            days: {
                type: string;
                description: string;
            };
            fetchDetails: {
                type: string;
                description: string;
            };
            fieldsOfStudy: {
                type: string;
                items: {
                    type: string;
                };
                description: string;
            };
            sortBy: {
                type: string;
                enum: string[];
                description: string;
            };
            sortOrder: {
                type: string;
                enum: string[];
                description: string;
            };
        };
        required: string[];
    };
};
export declare const GET_PAPER_BY_DOI_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            doi: {
                type: string;
                description: string;
            };
            dois: {
                type: string;
                items: {
                    type: string;
                };
                maxItems: number;
                description: string;
            };
            platform: {
                type: string;
                enum: string[];
                description: string;
            };
        };
        required: never[];
    };
};
export declare const METADATA_SEARCH_TOOLS: ({
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            query: {
                type: string;
                description: string;
            };
            platform: {
                type: string;
                enum: string[];
                description: string;
            };
            sources: {
                type: string;
                description: string;
            };
            maxResults: {
                type: string;
                minimum: number;
                maximum: number;
                description: string;
            };
            year: {
                type: string;
                description: string;
            };
            author: {
                type: string;
                description: string;
            };
            journal: {
                type: string;
                description: string;
            };
            category: {
                type: string;
                description: string;
            };
            days: {
                type: string;
                description: string;
            };
            fetchDetails: {
                type: string;
                description: string;
            };
            fieldsOfStudy: {
                type: string;
                items: {
                    type: string;
                };
                description: string;
            };
            sortBy: {
                type: string;
                enum: string[];
                description: string;
            };
            sortOrder: {
                type: string;
                enum: string[];
                description: string;
            };
        };
        required: string[];
    };
} | {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            doi: {
                type: string;
                description: string;
            };
            dois: {
                type: string;
                items: {
                    type: string;
                };
                maxItems: number;
                description: string;
            };
            platform: {
                type: string;
                enum: string[];
                description: string;
            };
        };
        required: never[];
    };
})[];
//# sourceMappingURL=tools.d.ts.map