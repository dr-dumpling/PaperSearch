"""Is a captured PDF this article's main text? Evidence from its first pages.

The same rule as PaperSearch's src/infrastructure/pdf/PdfIdentity.ts, with the
same test cases (tests/fixtures/pdf_identity_cases.json). One rule for every
publisher, layout and decade (2026-11-02, measured on 5,378 PDFs of the
maintainer's Zotero library from 1970 to 2026, each also checked against a
neighbouring article and the article with the most similar title). The text of
the first pages is normalised so that what extraction and OCR vary (line breaks,
hyphenation, spaces inside a DOI, line numbers, superscripts, ligatures,
misread letters, reading order) does not matter, and the evidence is weighed:

- strong: the whole title, exactly (letters only, at least 50 of them),
  standing as a title (an exact match inside a longer line counts one level lower);
- single: the target DOI; the title with a few misread letters; a shorter title; a title
  too short to count alone ("Reply") on its own line right next to the target DOI's line.

Strong evidence, or two single pieces, verify the PDF; one single piece verifies
it while the pages print no other DOI. Other DOIs and no evidence at all:
another article. A title's numbers must always be exact. An attachment
(supplementary material, disclosure form) and a notice about the article
(correction, retraction, briefing, letter to the editor), each known by its own
heading line, are not the article, unless the notice is itself the requested
item: its title says so, or the pages name it (its DOI in the header or right above
its copyright line, or its whole title and its DOI) and print no other DOI. A DOI the pages label as the article
a notice is about ("DOI of original article:", "Correction to:") is no other DOI for
the notice itself (a letter that names the article it discusses); when that label
points at the requested DOI, the PDF is a notice about it. A scan without a text layer is
``"source"`` when the URL it came from names the DOI, or its suffix when that is long
enough to name one article (an Elsevier PII) (``assess`` with ``source``;
the frontend passes it, the engine does not); so is a page that prints no DOI at all and is
no notice or attachment, for an item named like a section rather than an article (a
one-page "Journal Club" note, "Issue Information").

``classify`` gives ``"match"`` (verified), ``"other"`` (another article),
``"unknown"`` (no decision: no text layer, or nothing printed) or ``"invalid"``
(not a readable PDF). The caller accepts a match at once, never saves "other",
and keeps an "unknown" file as a fallback to be checked later.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from urllib.parse import unquote

log = logging.getLogger(__name__)

PAGES = 3  # the title and DOI are on page 1, or on page 2 after a cover or an opener page
STRONG_TITLE = 50  # letters a title needs to be strong evidence alone
SHORT_TITLE = 15  # letters a title needs to be evidence at all ("Editorial" is not)
CLOSE_TITLE = 25  # letters a title needs before misread letters are allowed in it
LETTERS_PER_ERROR = 12  # one misread letter allowed per this many letters
HEAD_CHARS = 400  # where an attachment or a notice announces itself
SHARED_SUFFIX = 10  # a suffix this long names one article under whichever prefix
SCAN_MAX_LETTERS = 300  # fewer letters on the pages read: a scan without a text layer

# A reference list cites other articles: its DOIs and titles are not evidence.
_REFERENCES_HEADING = re.compile(r"^\s*(?:references?|literature cited)\s*$", re.I | re.M)
# An attachment's own heading line, not a sentence that starts with the same words.
_ATTACHMENT_HEADING = re.compile(
    r"^\s*(?:electronic\s+)?(?:supplement(?:ary|al)?|supporting|online(?:\s+only)?)\s+(?:online\s+)?"
    r"(?:information|materials?|data|content|appendix|methods|figures?|figure legends|tables?|text|files?)"
    r"\s*(?:for\b.*|:.*)?$|^\s*appendix(?:\s+[a-z0-9])?\s*:?\s*$|^\s*plain language summary\b|^\s*(?:icmje\s+)?disclosure\s+form"
    r"|^\s*conflicts?\s+of\s+interest\s+(?:form|disclosure)", re.I | re.M)
# A notice's own heading line: the word opens the line, alone or followed by ":" or
# "to" ("CORRECTION", "Correction to: …", "Retraction Note", "RETRACTED ARTICLE: …",
# "Notice of Retraction"), or closes it after a colon ("<title>: Erratum"); not a
# sentence that uses it ("Upper eyelid retraction…", "Correction of hallux valgus…").
_NOTICE = re.compile(
    r"^\s*(?:(?:author|publisher|editorial|notice\s+of|statement\s+of)\s+)?"
    r"(?:correction|erratum|corrigendum|retraction|retracted|expression of concern|research briefing|letter to the editor)"
    r"(?:\s+(?:note|notice|article))?\s*(?::|\bto\b|$)|^\s*withdrawn\s*:"
    r"|:[ \t]*(?:correction|erratum|corrigendum|retraction|expression of concern)[ \t]*$", re.I | re.M)
# A requested item whose title says it is a notice ("…: Erratum", "Reply to …").
_NOTICE_TITLE = re.compile(r"\b(?:erratum|corrigendum|correction|retraction|retracted|withdrawn|expression of concern|reply to|letter)\b", re.I)
# A label for the article a notice is about, followed by its DOI ("DOI of original article:
# https://doi.org/…" under an Elsevier letter or reply, 2026-11-12; "Correction to: Nature
# https://doi.org/…"; "The original article can be found online at …").
_ABOUT_LABEL = re.compile(
    r"\b(?:doi\s+of\s+(?:the\s+)?original\s+article|(?:the\s+)?original\s+article(?:\s+can\s+be\s+found\s+online\s+at|\s+is\s+available\s+(?:online\s+)?at)?"
    r"|(?:correction|erratum|corrigendum|addendum)\s+to|retraction\s+(?:note\s+|notice\s+)?(?:to|of)|comment(?:ary)?\s+on"
    r"|(?:in\s+)?(?:reply|response)\s+to|see\s+the\s+article|refers\s+to|linked\s+article)\s*:?", re.I)
_ABOUT_REACH = 200  # how far after its label the DOI of the article a notice is about may be
# A DOI may break right after its prefix ("https://doi.org/10.1016/" then "S0140-…", The Lancet).
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/(?:[ \t]*\n[ \t]*)?[^\s\"<>]+")
_LETTER = re.compile(r"[a-zЀ-ӿ一-鿿]")
# The copyright line right after a DOI ("https://doi.org/…" then "1063-4584/© 2025 …"):
# the item's own footer. Text extraction can put the footer after the reference list
# (Elsevier letters and replies, 2026-11-13).
_COPYRIGHT_AFTER = re.compile(r"\s*(?:\d{4}-\d{3}[\dx]\s*/\s*)?©", re.I)
_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def normalize_doi_text(value: str) -> str:
    """Case, invisible characters, typographic dashes and control characters do not matter."""
    text = unicodedata.normalize("NFKC", value or "")
    text = re.sub("[­​-‍⁠﻿]", "", text)
    text = re.sub("[‐-―−﹘﹣－]", "-", text)
    return re.sub("[\x00-\x08\x0e-\x1f\x7f]", " ", text).lower()


def _plain_title(title: str) -> str:
    """A Crossref title without its markup ("<i>", "&amp;")."""
    def entity(match: re.Match[str]) -> str:
        name = match.group(1)
        if not name.startswith("#"):
            return _ENTITIES.get(name.lower(), match.group(0))
        return chr(int(name[2:], 16) if name[1:2].lower() == "x" else int(name[1:]))
    return re.sub(r"&(#x[0-9a-f]+|#\d+|[a-z]+);", entity, re.sub(r"<[^>]+>", " ", title or ""), flags=re.I)


def _letters(text: str) -> tuple[str, list[int]]:
    """Letters of a normalised text (accents dropped; digits, Greek, punctuation left out) and their positions."""
    chars: list[str] = []
    at: list[int] = []
    for i, char in enumerate(text):
        base = unicodedata.normalize("NFD", char)[0]
        if _LETTER.match(base):
            chars.append(base)
            at.append(i)
    return "".join(chars), at


def _weight(key: str) -> int:
    """A CJK character carries about as much as a short word."""
    return len(key) + 2 * len(re.findall("[一-鿿]", key))


def _close_match_end(text: str, key: str, errors: int) -> int:
    """End of the best match of ``key`` in ``text`` with at most ``errors`` edits, or -1."""
    m = len(key)
    previous = list(range(m + 1))
    best, end = errors + 1, -1
    for j, char in enumerate(text):
        current = [0] * (m + 1)
        for i in range(1, m + 1):
            current[i] = min(previous[i - 1] + (key[i - 1] != char), previous[i] + 1, current[i - 1] + 1)
        if current[m] < best:
            best, end = current[m], j + 1
        previous = current
    return end


def _stands_alone(text: str, start: int, stop: int) -> bool:
    """No words before the matched title on its first line, nor after it on its last."""
    before = text[max(0, start - 80):start]
    after = text[stop:stop + 80]
    line_after = after.split("\n", 1)[0]
    return not re.search(r"[a-z]{2,}", before[before.rfind("\n") + 1:]) and not re.search(r"[a-z]{3,}", line_after)


def _numbers_match(window: str, title: str) -> bool:
    found = set(re.findall(r"[0-9]+", window))
    return all(number in found for number in re.findall(r"[0-9]+", title))


def _title_evidence(text: str, chars: str, at: list[int], title: str) -> str | None:
    plain = normalize_doi_text(_plain_title(title))
    key = _letters(plain)[0]
    if _weight(key) < SHORT_TITLE:
        return None

    def window(end: int, length: int) -> str:
        # The matched stretch, a little wider: a title may start or end with numbers.
        return text[max(0, at[max(0, end - length)] - 25):at[end - 1] + 26]

    inside = False
    exact = chars.find(key)
    while exact >= 0:
        if _numbers_match(window(exact + len(key), len(key)), plain):
            if _stands_alone(text, at[exact], at[exact + len(key) - 1] + 1):
                return "strong" if _weight(key) >= STRONG_TITLE else "single"
            inside = True
        exact = chars.find(key, exact + 1)
    if inside:  # only inside longer lines: part of another title or of a sentence
        return "single" if _weight(key) >= STRONG_TITLE else None
    if _weight(key) < CLOSE_TITLE:
        return None
    errors = len(key) // LETTERS_PER_ERROR
    end = _close_match_end(chars, key, errors)
    return "single" if end > 0 and _numbers_match(window(end, len(key) + errors), plain) else None


def _short_title_beside_doi(text: str, target: str, title: str) -> bool:
    """A title too short to count alone ("Reply") on its own line within two lines of the
    target DOI's line (Wiley letters: "DOI 10.1002/…" then "Reply", 2026-11-12)."""
    key = _letters(normalize_doi_text(_plain_title(title)))[0]
    if not key or _weight(key) >= SHORT_TITLE:
        return False
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _doi_named(line, target) and any(_letters(near)[0] == key for near in lines[max(0, i - 2):i] + lines[i + 1:i + 3]):
            return True
    return False


