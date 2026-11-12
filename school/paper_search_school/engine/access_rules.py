"""May the reader read this article? One rule for each question, the same for
every publisher (``batch_access.py`` applies them to the open page).

A page is in one of three states:

- ``OUT``: a login, identity-provider or school-chooser page; or a page that
  offers the article for sale, shows only its abstract, puts it behind "Get
  access" / "Access through <school>", or says the reader has no access;
- ``IN``: the publisher names the signed-in institution (a session line such as
  "Brought to you by <school>", or the institution label in its page header),
  or says the reader may read the article (an open, free or full access badge,
  a Creative Commons licence, the full-text sections, "Subscribed");
- ``UNKNOWN``: neither. The PDF is tried first; the login follows when that fails.

The whole visible text is read, line by line. The first 5,000 characters missed
the access lines of long pages (Nature's "You have full access to this article
via <school>.", Optica's "Not Accessible", the access boxes of Taylor & Francis
and journals.lww.com, 2026-11-01), and each of those sites had grown a rule of
its own. Words every page header shows ("Institutional login", "Access through
your institution" in a menu) say nothing about the article, either way.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

IN, OUT, UNKNOWN = "in", "out", "unknown"

# --- Login, identity-provider and chooser pages --------------------------------
# Matched in the lower-case host and path, never the query: return addresses in
# the query name the article ("/action/showLogin?uri=/doi/pdf/<DOI>").
AUTH_PATHS = (
    "/login", "/logon", "/signin", "/sign-in", "/saml", "/sso/", "/shibboleth", "/shibauth/",
    "ssostart", "/action/showlogin", "/action/idlogin", "/institutional-login", "/wayf", "/idp/", "/cas/",
)
AUTH_HOST_PREFIXES = ("login.", "logon.", "sso.", "idp.", "auth.", "signin.", "wayf.", "wayfinder.",
                      "shibboleth.", "passport.")
AUTH_HOSTS = ("openathens.net", "seamlessaccess.org")


def is_auth_url(url: str, extra_markers: tuple[str, ...] = ()) -> bool:
    """A login, identity-provider or chooser address (``extra_markers``: a profile's own)."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    where = host + parsed.path.lower()
    return (any(marker in where for marker in AUTH_PATHS)
            or any(marker.lower() in where for marker in extra_markers if marker)
            or host.startswith(AUTH_HOST_PREFIXES)
            or any(host == domain or host.endswith("." + domain) for domain in AUTH_HOSTS))


# Second-level registry suffixes of country domains, under which a site's own
# domain has three labels: example.edu.cn, example.ac.uk, and Japan's and Korea's
# go.jp, or.jp, ne.jp, ed.jp, or.kr, re.kr (www.jstage.jst.go.jp was "go.jp" and
# koreascience.or.kr "or.kr", review 2026-11-02), and other common ones. No
# public-suffix list: none is a dependency.
_SECOND_LEVEL = frozenset({
    "ac", "co", "com", "edu", "gov", "net", "org",  # most countries
    "ad", "ed", "go", "gr", "lg", "ne", "or",  # Japan; or, go and ne in Korea too
    "pe", "re",  # Korea
    "gob", "gv", "mil", "nhs", "nic", "ltd", "plc", "res", "sch",  # Spain and Mexico, Austria, India, the UK
})


def registrable_domain(host: str) -> str:
    """The domain a site registered: ``idp.example.edu.cn`` -> ``example.edu.cn``,
    ``login.example.org`` -> ``example.org``, ``www.jstage.jst.go.jp`` -> ``jst.go.jp``."""
    labels = [label for label in str(host or "").lower().strip(".").split(".") if label]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


# Article views a site redirects to when the reader may not read the article:
# Silverchair's /article-abstract/ (ACS, Oxford Academic, Karger, RSC, JAMA) and
# ScienceDirect's /abs/pii/.
_ABSTRACT_ONLY = re.compile(r"/article-abstract/|/abs/pii/", re.I)


# The publisher shows the article as accepted, its full text not online yet:
# Optica's page "This paper has been accepted for publication. The DOI ... has been
# registered ... will redirect to the published article when available" (2026-11-08).
_NOT_YET_PUBLISHED = (("accepted for publication", "redirect to the published article when available"),)


def not_yet_published(text: str) -> bool:
    flat = " ".join(text.lower().split())
    return any(all(marker in flat for marker in markers) for markers in _NOT_YET_PUBLISHED)


def abstract_only(url: str) -> bool:
    return bool(_ABSTRACT_ONLY.search(urlparse(url or "").path))


# --- B: the institution's session -----------------------------------------------
# A line that says who gives the access: ScienceDirect "Brought to you by:" (the
# name on the next line), Springer Nature "You have full access to this article
# via <school>.", Optica "Access provided by <school>", Wiley "Access By<school>".
_SESSION_LINE = re.compile(
    r"(?P<prefix>brought to you by|access (?:provided|funded) by|access by|provided by"
    r"|you have (?:full )?access(?: to this (?:article|content|chapter))? (?:via|through)"
    r"|(?:logged|signed) in (?:via|through))(?P<name>.*)", re.I)
# "Access by" and a bare "provided by" are sessions only for an institution's name
# ("Provided by the Springer Nature SharedIt content-sharing initiative" is not).
_BARE_PREFIXES = ("access by", "provided by")
INSTITUTION_WORD = re.compile(
    r"universit|college|institut|hospital|school|academ|librar|polytechnic|cent(?:er|re)|council|"
    r"ministry|foundation|consortium|大学|学院|医院|研究所|研究院|图书馆|中心", re.I)
# Help and example copy quote these lines; so do conditionals ("If you have ...").
_EXAMPLE_CONTEXT = re.compile(r"\b(?:faq|frequently asked questions|example|if)\b", re.I)

# Words that name no institution: "Institutional login", "Log in via your
# institution", "Access through your organization", "University" alone.
_GENERIC_WORDS = frozenset("""
a an the your our my this another other any institution institutions institutional
organization organisation organizations organisations university universities library libraries school
login log logon logged in on sign signed signin via through with by from access accessed provided funded
select find choose change switch search user users member members account accounts personal individual
subscription subscriptions subscriber subscribers not or and here to for of now please
shibboleth openathens athens federated federation sso
""".split())
_GENERIC_CJK = re.compile("机构|登录|登陆|选择|您的|你的|学校|院校|单位|认证|访问|通过|个人|账户|账号")


def is_generic_label(label: str) -> bool:
    """True when ``label`` names no institution of its own."""
    text = str(label or "").lower()
    if any(len(word) >= 2 and not word.isdigit() and word not in _GENERIC_WORDS
           for word in re.findall(r"[a-z0-9]+", text)):
        return False
    return not _GENERIC_CJK.sub("", "".join(re.findall(r"[一-鿿]", text)))


def lines_of(text: str) -> list[str]:
    return [" ".join(line.split()) for line in str(text or "").splitlines() if line.strip()]


def session_names(lines: list[str]) -> list[str]:
    """Institution names in the page's session lines; help copy, quotes and
    generic labels are not sessions."""
    names: list[str] = []
    for index, line in enumerate(lines):
        match = _SESSION_LINE.match(line)
        if not match or _EXAMPLE_CONTEXT.search(" ".join(lines[max(0, index - 1):index])):
            continue
        rest = match.group("name").strip()
        if rest in ("", ":") and index + 1 < len(lines):
            rest = lines[index + 1]  # "Brought to you by:" with the name below
        name = re.sub(r"^:?\s*(?:(?:your|the) institution\s*:?\s*)?", "", rest, flags=re.I).strip(" .:;,")
        if (not name or is_generic_label(name)
                or (match.group("prefix").lower() in _BARE_PREFIXES and not INSTITUTION_WORD.search(name))):
            continue
        names.append(name[:200])
    return names


# --- C: the reader may read the article ----------------------------------------
# A badge by the title (PROBE_JS): ScienceDirect's "Full text access" / "Open
# archive", ACS "Subscribed", Wiley's .doi-access "Full Access" (its signed-in
# pages of 1965 and 1980 articles and of conference digests have no full-text
# sections, 2026-11-02). Only as a badge: "Open Access" is also a menu entry of
# many sites, and lists of related articles carry their own badges. As a line of
# text only the sentence "You have (full) access to this article".
_ACCESS_LINE = re.compile(r"you have (?:full )?access(?: to this (?:article|content|chapter))?\.?", re.I)
ACCESS_BADGE = re.compile(r"\b(?:open|free|full)(?: text)? access\b|\bopen archive\b|\bfree to read\b|^subscribed$", re.I)
# Access every reader has: the school's login adds nothing to it.
OPEN_TO_ALL = re.compile(r"\b(?:open|free)(?: text)? access\b|\bopen archive\b|\bfree to read\b|^licence:", re.I)
_LICENCE = re.compile(
    r"open access\s+this article is (?:licensed|distributed) under"
    r"|\b(?:is|are) (?:licensed|distributed) under (?:the terms of )?(?:a |the )?creative commons\b"
    r"|\bthis is an open[ -]access article\b", re.I)


def reader_access(lines: list[str], text: str, probe: dict) -> str:
    """Evidence that the page lets the reader read the article; "" without."""
    for badge in probe.get("badges") or ():
        if ACCESS_BADGE.search(str(badge)):
            return f"badge: {badge}"
    if probe.get("sections"):
        return "full-text sections"
    match = _LICENCE.search(" ".join(str(text or "").split()))
    if match:
        return f"licence: {match.group(0)}"
    for line in lines:
        if len(line) <= 60 and _ACCESS_LINE.fullmatch(line):
            return line
    return ""


# --- OUT: an offer, an abstract-only view, a denial ----------------------------
# Short controls and labels, a whole line or a control's whole text (links in a
# row share a line: BMJ's "Buy this article ($64)", Thieme's "Buy Article"):
# "Buy article PDF 39,95 €", "Purchase PDF", "Rent this article", "Get Access",
# "Check Access" (journals.lww.com, Ovid).
OFFER_LABEL = (r"(?:buy|purchase|rent)\s+(?:this\s+)?(?:article|pdf|chapter|e-?book|issue|instant access|access)\b.{0,40}"
               r"|(?:get|check)\s+access")
_OFFER_LINE = re.compile(OFFER_LABEL, re.I)
# Sentences only a reader without access is shown, anywhere in a line.
_OFFER_PHRASE = re.compile(
    r"this is a preview of subscription content|full text access for subscribers"
    r"|your library or personal account may give you access|sign in to continue reading"
    r"|subscribe to (?:read|access|unlock)|get access to the full (?:version|text|article)"
    r"|purchase instant access|you do not (?:currently )?have access to this (?:pdf|article|content)", re.I)

# The publisher's own words for "this reader, or the named institution, may not
# read this": RSC and Oxford Academic "You do not currently have access to this
# content/article.", ScienceDirect "<school> does not subscribe to this content
# on ScienceDirect.", Sage "Access via <school> is not available as they do not
# subscribe to Sage Journals content.". A whole line: help copy and
# conditionals around it are not a denial.
_DENIAL_LINE = re.compile(
    r"(?:(?:(?P<who>you|your (?:institution|organi[sz]ation))|(?P<name>[^.!?:\"“”]{2,120}?))\s+(?:do|does)\s+not"
    r"\s+(?:currently\s+)?(?:have access to|subscribe to)\s+(?:this|the)\s+"
    r"(?:article|content|pdf|full text|journal|book|chapter)(?:\s+on\s+[^.!?]{2,40})?"
    r"|access via (?P<via>[^.!?]{2,120}?) is not available as they do not subscribe to [^.!?]{2,80}"
    r"|your (?:institution|organi[sz]ation) has not (?:subscribed to this content|purchased access to this article))\.?",
    re.I)
_DENIAL_CONTEXT = re.compile(
    r"\b(?:if|when|whether|unless|example|message|means|contact|please|faq|frequently asked questions|help|troubleshooting)\b",
    re.I)
_CONDITIONAL = re.compile(r"\b(?:if|when|whether|unless)\b", re.I)
# Denial addresses: Wiley's denial layout, Thieme's PDF request sent to its login
# page with type=auth_denied, Oxford Academic's #no-access-message (Brain 1968 and
# AJE 1985 after the school's login, 2026-11-02).
DENIAL_URL_MARKERS = ("accessdeniallayout", "type=auth_denied", "#no-access-message")


def _denial(line: str) -> tuple[bool, str]:
    match = _DENIAL_LINE.fullmatch(line)
    if not match or _CONDITIONAL.search(match.group("name") or ""):
        return False, ""
    return True, (match.group("name") or match.group("via") or "").strip()


def denial_line(lines: list[str]) -> tuple[str, str]:
    """``(line, institution it names)`` for a denial line on its own; ``("", "")`` without."""
    for index, line in enumerate(lines):
        denied, named = _denial(line)
        if denied and not _DENIAL_CONTEXT.search(" ".join(lines[max(0, index - 1):index] + lines[index + 1:index + 2])):
            return line, named
    return "", ""


def has_denial_line(text: str) -> bool:
    """A denial line on its own in ``text`` (the CARSI driver asks this too)."""
    return bool(denial_line(lines_of(text))[0])


def denial_evidence(url: str, lines: list[str], probe: dict) -> tuple[str, str]:
    """``(evidence, institution named)`` of a denial on the page; ``("", "")`` without."""
    lower = str(url or "").lower()
    marker = next((m for m in DENIAL_URL_MARKERS if m in lower), "")
    if marker:
        return f"denial address: {marker}", ""
    panel = probe.get("denial_panel")
    if panel:
        return (f'denial panel: "{str(panel)[:200]}"' if isinstance(panel, str) else "denial panel"), ""
    for box in probe.get("denial_boxes") or ():
        for line in lines_of(str(box)):
            denied, named = _denial(line)
            if denied:
                return f'denial box: "{line[:200]}"', named
    line, named = denial_line(lines)
    return (f'denial line: "{line[:200]}"', named) if line else ("", "")


def offer_evidence(lines: list[str], probe: dict, *, gate: bool = True) -> str:
    """An offer to buy, a paywall box or (``gate``) an access gate; "" without.
    "Access through <school>" is also how a site shows a remembered school that
    is not signed in there: after a login it is no evidence of a missing licence."""
    for line in lines:
        if (len(line) <= 80 and _OFFER_LINE.fullmatch(line)) or _OFFER_PHRASE.search(line):
            return line[:200]
    for control in probe.get("offers") or ():
        if _OFFER_LINE.fullmatch(str(control)):
            return str(control)[:200]
    if probe.get("paywall"):
        return "paywall box"
    if gate and probe.get("gate"):
        return f"access gate: {probe.get('gate')}"
    return ""


# --- The page's elements, read in one round trip --------------------------------
# Institution labels: ACS's header dropdown, Thieme's #institutionName, RSC's
# institution panel, and any [class*=institution] element in the page header
# (Wiley shows the signed-in school next to its logo, 2026-11-02); never inside
# author affiliations or references.
# Access badges sit by the article's title: Wiley's .doi-access, the open/free
# icons of Atypon sites (ahajournals.org, neurology.org, 2026-11-01), any short
# text saying so there that is not a link or a menu entry. Badges far from the
# title, in a side column or a list of related articles belong to other articles.
_SELECTORS = {
    "labels": "#institutionName, button.at-institution, .dropdown-institution-item",
    "header": 'header, [role="banner"], [class*="header" i], [id*="header" i]',
    "notLabel": '[class*="author" i], [class*="affil" i], [class*="contrib" i], [class*="reference" i], '
                "#references, .references",
    "badges": ".doi-access",
    "badgeIcons": ".meta-panel__icons .text-access-open, .meta-panel__icons .text-access-free",
    "notBadge": 'a, button, select, option, nav, footer, aside, [role="navigation"], [role="menu"], '
                '[role="menubar"], [class*="menu" i], [class*="navbar" i], [class*="related" i], '
                '[class*="recommend" i], [id*="related" i], [id*="recommend" i]',
    "sections": ".article-section__full",  # Wiley's full-text sections, shown only to readers with access
    "paywall": "#inline-unauthorized-page",  # APS's access box for readers without access
    "denialPanel": "#accessDenialLayout",  # Wiley
    "denialBoxes": ".article-top-info-user-restricted-options, #no-access-message, #core-collateral-purchase-access p",
    "offer": OFFER_LABEL,
}
PROBE_JS = r"""() => {
    const S = SELECTORS;
    const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
    const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
    const all = selector => [...document.querySelectorAll(selector)];
    const title = all('h1').find(shown);
    const titleTop = title ? title.getBoundingClientRect().top + window.scrollY : 0;
    const byTitle = el => {
        const rect = el.getBoundingClientRect();
        return Math.abs(rect.top + window.scrollY - titleTop) < 800 && rect.left < window.innerWidth * 0.65;
    };
    const labels = [];
    for (const el of all(S.labels + ', [class*="institution" i]')) {
        if (labels.length >= 12) break;
        if (!shown(el) || el.closest(S.notLabel) || (!el.matches(S.labels) && !el.closest(S.header))) continue;
        const t = text(el);
        if (t && t.length <= 150) labels.push(t);
    }
    const badges = all(S.badges).filter(el => shown(el) && byTitle(el)).map(text).filter(Boolean).slice(0, 4);
    if (all(S.badgeIcons).some(el => shown(el) && byTitle(el))) badges.push('open access');
    const BADGE = /^(?:(?:open|free|full)(?: text)? access|open archive|free to read|subscribed)$/i;
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
    for (let n = 0; badges.length < 8 && n < 60000 && walker.nextNode(); n++) {
        const t = (walker.currentNode.nodeValue || '').replace(/\s+/g, ' ').trim();
        if (!t || t.length > 40 || !BADGE.test(t)) continue;
        const el = walker.currentNode.parentElement;
        if (el && shown(el) && !el.closest(S.notBadge) && byTitle(el)) badges.push(t);
    }
    const controls = all('a,button,[role="button"]').filter(shown);
    const gate = controls.find(el => {
        const t = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
        return /^get access$/i.test(t) || /^access through (?!.*\bpurchase\b).{2,80}$/i.test(t);
    });
    const OFFER = new RegExp('^(?:' + S.offer + ')$', 'i');
    const offers = controls.map(text).filter(t => t.length <= 80 && OFFER.test(t)).slice(0, 4);
    return {
        labels, badges, offers,
        sections: all(S.sections).some(shown),
        paywall: all(S.paywall).some(shown),
        denial_panel: (all(S.denialPanel).filter(shown).map(text)[0] || '') || all(S.denialPanel).some(shown),
        denial_boxes: all(S.denialBoxes).filter(shown).map(text).filter(Boolean).slice(0, 4),
        password: all('input[type="password"]').some(shown),
        gate: gate ? text(gate).slice(0, 120) : '',
    };
}""".replace("SELECTORS", json.dumps(_SELECTORS))
