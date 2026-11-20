"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS, CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS, AtyponAdapter


@register
class NeurologyAdapter(AtyponAdapter):
    """The AAN's Neurology journals on neurology.org."""

    publisher = "neurology"
    site_hosts = frozenset({"neurology.org", "www.neurology.org"})

    # --fulltext: Atypon's current template (platforms/atypon), verified 2026-11-14.
    fulltext_shown_js = CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS
    fulltext_images_js = CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS
