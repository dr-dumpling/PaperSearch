import type { CitationData } from './types.js';
export declare function referenceNumbers(keys: Array<string | undefined>): number[] | null;
/** The numbers missing from 1 to the last one: references the paper has but the publisher did not deposit. */
export declare function missingNumbers(papers: CitationData[]): number[];
/**
 * The reference list a publisher deposited with Crossref: the paper's own list, in its order, numbered as in the paper
 * when the keys show it. Open, no key. Some publishers deposit every reference in full (Elsevier, Springer Nature,
 * Frontiers, Wolters Kluwer); others little more than the DOIs (Wiley, NEJM): see `described`.
 */
export declare class CrossrefReferences {
    private readonly mailto;
    private readonly client;
    constructor(mailto?: string);
    list(doi: string): Promise<CitationData[]>;
}
/** Whether a deposit says what each reference is (a title or the printed citation), not just its DOI: at least 80% of them. */
export declare const described: (list: CitationData[]) => boolean;
//# sourceMappingURL=CrossrefReferences.d.ts.map