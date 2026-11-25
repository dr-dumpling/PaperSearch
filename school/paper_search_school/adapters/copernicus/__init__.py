"""Copernicus Publications: open-access journals on <journal>.copernicus.org.

The PDF path is derived from the DOI
(``10.5194/<journal>-<volume>-<page>-<year>``).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.fulltext_page import paragraph_text_js
from ...engine.router import _append_copernicus_candidates
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""

# --fulltext (PaperSearch's sites/templates/copernicus.ts). The server renders the article
# page in full and open: div.article holds the abstract and one div.sec#section<N> per
# section, the references last (.ref-list); an older article's page has only its abstract.
# A figure (div.fig) shows a thumbnail; its print version is behind "Download"
# (a.figure-download), else its web version is what the thumbnail links to (a.figure-link).
# The print version can be a PDF: only image files are taken, as the converter does. A table
# is only an image (div.table-wrap > a.table-link). MathJax 2 keeps each formula's MathML in
# a script beside its output, so nothing is prepared (Atmospheric Chemistry and Physics,
# 2026-11-15).
FULLTEXT_SHOWN_JS = paragraph_text_js('div.article > div.sec[id^="section"]:not(.ref-list) p', ".downloads, .caption", "> 500")
FULLTEXT_IMAGES_JS = """() => {
  const article = document.querySelector('div.article');
  if (!article) return [];
  const image = (url) => /^https?:\\/\\/[^?#]+\\.(?:png|jpe?g|gif|webp)(?:[?#]|$)/i.test(url);
  const first = (float, linkClass, names) => {
    const img = [...float.querySelectorAll('img')].find((node) => !node.closest('.caption'));
    const links = [...float.querySelectorAll(`a.${linkClass}`)];
    return names.flatMap((name) => (name === 'href' ? links.map((link) => link.getAttribute('href')) : [img?.getAttribute(name)]))
      .filter(Boolean).map((value) => new URL(value, location.href).href).find(image) || '';
  };
  const figures = [...article.querySelectorAll('div.fig')].map((fig) => first(fig, 'figure-download', ['href', 'data-printversion'])
    || first(fig, 'figure-link', ['href', 'data-webversion', 'src']));
  const tables = [...article.querySelectorAll('div.table-wrap')].filter((wrap) => !wrap.querySelector('table'))
    .map((wrap) => first(wrap, 'table-link', ['href', 'data-printversion', 'data-webversion', 'src']));
  return [...figures, ...tables].filter(Boolean);
}"""


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    article = re.fullmatch(r"10\.5194/([a-z0-9]+)-(\d+)-(\d+)-(\d{4})", doi, re.I)
    if not article:
        return []
    journal, volume, first_page, year = article.groups()
    stem = doi.split("/", 1)[1].lower()
    expected = f"/articles/{volume}/{first_page}/{year}/{stem}-supplement.pdf"
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        if (target.scheme == "https" and target.netloc.lower() == f"{journal.lower()}.copernicus.org"
                and unquote(target.path).lower() == expected and expected not in seen):
            seen.add(expected)
            links.append(SupplementLink(target._replace(fragment="").geturl(), str(row.get("label") or "")))
    return links


@register
class CopernicusAdapter(PublisherAdapter):
    publisher = "copernicus"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

    @classmethod
    def profile_pdf_candidate_url(cls, url: str) -> bool:
        target = urlparse(url)
        host = (target.hostname or "").lower()
        # A figure PDF includes the article stem too, but is not the article PDF.
        return (target.scheme == "https" and not target.username and not target.password
                and host.endswith(".copernicus.org")
                and re.fullmatch(r"[a-z0-9]+-\d+-\d+-\d{4}\.pdf",
                                 unquote(target.path).rsplit("/", 1)[-1].lower()) is not None)

    @classmethod
    def keeps_pdf_candidate(cls, profile, url: str, doi: str) -> bool:
        return cls.profile_pdf_candidate_url(url) and urlparse(url).path.lower().endswith(
            "/" + doi.split("/", 1)[-1].lower() + ".pdf")

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_copernicus_candidates(urls, doi, source_url)
        return urls
