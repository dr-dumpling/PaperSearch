"""On the Atypon platform (``platforms/atypon``): only its hosts are its own."""
from __future__ import annotations

from ..base import register
from ..platforms.atypon import AtyponAdapter


@register
class NeurologyAdapter(AtyponAdapter):
    """The AAN's Neurology journals on neurology.org."""

    publisher = "neurology"
    site_hosts = frozenset({"neurology.org", "www.neurology.org"})
