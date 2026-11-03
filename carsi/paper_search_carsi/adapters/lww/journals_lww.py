"""journals.lww.com: LWW journal pages (Hepatology, JBJS, Medicine, ...).

Without access the subscriber panel below the abstract says "Full Text Access
for Subscribers" and shows "Check Access" (offers of the shared access rule)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

HOST = "journals.lww.com"


def is_page(url: str) -> bool:
    return (urlparse(url or "").hostname or "").lower() == HOST


class JournalsLwwSite:
    """Answers for journals.lww.com pages; ``None`` = no opinion."""

    def __init__(self, downloader: Any):
        self.d = downloader

    def open_institution_entry(self, page: Any, result: Any) -> bool:
        # The subscriber panel offers "Institutional Users - Access through
        # Ovid"; never the individual-subscriber or society logins.
        for control in page.locator("a, button, [role='button']").filter(
                has_text=re.compile(r"Institutional\s+Users", re.I)).all():
            try:
                if control.is_visible() is True:
                    control.click(timeout=10_000, no_wait_after=True)
                    self.d._event(result, "sso_entry_clicked", "lww-institutional-users")
                    return True
            except Exception:
                continue
        return False
