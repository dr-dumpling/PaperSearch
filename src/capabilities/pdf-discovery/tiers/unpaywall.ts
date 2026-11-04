import { normalizeArxivId } from '../../../infrastructure/arxiv.js';
import type { UnpaywallSearcher } from '../../../platforms/UnpaywallSearcher.js';
import { downloadPdfFromUrl, safeFilename } from '../../../infrastructure/pdf/PdfDownload.js';
import { oaHostPolicy } from '../oaHosts.js';
import type { DownloadTier, DownloadTierContext, DownloadTierResult } from '../DownloadTier.js';

const CANDIDATE_TIMEOUT_MS = 30_000;
const MAX_HTTP_CANDIDATES = 4;

export function createUnpaywallTier(): DownloadTier {
  return {
    id: 'unpaywall',
    stage: 'unpaywall',
    run: tryUnpaywall
  };
}

/**
 * Tries Unpaywall's OA locations in order. Copies on hosts that refuse plain
 * HTTP are not attempted here: they are reported as browser_only and left to
 * the browser stage. arXiv copies are deferred to the final preprint stage.
 */
async function tryUnpaywall(context: DownloadTierContext): Promise<DownloadTierResult> {
  if (!context.doi) {
    return { status: 'skipped', message: 'DOI not provided.' };
  }
  const unpaywall = context.searchers.unpaywall as UnpaywallSearcher | undefined;
  if (!unpaywall?.resolvePdfCandidates) {
    return { status: 'skipped', message: 'Unpaywall searcher unavailable.' };
  }
  try {
    const candidates = await unpaywall.resolvePdfCandidates(context.doi);
    if (candidates.length === 0) {
      return { status: 'skipped', message: 'No OA PDF URL found or email not configured.' };
    }
    const browserHosts = new Set<string>();
    const errors: string[] = [];
    let tried = 0;
    // A published copy, even one only a browser can fetch, beats an accepted or
    // submitted manuscript: earlier versions are used only when none exists.
    const usable = candidates.filter((candidate) => {
      const policy = oaHostPolicy(candidate.url);
      if (policy === 'preprint') {
        const id = normalizeArxivId(candidate.url);
        if (id) (context.preprintIds ||= []).push(id);
      }
      return policy !== 'excluded' && policy !== 'preprint';
    });
    const publishedOnly = usable.some((candidate) => candidate.version === 'publishedVersion');
    for (const candidate of usable) {
      const policy = oaHostPolicy(candidate.url);
      if (publishedOnly && candidate.version !== 'publishedVersion') continue;
      const host = new URL(candidate.url).hostname;
      if (policy === 'browser') {
        browserHosts.add(host);
        continue;
      }
      if (tried >= MAX_HTTP_CANDIDATES) break;
      tried += 1;
      try {
        const path = await downloadPdfFromUrl(candidate.url, context.savePath, `unpaywall_${safeFilename(context.doi)}`, {
          timeoutMs: CANDIDATE_TIMEOUT_MS
        });
        return { status: 'ok', path, message: path, trace: { ...candidate } };
      } catch (error) {
        errors.push(`${host}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    if (browserHosts.size > 0) {
      return {
        status: 'skipped',
        code: 'browser_only',
        message: `Open-access copy on ${[...browserHosts].join(', ')} needs a browser; left to entitled access.`,
        ...(errors.length ? { trace: { errors } } : {})
      };
    }
    if (errors.length > 0) {
      return { status: 'error', message: errors.join('; ') };
    }
    return { status: 'skipped', message: 'No usable published OA PDF location; arXiv is deferred to the final preprint stage.' };
  } catch (error: any) {
    return { status: 'error', message: error?.message || String(error) };
  }
}
