"""The download progress capsule: a small always-on-top floating pill.

Collapsed it shows how far the task is ("12/40  正文 · Wiley"). Hovering opens
a card with the paper, the counts and every action (skip, no access, stop,
problem report, settings, output folder). A step that needs the user (school
login, verification) turns amber with a breathing glow and raises one system
notification. Clicking the reminder activates the task's browser. The page is
HTML (``assets/capsule.html``) drawn by pywebview with the system web engine:
WebKit on macOS, WebView2 on Windows. It is the only progress window: without
pywebview or a usable engine there is none, and the download goes on.

Usage: ``paper-search-school progress`` (or ``python -m paper_search_school.progress_capsule``).
Spawned automatically by ``progress_reporter.ensure_progress_bar`` when a download starts.
``paper-search-school settings`` opens it at the settings (download folder,
waits and reminders, API keys), also with no download running.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import api_keys, download_directory, i18n, progress_view, user_settings
from .edition import pro_features
from .capsule_placement import Placement, Rect
from .capsule_window import (_MacDrag, _cocoa_call, _enable_inactive_hover, _mac_button_held, _mac_pointer,
                             _prepare_nonactivating_start, _round_windows_corners, _screen_areas, _set_window_frame,
                             _window_geometry, _window_scale, _windows_button_held, _windows_pointer,
                             _windows_taskbar_icon)
from .progress_reporter import papers_path, progress_path, read_papers, read_state, take_settings_request

ASSETS = Path(__file__).with_name("assets")
PAGE = ASSETS / "capsule.html"


#: Where each language's table goes in the page.
_TABLE_MARKS = {"en": "CAPSULE_EN", "zh-Hant": "CAPSULE_ZH_HANT", "ja": "CAPSULE_JA", "ko": "CAPSULE_KO", "fr": "CAPSULE_FR"}


def page_html() -> str:
    """The page with its tables in it, one per language (the window loads it as one string)."""
    page = PAGE.read_text(encoding="utf-8")
    for code, mark in _TABLE_MARKS.items():
        page = page.replace(f"/*{mark}*/null", i18n.TABLES[code].read_text(encoding="utf-8"))
    return page
# PaperSearch's icon (assets/icon.svg) for the Dock.
ICON = ASSETS / "icon-512.png"
# The first, collapsed frame; the page then reports the size it needs.
START_SIZE = (260, 56)
MIN_SIZE = (60, 30)


def _corner() -> str:
    return "top" if sys.platform == "darwin" else "bottom"


# Windows toasts go out under PowerShell's registered app id: Settings names them "Windows PowerShell".
_TOAST_MANAGER = ("[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
                  "$n=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                  "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe');")


def _powershell(script: str, **env: str) -> str:
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          env={**os.environ, **env}, capture_output=True, text=True, timeout=10, check=True,
                          creationflags=0x08000000)
    return done.stdout.strip()


def _windows_toast(title: str, body: str) -> None:
    # The texts go in by environment so no quoting is needed.
    _powershell(_TOAST_MANAGER
                + "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                  "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  "$t=$x.GetElementsByTagName('text');"
                  "$t.Item(0).AppendChild($x.CreateTextNode($env:PSC_TITLE))>$null;"
                  "$t.Item(1).AppendChild($x.CreateTextNode($env:PSC_BODY))>$null;"
                  "$n.Show([Windows.UI.Notifications.ToastNotification]::new($x))",
                PSC_TITLE=title, PSC_BODY=body)


def notify(title: str, body: str, state: dict[str, Any] | None = None) -> None:
    """One system notification, bound to the current task on macOS."""
    if not user_settings.notify_enabled():
        return
    try:
        if sys.platform == "darwin":
            from .progress_macos import notify as native_notify

            native_notify(title, body, state or {})
        elif os.name == "nt":
            _windows_toast(title, body)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("progress notification failed: %s", type(exc).__name__)


def notifications_allowed() -> str:
    """Whether the system lets PaperSearch's notifications show: "ok", "off" or "unknown"."""
    if sys.platform == "darwin":
        from .progress_macos import notifications_allowed as mac_allowed

        return mac_allowed()
    if os.name == "nt":
        # Enabled, or DisabledForUser / DisabledForApplication / DisabledByGroupPolicy / DisabledByManifest.
        setting = _powershell(_TOAST_MANAGER + "$n.Setting")
        return "ok" if setting == "Enabled" else "off" if setting.startswith("Disabled") else "unknown"
    return "unknown"


TEST_NOTIFICATION = "测试通知：需要你登录或验证时，会这样提醒你"


class Notifier:
    """A system notification when a step starts to need the user, once per prompt."""

    def __init__(self, send=notify) -> None:
        self._send = send
        self._seen: set[str] = set()
        self._task: tuple[str, str] = ("", "")

    def observe(self, state: dict[str, Any] | None) -> None:
        if not user_settings.notify_enabled():
            self._seen.clear()
            if sys.platform == "darwin":
                from .progress_macos import close

                close()
            return
        task = (str((state or {}).get("run_id") or ""), str((state or {}).get("current") or ""))
        attention = state.get("attention") if state and state.get("status") == "running" else None
        prompts = {f"{key}@{value.get('since', '')}": value for key, value in attention.items()
                   if isinstance(value, dict)} if isinstance(attention, dict) else {}
        new = [prompts[key] for key in prompts if task != self._task or key not in self._seen]
        if self._seen and (not prompts or task != self._task) and sys.platform == "darwin":
            from .progress_macos import clear_notifications

            clear_notifications()
        self._seen = set(prompts)
        self._task = task
        if not new:
            return
        message = str(new[-1].get("message") or "需要你在浏览器里处理")
        message = i18n.translate(message, user_settings.language())
        threading.Thread(target=self._send, args=("PaperSearch", message, state), daemon=True).start()


#: How many schools 添加学校 lists at most (a country's name finds all of its).
FOUND_SHOWN = 50


