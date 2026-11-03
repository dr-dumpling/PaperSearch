"""World Scientific: journals on worldscientific.com, on the Atypon platform
(``platforms/atypon``): its pages carry Literatum's markers and cookies
(2026-11-03; no public announcement found).

Its own rule: the chooser at ``/action/ssostart`` shows an institution search
("Find your institution", "Type the name of your institution"); the same
address without it is a redirect that stalled.
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
        if "find your institution" in text or "type the name of your institution" in text:
            return ""
        return "sso_redirect_stalled"
