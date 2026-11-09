import axios from 'axios';
import { DEFAULT_MAILTO, TIMEOUTS, USER_AGENT } from '../../config/constants.js';
import { ErrorHandler } from '../../infrastructure/http/ErrorHandler.js';
import { logWarn } from '../../utils/Logger.js';
import { plainText } from '../../utils/plainText.js';
import { doiKey } from './OpenAlexGraph.js';
/**
 * Each reference's number in the paper, read from the keys the publisher deposited with Crossref:
 * Elsevier "…_bib9", Springer Nature "…_CR9", Atypon (Wiley, NEJM, AHA) "e_1_2_6_10_1" (that field counts from 2),
 * Wolters Kluwer "R9-…", others "B9", "r9". Trusted only when the numbers rise with the list and skip little;
 * otherwise null (Oxford's, for one, skip hundreds).
 */
const NUMBERING = [[/_bib(\d+)$/i, 0], [/_CR(\d+)$/, 0], [/^e(?:_\d+)+_(\d+)_\d+$/, 1], [/^R(\d+)-\d+$/, 0], [/(\d+)$/, 0]];
export function referenceNumbers(keys) {
    for (const [pattern, offset] of NUMBERING) {
        const numbers = keys.map(key => { const m = (key || '').match(pattern); return m ? Number(m[1]) - offset : NaN; });
        if (!numbers.length || numbers.some(n => !Number.isFinite(n) || n < 1))
            continue;
        if (!numbers.every((n, i) => i === 0 || n > numbers[i - 1]))
            continue;
        if (numbers[numbers.length - 1] - numbers.length <= Math.max(2, Math.ceil(numbers.length * 0.1)))
            return numbers;
    }
    return null;
}
/** The numbers missing from 1 to the last one: references the paper has but the publisher did not deposit. */
export function missingNumbers(papers) {
    const numbers = papers.map(p => p.number).filter((n) => typeof n === 'number');
    if (!numbers.length)
        return [];
    const have = new Set(numbers);
    return Array.from({ length: Math.max(...numbers) }, (_, i) => i + 1).filter(n => !have.has(n));
}
/** A deposited reference; its title is the article's title, or the whole citation as printed when that is all there is. */
function fromDeposit(ref, index, number) {
    const doi = typeof ref.DOI === 'string' ? doiKey(ref.DOI) : undefined;
    return {
        paperId: doi || ref.key || `reference-${index + 1}`,
        title: plainText(ref['article-title'] || ref['volume-title'] || ref['series-title'] || ref.unstructured || ''),
        citationCount: 0,
        referenceCount: 0,
        year: Number.parseInt(ref.year, 10) || undefined,
        authors: ref.author ? [{ name: String(ref.author) }] : undefined,
        venue: plainText(ref['journal-title'] || '') || undefined,
        doi: doi || undefined,
        url: doi ? `https://doi.org/${doi}` : undefined,
        source: 'crossref',
        ...(number ? { number } : {})
    };
}
/**
 * The reference list a publisher deposited with Crossref: the paper's own list, in its order, numbered as in the paper
 * when the keys show it. Open, no key. Some publishers deposit every reference in full (Elsevier, Springer Nature,
 * Frontiers, Wolters Kluwer); others little more than the DOIs (Wiley, NEJM): see `described`.
 */
export class CrossrefReferences {
    mailto;
    client;
    constructor(mailto = DEFAULT_MAILTO) {
        this.mailto = mailto;
        this.client = axios.create({
            baseURL: 'https://api.crossref.org',
            timeout: TIMEOUTS.DEFAULT,
            headers: { Accept: 'application/json', 'User-Agent': `${USER_AGENT} (mailto:${mailto})` }
        });
    }
    async list(doi) {
        try {
            const response = await ErrorHandler.retryWithBackoff(() => this.client.get(`/works/${encodeURIComponent(doiKey(doi))}`, { params: { mailto: this.mailto } }), { context: 'Crossref references lookup' });
            const deposited = response.data?.message?.reference || [];
            const numbers = referenceNumbers(deposited.map(ref => ref.key));
            return deposited.map((ref, i) => fromDeposit(ref, i, numbers?.[i]));
        }
        catch (error) {
            if (error?.response?.status !== 404)
                logWarn(`Crossref references lookup failed for ${doi}:`, error.message);
            return [];
        }
    }
}
/** Whether a deposit says what each reference is (a title or the printed citation), not just its DOI: at least 80% of them. */
export const described = (list) => list.length > 0 && list.filter(ref => ref.title).length >= 0.8 * list.length;
//# sourceMappingURL=CrossrefReferences.js.map