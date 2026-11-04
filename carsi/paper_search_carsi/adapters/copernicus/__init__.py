"""Copernicus Publications: open-access journals on <journal>.copernicus.org.

The PDF path is derived from the DOI
(``10.5194/<journal>-<volume>-<page>-<year>``).
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from ...engine.router import _append_copernicus_candidates
from ..base import PublisherAdapter, register


@register
class CopernicusAdapter(PublisherAdapter):
    publisher = "copernicus"

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
