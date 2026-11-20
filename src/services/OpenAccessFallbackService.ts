export {
  createDefaultDownloadTiers,
  downloadWithFallback,
  insertDownloadTierBefore
} from '../capabilities/download/content/pdf/OpenAccessFallbackService.js';

export type {
  DownloadTier,
  DownloadTierContext,
  DownloadTierResult
} from '../capabilities/download/content/pdf/DownloadTier.js';

export type {
  DownloadWithFallbackOptions,
  DownloadWithFallbackResult
} from '../capabilities/download/types.js';
