import { extractPages } from "./PdfFirstPage.cjs";
/*
 * One rule for every publisher, layout and decade (2026-11-02, measured on
 * 5,378 PDFs of the maintainer's Zotero library from 1970 to 2026, each also
 * checked against a neighbouring article and the article with the most similar
 * title, and on the acceptance runs). The text of the first pages is normalised
 * so that what extraction and OCR vary (line breaks, hyphenation, spaces inside
 * a DOI, line numbers, superscripts, ligatures, misread letters, reading order)
 * does not matter, and the evidence is weighed:
 * - strong: the whole title, exactly (letters only, at least 50 of them: a
 *   shorter title such as "Nonalcoholic fatty liver disease" also occurs in
 *   other articles' titles and text), standing as a title: an exact match
 *   inside a longer line (another, longer title; a sentence) counts one level
 *   lower;
 * - single: the target DOI; the title with a few misread letters; a shorter
 *   title exactly; a title too short to count alone ("Reply") on its own line
 *   right next to the target DOI's line.
 * Strong evidence, or two single pieces, verify the PDF; one single piece
 * verifies it while the pages print no other DOI (a cited or related article).
 * Other DOIs and no evidence at all: another article. A title's numbers must
 * always be exact ("Type 1" is not "Type 2").
 * Two kinds of document repeat an article's DOI and title without being it,
 * each known by its own heading line: an attachment (supplementary material,
 * disclosure form) and a notice about it (correction, retraction, briefing,
 * letter to the editor). A notice is itself the requested item when the
 * requested title says it is a notice, or when the pages name it (its DOI in
 * the header, or its whole title and its DOI) and print no other DOI: a notice
 * about an article prints its own as well. A DOI the pages label as the article
 * a notice is about ("DOI of original article:", "Correction to:") is no other
 * DOI for the notice itself (a letter that names the article it discusses);
 * when that label points at the requested DOI, the PDF is a notice about it.
 * A scan without a text layer cannot be read: the URL it came from, when that
 * names the DOI, is the evidence, unless what little it prints is a notice, an
 * attachment or another DOI. So is it for pages that print no DOI at all and are
 * no notice or attachment, when the requested item is named like a section rather
 * than an article (a one-page "Journal Club" note, "Issue Information", Wiley 2026-11-12).
 * The backend's pdf_guard.classify reads PDFs by the same evidence.
 */