class Api:
    """What the page calls (``window.pywebview.api``). Every method returns
    plain values and never raises into the page."""

    def __init__(self, placement: Placement, notifier: Notifier, auto_close: progress_view.AutoClose) -> None:
        self._window: Any = None
        self._placement = placement
        self._notifier = notifier
        self._auto_close = auto_close
        self._geometry_lock = threading.RLock()
        self._dragging = False
        self._native_geometry = False
        self._drag_origin: tuple[float, float, float, float] | None = None
        self._drag_pointer: tuple[float, float] | None = None
        self._mac_drag: _MacDrag | None = None  # macOS: presses tracked natively (main)
        self._native_drag = False  # this drag follows the mouse natively, not the page
        # papers.json: when read, its batch, the sites not yet supported its pages came from.
        self._papers_seen: tuple[int, str] = (0, "")
        self._hovering = False
        self._layout: tuple[int, bool, Rect, Rect] | None = None
        self._closed = False
        self._close_requested: float | None = None
        try:
            self._lang = user_settings.language()
        except Exception:
            self._lang = "zh"

    # --- what to show -----------------------------------------------------
    def platform(self) -> str:
        return sys.platform

    def state(self, hovering: bool = False) -> dict[str, Any]:
        """The capsule's view of the progress file; ``hovering`` keeps a finished window open."""
        self._hovering = bool(hovering) or self._dragging
        try:
            snapshot = read_state()
            shown = progress_view.view(snapshot, time.time())
            # 成功, 失败 and 剩余 open their lists once the caller has sent this batch's papers.
            if snapshot and snapshot.get("batch_id") and self._papers_batch() == snapshot["batch_id"]:
                shown["lists"] = True
        except Exception:
            shown = {"mode": "idle"}
        if shown.get("mode") in ("running", "attention"):
            shown["holds"] = self._holds()
        shown["lang"] = self._lang
        request = take_settings_request()  # `paper-search-school settings`: show the settings
        return {**shown, "open_settings": request} if request else shown

    # Read again at most this often: the settings change by hand, the page asks every second.
    _HOLDS_EVERY_SEC = 5.0

    def _holds(self) -> bool:
        """Whether a batch may hold papers for a later try, and the card shows 重试 (user, 2026-11-24): 失败后自动重试 on
        (原因不明 at the end, a blocking site after its pause), or 没权限时换下一所学校 on with another saved school. Each
        switch its own; both off, none waits and the card has no 重试, its papers failed at once."""
        cached = getattr(self, "_holds_cache", None)
        if cached and time.time() - cached[0] < self._HOLDS_EVERY_SEC:
            return cached[1]
        try:
            from . import config as _config, school_switch
            loaded = _config.load_config()
            holds = (user_settings.retry_enabled()
                     or (school_switch.enabled(loaded) and len(school_switch.schools(loaded)) > 1))
        except Exception:
            holds = True  # not known: as before, 重试 shown
        self._holds_cache = (time.time(), bool(holds))
        return bool(holds)

    # --- watching the task, also while the capsule is minimized ------------
    def watch(self) -> None:
        """Notifications and closing, off the page: the system slows a minimized
        page's timers down."""
        while not self._closed:
            try:
                snapshot = read_state()
            except Exception:
                snapshot = None
            self.watch_once(snapshot, time.monotonic())
            time.sleep(0.5)

    def watch_once(self, snapshot: dict[str, Any] | None, now: float) -> None:
        if self._close_requested is not None and now >= self._close_requested:
            self.close()
            return
        self._notifier.observe(snapshot)
        if self._auto_close.should_close(snapshot, now, hovering=self._hovering):
            self.close()

    def minimize(self) -> None:
        """Into the Dock / taskbar like a browser window; clicking it there brings it back."""
        try:
            self._window.minimize()
        except Exception:
            pass

    # --- the buttons ------------------------------------------------------
    def activate_on_input(self) -> None:
        """The first real click restores normal Windows focus and keyboard input."""
        activate = getattr(self._window, "_capsule_activate_on_input", None)
        if callable(activate):
            activate()

    def act(self, action: str, current: str, run_id: str = "") -> str:
        """Control the running download, including showing its browser on request."""
        try:
            from .entitlements import RESUME_HELD, SHOW_BROWSER, request_action, request_resume

            if action == RESUME_HELD:
                # The user is back: every publisher the batch holds goes on.
                state = read_state() or {}
                held = [str(entry["key"]) for entry in state.get("held") or [] if isinstance(entry, dict) and entry.get("key")]
                if state.get("status") != "running" or str(state.get("run_id") or "") != run_id or not held:
                    return "这批下载已没有暂停的篇目"
                for key in held:
                    request_resume(key, str(state.get("batch_id") or ""))
                return progress_view.ACTION_FEEDBACK[RESUME_HELD]
            if action == SHOW_BROWSER:
                # Asked for from a reminder, or from the paper on the card at any
                # time while it has a browser (user request, 2026-11-08).
                state = read_state() or {}
                if (state.get("status") != "running"
                        or str(state.get("current") or "") != current
                        or str(state.get("run_id") or "") != run_id):
                    return "当前没有正在下载的浏览器"
                if not state.get("attention") and state.get("channel"):
                    return "这一篇在查开放来源，没有打开浏览器"
                if sys.platform == "darwin":
                    from .browser.foreground import activate_mac

                    pid = state.get("browser_pid")
                    if not isinstance(pid, int) or pid <= 0 or not activate_mac(pid):
                        return "未能切到下载浏览器，请从程序坞打开"
                if os.name == "nt":
                    # The window raises the browser itself, as on macOS, whatever the paper
                    # is fetching and between papers: a request left for the article's watch
                    # was lost once the watch had ended (Windows, 2026-11-16).
                    pids = [p for p in state.get("browser_pids") or [] if isinstance(p, int) and p > 0]
                    if pids:
                        from .browser.foreground import activate_windows

                        if not activate_windows(pids):
                            return "未能切到下载浏览器，请从任务栏打开"
                    if isinstance(state.get("owner_pid"), int) and state["owner_pid"] > 0:
                        # The click gives this foreground window permission to let
                        # the exact backend process activate its browser on Windows.
                        import ctypes

                        ctypes.windll.user32.AllowSetForegroundWindow(state["owner_pid"])
                if state.get("awaiting_next"):
                    # Between papers no article watches for requests: raised above, nothing to leave.
                    return "已切到下载浏览器"

            request_action(str(current), str(action), str(run_id))
            return progress_view.ACTION_FEEDBACK[str(action)]
        except Exception as exc:
            return f"记录失败：{type(exc).__name__}"

    def issue_kinds(self) -> list[list[str]]:
        from .issues import ISSUE_KINDS

        return [[kind, label] for kind, label in ISSUE_KINDS.items()]

    def report(self, kind: str, current: str) -> str:
        """The problem the user saw in the browser; the running download acts on it at once."""
        try:
            from .issues import ISSUE_KINDS, report

            report(str(current), str(kind), read_state() or {})
            return f"已收到：{ISSUE_KINDS[kind]}，正在处理"
        except Exception as exc:
            return f"记录失败：{type(exc).__name__}"

    def open_article(self, doi: str) -> str:
        """The article's page (doi.org) in the user's own browser, to fetch what the
        batch could not; only a DOI is opened, never another address."""
        doi = str(doi or "").strip()
        if not progress_view.DOI.fullmatch(doi):
            return "打开失败：不是有效的 DOI"
        import webbrowser
        from urllib.parse import quote

        try:
            opened = webbrowser.open("https://doi.org/" + quote(doi, safe="/:;()._-"))
        except Exception as exc:
            return f"打开失败：{type(exc).__name__}"
        return "已在浏览器打开这篇文章" if opened else "打开失败：没有找到默认浏览器"

    def open_folder(self) -> bool:
        return progress_view.open_folder(progress_view.batch_folder(read_papers(), read_state()))

    # --- the lists behind 成功, 失败 and 剩余 ---------------------------------
    def _papers_batch(self) -> str:
        """The batch of the papers file, read again only when the file changed."""
        try:
            changed = papers_path().stat().st_mtime_ns
        except OSError:
            return ""
        if changed != self._papers_seen[0]:
            listed = read_papers() or {}
            batch = str(listed.get("batch_id") or "")
            self._papers_seen = (changed, batch)
        return self._papers_seen[1]

    def paper_lists(self) -> dict[str, Any]:
        return progress_view.paper_lists(read_papers(), read_state(), self._holds())

    # --- pages from sites not yet supported (user, 2026-11-16) -------------
    def _batch_papers(self) -> list[dict[str, Any]]:
        listed, state = read_papers() or {}, read_state() or {}
        if not listed.get("batch_id") or listed.get("batch_id") != state.get("batch_id"):
            return []
        return [p for p in (listed.get("papers") or {}).values() if isinstance(p, dict)]

    def markdown_issue(self) -> str:
        """提 issue (user, 2026-11-17: one button for both kinds of site): the report on this
        batch's pages from sites not yet supported, saved or not, as a ZIP in the batch's
        folder shown selected there, then GitHub's new issue page filled in with the sites,
        whose rules, the version and the counts (no DOI or title), in the user's browser; they
        drag the ZIP in and submit. Nothing is uploaded."""
        import webbrowser

        from .config import load_config
        from .markdown_report import ReportError, export, issue_url, paper_search_version, site_counts

        papers = self._batch_papers()
        sites = site_counts(papers)
        if not sites:
            return "这批没有暂未正式支持的网站"
        version = paper_search_version()
        entries = [{"report": p["markdown_report"], "doi": p.get("doi"), "title": p.get("title")}
                   for p in papers if p.get("markdown_report")]
        folder = progress_view.batch_folder(read_papers(), read_state())
        exported = ""
        try:
            if entries and folder:
                result = export(entries, Path(folder), load_config(), version)
                progress_view.reveal_file(result["path"])
                exported = result["name"]
        except ReportError:
            exported = ""
        except Exception as exc:
            return f"导出报告失败：{type(exc).__name__}"
        try:
            opened = webbrowser.open(issue_url(sites, version))
        except Exception as exc:
            return f"打开 issue 页面失败：{type(exc).__name__}"
        if not opened:
            return "打开 issue 页面失败：没有找到默认浏览器" + (f"；报告已导出：{exported}" if exported else "")
        return f"已导出报告 {exported} 并打开 issue 页面，把它拖进去" if exported else "已打开 issue 页面（这批没有留下可导出的网页）"

    def open_markdown_support(self) -> str:
        """已支持的网站: the list of sites with Markdown rules, in the user's browser."""
        import webbrowser

        from .markdown_report import paper_search_version, support_doc

        try:
            opened = webbrowser.open(support_doc(paper_search_version()))
        except Exception as exc:
            return f"打开失败：{type(exc).__name__}"
        return "已在浏览器打开" if opened else "打开失败：没有找到默认浏览器"

    def show_paper(self, index: int) -> str:
        """A saved paper of the running or finished batch, shown in its folder: the file the batch
        recorded for it (its PDF, else what it saved of it: a batch of the supplementary files or the
        Markdown alone has no PDF, 2026-11-16), wherever the paper was sent (folders of their own by
        topic, user 2026-11-11). The file is only selected in its folder, never opened."""
        listed, state = read_papers() or {}, read_state() or {}
        key = str(index) if isinstance(index, int) and not isinstance(index, bool) else ""
        paper = (listed.get("papers") or {}).get(key) if listed.get("batch_id") == state.get("batch_id") else None
        path = str((paper or {}).get("path") or "") if (paper or {}).get("state") == "ok" else ""
        real = os.path.realpath(path) if path else ""
        if not real:
            return "打开失败：这篇没有保存的文件"
        if not progress_view.reveal_file(real):
            return "打开失败：文件已被移走或删除"
        return "已打开所在文件夹"

    # --- settings ---------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        values = user_settings.current()
        return {
            "fields": [{"name": f.name, "label": f.label, "unit": f.unit, "value": values[f.name],
                        "default": f.default, "page": f.page} for f in user_settings.FIELDS],
            "notify": user_settings.notify_enabled(),
            "hourly_now": user_settings.hourly_now(),
            "retry": user_settings.retry_enabled(),
            "download_dir": download_directory.current(),
            "language": self._lang,
            # Whether the settings have the Markdown page (PaperSearch Pro's, edition.py).
            "pro": pro_features(),
        }

    def set_language(self, lang: str) -> dict[str, Any]:
        """The language switch saves at once and the page follows it."""
        if lang not in i18n.LANGUAGES:
            return {"ok": False, "error": "不支持这种语言"}
        try:
            user_settings.set_language(lang)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        self._lang = lang
        return {"ok": True, "language": lang}

    def set_notifications(self, enabled: bool) -> dict[str, Any]:
        """The notification switch saves immediately, independently of other fields."""
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "通知开关必须为开启或关闭"}
        try:
            user_settings.set_notify(enabled)
            self._notifier.observe(read_state())
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return {"ok": True, "notify": enabled}

    def set_hourly_now(self, enabled: bool) -> dict[str, Any]:
        """The switch beside the hourly limit (马上生效) saves immediately, like the notification switch."""
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "开关必须为开启或关闭"}
        try:
            user_settings.set_hourly_now(enabled)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return {"ok": True, "hourly_now": enabled}

    def set_retry(self, enabled: bool) -> dict[str, Any]:
        """失败后自动重试 saves immediately, like the notification switch (the next batch reads it)."""
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "开关必须为开启或关闭"}
        try:
            user_settings.set_retry(enabled)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return {"ok": True, "retry": enabled}

    # The settings' check of system notifications (user, 2026-11-10): a switch turned on,
    # or a test notification, says when the system keeps them from showing.
    def check_notifications(self) -> dict[str, str]:
        """"ok", "off" (the system keeps PaperSearch's notifications from showing) or "unknown"."""
        try:
            return {"state": notifications_allowed()}
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("notification check failed: %s", type(exc).__name__)
            return {"state": "unknown"}

    def test_notification(self) -> dict[str, str]:
        """A test notification, unless the system keeps it from showing: "sent", "off" or "failed"."""
        if self.check_notifications()["state"] == "off":
            return {"state": "off"}
        title = "PaperSearch"
        body = i18n.translate(TEST_NOTIFICATION, user_settings.language())
        try:
            if sys.platform == "darwin":
                from .progress_macos import send_test

                send_test(title, body)
            elif os.name == "nt":
                _windows_toast(title, body)
            else:
                return {"state": "failed", "message": "测试通知没有发出：这台电脑不发系统通知"}
        except Exception as exc:
            return {"state": "failed", "message": f"测试通知没有发出：{type(exc).__name__}"}
        return {"state": "sent"}

    def open_notification_settings(self) -> bool:
        try:
            if sys.platform == "darwin":
                from .progress_macos import open_settings

                open_settings()
            elif os.name == "nt":
                os.startfile("ms-settings:notifications")  # type: ignore[attr-defined]
            else:
                return False
        except Exception:
            return False
        return True

    def save_settings(self, values: dict[str, Any], download_dir: str | None = None) -> dict[str, Any]:
        """Check the fields of one settings page, then save them all; nothing is
        saved when one is wrong. The notification switch saves on its own."""
        checked, errors = {}, {}
        for field in user_settings.FIELDS:
            if field.name not in (values or {}):
                continue
            value, problem = user_settings.check(field, str(values[field.name]))
            if problem:
                errors[field.name] = problem
            else:
                checked[field.name] = value
        if download_dir is not None:
            try:
                download_dir = download_directory.validate(download_dir)
            except ValueError as exc:
                errors["download_dir"] = str(exc)
        if errors:
            return {"ok": False, "errors": errors}
        try:
            if download_dir is not None:
                download_directory.save(download_dir)
            user_settings.save(checked)
        except Exception as exc:
            return {"ok": False, "errors": {"": f"保存失败：{type(exc).__name__}"}}
        return {"ok": True}

    # --- API keys: values go to the config, never back to the page ---------
    def api_keys(self) -> dict[str, Any]:
        try:
            return {"ok": True, **api_keys.listing()}
        except Exception as exc:
            return {"ok": False, "error": f"读取配置失败：{type(exc).__name__}"}

    def api_key_values(self, service: str) -> dict[str, Any]:
        """The values of the row the user opened, for its hidden fields."""
        try:
            return {"ok": True, "values": api_keys.saved(str(service or ""))}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"读取配置失败：{type(exc).__name__}"}

    def save_api_key(self, service: str, values: dict[str, Any]) -> dict[str, Any]:
        try:
            api_keys.save(str(service or ""), {str(k): str(v) for k, v in (values or {}).items()})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return self.api_keys()

    def clear_api_key(self, service: str) -> dict[str, Any]:
        try:
            api_keys.clear(str(service or ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"清除失败：{type(exc).__name__}"}
        return self.api_keys()

    def test_api_key(self, service: str, values: dict[str, Any]) -> dict[str, Any]:
        """Whether the service takes what is in the row's fields (saved or not)."""
        try:
            return api_keys.test(str(service or ""), {str(k): str(v) for k, v in (values or {}).items()})
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        except Exception as exc:  # the window must get an answer, or it stays on 正在测试…
            return {"status": "error", "message": f"测试没有完成：{type(exc).__name__}"}

    def open_signup(self, service: str, guide: bool = False) -> dict[str, Any]:
        """The service's page for getting a key, or its guide; only the listed pages open."""
        found = api_keys.find(str(service or ""))
        address = found and (found.get("guide") if guide else found["url"])
        if not address:
            return {"ok": False, "message": "打开失败：没有这一项"}
        import webbrowser

        try:
            opened = webbrowser.open(address)
        except Exception as exc:
            return {"ok": False, "message": f"打开失败：{type(exc).__name__}"}
        return {"ok": True} if opened else {"ok": False, "message": "打开失败：没有找到默认浏览器"}

    # --- PaperSearch Pro: the Markdown page -------------------------------
    def school_login_state(self) -> dict[str, Any]:
        """The sign-in page (PaperSearch Pro, school_login.py): the schools saved, each with its account
        (masked; never the password) and whether Pro fills it in, the default one first (user,
        2026-11-20: several schools here, one of them the default for downloads, switched here); the
        default one's fields at the top level too, for the home page's line."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from . import school_login
            from .config import load_config
            from .schools import saved as saved_schools

            config = load_config()
            saved_schools.remember(config)
            pro = school_login.module()
            listed = []
            for entry in saved_schools.saved(config):
                entity_id = str(entry.get("idp_entity_id") or "").strip()
                account = school_login.saved(config, entity_id) or {}
                listed.append({"key": entity_id, "name": str(entry.get("school_name") or ""),
                               "name_en": str(entry.get("school_name_en") or ""),
                               "current": saved_schools.is_current(config, entry), "entity": bool(entity_id),
                               "saved": bool(account), "username": school_login.masked(account.get("username", "")) if account else "",
                               "enabled": bool(account.get("enabled")), "off": str(account.get("off") or ""),
                               "status": school_login.school_status(entity_id, pro) if pro is not None else ""})
            listed.sort(key=lambda school: not school["current"])
            current = next((school for school in listed if school["current"]), {})
            from . import school_switch

            return {"ok": True, "pro": pro is not None, "schools": listed, "switch": school_switch.enabled(config),
                    "counts": school_login.school_counts(pro) if pro is not None else {},
                    "school": current.get("name", ""), "entity": bool(current.get("entity")), "saved": bool(current.get("saved")),
                    "username": current.get("username", ""), "enabled": bool(current.get("enabled")),
                    "off": current.get("off", ""), "status": current.get("status", "")}
        except Exception as exc:
            return {"ok": False, "error": f"读取失败：{type(exc).__name__}"}

    def school_support_list(self) -> dict[str, Any]:
        """The sign-in page's 支持哪些学校 (user, 2026-11-20): the schools Pro knows, by name and province,
        each with what it does for them; an older Pro has no list."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from . import school_login

            pro = school_login.module()
            if pro is None:
                return {"ok": False, "error": "需要 PaperSearch Pro"}
            schools = school_login.school_list(pro)
        except Exception as exc:
            return {"ok": False, "error": f"读取失败：{type(exc).__name__}"}
        return {"ok": True, "schools": schools} if schools else {"ok": False, "error": "需要更新 PaperSearch Pro"}

    @staticmethod
    def _login_school(config: dict[str, Any], key: str) -> str:
        """The entityID of the saved school ``key`` names; the default school's when it is empty; "" when none."""
        from .schools import saved as saved_schools

        key = str(key or "").strip()
        if not key:
            return str(config.get("idp_entity_id") or "").strip()
        saved_schools.remember(config)
        known = {str(entry.get("idp_entity_id") or "").strip() for entry in saved_schools.saved(config)}
        return key if key in known else ""

    def school_login_saved(self, key: str = "") -> dict[str, str]:
        """A saved school's account and password, for the sign-in page's fields: the password there,
        hidden until its eye shows it (user, 2026-11-19: they may see it). The default school's by default."""
        if not pro_features():
            return {}
        try:
            from . import school_login
            from .config import load_config

            config = load_config()
            account = school_login.saved(config, self._login_school(config, key)) or {}
        except Exception:
            return {}
        return {"username": str(account.get("username") or ""), "password": str(account.get("password") or "")}

    def save_school_login(self, username: str = "", password: str = "", enabled: bool = True, key: str = "") -> dict[str, Any]:
        """Keep a saved school's account (the default school's by default); empty fields keep what was saved (the switch)."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from . import school_login
            from .config import load_config

            entity_id = self._login_school(load_config(), key)
            if key and not entity_id:
                return {"ok": False, "error": "这所学校还没有添加"}
            school_login.save(entity_id, str(username or ""), str(password or ""), enabled=bool(enabled))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return self.school_login_state()

    # 测试登录 (user, 2026-11-21; school_test.py): a saved school's account tried on an article, as a download goes.
    def school_test_article(self, key: str = "") -> dict[str, Any]:
        """The article this school's test opens: {ok, doi} ("" while the user has set none)."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        from .config import load_config
        from .school_test import article

        entity_id = self._login_school(load_config(), key)
        return {"ok": True, **article(entity_id)} if entity_id else {"ok": False, "error": "这所学校还没有添加"}

    def set_school_test_article(self, key: str = "", text: str = "") -> dict[str, Any]:
        """The article set by its DOI or its page's address (user, 2026-11-21: set by them, none for them)."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from .config import load_config
            from .school_test import set_article

            entity_id = self._login_school(load_config(), key)
            return set_article(entity_id, str(text or "")) if entity_id else {"ok": False, "error": "这所学校还没有添加"}
        except Exception as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}

    def start_school_test(self, key: str = "", doi: str = "") -> dict[str, Any]:
        """Starts the test of a saved school whose account is saved, on ``doi``; or says why not."""
        if not pro_features():
            return {"state": "idle", "error": "这个版本没有自动登录"}
        try:
            from . import school_login
            from .config import load_config

            config = load_config()
            entity_id = self._login_school(config, key)
            if not entity_id:
                return {"state": "idle", "error": "这所学校还没有添加"}
            if not school_login.saved(config, entity_id):
                return {"state": "idle", "error": "先保存账号和密码，再测试"}
            doi = str(doi or "").strip()
            if not doi:
                return {"state": "idle", "error": "先填测试文章"}
            return self._school_test().start(entity_id, doi)
        except Exception as exc:
            return {"state": "idle", "error": f"测试没有开始：{type(exc).__name__}"}

    def school_test_state(self) -> dict[str, Any]:
        return self._school_test().state()

    def stop_school_test(self) -> dict[str, Any]:
        return self._school_test().stop()

    def forget_school_test(self) -> dict[str, Any]:
        self._school_test().forget()
        return self._school_test().state()

    def _school_test(self):
        from .school_test import SchoolTest

        test = getattr(self, "_test", None)
        if test is None:
            test = self._test = SchoolTest()
        return test

    def set_school_switch(self, on: bool = True) -> dict[str, Any]:
        """没权限时换下一所学校 on or off (school_switch.py); the page's state after it."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from .config import update_config
            from .school_switch import SETTING

            update_config(SETTING, "true" if on else "false")
        except Exception as exc:
            return {"ok": False, "error": f"保存失败：{type(exc).__name__}"}
        return self.school_login_state()

    def clear_school_login(self, key: str = "") -> dict[str, Any]:
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from . import school_login
            from .config import load_config

            school_login.clear(self._login_school(load_config(), key))
        except Exception as exc:
            return {"ok": False, "error": f"清除失败：{type(exc).__name__}"}
        return self.school_login_state()

    def find_school(self, query: str = "") -> dict[str, Any]:
        """The sign-in page's 添加学校: the school named, in any language, by its domain or entityID, from
        the federations' own lists (schools/lookup.py, as setup finds one); each with whether Pro fills its
        sign-in in and whether it is saved already (user, 2026-11-20: only a school found there is kept)."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "请输入学校名称"}
        try:
            from . import school_login
            from .config import DATA_DIR, load_config
            from .schools import lookup
            from .schools import saved as saved_schools

            config = load_config()
            found = lookup.find(query, config, DATA_DIR)
            schools = ([found.school] if found.school is not None else []) + [s for s in found.candidates if s != found.school]
            # Kept for 添加: the school found, not looked up again (user, 2026-11-20: the page seemed stuck).
            self._found_schools = {school.entity_id: school for school in schools if school.entity_id}
            saved_schools.remember(config)
            saved = {str(entry.get("idp_entity_id") or "").strip() for entry in saved_schools.saved(config)}
            pro = school_login.module()
            # 支持哪些学校's own search too (user, 2026-11-21: 台湾 found nothing here, Taiwan's schools there): Pro's
            # list by any of its names (Wikidata's Chinese one among them), its country, province or state, in
            # Chinese or English; each school's names in other languages for the page to show.
            listed = [school for school in school_login.school_list(pro) if school["key"]] if pro is not None else []
            known = {school["key"]: school for school in listed}
            wanted = query.lower()

            def said(school: dict[str, Any]) -> str:
                places = [school["province"], school["area"], school["country"]]
                return " ".join([school["name"], school["name_en"], *school["names"].values(), *places,
                                 *(i18n.translate(place, "en") for place in places if place)]).lower()

            results = [{"key": school.entity_id, "name": school.name, "name_en": school.name_en,
                        "names": known.get(school.entity_id, {}).get("names", {}),
                        "federation": school.summary()["federation"], "added": school.entity_id in saved,
                        "status": school_login.school_status(school.entity_id, pro) if pro is not None else ""}
                       for school in schools if school.entity_id]
            taken = {result["key"] for result in results}
            results += [{"key": school["key"], "name": school["name"], "name_en": school["name_en"], "names": school["names"],
                         "federation": school["country"], "added": school["key"] in saved, "status": school["status"]}
                        for school in listed if school["key"] not in taken and wanted in said(school)]
        except Exception as exc:
            return {"ok": False, "error": f"查找失败：{type(exc).__name__}"}
        left = max(0, len(results) - FOUND_SHOWN)
        note = (f"还有 {left} 所没列出，输入更完整的名称可以缩小范围" if left
                else "" if results else "这所学校所在的学术联盟还不支持" if found.unsupported
                else "学校名单暂时读不到，请稍后再试" if found.unavailable
                else "没有找到这所学校：换成学校的正式中文名、英文名或网址试试")
        return {"ok": True, "results": results[:FOUND_SHOWN], "note": note}

    def add_school(self, key: str = "") -> dict[str, Any]:
        """A school found by 添加学校 kept in the saved list, the default one unchanged (none yet: it)."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from .config import DATA_DIR, load_config, save_config
            from .schools import lookup
            from .schools import saved as saved_schools

            key = str(key or "").strip()
            config = load_config()
            known = getattr(self, "_found_schools", {}).get(key)  # the school 添加学校 found
            if known is None:
                found = lookup.find(key, config, DATA_DIR) if key else None
                if found is None or found.school is None or found.school.entity_id != key:
                    return {"ok": False, "error": "这所学校没有找到，请重新查找"}
                known = found.school
            school: dict[str, Any] = {}
            lookup.save(school, known)
            if saved_schools.current(config) is None:
                saved_schools.apply(config, school)
            saved_schools.remember(config)
            listed = saved_schools.saved(config)
            if not any(saved_schools._same(entry, school) for entry in listed):
                listed.append({name: school.get(name) for name in saved_schools.SCHOOL_FIELDS})
            config[saved_schools.SAVED_KEY] = listed[:saved_schools.MAX_SAVED]
            save_config(config)
        except Exception as exc:
            return {"ok": False, "error": f"添加失败：{type(exc).__name__}"}
        return self.school_login_state()

    def set_default_school(self, key: str = "") -> dict[str, Any]:
        """A saved school as the default one for downloads (the current school; `paper-search-school use`)."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from .config import load_config, save_config
            from .schools import saved as saved_schools

            config = load_config()
            saved_schools.remember(config)
            entry = next((entry for entry in saved_schools.saved(config)
                          if str(entry.get("idp_entity_id") or "").strip() == str(key or "").strip()), None)
            if entry is None:
                return {"ok": False, "error": "这所学校还没有添加"}
            saved_schools.apply(config, entry)
            saved_schools.remember(config)
            save_config(config)
        except Exception as exc:
            return {"ok": False, "error": f"切换失败：{type(exc).__name__}"}
        return self.school_login_state()

    def forget_school(self, key: str = "") -> dict[str, Any]:
        """A saved school out of the list, its account with it; the default one stays."""
        if not pro_features():
            return {"ok": False, "error": "这个版本没有自动登录"}
        try:
            from . import school_login
            from .config import load_config, save_config
            from .schools import saved as saved_schools

            config = load_config()
            saved_schools.remember(config)
            entry = next((entry for entry in saved_schools.saved(config)
                          if str(entry.get("idp_entity_id") or "").strip() == str(key or "").strip()), None)
            if entry is None:
                return {"ok": False, "error": "这所学校还没有添加"}
            if not saved_schools.forget(config, entry):
                return {"ok": False, "error": "默认学校不能移除：先把别的学校设为默认"}
            save_config(config)
            school_login.clear(str(key).strip())
        except Exception as exc:
            return {"ok": False, "error": f"移除失败：{type(exc).__name__}"}
        return self.school_login_state()

    def pro_status(self) -> dict[str, Any]:
        from . import pro_status

        try:
            return {"ok": True, **pro_status.status()}
        except Exception as exc:
            return {"ok": False, "error": f"读取失败：{type(exc).__name__}"}

    def install_pro(self, code: str | None = None) -> dict[str, Any]:
        """Pro's 安装, or 激活并安装 with the code typed: starts it, or says how it goes (pro_install_state)."""
        return self._pro_installer().start(None if code is None else str(code))

    def pro_install_state(self) -> dict[str, Any]:
        return self._pro_installer().state()

    def _pro_installer(self):
        from .pro_status import ProInstall

        installer = getattr(self, "_pro_install", None)
        if installer is None:
            installer = self._pro_install = ProInstall()
        return installer

    # One version and one update (user, 2026-11-21; updates.py): the about page, the home page's foot, the card's dot.
    def versions(self) -> dict[str, Any]:
        """The version this window runs and the one installed now (an update elsewhere: they differ)."""
        from . import updates

        return {"running": updates.RUNNING, "installed": updates.installed_version()}

    def check_versions(self, again: bool = False) -> dict[str, Any]:
        return self._version_check().start(bool(again))

    def versions_state(self) -> dict[str, Any]:
        return self._version_check().state()

    def update_all(self) -> dict[str, Any]:
        """更新: what the last check found behind (PaperSearch, then its extension and Skills; Pro)."""
        checked = self._version_check().state()
        if checked.get("state") != "done":
            return {"state": "idle", "error": "先检查更新"}
        return self._updater().start(bool(checked.get("update")), bool(checked.get("pro_update")),
                                     str(checked.get("latest") if checked.get("update") else ""))

    def update_state(self) -> dict[str, Any]:
        return self._updater().state()

    def reopen_window(self, page: str = "about") -> dict[str, Any]:
        """The settings opened again with the PaperSearch installed now, once this window has closed."""
        from . import updates

        page = page if page in ("home", "about") else "about"
        if not updates.reopen(page):
            return {"ok": False, "message": "找不到 paper-search 命令，请关掉窗口后重新打开设置"}
        threading.Timer(0.3, self.request_close).start()
        return {"ok": True}

    def open_release_notes(self) -> dict[str, Any]:
        """这次更新了什么: the release notes where the check found the new version."""
        import webbrowser

        url = str(self._version_check().state().get("notes") or "")
        if not url.startswith("https://"):
            return {"ok": False, "message": "没有更新说明"}
        try:
            opened = webbrowser.open(url)
        except Exception as exc:
            return {"ok": False, "message": f"打开失败：{type(exc).__name__}"}
        return {"ok": True} if opened else {"ok": False, "message": "打开失败：没有找到默认浏览器"}

    def _version_check(self):
        from .updates import VersionCheck

        check = getattr(self, "_versions", None)
        if check is None:
            check = self._versions = VersionCheck()
        return check

    def _updater(self):
        from .updates import UpdateAll

        updater = getattr(self, "_update_all", None)
        if updater is None:
            updater = self._update_all = UpdateAll()
        return updater

    def open_issue(self) -> dict[str, Any]:
        """GitHub's new-issue page for the Markdown, its title begun."""
        import webbrowser

        from .pro_status import ISSUE_URL

        try:
            opened = webbrowser.open(ISSUE_URL)
        except Exception as exc:
            return {"ok": False, "message": f"打开失败：{type(exc).__name__}"}
        return {"ok": True} if opened else {"ok": False, "message": "打开失败：没有找到默认浏览器"}

    def choose_download_directory(self) -> str | None:
        """Native directory picker; cancelling leaves the field unchanged."""
        import webview

        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                  directory=download_directory.current())
        return str(selected[0]) if selected else None

    # --- the window -------------------------------------------------------
    def _button_held(self) -> bool:
        if sys.platform == "darwin" and self._native_geometry:
            return _mac_button_held()
        if sys.platform == "win32":
            return _windows_button_held()
        return True

    def _drag_point(self, x: float, y: float) -> tuple[float, float]:
        if sys.platform == "darwin" and self._native_geometry:
            return _mac_pointer()
        if sys.platform == "win32":
            return _windows_pointer()
        return x, y

    def _mac_press(self) -> tuple[float, float, float, float] | None:
        """The press a macOS drag began with, followed natively from now on (_MacDrag)."""
        if self._mac_drag is None or not (sys.platform == "darwin" and self._native_geometry):
            return None
        try:
            return _cocoa_call(self._mac_drag.start)
        except TimeoutError as exc:
            import logging

            logging.getLogger(__name__).warning("capsule drag follows the page: %s", exc)
            return None

    def set_dragging(self, active: bool, screen_x: float | None = None,
                     screen_y: float | None = None) -> None:
        """Freeze resizing while held, then place the window on its drop screen."""
        with self._geometry_lock:
            if active:
                scale = _window_scale(self._window)
                press = self._mac_press()
                self._native_drag = press is not None
                if press is None:
                    x, y, _, _ = _window_geometry(self._window, self._native_geometry)
                    point = self._drag_point(screen_x or 0, screen_y or 0)
                    press = (*point, x * scale, y * scale)
                self._drag_origin = press
                self._drag_pointer = press[:2]
                self._dragging = self._hovering = True
                self._placement.rescale(scale)
                self._layout = None
            elif self._dragging:
                try:
                    if not self._native_drag and screen_x is not None and screen_y is not None:
                        self.move_drag(screen_x, screen_y)
                finally:
                    self._dragging = False
                if self._native_drag:
                    self._native_drag = False
                    self._drag_pointer = _cocoa_call(self._mac_drag.stop) or self._drag_pointer
                origin, point = self._drag_origin, self._drag_pointer
                self._drag_origin = None
                self._drag_pointer = None
                if self._window is None or origin is None or point is None or point == origin[:2]:
                    return
                actual = Rect(*_window_geometry(self._window, self._native_geometry))
                scale = _window_scale(self._window)
                self._placement.rescale(scale)
                target = self._placement.dragged(actual, _screen_areas(self._window),
                                                 (point[0] / scale, point[1] / scale))
                if target != actual:
                    _set_window_frame(self._window, target)

    def move_drag(self, screen_x: float, screen_y: float) -> None:
        """Use pointer deltas, independent of the web engine's screen origin."""
        with self._geometry_lock:
            if not self._dragging or self._drag_origin is None or self._native_drag:
                return  # on macOS the window follows the mouse itself (_MacDrag)
            sx, sy, x, y = self._drag_origin
            if not self._button_held():
                # The page reports the release late, and the pointer may have
                # moved on since: the window stays where it was let go.
                return
            # WebView coordinates can rebase across monitors. Native pointer
            # deltas stay global; on Windows they are physical until the move.
            screen_x, screen_y = self._drag_point(screen_x, screen_y)
            if self._drag_pointer == (screen_x, screen_y):
                return
            self._drag_pointer = (screen_x, screen_y)
            x, y = round(x + screen_x - sx), round(y + screen_y - sy)
            if sys.platform == "darwin" and self._native_geometry:
                import AppKit

                def move():
                    top = AppKit.NSScreen.screens()[0].frame().size.height
                    self._window.native.setFrameTopLeftPoint_(AppKit.NSPoint(x, top - y))
                _cocoa_call(move)
            else:
                scale = _window_scale(self._window)
                self._window.move(round(x / scale), round(y / scale))

    def hover_state(self) -> dict[str, Any]:
        """Read the real pointer/frame together; native enter/exit events may be stale."""
        import AppKit

        def read():
            point = AppKit.NSEvent.mouseLocation()
            frame = self._window.native.frame()
            return {"x": point.x, "y": point.y,
                    "inside": frame.origin.x + 10 <= point.x < frame.origin.x + frame.size.width - 10
                    and frame.origin.y + 10 <= point.y < frame.origin.y + frame.size.height - 10}
        return _cocoa_call(read)

    def begin_layout(self, expanded: bool, width: float, height: float, generation: int) -> dict[str, Any]:
        """Choose a corner once per expansion and plan one atomic frame animation."""
        with self._geometry_lock:
            if self._dragging or self._window is None:
                return {}
            actual = Rect(*_window_geometry(self._window, self._native_geometry))
            self._placement.rescale(_window_scale(self._window))
            self._placement.begin(expanded, actual, _screen_areas(self._window))
            target = self._placement.target(max(MIN_SIZE[0], int(width)), max(MIN_SIZE[1], int(height)), expanded)
            self._layout = (generation, expanded, actual, target)
            vertical, horizontal = self._placement.direction
            return {"vertical": vertical, "horizontal": horizontal,
                    "width": target.width, "height": target.height,
                    "from_width": actual.width, "from_height": actual.height}

    def resize(self, width: float, height: float, fraction: float = 1, generation: int = 0) -> None:
        """Position and size change together; obsolete animation frames are ignored."""
        with self._geometry_lock:
            if self._dragging or self._window is None or self._layout is None:
                return
            current, _, start, target = self._layout
            if generation != current:
                return
            t = max(0, min(1, fraction))
            frame = Rect(round(start.x + (target.x - start.x) * t),
                         round(start.y + (target.y - start.y) * t),
                         round(start.width + (target.width - start.width) * t),
                         round(start.height + (target.height - start.height) * t))
            _set_window_frame(self._window, frame)

    def finish_layout(self, generation: int) -> None:
        with self._geometry_lock:
            if self._layout is None or self._layout[0] != generation or self._dragging:
                return
            _, expanded, _, target = self._layout
            self._placement.finish(expanded, target)
            self._layout = None

    def request_close(self) -> None:
        # Let the JS bridge deliver this call's reply before disposing WebView2.
        # The watcher stays alive independently of the page's stopped timers.
        self._close_requested = time.monotonic() + 0.2

    def close(self) -> None:
        self._closed = True
        progress_view.release_window_lock()
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            pass


