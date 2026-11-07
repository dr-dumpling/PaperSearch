"""World Scientific: journals on worldscientific.com, on the Atypon platform
(``platforms/atypon``): its pages carry Literatum's markers and cookies
(2026-11-03; no public announcement found).

Its chooser at ``/action/ssostart`` shows either the institution search or
lists for the federation and the institution.
"""
from __future__ import annotations

from typing import Any

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class WorldScientificAdapter(AtyponAdapter):
    publisher = "world scientific"
    site_hosts = frozenset({"www.worldscientific.com", "worldscientific.com"})

    def chooser_block_reason(self, page: Any, url: str, text: str) -> str | None:
        if "worldscientific.com/action/ssostart" not in url:
            return None
        if any(label in text for label in ("find your institution", "type the name of your institution",
                                           "select your federation", "select your institution",
                                           "china cernet federation (carsi)")):
            return ""
        return "sso_redirect_stalled"
