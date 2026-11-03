"""Taylor & Francis Online: journals on tandfonline.com, DOI paths.

An Atypon site (``atypon.py``): its institution login is the Shibboleth
chooser at ``/action/ssostart`` with a federation dropdown, then the school.
Its own rule here is the supplement box. Dove Medical Press (open access)
needs no adapter.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..platforms.atypon import AtyponAdapter
from ..base import SupplementLink, register

_HOSTS = frozenset({"tandfonline.com", "www.tandfonline.com"})
# The supplement box's download links with the box's text (file name and size).
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="downloadSupplement"]')].map(a => {
    const box = a.closest('.supplement-box, li, tr');
    return {href: a.href, label: ((box || a).innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200)};
})"""


@register
class TaylorFrancisAdapter(AtyponAdapter):
    publisher = "taylor & francis"
    site_hosts = _HOSTS
    entry_event = "tandf-institution-link"
    # A viewer's first range can start with %PDF yet contain no usable pages.
    requires_complete_pdf = True

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """``/action/downloadSupplement?doi=<this DOI>&file=<name>`` (the Supplemental box)."""
        links: list[SupplementLink] = []
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) and doi else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            query = parse_qs(target.query)
            url = target._replace(fragment="").geturl()
            if (target.scheme == "https" and (target.hostname or "").lower() in _HOSTS
                    and target.path == "/action/downloadSupplement"
                    and query.get("doi", [""])[0].lower() == doi.lower()
                    and url not in {link.url for link in links}):
                name = query.get("file", [""])[0]
                links.append(SupplementLink(url, f"{name} {row.get('label') or ''}".strip()))
        return links
