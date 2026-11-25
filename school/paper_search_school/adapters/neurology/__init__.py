"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS, CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS, AtyponAdapter


@register
class NeurologyAdapter(AtyponAdapter):
    """The AAN's Neurology journals on neurology.org, and CONTINUUM on continuum.aan.com: the same
    Atypon site type, its DOIs 10.1212/cont.* (its access box "GET ACCESS"; without its host here the
    platform's institution login was never opened and the wait ran out on the article,
    10.1212/cont.0000000000001619, Windows 2026-11-23)."""

    publisher = "neurology"
    site_hosts = frozenset({"neurology.org", "www.neurology.org", "continuum.aan.com"})

    # --fulltext: Atypon's current template (platforms/atypon), verified 2026-11-14.
    fulltext_shown_js = CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS
    fulltext_images_js = CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS
