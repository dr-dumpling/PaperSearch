export declare const DOWNLOAD_PAPER_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            paperId: {
                type: string;
                description: string;
            };
            platform: {
                type: string;
                enum: string[];
                description: string;
            };
            savePath: {
                type: string;
                description: string;
            };
            useEntitledAccess: {
                type: string;
                default: boolean;
                description: string;
            };
        };
        required: string[];
    };
};
export declare const DOWNLOAD_WITH_FALLBACK_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            source: {
                type: string;
                description: string;
            };
            paperId: {
                type: string;
                description: string;
            };
            doi: {
                type: string;
                description: string;
            };
            title: {
                type: string;
                description: string;
            };
            savePath: {
                type: string;
                description: string;
            };
            useEntitledAccess: {
                type: string;
                default: boolean;
                description: string;
            };
            useSciHub: {
                type: string;
                description: string;
            };
            content: {
                type: string;
                enum: string[];
                default: string;
                description: string;
            };
            batch: {
                type: string;
                description: string;
                properties: {
                    id: {
                        type: string;
                        description: string;
                    };
                    index: {
                        type: string;
                        minimum: number;
                    };
                    total: {
                        type: string;
                        minimum: number;
                    };
                    done: {
                        type: string;
                        minimum: number;
                    };
                    succeeded: {
                        type: string;
                        minimum: number;
                    };
                    failed: {
                        type: string;
                        minimum: number;
                    };
                };
                required: string[];
            };
        };
        required: string[];
    };
};
export declare const DOWNLOAD_BATCH_TOOL: {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            items: {
                type: string;
                minItems: number;
                maxItems: number;
                description: string;
                items: {
                    type: string;
                    properties: {
                        doi: {
                            type: string;
                        };
                        title: {
                            type: string;
                            description: string;
                        };
                        source: {
                            type: string;
                            description: string;
                        };
                        paperId: {
                            type: string;
                            description: string;
                        };
                        savePath: {
                            type: string;
                            description: string;
                        };
                    };
                };
            };
            savePath: {
                type: string;
                description: string;
            };
            useEntitledAccess: {
                type: string;
                default: boolean;
                description: string;
            };
            useSciHub: {
                type: string;
                description: string;
            };
            content: {
                type: string;
                enum: string[];
                default: string;
                description: string;
            };
            mode: {
                type: string;
                enum: string[];
                default: string;
                description: string;
            };
        };
        required: string[];
    };
};
export declare const PDF_DISCOVERY_TOOLS: ({
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: {
            paperId: {
                type: string;
                description: string;
            };
            platform: {
                type: string;
                enum: string[];
                description: string;
            };
            savePath: {
                type: string;
                description: string;
            };
            useEntitledAccess: {
                type: string;
                default: boolean;
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
            source: {
                type: string;
                description: string;
            };
            paperId: {
                type: string;
                description: string;
            };
            doi: {
                type: string;
                description: string;
            };
            title: {
                type: string;
                description: string;
            };
            savePath: {
                type: string;
                description: string;
            };
            useEntitledAccess: {
                type: string;
                default: boolean;
                description: string;
            };
            useSciHub: {
                type: string;
                description: string;
            };
            content: {
                type: string;
                enum: string[];
                default: string;
                description: string;
            };
            batch: {
                type: string;
                description: string;
                properties: {
                    id: {
                        type: string;
                        description: string;
                    };
                    index: {
                        type: string;
                        minimum: number;
                    };
                    total: {
                        type: string;
                        minimum: number;
                    };
                    done: {
                        type: string;
                        minimum: number;
                    };
                    succeeded: {
                        type: string;
                        minimum: number;
                    };
                    failed: {
                        type: string;
                        minimum: number;
                    };
                };
                required: string[];
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
            items: {
                type: string;
                minItems: number;
                maxItems: number;
                description: string;
                items: {
                    type: string;
                    properties: {
                        doi: {
                            type: string;
                        };
                        title: {
                            type: string;
                            description: string;
                        };
                        source: {
                            type: string;
                            description: string;
                        };
                        paperId: {
                            type: string;
                            description: string;
                        };
                        savePath: {
                            type: string;
                            description: string;
                        };
                    };
                };
            };
            savePath: {
                type: string;
                description: string;
            };
            useEntitledAccess: {
                type: string;
                default: boolean;
                description: string;
            };
            useSciHub: {
                type: string;
                description: string;
            };
            content: {
                type: string;
                enum: string[];
                default: string;
                description: string;
            };
            mode: {
                type: string;
                enum: string[];
                default: string;
                description: string;
            };
        };
        required: string[];
    };
})[];
//# sourceMappingURL=tools.d.ts.map