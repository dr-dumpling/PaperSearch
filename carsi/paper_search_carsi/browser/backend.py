"""Browser backends: Chrome (default) or ego-lite, both driven by Patchright.

Two backends are supported, selected by the ``browser_backend`` config key:

* ``chrome`` (default) — the user's installed, self-updating Google Chrome,
  launched with a profile of its own by Patchright
  (Playwright with Chromium's automation traces removed). Only Chrome's public
  switches: automated clicks do not activate its window, and the default
  switches keep a covered window rendering, so it needs no helper.
* ``ego`` — the user's own, already running ego-lite browser (a Chromium
  fork), reached over the Chrome DevTools Protocol with Patchright's
  ``connect_over_cdp``. The user turns this on once (ego keeps it in Local
  State, devtools.remote_debugging.user-enabled) at
  ``chrome://inspect/#remote-debugging`` ("Allow remote debugging for this
  browser instance"); ego then writes ``DevToolsActivePort`` in its user data
  directory. The same engine and adapters run on it, with the user's logins.
  The package only ever sees and closes the tabs it opened (and their popups),
  never closes the browser, and does not save or restore cookies there.

The retired values ``camoufox``, ``patchright`` and ``cloakbrowser`` are
accepted for old configs, logged once, and mapped to ``chrome``; the config
file is left as it is.
"""

from __future__ import annotations

import json
import logging
import os
import re
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

BACKEND_CHROME = "chrome"
BACKEND_EGO = "ego"
# The browser and version the last launch in this process used (browser_info).
_launched: dict[str, str] = {}
DEFAULT_BACKEND = BACKEND_CHROME
SUPPORTED_BACKENDS = (BACKEND_CHROME, BACKEND_EGO)
_RETIRED_BACKENDS = ("camoufox", "patchright", "cloakbrowser")
_retired_noted: set[str] = set()

# Chrome keeps its own profile, never the profile of the user's everyday Chrome.
CHROME_PROFILE_SUFFIX = "-chrome"
CHROME_DOWNLOAD_URL = "https://www.google.com/chrome/"
CHROME_MISSING = (f"Google Chrome was not found: install it from {CHROME_DOWNLOAD_URL} "
                  "(or set chrome_executable to the path of a Chrome installed elsewhere)")
# The Chrome version this release was tested with (acceptance); older ones are reported.
TESTED_CHROME = "156.0.8078.80"


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


