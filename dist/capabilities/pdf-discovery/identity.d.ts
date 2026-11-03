import type { PdfIdentityStatus } from "../../infrastructure/pdf/PdfIdentity.js";
import type { DownloadTierResult } from "./DownloadTier.js";
/**
 * The error result for a saved PDF that is not verifiably this article; null when
 * verified, or when a scan without text came from a URL naming the DOI ("source").
 */
export declare function identityRejection(identity: PdfIdentityStatus, path: string): DownloadTierResult | null;
//# sourceMappingURL=identity.d.ts.map