def _target_doi(identifier: str) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (identifier or "").strip().lower())


def _bare(doi: str) -> str:
    return re.sub(r"[^0-9a-z]", "", doi)


def _suffix(doi: str) -> str:
    return doi[doi.find("/") + 1:]


def _doi_named(pages: str, target: str) -> bool:
    """The DOI anywhere, spaces inside it ignored, not part of a longer DOI; a long suffix under another prefix too."""
    if not re.match(r"10\.\d{4,9}/\S", target):
        return False
    pattern = lambda value: r"\s*".join(re.escape(char) for char in value)  # noqa: E731
    suffix = _suffix(target)
    head = r"10\.\d{4,9}/\s*" if len(_bare(suffix)) >= SHARED_SUFFIX else pattern(target[:-len(suffix)]) + r"\s*"
    return re.search(rf"(?<![0-9.]){head}{pattern(suffix)}(?![0-9a-z_/-]|\.[0-9a-z])", pages) is not None


def _doi_above_copyright(text: str, target: str) -> bool:
    """The target DOI with the copyright line right after it: its own footer, wherever
    the text extraction put it."""
    return any(_bare(_clean_doi(match)) == _bare(target) and _COPYRIGHT_AFTER.match(text, match.end())
               for match in _DOI_IN_TEXT.finditer(text))


