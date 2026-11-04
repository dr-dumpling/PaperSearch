/** Parse only complete arXiv identifiers and official URLs, preserving versions. */
export function normalizeArxivId(value) {
    let id = (value || '').trim();
    if (/^https?:\/\//i.test(id)) {
        try {
            const url = new URL(id);
            if (url.username || url.password)
                return undefined;
            if (['arxiv.org', 'www.arxiv.org', 'export.arxiv.org'].includes(url.hostname.toLowerCase())) {
                if (!/^\/(abs|pdf)\//.test(url.pathname))
                    return undefined;
                id = decodeURIComponent(url.pathname.replace(/^\/(abs|pdf)\//, ''));
            }
            else if (['doi.org', 'dx.doi.org'].includes(url.hostname.toLowerCase())) {
                id = decodeURIComponent(url.pathname.slice(1));
            }
            else
                return undefined;
        }
        catch {
            return undefined;
        }
    }
    id = id.replace(/^doi:\s*/i, '').replace(/^10\.48550\/arxiv\./i, '')
        .replace(/^arxiv:\s*/i, '').replace(/\.pdf$/i, '');
    return /^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?\/\d{7})(?:v[1-9]\d*)?$/i.test(id) ? id : undefined;
}
export function arxivPdfUrl(value) {
    const id = normalizeArxivId(value);
    return id ? `https://arxiv.org/pdf/${id}` : undefined;
}
export function publishedDoi(value) {
    const doi = (value || '').trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, '').toLowerCase();
    return /^10\.\d{4,9}\/\S+$/.test(doi) && !/^10\.48550\/arxiv\./i.test(doi) ? doi : undefined;
}
//# sourceMappingURL=arxiv.js.map