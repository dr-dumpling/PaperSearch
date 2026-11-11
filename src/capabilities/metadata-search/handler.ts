import { normalizeArxivId } from '../../infrastructure/arxiv.js';
import type { Searchers } from '../../core/searchers.js';
import { TIMEOUTS } from '../../config/constants.js';
import { PaperFactory, type Paper } from '../../models/Paper.js';
import { PaperSource, type SearchOptions } from '../../platforms/PaperSource.js';
import { logDebug } from '../../utils/Logger.js';
import { withTimeout } from '../../infrastructure/security/SecurityUtils.js';
import {
  getDoiLookupSources,
  getPlatformMetadata,
  resolvePlatformId
} from '../../registry/platformMetadata.js';
import { searchMultipleSources } from './MultiSourceSearchService.js';

function jsonTextResponse(text: string) {
  return {
    content: [
      {
        type: 'text' as const,
        text
      }
    ]
  };
}

function normalizeDoi(value: string): string {
  return value
    .trim()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '')
    .toLowerCase();
}

function paperMatchesDoi(paper: Paper, doi: string): boolean {
  const id = normalizeArxivId(doi);
  if (id && paper.source === 'arxiv') {
    const found = normalizeArxivId(paper.paperId);
    return !!found && (/v\d+$/.test(id) ? found === id : found.replace(/v\d+$/, '') === id);
  }
  return normalizeDoi(paper.doi || '') === normalizeDoi(doi);
}

export async function handleGenericSearch(platform: string, args: any, searchers: Searchers) {
  const resolvedPlatform = resolvePlatformId(platform);
  const searcher = (searchers as any)[resolvedPlatform] as PaperSource | undefined;
  if (!searcher) {
    throw new Error(`Unsupported platform: ${platform}`);
  }

  const { query, ...searchOptions } = args;
  const results = await searcher.search(query, searchOptions as SearchOptions);
  const displayName = getPlatformMetadata(platform)?.displayName || platform;

  return jsonTextResponse(
    `Found ${results.length} ${displayName} papers.\n\n${JSON.stringify(
      results.map((paper: Paper) => PaperFactory.toDict(paper)),
      null,
      2
    )}`
  );
}

export async function handleSearchPapers(args: any, searchers: Searchers) {
  const {
    query,
    platform,
    sources,
    maxResults,
    year,
    author,
    journal,
    category,
    days,
    fetchDetails,
    fieldsOfStudy,
    sortBy,
    sortOrder
  } = args;

  const results: Record<string, any>[] = [];
  const searchOptions: SearchOptions = {
    maxResults,
    year,
    author,
    journal,
    category,
    days,
    fetchDetails,
    fieldsOfStudy,
    sortBy,
    sortOrder
  };

  if (platform === 'all') {
    const result = await searchMultipleSources(searchers, query, sources || 'all', searchOptions);
    return jsonTextResponse(`Found ${result.total} papers across ${result.sources_used.length} source(s).\n\n${JSON.stringify(result, null, 2)}`);
  } else if (sources) {
    const result = await searchMultipleSources(searchers, query, sources, searchOptions);
    return jsonTextResponse(`Found ${result.total} papers across ${result.sources_used.length} source(s).\n\n${JSON.stringify(result, null, 2)}`);
  } else {
    const resolvedPlatform = resolvePlatformId(platform);
    const searcher = (searchers as any)[resolvedPlatform];
    if (!searcher) {
      throw new Error(`Unsupported platform: ${platform}`);
    }

    const platformResults = await (searcher as PaperSource).search(query, searchOptions);
    results.push(...platformResults.map((paper: Paper) => PaperFactory.toDict(paper)));
  }

  return jsonTextResponse(`Found ${results.length} papers.\n\n${JSON.stringify(results, null, 2)}`);
}

/** At most this many DOIs are looked up at the same time; each source keeps its own rate limit. */
const DOI_LOOKUP_CONCURRENCY = 5;

interface DoiLookup {
  doi: string;
  papers: Record<string, any>[];
  sourcesUsed: string[];
  sourceResults: Record<string, number>;
  errors: Record<string, string>;
  failedSources: string[];
  /** Sources that answered (a paper, or none), errors aside: a DOI no source answered for was not checked. */
  answered: number;
}

/** Ask ``sources`` for ``doi`` at the same time; the matching papers, in the order of ``sources``. */
async function lookupFrom(sources: string[], doi: string, searchers: Searchers, lookup: DoiLookup): Promise<Paper[]> {
  const settled = await Promise.allSettled(sources.map(source => withTimeout(
    ((searchers as any)[source] as PaperSource).getPaperByDoi(doi),
    TIMEOUTS.SOURCE_TASK,
    `${source} DOI lookup timed out after ${TIMEOUTS.SOURCE_TASK}ms`
  )));
  const found: Paper[] = [];
  settled.forEach((result, i) => {
    const source = sources[i];
    lookup.sourcesUsed.push(source);
    lookup.sourceResults[source] = 0;
    if (result.status === 'rejected') {
      lookup.errors[source] = result.reason?.message || String(result.reason);
      lookup.failedSources.push(source);
      logDebug(`Error getting paper by DOI from ${source}:`, result.reason);
      return;
    }
    lookup.answered += 1;
    const paper = result.value;
    if (!paper) return;
    if (!paperMatchesDoi(paper, doi)) {
      lookup.errors[source] = `Returned DOI ${paper.doi || '(missing)'} did not match requested DOI ${doi}`;
      lookup.failedSources.push(source);
      return;
    }
    lookup.sourceResults[source] = 1;
    found.push(paper);
  });
  return found;
}

