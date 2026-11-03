"""On the Atypon platform (``platforms/atypon``): only its hosts are its own.

The article page links only to NEJM's own sign-in page, whose "INSTITUTIONAL
SIGN IN" leads to the platform's chooser; the platform opens that chooser
directly (2026-11-03).
"""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class NEJMAdapter(AtyponAdapter):
    """NEJM Group journals: nejm.org and its journals' subdomains (NEJM Evidence, NEJM AI, NEJM Catalyst)."""

    publisher = "nejm"
    site_hosts = frozenset({"nejm.org", "www.nejm.org", "evidence.nejm.org", "ai.nejm.org", "catalyst.nejm.org"})