def find_chrome(config: dict[str, Any] | None = None) -> Path | None:
    """The installed Google Chrome for the ``chrome`` backend.

    Config ``chrome_executable`` (the path of a Chrome installed elsewhere)
    overrides. Chrome is the user's stable, self-updating browser; the backend
    runs it with a profile of its own.
    """
    configured = str((config or {}).get("chrome_executable") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.exists() else None
    if sys.platform == "darwin":
        candidates = [Path(base) / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
                      for base in ("/Applications", str(Path.home() / "Applications"))]
    elif os.name == "nt":
        roots = [os.environ.get(key, "") for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        candidates = [Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe" for root in roots if root]
    else:
        candidates = [Path(found) for found in (shutil.which(name) for name in
                      ("google-chrome", "google-chrome-stable")) if found]
    return next((c for c in candidates if c.exists()), None)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:4])


def chrome_version(executable: str | Path | None) -> str:
    """The installed Chrome's version, read without starting it ("" when unknown).

    macOS: the app bundle's Info.plist. Windows: the version folder next to the
    program (``Application/156.0.8078.80``; the newest after an update). Linux:
    ``--version``.
    """
    if executable is None:
        return ""
    path = Path(executable)
    if sys.platform == "darwin":
        import plistlib

        bundle = next((p for p in path.parents if p.suffix == ".app"), None)
        try:
            with open((bundle or path) / "Contents" / "Info.plist", "rb") as handle:
                return str(plistlib.load(handle).get("CFBundleShortVersionString") or "")
        except (OSError, plistlib.InvalidFileException):
            return ""
    if sys.platform == "win32":
        try:
            folders = [p.name for p in path.parent.iterdir() if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+){3}", p.name)]
        except OSError:
            return ""
        return max(folders, key=_version_key, default="")
    import subprocess

    try:
        answer = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    found = re.search(r"\d+(?:\.\d+){1,3}", answer or "")
    return found.group(0) if found else ""


def patchright_version() -> str:
    """The installed Patchright, which drives both backends; "" when missing."""
    try:
        from importlib.metadata import version

        return version("patchright")
    except Exception:
        return ""


def browser_check(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """The Chrome the chrome backend would run, for health checks: where, its
    version against the version this release was tested with, and the driver.
    ``outdated``: older than the tested version."""
    found = find_chrome(config)
    driver = patchright_version()
    report: dict[str, Any] = {"browser": "", "path": "", "version": "", "tested": TESTED_CHROME,
                              "outdated": False, "driver": f"patchright {driver}" if driver else ""}
    if found is None:
        return report
    version = chrome_version(found)
    report.update(browser="Google Chrome", path=str(found), version=version,
                  outdated=bool(version) and _version_key(version) < _version_key(TESTED_CHROME))
    return report


def is_available(name: str | None = None, config: dict[str, Any] | None = None) -> bool:
    """Whether a backend is installed. None → the default backend."""
    name = name or DEFAULT_BACKEND
    if name == BACKEND_EGO:
        return ego_user_data_dir(config).exists() and bool(patchright_version())
    if name == BACKEND_CHROME:
        return find_chrome(config) is not None and bool(patchright_version())
    return False


def resolve_backend(config: dict[str, Any] | None = None) -> str:
    """Effective backend from config.

    Retired values (camoufox, patchright, cloakbrowser) map to chrome, logged
    once per process; unknown values map to chrome with a warning. ``ego``
    without an ego-lite installation falls back to chrome with a warning; an
    installed ego whose remote debugging is off stays selected and the launch
    explains how to turn it on. A missing Chrome is not swapped for anything:
    the launch says how to install it.
    """
    cfg = config or {}
    requested = str(cfg.get("browser_backend", DEFAULT_BACKEND) or DEFAULT_BACKEND).strip().lower()
    if requested in _RETIRED_BACKENDS:
        if requested not in _retired_noted:
            _retired_noted.add(requested)
            logger.warning("browser_backend: '%s' is retired, using %s (set browser_backend to 'chrome' or 'ego')",
                           requested, DEFAULT_BACKEND)
        return DEFAULT_BACKEND
    if requested not in SUPPORTED_BACKENDS:
        logger.warning("browser_backend: unknown backend '%s', using %s", requested, DEFAULT_BACKEND)
        return DEFAULT_BACKEND
    if requested == BACKEND_EGO and not ego_user_data_dir(cfg).exists():
        logger.warning("browser_backend: ego-lite is not installed, using %s", DEFAULT_BACKEND)
        return DEFAULT_BACKEND
    return requested

# What a backend offers beyond plain Playwright. Callers ask for a capability,
# never for a backend's name, so a new backend only declares its own entry.
#   batch_window: a serial batch keeps one browser window and tab from paper
#     to paper (browser/batch_session.py); without it every paper opens and
#     closes its own browser, as before.
BACKEND_CAPABILITIES: dict[str, frozenset[str]] = {
    BACKEND_CHROME: frozenset({"batch_window"}),
    # The user's own running browser: one tab per paper until a batch there
    # has been tried.
    BACKEND_EGO: frozenset(),
}


def supports(capability: str, config: dict[str, Any] | None = None) -> bool:
    """Whether the effective backend declares ``capability``."""
    return capability in BACKEND_CAPABILITIES.get(resolve_backend(config), frozenset())


def uses_playwright(config: dict[str, Any] | None = None) -> bool:
    """Every backend is driven through the Playwright API (Patchright's)."""
    return resolve_backend(config) in SUPPORTED_BACKENDS


# ---------------------------------------------------------------------------
# ego-lite: the user's running browser over remote debugging
# ---------------------------------------------------------------------------

_EGO_HINT = ("在 ego 中打开 chrome://inspect/#remote-debugging，勾选 "
             "\"Allow remote debugging for this browser instance\"（勾选一次即保存在 ego 设置中）")


def _connect_ego(config: dict[str, Any] | None) -> tuple[Any, Any]:
    """(driver, browser) connected to the running ego-lite."""
    from patchright.sync_api import sync_playwright

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
            # The driver took over downloads for this context; give them back.
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
# Chrome launchers
# ---------------------------------------------------------------------------

def _proxy_from_config(config: dict[str, Any] | None) -> Any:
    """The driver's proxy dict from config, or None: the configured egress
    (browser_static_proxy, else network_proxy)."""
    cfg = config or {}
    proxy = (str(cfg.get("browser_static_proxy", "") or "").strip()
             or str(cfg.get("network_proxy", "") or "").strip())
    return {"server": proxy} if proxy else None


def _close_with_driver(target: Any, pw: Any) -> Any:
    """Stop the driver when the browser/context closes."""
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


def chrome_profile_dir(user_data_dir: str | Path) -> Path:
    """Chrome's own profile directory next to the given one."""
    path = Path(user_data_dir)
    if path.name.endswith(CHROME_PROFILE_SUFFIX):
        return path
    return path.with_name(path.name + CHROME_PROFILE_SUFFIX)


def _chrome_options(headless: bool, proxy: Any, args: list[str] | None,
                    config: dict[str, Any] | None) -> dict[str, Any]:
    """Launch options for the installed Chrome: its public switches only.

    The driver's defaults already include --disable-backgrounding-occluded-windows,
    --disable-renderer-backgrounding and --disable-background-timer-throttling,
    so a covered window keeps rendering, and CDP input does not activate it.
    Patchright itself adds --disable-blink-features=AutomationControlled and
    drops --enable-automation.
    """
    executable = find_chrome(config)
    if executable is None:
        raise RuntimeError(f"browser_backend chrome: {CHROME_MISSING}")
    switches = [arg for arg in (args or []) if not (proxy and arg.startswith("--proxy-server="))]
    # Patchright's --disable-blink-features=AutomationControlled is on Chrome's
    # list of unsupported flags, shown on a warning bar; Chrome's own
    # --test-type switch skips that prompt.
    switches = list(dict.fromkeys([*switches, "--test-type"]))
    opts: dict[str, Any] = {"executable_path": str(executable), "headless": headless, "args": switches,
                            # Without it the driver adds --no-sandbox, and Chrome shows a warning bar.
                            "chromium_sandbox": True}
    if proxy:
        opts["proxy"] = proxy
    if not headless:
        opts["no_viewport"] = True  # the window's own size, as the user sees it
    return opts


def _note_chrome_launch(version: str, executable: str) -> None:
    _launched.clear()
    _launched.update(backend=BACKEND_CHROME, app=Path(executable).stem, version=str(version or ""),
                     driver=f"patchright {patchright_version()}")


def _launch_chrome(headless: bool, proxy: Any, args: list[str] | None, config: dict[str, Any] | None) -> Any:
    from patchright.sync_api import sync_playwright

    opts = _chrome_options(headless, proxy, args, config)
    opts.pop("no_viewport", None)  # a context option, not a launch option
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(**opts)
    except Exception:
        pw.stop()
        raise
    _note_chrome_launch(browser.version, opts["executable_path"])
    return _close_with_driver(browser, pw)


def _launch_chrome_persistent(profile: Path, headless: bool, proxy: Any, args: list[str] | None,
                              config: dict[str, Any] | None) -> Any:
    from patchright.sync_api import sync_playwright

    opts = _chrome_options(headless, proxy, args, config)
    pw = sync_playwright().start()
    try:
        context = pw.chromium.launch_persistent_context(str(profile), **opts)
    except Exception:
        pw.stop()
        raise
    _note_chrome_launch(getattr(context.browser, "version", ""), opts["executable_path"])
    return _close_with_driver(context, pw)


def _chrome_persistent(user_data_dir: str, *, headless: bool, proxy: Any, args: list[str] | None,
                       config: dict[str, Any] | None) -> Any:
    profile = chrome_profile_dir(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)
    holder = profile_holder(str(profile))
    waited_from = time.monotonic()
    released = wait_for_profile_release(str(profile))
    LAST_LAUNCH.update(holder=holder or "free", waited=round(time.monotonic() - waited_from, 1), released=released)
    if proxy is None:
        proxy = _proxy_from_config(config)
    context = _launch_chrome_persistent(profile, headless, proxy, args, config)
    _keep_session_cookies(context, profile)
    if not headless:
        _open_tabs_in_background(context)
    _reuse_startup_page(context)
    return context


def _open_tabs_in_background(context: Any) -> None:
    """New tabs leave Chrome where the user put it.

    The driver opens a page with Target.createTarget, which Chrome shows in the
    foreground, bringing its window to the front: 3 of 3 times on macOS
    (2026-11-07), once per supplements page and file. The same public command
    with ``background`` left the user's front app in front 3 of 3 times, and
    clicks in the new tab still worked.
    """
    session = context.browser.new_browser_cdp_session()
    open_page = context.new_page

    def new_page(*args: Any, **kwargs: Any) -> Any:
        if args or kwargs:
            return open_page(*args, **kwargs)
        with context.expect_page() as created:
            session.send("Target.createTarget", {"url": "about:blank", "background": True})
        return created.value

    context.new_page = new_page  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Public entry points (Playwright sync API, through Patchright)
# ---------------------------------------------------------------------------

def launch(
    *,
    headless: bool = True,
    proxy: Any = None,
    args: list[str] | None = None,
    humanize: bool = True,
    config: dict[str, Any] | None = None,
) -> Any:
    """Launch Chrome (or attach to ego); returns a ``Browser``. ``humanize`` is kept for callers."""
    if resolve_backend(config) == BACKEND_EGO:
        return _launch_ego(config)
    if proxy is None:
        proxy = _proxy_from_config(config)
    return _launch_chrome(headless, proxy, args, config)


# The last launch of this process, for the article's record: who held the
# profile, how long the launch waited for it, whether it was released.
LAST_LAUNCH: dict[str, Any] = {}


def launch_persistent_context(
    user_data_dir: str,
    *,
    headless: bool = True,
    proxy: Any = None,
    args: list[str] | None = None,
    humanize: bool = True,
    config: dict[str, Any] | None = None,
) -> Any:
    """Chrome with a persistent profile, or the running ego; returns a ``BrowserContext``.

    Chrome: the profile lives in a ``-chrome`` sibling of ``user_data_dir``;
    waits (bounded) for a previous browser process to release it. ego: the
    user's running browser and its own profile (``user_data_dir`` unused).
    ``humanize`` is kept for callers.
    """
    LAST_LAUNCH.clear()
    if resolve_backend(config) == BACKEND_EGO:
        return _launch_ego_persistent(config)
    return _chrome_persistent(user_data_dir, headless=headless, proxy=proxy, args=args, config=config)


def _keep_session_cookies(context: Any, profile: Path) -> None:
    """Session cookies (a school login) survive a browser that closes between runs."""
    restored = _restore_session_cookies(context, profile)
    if restored:
        logger.info("browser_backend: restored %d session cookie(s) from the previous run", restored)
    close = context.close

    def _close_keeping_session(*a: Any, **kw: Any) -> None:
        _save_session_cookies(context, profile)
        close(*a, **kw)

    context.close = _close_keeping_session  # type: ignore[method-assign]


def _reuse_startup_page(context: Any) -> None:
    """A persistent profile opens with one blank window; callers then ask for a
    page and got a second window. The first ``new_page()`` now returns that
    untouched startup page instead.

    Closing the last open page first opens a blank one, which the next
    ``new_page()`` returns, so the browser keeps its window between steps (the
    earlier Firefox-based browser could not open one on Windows once its last
    had closed: "window is null", 2026-11-01)."""
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

    Chrome: ``{"backend", "app", "version", "driver"}`` (the user's browser,
    recorded, not pinned); ego: ``{"backend", "app", "chromium"}``.
    """
    if _launched:
        return dict(_launched)
    if resolve_backend(config) == BACKEND_EGO:
        return {"backend": BACKEND_EGO, "app": ego_app_version(config), "chromium": ""}
    found = find_chrome(config)
    return {"backend": BACKEND_CHROME, "app": found.stem if found else "", "version": chrome_version(found),
            "driver": f"patchright {patchright_version()}"}
