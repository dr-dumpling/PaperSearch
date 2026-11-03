import type { Searchers } from "../../core/searchers.js";
import { downloadWithFallback } from "./OpenAccessFallbackService.js";
import type { CarsiBackend } from "./carsi/index.js";
import { type DownloadBatchOptions } from "./batch.js";
export declare function handleDownloadPaper(args: {
    paperId: string;
    platform: string;
    savePath?: string;
    useEntitledAccess?: boolean;
}, searchers: Searchers, carsiBackend?: CarsiBackend): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleDownloadWithFallback(args: Parameters<typeof downloadWithFallback>[1], searchers: Searchers, carsiBackend?: CarsiBackend): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleDownloadBatch(args: DownloadBatchOptions, searchers: Searchers, carsiBackend?: CarsiBackend): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
//# sourceMappingURL=handler.d.ts.map