def _clean_doi(match: re.Match[str]) -> str:
    return re.sub(r"[.,;:)\]]+$", "", re.sub(r"\s+", "", match.group(0)))


def _same_article(doi: str, target: str) -> bool:
    """``doi`` is the target, or a piece, an extension, a misprint or an older prefix of it."""
    own, own_suffix = _bare(target), _bare(_suffix(target))
    return (own.startswith(_bare(doi)) or _bare(doi).startswith(own)
            or (len(own_suffix) >= SHARED_SUFFIX and _bare(_suffix(doi)) == own_suffix))


def _other_dois(pages: str, target: str) -> list[str]:
    """DOIs printed that are not the target, nor a piece, an extension, a misprint or an older prefix of it."""
    return [doi for doi in map(_clean_doi, _DOI_IN_TEXT.finditer(pages)) if not _same_article(doi, target)]


def _about_dois(pages: str) -> list[str]:
    """DOIs the pages label as the article a notice is about: the first DOI after each label."""
    found = []
    for label in _ABOUT_LABEL.finditer(pages):
        doi = _DOI_IN_TEXT.search(pages, label.end(), label.end() + _ABOUT_REACH)
        if doi:
            found.append(_clean_doi(doi))
    return found


def _title_before(text: str, title: str) -> bool:
    """The requested title (its first letters) is printed in ``text``."""
    key = _letters(normalize_doi_text(_plain_title(title)))[0]
    return _weight(key) >= SHORT_TITLE and key[:30] in _letters(text)[0]


