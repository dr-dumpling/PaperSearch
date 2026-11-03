"""BMJ: journals on <journal>.bmj.com (HighWire).

Without access the article page offers the article for sale ("Buy this
article", an offer of the shared access rule). The institution login is HighWire's "Log in via Institution", a
Shibboleth discovery page on the journal's own host (``/login/shibboleth``).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from ...engine.batch_common import open_page
from ..base import PublisherAdapter, register


@register
class BMJAdapter(PublisherAdapter):
    publisher = "bmj"

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        """HighWire's "Log in via Institution"; the login menu also holds
        personal and society logins, which are never used."""
        host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower()
        if not host.endswith("bmj.com"):
            return None
        for control in page.locator('a[href*="/login/shibboleth"]').all():
            target = urlparse(urljoin(str(page.url), control.get_attribute("href") or ""))
            if target.scheme == "https" and target.hostname == host and target.path == "/login/shibboleth":
                open_page(page, target.geturl(), timeout_ms=30_000)
                self.d._event(result, "sso_entry_clicked", "bmj-institution-login")
                return True
        return False
