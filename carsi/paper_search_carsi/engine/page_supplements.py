"""The shared rule for a site without a supplementary-file rule of its own: the
files the article page itself lists as its supplementary material.

A link counts only inside the page's supplementary part (an element whose class
or id says so, or the part under a "Supplementary data", "Supplemental
material" or "Supporting information" heading), only when its address names this
article's DOI ("/" kept, or as "_") between two "/", and only when it ends in a
file name. The DOI in the address binds the file to this article; a page's links
to other articles, datasets or web pages are no files of it (the Journal of
Experimental Medicine's tables on its own CDN, 2026-11-11).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ..adapters.base import SupplementLink

_SECTION_LINKS_JS = r"""() => {
 const part = '[class*="suppl" i], [id*="suppl" i], [class*="datasupp" i], [class*="supporting" i], [id*="supporting" i]';
 const heading = /^(?:online )?(?:supplementa(?:ry|l) (?:data|materials?|information|files?)|supporting information)$/i;
 const headed = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')]
   .filter(h => heading.test((h.textContent || '').replace(/\s+/g, ' ').trim()) && h.parentElement)
   .map(h => h.parentElement);
 return {
   doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
   rows: [...document.querySelectorAll('a[href]')]
     .filter(a => a.closest(part) || headed.some(p => p.contains(a)))
     .map(a => ({href: a.href, label: (a.innerText || a.getAttribute('title') || '').replace(/\s+/g, ' ').trim().slice(0, 200)}))
 };
}"""
# Addresses that end in a web page, not a file (figure slides are .aspx).
_WEB_PAGES = frozenset({"html", "htm", "xhtml", "shtml", "asp", "aspx", "php", "jsp", "cfm"})


def listed_files(page: Any, doi: str) -> list[SupplementLink]:
    """This article's files in its page's supplementary part (see the module); a
    page that names another article in ``citation_doi`` lists none. A file linked
    several times (signed addresses differ in their query) is taken once."""
    doi = (doi or "").strip().lower()
    data = page.evaluate(_SECTION_LINKS_JS)
    if not doi or not isinstance(data, dict):
        return []
    page_doi = str(data.get("doi") or "").strip().lower()
    if page_doi and page_doi != doi:
        return []
    forms = (f"/{doi}/", f"/{doi.replace('/', '_')}/")
    links: list[SupplementLink] = []
    seen: set[tuple[str, str]] = set()
    rows = data.get("rows")
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        target = urlparse(str(row.get("href") or ""))
        path = unquote(target.path)
        name = path.rsplit("/", 1)[-1]
        extension = name.rpartition(".")[2].lower() if "." in name else ""
        if (target.scheme != "https" or not target.hostname or target.username or target.password
                or not any(form in path.lower() for form in forms)
                or not re.fullmatch(r"[a-z0-9]{1,5}", extension) or extension in _WEB_PAGES):
            continue
        key = (target.hostname.lower(), path)
        if key not in seen:
            seen.add(key)
            links.append(SupplementLink(target._replace(fragment="").geturl(), str(row.get("label") or "")))
    return links
