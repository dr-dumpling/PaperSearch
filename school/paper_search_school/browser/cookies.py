"""Publisher cookies the download browser saved: kept, merged and restored.

Signing in is the download's own work (``login`` runs its steps without the
PDF); the old window that only captured cookies was removed on 2026-11-09.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..log import get_logger

log = get_logger()

# Publisher domains that benefit from institutional cookies
PUBLISHER_DOMAINS = [
    "sciencedirect.com",
    "elsevier.com",
    "springer.com",
    "springerlink.com",
    "link.springer.com",
    "onlinelibrary.wiley.com",
    "wiley.com",
    "ieeexplore.ieee.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "sciencemag.org",
    "tandfonline.com",
    "pnas.org",
    "jstor.org",
    "acs.org",
    "rsc.org",
    "cambridge.org",
    "oup.com",
    "academic.oup.com",
    "sagepub.com",
    "sage.cnpereading.com",
    "mdpi.com",
    "frontiersin.org",
]

# Cloudflare bot-management cookies: they carry no login.
_CLOUDFLARE_COOKIE_NAMES = {"__cf_bm", "_cfuvid", "cf_clearance", "cf_chl_rc_ni"}


def _save_cookies_json(cookies: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")


def cookies_to_netscape(cookies: list[dict[str, Any]]) -> str:
    """Convert a list of cookie dicts to Netscape HTTP Cookie File format."""
    lines = ["# Netscape HTTP Cookie File\n"]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = str(int(c.get("expires", 0)) or 0)
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    return "".join(lines)


def _save_cookies_netscape(cookies: list[dict[str, Any]], output_path: Path) -> None:
    output_path.write_text(cookies_to_netscape(cookies), encoding="utf-8")


def _is_publisher_cookie(cookie: dict[str, Any]) -> bool:
    """Check if a cookie belongs to a known publisher domain."""
    domain = cookie.get("domain", "").lstrip(".").lower()
    return any(domain == d or domain.endswith("." + d) for d in PUBLISHER_DOMAINS)


def load_saved_cookies(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Load previously saved publisher cookies, filtering out expired ones."""
    from ..config import DATA_DIR
    cookie_file = Path(config.get("cache_dir", str(DATA_DIR / "cache"))) / "publisher_cookies.json"
    if not cookie_file.exists():
        return []
    try:
        cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    now = time.time()
    return [c for c in cookies if _is_cookie_valid(c, now)]


def _is_cookie_valid(cookie: dict[str, Any], now: float | None = None) -> bool:
    """Keep session cookies (expires=-1/0) and unexpired persistent cookies."""
    expires = cookie.get("expires", 0)
    if not expires or expires in (-1, 0):
        return True
    if now is None:
        now = time.time()
    return expires > now


def inject_cookies(session: Any, config: dict[str, Any]) -> None:
    """Inject saved publisher cookies into a requests.Session."""
    cookies = load_saved_cookies(config)
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))


def _restore_cookies_to_context(
    context: Any, config: dict[str, Any], *, preserve_existing: bool = False,
) -> bool:
    try:
        existing = {
            (c["name"], c["domain"], c.get("path", "/"))
            for c in context.cookies()
        } if preserve_existing else set()
        saved = load_saved_cookies(config)
        if saved:
            pw_cookies = []
            for c in saved:
                if (c.get("name"), c.get("domain"), c.get("path", "/")) in existing:
                    continue
                pw_c = {"name": c.get("name", ""), "value": c.get("value", ""),
                         "domain": c.get("domain", ""), "path": c.get("path", "/")}
                for key in ("expires", "secure", "httpOnly", "sameSite"):
                    if key in c:
                        pw_c[key] = c[key]
                # Older exports use 0 for a session; Playwright uses -1.
                # Keep persistent expiry timestamps unchanged.
                if pw_c.get("expires") == 0:
                    pw_c["expires"] = -1
                if pw_c["domain"]:
                    pw_cookies.append(pw_c)
            if pw_cookies:
                context.add_cookies(pw_cookies)
        return True
    except Exception:
        log.info("publisher_session_restore_failed")
        return False


def merge_cookies(new_cookies: list[dict[str, Any]], config: dict[str, Any], *,
                  publisher_domains: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Merge new cookies into saved publisher cookies, dedup by (name, domain, path).

    Filters to publisher domains only. Updates existing cookies in-place
    (new value overwrites old) and appends genuinely new ones. Saves both
    JSON and Netscape formats.

    Returns the merged cookie list.
    """
    from ..config import DATA_DIR

    cache_dir = Path(config.get("cache_dir", str(DATA_DIR / "cache")))
    cookie_file = cache_dir / "publisher_cookies.json"
    netscape_file = cache_dir / "publisher_cookies.txt"

    existing = load_saved_cookies(config)

    # Build index of existing cookies by (name, domain, path)
    key = lambda c: (c.get("name", ""), c.get("domain", ""), c.get("path", "/"))
    merged: dict[tuple, dict[str, Any]] = {key(c): c for c in existing}

    for c in new_cookies:
        if publisher_domains is None:
            accepted = _is_publisher_cookie(c)
        else:
            domain = str(c.get("domain", "")).lstrip(".").lower()
            accepted = any(domain == allowed or domain.endswith("." + allowed)
                           for allowed in publisher_domains)
        if not accepted:
            continue
        merged[key(c)] = c

    result = list(merged.values())

    if result:
        _save_cookies_json(result, cookie_file)
        _save_cookies_netscape(result, netscape_file)

    return result
