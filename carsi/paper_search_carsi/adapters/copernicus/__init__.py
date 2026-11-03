"""Copernicus Publications: open-access journals on <journal>.copernicus.org.

The PDF path is derived from the DOI
(``10.5194/<journal>-<volume>-<page>-<year>``).
"""
from __future__ import annotations

from ...engine.router import _append_copernicus_candidates
from ..base import PublisherAdapter, register


@register
class CopernicusAdapter(PublisherAdapter):
    publisher = "copernicus"

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_copernicus_candidates(urls, doi, source_url)
        return urls
