"""Runs over many records: workers, shared login cookies, result files.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import shutil
import threading
import time
from urllib.parse import urlparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import parse_proxy_pool
from ..download_diagnostics import serialize_download_result, serialize_download_summary
from .. import progress_reporter
from .batch_common import (
    DownloadResult,
    IP_BLOCK_STOP_THRESHOLD,
    MAX_BROWSER_CONCURRENCY,
    PaperRecord,
    RETRYABLE_REASONS,
    _PagePool,
    _resolve_profile_dir,
    logger,
)


class RunsMixin:
    """Runs over many records: workers, shared login cookies, result files."""

    def run_records(
        self,
        records: list[PaperRecord],
        run_dir: str | Path,
        *,
        retry_failed: bool = True,
        target_verified: int | None = None,
        attempt_cache: str | Path | None = None,
        skip_attempted: bool = False,
        concurrency: int = 1,
    ) -> dict[str, Any]:
        """Download all records and write summary/manifest artifacts."""
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        self._progress_active = True
        progress_reporter.start_task(
            f"出版商下载 · {self.profile.name}", total=len(records),
        )
        target = target_verified if target_verified and target_verified > 0 else None
        worker_count = min(max(1, int(concurrency or 1)), MAX_BROWSER_CONCURRENCY)
        if target:
            worker_count = 1
        attempt_cache_path = Path(attempt_cache) if attempt_cache else run_path / "attempts.jsonl"
        (run_path / "records.json").write_text(
            json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_path / "dois.txt").write_text(
            "\n".join(r.doi for r in records) + "\n",
            encoding="utf-8",
        )

        missing_reasons: dict[str, str] = {}
        records_to_run = records
        cached_skipped = 0
        if skip_attempted:
            attempted_dois = self._read_attempted_dois(attempt_cache_path)
            records_to_run = []
            for record in records:
                if record.doi.lower() in attempted_dois:
                    cached_skipped += 1
                    missing_reasons[record.doi.lower()] = "skipped_cached_attempt"
                else:
                    records_to_run.append(record)
            if cached_skipped:
                progress_reporter.update(
                    done=cached_skipped, phase="跳过已尝试",
                )

        self._ip_block_stopped = False  # reset; set by _run_once(_parallel) on trip
        self._proxy_blocked = []         # reset; set by _run_once_parallel_rotating

        restart_every = max(0, int(self.config.get("browser_restart_every", 0) or 0))
        if restart_every and len(records_to_run) > restart_every:
            segments = [
                records_to_run[i : i + restart_every]
                for i in range(0, len(records_to_run), restart_every)
            ]
            logger.info(
                "browser_restart_every=%d: %d records in %d segments "
                "(browser context recycled between segments, cookies handed over)",
                restart_every,
                len(records_to_run),
                len(segments),
            )
        else:
            segments = [records_to_run]

        results: list[DownloadResult] = []
        for seg_index, segment in enumerate(segments):
            if target and self._count_verified(results) >= target:
                break  # cumulative verified count already reached the target
            if self._ip_block_stopped:
                break  # a previous segment tripped the IP-block auto-stop
            logger.info("Segment %d/%d: %d records", seg_index + 1, len(segments), len(segment))
            results.extend(
                self._run_once(
                    segment,
                    run_path / "primary",
                    target_verified=target,
                    attempt_cache_path=attempt_cache_path,
                    phase="primary",
                    concurrency=worker_count,
                )
            )
        primary_ip_blocked = self._ip_block_stopped
        primary_counts = self._count_results(results)
        target_reached = bool(target and self._count_verified(results) >= target)
        if target_reached and len(results) < len(records_to_run):
            for record in records_to_run[len(results):]:
                missing_reasons[record.doi.lower()] = "target_verified_reached"

        failed_records = [
            record
            for record, result in zip(records, results)
            if result.status == "failed" and result.reason in RETRYABLE_REASONS
        ]

        retry_results: list[DownloadResult] = []
        # Skip the retry pass entirely when the primary pass was auto-stopped
        # for an IP block — retrying against a still-blocked IP only deepens it.
        retry_skipped_ip_block = primary_ip_blocked
        if retry_failed and failed_records and not target_reached and not retry_skipped_ip_block:
            remaining_target = target - self._count_verified(results) if target else None
            retry_results = self._run_once(
                failed_records,
                run_path / "retry",
                target_verified=remaining_target,
                attempt_cache_path=attempt_cache_path,
                phase="retry",
                concurrency=worker_count,
            )
            retry_by_doi = {result.doi.lower(): result for result in retry_results if result.ok}
            results = [
                retry_by_doi.get(result.doi.lower(), result)
                for result in results
            ]
            target_reached = bool(target and self._count_verified(results) >= target)

        summary = self._write_complete_artifacts(records, results, run_path, missing_reasons=missing_reasons)
        summary["publisher"] = self.profile.name
        summary["primary"] = primary_counts
        summary["final"] = self._count_results(results)
        summary["retry_attempted"] = len(failed_records)
        summary["retry_success"] = sum(1 for result in retry_results if result.ok)
        summary["target_verified"] = target
        summary["target_reached"] = target_reached
        summary["skipped"] = max(0, len(records) - len(results) - cached_skipped)
        summary["cached_skipped"] = cached_skipped
        summary["attempt_cache"] = str(attempt_cache_path)
        summary["concurrency"] = worker_count
        summary["browser_profile_dir"] = str(_resolve_profile_dir(self.config))
        # Surface auto-stop so callers (CLI/MCP) can tell a halt from a clean
        # finish. ip_block_count is how many records came back ip_blocked in the
        # primary pass (the trip trigger).
        ip_blocked_total = sum(1 for r in results if r.reason == "ip_blocked")
        summary["auto_stopped"] = bool(retry_skipped_ip_block)
        summary["stop_reason"] = "ip_blocked" if retry_skipped_ip_block else ""
        summary["ip_blocked_count"] = ip_blocked_total
        # Proxy rotation fields (empty when proxy_pool is not configured).
        summary["proxy_pool"] = parse_proxy_pool(self.config.get("proxy_pool", ""))
        summary["proxy_blocked"] = list(dict.fromkeys(self._proxy_blocked))  # deduplicate
        (run_path / "summary.json").write_text(
            json.dumps(serialize_download_summary(summary), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        progress_reporter.finish()
        self._progress_active = False
        return summary

    def _report_progress(self, result: DownloadResult, phase: str) -> None:
        if getattr(self, "_progress_active", False) and phase == "primary":
            progress_reporter.advance(
                result.ok, current=result.doi, phase="浏览器下载",
            )

    def _run_once(
        self,
        records: list[PaperRecord],
        run_dir: Path,
        *,
        target_verified: int | None = None,
        attempt_cache_path: Path | None = None,
        phase: str = "primary",
        concurrency: int = 1,
    ) -> list[DownloadResult]:
        run_dir.mkdir(parents=True, exist_ok=True)
        worker_count = min(max(1, int(concurrency or 1)), len(records) or 1)
        if worker_count > 1 and not target_verified:
            return self._run_once_parallel(
                records,
                run_dir,
                worker_count=worker_count,
                attempt_cache_path=attempt_cache_path,
                phase=phase,
            )

        results: list[DownloadResult] = []
        verified_count = 0
        consecutive_ip_blocks = 0

        context = self._launch_context()
        self._apply_handoff_cookies(context)
        try:
            for record in records:
                result = self.fetch_one(context, record, run_dir)
                results.append(result)
                self._report_progress(result, phase)
                if result.ok and result.verified_match:
                    verified_count += 1
                self._append_attempt(attempt_cache_path, result, phase)
                self._write_results(run_dir / "summary_partial.json", results)
                # Auto-stop on consecutive IP blocks (serial mirror of the
                # parallel path's stop_event logic).
                if result.reason == "ip_blocked":
                    consecutive_ip_blocks += 1
                    if consecutive_ip_blocks >= IP_BLOCK_STOP_THRESHOLD:
                        self._ip_block_stopped = True
                        break
                else:
                    consecutive_ip_blocks = 0
                if target_verified and verified_count >= target_verified:
                    break
        finally:
            self._export_handoff_cookies(context)
            try:
                context.close()
            except Exception:
                pass

        self._write_results(run_dir / "summary.json", results)
        return results

    def _run_once_parallel(
        self,
        records: list[PaperRecord],
        run_dir: Path,
        *,
        worker_count: int,
        attempt_cache_path: Path | None = None,
        phase: str = "primary",
    ) -> list[DownloadResult]:
        """Run downloads in parallel using a shared browser context + page pool.

        Architecture:
        - ONE persistent context (preserves cookies, localStorage, sessionStorage,
          HTTP connections, TLS sessions — the complete login state)
        - N worker threads, each borrows a page from the pool, downloads, returns it
        - All pages share the same context = same identity, no re-login needed

        This is the correct model: login state is NOT just cookies. It includes
        localStorage tokens, sessionStorage, connection pools, and TLS sessions.
        Exporting cookies to a new context is like "switching devices" — some
        publishers reject that. Sharing the context keeps the same device identity.
        """
        # ── proxy-pool rotation branch ──
        proxies = parse_proxy_pool(self.config.get("proxy_pool", ""))
        if proxies:
            return self._run_once_parallel_rotating(
                records, run_dir, proxies=proxies,
                worker_count=worker_count,
                attempt_cache_path=attempt_cache_path, phase=phase,
            )

        run_dir.mkdir(parents=True, exist_ok=True)
        profile_root = run_dir / "worker-profiles"
        source_profile = _resolve_profile_dir(self.config)
        profile_dir = self._prepare_worker_profile(source_profile, profile_root / f"{phase}-shared")

        results_by_index: dict[int, DownloadResult] = {}
        results_lock = threading.Lock()
        attempt_lock = threading.Lock()

        # Auto-stop state: once IP_BLOCK_STOP_THRESHOLD consecutive records come
        # back ip_blocked, the remaining records are skipped. A blocked IP does
        # not unblock mid-run, so churning the rest only deepens the block.
        stop_event = threading.Event()
        ip_block_count = {"n": 0}
        count_lock = threading.Lock()

        def record_result(index: int, result: DownloadResult) -> None:
            with results_lock:
                results_by_index[index] = result
                partial = [results_by_index[item_index] for item_index in sorted(results_by_index)]
                self._write_results(run_dir / "summary_partial.json", partial)
            with attempt_lock:
                self._append_attempt(attempt_cache_path, result, phase)
            self._report_progress(result, phase)
            # Escalate to a hard stop after N consecutive IP blocks.
            if result.reason == "ip_blocked":
                with count_lock:
                    ip_block_count["n"] += 1
                    tripped = ip_block_count["n"] >= IP_BLOCK_STOP_THRESHOLD
                if tripped and not stop_event.is_set():
                    stop_event.set()
                    self._ip_block_stopped = True
            elif result.ok or result.reason:
                # A success or any non-block failure resets the streak — only
                # *consecutive* blocks should trip the stop.
                with count_lock:
                    ip_block_count["n"] = 0

        # Single shared context — login state fully preserved
        context = self._launch_context(profile_dir=profile_dir)
        self._apply_handoff_cookies(context)
        page_pool = _PagePool(context, max_size=worker_count)

        def run_worker(items: list[tuple[int, PaperRecord]]) -> None:
            for item_index, record in items:
                if stop_event.is_set():
                    break  # IP block tripped — skip the rest of this chunk
                page = page_pool.acquire()
                try:
                    record_result(item_index, self.fetch_one(page, record, run_dir))
                finally:
                    page_pool.release(page)

        indexed_records = list(enumerate(records))
        chunks = [indexed_records[i::worker_count] for i in range(worker_count)]

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(run_worker, chunk) for chunk in chunks if chunk]
            for future in as_completed(futures):
                future.result()

        page_pool.close_all()
        self._export_handoff_cookies(context)
        try:
            context.close()
        except Exception:
            pass

        results = [results_by_index[i] for i in range(len(records)) if i in results_by_index]
        self._write_results(run_dir / "summary.json", results)
        return results

    def _run_once_parallel_rotating(
        self,
        records: list[PaperRecord],
        run_dir: Path,
        *,
        proxies: list[str],
        worker_count: int,
        attempt_cache_path: Path | None = None,
        phase: str = "primary",
    ) -> list[DownloadResult]:
        """Run downloads across multiple per-proxy contexts (IP rotation).

        - Logs in once, exports cookies, injects into each proxy context.
        - Round-robin assigns records to proxies.
        - Per-proxy IP-block tracking: when a proxy hits the block threshold,
          it's excluded; when all proxies are excluded the run auto-stops.
        """
        run_dir.mkdir(parents=True, exist_ok=True)
        profile_root = run_dir / "worker-profiles"
        source_profile = _resolve_profile_dir(self.config)

        # ── 1. shared cookies (login once, reuse across proxies) ──
        login_profile = profile_root / f"{phase}-login"
        cookies = self._login_and_export_cookies(run_dir, login_profile)

        # ── 2. per-proxy context + page-pool ──
        class _ProxySlot:
            __slots__ = ("proxy", "context", "pool", "blocked", "ip_blocks")
            def __init__(self, proxy: str, context, pool):
                self.proxy = proxy
                self.context = context
                self.pool = pool
                self.blocked = False
                self.ip_blocks = 0

        slots: list[_ProxySlot] = []
        self._proxy_blocked = []  # populated as proxies are excluded
        for i, proxy in enumerate(proxies):
            p_dir = self._prepare_worker_profile(source_profile, profile_root / f"{phase}-p{i}")
            ctx = self._launch_context(profile_dir=p_dir, proxy=proxy)
            if cookies:
                self._inject_cookies(ctx, cookies)
            pool = _PagePool(ctx, max_size=max(1, max(1, worker_count) // len(proxies) + 1))
            slots.append(_ProxySlot(proxy, ctx, pool))

        # ── 3. shared orchestrator state ──
        results_by_index: dict[int, DownloadResult] = {}
        results_lock = threading.Lock()
        attempt_lock = threading.Lock()
        rr_lock = threading.Lock()
        rr_index = 0
        # No global consecutive-block counter here: in rotation mode each proxy
        # is tracked independently (slot.ip_blocks). The whole run only stops
        # when ALL proxies are excluded — that's the point of having a pool.
        stop_event = threading.Event()

        def _pick_slot() -> _ProxySlot | None:
            nonlocal rr_index
            with rr_lock:
                active = [s for s in slots if not s.blocked]
                if not active:
                    return None
                slot = active[rr_index % len(active)]
                rr_index += 1
                return slot

        def _record(index: int, result: DownloadResult, slot: _ProxySlot | None) -> None:
            with results_lock:
                results_by_index[index] = result
                part = [results_by_index[ii] for ii in sorted(results_by_index)]
                self._write_results(run_dir / "summary_partial.json", part)
            with attempt_lock:
                self._append_attempt(attempt_cache_path, result, phase)
            self._report_progress(result, phase)

            if result.reason == "ip_blocked":
                if slot is not None:
                    slot.ip_blocks += 1
                    if slot.ip_blocks >= IP_BLOCK_STOP_THRESHOLD and not slot.blocked:
                        slot.blocked = True
                        self._proxy_blocked.append(slot.proxy)
                        # If every proxy is now blocked, stop the whole run.
                        if all(s.blocked for s in slots) and not stop_event.is_set():
                            stop_event.set()
                            self._ip_block_stopped = True
            elif result.ok or result.reason:
                # A success (or non-block failure) resets this proxy's streak.
                if slot is not None:
                    slot.ip_blocks = 0

        def _worker(chunk: list[tuple[int, PaperRecord]]) -> None:
            for item_index, record in chunk:
                if stop_event.is_set():
                    break
                slot = _pick_slot()
                if slot is None:          # all proxies excluded
                    break
                page = slot.pool.acquire()
                try:
                    _record(item_index, self.fetch_one(page, record, run_dir), slot)
                finally:
                    slot.pool.release(page)

        # ── 4. execution ──
        indexed = list(enumerate(records))
        chunks = [indexed[i::worker_count] for i in range(worker_count)]
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker, c) for c in chunks if c]
            for future in as_completed(futures):
                future.result()

        # ── 5. cleanup ──
        for slot in slots:
            slot.pool.close_all()
            try:
                slot.context.close()
            except Exception:
                pass

        results = [results_by_index[i] for i in range(len(records)) if i in results_by_index]
        self._write_results(run_dir / "summary.json", results)
        return results

    def _prepare_worker_profile(self, source: Path, target: Path) -> Path:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            target.mkdir(parents=True, exist_ok=True)
            return target
        ignored_names = {
            "SingletonCookie",
            "SingletonLock",
            "SingletonSocket",
            "BrowserMetrics",
            "Cache",
            "Code Cache",
            "Crashpad",
            "DawnCache",
            "GPUCache",
            "GrShaderCache",
            "ShaderCache",
        }

        def ignore(_directory: str, names: list[str]) -> set[str]:
            return {name for name in names if name in ignored_names}

        try:
            shutil.copytree(source, target, ignore=ignore)
        except Exception:
            target.mkdir(parents=True, exist_ok=True)
        return target

    def _login_and_export_cookies(self, run_dir: Path, profile_dir: Path) -> list[dict]:
        """Login once and export cookies for all workers to share.

        This ensures the user only needs to complete SSO/login once,
        while each worker still gets its own browser fingerprint.

        Returns list of cookies that can be injected via context.add_cookies().
        """
        cookie_cache = run_dir / "shared_cookies.json"

        # Check for cached cookies from previous run
        if cookie_cache.exists():
            try:
                cookies = json.loads(cookie_cache.read_text(encoding="utf-8"))
                if cookies and isinstance(cookies, list):
                    self._event(None, "shared_cookies_loaded", f"{len(cookies)} cookies from cache")
                    return cookies
            except Exception:
                pass

        # Launch a dedicated login context
        self._event(None, "login_phase_start", "Launching browser for authentication...")
        context = self._launch_context(profile_dir=profile_dir)
        try:
            # Navigate to the publisher's institutional login page
            login_url = self._get_login_url()
            if not login_url:
                return []

            page = context.new_page()
            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                # Wait for user to complete login
                login_timeout = self.login_timeout_sec
                self._event(None, "login_waiting", f"Complete login in browser (timeout={login_timeout}s)")
                print(f"\n  🔐 Complete login in the browser window")
                print(f"     Timeout: {login_timeout}s")
                print(f"     Cookies will be shared with all download workers\n")

                deadline = time.time() + login_timeout
                while time.time() < deadline:
                    time.sleep(1)
                    try:
                        current_url = page.url
                    except Exception:
                        break
                    # Check if login is complete
                    if self._looks_like_logged_in(page, current_url):
                        break

                # Export cookies
                cookies = context.cookies()
                if cookies:
                    cookie_cache.write_text(
                        json.dumps(cookies, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    self._event(None, "shared_cookies_exported", f"{len(cookies)} cookies saved")
                    print(f"  ✅ Login successful! Exported {len(cookies)} cookies for {len(cookies)} workers")
                return cookies
            finally:
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            try:
                context.close()
            except Exception:
                pass

    def _inject_cookies(self, context: Any, cookies: list[dict]) -> None:
        """Inject previously exported cookies into a context (Playwright add_cookies).

        Used by the IP-rotation path: login once in one context, then spread the
        session cookies across per-proxy contexts so each can reuse the login
        without the user re-authenticating. ``add_cookies`` is a no-op when the
        context is already authenticated for those domains.
        """
        if not cookies:
            return
        try:
            context.add_cookies(cookies)
        except Exception as exc:
            self._event(None, "cookie_inject_failed", f"{type(exc).__name__}: {exc}")

    def _get_login_url(self) -> str:
        """The page the proxy pool's one login per exit address opens: the profile's
        or its adapter's ``login_url``, else the publisher's own site (its article
        address, else its first domain). The upstream guess "https://www.<name>.com/"
        was mostly another site; the step itself is kept (the user, 2026-11-02)."""
        profile = self.profile
        # Profiles carry no login_url field today; an extension profile may add one.
        login_url = getattr(profile, "login_url", "") or self.adapter.login_url()
        if login_url:
            return login_url
        host = urlparse(str(getattr(profile, "article_url_template", "") or "")).hostname or ""
        if not host or host in ("doi.org", "dx.doi.org"):
            host = next(iter(getattr(profile, "base_domains", ()) or ()), "")
        return f"https://{host}/" if host else ""

    def _looks_like_logged_in(self, page: Any, current_url: str) -> bool:
        """Check if the page looks like a successful login."""
        url_lower = current_url.lower()
        # If we're no longer on a login/CAS page, consider it done
        if not any(kw in url_lower for kw in ("login", "cas", "sso", "signin", "sign-in")):
            return True
        # Check for SSO-specific indicators
        try:
            title = (page.title() or "").lower()
            if any(kw in title for kw in ("登录成功", "welcome", "dashboard")):
                return True
        except Exception:
            pass
        return False

    def _save_publisher_session(self, page: Any, result: DownloadResult) -> None:
        if not self.profile.base_domains:
            return
        try:
            from ..browser.cookies import merge_cookies, PUBLISHER_DOMAINS
            # Declared hosts admit new publishers; known publisher parents
            # retain legitimate cookies such as .acs.org for pubs.acs.org.
            domains = set(self.profile.base_domains)
            domains.update(domain for domain in PUBLISHER_DOMAINS
                           if any(host == domain or host.endswith("." + domain)
                                  for host in self.profile.base_domains))
            merge_cookies(page.context.cookies(), self.config, publisher_domains=tuple(domains))
            self._event(result, "publisher_session_saved")
        except Exception:
            # The PDF is still valid, but reuse must not silently claim success.
            self._event(result, "publisher_session_save_failed")
            logger.warning("publisher_session_save_failed")

    def _apply_handoff_cookies(self, context: Any) -> None:
        """Inject cookies exported from the previous context (segment restarts).

        Uses getattr defensively: unit tests build downloaders via ``__new__``
        without running ``__init__``.
        """
        cookies = getattr(self, "_handoff_cookies", None)
        if not cookies:
            return
        try:
            context.add_cookies(cookies)
            logger.info("Restored %d cookies from previous browser context", len(cookies))
        except Exception as exc:
            logger.warning("Cookie hand-off injection failed: %s", exc)
        finally:
            self._handoff_cookies = None

    def _export_handoff_cookies(self, context: Any) -> None:
        """Snapshot cookies before a context closes so the next one stays logged in."""
        try:
            self._handoff_cookies = context.cookies()
        except Exception:
            self._handoff_cookies = None

    @staticmethod
    def _write_results(path: Path, results: list[DownloadResult]) -> None:
        summary = {
            "count": len(results),
            "success": sum(1 for result in results if result.status == "success"),
            "partial": sum(1 for result in results if result.status == "partial"),
            "failed": sum(1 for result in results if result.status == "failed"),
            "results": [serialize_download_result(result) for result in results],
        }
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _count_results(results: list[DownloadResult]) -> dict[str, int]:
        return {
            "count": len(results),
            "success": sum(1 for result in results if result.status == "success"),
            "failed": sum(1 for result in results if result.status == "failed"),
        }

    @staticmethod
    def _count_verified(results: list[DownloadResult]) -> int:
        return sum(1 for result in results if result.ok and result.verified_match)

    @staticmethod
    def _read_attempted_dois(path: Path) -> set[str]:
        if not path.exists():
            return set()
        attempted: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            doi = str(item.get("doi", "")).strip().lower()
            if doi:
                attempted.add(doi)
        return attempted

    @staticmethod
    def _append_attempt(path: Path | None, result: DownloadResult, phase: str) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        item = serialize_download_result(result, phase=phase, include_events=False)
        item["created_at"] = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
