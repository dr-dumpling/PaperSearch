"""Karger: journals on karger.com (Silverchair, ``silverchair.py``).

Its article pages are the platform's. The header's
LOGIN menu holds the Shibboleth/OpenAthens federation gateway
(``/ExternalAuthentication/OpenAthensKeystoneLogin``), separate from Karger's
institutional username/password login; it leads to OpenAthens's wayfinder,
which can show a remembered school.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from ...browser.driver import is_driver_error
from ...engine.batch_common import open_page
from ..base import register
from ..platforms.silverchair import SilverchairAdapter


@register
class KargerAdapter(SilverchairAdapter):
    publisher = "karger"
    site_hosts = frozenset({"karger.com"})

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        d = self.d
        if (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower() != "karger.com":
            return None
        entry_path = "/ExternalAuthentication/OpenAthensKeystoneLogin"
        menu = page.get_by_role("button", name=re.compile(r"^LOGIN(?:\s+Open Menu)?$", re.I))
        entry = page.locator(f'a[href*="{entry_path}"]').first
        if not entry.is_visible() and menu.count() and menu.is_visible():
            menu.click(timeout=5_000, no_wait_after=True)
            d._event(result, "publisher_login_menu_opened", "karger")
        # Karger's observed Shibboleth/OpenAthens federation gateway is
        # separate from its institutional username/password login.
        for control in page.locator('a[href]').all():
            target = urlparse(urljoin(str(page.url), control.get_attribute("href") or ""))
            if (target.scheme == "https" and target.hostname == "karger.com"
                    and target.path == entry_path and control.is_visible()):
                # A click on this menu link was observed to leave the
                # article page in place; the validated gateway URL itself
                # reaches the federation chooser.
                open_page(page, target.geturl(), timeout_ms=30_000)
                d._event(result, "sso_entry_clicked", "karger-official-institution-control")
                return True
        return False

    def prepare_institution_choice(self, page: Any, result: Any) -> bool | None:
        """On OpenAthens's wayfinder, "Find another institution..." once instead of the remembered school."""
        d = self.d
        current = urlparse(str(page.url))
        if (current.scheme == "https" and current.hostname == "wayfinder.openathens.net"
                and not any(e["state"] == "karger_institution_chooser_opened" for e in result.events)):
            # This is the publisher's federation discovery page, not
            # an OpenAthens account form. Never choose a remembered school.
            try:
                active = d._has_visible_editable_input(page)
                change = page.get_by_role("button",name="Find another institution...",exact=True)
                if not active and change.is_visible():
                    change.click(timeout=5_000,no_wait_after=True)
                    d._event(result,"karger_institution_chooser_opened")
            except Exception as exc:
                # The user can select a school while this observation
                # runs. Keep waiting on the same page after navigation;
                # do not reopen the chooser or restart authentication.
                if (not is_driver_error(exc)
                        or not any(marker in str(exc) for marker in (
                            "Execution context was destroyed",
                            "Cannot find context with specified id",
                        ))):
                    raise
                d._event(result, "login_navigation_interrupted", "karger-institution-selection")
                return False
        return None
