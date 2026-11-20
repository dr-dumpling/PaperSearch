"""The school's sign-in filled in for the user, a PaperSearch Pro feature.

This is the public side: where the account is kept, which pages may be given it, how often,
and the loading of Pro's part, which finds the form, fills it, submits it and says how that
went. Without Pro, or for a school Pro has not tested, nothing is filled and the user signs in
as before.

The account is kept in the backend's config file (user, 2026-11-19), under ``school_logins``
by the school's entityID; ``config show`` masks it and reports leave it out (report_sanitizer).
Nothing here writes the account into an event, a log or a diagnostic file.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .edition import pro_features

log = logging.getLogger(__name__)

#: Pro's part, written by PaperSearch once Pro's access check has passed (pro.ts): the package's
#: ``school_login/__init__.py`` (its schools in ``schools/<federation>/``), or a single file.
MODULE_ENV = "PAPER_SEARCH_PRO_SCHOOL_LOGIN"
#: Maintainers testing a school Pro lists as still being tested ("trial").
TRIAL_ENV = "PAPER_SEARCH_SCHOOL_LOGIN_TRIAL"
#: Maintainers surveying schools' sign-in pages without their accounts: "1", what Pro finds there and
#: whether the sign-in control takes a click (a trial click), nothing filled in or sent; "press", a
#: made-up account typed in and the control pressed for real, once, and what the school answered.
SURVEY_ENV = "PAPER_SEARCH_SCHOOL_LOGIN_SURVEY"
#: The interface between this file and Pro's part.
API = 1
CONFIG_KEY = "school_logins"
#: Sign-ins filled in per school and hour. About one an hour is normal (a school's sign-in
#: lasts an hour at the shortest seen); more means something keeps failing.
PER_HOUR = 6
HOUR = 3600

_loaded: tuple[str, Any] | None = None


def module() -> Any | None:
    """Pro's part, or None: no Pro, its access not given, or another interface."""
    global _loaded
    path = os.environ.get(MODULE_ENV, "").strip()
    if not path or not pro_features() or not Path(path).is_file():
        return None
    if _loaded is not None and _loaded[0] == path:
        return _loaded[1]
    name = "papersearch_pro_school_login"
    package = [str(Path(path).parent)] if Path(path).name == "__init__.py" else None
    try:
        spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=package)
        if spec is None or spec.loader is None:
            return None
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded  # its own modules import it by name
        spec.loader.exec_module(loaded)
    except Exception as exc:  # Pro's part does not load: no filling in, the downloads go on
        sys.modules.pop(name, None)
        log.warning("PaperSearch Pro's school sign-in did not load: %s: %s", type(exc).__name__, exc)
        return None
    if getattr(loaded, "API", None) != API:
        log.warning("PaperSearch Pro's school sign-in has interface %s, this backend %s; update Pro",
                    getattr(loaded, "API", None), API)
        return None
    _loaded = (path, loaded)
    return loaded


def school_status(entity_id: str, pro: Any | None = None) -> str:
    """``verified`` (signed in for real), ``surveyed`` (its form filled in and pressed, the school's
    "wrong password" read: user, 2026-11-19, enough), ``trial`` (being tested), or "" (not tested)."""
    pro = pro if pro is not None else module()
    if pro is None or not entity_id:
        return ""
    try:
        status = str(pro.school_status(entity_id) or "")
    except Exception:
        return ""
    return status if status in {"verified", "surveyed", "trial"} else ""


def fills_for(entity_id: str, pro: Any | None = None) -> bool:
    """Whether Pro fills this school's sign-in in: tested or surveyed, or being tested by a maintainer."""
    status = school_status(entity_id, pro)
    return status in {"verified", "surveyed"} or (status == "trial" and os.environ.get(TRIAL_ENV) == "1")


# -- the account ------------------------------------------------------------------------------