/** Pages read: the title and DOI are on page 1, or on page 2 after a cover or an opener page. */
const PAGES = 3;
/** Letters a title needs to be strong evidence alone. */
const STRONG_TITLE = 50;
/** Letters a title needs to be evidence at all ("Editorial", "Cover Image" are not). */
const SHORT_TITLE = 15;
/** Letters a title needs before misread letters are allowed in it. */
const CLOSE_TITLE = 25;
/** One misread letter allowed per this many letters of the title. */
const LETTERS_PER_ERROR = 12;
/** Where an attachment or a notice announces itself. */
const HEAD_CHARS = 400;
/** Fewer letters than this on the pages read: a scan without a text layer. */
const SCAN_MAX_LETTERS = 300;
// A reference list cites other articles: its DOIs and titles are not evidence.
const REFERENCES_HEADING = /^\s*(?:references?|literature cited)\s*$/im;
// An attachment's own heading line ("Supplementary Information for …",
// "Supplementary Online Content", "Appendix A", "ICMJE Disclosure Form", a plain
// language summary), not a sentence that starts with the same words.
const ATTACHMENT_HEADING = /^\s*(?:electronic\s+)?(?:supplement(?:ary|al)?|supporting|online(?:\s+only)?)\s+(?:online\s+)?(?:information|materials?|data|content|appendix|methods|figures?|figure legends|tables?|text|files?)\s*(?:for\b.*|:.*)?$|^\s*appendix(?:\s+[a-z0-9])?\s*:?\s*$|^\s*plain language summary\b|^\s*(?:icmje\s+)?disclosure\s+form|^\s*conflicts?\s+of\s+interest\s+(?:form|disclosure)/im;
// A notice's own heading line: the word opens the line, alone or followed by
// ":" or "to" ("CORRECTION", "Correction to: …", "Retraction Note", "RETRACTED
// ARTICLE: …", "Notice of Retraction"), or closes it after a colon ("<title>:
// Erratum"); not a sentence that uses it ("Upper eyelid retraction…",
// "Correction of hallux valgus…").
const NOTICE = /^\s*(?:(?:author|publisher|editorial|notice\s+of|statement\s+of)\s+)?(?:correction|erratum|corrigendum|retraction|retracted|expression of concern|research briefing|letter to the editor)(?:\s+(?:note|notice|article))?\s*(?::|\bto\b|$)|^\s*withdrawn\s*:|:[ \t]*(?:correction|erratum|corrigendum|retraction|expression of concern)[ \t]*$/im;
// A label for the article a notice is about, followed by its DOI ("DOI of original article:
// https://doi.org/…" under an Elsevier letter or reply, 2026-11-12; "Correction to: Nature
// https://doi.org/…"; "The original article can be found online at …").
const ABOUT_LABEL = /\b(?:doi\s+of\s+(?:the\s+)?original\s+article|(?:the\s+)?original\s+article(?:\s+can\s+be\s+found\s+online\s+at|\s+is\s+available\s+(?:online\s+)?at)?|(?:correction|erratum|corrigendum|addendum)\s+to|retraction\s+(?:note\s+|notice\s+)?(?:to|of)|comment(?:ary)?\s+on|(?:in\s+)?(?:reply|response)\s+to|see\s+the\s+article|refers\s+to|linked\s+article)\s*:?/gi;
/** How far after its label the DOI of the article a notice is about may be. */
const ABOUT_REACH = 200;
// A DOI may break right after its prefix ("https://doi.org/10.1016/" then "S0140-…", The Lancet).
const DOI_IN_TEXT = /10\.\d{4,9}\/(?:[ \t]*\n[ \t]*)?[^\s"<>]+/g;
/** Case, invisible characters, typographic dashes and control characters do not matter. */
function normalise(text) {
    return text
        .normalize("NFKC")
        .replace(/[­​-‍⁠﻿]/g, "")
        .replace(/[‐-―−﹘﹣－]/g, "-")
        .replace(/[\x00-\x08\x0e-\x1f\x7f]/g, " ")
        .toLowerCase();
}
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
/** A Crossref title without its markup ("<i>", "&amp;"). */
function plainTitle(title) {
    return title
        .replace(/<[^>]+>/g, " ")
        .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, name) => {
        if (name[0] !== "#")
            return ENTITIES[name.toLowerCase()] ?? entity;
        const code = name[1].toLowerCase() === "x" ? parseInt(name.slice(2), 16) : Number(name.slice(1));
        return Number.isFinite(code) ? String.fromCodePoint(code) : entity;
    });
}
const LETTER = /[a-zЀ-ӿ一-鿿]/;
/**
 * The letters of a normalised text (accents dropped; digits, Greek letters,
 * punctuation and spaces left out), with each letter's position in the text.
 */
function letters(text) {
    let chars = "";
    const at = [];
    for (let i = 0; i < text.length; i++) {
        const base = text[i].normalize("NFD")[0];
        if (LETTER.test(base)) {
            chars += base;
            at.push(i);
        }
    }
    return { chars, at };
}
/** A CJK character carries about as much as a short word. */
function weight(key) {
    return key.length + 2 * (key.match(/[一-鿿]/g)?.length ?? 0);
}
/**
 * Where `key` occurs in `text` with at most `errors` misread, missing or extra
 * letters (approximate substring search): the end of the best match, or -1.
 */
function closeMatchEnd(text, key, errors) {
    const m = key.length;
    let previous = new Int32Array(m + 1).map((_, i) => i);
    let current = new Int32Array(m + 1);
    let best = errors + 1;
    let end = -1;
    for (let j = 0; j < text.length; j++) {
        current[0] = 0;
        for (let i = 1; i <= m; i++) {
            const cost = key[i - 1] === text[j] ? 0 : 1;
            current[i] = Math.min(previous[i - 1] + cost, previous[i] + 1, current[i - 1] + 1);
        }
        if (current[m] < best) {
            best = current[m];
            end = j + 1;
        }
        [previous, current] = [current, previous];
    }
    return end;
}
/**
 * The matched title stands as a title: no words before it on its first line nor
 * after it on its last ("…therapies for obesity in adults" is not the title
 * "Obesity in adults"; "Patient-Related Risk Factors for …" does not show the
 * title "Risk Factors for …").
 */
