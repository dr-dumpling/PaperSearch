"""American Meteorological Society: journals on journals.ametsoc.org.

The PDF of an article page ``/view/<path>.xml`` is ``/downloadpdf/view/<path>.pdf``.
The site offers no institutional sign-in: its "Sign in" is the AMS member login
(www.ametsoc.org/ams/log-in, user name and password only), and institutions reach
the journals by their network address (checked 2026-11-08).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.router import _append_ams_candidates
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
    href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
}))"""

# --fulltext (PaperSearch's sites/templates/ams.ts). The article page (PubFactory) holds the
# full text in div#contentRoot > div#articleBody: div.section sections, the back matter, the
# appendices, the references (section.refSection). The Abstract / Full Text / PDF tabs are
# on every page, an early-online article's too, which has no #articleBody: they prove no
# body. A figure (div.figure) or a table (div.tableWrap, only an image) is lazy: its <img>
# shows Blank.svg until in view, data-image-src names the medium image ("inline-…") and a
# hidden pop-up (pf-box) the largest ("full-…"), which is taken, as the converter does.
# MathJax 2 keeps each formula's MathML in a math/mml script beside its output, so nothing
# is prepared (Artificial Intelligence for the Earth Systems, open access, 2026-11-15).
FULLTEXT_SHOWN_JS = """() => {
  const body = document.querySelector('#articleBody');
  if (!body) return false;
  const text = [...body.querySelectorAll('p, div.p')]
    .filter((p) => !p.closest('.figure, .tableWrap, .refSection, .keywords') && !p.parentElement?.closest('p, div.p'))
    .reduce((total, p) => total + (p.textContent || '').length, 0);
  return text > 500;
}"""
FULLTEXT_IMAGES_JS = """() => {
  const body = document.querySelector('#articleBody');
  if (!body) return [];
  const listed = (images) => images.map((img) => (img.getAttribute('data-image-src') || '').trim()).find(Boolean);
  return [...body.querySelectorAll('div.figure, div.tableWrap')]
    .filter((box) => !box.parentElement?.closest('div.figure, div.tableWrap'))
    .filter((box) => !box.classList.contains('tableWrap') || !box.querySelector('table'))
    .map((box) => {
      const images = [...box.querySelectorAll('img')];
      return listed(images.filter((img) => img.closest('pf-box'))) || listed(images)
        || images.map((img) => (img.getAttribute('src') || '').trim())
          .find((src) => src && !/\\/Blank\\.svg(?:[?#]|$)|^data:/i.test(src)) || '';
    })
    .filter(Boolean)
    .map((src) => new URL(src, location.href).href);
}"""


def supplement_links_from_rows(rows: list[dict], doi: str) -> list[SupplementLink]:
    """Only files listed under this article's own supplemental XML directory."""
    if not doi.lower().startswith("10.1175/"):
        return []
    article = re.escape(doi.split("/", 1)[1])
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in rows:
        target = urlparse(str(row.get("href") or ""))
        if (target.scheme != "https" or target.netloc != "journals.ametsoc.org"
                or not re.fullmatch(r"/supplemental/+journals/[^/]+/\d+/\d+/" + article
                                    + r"\.xml/[^/]+", unquote(target.path), re.I)):
            continue
        url = target._replace(fragment="").geturl()
        # In-text and end-of-article links differ by a duplicate slash.
        identity = re.sub(r"/+", "/", unquote(target.path))
        if identity not in seen:
            seen.add(identity)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links


@register
class AMSAdapter(PublisherAdapter):
    publisher = "ams"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS

    def prepare_institution_choice(self, page: Any, result: Any) -> bool | None:
        """No school to choose here: the article ends at once as having no login route
        for the school, instead of waiting on the article page for a choice."""
        if result is not None and not getattr(result, "_institution_not_listed", False):
            self.d._event(result, "institution_login_unavailable",
                          "AMS: member sign-in only; institutions by network address")
            result._institution_not_listed = True
        return False

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        return supplement_links_from_rows(page.evaluate(_SUPPLEMENT_ROWS_JS), doi)

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_ams_candidates(urls, source_url)
        return urls
