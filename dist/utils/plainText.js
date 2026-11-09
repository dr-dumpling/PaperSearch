const NAMED = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
/**
 * Metadata text as plain text. Crossref deposits keep their markup and HTML
 * entities ("<i>E. coli</i>", "Arthritis &amp; Rheumatology"): tags are dropped,
 * entities decoded, runs of spaces collapsed.
 */
export function plainText(value) {
    return value
        .replace(/<[^>]+>/g, "")
        .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, name) => {
        if (name[0] !== "#")
            return NAMED[name.toLowerCase()] ?? entity;
        const code = /^#x/i.test(name) ? Number.parseInt(name.slice(2), 16) : Number(name.slice(1));
        return Number.isInteger(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : entity;
    })
        .replace(/\s+/g, " ")
        .trim();
}
//# sourceMappingURL=plainText.js.map