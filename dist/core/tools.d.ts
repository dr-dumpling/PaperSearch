export interface CliTool {
    name: string;
    description: string;
    inputSchema: Record<string, unknown>;
}
/** The tools as this edition offers them: without PaperSearch Pro's features (config/edition.ts), no Markdown. */
export declare function toolList(pro?: boolean): CliTool[];
//# sourceMappingURL=tools.d.ts.map