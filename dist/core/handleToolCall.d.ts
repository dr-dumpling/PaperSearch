import type { Searchers } from "./searchers.js";
import type { SchoolBackend } from "../capabilities/pdf-discovery/school/index.js";
export interface ToolCallDependencies {
    schoolBackend?: SchoolBackend;
}
export declare const TOOL_HANDLER_NAMES: string[];
export declare function handleToolCall(toolNameRaw: string, rawArgs: unknown, searchers: Searchers, dependencies?: ToolCallDependencies): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
//# sourceMappingURL=handleToolCall.d.ts.map