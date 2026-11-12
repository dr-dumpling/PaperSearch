import type { DownloadTier } from "../DownloadTier.js";
import { type SchoolBackend, type SchoolDownloadRequest } from "../school/index.js";
import type { SupplementFile } from "../types.js";
export declare function createEntitledAccessTier(backend?: SchoolBackend): DownloadTier;
/**
 * Supplementary files only, for an article whose main text came from another
 * stage. Undefined when no backend can do it.
 */
export declare function fetchSupplementsOnly(backend: SchoolBackend | undefined, request: Omit<SchoolDownloadRequest, "supplements">, onTrace?: (trace: Record<string, unknown>) => void): Promise<SupplementFile[] | undefined>;
//# sourceMappingURL=entitledAccess.d.ts.map