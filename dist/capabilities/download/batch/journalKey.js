/**
 * A journal's key from its article's DOI, for taking one journal's papers one after another in a batch (PaperSearch
 * Pro's 没权限时换下一所学校, user 2026-11-21: a school switched to for a journal is not switched away from and back).
 * A guess, not the journal's name: the DOI's prefix and the start of its suffix, which most publishers give each
 * journal (10.1016/j.metabol, 10.1007/s00125, 10.1111/dom, 10.1093/eurheartj, 10.1038/s41586, 10.1001/jama,
 * 10.1056/nejmoa); "" for what is no DOI. A key too narrow only groups less; the backend tells journals apart by
 * their ISSN for what it remembers.
 */
export function journalOfDoi(doi) {
    const found = /^(10\.\d{4,9})\/(.+)$/.exec(String(doi ?? "").trim().toLowerCase());
    if (!found)
        return "";
    const [, prefix, suffix] = found;
    const parts = suffix.split(/[./\-(_;]/).filter(Boolean);
    if (!parts.length)
        return prefix;
    // A journal's letters with the article's number run on (nejmoa2300000, MDPI's nu16010001): the letters.
    const first = parts[0].replace(/^([a-z]{2,})\d{6,}$/, "$1");
    return `${prefix}/${(first.length <= 2 || first === "journal") && parts[1] ? `${first}.${parts[1]}` : first}`;
}
/** The queue's next paper: with ``group``, the next one of ``last``'s journal there is, else the first. */
export function takeNext(queue, journalOf, last, group) {
    if (group && last) {
        const at = queue.findIndex((offset) => journalOf(offset) === last);
        if (at >= 0)
            return queue.splice(at, 1)[0];
    }
    return queue.shift();
}
//# sourceMappingURL=journalKey.js.map