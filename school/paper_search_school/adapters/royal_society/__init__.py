"""The Royal Society: journals on royalsocietypublishing.org (Silverchair).

Its PDF needs no rules of its own: the engine's general ones take it. Its full-text page
is Silverchair's, read for the Markdown with the platform's page rules (Journal of the Royal Society Interface,
2026-11-15).
"""
from __future__ import annotations

from ..base import PublisherAdapter, register
from ..platforms.silverchair import SILVERCHAIR_FULLTEXT_IMAGES_JS, SILVERCHAIR_FULLTEXT_SHOWN_JS


@register
class RoyalSocietyAdapter(PublisherAdapter):
    publisher = "royal society publishing"
    fulltext_shown_js = SILVERCHAIR_FULLTEXT_SHOWN_JS
    fulltext_images_js = SILVERCHAIR_FULLTEXT_IMAGES_JS
