"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class ASCEAdapter(AtyponAdapter):
    """ASCE Library (ascelibrary.org), an Atypon site: the shared rules, nothing of its own (2026-11-02)."""

    publisher = "asce"
    site_hosts = frozenset({"ascelibrary.org", "www.ascelibrary.org"})
