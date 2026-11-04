import { normalizeArxivId } from '../../../infrastructure/arxiv.js';
import { downloadPdfFromUrl, safeFilename } from '../../../infrastructure/pdf/PdfDownload.js';
import { getCapabilityProfileSources, resolvePlatformId } from '../../../registry/platformMetadata.js';
const OPEN_ACCESS_SOURCE_IDS = new Set(getCapabilityProfileSources('pdf_open_access'));
export function createDirectPdfUrlTier() {
    return {
        id: 'direct_pdf_url',
        stage: 'direct_pdf_url',
        run: tryDirectMetadataUrl
    };
}
async function tryDirectMetadataUrl(context) {
    const searcher = context.searchers[context.source];
    if (!searcher) {
        return { status: 'skipped', message: `No metadata searcher for ${context.source}.` };
    }
    try {
        const lookupId = context.doi || context.paperId;
        const paper = await searcher.getPaperByDoi(lookupId);
        if (!paper?.pdfUrl) {
            return { status: 'skipped', message: 'No pdf_url found in source metadata.' };
        }
        const preprintId = normalizeArxivId(paper.pdfUrl);
        if (preprintId) {
            (context.preprintIds ||= []).push(preprintId);
            return { status: 'skipped', message: 'arXiv PDF deferred until published-version routes finish.' };
        }
        if (!hasOpenAccessProvenance(context.source, paper)) {
            return {
                status: 'skipped',
                message: 'Metadata PDF URL was not downloaded because the record has no explicit open-access provenance.'
            };
        }
        const path = await downloadPdfFromUrl(paper.pdfUrl, context.savePath, `${context.source}_${safeFilename(paper.paperId)}`);
        return { status: 'ok', path, message: path };
    }
    catch (error) {
        return { status: 'error', message: error?.message || String(error) };
    }
}
export function hasOpenAccessProvenance(source, paper) {
    if (paper.extra?.openAccess === true || paper.extra?.isOpenAccess === true)
        return true;
    return OPEN_ACCESS_SOURCE_IDS.has(resolvePlatformId(source));
}
//# sourceMappingURL=directPdfUrl.js.map