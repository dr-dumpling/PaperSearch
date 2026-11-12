"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class ACMAdapter(AtyponAdapter):
    """The ACM Digital Library on dl.acm.org: on Atypon's Literatum since 2017 (ACM, 2017-10-03)."""

    publisher = "acm"
    site_hosts = frozenset({"dl.acm.org"})
