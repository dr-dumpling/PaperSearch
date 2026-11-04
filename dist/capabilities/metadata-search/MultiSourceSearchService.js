import { TIMEOUTS } from '../../config/constants.js';
import { PaperFactory } from '../../models/Paper.js';
import { withTimeout } from '../../infrastructure/security/SecurityUtils.js';
import { getAliasMap, getDefaultAllSources, getNoKeySources, NO_KEY_SOURCE_ALIASES, resolvePlatformId } from '../../registry/platformMetadata.js';
const ALIASES = getAliasMap();
const NO_KEY_ALIASES = new Set(NO_KEY_SOURCE_ALIASES);
export function parseSourceList(sources, searchers) {
    const requested = !sources || sources.trim() === '' ? 'crossref' : sources.trim();
    if (requested.toLowerCase() === 'all') {
        return getDefaultAllSources().filter(source => source in searchers);
    }
    const expanded = requested
        .split(',')
        .map(source => source.trim().toLowerCase())
        .filter(Boolean)
        .flatMap(source => (NO_KEY_ALIASES.has(source) ? getNoKeySources() : [source]))
        .map(source => ALIASES[source] || resolvePlatformId(source));
    return expanded
        .filter((source, index, values) => values.indexOf(source) === index)
        .filter(source => source in searchers);
}
export async function searchMultipleSources(searchers, query, sources, options, sourceTimeoutMs = TIMEOUTS.SOURCE_TASK) {
    const selected = parseSourceList(sources, searchers);
    const settled = await Promise.allSettled(selected.map(async (source) => {
        const searcher = searchers[source];
        const results = await withTimeout(searcher.search(query, options), sourceTimeoutMs, `${source} search timed out after ${sourceTimeoutMs}ms`);
        return { source, results };
    }));
    const sourceResults = {};
    const errors = {};
    const failedSources = [];
    const merged = [];
    for (let i = 0; i < settled.length; i += 1) {
        const source = selected[i];
        const result = settled[i];
        if (result.status === 'rejected') {
            sourceResults[source] = 0;
            errors[source] = result.reason?.message || String(result.reason);
            failedSources.push(source);
            continue;
        }
        sourceResults[source] = result.value.results.length;
        merged.push(...result.value.results);
    }
    const deduped = dedupePapers(merged);
    return {
        query,
        sources_requested: sources,
        sources_used: selected,
        source_results: sourceResults,
        errors,
        failed_sources: failedSources,
        warnings: failedSources.map(source => `${source}: ${errors[source]}`),
        total: deduped.length,
        raw_total: merged.length,
        papers: deduped.map(paper => PaperFactory.toDict(paper))
    };
}
export function dedupePapers(papers) {
    const positions = new Map();
    const out = [];
    const preprint = (paper) => paper.source === 'arxiv' || /^10\.48550\/arxiv\./i.test(paper.doi);
    for (const paper of papers) {
        const key = paperKey(paper);
        const index = positions.get(key);
        if (index === undefined) {
            positions.set(key, out.length);
            out.push(paper);
            continue;
        }
        const previous = out[index];
        // A known shared DOI links these versions; title resemblance alone does not.
        if (preprint(previous) !== preprint(paper)) {
            const formal = preprint(previous) ? paper : previous;
            const early = preprint(previous) ? previous : paper;
            out[index] = { ...formal, extra: { ...formal.extra,
                    arxivId: early.extra?.arxivId || early.paperId, preprintUrl: early.pdfUrl } };
        }
    }
    return out;
}
function paperKey(paper) {
    const doi = (paper.doi || '').trim().toLowerCase();
    if (doi)
        return `doi:${doi}`;
    const title = (paper.title || '').trim().toLowerCase();
    const authors = (paper.authors || []).join(';').trim().toLowerCase();
    if (paper.source === 'arxiv')
        return `arxiv:${paper.paperId.replace(/v\d+$/, '')}`;
    if (title)
        return `title:${title}|authors:${authors}`;
    return `id:${paper.source || 'unknown'}:${paper.paperId || 'unknown'}`;
}
//# sourceMappingURL=MultiSourceSearchService.js.map