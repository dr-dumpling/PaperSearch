import type { CarsiInvocationOutcome } from "./types.js";
export declare class CarsiToolResultError extends Error {
    readonly code: "cache_clear_failed" | "invalid_download_result";
    constructor(code: "cache_clear_failed" | "invalid_download_result");
}
export declare function normalizeCacheClearResult(result: unknown): void;
export declare function normalizeDownloadResult(result: unknown, identifier: string, outputDir?: string): CarsiInvocationOutcome;
//# sourceMappingURL=CarsiResultNormalizer.d.ts.map