import type { DownloadTier, DownloadTierContext, DownloadTierResult } from '../../DownloadTier.js';

export function createSciHubTier(): DownloadTier {
  return {
    id: 'scihub',
    stage: 'scihub',
    run: trySciHub
  };
}

async function trySciHub(context: DownloadTierContext): Promise<DownloadTierResult> {
  if (!context.useSciHub) {
    return { status: 'skipped', message: 'Sci-Hub fallback disabled by useSciHub=false.' };
  }

  const identifier = context.doi || context.title || context.paperId;
  try {
    const path = await context.searchers.scihub.downloadPdf(identifier, { savePath: context.savePath });
    return { status: 'ok', path, message: path };
  } catch (error: any) {
    return { status: 'error', message: error?.message || String(error) };
  }
}