def main() -> None:
    if not progress_view.claim_window():
        return  # another progress window is open: it shows this download too
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(f"进度胶囊需要 pywebview，当前环境里没有（{exc}）；请运行 paper-search school update")
    try:
        page = page_html()
        screens = _screen_areas()
        placement = Placement(progress_path().parent / "capsule.json", _corner())
        x, y = placement.start(screens, START_SIZE, _window_scale())
        size = (round(placement.home.width), round(placement.home.height))
        api = Api(placement, Notifier(), progress_view.AutoClose.from_env())
        dark = progress_view.dark_mode()
        if sys.platform == "darwin":
            x = y = None  # placed at placement.home on its first show (_prepare_nonactivating_start)
        window = webview.create_window(
            "PaperSearch", html=page, js_api=api, width=size[0], height=size[1], x=x, y=y,
            min_size=MIN_SIZE, resizable=False, frameless=True, easy_drag=False, on_top=True, focus=True,
            transparent=sys.platform == "darwin", shadow=True,
            background_color="#202124" if dark else "#FFFFFF",
        )
        api._window = window
        window._capsule_home = placement.home if sys.platform == "darwin" else None
        if sys.platform == "darwin":
            from .progress_macos import install_notification_handler

            try:
                install_notification_handler(lambda current, run_id: api.act("show_browser", current, run_id))
            except (OSError, RuntimeError) as exc:
                import logging

                logging.getLogger(__name__).warning("notification host unavailable: %s", type(exc).__name__)
        api._native_geometry = sys.platform == "darwin"
        _prepare_nonactivating_start(window)
        if sys.platform == "darwin":
            api._mac_drag = _MacDrag(window)
            window.events.loaded += lambda: api._mac_drag.install_soon()
        # Do not persist native moved events: animated resizing emits them too.
        # Only the user's completed drag updates the collapsed home.
        window.events.loaded += lambda: _enable_inactive_hover(window)
        if os.name == "nt":
            def restore_after_dpi_setup():
                # pywebview enables DPI awareness while creating the native form.
                # Re-read work areas before showing it, in that form's actual scale.
                placement.start(_screen_areas(window), START_SIZE, _window_scale(window))
                _set_window_frame(window, placement.home)

            window.events.before_show += restore_after_dpi_setup
            window.events.shown += lambda: (_round_windows_corners(window), _windows_taskbar_icon(window))
        progress_view.write_window_lock()
        # icon: the Dock icon on macOS, instead of a blank one; watch: notifications and closing.
        webview.start(func=api.watch, icon=str(ICON) if sys.platform == "darwin" else None)
    except Exception:  # no usable web engine (e.g. WebView2 missing): no window this time
        if sys.platform == "darwin":
            from .progress_macos import close

            close()
        progress_view.release_window_lock()
        raise
    progress_view.release_window_lock()
    if sys.platform == "darwin":
        from .progress_macos import close

        close()
    # The window is gone. pywebview answers each page call on a thread of its own,
    # and one still waiting for the closed page would hold the interpreter's
    # shutdown forever (the window froze on screen): leave without waiting.
    os._exit(0)


if __name__ == "__main__":
    main()
