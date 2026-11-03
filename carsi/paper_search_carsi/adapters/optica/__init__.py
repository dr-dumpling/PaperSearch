"""Optica (formerly OSA): journals on opg.optica.org.

Without access the article page says "Not Accessible" with "Your library or
personal account may give you access" (an offer of the shared access rule).
Its LOGIN modal holds a personal
email/password form and the "Institutional Login" link (auth.optica.org's
``/connect/authorize``, then OpenAthens).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from ...engine.batch_common import open_page
from ..base import PublisherAdapter, register


@register
class OpticaAdapter(PublisherAdapter):
    publisher = "optica"

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        """The modal's "Institutional Login" link, opened directly; the personal form is never used."""
        if (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower() != "opg.optica.org":
            return None
        for control in page.locator('a[href*="auth.optica.org"]').all():
            target = urlparse(urljoin(str(page.url), control.get_attribute("href") or ""))
            if (target.scheme == "https" and target.hostname == "auth.optica.org"
                    and target.path == "/connect/authorize"):
                open_page(page, target.geturl(), timeout_ms=30_000)
                self.d._event(result, "sso_entry_clicked", "optica-institutional-login")
                return True
        return False
