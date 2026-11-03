import type { CarsiBatchPosition, CarsiReadiness, CarsiToolDefinition } from "./types.js";
/** The MCP server name of the bundled backend (carsi/). */
export declare const ACCEPTED_SERVER_NAMES: Set<string>;
/** Request policy sent to the backend. legal_only is the baseline every backend must accept. */
export type CarsiDownloadStrategy = "legal_only" | "institutional_only";
/** The probe and real invocation must validate and send the same policy. */
export declare function createCarsiDownloadArguments(identifier: string, outputDir: string, strategy?: CarsiDownloadStrategy, batch?: CarsiBatchPosition, supplements?: "with" | "only", userWait?: "short"): Record<string, string | boolean | number>;
/** Batch progress support advertised by the backend (both optional extensions). */
export interface CarsiBatchSupport {
    /** The download tool declares and accepts the batch_* fields. */
    downloadFields: boolean;
    /** carsi_batch_progress exists with the expected arguments. */
    progressTool: boolean;
    /** The download tool declares the supplements field. */
    supplementsField: boolean;
    /** The download tool declares the user_wait field. */
    userWaitField: boolean;
}
export declare function selectCarsiBatchSupport(tools: readonly CarsiToolDefinition[], strategy: CarsiDownloadStrategy): CarsiBatchSupport;
export declare function validateCarsiContract(serverName: string | undefined, tools: readonly CarsiToolDefinition[]): CarsiReadiness;
/**
 * institutional_only tells the backend to skip its own public/OA race, which
 * PaperSearch has already run. It is only sent when the schema explicitly
 * enumerates the value; a plain string schema keeps legal_only.
 */
export declare function selectCarsiDownloadStrategy(schema: CarsiToolDefinition["inputSchema"]): CarsiDownloadStrategy;
export declare function isCompatibleDownloadSchema(schema: CarsiToolDefinition["inputSchema"]): boolean;
export declare function isCompatibleCacheClearSchema(schema: CarsiToolDefinition["inputSchema"]): boolean;
//# sourceMappingURL=CarsiReadiness.d.ts.map