"""Profile-driven browser batch downloader with retryable machine states.

``PublisherBatchDownloader`` keeps the article flow (``fetch_one``) here and combines
one mixin per responsibility from the ``batch_*.py`` modules: login, institution
choice, access state, waits on the user, PDF capture, PDF URLs, runs over many
records, diagnostics. Shared definitions live in ``batch_common.py``."""

from __future__ import annotations

# The module's imports from before the split are kept: callers and tests reach
# some of these names (``batch.time``, ``batch.requests``) through this module.
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import csv
import inspect
import json
import logging
import os
import re
import shutil
import threading
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, quote

import requests

from ..config import load_config, parse_proxy_pool
from ..extractors import pdf_extractor
from ..download_diagnostics import serialize_download_result, serialize_download_summary
from .. import progress_reporter
from .router import (
    build_pdf_candidates,
    extract_elsevier_pii,
    is_pdf_candidate_url,
    is_supplementary_url,
    is_springer_article_pdf_url,
    is_thieme_article_pdf_url,
)
from ..publishers.profiles import ACS_PROFILE, PublisherProfile
from ..entitlements import UserMarkedNoEntitlement  # noqa: E402  (re-exported)
from ..adapters import PublisherAdapter, adapter_class  # noqa: E402
from .batch_common import (
    page_operation,  # re-exported: other modules import these from batch
    open_page,
    goto_retrying,
    settle,
    _is_network_failure,
    browser_closed,
    DownloadResult,
    EST_ISSN,
    IP_BLOCK_STOP_THRESHOLD,
    AWAY_WAIT_SEC,
    MAX_BROWSER_CONCURRENCY,
    MIN_PDF_BYTES,
    PDF_URL_RE,
    PaperRecord,
    PublisherAccessBlocked,
    PublisherContentError,
    PublisherPlatformUnsupported,
    ArticleNotYetPublished,
    RETRYABLE_REASONS,
    _ACCESS_GATE_JS,
    _IN_REFERENCES_JS,
    _IP_BLOCK_STATUS_CODES,
    _JS_TEXTOF,
    _JS_VISIBLE,
    _OPEN_ACCESS_LICENSE,
    _OPEN_ACCESS_LICENSE_PHRASE,
    _PagePool,
    _REFERENCE_AREA,
    _block_state,
    _is_browser_error,
    _observe_preview,
    _resolve_profile_dir,
    fetch_est_records,
    logger,
    safe_name,
)
from .batch_login import GENERIC_ENTRY_MISSING, LoginMixin
from .batch_institution import InstitutionMixin
from .batch_access import AccessMixin
from .batch_waits import UserWaitMixin
from .batch_capture import CaptureMixin
from .batch_pdf_urls import PdfUrlsMixin
from .batch_runs import RunsMixin
from .batch_diagnostics import DiagnosticsMixin
from .batch_user import PdfFoundWhileWaiting, UserProvidedPdf, UserRequestsMixin
from ..browser import watchdog
from ..entitlements import UserSkippedArticle, UserStoppedBatch


