/**
 * A journal's key from its article's DOI, for taking one journal's papers one after another in a batch (PaperSearch
 * Pro's 没权限时换下一所学校, user 2026-11-21: a school switched to for a journal is not switched away from and back).
 * A guess, not the journal's name: the DOI's prefix and the start of its suffix, which most publishers give each
 * journal (10.1016/j.metabol, 10.1007/s00125, 10.1111/dom, 10.1093/eurheartj, 10.1038/s41586, 10.1001/jama,
 * 10.1056/nejmoa); "" for what is no DOI. A key too narrow only groups less; the backend tells journals apart by
 * their ISSN for what it remembers.
 */
export declare function journalOfDoi(doi: string | undefined): string;
/** The queue's next paper: with ``group``, the next one of ``last``'s journal there is, else the first. */
export declare function takeNext(queue: number[], journalOf: (offset: number) => string, last: string, group: boolean): number | undefined;
//# sourceMappingURL=journalKey.d.ts.map