function standsAlone(text, from, to) {
    const before = text.slice(Math.max(0, from - 80), from);
    const after = text.slice(to, to + 80);
    const newline = after.indexOf("\n");
    return !/[a-z]{2,}/.test(before.slice(before.lastIndexOf("\n") + 1))
        && !/[a-z]{3,}/.test(newline < 0 ? after : after.slice(0, newline));
}
/** The title's numbers, all of them, in the matched stretch of text. */
function numbersMatch(window, title) {
    const wanted = title.match(/\d+/g) ?? [];
    const found = new Set(window.match(/\d+/g) ?? []);
    return wanted.every((number) => found.has(number));
}
function titleEvidence(text, page, title) {
    const plain = normalise(plainTitle(title));
    const key = letters(plain).chars;
    if (weight(key) < SHORT_TITLE)
        return null;
    // The matched stretch, a little wider: a title may start or end with numbers ("…, 2016–2019").
    const windowAt = (end, length) => text.slice(Math.max(0, page.at[Math.max(0, end - length)] - 25), page.at[end - 1] + 26);
    let inside = false;
    for (let at = page.chars.indexOf(key); at >= 0; at = page.chars.indexOf(key, at + 1)) {
        if (!numbersMatch(windowAt(at + key.length, key.length), plain))
            continue;
        if (standsAlone(text, page.at[at], page.at[at + key.length - 1] + 1))
            return weight(key) >= STRONG_TITLE ? "strong" : "single";
        inside = true;
    }
    // Only inside longer lines: part of another title or of a sentence.
    if (inside)
        return weight(key) >= STRONG_TITLE ? "single" : null;
    if (weight(key) < CLOSE_TITLE)
        return null;
    const errors = Math.floor(key.length / LETTERS_PER_ERROR);
    const end = closeMatchEnd(page.chars, key, errors);
    return end > 0 && numbersMatch(windowAt(end, key.length + errors), plain) ? "single" : null;
}
/** The DOI as written in a request: "doi:" and resolver prefixes dropped, lower case. */
function targetDoi(identifier) {
    return identifier.trim().toLowerCase().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/, "");
}
const bare = (doi) => doi.replace(/[^0-9a-z]/g, "");
/** A suffix this long names one article under whichever prefix (Annals moved from 10.1059 to 10.7326). */
const SHARED_SUFFIX = 10;
const suffixOf = (doi) => doi.slice(doi.indexOf("/") + 1);
/**
 * The DOI anywhere, spaces and line breaks inside it ignored, not as part of a
 * longer DOI; a long suffix under another prefix counts too.
 */
function doiNamed(pages, target) {
    if (!/^10\.\d{4,9}\/\S/.test(target))
        return false;
    const pattern = (value) => [...value].map((char) => char.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")).join("\\s*");
    const suffix = suffixOf(target);
    const head = bare(suffix).length >= SHARED_SUFFIX ? "10\\.\\d{4,9}\\/\\s*" : `${pattern(target.slice(0, -suffix.length))}\\s*`;
    return new RegExp(`(?<![0-9.])${head}${pattern(suffix)}(?![0-9a-z_/-]|\\.[0-9a-z])`).test(pages);
}
function cleanDoi(match) {
    return match.replace(/\s+/g, "").replace(/[.,;:)\]]+$/, "");
}
/** `doi` is the target, or a piece, an extension, a misprint or an older prefix of it. */
function sameArticle(doi, target) {
    const own = bare(target);
    const ownSuffix = bare(suffixOf(target));
    return own.startsWith(bare(doi)) || bare(doi).startsWith(own)
        || (ownSuffix.length >= SHARED_SUFFIX && bare(suffixOf(doi)) === ownSuffix);
}
/** DOIs printed that are not the target, nor a piece, an extension, a misprint or an older prefix of it. */
function otherDois(pages, target) {
    return [...pages.matchAll(DOI_IN_TEXT)].map((match) => cleanDoi(match[0])).filter((doi) => !sameArticle(doi, target));
}
/** DOIs the pages label as the article a notice is about: the first DOI after each label. */
function aboutDois(pages) {
    const found = [];
    for (const label of pages.matchAll(ABOUT_LABEL)) {
        const from = (label.index ?? 0) + label[0].length;
        const doi = new RegExp(DOI_IN_TEXT.source).exec(pages.slice(from, from + ABOUT_REACH));
        if (doi)
            found.push(cleanDoi(doi[0]));
    }
    return found;
}
/**
 * A title too short to count alone ("Reply") on its own line within two lines of
 * the target DOI's line (Wiley letters: "DOI 10.1002/…" then "Reply", 2026-11-12).
 */
function shortTitleBesideDoi(text, target, title) {
    const key = letters(normalise(plainTitle(title))).chars;
    if (!key || weight(key) >= SHORT_TITLE)
        return false;
    const lines = text.split("\n");
    return lines.some((line, i) => doiNamed(line, target)
        && [...lines.slice(Math.max(0, i - 2), i), ...lines.slice(i + 1, i + 3)].some((near) => letters(near).chars === key));
}
// A requested item whose title says it is a notice ("…: Erratum", "Reply to …").
const NOTICE_TITLE = /\b(?:erratum|corrigendum|correction|retraction|retracted|withdrawn|expression of concern|reply to|letter)\b/i;
/** The requested title (its first letters) is printed in `text`. */
function titleBefore(text, title) {
    const key = letters(normalise(plainTitle(title))).chars;
    return weight(key) >= SHORT_TITLE && letters(text).chars.includes(key.slice(0, 30));
}
/**
 * An attachment, or a notice about an article (not the requested notice itself).
 * `named`: the pages name the requested item and no other article (identityEvidence).
 */
