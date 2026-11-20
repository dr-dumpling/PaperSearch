"""AIP Publishing: journals on pubs.aip.org (Silverchair).

Its PDF needs no rules of its own: the engine's general ones take it. Its full-text page
is Silverchair's, read for the Markdown with the platform's page rules (The Journal of Chemical Physics,
2026-11-15).
"""
from __future__ import annotations

from ..base import PublisherAdapter, register
from ..platforms.silverchair import SILVERCHAIR_FULLTEXT_IMAGES_JS, SILVERCHAIR_FULLTEXT_SHOWN_JS


@register
class AIPAdapter(PublisherAdapter):
    publisher = "aip publishing"
    fulltext_shown_js = SILVERCHAIR_FULLTEXT_SHOWN_JS
    fulltext_images_js = SILVERCHAIR_FULLTEXT_IMAGES_JS
