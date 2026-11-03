"""PLOS: open-access journals on journals.plos.org.

The printable PDF is ``/<journal>/article/file?id=<DOI>&type=printable``; the journal
path comes from the source page or the DOI's journal code.
"""
from __future__ import annotations

from ...engine.router import _append_plos_candidates
from ..base import PublisherAdapter, register


@register
class PLOSAdapter(PublisherAdapter):
    publisher = "plos"

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_plos_candidates(urls, doi, source_url)
        return urls
