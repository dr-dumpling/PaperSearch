import type { DownloadTier } from "../DownloadTier.js";
import { type CarsiBackend, type CarsiDownloadRequest } from "../carsi/index.js";
import type { SupplementFile } from "../types.js";
export declare function createEntitledAccessTier(backend?: CarsiBackend): DownloadTier;
/**
 * Supplementary files only, for an article whose main text came from another
 * stage. Undefined when no backend can do it.
 */
export declare function fetchSupplementsOnly(backend: CarsiBackend | undefined, request: Omit<CarsiDownloadRequest, "supplements">, onTrace?: (trace: Record<string, unknown>) => void): Promise<SupplementFile[] | undefined>;
//# sourceMappingURL=entitledAccess.d.ts.map