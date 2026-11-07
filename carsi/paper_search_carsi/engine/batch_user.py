"""The progress window's buttons, acted on while the article runs.

A thread started for each article reads the window's requests every second.
"Skip" buttons end the article at once: the running browser call is
interrupted. A problem report is handled on the browser thread before its next
call: the live page is captured, then the kind of report decides what happens
(read the PDF an open tab shows, go back to the article, reload, stop choosing
the school). The outcome is shown in the window and kept with the report.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import progress_reporter
from ..entitlements import UserMarkedNoEntitlement
from .batch_common import DownloadResult, open_page
from .page_activity import PageActivity


class _UserWatch(threading.Event):
    def __init__(self, activity: PageActivity):
        super().__init__()
        self.activity = activity

    def set(self) -> None:
        super().set()
        self.activity.close()


class UserProvidedPdf(Exception):
    """A problem report pointed at an open PDF the capture missed; it is this article's."""

    def __init__(self, body: bytes, url: str):
        super().__init__(url)
        self.body, self.url = body, url


class PdfFoundWhileWaiting(UserProvidedPdf):
    """While the login waited, this article's PDF came from an open tab or the
    article's PDF address (batch_capture.py ``_probe_pdf``)."""


class UserRequestsMixin:
    """The progress window's buttons, acted on while the article runs."""

    # "跳到了无关页面" on the school's login page or a chooser of this login is
    # answered there, the login left alone; a second one on the same page within
    # this time goes back to the article. ACS, 2026-11-02: the user took the
    # school's CAS page for a wrong one and the return cut the login off.
    LOGIN_PAGE_REPORT_SEC = 300
    LOGIN_PAGE_NOTICE = ("已记录。当前是学校登录页，这是正常的一步，请在这里登录；"
                         "如果确实不对，再点一次“跳到了无关页面”即可返回文章。")

    def _start_user_watch(self, page: Any, result: DownloadResult) -> threading.Event:
        """Watch the window's requests for this article; set the returned event to stop."""
        from .. import entitlements, issues
        from ..browser import watchdog

        activity, _ = self._observe_page_activity(page, result)
        stop = _UserWatch(activity)
        publisher = str(getattr(getattr(self, "profile", None), "name", "") or "")
        since = getattr(self, "_item_started", 0.0)
        scheduled: set[str] = set()
        if sys.platform == "darwin":
            from ..browser.foreground import mac_browser_pid

            try:
                pid = mac_browser_pid(page, self.config)
            except Exception as exc:
                self._event(result, "browser_focus_unavailable", type(exc).__name__)
                pid = 0
            progress_reporter.update(browser_pid=pid)

        def watch() -> None:
            while not stop.wait(1.0):
                activity.check()
                try:
                    action = entitlements.apply_user_decision(result.doi, publisher, since)
                    if action == entitlements.SHOW_BROWSER:
                        watchdog.run_soon(lambda: self._show_download_browser(page, result))
                except UserMarkedNoEntitlement as decision:
                    self._event(result, "user_entitlement_decision", str(decision))
                    watchdog.interrupt(decision)
                    return
                except Exception:
                    pass
                try:
                    new = [f for f in issues.pending_captures(result.doi) if f.name not in scheduled]
                except Exception:
                    new = []
                if new:
                    scheduled.update(f.name for f in new)
                    watchdog.run_soon(lambda: self._capture_reported_issues(page, result))

        threading.Thread(target=watch, name="user-requests", daemon=True).start()
        return stop

    def _observe_page_activity(self, page: Any, result: DownloadResult) -> tuple[PageActivity, bool]:
        activity = getattr(result, "_page_activity", None)
        owned = activity is None or activity.closed
        if owned:
            result._page_activity = activity = PageActivity(result.doi, self.config)
        if page is not None:
            activity.observe(page)
        return activity, owned

    def _show_download_browser(self, page: Any, result: DownloadResult) -> None:
        """Focus the existing task page only after the user requests it."""
        from ..browser import watchdog

        try:
            page = getattr(result, "_attention_page", None) or page
            activity = getattr(result, "_page_activity", None)
            if not getattr(result, "_attention_page", None) and activity is not None and not activity.closed:
                page = activity.page or page
            if page is None or page.is_closed():
                self._tell_user("下载浏览器已关闭", result)
                return
            from ..browser.foreground import show

            show(page, self.config)
            wait = getattr(result, "_login_wait", None)
            if wait is not None and getattr(result, "_login_attention", ""):
                wait.take_over()
                self._set_login_attention(result, result._login_attention, page=page)
            verification_wait = getattr(result, "_verification_wait", None)
            if verification_wait is not None:
                verification_wait.take_over()
        except (watchdog.BrowserUnresponsive, UserMarkedNoEntitlement):
            raise
        except Exception as exc:
            self._event(result, "browser_focus_failed", type(exc).__name__)
            self._tell_user("未能切到下载浏览器，请从程序坞或任务栏打开", result)
            return
        self._event(result, "browser_shown", "requested from progress capsule")
        self._tell_user("已切到下载浏览器", result)

    def _handle_report(self, folder: Path, page: Any, result: DownloadResult, *, act: bool = True) -> None:
        """Capture the live page for a report and, while the article runs (``act``),
        do what it asks. Raises only to end the article (an open PDF that is this
        article's, or another button pressed meanwhile)."""
        from .. import issues
        from ..browser import watchdog

        kind = issues.kind_of(folder)
        issues.attach_page(folder, page, result.events)
        self._event(result, "user_issue_report", f"{kind} {folder.name}")
        if not act:
            return
        text, action = "已记录页面，留给 agent 分析", "captured"
        try:
            if kind == "pdf_not_captured":
                found = self._open_pdf_for_record(page, result.doi)
                if found:
                    issues.mark_handled(folder, "pdf_found", "从打开的标签页读到本文的 PDF")
                    self._tell_user("已从打开的 PDF 读取，正在核对并保存", result)
                    watchdog.interrupt(UserProvidedPdf(*found))
                    raise watchdog.interrupted
                text, action = "没在打开的标签页里找到本文的 PDF，已记录页面", "pdf_not_found"
            elif kind == "wrong_redirect" and self._first_report_on_login_page(page, result):
                text, action = self.LOGIN_PAGE_NOTICE, "login_page_kept"
            elif kind in ("wrong_redirect", "personal_login", "no_institution_page"):
                if getattr(result, "_report_returned", False):
                    text = "已记录页面；已经回过一次文章，请在浏览器里自己点到学校登录"
                else:
                    result._report_returned = True
                    open_page(page, result.article_url, timeout_ms=60_000)
                    text, action = "已记录页面，已回到文章重新进入；也可以在浏览器里自己点到学校登录", "returned"
            elif kind == "wrong_school":
                self._manual_school = True
                text, action = "已停止自动选校，请在浏览器里选择学校", "manual_school"
            elif kind == "stuck_loading":
                page.reload(wait_until="commit", timeout=60_000)
                text, action = "已记录页面并刷新", "reloaded"
        except Exception as exc:
            if watchdog.interrupted is not None or watchdog.fired is not None:
                raise
            text, action = f"已记录页面；处理时出错（{type(exc).__name__}）", "error"
        issues.mark_handled(folder, action, text)
        where = f" | {str(getattr(page, 'url', '') or '')[:160]}" if action == "login_page_kept" else ""
        self._event(result, "user_issue_handled", f"{kind}: {action}{where}")
        self._tell_user(text, result)

    def _first_report_on_login_page(self, page: Any, result: DownloadResult) -> bool:
        """The tab is on the school's login page or a chooser of this login
        (``_school_or_federation_page``) and no "wrong page" report came on this
        page in the last ``LOGIN_PAGE_REPORT_SEC``. The next one there goes back."""
        url = str(getattr(page, "url", "") or "")
        if not self._school_or_federation_page(url, result):
            return False
        parsed = urlparse(url)
        here = f"{parsed.hostname}{parsed.path}"
        seen = getattr(result, "_login_page_report", None)
        if seen and seen[0] == here and time.time() - seen[1] < self.LOGIN_PAGE_REPORT_SEC:
            result._login_page_report = None
            return False
        result._login_page_report = (here, time.time())
        return True

    def _open_pdf_for_record(self, page: Any, doi: str) -> tuple[bytes, str] | None:
        """This article's PDF from an open tab: what the browser's PDF viewer shows,
        or a PDF address fetched with the browser's session. None when no tab has it."""
        from .pdf_guard import names_other_article

        try:
            tabs = [p for p in list(page.context.pages) if not p.is_closed()]
        except Exception:
            tabs = [page]
        for tab in tabs[:8]:
            url = str(getattr(tab, "url", "") or "")
            try:
                body = self._viewer_pdf_for_record(tab, doi)
            except Exception:
                body = None
            if not body and url.startswith("http") and "pdf" in url.lower():
                try:
                    response = tab.context.request.get(url, timeout=60_000)
                    body = response.body() if response.ok else None
                except Exception:
                    body = None
            if body and body.startswith(b"%PDF-") and not names_other_article(body, doi, self._identity_title()):
                return body, url
        return None

    @staticmethod
    def _tell_user(text: str, result: DownloadResult) -> None:
        """Show the outcome of a click in the progress window."""
        try:
            progress_reporter.update(notice={"text": text, "current": result.doi, "at": time.time()})
        except Exception:
            pass
