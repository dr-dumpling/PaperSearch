import { normalizeArxivId, publishedDoi } from '../../infrastructure/arxiv.js';
import { sanitizeDoi, withTimeout } from '../../infrastructure/security/SecurityUtils.js';
/** Resolve an arXiv input to its explicitly linked published DOI before any PDF. */
export async function prepareArxiv(context) {
    const id = normalizeArxivId(context.paperId) || normalizeArxivId(context.doi);
    if (!id) {
        if (!context.doi)
            context.doi = publishedDoi(context.paperId) ? sanitizeDoi(context.paperId).sanitized : undefined;
        return;
    }
    context.arxivId = id;
    const givenDoi = publishedDoi(context.doi);
    let paper = null;
    try {
        const searcher = context.searchers.arxiv;
        if (searcher)
            paper = await withTimeout(searcher.getPaperByDoi(id), 12_000, 'arXiv metadata lookup timed out');
    }
    catch (error) {
        context.arxivLookupError = error instanceof Error ? error.message : String(error);
    }
    const linkedDoi = publishedDoi(paper?.doi);
    if (givenDoi && linkedDoi && givenDoi !== linkedDoi) {
        // Conflicting supplied DOI: try that formal paper, but never silently use
        // an unrelated preprint as its fallback.
        context.arxivId = undefined;
        context.arxivConflict = true;
    }
    context.arxivPaper = paper || undefined;
    const doi = givenDoi || linkedDoi;
    if (doi) {
        context.doi = doi;
        context.paperId = doi;
        context.source = 'crossref';
        context.title = undefined; // published and preprint titles can differ
    }
    else {
        context.doi = undefined;
        context.arxivOnly = true;
    }
}
//# sourceMappingURL=arxiv.js.map