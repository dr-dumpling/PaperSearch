import { withTimeout } from '../../../infrastructure/security/SecurityUtils.js';
import { normalizeArxivId, publishedDoi } from '../../../infrastructure/arxiv.js';
import { extractPages } from '../../../infrastructure/pdf/PdfFirstPage.cjs';
import { assessPdfIdentity } from '../../../infrastructure/pdf/PdfIdentity.js';
import { identityRejection } from '../identity.js';
export function assessArxivIdentity(text, id, title) {
    const marks = [...text.matchAll(/(?:^|\n)\s*arXiv:\s*((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?\/\d{7})(?:v\d+)?)(?=\s|$)/gi)]
        .map(match => match[1].toLowerCase());
    const exact = /v\d+$/.test(id);
    if (marks.length)
        return marks.some(mark => exact ? mark === id.toLowerCase() : mark.replace(/v\d+$/, '') === id.toLowerCase())
            ? 'verified' : 'mismatch';
    if (exact)
        return 'unverified';
    return assessPdfIdentity(text, `10.48550/arXiv.${id.replace(/v\d+$/, '')}`, title);
}
export function createPreprintTier() {
    return { id: 'preprint', stage: 'preprint', run: tryPreprint };
}
async function tryPreprint(context) {
    if (context.arxivConflict)
        return { status: 'error', code: 'arxiv_doi_conflict', message: 'arXiv publication DOI differs from the requested DOI.' };
    const searcher = context.searchers.arxiv;
    if (!searcher)
        return { status: 'skipped', message: 'arXiv searcher unavailable.' };
    try {
        let id = context.arxivId;
        let paper = context.arxivPaper;
        const doi = publishedDoi(context.doi);
        if (doi && (!paper || publishedDoi(paper.doi) !== doi)) {
            // A metadata PDF URL is only a candidate, never proof of association.
            id = undefined;
            for (const candidate of [...new Set([context.arxivId, ...(context.preprintIds || [])])].filter(Boolean).slice(0, 3)) {
                const linked = await withTimeout(searcher.getPaperByDoi(candidate), 12_000, 'arXiv metadata lookup timed out');
                if (linked && publishedDoi(linked.doi) === doi) {
                    id = normalizeArxivId(candidate);
                    paper = linked;
                    break;
                }
            }
            if (!id) {
                paper = await withTimeout(searcher.getPaperByDoi(context.doi), 12_000, 'arXiv DOI lookup timed out') || undefined;
                if (!paper && context.searchers.crossref) {
                    // arXiv indexes mixed-case DOIs literally. Crossref's registered
                    // spelling can recover a DOI supplied in lower case; association
                    // still requires exact, case-insensitive DOI equality.
                    const registered = await withTimeout(context.searchers.crossref.getPaperByDoi(doi), 10_000, 'Publication DOI lookup timed out');
                    if (registered && publishedDoi(registered.doi) === doi && registered.doi !== context.doi) {
                        paper = await withTimeout(searcher.getPaperByDoi(registered.doi), 12_000, 'arXiv DOI lookup timed out') || undefined;
                    }
                }
                if (paper && publishedDoi(paper.doi) === doi)
                    id = normalizeArxivId(paper.paperId);
            }
        }
        else if (!id && paper) {
            id = normalizeArxivId(paper.paperId);
        }
        if (!id)
            return { status: 'skipped', message: 'No DOI-linked arXiv preprint found.' };
        context.arxivPaper = paper;
        const path = await searcher.downloadPdf(id, { savePath: context.savePath });
        const text = await extractPages(path, 1);
        const identity = text === null ? 'unreadable' : assessArxivIdentity(text, id, paper?.title || context.title);
        const rejected = identityRejection(identity, path);
        if (rejected)
            return rejected;
        return {
            status: 'ok', path, verified: true, version: 'preprint', arxivId: id,
            ...(publishedDoi(context.doi) ? { publishedDoi: context.doi } : {}),
            code: 'preprint_fallback',
            message: `Downloaded arXiv preprint ${id}; this is not the published version.${context.arxivLookupError ? " Publication metadata was unavailable; publication status is unknown." : ""}`,
            trace: { identity, version: 'preprint', arxivId: id, ...(context.arxivLookupError ? { metadataError: context.arxivLookupError } : {}) }
        };
    }
    catch (error) {
        return { status: 'error', message: error instanceof Error ? error.message : String(error) };
    }
}
//# sourceMappingURL=preprint.js.map