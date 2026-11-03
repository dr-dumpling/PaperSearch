"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class AHAJournalsAdapter(AtyponAdapter):
    """AHA journals (Circulation, Stroke, ...) on ahajournals.org."""

    publisher = "aha journals"
    site_hosts = frozenset({"ahajournals.org", "www.ahajournals.org"})
