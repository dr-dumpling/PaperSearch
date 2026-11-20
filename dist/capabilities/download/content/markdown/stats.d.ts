export interface MarkdownStats {
    converted: number;
    complete: number;
}
export declare function markdownStatsFile(env?: Record<string, string | undefined>): string;
export declare function readMarkdownStats(env?: Record<string, string | undefined>): MarkdownStats;
/** One Markdown saved; ``complete``: nothing noted as possibly missing. */
export declare function recordMarkdownSaved(complete: boolean, env?: Record<string, string | undefined>): void;
//# sourceMappingURL=stats.d.ts.map