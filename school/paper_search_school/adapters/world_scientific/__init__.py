"""World Scientific: journals on worldscientific.com, on the Atypon platform
(``platforms/atypon``): its pages carry Literatum's markers and cookies
(2026-11-03; no public announcement found).

Its chooser at ``/action/ssostart`` shows either the institution search or
lists for the federation and the institution.
"""
from __future__ import annotations

from typing import Any

from ..base import register
from ..platforms.atypon import (
    CLASSIC_TEMPLATE_FULLTEXT_IMAGES_JS,
    CLASSIC_TEMPLATE_FULLTEXT_PREPARE_JS,
    CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS,
    AtyponAdapter,
)


@register
class WorldScientificAdapter(AtyponAdapter):
    publisher = "world scientific"
    site_hosts = frozenset({"www.worldscientific.com", "worldscientific.com"})
    # --fulltext: Atypon's older template (platforms/atypon), as Taylor & Francis: the body
    # .hlFld-Fulltext, figures as <figure> with the full-size image in data-lg-src, the
    # references in the page's side tab (International Journal of Neural Systems, 2026-11-15).
    fulltext_shown_js = CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS
    fulltext_images_js = CLASSIC_TEMPLATE_FULLTEXT_IMAGES_JS
    fulltext_prepare_js = CLASSIC_TEMPLATE_FULLTEXT_PREPARE_JS

    def chooser_block_reason(self, page: Any, url: str, text: str) -> str | None:
        if "worldscientific.com/action/ssostart" not in url:
            return None
        federation = self.d.federation
        if (any(label in text for label in ("find your institution", "type the name of your institution",
                                            "select your federation", "select your institution"))
                or (federation is not None and federation.matches(text))):
            return ""
        return "sso_redirect_stalled"
