"""Stream attachments with the active browser session, outside the RPC body channel."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import requests


class Response:
    def __init__(self, response: requests.Response):
        self._response = response
        self.status = response.status_code
        self.ok = response.ok
        self.headers = response.headers

    def chunks(self):
        # read1 returns available data instead of waiting to fill a whole chunk;
        # the collector can enforce its deadline even on a trickling server.
        while chunk := self._response.raw.read1(64 * 1024, decode_content=True):
            yield chunk

    def dispose(self):
        self._response.close()


class Request:
    def __init__(self, session: requests.Session):
        self._session = session

    def get(self, url: str, *, timeout: int):
        # Only connection/header acquisition happens here. Subsequent reads have
        # an idle timeout; a progressing large file is not a frozen browser RPC.
        return Response(self._session.get(url, stream=True, timeout=(10, timeout / 1000)))


@contextmanager
def browser_request(page: Any, config: dict, *, proxy: str | None = None):
    """Keep cookie domain/path/secure scope and the browser's configured egress.

    Cookies remain in memory. Requests' redirect handling reapplies cookie scope
    on each host; no manually copied Cookie header follows cross-site redirects.
    """
    with requests.Session() as session:
        session.trust_env = False
        proxy = str(proxy or config.get("browser_static_proxy") or config.get("network_proxy") or "").strip()
        if proxy:
            session.proxies.update(http=proxy, https=proxy)
        session.headers.update({"User-Agent": page.evaluate("navigator.userAgent"),
                                "Referer": str(page.url)})
        for cookie in page.context.cookies():
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"],
                                path=cookie.get("path", "/"), secure=bool(cookie.get("secure")),
                                expires=int(cookie["expires"]) if cookie.get("expires", -1) > 0 else None)
        yield Request(session)
