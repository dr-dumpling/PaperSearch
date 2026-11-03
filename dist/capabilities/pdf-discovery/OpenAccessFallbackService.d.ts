import type { Searchers } from "../../core/searchers.js";
import { type PdfIdentityStatus } from "../../infrastructure/pdf/PdfIdentity.js";
import type { DownloadTier } from "./DownloadTier.js";
import type { DownloadWithFallbackOptions, DownloadWithFallbackResult } from "./types.js";
import type { CarsiBackend } from "./carsi/index.js";
export type { DownloadTier, DownloadTierContext, DownloadTierResult, } from "./DownloadTier.js";
export type { DownloadWithFallbackOptions, DownloadWithFallbackResult, } from "./types.js";
export declare function createDefaultDownloadTiers(carsiBackend?: CarsiBackend): DownloadTier[];
export declare function insertDownloadTierBefore(tiers: DownloadTier[], beforeStage: string, tier: DownloadTier): DownloadTier[];
export interface DownloadFallbackLimits {
    /** Wall-clock cap per non-entitled stage (entitled access has its own). */
    stageTimeoutMs?: number;
}
export declare function downloadWithFallback(searchers: Searchers, options: DownloadWithFallbackOptions, tiers?: DownloadTier[], limits?: DownloadFallbackLimits, verifyIdentity?: PdfIdentityCheck): Promise<DownloadWithFallbackResult>;
export type PdfIdentityCheck = (path: string, identifier: string, title?: string) => Promise<PdfIdentityStatus>;
//# sourceMappingURL=OpenAccessFallbackService.d.ts.map