def _logins(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get(CONFIG_KEY)
    return value if isinstance(value, dict) else {}


def saved(config: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    """The school's saved account ({username, password, enabled, off}), or None."""
    entry = _logins(config).get(entity_id) if entity_id else None
    if not isinstance(entry, dict) or not entry.get("username") or not entry.get("password"):
        return None
    return entry


def masked(username: str) -> str:
    """The account as shown once saved: its first and last characters."""
    name = str(username or "")
    return name if len(name) <= 2 else name[0] + "*" * min(6, len(name) - 2) + name[-1]


def save(entity_id: str, username: str, password: str, *, enabled: bool = True) -> None:
    """Keep the school's account (``enabled``: whether Pro fills it in)."""
    from . import config as cfg

    if not entity_id:
        raise ValueError("还没有设置学校")
    current = cfg.load_config()
    entry = _logins(current).get(entity_id) if isinstance(_logins(current).get(entity_id), dict) else {}
    # A field left empty keeps what was saved: the switch, or one of the two changed.
    username = str(username or "").strip() or str(entry.get("username") or "")
    password = str(password or "") or str(entry.get("password") or "")
    if not username:
        raise ValueError("请填写账号")
    if not password:
        raise ValueError("请填写密码")
    logins = dict(_logins(current))
    logins[entity_id] = {"username": username, "password": password, "enabled": bool(enabled), "off": "",
                         "saved": time.strftime("%Y-%m-%d %H:%M")}
    current[CONFIG_KEY] = logins
    cfg.save_config(current)


def clear(entity_id: str) -> None:
    from . import config as cfg

    current = cfg.load_config()
    logins = dict(_logins(current))
    if logins.pop(entity_id, None) is not None:
        current[CONFIG_KEY] = logins
        cfg.save_config(current)


def turn_off(entity_id: str, why: str) -> None:
    """Stop filling this school's sign-in in until the user saves the account again."""
    from . import config as cfg

    current = cfg.load_config()
    logins = dict(_logins(current))
    entry = logins.get(entity_id)
    if isinstance(entry, dict):
        logins[entity_id] = {**entry, "enabled": False, "off": why}
        current[CONFIG_KEY] = logins
        cfg.save_config(current)


# -- where and how often ----------------------------------------------------------------------

def may_fill(url: str, config: dict[str, Any], also: tuple[str, ...] = ()) -> bool:
    """An https page of the school's own: one of its login hosts as its federation lists them,
    or under its own domains. Hosts merely passed through in a batch never count. ``also``: the
    hosts Pro has for this school's login page on another domain of its own (Pro's ``login_hosts``,
    found by its survey: a login system that sends to a login page on a second domain of the school's)."""
    from .schools import lookup

    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    if host in set(lookup.login_hosts(config)) or host in {str(h).lower() for h in also}:
        return True
    return any(host == domain or host.endswith("." + domain) for domain in lookup.domains(config))


def pro_login_hosts(pro: Any, entity_id: str) -> tuple[str, ...]:
    """Pro's hosts for this school's login page on another domain of its own (``may_fill``'s ``also``);
    none from a Pro without them."""
    hosts = getattr(pro, "login_hosts", None)
    try:
        return tuple(str(h).strip().lower() for h in (hosts(entity_id) if callable(hosts) else ()) if str(h).strip())
    except Exception:
        return ()


# -- a login page whose certificate has expired or is not trusted ---------------------------------
# Some schools' login pages serve a certificate Chrome will not take (one ran out in 2022;
# others are issued by an authority Chrome does not trust): Chrome stops at its warning. For those
# Pro's survey has recorded the certificate the page serves; the warning is passed, and the account
# typed in, only when the page then has that very certificate (user, 2026-11-20: fill those in too).
# Its key never leaves the school, so another server cannot show it: the account goes to the school.

def pro_certificates(pro: Any, entity_id: str) -> dict[str, str]:
    """Pro's certificates for this school's login pages that Chrome will not take: host -> the
    SHA-256 of the certificate (hex) its survey saw there; none from a Pro without them."""
    found = getattr(pro, "certificates", None)
    try:
        pins = found(entity_id) if callable(found) else {}
        return {str(h).strip().lower(): str(d).strip().lower() for h, d in dict(pins or {}).items() if str(h).strip() and str(d).strip()}
    except Exception:
        return {}


def page_certificate(page: Any, wait: float = 2.0) -> tuple[str, str]:
    """(the certificate error the page was let through with, "" for a certificate Chrome takes; the SHA-256
    of the page's own certificate), as Chrome shows them for the page (DevTools' Security domain).
    ("?", "") when they could not be read: a browser that is not Chromium, a page gone."""
    import base64
    import hashlib

    try:
        session = page.context.new_cdp_session(page)
    except Exception:
        return "?", ""
    seen: list[dict] = []
    try:
        session.on("Security.visibleSecurityStateChanged", lambda e: seen.append(dict(e.get("visibleSecurityState") or {})))
        session.send("Security.enable")  # the page's state comes at once
        deadline = time.time() + wait
        while not seen and time.time() < deadline:
            page.wait_for_timeout(100)
    except Exception:
        return "?", ""
    finally:
        try:
            session.detach()
        except Exception:
            pass
    if not seen:
        return "?", ""
    state = seen[-1].get("certificateSecurityState") or {}
    chain = state.get("certificate") or []
    try:
        digest = hashlib.sha256(base64.b64decode(chain[0])).hexdigest() if chain else ""
    except ValueError:
        digest = ""
    return str(state.get("certificateNetworkError") or ""), digest


def certificate_allows(host: str, error: str, digest: str, pins: dict[str, str]) -> bool:
    """Whether a page of ``host`` may get the account, by its certificate (``page_certificate``): one
    Chrome takes, or the very one Pro has for that host. A host Pro has one for, whose certificate
    could not be read, gets nothing; any other such page is as before (a browser without DevTools)."""
    host = (host or "").lower()
    if error == "?":
        return host not in pins
    return not error or bool(digest) and pins.get(host) == digest


#: Where Chrome's warning shows: its own error page, or about:blank for a page opened straight on the address.
WARNING_PAGES = ("chrome-error://", "about:blank")
#: Chrome's warning before a page whose certificate it will not take (its own error page).
_WARNING_JS = """(hosts) => {
  const advanced = document.getElementById('details-button'), go = document.getElementById('proceed-link');
  if (!advanced || !go) return '';
  const text = (document.body && document.body.innerText || '').toLowerCase();
  return hosts.find(h => text.includes(h)) || '';
}"""


def warning_for(page: Any, hosts: tuple[str, ...], tries: int = 3) -> str:
    """The host, of ``hosts``, Chrome's certificate warning on this page is for; "" when it is not
    such a warning (or one Chrome lets no one past: a host that insists on https, HSTS)."""
    for _ in range(max(1, tries)):
        # Chrome's own error page; a page opened straight on such an address still says about:blank.
        if not hosts or not str(getattr(page, "url", "") or "").startswith(WARNING_PAGES):
            return ""
        try:
            return str(page.evaluate(_WARNING_JS, [h.lower() for h in hosts]) or "")
        except Exception:  # the warning still being put up
            try:
                page.wait_for_timeout(500)
            except Exception:
                return ""
    return ""


def warning_certificate(host: str, error: str, digest: str, pins: dict[str, str]) -> bool:
    """Whether Chrome's warning for ``host`` is for the very certificate Pro has (``page_certificate`` read on
    the warning: the certificate offered, with Chrome's error); never past one whose certificate went unread."""
    return bool(error) and error != "?" and bool(digest) and pins.get((host or "").lower()) == digest


def pass_warning(page: Any, host: str, wait: float = 20.0) -> bool:
    """Chrome's warning passed as a person would (Advanced, then Proceed): True once the page of
    ``host`` has loaded in its place."""
    try:
        page.evaluate("() => { document.getElementById('details-button').click(); document.getElementById('proceed-link').click(); }")
    except Exception:
        pass  # the click goes on to the page at once, which may end the call: the page loading says whether it went
    deadline = time.time() + wait
    while time.time() < deadline:
        if (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower() == host.lower():
            try:
                page.wait_for_load_state("domcontentloaded", timeout=max(1000, int((deadline - time.time()) * 1000)))
            except Exception:
                pass
            return True
        try:
            page.wait_for_timeout(200)
        except Exception:
            return False
    return False


def _turns_file() -> Path:
    from .entitlements import _data_dir

    return _data_dir() / "school_sign_in.json"


def take_turn(entity_id: str, now: float | None = None) -> bool:
    """Count one sign-in filled in for this school; False when this hour has had PER_HOUR."""
    now = time.time() if now is None else now
    path = _turns_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    times = [t for t in data.get(entity_id) or [] if isinstance(t, (int, float)) and now - HOUR < t <= now]
    if len(times) >= PER_HOUR:
        return False
    data[entity_id] = [*times, now]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return True


# -- one sign-in --------------------------------------------------------------------------------

@dataclass
class Attempt:
    """What Pro's ``sign_in`` gets: the account, where it may be typed, and where to say what it did.

    ``event`` takes a state and a detail; it hides the account wherever a detail would carry it.
    """

    username: str
    password: str
    allowed: Callable[[str], bool]
    event: Callable[[str, str], None]
    hidden: tuple[str, ...] = field(default=(), repr=False)
    #: The school's entityID: its own rule, when Pro has one (schools/<federation>/<school>.py).
    school: str = ""
    #: Set by Pro on ``needs_user``: the kind of check the school's page asks the user for (image_code,
    #: slider, click_select, sms_code, qr_scan, site_check, second_factor), for the note the user reads.
    asks: str = ""

    def __repr__(self) -> str:  # never the account, not even in a traceback's locals
        return "Attempt(<hidden>)"


def hide(text: str, secrets: tuple[str, ...]) -> str:
    """``text`` with every secret replaced (an event's detail, defence in depth)."""
    for secret in secrets:
        if secret and len(secret) >= 3:
            text = text.replace(secret, "***")
    return text


#: How a sign-in went (Pro's ``sign_in``):
#: ``submitted`` the form was sent and the page moved on; ``rejected`` the school's page came back
#: asking again (a wrong password); ``needs_user`` a code, a captcha or a second factor;
#: ``no_form`` none found; ``unsafe_form`` more than one password field (changing a password);
#: ``not_allowed`` the form sits in a frame of another site; ``failed`` the page broke off.
OUTCOMES = ("submitted", "rejected", "needs_user", "no_form", "unsafe_form", "not_allowed", "failed")
