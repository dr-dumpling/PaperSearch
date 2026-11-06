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
from ..base import PublisherAdapter, register


@register
class OpticaAdapter(PublisherAdapter):
    publisher = "optica"

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
