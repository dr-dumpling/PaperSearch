import type { DownloadTier } from "../DownloadTier.js";
import { type PublisherApiAdapter, type PublisherApiEnv } from "../publisherApi/index.js";
/** For tests: forget remembered rejections. */
export declare function resetRejectedPublisherKeys(): void;
/**
 * `publisher_api`: the user's own publisher API keys fetch full text over
 * plain HTTPS (Elsevier PDF, Springer JATS). Runs after the open-access tiers
 * and before Sci-Hub; it never opens a browser and never needs the entitled
 * access backend. See ADR 0007.
 */
export declare function createPublisherApiTier(adapters?: readonly PublisherApiAdapter[], env?: PublisherApiEnv): DownloadTier;
//# sourceMappingURL=publisherApi.d.ts.map