def title_printed(text: str, title: str) -> bool:
    """The title (its first letters) is printed in ``text``, as on the article's own page."""
    return bool((title or "").strip()) and _title_before(normalize_doi_text(text or ""), title)


def _not_the_article(head: str, title: str, named: bool) -> bool:
    """An attachment, or a notice about an article (not the requested notice itself).
    ``named``: the pages name the requested item and no other article (``evidence``)."""
    # A supplementary file opens with its heading and names the article after it;
    # an article whose toolbar lists "Supporting Information" below its own title
    # is the article (ACS, 2026-11-02).
    attachment = _ATTACHMENT_HEADING.search(head)
    if attachment and not _title_before(head[:attachment.start()], title):
        return True
    return bool(_NOTICE.search(head)) and not named and not _NOTICE_TITLE.search(_plain_title(title))


def evidence(first_pages: str, identifier: str, title: str = "") -> dict | None:
    """What the first pages show; None without any text."""
    if not (first_pages or "").strip():
        return None
    text = normalize_doi_text(first_pages)
    front = _REFERENCES_HEADING.split(text, maxsplit=1)[0]
    target = _target_doi(identifier)
    chars, at = _letters(front)
    own_footer = _doi_above_copyright(text, target)
    doi = _doi_named(front, target) or own_footer
    found = _title_evidence(front, chars, at, title) if (title or "").strip() else None
    if found is None and doi and _short_title_beside_doi(front, target, title or ""):
        found = "single"
    others = _other_dois(front, target)
    about = _about_dois(front)
    if not any(_same_article(doi, target) for doi in about):
        # The article a notice discusses is not another article on these pages.
        others = [doi for doi in others if doi not in about]
    # A notice is itself the requested item when the pages name it (its DOI in the
    # header, Neurology; its whole title and its DOI, a letter under a "Letter to the
    # editor" heading) and print no other DOI. A notice about an article prints its
    # own DOI as well ("Author Correction" then "Correction to: Nature
    # https://doi.org/<the article>"; a Frontiers corrigendum, 2026-11-02).
    # Its DOI above its copyright line names it as well as its header does (a letter with
    # a short title, 2026-11-13).
    named = (_doi_named(front[:HEAD_CHARS], target) or own_footer or (doi and found == "strong")) and not others
    return {
        "not_article": _not_the_article(text[:HEAD_CHARS], title or "", named),
        "doi": doi,
        "title": found,
        "other_dois": others,
    }