function notTheArticle(head, title, named) {
    // A supplementary file opens with its heading and names the article after
    // it; an article whose toolbar lists "Supporting Information" below its own
    // title is the article (ACS, 2026-11-02).
    const attachment = ATTACHMENT_HEADING.exec(head);
    if (attachment && !titleBefore(head.slice(0, attachment.index), title))
        return true;
    return NOTICE.test(head) && !named && !NOTICE_TITLE.test(plainTitle(title));
}
/** What the first pages show; null without any text. */
export function identityEvidence(firstPages, identifier, title) {
    if (!firstPages.trim())
        return null;
    const text = normalise(firstPages);
    const front = text.split(REFERENCES_HEADING)[0];
    const target = targetDoi(identifier);
    const doi = doiNamed(front, target);
    let found = title?.trim() ? titleEvidence(front, letters(front), title) : null;
    if (found === null && doi && shortTitleBesideDoi(front, target, title ?? ""))
        found = "single";
    let others = otherDois(front, target);
    const about = aboutDois(front);
    // The article a notice discusses is not another article on these pages.
    if (!about.some((doi) => sameArticle(doi, target)))
        others = others.filter((doi) => !about.includes(doi));
    // A notice is itself the requested item when the pages name it (its DOI in the
    // header, Neurology; its whole title and its DOI, a letter under a "Letter to
    // the editor" heading) and print no other DOI. A notice about an article
    // prints its own DOI as well ("Author Correction" then "Correction to: Nature
    // https://doi.org/<the article>"; a Frontiers corrigendum, 2026-11-02).
    const named = (doiNamed(front.slice(0, HEAD_CHARS), target) || (doi && found === "strong")) && others.length === 0;
    return {
        notArticle: notTheArticle(text.slice(0, HEAD_CHARS), title ?? "", named),
        doi,
        title: found,
        otherDois: others,
    };
}
/** The URL percent-decoded; as given when it does not decode. */
function decoded(url) {
    try {
        return decodeURIComponent(url);
    }
    catch {
        return url;
    }
}
/** The URL a PDF came from names the DOI, not as part of a longer DOI (a ".pdf" may follow). */
function sourceNamesDoi(source, target) {
    if (!/^10\.\d{4,9}\/\S/.test(target))
        return false;
    const doi = target.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
    return new RegExp(`(?<![0-9.])${doi}(?![0-9a-z_/-]|\\.(?!pdf(?![0-9a-z]))[0-9a-z])`).test(decoded(source).toLowerCase());
}
/**
 * The decision on the text of the first pages. `source` is the URL the PDF came
 * from: the only evidence for a scan without a text layer ("source"), when
 * nothing printed points elsewhere (a notice, an attachment, another DOI).
 */
export function assessPdfIdentity(firstPages, identifier, title, source) {
    const evidence = identityEvidence(firstPages, identifier, title);
    if (evidence && !evidence.notArticle) {
        const single = Number(evidence.doi) + Number(evidence.title === "single");
        if (evidence.title === "strong" || single === 2 || (single === 1 && evidence.otherDois.length === 0))
            return "verified";
        if (single === 0 && evidence.otherDois.length)
            return "mismatch";
    }
    const scan = (firstPages.match(/\p{L}/gu) ?? []).length < SCAN_MAX_LETTERS
        && !(evidence && (evidence.notArticle || evidence.otherDois.length));
    // Pages that print no DOI at all and are no notice or attachment, for an item named
    // like a section rather than an article (under CLOSE_TITLE letters: Wiley's "Journal
    // Club" and "Issue Information", 2026-11-12): the URL is the evidence, as for a scan.
    // An article's title not printed is a reason for doubt (an issue's front matter at
    // the article's address).
    const short = weight(letters(normalise(plainTitle(title ?? ""))).chars) < CLOSE_TITLE;
    const noDoi = Boolean(evidence) && short
        && !(evidence.notArticle || evidence.doi || evidence.otherDois.length || evidence.title);
    return source && (scan || noDoi) && sourceNamesDoi(source, targetDoi(identifier)) ? "source" : "unverified";
}
/** Isolate pdf-parse diagnostics and CPU work from CLI JSON output. */
export async function verifyPdfIdentity(filePath, identifier, title, source) {
    const pages = await extractPages(filePath, PAGES);
    if (pages === null)
        return "unreadable";
    return assessPdfIdentity(pages, identifier, title, source);
}
//# sourceMappingURL=PdfIdentity.js.map