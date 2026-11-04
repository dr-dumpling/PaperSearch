import { PaperSource } from '../../../platforms/PaperSource.js';
import type { DownloadTier, DownloadTierContext, DownloadTierResult } from '../DownloadTier.js';

export function createPrimaryTier(): DownloadTier {
  return {
    id: 'primary',
    stage: 'primary',
    run: tryPrimaryDownload
  };
}

async function tryPrimaryDownload(context: DownloadTierContext): Promise<DownloadTierResult> {
  if (context.source === 'arxiv') return { status: 'skipped', message: 'arXiv is deferred until published-version routes finish.' };
  const primary = (context.searchers as any)[context.source] as PaperSource | undefined;
  if (!primary?.getCapabilities().download) {
    return { status: 'skipped', message: `No primary downloader for ${context.source}` };
  }

  try {
    const path = await primary.downloadPdf(context.paperId, { savePath: context.savePath });
    return { status: 'ok', path, message: path };
  } catch (error: any) {
    return { status: 'error', message: error?.message || String(error) };
  }
}
