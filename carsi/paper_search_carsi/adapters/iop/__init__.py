"""IOP Publishing: journals on iopscience.iop.org.

Without access the article page offers "Access this article" or "Access
through your institution". The institution login starts at myIOPscience's
sign-in (``myiopscience.iop.org/signin``) with the article as its target.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlparse

from ...engine.batch_common import open_page
from ..base import PublisherAdapter, register


@register
class IOPAdapter(PublisherAdapter):
    publisher = "iop"

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        current_url = str(getattr(page, "url", "") or "")
        host = (urlparse(current_url).hostname or "").lower()
        if host == "openathens.net" or host.endswith(".openathens.net"):
            return None  # a federation page: the engine clicks nothing there
        if "iopscience.iop.org/article/" not in current_url.lower():
            return None
        text = self.d._body_text(page, 5_000).lower()
        if "access this article" not in text and "access through your institution" not in text:
            return None
        signin_url = "https://myiopscience.iop.org/signin?" + urlencode(
            {"origin": "deeplink", "target": current_url}
        )
        try:
            open_page(page, signin_url, timeout_ms=30_000)
            if result is not None:
                self.d._event(result, "sso_entry_clicked", signin_url)
            return True
        except Exception as exc:
            if result is not None:
                self.d._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
            return None  # the generic entries are tried next
