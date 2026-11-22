import type { SchoolBatchPosition, SchoolReadiness, SchoolToolDefinition } from "./types.js";
export declare const CLOSE_BATCH_BROWSER = "school_close_batch_browser";
/** The MCP server name of the bundled backend (school/). */
export declare const ACCEPTED_SERVER_NAMES: Set<string>;
/** Request policy sent to the backend. legal_only is the baseline every backend must accept. */
export type SchoolDownloadStrategy = "legal_only" | "institutional_only";
/** The probe and real invocation must validate and send the same policy. */
export declare function createSchoolDownloadArguments(identifier: string, outputDir: string, strategy?: SchoolDownloadStrategy, batch?: SchoolBatchPosition, supplements?: "with" | "only", userWait?: "short", diagnosticsDir?: string, title?: string, fulltext?: "with" | "only", school?: string): Record<string, string | boolean | number>;
/** Batch progress support advertised by the backend (both optional extensions). */
export interface SchoolBatchSupport {
    /** The download tool declares and accepts the batch_* fields. */
    downloadFields: boolean;
    /** school_batch_progress exists with the expected arguments. */
    progressTool: boolean;
    /** The download tool declares the supplements field. */
    supplementsField: boolean;
    /** The download tool declares the user_wait field. */
    userWaitField: boolean;
    diagnosticsDirField?: boolean;
    /** The download tool declares ``title`` (the paper's title for the PDF identity check). */
    titleField?: boolean;
    /** The download tool declares ``fulltext`` (save the article's full-text page and figures). */
    fulltextField?: boolean;
    /** The download tool declares ``school`` (another saved school for this download alone). */
    schoolField?: boolean;
    keepBrowser?: boolean;
    /** school_batch_progress declares ``results`` (the finished window's summary). */
    progressResults?: boolean;
    /** school_batch_progress declares ``phase`` and ``channel`` (the open-access stretch). */
    progressPhase?: boolean;
    /** school_batch_progress declares ``lanes`` (the open-access lane beside a running download). */
    progressLanes?: boolean;
    /** school_batch_progress declares ``held`` (publishers held, a button to go on with them). */
    progressHeld?: boolean;
    /** school_batch_progress declares ``held_wait`` (only the held publishers left, waiting for the user). */
    progressHeldWait?: boolean;
    /** school_batch_papers exists (the papers behind the window's 成功, 失败 and 剩余). */
    papersTool?: boolean;
    /** school_keep_session exists (a batch's wait keeps the publisher's session alive). */
    keepSessionTool?: boolean;
    /** school_hourly_wait exists (a batch's wait for the hourly limit follows the setting as it changes). */
    hourlyWaitTool?: boolean;
    /** school_switch_state exists (a batch may take one journal's papers one after another). */
    switchStateTool?: boolean;
}
export declare function selectSchoolBatchSupport(tools: readonly SchoolToolDefinition[], strategy: SchoolDownloadStrategy): SchoolBatchSupport;
export declare function validateSchoolContract(serverName: string | undefined, tools: readonly SchoolToolDefinition[]): SchoolReadiness;
/**
 * institutional_only tells the backend to skip its own public/OA race, which
 * PaperSearch has already run. It is only sent when the schema explicitly
 * enumerates the value; a plain string schema keeps legal_only.
 */
export declare function selectSchoolDownloadStrategy(schema: SchoolToolDefinition["inputSchema"]): SchoolDownloadStrategy;
export declare function isCompatibleDownloadSchema(schema: SchoolToolDefinition["inputSchema"]): boolean;
export declare function isCompatibleCacheClearSchema(schema: SchoolToolDefinition["inputSchema"]): boolean;
//# sourceMappingURL=SchoolReadiness.d.ts.map