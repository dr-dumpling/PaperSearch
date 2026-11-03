"""American Meteorological Society: journals on journals.ametsoc.org.

The PDF of an article page ``/view/<path>.xml`` is ``/downloadpdf/view/<path>.pdf``.
"""
from __future__ import annotations

from ...engine.router import _append_ams_candidates
from ..base import PublisherAdapter, register


@register
class AMSAdapter(PublisherAdapter):
    publisher = "ams"

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_ams_candidates(urls, source_url)
        return urls
