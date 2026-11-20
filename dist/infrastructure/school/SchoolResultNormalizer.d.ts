import type { SchoolInvocationOutcome } from "./types.js";
export declare class SchoolToolResultError extends Error {
    readonly code: "cache_clear_failed" | "invalid_download_result";
    constructor(code: "cache_clear_failed" | "invalid_download_result");
}
export declare function normalizeCacheClearResult(result: unknown): void;
export declare function normalizeDownloadResult(result: unknown, identifier: string, outputDir?: string, diagnosticsDir?: string): SchoolInvocationOutcome;
//# sourceMappingURL=SchoolResultNormalizer.d.ts.map