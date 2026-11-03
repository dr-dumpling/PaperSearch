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
from .batch_common import DownloadResult, PaperRecord, safe_name


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

    @staticmethod
    def _title(page: Any) -> str:
        try:
            return str(page.title() or "")
        except Exception:
            return ""

    @staticmethod
    def _body_text(page: Any, limit: int = 2_000) -> str:
        from ..browser.preview import observe_page
        observe_page(page)
        try:
            text = page.locator("body").inner_text(timeout=3_000)
        except Exception:
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
            # Only publish fixed phase text; event details can contain signed URLs.
            report = {
                "article_open": ("打开论文页面", "opening_article"),
                "sso_start": ("机构登录", "waiting_login"),
                "institution_federation_selected": ("已进入所选机构认证联盟", "waiting_login"),
                "institution_selection_required": ("请在 CARSI 页面自行选择学校并完成登录", "waiting_login"),
                "institution_entry_unresolved": ("官方机构入口尚未确认 CARSI", "waiting_login"),
                "login_state": ("机构登录", "waiting_login"),
                "idp_confirmation_required": ("请在浏览器里确认学校认证页的提示（信息发送同意、使用条款或二次验证）", "waiting_login"),
                "login_attempt_started": ("正在尝试机构登录", "waiting_login"),
                "login_retry_wait": ("机构登录暂未完成，准备重试", "waiting_login"),
                "login_navigation_interrupted": ("登录跳转中断，检查是否可重试", "waiting_login"),
                "login_stopped": ("机构登录未完成", "route_failed"),
                "challenge_manual_wait": ("等待人工安全验证", "waiting_verification"),
                "challenge_wait": ("等待人工安全验证", "waiting_verification"),
                "challenge_resolved": ("安全验证已结束，继续检查页面", "checking_access"),
                "article_access_ready": ("论文页面已就绪，检查正文入口", "checking_access"),
                "publisher_content_error": ("出版社返回内容服务错误", "route_failed"),
                "publisher_access_blocked": ("网站已阻止当前访问，此路径已停止", "route_failed"),
                "pdf_capture_started": ("读取 PDF", "fetching_pdf"),
                "browser_pdf_response_captured": ("PDF 已捕获，正在保存", "pdf_captured"),
                "pdf_saved": ("PDF 已保存，待内容核验", "saved_pending_verification"),
            }.get(state)
            if state == "login_attempt_started" and detail in {"1/3", "2/3", "3/3"}:
                report = (f"机构登录：第 {detail[0]} 次尝试，共 3 次", "waiting_login")
            if state == "login_observed":
                if detail == "verification":
                    report = ("等待人工安全验证", "waiting_verification")
                elif detail == "human_login":
                    report = ("等待在浏览器完成机构登录", "waiting_login")
                else:
                    report = ("检查机构登录页面", "waiting_login")
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
        if result is None or len(result.snapshots) >= self.MAX_SNAPSHOTS:
            return
        url = str(getattr(page, "url", "") or "")
        entry = {"at": datetime.now().strftime("%H:%M:%S"), "why": why, "url": url[:500],
                 "title": self._title(page)[:200]}
        run_dir = getattr(self, "_run_dir", None)
        if run_dir is not None:
            folder = Path(run_dir) / "diagnostics" / safe_name(result.doi)
            path = folder / f"snapshot-{len(result.snapshots) + 1}-{re.sub(r'[^a-z0-9]+', '-', why.lower())[:40]}.jpg"
            try:
                folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path), type="jpeg", quality=50, full_page=False, timeout=3_000,
                                mask=[page.locator("input, textarea, select")])
                entry["screenshot"] = str(path)
            except Exception:
                pass  # the URL and title are kept
        result.snapshots.append(entry)
        self._event(result, "snapshot", f"{why} | {url[:160]} | {entry['title'][:80]}")

    def _drop_snapshot_pictures(self, result: DownloadResult) -> None:
        """A successful article keeps its snapshots' URLs and titles, not their
        pictures (the live preview's frames go the same way)."""
        for entry in result.snapshots:
            picture = entry.pop("screenshot", None)
            if picture:
                Path(picture).unlink(missing_ok=True)

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
        packet["adapter"] = type(self.adapter).__name__
        packet["browser"] = getattr(self, "browser", {})
        try:
            packet["access_state"], packet["access_evidence"] = self._access_state(page)
        except Exception as exc:
            packet["access_state"], packet["access_evidence"] = "unknown", [f"probe failed: {type(exc).__name__}"]
        packet_path = diag_dir / "diagnostic.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.adapter.diagnostic_screenshots and result.reason != "publisher_access_blocked":
            try:
                page.screenshot(path=str(diag_dir / "screenshot.png"), full_page=True)
            except Exception:
                pass
            # Other tabs (a PDF or verification tab) are where the problem usually is.
            try:
                others = [p for p in list(page.context.pages) if p is not page and not p.is_closed()]
            except Exception:
                others = []
            for index, other in enumerate(others[:6], 1):
                try:
                    other.screenshot(path=str(diag_dir / f"screenshot-tab{index}.png"), full_page=False)
                except Exception:
                    pass
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
