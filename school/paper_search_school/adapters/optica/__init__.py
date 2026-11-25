"""Optica (formerly OSA): journals on opg.optica.org.

Without access the article page says "Not Accessible" with "Your library or
personal account may give you access" (an offer of the shared access rule).
Its LOGIN modal holds a personal
email/password form and the "Institutional Login" link (auth.optica.org's
``/connect/authorize``, then OpenAthens).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from ...engine.batch_common import open_page, pump_until
from ...engine.fulltext_page import MATHJAX_SOURCES_JS, paragraph_text_js
from ..base import PublisherAdapter, register

# --fulltext (PaperSearch's sites/templates/optica.ts). The article page (abstract.cfm, as
# fulltext.cfm) shows a reader with access the full text: div#articleBody holds the abstract
# and <article>, the body with its figures, formulas, back matter and references. A figure's
# <img> is lazy (its src a loader until in view); its "Download Full Size" link
# (viewmedia.cfm ...&imagetype=full) is the full-size image, taken as the converter does; the
# general sample rules had the loader (Optics Letters, a page saved after a school login,
# 2026-11-15).
FULLTEXT_SHOWN_JS = paragraph_text_js("p", ".back, .figure-image, .text-plus-thumb", "> 500", root="div#articleBody > article")
FULLTEXT_IMAGES_JS = """() => [...document.querySelectorAll('div#articleBody div.figure-image')].map((figure) => {
  const full = [...figure.querySelectorAll('a[href]')].find((a) => /[?&]imagetype=full(?:&|$)/i.test(a.getAttribute('href') || ''));
  if (full) return full.getAttribute('href');
  const img = figure.querySelector('img');
  return img ? img.getAttribute('data-src') || img.getAttribute('src') || '' : '';
}).filter((src) => src && !src.startsWith('data:') && !/ajax-loader/i.test(src))
  .map((src) => new URL(src, location.href).href)"""


# Back on Optica after the school's login, its home page saying the organisation the login named
# has no access through SSO (a CARSI school through the OpenAthens chooser, 2026-11-18): the login
# cannot go on. It was taken for the article, and the page and the PDF waited until they ran out.
_SSO_REFUSED = re.compile(r"your organi[sz]ation does not have access via sso", re.I)


def _home_page(url: str) -> bool:
    target = urlparse(url)
    return (target.hostname or "").lower() == "opg.optica.org" and target.path.lower() in ("", "/", "/default.cfm", "/index.cfm")


@register
class OpticaAdapter(PublisherAdapter):
    publisher = "optica"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS
    # MathJax 4.1 (TeX and MathML input, SVG output): a TeX formula keeps its TeX on its
    # output (data-latex), which the shared script leaves alone; it keeps a MathML one's
    # source and waits for the first typesetting.
    fulltext_prepare_js = MATHJAX_SOURCES_JS

    def supplement_links(self, page: Any, doi: str) -> None:
        # The embedded reader can still be loading after the outer document
        # reports ready. Let its article metadata/links render before discovery.
        target = urlparse(str(page.url))
        if (target.scheme == "https" and target.netloc == "opg.optica.org"
                and target.path.endswith("/viewmedia.cfm") and parse_qs(target.query).get("html") == ["true"]):
            pump_until(page, lambda: page.evaluate("""() =>
                document.readyState !== 'loading' &&
                (!!document.querySelector('meta[name="citation_doi"]')
                 || document.querySelectorAll('a[href]').length > 0)
            """), 15_000)
        return None

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        source = urlparse(source_url)
        if source.scheme != "https" or source.hostname != "opg.optica.org":
            return []
        match = re.fullmatch(r"/([a-z0-9]+)/(?:abstract|fulltext|viewmedia)\.cfm", source.path)
        uri = parse_qs(source.query).get("uri", [])
        if not match or len(uri) != 1 or not re.fullmatch(rf"{match[1]}-\d+-[a-z0-9-]+", uri[0]):
            return []
        # The page's Get PDF link uses its journal/volume/issue/article URI,
        # not the DOI. html=true serves the HTML reader at this same endpoint.
        return [f"https://opg.optica.org/{match[1]}/viewmedia.cfm?" + urlencode({"uri": uri[0], "seq": "0"})]

    @classmethod
    def profile_pdf_candidate_url(cls, url: str) -> bool | None:
        target = urlparse(url)
        if target.hostname != "opg.optica.org" or not target.path.endswith("/viewmedia.cfm"):
            return None
        query = parse_qs(target.query, keep_blank_values=True)
        return (target.scheme == "https" and bool(query.get("uri"))
                and not any(key in query for key in ("html", "figure", "imagetype")))

    @classmethod
    def keeps_pdf_candidate(cls, profile: Any, url: str, doi: str) -> bool:
        return cls.profile_pdf_candidate_url(url) is not False

    @classmethod
    def belongs_to_article(cls, url: str, doi: str, source_url: str) -> bool | None:
        if cls.profile_pdf_candidate_url(url) is not True:
            return None
        uri = parse_qs(urlparse(url).query).get("uri", [])
        source_uri = parse_qs(urlparse(source_url).query).get("uri", [])
        return len(uri) == 1 and (uri == source_uri or uri[0].lower() == doi.lower())

    def looks_logged_out(self, page: Any, url: str, text: str) -> bool | None:
        """Optica's home page, where its sign-in ends, is not the article: never read as access."""
        return True if _home_page(url) else None

    def login_block_reason(self, page: Any, text: str) -> str | None:
        """Optica refused the organisation the school's login named (no access through SSO)."""
        return "institution_not_registered" if _SSO_REFUSED.search(" ".join(text.split())) else None

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        """The modal's "Institutional Login" link, opened directly; the personal form is never used."""
        if (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower() != "opg.optica.org":
            return None
        for control in page.locator('a[href*="auth.optica.org"]').all():
            target = urlparse(urljoin(str(page.url), control.get_attribute("href") or ""))
            if (target.scheme == "https" and target.hostname == "auth.optica.org"
                    and target.path == "/connect/authorize"):
                open_page(page, target.geturl(), timeout_ms=30_000)
                self.d._event(result, "sso_entry_clicked", "optica-institutional-login")
                return True
        return False
