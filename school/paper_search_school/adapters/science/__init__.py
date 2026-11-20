"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS, CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS, AtyponAdapter


@register
class ScienceAdapter(AtyponAdapter):
    """The Science family of journals (AAAS) on science.org: on Atypon's Literatum since 2021 (NISO, 2021-09-09)."""

    publisher = "science"
    site_hosts = frozenset({"www.science.org", "science.org"})

    # --fulltext: Atypon's current template (platforms/atypon).
    fulltext_shown_js = CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS
    fulltext_images_js = CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS
