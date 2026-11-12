"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class PNASAdapter(AtyponAdapter):
    """PNAS on pnas.org: on Atypon's platform since 2022 (Atypon, 2022-03-16)."""

    publisher = "pnas"
    site_hosts = frozenset({"www.pnas.org", "pnas.org"})
