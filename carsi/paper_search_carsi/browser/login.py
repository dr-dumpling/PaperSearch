"""Institutional login via stealth browser: the window of ``login --kind custom``."""

from __future__ import annotations

import json
import time
import atexit
from pathlib import Path
from typing import Any

try:
    from .backend import launch
    from .backend import BACKEND_CAMOUFOX
    from .backend import is_available as _browser_backend_available
    _HAS_CLOAKBROWSER = _browser_backend_available(BACKEND_CAMOUFOX)
except ImportError:
    launch = None  # type: ignore[assignment]
    _HAS_CLOAKBROWSER = False
from ..log import get_logger

log = get_logger()


class PersistentBrowser:
    """Keeps a stealth browser alive across multiple operations.

    Login once, reuse the same browser for all subsequent downloads.
    The WebVPN session stays valid because the browser instance never closes.
    """

    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None
        self._cookies_saved = False

    @property
    def is_alive(self) -> bool:
        if self._browser is None:
            return False
        try:
            self._page.url  # noqa: B018
            return True
        except Exception:
            self._cleanup()
            return False

    def get_page(self, config: dict[str, Any] | None = None):
        """Get or create the browser page. Returns (context, page)."""
        if self.is_alive:
            return self._context, self._page
        return self._start(config)

    def _start(self, config: dict[str, Any] | None = None):
        """Start a new browser instance. Restores saved state if available."""
        if not _HAS_CLOAKBROWSER:
            raise RuntimeError("camoufox not installed. Run: pip install 'camoufox[geoip]' && python -m camoufox fetch")
        log.info("   [browser] Starting persistent browser...")
        self._browser = launch(
            headless=False, humanize=True,
            args=["--disable-features=CrossOriginOpenerPolicy"],
        )
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

        if config:
            self._restore_state(config)

        return self._context, self._page

    def _restore_state(self, config: dict[str, Any]):
        """Restore saved cookies and localStorage into the browser."""
        from ..config import DATA_DIR
        cache_dir = Path(config.get("cache_dir", str(DATA_DIR / "cache")))
        state_file = cache_dir / "browser_state.json"
        if not state_file.exists():
            return
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            log.info("   [browser] browser_state.json corrupted, starting fresh")
            return

        cookies = state.get("cookies", [])
        if cookies:
            try:
                self._context.add_cookies(cookies)
                log.info(f"   [browser] Restored {len(cookies)} cookies")
            except Exception as e:
                log.info(f"   [browser] Cookie restore warning: {e}")

        storage = state.get("localStorage", {})
        for origin, items in storage.items():
            try:
                self._page.goto(origin, wait_until="commit", timeout=10000)
                for key, value in items.items():
                    self._page.evaluate(f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)})")
            except Exception as e:
                log.info(f"   [browser] localStorage restore failed for {origin}: {e}")

        log.info("   [browser] Browser state restored")

    def save_cookies(self, config: dict[str, Any]):
        """Save current browser state (cookies + localStorage) to disk."""
        if not self._context:
            return
        try:
            from ..config import DATA_DIR
            cache_dir = Path(config.get("cache_dir", str(DATA_DIR / "cache")))
            cache_dir.mkdir(parents=True, exist_ok=True)

            cookies = self._context.cookies()

            localStorage = {}
            for page in self._context.pages:
                try:
                    url = page.url
                    if url.startswith("http"):
                        from urllib.parse import urlparse
                        origin = f"{urlparse(url).scheme}://{urlparse(url).hostname}"
                        items = page.evaluate("""
                            (() => {
                                const items = {};
                                for (let i = 0; i < localStorage.length; i++) {
                                    const key = localStorage.key(i);
                                    items[key] = localStorage.getItem(key);
                                }
                                return items;
                            })()
                        """)
                        if items:
                            localStorage[origin] = items
                except Exception:
                    pass

            state = {"cookies": cookies, "localStorage": localStorage}
            state_file = cache_dir / "browser_state.json"
            state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

            cookie_file = cache_dir / "instsci-cookies.json"
            cookie_data = [
                {"name": c["name"], "value": c["value"], "domain": c.get("domain", ""), "path": c.get("path", "/")}
                for c in cookies
            ]
            cookie_file.write_text(json.dumps(cookie_data, indent=2, ensure_ascii=False), encoding="utf-8")

            netscape_file = cache_dir / "instsci-cookies.txt"
            from .cookies import cookies_to_netscape
            netscape_file.write_text(cookies_to_netscape(cookies), encoding="utf-8")

            self._cookies_saved = True
            log.info(f"   [browser] Saved {len(cookies)} cookies + {len(localStorage)} localStorage origins")
        except Exception as e:
            log.info(f"   [browser] Failed to save state: {e}")

    def _cleanup(self):
        """Close browser gracefully."""
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None

    def close(self):
        """Explicitly close the browser."""
        self._cleanup()
        log.info("   [browser] Persistent browser closed")


# Module-level singleton
_browser = PersistentBrowser()
atexit.register(_browser.close)


def get_browser(config: dict[str, Any] | None = None):
    """Get the persistent browser singleton. Returns (browser, context, page)."""
    context, page = _browser.get_page(config)
    return _browser, context, page


