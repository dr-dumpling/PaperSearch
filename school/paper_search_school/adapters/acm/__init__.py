"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ...engine.fulltext_page import MATHJAX_SOURCES_JS
from ..base import register
from ..platforms.atypon import CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS, CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS, AtyponAdapter


@register
class ACMAdapter(AtyponAdapter):
    """The ACM Digital Library on dl.acm.org: on Atypon's Literatum since 2017 (ACM, 2017-10-03)."""

    publisher = "acm"
    site_hosts = frozenset({"dl.acm.org"})
    # The full-text page for the Markdown: Atypon's current template (PACM HCI, 2026-11-15);
    # many ACM articles have only their PDF, whose page shows the abstract.
    fulltext_shown_js = CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS
    fulltext_images_js = CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS
    fulltext_prepare_js = MATHJAX_SOURCES_JS
