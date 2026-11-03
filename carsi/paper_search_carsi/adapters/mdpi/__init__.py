"""MDPI: open-access journals on www.mdpi.com.

The PDF is the article page's ``/pdf``; the page is the source page or derived
from the DOI for the journals whose codes are known.
"""
from __future__ import annotations

from ...engine.router import _append_mdpi_candidates
from ..base import PublisherAdapter, register


@register
class MDPIAdapter(PublisherAdapter):
    publisher = "mdpi"

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_mdpi_candidates(urls, doi, source_url)
        return urls