/**
 * One DOI. ``auto`` (the default): Crossref, where DOIs are registered, then the
 * other sources only when it does not know the DOI, the first match kept; waiting
 * on all of them made each DOI take as long as the slowest (Windows 2026-11-11:
 * about 7 s a DOI, Europe PMC alone 2-13 s). ``all``: every source, each copy kept.
 */
async function lookupDoi(doi: string, platform: string, searchers: Searchers): Promise<DoiLookup> {
  const lookup: DoiLookup = { doi, papers: [], sourcesUsed: [], sourceResults: {}, errors: {}, failedSources: [], answered: 0 };
  const available = getDoiLookupSources().filter(source => source in searchers);
  let found: Paper[];
  if (platform === 'all') {
    found = await lookupFrom(available, doi, searchers, lookup);
  } else if (platform === 'auto') {
    found = await lookupFrom(available.filter(source => source === 'crossref'), doi, searchers, lookup);
    if (!found.length) found = await lookupFrom(available.filter(source => source !== 'crossref'), doi, searchers, lookup);
    found = found.slice(0, 1);
  } else {
    const source = resolvePlatformId(platform);
    if (!(searchers as any)[source]) {
      throw new Error(`Unsupported platform: ${platform}`);
    }
    found = await lookupFrom([source], doi, searchers, lookup);
  }
  lookup.papers = found.map(paper => PaperFactory.toDict(paper));
  return lookup;
}

async function inPool<T, R>(items: T[], limit: number, work: (item: T) => Promise<R>): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const at = next++;
      out[at] = await work(items[at]);
    }
  }));
  return out;
}

/**
 * ``get_paper_by_doi``: one DOI (``doi``) or many (``dois``) in one call. The answer
 * has one shape whatever the platform (user, 2026-11-11): every paper in ``papers``;
 * ``not_found`` for DOIs the sources answered for without the paper, ``lookup_failed``
 * for DOIs no source could answer for; ``warnings`` for sources that failed. One DOI
 * also gets its ``doi`` and per-source ``source_results``, ``errors``, ``failed_sources``.
 */
export async function handleGetPaperByDoi(args: { doi?: string; dois?: string[]; platform?: string }, searchers: Searchers) {
  const platform = args.platform || 'auto';
  const seen = new Set<string>();
  const dois = [...(args.dois || []), ...(args.doi ? [args.doi] : [])]
    .map(doi => doi.trim())
    .filter(doi => doi && !seen.has(normalizeDoi(doi)) && seen.add(normalizeDoi(doi)));
  if (!dois.length) {
    throw new Error('Give a DOI in doi, or several in dois.');
  }
  const lookups = await inPool(dois, DOI_LOOKUP_CONCURRENCY, doi => lookupDoi(doi, platform, searchers));
  const papers = lookups.flatMap(lookup => lookup.papers);
  const missing = lookups.filter(lookup => !lookup.papers.length);
  const notFound = missing.filter(lookup => lookup.answered > 0).map(lookup => lookup.doi);
  const lookupFailed = missing.filter(lookup => lookup.answered === 0).map(lookup => lookup.doi);
  const found = dois.length - missing.length;
  const one = lookups.length === 1 ? lookups[0] : undefined;
  const data = {
    ...(one ? { doi: one.doi } : {}),
    sources_requested: platform,
    requested: dois.length,
    found,
    not_found: notFound,
    lookup_failed: lookupFailed,
    total: papers.length,
    papers,
    sources_used: [...new Set(lookups.flatMap(lookup => lookup.sourcesUsed))],
    ...(one ? { source_results: one.sourceResults, errors: one.errors, failed_sources: one.failedSources } : {}),
    warnings: lookups.flatMap(lookup => lookup.failedSources.map(source =>
      `${one ? '' : `${lookup.doi} `}${source}: ${lookup.errors[source]}`)),
  };
  // The first line holds no DOI: the CLI reads the JSON from the first bracket on.
  const summary = `DOI lookup: ${found} of ${dois.length} found`
    + (lookupFailed.length ? `, ${lookupFailed.length} could not be checked` : '')
    + (platform === 'all' ? `; ${papers.length} record(s) from ${data.sources_used.length} source(s)` : '')
    + '.';
  return jsonTextResponse(`${summary}\n\n${JSON.stringify(data, null, 2)}`);
}