def save_browser_cookies(config: dict[str, Any]):
    """Save cookies from the persistent browser."""
    _browser.save_cookies(config)


def close_browser():
    """Close the persistent browser."""
    _browser.close()


def _save_cookies_json(cookies: list[dict[str, Any]], cookie_file: Path) -> None:
    """Save cookies in JSON format."""
    cookie_data = [
        {"name": c["name"], "value": c["value"], "domain": c.get("domain", ""), "path": c.get("path", "/")}
        for c in cookies
    ]
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(
        json.dumps(cookie_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _save_cookies_netscape(cookies: list[dict[str, Any]], cookie_file: Path) -> None:
    """Save cookies in Netscape format (Camoufox import compatible)."""
    from .cookies import cookies_to_netscape
    cookie_file.write_text(cookies_to_netscape(cookies), encoding="utf-8")


def _import_to_browser(cookie_file: Path, config: dict[str, Any]) -> int:
    """Import cookies into Camoufox. Returns count imported."""
    try:
        from .engine import import_cookies, is_available
        if not is_available(config):
            log.info("   [browser] Camoufox not running, skipping auto-import")
            return 0
        count = import_cookies(cookie_file, config)
        log.info(f"   [browser] Imported {count} cookies into Camoufox")
        return count
    except Exception as exc:
        log.info(f"   [browser] Could not auto-import to Camoufox: {exc}")
        return 0


def open_login_browser(
    url: str,
    config: dict[str, Any],
    *,
    cookie_file: Path,
    detect_login: Any = None,
    max_wait: int = 300,
    auto_import: bool = True,
    keep_alive: bool = False,
    publisher: str = "",
) -> bool | tuple[bool, Any, Any, Any]:
    """Open a visible stealth browser for interactive login.

    Args:
        url: Login URL to open.
        config: backend config dict.
        cookie_file: Path to save captured cookies (JSON).
        detect_login: Optional callable(browser_context, page) -> bool for custom login detection.
        max_wait: Max seconds to wait for login.
        auto_import: Whether to auto-import cookies into Camoufox.
        keep_alive: If True, return (True, context, page) without closing browser.
        publisher: Publisher name (unused; kept for callers).

    Returns:
        True if login succeeded, or (True, context, page) if keep_alive.
    """
    log.info(f"   [browser] Opening stealth browser: {url}")
    print(f"\n  请在浏览器中登录 ({url})")
    print("  程序会自动检测登录完成...\n")

    if not _HAS_CLOAKBROWSER:
        log.info("   [browser] camoufox not installed")
        return (False, None, None, None) if keep_alive else False

    try:
        browser = launch(headless=False, humanize=True,
                         args=["--disable-features=CrossOriginOpenerPolicy"])
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            log.info(f"   [browser] Page load warning: {exc}")
            print("  页面加载超时，但仍可手动登录。")

        elapsed = 0
        while elapsed < max_wait:
            try:
                page.wait_for_timeout(3000)
                elapsed += 3
                current_url = page.url
            except Exception:
                log.info("   [browser] Browser closed by user.")
                if not keep_alive:
                    try:
                        browser.close()
                    except Exception:
                        pass
                return (False, None, None, None) if keep_alive else False

            # A custom detector is authoritative: when it says "not yet", the
            # generic URL-shape fallback below must NOT confirm the login —
            # it used to bless an unauthenticated redirect to the publisher
            # (cookie count > 3) as success for CARSI/EZProxy (#29, #62).
            if detect_login is not None:
                if detect_login(context, page):
                    cookies = context.cookies()
                    _save_cookies_json(cookies, cookie_file)
                    netscape_path = cookie_file.with_suffix(".txt")
                    _save_cookies_netscape(cookies, netscape_path)
                    log.info(f"   [browser] Login successful! Saved {len(cookies)} cookies.")
                    print(f"  登录成功！Cookie 已保存至 {cookie_file}")
                    if auto_import:
                        _import_to_browser(netscape_path, config)
                    if keep_alive:
                        return True, context, page
                    browser.close()
                    return True
                continue

            url_lower = current_url.lower()
            if "login" not in url_lower and "cas" not in url_lower and "sso" not in url_lower:
                cookies = context.cookies()
                if len(cookies) > 3:
                    _save_cookies_json(cookies, cookie_file)
                    netscape_path = cookie_file.with_suffix(".txt")
                    _save_cookies_netscape(cookies, netscape_path)
                    log.info(f"   [browser] Login successful! Saved {len(cookies)} cookies.")
                    print(f"  登录成功！Cookie 已保存至 {cookie_file}")
                    if auto_import:
                        _import_to_browser(netscape_path, config)
                    if keep_alive:
                        return True, context, page
                    browser.close()
                    return True

        print("  登录超时。")
        if not keep_alive:
            try:
                browser.close()
            except Exception:
                pass
        return (False, None, None, None) if keep_alive else False

    except Exception as exc:
        log.info(f"   [browser] Login error: {exc}")
        print(f"  登录出错: {exc}")
        return (False, None, None, None) if keep_alive else False
