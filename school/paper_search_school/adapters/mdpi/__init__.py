"""MDPI: open-access journals on www.mdpi.com.

The PDF is the article page's ``/pdf``; the page is the source page or derived
from the DOI for the journals whose codes are known.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.fulltext_page import MATHJAX_SOURCES_JS
from ...engine.router import _append_mdpi_candidates
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => ({
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    rows: [...document.querySelectorAll('a[href]')].map(a => ({
        href: a.href,
        label: (a.closest('.html-p')?.innerText || a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
    }))
})"""


# --fulltext (PaperSearch's sites/publishers/mdpi/template.ts). The article is MDPI's HTML of its
# JATS, open: in the current design (2026) div#article-contents, in the earlier one div.html-body
# and div.html-back; body paragraphs are div.html-p, the abstract, back matter, references and
# the hidden copies of the figures and tables apart. A figure (div.html-fig-wrap) shows a 550 px
# thumbnail; its full size is the image's data-large. A table is an HTML table in the pop-up its
# link names (#table_body_display_...), an image there only when it has none. The general sample
# rules found no figure (no <figure>, no .fig), so nothing was saved (Energies, 10.3390/en19215289,
# 2026-11-18). The current design's MathJax 4 typesets lazily and the page's globals did not keep
# the formulas' sources; PaperSearch takes them from the page's Nuxt payload. The shared script
# still runs: it keeps them when MathJax is there to ask.
FULLTEXT_SHOWN_JS = """() => {
  const contents = document.querySelector('#article-contents');
  const roots = contents ? [contents] : [...document.querySelectorAll('div.html-body')];
  const apart = '.html-abstract, .html-notes, .html-ack, #html-references_list, #html-glossary, .html-fn_group, '
    + '#html-copyright, #html-keywords, #html-graphical, [type="display-objects"], .html-fig_show, .html-table_show, '
    + '.html-fig-wrap, .html-table-wrap';
  const text = roots.flatMap((root) => [...root.querySelectorAll('div.html-p')])
    .filter((p) => !p.closest(apart) && !p.querySelector('div.html-p'))
    .reduce((total, p) => total + (p.textContent || '').length, 0);
  return text > 500;
}"""
FULLTEXT_IMAGES_JS = """() => {
  const contents = document.querySelector('#article-contents');
  const roots = contents ? [contents] : [...document.querySelectorAll('div.html-body, div.html-back')];
  const apart = '.html-abstract, .html-fig_show, .html-table_show, .html-fn_group, #html-keywords, #html-graphical, '
    + '#html-references_list, #html-copyright, section[type="display-objects"]';
  const full = (scope) => {
    const img = scope && [...scope.querySelectorAll('img')].find((node) => !node.closest('.html-fig_description, .html-caption'));
    if (!img) return '';
    const src = ['data-large', 'data-original', 'data-lsrc', 'src'].map((name) => (img.getAttribute(name) || '').trim()).find(Boolean) || '';
    return src && !src.startsWith('data:') && !/\\/img\\/table\\.png(?:[?#]|$)/i.test(src) ? src : '';
  };
  const popup = (wrap, linkClass) => {
    const link = [...wrap.querySelectorAll(`.${linkClass}`)].find((node) => (node.getAttribute('href') || '').startsWith('#'));
    return link ? document.getElementById(link.getAttribute('href').slice(1)) : null;
  };
  const urls = [];
  for (const root of roots) {
    for (const wrap of root.querySelectorAll('div.html-fig-wrap, div.html-table-wrap')) {
      if (wrap.closest(apart)) continue;
      if (wrap.classList.contains('html-fig-wrap')) {
        urls.push(full(wrap) || full(popup(wrap, 'html-figpopup')));
      } else {
        const table = popup(wrap, 'html-tablepopup');
        if (table && !table.querySelector('table')) urls.push(full(table));
      }
    }
  }
  return urls.filter(Boolean).map((src) => new URL(src, location.href).href);
}"""


# An article's page: /<ISSN>/<volume>/<issue>/<article> (www.mdpi.com/1996-1073/19/21/5291).
_ARTICLE_PATH = re.compile(r"/\d{4}-\d{3}[\dXx]/\d+/\d+/\d+/?")


def supplement_links_from_page(data: Any, doi: str) -> list[SupplementLink]:
    """MDPI's DOI-bound /sN links redirect to the original supporting files."""
    if not isinstance(data, dict) or str(data.get("doi", "")).strip().lower() != doi.lower():
        return []
    pattern = re.compile(r"/article/" + re.escape(doi) + r"/s[1-9][0-9]*", re.I)
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        url = target._replace(fragment="").geturl()
        if (target.scheme == "https" and target.hostname in {"www.mdpi.com", "mdpi.com"}
                and pattern.fullmatch(unquote(target.path)) and url not in seen):
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class MDPIAdapter(PublisherAdapter):
    publisher = "mdpi"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS
    fulltext_prepare_js = MATHJAX_SOURCES_JS

    def fulltext_page_url(self, doi: str, page_url: str) -> str:
        """--fulltext: the article page again, at its address with MDPI's update-check query and
        a value of this read's own, for when the article page shows no full text. MDPI may answer
        an article's address with the abstract alone (a 120-140 kB document with one div.html-p;
        the full page is 230-800 kB) and keeps doing so for that address: the bare one on a repeat
        visit (Energies 10.3390/en19215280, -5291, 2026-11-18), and the one with the update-check
        query too, for 16 of 80 articles of 2025 (10.3390/s25226876: the same abstract-only page
        on two reads 30 s apart; for 6 of them the bare address, loaded twice meanwhile, was a
        full page by its size, 2026-11-22). Queries not asked before (?a=1, ?a=2) gave the full
        page every time (2026-11-18). "" off MDPI's article pages, or when the address has a query
        already."""
        target = urlparse(page_url or "")
        if (target.scheme != "https" or (target.hostname or "").lower() not in {"www.mdpi.com", "mdpi.com"}
                or target.query or not _ARTICLE_PATH.fullmatch(target.path)):
            return ""
        return target._replace(query=f"type=check_update&version=1&t={time.time_ns() // 1_000_000}", fragment="").geturl()

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_mdpi_candidates(urls, doi, source_url)
        return urls

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)