class PublisherBatchDownloader(
    LoginMixin,
    InstitutionMixin,
    AccessMixin,
    UserWaitMixin,
    CaptureMixin,
    PdfUrlsMixin,
    RunsMixin,
    DiagnosticsMixin,
    UserRequestsMixin,
):
    """Deterministic publisher workflow with diagnostic packets for surprises."""

    @property
    def adapter(self) -> PublisherAdapter:
        """The most specific adapter for the current article: journal, then publisher.

        Re-selected when the profile, the article's DOI or the host the page
        landed on changes (journals served from their own sites).
        """
        name = str(getattr(self.profile, "name", "") or "").lower()
        doi = getattr(self, "_adapter_doi", "") or ""
        page = getattr(self, "_adapter_page", None)
        try:
            host = (urlparse(str(page.url)).hostname or "") if page is not None else ""
        except Exception:
            host = ""  # a closed page keeps the last selection's host out
        issns = getattr(self, "_adapter_issns", ()) or ()
        cls = adapter_class(name, doi=doi, host=host, issns=issns)
        # Adapters keep no state: the instance changes only with the class.
        if type(getattr(self, "_adapter", None)) is not cls:
            self._adapter = cls(self)
        return self._adapter

    def _download_in_new_tab(self, page: Any, url: str, *, result: DownloadResult | None = None) -> tuple[Path, str]:
        """Open the file in a new tab, as typed in the address bar, and take what
        the browser downloads. Clicks on the page were flaky after the first
        file (a later file's download never started); new tabs took 8 of 8
        (Taylor & Francis with ego, 2026-11-01)."""
        from .page_activity import transfer
        from .supplements import MAX_FILE_BYTES

        tab = page.context.new_page()
        path = None
        completed = False
        try:
            activity = getattr(result, "_page_activity", None)
            if activity is not None:
                activity.observe(tab)
            downloads = []
            tab.on("download", lambda item: downloads.append(item))
            deadline = time.monotonic() + 60
            try:
                referer = str(page.url)
                goto_retrying(tab, url, timeout_ms=60_000, wait_until="load",
                              **({"referer": referer} if referer.startswith(("http://", "https://")) else {}))
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
            with tempfile.NamedTemporaryFile(prefix="papersearch-supplement-", suffix=".part", delete=False) as fh:
                path = Path(fh.name)
            while time.monotonic() < deadline:
                if result is not None:
                    self._check_user_decision(result, tab)
                if downloads:
                    download = downloads[0]
                    with transfer(result):
                        download.save_as(str(path))
                    name = download.suggested_filename
                    download.delete()
                    completed = True
                    return path, name
                if self._pdf_viewer_present(tab):
                    # Inline attachments produce no download event. Reuse the
                    # native reader, copying at most 1 MiB across each bridge
                    # call directly to disk, under the attachment size limit.
                    with transfer(result):
                        saved = self._capture_loaded_pdf_viewer(tab, url, output=path, max_bytes=MAX_FILE_BYTES)
                    if saved == path:
                        completed = True
                        return path, Path(unquote(urlparse(url).path)).name or "supplement.pdf"
                tab.wait_for_timeout(min(250, max(1, int((deadline - time.monotonic()) * 1000))))
            raise TimeoutError("attachment download or native PDF was not ready")
        finally:
            if path is not None and not completed:
                path.unlink(missing_ok=True)
            tab.close()

    def collect_supplements(self, context: Any, doi: str, output_dir: Path,
                            result: "DownloadResult", *, manifest_dir: Path | None = None) -> list[dict[str, Any]]:
        """Open the article page in a new tab of ``context`` (already logged in)
        and download every supplementary file the adapter lists there."""
        from . import supplements
        from .supplement_transfer import browser_request

        self._run_dir = manifest_dir or getattr(self, "_run_dir", None)
        self._phase(result, "supplements")
        main_state = result.state
        progress_reporter.update(part="supplements", supplements_saved=0, supplements_total=None)
        try:
            page = context.new_page()
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            # The browser was closed meanwhile (during the login wait, SID Symposium
            # Digest 2026-11-02): no supplements, and the article keeps its result.
            self._event(result, "supplements_skipped", f"browser closed: {type(exc).__name__}")
            return [{"status": "skipped", "reason": "browser_closed", "url": "", "label": ""}]
        user_watch = self._start_user_watch(page, result)
        try:
            with watchdog.operation(self.page_wait_sec, "supplement_discovery"):
                self._track_article_for_adapter(page, doi)
                links: list = []
                # The journal's own article page the main text came from (cell.com,
                # journal-of-hepatology.eu) lists every file it has: no detour to the
                # platform, also when it lists none.
                final_url = str(getattr(result, "final_url", "") or "")
                own_page = [final_url] if final_url and self.adapter.is_article_page_url(final_url) else []
                candidates = self.adapter.supplements_page_urls(doi) or [self._article_url(doi)]
                incomplete = ""
                listed = list(getattr(result, "_listed_supplements", None) or [])
                if listed:
                    # Read on the article page before its PDF: no second load.
                    links = listed
                    self._event(result, "supplements_listed_on_article", str(len(links)))
                for url in ([] if listed else dict.fromkeys(own_page + candidates)):
                    open_page(page, url, timeout_ms=60_000)
                    if self._challenge_shell(page) or self._is_challenge_page(page):
                        if not self._wait_for_challenge(page, result):
                            self._event(result, "supplements_failed", "verification not completed")
                            return [{"status": "failed", "reason": "challenge_timeout", "url": url, "label": ""}]
                    settle(page, 2_000)
                    while True:
                        # The initial check can finish on a blank redirect, and
                        # the adapter can trigger a later navigation. Neither is
                        # evidence that the article has no supplementary files.
                        self._wait_for_page_text(page, result)
                        if not self._wait_for_challenge(page, result):
                            self._event(result, "supplements_failed", "verification not completed")
                            return [{"status": "failed", "reason": "challenge_timeout", "url": url, "label": ""}]
                        self._wait_for_page_text(page, result)
                        if self._challenge_shell(page) or self._is_challenge_page(page):
                            continue
                        links = self._settled_supplement_links(page, doi, result)
                        if not (self._challenge_shell(page) or self._is_challenge_page(page)):
                            break
                    self._snapshot(page, result, "supplements page")
                    if links is None:
                        self._event(result, "supplements_not_supported", self.profile.name)
                        return [{"status": "skipped", "reason": "supplements_not_supported", "url": url, "label": ""}]
                    # An identity-provider redirect can finish after verification.
                    # An empty login page is no evidence about the article's files.
                    if not links and self._is_auth_page(str(getattr(page, "url", "") or "")):
                        incomplete = "login_required"
                        continue  # The next journal/platform entry may still work.
                    incomplete = ""
                    if links or url in own_page:
                        break
                if incomplete:
                    self._event(result, "supplements_failed", incomplete)
                    return [{"status": "failed", "reason": incomplete, "url": "", "label": ""}]
                self._event(result, "supplements_found", str(len(links)))
                progress_reporter.update(supplements_total=len(links))
            files = []
            if links:
                with browser_request(page, self.config, proxy=self._context_proxy.get(id(context))) as request:
                    files = supplements.collect(request, links, Path(output_dir), doi,
                                                manifest_dir=manifest_dir,
                                                target_dir=Path(output_dir) / "supplements" if self.config.get("diagnostics_dir") else None,
                                                download=lambda url: self._download_in_new_tab(page, url, result=result),
                                                activity=user_watch.activity.progress,
                                                progress=lambda saved: progress_reporter.update(supplements_saved=saved))
            saved = sum(1 for f in files if f.get("status") == "saved")
            self._event(result, "supplements_saved", f"{saved}/{len(files)}")
            return files
        except PublisherContentError as exc:
            self._event(result, "supplements_failed", str(exc))
            return [{"status": "failed", "reason": "publisher_content_error", "url": "", "label": ""}]
        except watchdog.BrowserUnresponsive as exc:
            reason = ("browser_operation_timeout" if isinstance(exc, watchdog.BrowserOperationTimeout)
                      else "browser_unresponsive")
            self._event(result, "supplements_failed", reason)
            return [{"status": "failed", "reason": reason, "url": "", "label": ""}]
        except UserMarkedNoEntitlement as exc:
            reason = ("batch_stopped" if isinstance(exc, UserStoppedBatch) else
                      "user_skipped" if isinstance(exc, UserSkippedArticle) else "user_marked_no_entitlement")
            self._event(result, "supplements_skipped", reason)
            if not result.ok:
                result.reason = result.state = reason
            return [{"status": "skipped", "reason": reason, "url": "", "label": ""}]
        except PublisherAccessBlocked:
            # The publisher paused access (BJSM, 2026-11-01): the article ends as
            # blocked when its main text failed, so the batch stops as for any block.
            self._event(result, "publisher_access_blocked", "supplements")
            if not result.ok:
                result.reason = result.state = "publisher_access_blocked"
            return [{"status": "failed", "reason": "publisher_access_blocked", "url": "", "label": ""}]
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "supplements_failed", f"{type(exc).__name__}: {str(exc)[:160]}")
            # The site did not answer, not the error's class name ("Error": pubs.acs.org
            # closed the connection on every try, Windows 2026-11-07).
            reason = "publisher_unreachable" if _is_network_failure(exc) else type(exc).__name__
            return [{"status": "failed", "reason": reason, "url": "", "label": ""}]
        finally:
            user_watch.set()
            watchdog.clear_interrupt()
            if result.ok:
                result.state = main_state
            self._close_phase(result)
            try:
                page.close()
            except Exception:
                pass

    def _settled_supplement_links(self, page: Any, doi: str, result: Any = None) -> Any:
        """The adapter's links once the page has stopped navigating (ScienceDirect
        moves /pii/ to /abs/pii/ by script after the document has loaded). A site
        without a rule of its own gets the shared one (``page_supplements``); a
        Figshare resource set aside is recorded on ``result``, not returned."""
        for attempt in range(3):
            try:
                from ..adapters.platforms.figshare import supplement_links as external_links
                from .page_supplements import listed_files

                own = self.adapter.supplement_links(page, doi)
                if own is None:
                    own = listed_files(page, doi) or None
                external = external_links(page, doi)
                if result is not None:
                    for link in external or ():
                        if link.set_aside:
                            self._event(result, "supplements_set_aside", f"{link.set_aside} {link.url}")
                external = [link for link in external or () if not link.set_aside] or None
                if own is None and external is None:
                    from ..adapters.platforms.silverchair import declares_no_supplements

                    # No rule found files, but the page itself may say there are none.
                    return [] if declares_no_supplements(page, doi) else None
                return list(dict.fromkeys([*(own or []), *(external or [])]))
            except Exception as exc:
                if (attempt == 2 or not _is_browser_error(exc)
                        or "Execution context was destroyed" not in str(exc)):
                    raise
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
                settle(page, 2_000)
        return None

    def _track_article_for_adapter(self, page: Any, doi: str) -> None:
        """Remember the article whose journal decides the adapter (ISSN from cache only)."""
        self._adapter_page = page
        self._adapter_doi = (doi or "").lower()
        try:
            from ..entitlements import journal_identity

            self._adapter_issns = tuple(journal_identity(doi, lookup=False).get("issn") or ())
        except Exception:
            self._adapter_issns = ()

    def __init__(
        self,
        config: dict | None = None,
        *,
        profile: PublisherProfile = ACS_PROFILE,
        institution_query: str = "",
        login_timeout_sec: int = 180,
        pdf_timeout_sec: int = 60,
        post_login_hold_sec: int = 0,
        post_run_hold_sec: int = 0,
        require_interactive_browser: bool = False,
    ) -> None:
        self.config = load_config() if config is None else config
        self.profile = profile
        self.institution_query = institution_query.strip()
        self.login_timeout_sec = login_timeout_sec
        self.pdf_timeout_ms = max(1, pdf_timeout_sec) * 1_000
        self.post_login_hold_sec = max(0, int(post_login_hold_sec or 0))
        self.post_run_hold_sec = max(0, int(post_run_hold_sec or 0))
        # The institutional downloader this implementation replaced always
        # launched a *visible* browser, because its login flow is a manual
        # SSO/2FA round trip. Callers that come from that path set this flag
        # so that ``browser_headless`` in the config cannot turn the login
        # into one a headless browser cannot complete.
        self.require_interactive_browser = bool(require_interactive_browser)
        # Set True by _run_once/_run_once_parallel when IP_BLOCK_STOP_THRESHOLD
        # consecutive ip_blocked results trip an auto-stop. Read by run_records.
        self._ip_block_stopped: bool = False
        # Populated by _run_once_parallel_rotating with proxies that were
        # excluded due to IP-block detection. Read by run_records summary.
        self._proxy_blocked: list[str] = []
        # Maps id(context) → proxy string so _fetch_pdf_url can look up the
        # egress proxy for a page's context and pass it to requests.get().
        self._context_proxy: dict[int, str] = {}
        # Cookies exported from a closing browser context, re-injected into the
        # next one when browser_restart_every segments a long run. Session
        # cookies (no Expires) do not survive a persistent-context restart on
        # disk, so the hand-off must go through memory.
        self._handoff_cookies: list[dict[str, Any]] | None = None
        self._progress_active = False

    def _launch_context(self, profile_dir: str | Path | None = None, *, proxy: str | None = None,
                        relaunch: str = ""):
        """The persistent browser context; ``relaunch``: why the item's first
        browser was replaced (kept for the item's record with the launch's own)."""
        from ..browser import backend as browser_backend
        from ..browser import watchdog
        from ..browser.engine import get_persistent_context

        watchdog.install()

        profile_path = _resolve_profile_dir(self.config, profile_dir)
        profile_path.mkdir(parents=True, exist_ok=True)
        # Overlay a per-launch proxy without mutating the shared config object.
        config = dict(self.config)
        if proxy:
            config["browser_static_proxy"] = proxy
        if getattr(self, "require_interactive_browser", False):
            # This flow drives a manual SSO/2FA login, which a headless browser
            # cannot complete. The institutional downloader this replaced was
            # always visible, so keep it that way regardless of the config.
            if config.get("browser_headless"):
                logger.info(
                    "require_interactive_browser: forcing a visible browser "
                    "(browser_headless=%s) for the interactive login",
                    config.get("browser_headless"),
                )
            config["browser_headless"] = False
        started = time.time()
        ctx = get_persistent_context(profile_path, config)
        from ..browser.challenge_interaction import prepare_context
        prepare_context(ctx)
        self._browser_start = {**dict(getattr(browser_backend, "LAST_LAUNCH", {}) or {}),
                               "seconds": round(time.time() - started, 1), **({"relaunch": relaunch} if relaunch else {})}
        from ..browser.backend import browser_info
        # Which browser and version this article ran in (ADR 0013).
        self.browser = browser_info(config)
        from ..browser.preview import ensure_enabled
        ensure_enabled(ctx, config)
        if self.profile.base_domains:
            # Chromium drops session cookies when its process exits. Reuse the
            # existing publisher-only cache without overwriting live values.
            from ..browser.cookies import _restore_cookies_to_context
            _restore_cookies_to_context(ctx, config, preserve_existing=True)
        # Record the binding so _fetch_pdf_url can route plain-HTTP requests
        # through the same proxy as this context's browser traffic.
        if proxy:
            self._context_proxy[id(ctx)] = proxy
        return ctx

    def fetch_one(self, context_or_page: Any, record: PaperRecord, run_dir: Path) -> DownloadResult:
        # Support both context (creates new page) and pre-created page (from page pool)
        if hasattr(context_or_page, "new_page") and hasattr(context_or_page, "cookies"):
            # It's a context — create a new page
            page = context_or_page.new_page()
            _owns_page = True
        else:
            # It's already a page (from page pool)
            page = context_or_page
            _owns_page = False
        result = DownloadResult(
            doi=record.doi,
            status="failed",
            state="started",
            article_url=self._article_url(record.doi),
        )
        self._item_started = time.time()
        self._item_result = result
        self._record_title = record.title
        self._expected_title = ""
        self._manual_school = False
        self._track_article_for_adapter(page, record.doi)
        from ..browser import watchdog

        self._phase(result, "open")
        progress_reporter.update(part="main", supplements_saved=0, supplements_total=None,
                                 title=record.title or "")
        self._run_dir = run_dir
        watchdog.on_slow_call = lambda name, seconds, ended, where: self._event(
            result, "wait", f"browser call {name}: {seconds:.0f} s, ended: {ended} ({where})")
        start = getattr(self, "_browser_start", None)
        if start:
            # Recorded with the item the browser was started for, once.
            self._browser_start = None
            result.browser_start = dict(start)
            self._event(result, "browser_start", self._browser_start_line(start))
        user_watch = self._start_user_watch(page, result)
        # Reuse confirmed public access only for this document's initial PDF
        # attempt. A redirect or reload (even at the same URL) invalidates it.
        def invalidate_open_access(frame: Any) -> None:
            if frame == page.main_frame:
                result._open_access_current = False

        page.on("framenavigated", invalidate_open_access)
        try:
            preparation = self._prepare_article(page, result, run_dir)
            if preparation is not None:
                return preparation
            if self.config.get("login_only"):
                # `login` (cli): the school's login and the article's access, then stop; no PDF.
                result.signed_in = self._school_login_done()
                result.state = "access_ready"
                self._event(result, "login_only_done",
                            "signed in to the school" if result.signed_in else "access without the school's login")
                return result
            self._snapshot(page, result, "article access checked")
            ip_block: str | None = None
            # Whether this capture comes after the school's login, and its first attempt.
            signed_in, attempts_from = self._school_login_done(), len(result.pdf_attempts)
            pdf_bytes, pdf_url, ip_block = self._capture_pdf(page, record.doi, result)
            if not pdf_bytes:
                if ip_block or result.reason == "institution_pdf_entitlement_missing":
                    result.reason = result.state = ("institution_pdf_entitlement_missing"
                        if (result.reason == "institution_pdf_entitlement_missing"
                            or self._institution_pdf_entitlement_missing(page)) else _block_state(ip_block))
                    result.final_url = page.url
                    result.title = self._title(page)
                    self._write_diagnostic(page, result, run_dir)
                    return result
                wall = self._pdf_step_login_required(result) or self._looks_logged_out(page)
                # The PDF was tried first (nothing said either way, or only the
                # reader's access showed): the school's login, once, then the PDF again.
                retry = (not wall and getattr(result, "_pdf_first", False) and not self._school_login_done())
                if wall or retry:
                    if wall:
                        self._event(result, "auth_wall_after_pdf_attempt", self._decision_text(page))
                    else:
                        self._event(result, "access_unknown_pdf_failed", getattr(page, "url", ""))
                        self._reopen_article_page(page, result)
                        result._pdf_retry_login = True
                    logged_in = self._complete_login_from_current_page(page, result)
                    attempts_from = len(result.pdf_attempts)
                    if logged_in:
                        result.final_url = page.url
                        result.title = self._title(page)
                        result.state = "article_loaded_after_sso"
                        pdf_bytes, pdf_url, cap_block = self._capture_pdf(page, record.doi, result)
                        ip_block = ip_block or cap_block
                        if not pdf_bytes and self._denied_after_login(page):
                            # The institution login just completed and the publisher
                            # still denies the PDF (Thieme's type=auth_denied): this
                            # journal is not licensed.
                            self._event(result, "pdf_denied_after_institution_login", str(page.url))
                            self._snapshot(page, result, "not subscribed")
                            result.reason = "institution_pdf_entitlement_missing"
                    elif self._article_access_available(page):
                        self._event(result, "login_completed_after_timeout", getattr(page, "url", ""))
                        result.final_url = page.url
                        result.title = self._title(page)
                        result.state = "article_loaded_after_sso"
                        pdf_bytes, pdf_url, cap_block = self._capture_pdf(page, record.doi, result)
                        ip_block = ip_block or cap_block
                    result._pdf_retry_login = False
                    if (not pdf_bytes and not ip_block and result.reason != "institution_pdf_entitlement_missing"
                            and not self._pdf_sent_to_article_after_login(page, result, attempts_from)
                            and logged_in and len(result.pdf_attempts) == attempts_from):
                        # Nothing was tried after the school's login, and the page still
                        # denies, offers or abstracts the article: the school has no access
                        # (Thieme's Thrombosis and Haemostasis, "Buy Article", 2026-11-02).
                        evidence = self._no_access_after_login(page, result)
                        if evidence:
                            result.reason = "institution_pdf_entitlement_missing"
                            self._event(result, "no_access_after_login", evidence[:300])
                            self._snapshot(page, result, "not subscribed")
                    # Explicit denial and blocked requests are terminal; an
                    # ordinary login failure retains its existing reason.
                    if ip_block or result.reason == "institution_pdf_entitlement_missing":
                        result.reason = result.state = ("institution_pdf_entitlement_missing"
                            if (result.reason == "institution_pdf_entitlement_missing"
                                or self._institution_pdf_entitlement_missing(page)) else _block_state(ip_block))
                        result.final_url = page.url
                        result.title = self._title(page)
                        self._write_diagnostic(page, result, run_dir)
                        return result
                    block_reason = self._login_block_reason(page)
                    if not pdf_bytes and (block_reason or self._looks_logged_out(page)):
                        result.reason = block_reason or result.reason or "sso_required"
                        result.state = result.reason
                        result.final_url = page.url
                        result.title = self._title(page)
                        self._write_diagnostic(page, result, run_dir)
                        return result
                    if not pdf_bytes:
                        # A site without rules whose page offered no institution entry says so.
                        result.reason = result.state = (GENERIC_ENTRY_MISSING if result.reason == GENERIC_ENTRY_MISSING
                                                        else "pdf_not_captured")
                        result.final_url = page.url
                        result.title = self._title(page)
                        self._write_diagnostic(page, result, run_dir)
                        return result
                else:
                    if ip_block:
                        result.reason = result.state = _block_state(ip_block)
                        result.final_url = page.url
                        result.title = self._title(page)
                        self._write_diagnostic(page, result, run_dir)
                        return result
                    block_reason = self._login_block_reason(page)
                    if (not block_reason and signed_in
                            and self._pdf_sent_to_article_after_login(page, result, attempts_from)):
                        block_reason = "institution_pdf_entitlement_missing"
                    result.reason = block_reason or "pdf_not_captured"
                    result.state = result.reason
                    result.final_url = page.url
                    result.title = self._title(page)
                    self._write_diagnostic(page, result, run_dir)
                    return result

            if not pdf_bytes:
                result.reason = "pdf_not_captured"
                result.state = "pdf_not_captured"
                result.final_url = page.url
                result.title = self._title(page)
                self._write_diagnostic(page, result, run_dir)
                return result

            return self._save_captured_pdf(page, record, result, run_dir, pdf_bytes, pdf_url)
        except UserProvidedPdf as provided:
            watchdog.clear_interrupt()
            self._event(result, "pdf_found_while_waiting" if isinstance(provided, PdfFoundWhileWaiting)
                        else "pdf_from_user_report", provided.url)
            return self._save_captured_pdf(page, record, result, run_dir, provided.body, provided.url)
        except UserStoppedBatch as decision:
            watchdog.clear_interrupt()
            result.reason = result.state = "batch_stopped"
            self._event(result, "batch_stopped", str(decision))
            self._write_diagnostic(page, result, run_dir)
            return result
        except UserSkippedArticle as decision:
            watchdog.clear_interrupt()
            result.reason = result.state = "user_skipped"
            self._event(result, "user_skipped", str(decision))
            self._write_diagnostic(page, result, run_dir)
            return result
        except UserMarkedNoEntitlement as decision:
            watchdog.clear_interrupt()
            result.reason = result.state = "user_marked_no_entitlement"
            self._event(result, "user_marked_no_entitlement", str(decision))
            self._write_diagnostic(page, result, run_dir)
            return result
        except PublisherAccessBlocked:
            result.reason = result.state = "publisher_access_blocked"
            self._event(result, "publisher_access_blocked")
            self._write_diagnostic(page, result, run_dir)
            return result
        except ArticleNotYetPublished as page_url:
            result.reason = result.state = "article_not_yet_published"
            self._event(result, "article_not_yet_published", str(page_url))
            progress_reporter.update(phase="出版社尚未发布这篇论文的全文，当前路径已停止")
            self._write_diagnostic(page, result, run_dir)
            return result
        except PublisherPlatformUnsupported as platform:
            result.reason = result.state = "unsupported_platform"
            self._event(result, "unsupported_platform", str(platform))
            progress_reporter.update(phase=f"这篇文章只在 {platform} 平台提供，暂不支持，当前路径已停止")
            self._write_diagnostic(page, result, run_dir)
            return result
        except PublisherContentError as error:
            result.reason = "publisher_content_error"
            result.state = "publisher_content_error"
            self._event(result, "publisher_content_error", str(error))
            progress_reporter.update(phase="出版社内容服务错误，当前路径已停止")
            self._write_diagnostic(page, result, run_dir)
            return result
        except watchdog.BrowserUnresponsive as exc:
            if isinstance(exc, watchdog.BrowserBudgetExhausted) and result.state == "challenge_or_viewer_timeout":
                result.reason = result.state
            else:
                result.reason = result.state = ("browser_operation_timeout" if isinstance(exc, watchdog.BrowserOperationTimeout)
                                                else "browser_unresponsive")
            self._event(result, result.state, str(exc))
            self._write_diagnostic(page, result, run_dir)
            return result
        except Exception as exc:
            import traceback

            frames = traceback.extract_tb(exc.__traceback__)
            own = [f for f in frames if "paper_search_carsi" in f.filename]
            frames = (own or frames)[-4:]
            where = " <- ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(frames))
            if _is_network_failure(exc):
                # The site did not answer: reported as the publisher's side.
                result.reason = result.state = "publisher_unreachable"
                self._event(result, "publisher_unreachable", f"{str(exc).splitlines()[0][:300]} | {where}")
                self._write_diagnostic(page, result, run_dir)
                return result
            if browser_closed(exc):
                # The user closed the download browser, or it quit: said as such, not
                # as an unexplained error (Elsevier at the school's login page, 2026-11-09).
                result.reason = result.state = "browser_closed"
                self._event(result, "browser_closed", f"{type(exc).__name__}: {str(exc)[:200]} | {where}")
                self._write_diagnostic(page, result, run_dir)
                return result
            result.reason = f"{type(exc).__name__}: {exc}"
            result.state = "unexpected_error"
            # The diagnostic normalizes reason to "unexpected_error"; keep the
            # exception and where it happened as an event so it can be fixed.
            self._event(result, "unexpected_exception", f"{type(exc).__name__}: {str(exc)[:400]} | {where}")
            self._write_diagnostic(page, result, run_dir)
            return result
        finally:
            page.remove_listener("framenavigated", invalidate_open_access)
            user_watch.set()
            watchdog.on_slow_call = None
            if isinstance(watchdog.interrupted, UserMarkedNoEntitlement) and result.ok:
                # The click came while the PDF was being saved.
                self._tell_user("点击时这一篇已经保存好了，没有跳过", result)
            watchdog.clear_interrupt()
            stopped = bool(watchdog.fired) or result.state in {
                "browser_unresponsive", "browser_operation_timeout", "user_skipped", "batch_stopped", "user_marked_no_entitlement"}
            if not stopped:
                self._capture_reported_issues(page, result, act=False)
            if not result.ok:
                progress_reporter.report_stage("route_failed", current=record.doi)
            if not stopped:
                self._hold_after_run(page, result)
            if _owns_page:
                try:
                    page.close()
                except Exception:
                    pass

    @page_operation
    def _prepare_article(self, page: Any, result: DownloadResult, run_dir: Path) -> DownloadResult | None:
        """Reach the first PDF attempt within one shared page budget."""
        self._event(result, "article_open", result.article_url)
        if not self._ensure_login(page, result):
            if self._article_access_available(page):
                self._event(result, "login_completed_after_timeout", getattr(page, "url", ""))
            else:
                return self._login_failed(page, result, run_dir)

        self._return_from_other_article(page, result)
        settle(page, 2_000)
        if not (getattr(result, "_open_access_current", False)
                or self._pdf_first_unless_signed_out(page, result)):
            self._event(result, "auth_wall_after_article_load", self._decision_text(page))
            # This item has been through the school's login and the article still
            # denies it, shows only its abstract or offers it: the school has no
            # access, and a second login would only wait out the user's time
            # (JAMA Oncology back from the store page, 2026-11-02).
            evidence = self._no_access_after_login(page, result)
            if evidence:
                result.reason = result.state = "institution_pdf_entitlement_missing"
                self._event(result, "no_access_after_login", evidence[:300])
                self._snapshot(page, result, "not subscribed")
                result.final_url = page.url
                result.title = self._title(page)
                self._write_diagnostic(page, result, run_dir)
                return result
            if not self._complete_login_from_current_page(page, result):
                if self._article_access_available(page):
                    self._event(result, "login_completed_after_timeout", getattr(page, "url", ""))
                else:
                    return self._login_failed(page, result, run_dir)
            settle(page, 2_000)
            if not self._pdf_first_unless_signed_out(page, result):
                return self._login_failed(page, result, run_dir)

        self._return_from_other_article(page, result)
        result.final_url = page.url
        result.title = self._title(page)
        result.state = "article_loaded"
        self._event(result, "article_access_ready")
        self._hold_after_login(page, result)
        return None

    @staticmethod
    def _browser_start_line(start: dict) -> str:
        """``browser_start``'s detail: "profile free; launch 3.1 s", or the holder,
        the wait for it and its release, and a relaunch's reason."""
        holder = str(start.get("holder") or "")
        parts = [f"relaunch: {start['relaunch']}"] if start.get("relaunch") else []
        if holder and holder != "free":
            parts.append(f"profile {holder}, waited {start.get('waited', 0)} s, "
                         + ("released" if start.get("released") else "still held"))
        elif holder:
            parts.append("profile free")
        parts.append(f"launch {start.get('seconds', 0)} s")
        return "; ".join(parts)

    def _reopen_article_page(self, page: Any, result: DownloadResult) -> None:
        """Back to the article page the PDF was tried from, for its login entry."""
        target = str(result.final_url or result.article_url)
        try:
            open_page(page, target)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "article_reopen_error", f"{type(exc).__name__}: {str(exc)[:160]}")
            return
        settle(page, 3_000)
        self._wait_past_redirect_page(page, result)
        self._dismiss_cookie_banners(page, result)

    def _article_url(self, doi: str) -> str:
        """The article's page: the adapter's (APS's journal codes), else the profile's."""
        return self.adapter.article_url(doi) or self.profile.article_url(doi)

    def _login_failed(self, page: Any, result: DownloadResult, run_dir: Path) -> DownloadResult:
        """The login did not complete: name the reason, and for a wait that ran
        out, where it ended (a timeout on the school's login page is the user's
        step; elsewhere the program did not reach the login, ADR 0012)."""
        result.reason = self._login_block_reason(page) or result.reason or "sso_required"
        result.state = result.reason
        if result.reason == "login_timeout" or (
                result.reason == "sso_required" and getattr(result, "_user_wait_expired", False)):
            result.login_wait_page = self._login_wait_page(page)
            self._event(result, "login_wait_ended", result.login_wait_page)
        self._write_diagnostic(page, result, run_dir)
        return result

    def _save_captured_pdf(self, page: Any, record: PaperRecord, result: DownloadResult, run_dir: Path,
                           pdf_bytes: bytes, pdf_url: str) -> DownloadResult:
        """Check that a captured PDF is this article's and save it with its record."""
        pdf_dir = run_dir / "pdfs"
        if not pdf_bytes.startswith(b"%PDF-") or self._is_supplementary_url(pdf_url):
            result.reason = result.state = "pdf_not_captured"
            self._event(result, self.adapter.pdf_rejected_event, "non_article_or_invalid_pdf")
            return result
        from .pdf_guard import names_other_article

        # With the title the capture judged by: a PDF it accepted by its exact title is
        # not refused here for citing another DOI (review, 2026-11-02).
        other_dois = names_other_article(pdf_bytes, record.doi, record.title or self._identity_title())
        if other_dois:
            # Page 1 labels another article (e.g. a stale viewer tab): never save it.
            result.reason = result.state = "pdf_wrong_article"
            self._event(result, "pdf_wrong_article", f"{pdf_url} names {', '.join(other_dois)[:200]}")
            result.final_url = page.url
            result.title = self._title(page)
            self._write_diagnostic(page, result, run_dir)
            return result
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{safe_name(record.doi)}.pdf"
        pdf_path.write_bytes(pdf_bytes)
        self._event(result, "pdf_saved")
        text = pdf_extractor.extract_from_bytes(pdf_bytes)
        result.status = "success"
        result.reason = ""
        result.state = "pdf_response_captured"
        result.pdf_url = pdf_url
        result.pdf_path = str(pdf_path)
        result.size_bytes = len(pdf_bytes)
        result.text_length = len(text or "")
        result.verified_match = self._text_matches_record(
            text, record, fallback_title=self._identity_title() or result.title)
        if result.verified_match and str(self.config.get("supplements") or "") != "with":
            self._drop_snapshot_pictures(result)
        self._save_publisher_session(page, result)
        if not any(e["state"] == "pdf_saved_unconfirmed" for e in result.events):
            from ..browser.preview import discard_frames
            discard_frames(getattr(page, "context", None))
        result.record_path = str(run_dir / f"{safe_name(record.doi)}.json")
        self._close_phase(result)
        packet = serialize_download_result(result, full_text=text, artifact_name=pdf_path.name, diagnostic=True)
        packet["browser"] = getattr(self, "browser", {})
        (run_dir / f"{safe_name(record.doi)}.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


class ACSCloakBatchDownloader(PublisherBatchDownloader):
    """Compatibility wrapper for the original ACS/EST downloader API."""

    def __init__(
        self,
        config: dict | None = None,
        *,
        institution_query: str = "",
        login_timeout_sec: int = 180,
        pdf_timeout_sec: int = 60,
    ) -> None:
        super().__init__(
            config,
            profile=ACS_PROFILE,
            institution_query=institution_query,
            login_timeout_sec=login_timeout_sec,
            pdf_timeout_sec=pdf_timeout_sec,
        )
