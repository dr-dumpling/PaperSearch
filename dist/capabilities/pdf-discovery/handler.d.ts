import type { Searchers } from "../../core/searchers.js";
import { downloadWithFallback } from "./OpenAccessFallbackService.js";
import type { CarsiBackend } from "./carsi/index.js";
import { type DownloadBatchOptions } from "./batch.js";
/**
 * The folder of this download (runDownloadFolder). A caller's own serial batch, several calls with one batch id,
 * keeps the folder its first call got: remembered for two days in the run ledger's batch-folders.json. With the
 * ledger turned off every call gets its own folder.
 */
export declare function downloadRunFolder(savePath?: string, batchId?: string, now?: Date): string;
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