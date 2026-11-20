import type { Searchers } from "../../../../core/searchers.js";
import { type SchoolBackend, type SchoolDownloadRequest } from "../../../../infrastructure/school/index.js";
import { type NetworkWatch } from "../../batch/networkLoss.js";
import type { DownloadBatchItemResult } from "../../batch/batch.js";
import type { CapturedFulltextPage, DownloadWithFallbackOptions, DownloadWithFallbackResult, SupplementFile } from "../../types.js";
/**
 * Supplementary files only, for an article whose main text came from another
 * stage. Undefined when no backend can do it.
 */
export declare function fetchSupplementsOnly(backend: SchoolBackend | undefined, request: Omit<SchoolDownloadRequest, "supplements">, onTrace?: (trace: Record<string, unknown>) => void, onFulltextPage?: (page: CapturedFulltextPage) => void): Promise<SupplementFile[] | undefined>;
/**
 * Supplementary files only: the entitled-access backend visits the article
 * page for them. An empty completed check is also ok; it is not a failed download,
 * nor is a site without a supplementary-file rule (user, 2026-11-11). Reported to
 * the run ledger through ``request.onStage`` as the "supplements" stage.
 * ``mainPath``: the paper's main text, saved before; once a file is saved it moves
 * into the paper's folder beside them (the returned ``path``).
 */
export declare function downloadSupplementsOnly(request: DownloadWithFallbackOptions, backend: SchoolBackend | undefined, searchers?: Searchers, mainPath?: string): Promise<DownloadWithFallbackResult>;
/** content "both": supplementary files for an item whose main text came from an open stage. */
export declare function supplementsForOpenItem(result: DownloadBatchItemResult, request: DownloadWithFallbackOptions, backend: SchoolBackend | undefined, searchers: Searchers): Promise<DownloadWithFallbackResult | undefined>;
/**
 * supplementsForOpenItem, asked again after a network loss: the files the lost network
 * failed are fetched anew once it is back (those a first visit found stand otherwise).
 */
export declare function filesPastNetworkLoss(result: DownloadBatchItemResult, request: DownloadWithFallbackOptions, backend: SchoolBackend | undefined, searchers: Searchers, watch: NetworkWatch): Promise<DownloadWithFallbackResult | undefined>;
//# sourceMappingURL=fetch.d.ts.map