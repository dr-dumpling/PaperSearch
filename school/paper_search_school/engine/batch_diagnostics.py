"""Events, diagnostic files and reading the page's title and text.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..extractors import pdf_extractor
from ..download_diagnostics import serialize_download_result
from .. import progress_reporter
from . import access_rules
from .batch_common import DownloadResult, PaperRecord, safe_name, _is_browser_error, page_title


class DiagnosticsMixin:
    """Events, diagnostic files and reading the page's title and text."""

    def _capture_reported_issues(self, page: Any, result: DownloadResult | None, *, act: bool = True) -> None:
        """Problem reports the user filed for this paper: capture the live page and,
        while the article still runs (``act``), do what each asks (batch_user.py)."""
        # A report's own browser calls run queued work, which may be this again: once.
        if result is None or page is None or getattr(self, "_handling_reports", False):
            return
        try:
            from .. import issues
            folders = issues.pending_captures(result.doi)
        except Exception:
            return
        self._handling_reports = True
        try:
            for folder in folders:
                self._handle_report(folder, page, result, act=act)
        finally:
            self._handling_reports = False

    _title = staticmethod(page_title)

    @staticmethod
    def _body_text(page: Any, limit: int = 2_000) -> str:
        from ..browser.preview import observe_page
        observe_page(page)
        try:
            text = page.locator("body").inner_text(timeout=3_000)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return ""
        return re.sub(r"\s+", " ", text).strip()[:limit]

    # A step after more than this much silence says so ("gap"), and a wait this
    # long says what it waited for and why it ended (Sage's silent 60 s and 30 s,
    # 2026-11-02).
    LONG_WAIT_SEC = 10

    @staticmethod
    def _event(result: DownloadResult | None, state: str, detail: str = "") -> None:
        if result is not None:
            now = time.monotonic()
            item = {"state": state, "detail": detail[:500], "at": datetime.now().strftime("%H:%M:%S")}
            last = getattr(result, "_last_event_at", None)
            from ..browser import watchdog
            spent = watchdog.take_period()
            if last is not None and now - last > DiagnosticsMixin.LONG_WAIT_SEC:
                item["gap"] = round(now - last)
                if spent["calls"]:
                    item["browser_time"] = (f"{spent['calls']} browser calls, {spent['seconds']:.0f} s; slowest "
                                            f"{spent['slowest']} {spent['slowest_sec']:.0f} s")
            result._last_event_at = now
            result.events.append(item)
            activity = getattr(result, "_page_activity", None)
            if activity is not None and state in {
                "article_open", "institution_federation_selected", "article_access_ready",
                "pdf_capture_started", "browser_pdf_response_captured", "pdf_saved",
                "supplements_found", "supplements_saved", "challenge_resolved",
                # The login steps the program takes itself: while it is still
                # choosing the school the page is not waiting for the user (JBJS on
                # OpenAthens, 2026-11-06: five remembered-school clicks in 25 s, no
                # main-frame navigation, and a "no progress" reminder in between).
                "sso_entry_clicked", "openathens_entry", "seamlessaccess_chooser_opened",
                "auto_remembered_entry", "institution_selected", "auto_institution_search",
                "institution_search_submitted", "institution_search_retyped",
                "institution_list_submitted", "institution_continue",
                "login_round_trip_returned", "redirect_page_passed",
                "publisher_terms_accepted", "idp_confirmation_accepted",
            }:
                activity.progress()
            # Only publish fixed phase text; event details can contain signed URLs.
            report = {
                "article_open": ("打开论文页面", "opening_article"),
                "sso_start": ("正在查找机构登录入口", "checking_access"),
                "institution_federation_selected": ("已进入所选机构认证联盟", "checking_access"),
                "institution_selection_required": ("检查学校选择入口", "checking_access"),
                "institution_entry_unresolved": ("官方机构入口尚未确认所属联盟", "checking_access"),
                "login_state": ("检查机构登录页面", "checking_access"),
                "idp_confirmation_required": ("请在浏览器里确认学校认证页的提示（信息发送同意、使用条款或二次验证）", "waiting_login"),
                "idp_confirmation_accepted": ("已确认学校认证页的提示", "checking_access"),
                "publisher_terms_accepted": ("已同意出版社的条款", "checking_access"),
                "login_attempt_started": ("正在尝试机构登录", "checking_access"),
                "login_retry_wait": ("机构登录暂未完成，准备重试", "checking_access"),
                "login_navigation_interrupted": ("登录跳转中断，检查是否可重试", "checking_access"),
                "login_stopped": ("机构登录未完成", "route_failed"),
                "challenge_manual_wait": ("等待人工安全验证", "waiting_verification"),
                "challenge_wait": ("正在检查安全验证", "checking_access"),
                "challenge_interaction": ("正在操作安全验证复选框", "checking_access"),
                "challenge_resolved": ("安全验证已结束，继续检查页面", "checking_access"),
                "article_access_ready": ("论文页面已就绪，检查正文入口", "checking_access"),
                "publisher_content_error": ("出版社返回内容服务错误", "route_failed"),
                "publisher_access_blocked": ("网站已阻止当前访问，此路径已停止", "route_failed"),
                "pdf_capture_started": ("读取 PDF", "fetching_pdf"),
                "browser_pdf_response_captured": ("PDF 已捕获，正在保存", "pdf_captured"),
                "pdf_saved": ("PDF 已保存，待内容核验", "saved_pending_verification"),
            }.get(state)
            if state == "login_state" and getattr(result, "_login_attention", ""):
                report = ("等待在浏览器完成机构登录", "waiting_login")
            if state == "challenge_manual_wait" or state == "challenge_wait" and detail.startswith("manual "):
                report = (("等待人工安全验证", "waiting_verification")
                          if getattr(result, "_verification_attention", False)
                          else ("正在检查安全验证", "checking_access"))
            if state == "login_attempt_started" and detail in {"1/3", "2/3", "3/3"}:
                report = (f"机构登录：第 {detail[0]} 次尝试，共 3 次", "checking_access")
            if state == "login_observed":
                if detail == "verification":
                    report = ("正在检查安全验证", "checking_access")
                elif detail == "human_login":
                    report = ("等待在浏览器完成机构登录", "waiting_login")
                else:
                    report = ("检查机构登录页面", "checking_access")
            # A click can finish after a synchronous PDF response was captured;
            # capture_started supplies its stage without moving it backwards.
            if report:
                phase, stage = report
                progress_reporter.report_stage(stage, current=result.doi)
                progress_reporter.update(phase=phase)

    @staticmethod
    def _phase(result: DownloadResult | None, name: str) -> str:
        """Count the time from now on to phase ``name`` (open, verification, login,
        pdf, supplements); the previous phase's name, to go back to it."""
        if result is None:
            return ""
        now = time.monotonic()
        current = getattr(result, "_phase_now", None)
        activity = getattr(result, "_page_activity", None)
        if activity is not None and name and (current is None or current[0] != name):
            activity.progress()
        if current:
            result.phases[current[0]] = round(result.phases.get(current[0], 0.0) + now - current[1], 1)
        result._phase_now = (name, now) if name else None
        return current[0] if current else ""

    def _close_phase(self, result: DownloadResult) -> None:
        """Bring the phase durations up to now (the phase goes on)."""
        current = getattr(result, "_phase_now", None)
        if current:
            self._phase(result, current[0])

    # A few pictures per article, at its decision points: not subscribed, no login
    # entry, a PDF attempt that failed, waiting for the user, a stopped login.
    MAX_SNAPSHOTS = 5

    def _snapshot(self, page: Any, result: DownloadResult | None, why: str) -> None:
        """The page's URL and title, and a small picture of the window with every
        form field masked (never their values), in the article's diagnostics folder."""
        from ..browser import watchdog
        if watchdog.fired:
            return
        if (result is None or len(result.snapshots) >= self.MAX_SNAPSHOTS
                or (self.config.get("supplements") == "with" and len(result.snapshots) >= self.MAX_SNAPSHOTS - 1
                    and not why.startswith("supplements"))):
            return
        url = str(getattr(page, "url", "") or "")
        entry = {"at": datetime.now().strftime("%H:%M:%S"), "why": why, "url": url[:500],
                 "title": self._title(page)[:200]}
        run_dir = getattr(self, "_run_dir", None)
        if run_dir is not None:
            folder = Path(run_dir) / "diagnostics" / safe_name(result.doi)
            path = folder / f"snapshot-{len(result.snapshots) + 1}-{re.sub(r'[^a-z0-9]+', '-', why.lower())[:40]}.jpg"
            from ..page_snapshot import capture_structure, masked_screenshot
            entry.update(capture_structure(page, path.with_suffix(".html"), self.config))
            entry.update(masked_screenshot(page, path))
        result.snapshots.append(entry)
        self._event(result, "snapshot", f"{why} | {url[:160]} | {entry['title'][:80]}")

    def _drop_snapshot_pictures(self, result: DownloadResult) -> None:
        """A successful article keeps its snapshots' URLs and titles, not their
        pictures (the live preview's frames go the same way)."""
        for entry in result.snapshots:
            for key in ("screenshot", "html"):
                artifact = entry.pop(key, None)
                if artifact:
                    Path(artifact).unlink(missing_ok=True)

    def _note_wait(self, result: DownloadResult | None, what: str, started: float, why: str) -> None:
        """A wait of more than ``LONG_WAIT_SEC``: what it waited for and why it ended."""
        took = time.time() - started
        if result is not None and took > self.LONG_WAIT_SEC:
            self._event(result, "wait", f"{what}: {took:.0f} s, ended: {why}")

    def _write_diagnostic(self, page: Any, result: DownloadResult, run_dir: Path) -> None:
        diag_dir = run_dir / "diagnostics" / safe_name(result.doi)
        diag_dir.mkdir(parents=True, exist_ok=True)
        self._close_phase(result)
        if (result.state == "institution_pdf_entitlement_missing"
                and not any(e["state"] == "entitlement_denied" for e in result.events)):
            # The evidence for "no access" (ADR 0012): the page's own words.
            self._event(result, "entitlement_denied", self._denial_line(page))
        # Persist fixed classifications, without changing the live workflow state.
        packet = serialize_download_result({**asdict(result),
            "final_url": getattr(page, "url", result.final_url)}, diagnostic=True)
        import platform
        packet["capture_system"] = platform.system()
        packet["adapter"] = type(self.adapter).__name__
        packet["browser"] = getattr(self, "browser", {})
        from ..browser import watchdog
        stopped = bool(watchdog.fired) or result.state in {
            "browser_unresponsive", "browser_operation_timeout", "user_skipped", "batch_stopped", "user_marked_no_entitlement"}
        if stopped:
            packet["access_state"], packet["access_evidence"] = "unknown", ["probe skipped: item stopped"]
        else:
            try:
                packet["access_state"], packet["access_evidence"] = self._access_state(page)
            except Exception as exc:
                packet["access_state"], packet["access_evidence"] = "unknown", [f"probe failed: {type(exc).__name__}"]
        packet_path = diag_dir / "diagnostic.json"
        if not stopped and result.reason != "publisher_access_blocked":
            from ..page_snapshot import capture_structure, masked_screenshot
            pages = []
            try:
                pages = [p for p in list(page.context.pages) if p is not page and not p.is_closed()][:2]
            except Exception:
                pass  # The working page is still captured; no other tab is known.
            packet["pages"] = []
            for index, tab in enumerate([page] + pages):
                stem = "screenshot" if index == 0 else f"screenshot-tab{index}"
                row = {"url": str(getattr(tab, "url", "") or ""), "title": self._title(tab)[:200], "why": "download failed"}
                row.update(capture_structure(tab, diag_dir / f"{stem}.html", self.config))
                if self.adapter.diagnostic_screenshots:
                    row.update(masked_screenshot(tab, diag_dir / f"{stem}.png"))
                packet["pages"].append(row)
        packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        result.diagnostic_path = str(packet_path)

    def _denial_line(self, page: Any) -> str:
        """The page's denial (access_rules.denial_evidence) for the diagnostic, and
        why it is the school's: ``denial line: "<the page's words>" (after this
        item's school login)``."""
        try:
            snap = self._access_snapshot(page)
        except Exception:
            return ""  # a probe for the diagnostic; the failure is reported either way
        evidence, named = access_rules.denial_evidence(snap.url, snap.lines, snap.probe)
        if not evidence:
            return ""
        try:
            whose = ("after this item's school login" if self._school_login_done()
                     else "the institution's session" if self._institution_session(page, snap) == "ours"
                     else "names the configured school" if named and self._names_configured_school(named) else "")
        except Exception:
            whose = ""
        return f"{evidence} ({whose})" if whose else evidence

    def _write_complete_artifacts(
        self,
        records: list[PaperRecord],
        results: list[DownloadResult],
        run_dir: Path,
        *,
        missing_reasons: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        complete_dir = run_dir / "complete"
        pdf_dir = complete_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        missing_reasons = missing_reasons or {}
        result_by_doi = {result.doi.lower(): result for result in results if result.ok}
        manifest: list[dict[str, Any]] = []

        for record in records:
            result = result_by_doi.get(record.doi.lower())
            item = {
                "doi": record.doi,
                "published": record.published,
                "title": record.title,
                "status": "missing",
                "reason": missing_reasons.get(record.doi.lower(), ""),
                "pdf_path": "",
                "size_bytes": 0,
                "text_length": 0,
                "verified_match": False,
            }
            if result and result.pdf_path:
                src = Path(result.pdf_path)
                dst = pdf_dir / src.name
                if src.exists():
                    dst.write_bytes(src.read_bytes())
                    text = pdf_extractor.extract_text(dst)
                    verified_match = self._text_matches_record(text, record, fallback_title=result.title)
                    item.update(
                        {
                            "status": "success" if verified_match else "unverified",
                            "reason": result.reason,
                            "pdf_path": str(dst),
                            "size_bytes": dst.stat().st_size,
                            "text_length": len(text or ""),
                            "verified_match": verified_match,
                        }
                    )
            manifest.append(item)

        complete_dir.mkdir(parents=True, exist_ok=True)
        # Keep the generated local PDF path for the batch consumer. Never copy
        # observed browser titles, URLs, exception text, or event payloads here.
        public_manifest = []
        for item in manifest:
            packet = serialize_download_result(item, include_events=False)
            packet["pdf_path"] = item["pdf_path"]
            public_manifest.append(packet)
        (complete_dir / "manifest.json").write_text(
            json.dumps(public_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (complete_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            fields = list(serialize_download_result({}, include_events=False)) + ["pdf_path"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(public_manifest)

        return {
            "count": len(manifest),
            "success": sum(1 for item in manifest if item["status"] == "success"),
            "missing": sum(1 for item in manifest if item["status"] == "missing"),
            "unverified": sum(1 for item in manifest if item["status"] == "unverified"),
            "verified_match": sum(1 for item in manifest if item["verified_match"]),
            "pdf_dir": str(pdf_dir),
            "manifest": str(complete_dir / "manifest.csv"),
        }
