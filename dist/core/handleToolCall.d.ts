import type { Searchers } from "./searchers.js";
import type { CarsiBackend } from "../capabilities/pdf-discovery/carsi/index.js";
export interface ToolCallDependencies {
    carsiBackend?: CarsiBackend;
}
export declare const TOOL_HANDLER_NAMES: string[];
export declare function handleToolCall(toolNameRaw: string, rawArgs: unknown, searchers: Searchers, dependencies?: ToolCallDependencies): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
//# sourceMappingURL=handleToolCall.d.ts.map