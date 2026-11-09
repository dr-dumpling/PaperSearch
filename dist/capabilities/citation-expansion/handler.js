import CitationService from './CitationService.js';
import { CrossrefReferences, described, missingNumbers } from './CrossrefReferences.js';
import { KEYLESS_PAGING_LIMIT, OpenAlexGraph, newestFirst } from './OpenAlexGraph.js';
import { apiKeyHint } from '../../config/apiKeySignup.js';
function jsonTextResponse(text) {
    return {
        content: [
            {
                type: 'text',
                text
            }
        ]
    };
}
export function resolveCitationTarget(args) {
    if (args.paperId)
        return args.paperId;
    if (args.doi)
        return `DOI:${args.doi}`;
    if (args.arxivId)
        return `ARXIV:${args.arxivId}`;
    throw new Error('Provide paperId, doi, or arxivId');
}
/** One source per answer (provider); notes say why when it is not the usual one, or what is missing. */
export function citationResponse(target, relation, provider, papers, extra = {}, notes = []) {
    return { target, relation, provider, total: papers.length, ...extra, papers, ...(notes.length ? { notes } : {}) };
}
/** The target's DOI: given, or looked up on Semantic Scholar for a paper id or arXiv id. */
async function targetDoi(target, service) {
    const given = target.match(/^DOI:(.+)$/i);
    if (given)
        return given[1];
    return (await service.getCitationData(target))?.doi || undefined;
}
/** Semantic Scholar answers at most this many in one request; it is asked only when the others have nothing. */
export const SEMANTIC_SCHOLAR_MAX = 1000;
const reply = (found, notes, result) => jsonTextResponse(`${found}${notes.length ? ` ${notes.join(' ')}` : ''}\n\n${JSON.stringify(result, null, 2)}`);
/** Every citing paper OpenAlex knows, newest first; Semantic Scholar only when OpenAlex has no record of the paper. */
export async function handleGetPaperCitations(args) {
    const target = resolveCitationTarget(args);
    const service = new CitationService();
    const doi = await targetDoi(target, service);
    const graph = new OpenAlexGraph();
    const work = doi ? await graph.work(doi) : null;
    if (work) {
        const papers = await graph.citedBy(work.id);
        const notes = !graph.keyed && papers.length >= KEYLESS_PAGING_LIMIT && work.citedByCount > papers.length
            ? [`OpenAlex counts ${work.citedByCount} citing papers; without an API key it lists the newest ${KEYLESS_PAGING_LIMIT}. OPENALEX_API_KEY (free) lists them all: ${apiKeyHint('OPENALEX_API_KEY')}`] : [];
        return reply(`Found ${papers.length} citing paper(s).`, notes, citationResponse(target, 'citations', 'openalex', papers, { citedByCount: work.citedByCount }, notes));
    }
    const papers = await service.getCitations(target, SEMANTIC_SCHOLAR_MAX);
    const notes = [doi ? 'OpenAlex has no record of this paper; these come from Semantic Scholar.' : 'Without a DOI OpenAlex cannot be asked; these come from Semantic Scholar.'];
    return reply(`Found ${papers.length} citing paper(s).`, notes, citationResponse(target, 'citations', 'semantic_scholar', papers, {}, notes));
}
/**
 * One source for the whole list: the publisher's own list from Crossref when it says what each reference is (numbered
 * as in the paper); OpenAlex's when the publisher deposited no more than DOIs, or nothing; Semantic Scholar's last.
 */
export async function handleGetPaperReferences(args) {
    const target = resolveCitationTarget(args);
    const service = new CitationService();
    const doi = await targetDoi(target, service);
    const notes = [];
    if (doi) {
        const deposit = await new CrossrefReferences().list(doi);
        if (described(deposit)) {
            const missing = missingNumbers(deposit);
            const numberedTo = Math.max(0, ...deposit.map(p => p.number || 0));
            if (missing.length)
                notes.push(`The paper's list is numbered to ${numberedTo}; the publisher deposited ${deposit.length} of them with Crossref, not #${missing.join(', #')}.`);
            const extra = numberedTo ? { numberedTo, missing } : {};
            return reply(`Found ${deposit.length} cited reference(s).`, notes, citationResponse(target, 'references', 'crossref', deposit, extra, notes));
        }
        const graph = new OpenAlexGraph();
        const work = await graph.work(doi);
        if (work?.referencedWorks.length) {
            const papers = (await graph.works(work.referencedWorks)).sort(newestFirst);
            if (papers.length) {
                if (deposit.length)
                    notes.push(`The publisher deposited little more than DOIs with Crossref; this is OpenAlex's list.`);
                const gone = work.referencedWorks.length - papers.length;
                if (gone > 0)
                    notes.push(`OpenAlex lists ${work.referencedWorks.length} references; ${gone} of them it has no record of any more.`);
                return reply(`Found ${papers.length} cited reference(s).`, notes, citationResponse(target, 'references', 'openalex', papers, {}, notes));
            }
        }
    }
    const listed = await service.getReferenceList(target, SEMANTIC_SCHOLAR_MAX);
    const elsewhere = doi ? 'Neither Crossref nor OpenAlex lists references for this paper' : 'Without a DOI only Semantic Scholar can be asked';
    notes.push(listed.papers.length ? `${elsewhere}; these come from Semantic Scholar.`
        : `${elsewhere}, and Semantic Scholar ${listed.withheld ? "withholds them at the publisher's request" : 'has none'}.`);
    return reply(`Found ${listed.papers.length} cited reference(s).`, notes, citationResponse(target, 'references', 'semantic_scholar', listed.papers, {}, notes));
}
//# sourceMappingURL=handler.js.map