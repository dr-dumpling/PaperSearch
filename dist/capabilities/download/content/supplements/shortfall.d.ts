import { type SchoolBatchResults } from "../../../../infrastructure/school/index.js";
import type { DownloadBatchItemResult, DownloadBatchResult } from "../../batch/batch.js";
/**
 * The reason a paper whose main text was saved still lacks supplementary files:
 * its first file not saved, a real failure before "no rule for this site".
 * A paper without its main text is told by its main text's reason instead.
 */
export declare function supplementShortfall(item: DownloadBatchItemResult): string | undefined;
/** Supplementary files a saved paper is missing (content "both"): the class and the reason in a few words. */
export declare function supplementsMissing(item: DownloadBatchItemResult, content: DownloadBatchResult["content"]): Pick<SchoolBatchResults["supplement_failures"][number], "cls" | "reason"> | undefined;
//# sourceMappingURL=shortfall.d.ts.map