def _decoded(url: str) -> str:
    """The URL percent-decoded; as given when it does not decode (as decodeURIComponent)."""
    if re.search(r"%(?![0-9a-f]{2})", url, re.I):
        return url
    try:
        return unquote(url, errors="strict")
    except UnicodeDecodeError:
        return url


def _source_names_doi(source: str, target: str) -> bool:
    """The URL a PDF came from names the DOI, not as part of a longer DOI (a ".pdf" may follow)."""
    if not re.match(r"10\.\d{4,9}/\S", target):
        return False
    url = _decoded(source).lower()
    if re.search(rf"(?<![0-9.]){re.escape(target)}(?![0-9a-z_/-]|\.(?!pdf(?![0-9a-z]))[0-9a-z])", url):
        return True
    # A suffix long enough to name one article on its own, as a path segment: an Elsevier
    # PII ("/article/S1063-4584(25)01284-1/pdf" for 10.1016/S1063-4584(25)01284-1, 2026-11-13).
    suffix = _suffix(target)
    return len(_bare(suffix)) >= SHARED_SUFFIX and re.search(
        rf"/{re.escape(suffix)}(?![0-9a-z_-]|\.(?!pdf(?![0-9a-z]))[0-9a-z])", url) is not None


def assess(first_pages: str, identifier: str, title: str = "", source: str = "") -> str:
    """``"verified"``, ``"mismatch"``, ``"source"`` or ``"unverified"`` for the text of the first
    pages. ``source``: the URL the PDF came from, the only evidence for a scan without a text
    layer (``"source"``) when nothing printed points elsewhere."""
    found = evidence(first_pages, identifier, title)
    if found and not found["not_article"]:
        single = int(found["doi"]) + int(found["title"] == "single")
        if found["title"] == "strong" or single == 2 or (single == 1 and not found["other_dois"]):
            return "verified"
        if single == 0 and found["other_dois"]:
            return "mismatch"
    scan = (sum(char.isalpha() for char in first_pages or "") < SCAN_MAX_LETTERS
            and not (found and (found["not_article"] or found["other_dois"])))
    # Pages that print no DOI at all and are no notice or attachment, for an item named
    # like a section rather than an article (under CLOSE_TITLE letters: Wiley's "Journal
    # Club" and "Issue Information", 2026-11-12): the URL is the evidence, as for a scan.
    # An article's title not printed is a reason for doubt (an issue's front matter at
    # the article's address).
    short = _weight(_letters(normalize_doi_text(_plain_title(title)))[0]) < CLOSE_TITLE
    no_doi = bool(found) and short and not (found["not_article"] or found["doi"] or found["other_dois"] or found["title"])
    return "source" if source and (scan or no_doi) and _source_names_doi(source, _target_doi(identifier)) else "unverified"


def first_pages_text(body: bytes) -> str | None:
    """Text of the first pages; None for an unreadable PDF."""
    from .. import pdf_text

    try:
        return pdf_text.text(body, PAGES)
    except pdf_text.PdfError as exc:
        log.info("pdf_guard: unreadable PDF (%s)", type(exc).__name__)
        return None


def classify(body: bytes, doi: str, title: str = "") -> str:
    return classify_with_evidence(body, doi, title)[0]


def classify_with_evidence(body: bytes, doi: str, title: str = "") -> tuple[str, dict | None]:
    """``classify``'s verdict and the evidence behind it (``evidence``: doi,
    title, other_dois, not_article; None for an unreadable PDF or no text)."""
    text = first_pages_text(body)
    if text is None:
        return "invalid", None
    verdict = {"verified": "match", "mismatch": "other"}.get(assess(text, doi, title), "unknown")
    return verdict, evidence(text, doi, title)


def names_other_article(body: bytes, doi: str, title: str = "") -> list[str]:
    """Other articles' DOIs when the PDF names only them (else an empty list); an unreadable PDF passes."""
    text = first_pages_text(body)
    if not text or assess(text, doi, title) != "mismatch":
        return []
    return sorted(set((evidence(text, doi, title) or {}).get("other_dois", [])))
