"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ...engine.fulltext_page import MATHJAX_SOURCES_JS
from ..base import register
from ..platforms.atypon import CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS, CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS, AtyponAdapter


@register
class ASCEAdapter(AtyponAdapter):
    """ASCE Library (ascelibrary.org), an Atypon site: the shared rules, nothing of its own (2026-11-02)."""

    publisher = "asce"
    site_hosts = frozenset({"ascelibrary.org", "www.ascelibrary.org"})
    # The full-text page for the Markdown: Atypon's current template; MathJax 3's MathML
    # kept before saving (Journal of Structural Engineering, 2026-11-15).
    fulltext_shown_js = CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS
    fulltext_images_js = CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS
    fulltext_prepare_js = MATHJAX_SOURCES_JS
