"""Browser backends: Camoufox (default) or ego-lite.

Exactly two backends are supported, selected by the ``browser_backend``
config key:

* ``camoufox`` (default) — an open-source anti-detect Firefox build driven
  through the standard Playwright sync API (``launch*`` return ordinary
  Playwright objects). Every Playwright-based route in this package runs on
  it. It is Firefox, so Chromium-only features (CDP sessions, Chromium launch
  flags) are skipped by their callers.
* ``ego`` — the user's own, already running ego-lite browser (a Chromium
  fork), reached over the Chrome DevTools Protocol with Playwright's
  ``connect_over_cdp``. The user turns this on once (ego keeps it in Local
  State, devtools.remote_debugging.user-enabled) at
  ``chrome://inspect/#remote-debugging`` ("Allow remote debugging for this
  browser instance"); ego then writes ``DevToolsActivePort`` in its user data
  directory. The same engine and adapters run on it, with the user's logins.
  The package only ever sees and closes the tabs it opened (and their popups),
  never closes the browser, and does not save or restore cookies there.

The former ``patchright`` and ``cloakbrowser`` values are accepted for old
configs, logged, and mapped to ``camoufox``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

# Compatibility exports: existing launchers and cold-start tooling use these names.
# Their implementation is owned solely by profiles.py.
from .profiles import (
    PROFILE_RELEASE_TIMEOUT_SEC,
    SESSION_COOKIES_FILE,
    SESSION_COOKIES_MAX_AGE_SEC,
    _lock_file_held,
    _pid_alive,
    _profile_owner_pid,
    _restore_session_cookies,
    _save_session_cookies,
    profile_holder,
    wait_for_profile_release,
)

logger = logging.getLogger(__name__)

BACKEND_CAMOUFOX = "camoufox"
BACKEND_EGO = "ego"
# The Camoufox browser build this release is tested with: the stable build
# paired with the pinned camoufox package (pyproject.toml; stable releases only,
# ADR 0013). It is launched by path, so another program changing the shared
# cache's active version does not change ours.
CAMOUFOX_BROWSER = "156.0.1-beta.36"
# The browser and version the last launch in this process used (browser_info).
_launched: dict[str, str] = {}
DEFAULT_BACKEND = BACKEND_CAMOUFOX
SUPPORTED_BACKENDS = (BACKEND_CAMOUFOX, BACKEND_EGO)
_RETIRED_BACKENDS = ("patchright", "cloakbrowser")

# A Firefox profile cannot share a directory with the Chromium profiles that
# earlier backends left behind, so Camoufox keeps its own sibling directory.
CAMOUFOX_PROFILE_SUFFIX = "-camoufox"


class EgoUnavailable(RuntimeError):
    """The running ego-lite browser cannot be reached over remote debugging."""


EGO_CONNECT_TIMEOUT_MS = 90_000  # the user may have to approve the connection in ego
EGO_START_TIMEOUT_SEC = 45.0


# ---------------------------------------------------------------------------
# Availability / resolution
# ---------------------------------------------------------------------------

def ego_user_data_dir(config: dict[str, Any] | None = None) -> Path:
    """ego-lite's user data directory (config ``ego_user_data_dir`` overrides)."""
    configured = str((config or {}).get("ego_user_data_dir") or "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Citro Labs" / "ego lite"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Citro Labs" / "ego lite" / "User Data"
    return Path.home() / ".config" / "Citro Labs" / "ego lite"


def find_ego_app(config: dict[str, Any] | None = None) -> Path | None:
    """The ego-lite application (config ``ego_app`` overrides)."""
    configured = str((config or {}).get("ego_app") or "").strip()
    candidates = [Path(configured).expanduser()] if configured else [
        Path.home() / "Applications" / "ego lite.app",
        Path("/Applications/ego lite.app"),
    ]
    return next((c for c in candidates if c.exists()), None)


def ego_app_version(config: dict[str, Any] | None = None) -> str:
    """ego lite's own version (its Info.plist); the user's browser, recorded, not pinned (ADR 0013)."""
    app = find_ego_app(config)
    if app is None:
        return ""
    import plistlib

    try:
        with open(app / "Contents" / "Info.plist", "rb") as handle:
            return str(plistlib.load(handle).get("CFBundleShortVersionString") or "")
    except (OSError, plistlib.InvalidFileException):
        return ""


def ego_running(config: dict[str, Any] | None = None) -> bool:
    """Whether ego holds its user data directory (Chromium's SingletonLock)."""
    pid = _profile_owner_pid(str(ego_user_data_dir(config)))
    return pid is not None and _pid_alive(pid)


def _start_ego(config: dict[str, Any] | None) -> bool:
    """Open the user's ego normally and wait for its remote-debugging port.

    Remote debugging is a saved ego setting, so a fresh start opens the port
    again and rewrites DevToolsActivePort. Returns True when it did.
    """
    import subprocess

    app = find_ego_app(config)
    if app is None:
        return False
    port_file = ego_user_data_dir(config) / "DevToolsActivePort"
    started = time.time()
    command = ["open", "-a", str(app)] if sys.platform == "darwin" else [str(app)]
    logger.info("browser_backend: ego-lite is not running; starting it")
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    while time.time() - started < EGO_START_TIMEOUT_SEC:
        time.sleep(1)
        try:
            if port_file.stat().st_mtime >= started - 1 and ego_endpoint(config):
                return True
        except OSError:
            continue
    return False


def ego_endpoint(config: dict[str, Any] | None = None) -> str | None:
    """WebSocket endpoint from ego's DevToolsActivePort, or None when remote debugging is off."""
    try:
        lines = (ego_user_data_dir(config) / "DevToolsActivePort").read_text().split()
    except OSError:
        return None
    if len(lines) < 2 or not lines[0].isdigit() or not lines[1].startswith("/devtools/"):
        return None
    return f"ws://127.0.0.1:{lines[0]}{lines[1]}"


def is_available(name: str | None = None) -> bool:
    """Whether a backend is installed. None → the default backend."""
    name = name or DEFAULT_BACKEND
    if name == BACKEND_CAMOUFOX:
        try:
            import camoufox  # noqa: F401
        except ImportError:
            return False
        return True
    if name == BACKEND_EGO:
        return ego_user_data_dir().exists()
    return False


def resolve_backend(config: dict[str, Any] | None = None) -> str:
    """Effective backend from config.

    Retired values (patchright, cloakbrowser) and unknown values map to
    camoufox with a warning. ``ego`` without an ego-lite installation falls
    back to camoufox with a warning; an installed ego whose remote debugging
    is off stays selected and the launch explains how to turn it on. A
    missing camoufox is not swapped for anything.
    """
    cfg = config or {}
    requested = str(cfg.get("browser_backend", DEFAULT_BACKEND) or DEFAULT_BACKEND).strip().lower()
    if requested in _RETIRED_BACKENDS:
        logger.warning(
            "browser_backend: '%s' is no longer supported, using %s (set browser_backend to "
            "'camoufox' or 'ego')", requested, DEFAULT_BACKEND,
        )
        return DEFAULT_BACKEND
    if requested not in SUPPORTED_BACKENDS:
        logger.warning("browser_backend: unknown backend '%s', using %s", requested, DEFAULT_BACKEND)
        return DEFAULT_BACKEND
    if requested == BACKEND_EGO and not ego_user_data_dir(cfg).exists():
        logger.warning("browser_backend: ego-lite is not installed, using %s", DEFAULT_BACKEND)
        return DEFAULT_BACKEND
    return requested


def uses_playwright(config: dict[str, Any] | None = None) -> bool:
    """Both backends are driven through the Playwright API."""
    return resolve_backend(config) in SUPPORTED_BACKENDS


# ---------------------------------------------------------------------------
# ego-lite: the user's running browser over remote debugging
# ---------------------------------------------------------------------------

_EGO_HINT = ("在 ego 中打开 chrome://inspect/#remote-debugging，勾选 "
             "\"Allow remote debugging for this browser instance\"（勾选一次即保存在 ego 设置中）")


def _connect_ego(config: dict[str, Any] | None) -> tuple[Any, Any]:
    """(playwright, browser) connected to the running ego-lite."""
    from playwright.sync_api import sync_playwright

    if not ego_running(config) and not _start_ego(config):
        raise EgoUnavailable(f"ego-lite is not running and could not be started with remote "
                             f"debugging. {_EGO_HINT}")
    upstream = ego_endpoint(config)
    if not upstream:
        raise EgoUnavailable(f"ego-lite remote debugging is off. {_EGO_HINT}")
    endpoint = _relay_endpoint(upstream)
    pw = sync_playwright().start()
    for attempt in (1, 2):
        try:
            browser = pw.chromium.connect_over_cdp(endpoint, timeout=EGO_CONNECT_TIMEOUT_MS)
            _launched.clear()
            _launched.update(backend=BACKEND_EGO, app=ego_app_version(config),
                             chromium=str(getattr(browser, "version", "") or ""))
            return pw, browser
        except Exception as exc:
            # ego keeps running with every window closed (macOS); without a
            # window no profile is loaded and Chromium answers "Browser context
            # management is not supported". Opening the app again opens a window.
            if attempt == 1 and "browser context management is not supported" in str(exc).lower() \
                    and _reopen_ego_window(config):
                continue
            pw.stop()
            raise EgoUnavailable(f"cannot reach ego-lite at its remote-debugging port "
                                 f"({type(exc).__name__}). Is ego running? {_EGO_HINT}") from exc
    raise AssertionError("unreachable")


def _reopen_ego_window(config: dict[str, Any] | None) -> bool:
    import subprocess

    app = find_ego_app(config)
    if app is None or sys.platform != "darwin":
        return False
    logger.info("browser_backend: ego has no open window; opening one")
    subprocess.run(["open", "-a", str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    time.sleep(4)
    return True


def _relay_state_file() -> Path:
    from ..config import DATA_DIR

    base = Path(os.environ.get("CARSI_DATA_DIR") or DATA_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base / "ego-relay.json"


def _relay_endpoint(upstream: str) -> str:
    """Local endpoint of the relay that holds the one connection to ego.

    ego asks the user to allow each new remote-debugging connection; every
    paper runs in a new backend process. A running relay for the same ego
    endpoint is reused; otherwise one is started (the user allows it once).
    """
    import subprocess

    state_file = _relay_state_file()

    def current() -> str | None:
        try:
            state = json.loads(state_file.read_text())
        except (OSError, ValueError):
            return None
        if state.get("upstream") != upstream or not _pid_alive(int(state.get("pid") or 0)):
            return None
        return f"ws://127.0.0.1:{int(state['port'])}/devtools/browser/relay"

    found = current()
    if found:
        return found
    try:
        import websockets  # noqa: F401
    except ImportError:
        logger.info("browser_backend: websockets not installed; connecting to ego directly")
        return upstream
    log_path = state_file.with_suffix(".log")
    log_start = log_path.stat().st_size if log_path.exists() else 0
    with open(log_path, "ab") as log:
        relay = subprocess.Popen([sys.executable, "-m", "paper_search_carsi.browser.ego_relay",
                                  "--upstream", upstream, "--state", str(state_file)],
                                 stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    logger.info("browser_backend: started the ego relay (allow its connection in ego once)")
    deadline = time.time() + EGO_CONNECT_TIMEOUT_MS / 1000
    while time.time() < deadline:
        time.sleep(0.5)
        found = current()
        if found:
            return found
        if relay.poll() is not None:
            # The relay gave up: ego refused it (HTTP 403 two seconds in, with
            # its window in the background, 2026-11-01). Waiting longer helps nothing.
            raise EgoUnavailable(f"ego refused the relay's connection ({_relay_failure(log_path, log_start)}). "
                                 f"Bring ego to the front and allow the connection when it asks. {_EGO_HINT}")
    raise EgoUnavailable(f"the ego relay could not connect (was the connection allowed in ego?). {_EGO_HINT}")


def _relay_failure(log_path: Path, start: int) -> str:
    """The last line the relay wrote before it stopped (its exception)."""
    try:
        with open(log_path, "rb") as log:
            log.seek(start)
            text = log.read().decode("utf-8", "replace")
    except OSError:
        return "no log"
    lines = [line for line in text.splitlines() if line.strip() and not line[:1].isspace()]
    return lines[-1][:200] if lines else "no log"


def _scope_to_own_tabs(context: Any) -> set:
    """Make ``context`` show only the tabs this package opened (and their popups).

    The user's own tabs live in the same browser context. Every place that
    walks ``context.pages`` (diagnostic screenshots, tab scans, previews) and
    every ``context.on("page")`` listener must ignore them, and ``page.context``
    returns this same object, so its class is swapped for a subclass whose
    ``pages`` and ``on("page")`` see only owned tabs.
    """
    owned: set = set()
    base = type(context)

    def track(page: Any) -> None:
        try:
            opener = page.opener()
        except Exception:
            opener = None
        if opener is not None and opener in owned:
            owned.add(page)

    base.on(context, "page", track)
    open_page = context.new_page

    def new_page(*a: Any, **kw: Any) -> Any:
        page = open_page(*a, **kw)
        owned.add(page)
        return page

    def on(self: Any, event: str, handler: Any) -> Any:
        if event != "page":
            return base.on(self, event, handler)

        def own_only(page: Any) -> None:
            track(page)
            if page in owned:
                handler(page)

        return base.on(self, event, own_only)

    scoped = type("EgoScopedContext", (base,), {
        "pages": property(lambda self: [p for p in base.pages.fget(self) if p in owned]),
        "on": on,
    })
    context.__class__ = scoped
    context.new_page = new_page  # type: ignore[method-assign]
    return owned


def _launch_ego_persistent(config: dict[str, Any] | None) -> Any:
    """The running ego's own context (the user's logins), scoped to our tabs."""
    pw, browser = _connect_ego(config)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    owned = _scope_to_own_tabs(context)

    def close(*_a: Any, **_kw: Any) -> None:
        for page in list(owned):
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass
        try:
            # Playwright took over downloads for this context; give them back.
            browser.new_browser_cdp_session().send("Browser.setDownloadBehavior", {"behavior": "default"})
        except Exception as exc:
            logger.info("browser_backend: ego download behaviour not reset (%s)", type(exc).__name__)
        pw.stop()  # disconnects; the user's browser keeps running

    context.close = close  # type: ignore[method-assign]
    logger.info("browser_backend: attached to the running ego-lite")
    return context


def _launch_ego(config: dict[str, Any] | None) -> Any:
    """A separate, empty context in the running ego (no user cookies or tabs)."""
    pw, browser = _connect_ego(config)
    contexts: list = []
    open_context = browser.new_context

    def new_context(*a: Any, **kw: Any) -> Any:
        context = open_context(*a, **kw)
        contexts.append(context)
        return context

    def close(*_a: Any, **_kw: Any) -> None:
        for context in contexts:
            try:
                context.close()
            except Exception:
                pass
        pw.stop()

    browser.new_context = new_context  # type: ignore[method-assign]
    browser.close = close  # type: ignore[method-assign]
    return browser


# ---------------------------------------------------------------------------
# Camoufox launchers
# ---------------------------------------------------------------------------

def _host_os() -> str:
    """Camoufox fingerprint OS matching the real machine (fonts, UA, platform agree)."""
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


def _proxy_from_config(config: dict[str, Any] | None) -> Any:
    """Playwright proxy dict from config, or None.

    Firefox ignores Chromium's --proxy-server launch arg, so the configured
    egress (browser_static_proxy, else network_proxy) is passed explicitly.
    """
    cfg = config or {}
    proxy = (str(cfg.get("browser_static_proxy", "") or "").strip()
             or str(cfg.get("network_proxy", "") or "").strip())
    return {"server": proxy} if proxy else None


def _camoufox_options(headless: bool, proxy: Any, args: list[str] | None, humanize: bool,
                      kwargs: dict[str, Any]) -> dict[str, Any]:
    if args:
        # Callers pass Chromium flags; handed to Firefox they would be read as
        # URLs to open. Camoufox configures its own anti-fingerprinting.
        logger.debug("browser_backend: camoufox ignores %d Chromium arg(s)", len(args))
    from camoufox import DefaultAddons

    opts = dict(kwargs)
    # The bundled uBlock addon is downloaded at build time and can fail or be
    # rate-limited; download sessions do not need it.
    opts.setdefault("exclude_addons", [DefaultAddons.UBO])
    opts.setdefault("os", _host_os())
    # No disk cache: a PDF cached by an earlier download is revalidated and
    # comes back as 304 Not Modified, without a body to capture (Springer,
    # 2026-10-31). The browser starts anew for every article, so its memory
    # cache never holds an earlier article's PDF.
    # Camoufox 156 with Fission loses cross-process Turnstile frames and sends
    # input to their parent container. Keep CARSI's owned automation browser
    # compatible with Juggler; explicit caller preferences still take priority.
    opts["firefox_user_prefs"] = {
        "browser.cache.disk.enable": False,
        "fission.autostart": False,
        # Keep this owned browser usable while the user works in another app.
        "focusmanager.testmode": True,
        "dom.disable_window_flip": True,
        "browser.tabs.loadDivertedInBackground": True,
        "browser.link.open_newwindow": 3,
        "browser.link.open_newwindow.restriction": 0,
        **(opts.get("firefox_user_prefs") or {}),
        "papersearch.background.enabled": not headless,
        "papersearch.background.bootstrap": False,
    }
    if not headless and opts.get("ignore_default_args") is not True:
        # Playwright adds -foreground to every headed Firefox launch.
        opts["ignore_default_args"] = list(dict.fromkeys([
            *(opts.get("ignore_default_args") or []), "-foreground",
        ]))
    if not headless:
        from .background import options as background_options
        background_options(opts)
    opts.update(headless=headless, humanize=humanize, proxy=proxy)
    pinned = pinned_camoufox_dir()
    if pinned is not None and "executable_path" not in opts:
        from camoufox.pkgman import launch_path

        try:
            opts["executable_path"] = launch_path(pinned)
        except Exception as exc:  # CamoufoxNotInstalled: a partial download
            logger.info("browser_backend: pinned Camoufox %s not usable (%s); the active build is used",
                        pinned.name, type(exc).__name__)
    _launched.clear()
    _launched.update(backend=BACKEND_CAMOUFOX, pinned="yes" if "executable_path" in opts else "no",
                     version=pinned.name if pinned is not None and "executable_path" in opts
                     else _active_camoufox_version())
    return opts


def pinned_camoufox_dir() -> Path | None:
    """The installed ``CAMOUFOX_BROWSER``: ``<cache>/browsers/official/<version>-<sha8>``."""
    try:
        from camoufox.pkgman import INSTALL_DIR
    except ImportError:
        return None
    found = sorted((Path(INSTALL_DIR) / "browsers" / "official").glob(f"{CAMOUFOX_BROWSER}-*"))
    return found[-1] if found else None


def _active_camoufox_version() -> str:
    """The shared cache's active build, used when the pinned one is not installed."""
    try:
        from camoufox.pkgman import Version

        return Version.from_path().full_string
    except Exception:
        return ""


def _close_with_driver(target: Any, pw: Any) -> Any:
    """Stop the Playwright driver when the browser/context closes."""
    original_close = target.close

    def _close_with_cleanup(*a: Any, **kw: Any) -> None:
        try:
            original_close(*a, **kw)
        finally:
            try:
                pw.stop()
            except Exception:
                pass

    target.close = _close_with_cleanup  # type: ignore[method-assign]
    return target


def _launch_camoufox(headless: bool, proxy: Any, args: list[str] | None, humanize: bool,
                     **kwargs: Any) -> Any:
    from camoufox import NewBrowser
    from playwright.sync_api import sync_playwright

    opts = _camoufox_options(headless, proxy, args, humanize, kwargs)
    pw = sync_playwright().start()
    try:
        browser = NewBrowser(pw, **opts)
    except Exception:
        pw.stop()
        raise
    return _close_with_driver(browser, pw)


def _launch_camoufox_persistent(user_data_dir: str, headless: bool, proxy: Any,
                                args: list[str] | None, humanize: bool, **kwargs: Any) -> Any:
    from camoufox import NewBrowser
    from playwright.sync_api import sync_playwright

    opts = _camoufox_options(headless, proxy, args, humanize, kwargs)
    if os.name == "nt" and not headless:
        # Let the owned helper create the first window without activation.
        from .background import ADDON_DIR, install_startup_helper
        install_startup_helper(Path(user_data_dir))
        opts["addons"] = [p for p in opts["addons"] if str(p) != str(ADDON_DIR)]
        opts["ignore_default_args"] = [*(opts.get("ignore_default_args") or []), "about:blank"]
        opts["args"] = [*(opts.get("args") or []), "-silent"]
        opts["firefox_user_prefs"].update({
            "papersearch.background.bootstrap": True,
            "xpinstall.signatures.required": False,
            "extensions.autoDisableScopes": 0,
            "extensions.enabledScopes": 1,
            "extensions.startupScanScopes": 1,
            # Gecko's first-profile video self-test opens an offscreen dialog
            # that still steals focus before any download window is created.
            "media.sanity-test.disabled": True,
        })
    pw = sync_playwright().start()
    try:
        context = NewBrowser(pw, persistent_context=True, user_data_dir=user_data_dir, **opts)
    except Exception:
        pw.stop()
        raise
    return _close_with_driver(context, pw)


def camoufox_profile_dir(user_data_dir: str | Path) -> Path:
    """Camoufox's own profile directory next to the given (Chromium-era) one."""
    path = Path(user_data_dir)
    if path.name.endswith(CAMOUFOX_PROFILE_SUFFIX):
        return path
    return path.with_name(path.name + CAMOUFOX_PROFILE_SUFFIX)


# ---------------------------------------------------------------------------
# Public entry points (Playwright sync API, Camoufox)
# ---------------------------------------------------------------------------

def launch(
    *,
    headless: bool = True,
    proxy: Any = None,
    args: list[str] | None = None,
    humanize: bool = True,
    config: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Launch Camoufox (or attach to ego); returns a ``playwright.sync_api.Browser``."""
    if resolve_backend(config) == BACKEND_EGO:
        return _launch_ego(config)
    if proxy is None:
        proxy = _proxy_from_config(config)
    return _launch_camoufox(headless=headless, proxy=proxy, args=args, humanize=humanize, **kwargs)


# The last Camoufox launch of this process, for the article's record: who held
# the profile, how long the launch waited for it, whether it was released.
LAST_LAUNCH: dict[str, Any] = {}


def launch_persistent_context(
    user_data_dir: str,
    *,
    headless: bool = True,
    proxy: Any = None,
    args: list[str] | None = None,
    humanize: bool = True,
    config: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Camoufox with a persistent profile, or the running ego; returns a ``BrowserContext``.

    Camoufox: the profile lives in a ``-camoufox`` sibling of ``user_data_dir``;
    waits (bounded) for a previous browser process to release it. ego: the
    user's running browser and its own profile (``user_data_dir`` unused).
    """
    LAST_LAUNCH.clear()
    if resolve_backend(config) == BACKEND_EGO:
        return _launch_ego_persistent(config)
    profile = camoufox_profile_dir(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)
    # Each item runs in a new process with the same profile: the previous item's
    # browser may still be closing; a launch then lost its pages a few seconds
    # later (OUP and Wiley items, TargetClosedError at the first page, 2026-11-02).
    holder = profile_holder(str(profile))
    waited_from = time.monotonic()
    released = wait_for_profile_release(str(profile))
    LAST_LAUNCH.update(holder=holder or "free", waited=round(time.monotonic() - waited_from, 1), released=released)
    if proxy is None:
        proxy = _proxy_from_config(config)
    from uuid import uuid4
    background_session = uuid4().hex
    if not headless:
        kwargs["firefox_user_prefs"] = {**(kwargs.get("firefox_user_prefs") or {}),
                                        "papersearch.background.session": background_session}
    context = _launch_camoufox_persistent(
        str(profile), headless=headless, proxy=proxy, args=args, humanize=humanize, **kwargs
    )
    if not callable(getattr(context, "close", None)):
        return context
    if not headless:
        from .background import ready as background_ready
        try:
            background_ready(profile, background_session)
        except Exception:
            context.close()
            raise
    restored = _restore_session_cookies(context, profile)
    if restored:
        logger.info("browser_backend: restored %d session cookie(s) from the previous run", restored)
    close = context.close

    def _close_keeping_session(*a: Any, **kw: Any) -> None:
        _save_session_cookies(context, profile)
        close(*a, **kw)

    context.close = _close_keeping_session  # type: ignore[method-assign]
    _reuse_startup_page(context)
    return context


def _reuse_startup_page(context: Any) -> None:
    """A persistent Firefox profile opens with one blank window; callers then
    ask for a page and got a second window. The first ``new_page()`` now
    returns that untouched startup page instead.

    Firefox on Windows cannot open a window once its last one is closed:
    ``new_page()`` then fails with "window is null" (2026-11-01, the
    supplements step after the main text had closed its page; macOS keeps a
    hidden window, so it never showed there). Closing the last open page
    therefore first opens a blank one, which the next ``new_page()`` returns;
    the same on every system."""
    spare = [page for page in list(getattr(context, "pages", None) or [])
             if str(getattr(page, "url", "")) in ("about:blank", "")]
    open_page = context.new_page
    kept: list[Any] = []

    def _keeping_a_window(page: Any) -> Any:
        if any(page is k for k in kept):
            return page
        kept.append(page)
        close = page.close

        def _close(*a: Any, **kw: Any) -> Any:
            last = not page.is_closed() and not any(
                other is not page and not other.is_closed() for other in list(context.pages))
            if last:
                try:
                    spare.append(_keeping_a_window(open_page()))
                except Exception as e:
                    logger.debug("browser_backend: no blank window kept before closing the last page: %s", e)
            return close(*a, **kw)

        page.close = _close
        return page

    def _new_page(*a: Any, **kw: Any) -> Any:
        while spare and not a and not kw:
            page = spare.pop(0)
            if not page.is_closed() and str(page.url) in ("about:blank", ""):
                return _keeping_a_window(page)
        return _keeping_a_window(open_page(*a, **kw))

    context.new_page = _new_page  # type: ignore[method-assign]


def browser_info(config: dict[str, Any] | None = None) -> dict[str, str]:
    """The browser and version of this process's last launch, else what a launch
    would use; kept with each download's record (ADR 0013).

    Camoufox: ``{"backend", "version", "pinned"}``; ego: ``{"backend", "app", "chromium"}``.
    """
    if _launched:
        return dict(_launched)
    if resolve_backend(config) == BACKEND_EGO:
        return {"backend": BACKEND_EGO, "app": ego_app_version(config), "chromium": ""}
    pinned = pinned_camoufox_dir()
    return {"backend": BACKEND_CAMOUFOX, "pinned": "yes" if pinned else "no",
            "version": pinned.name if pinned else _active_camoufox_version()}
