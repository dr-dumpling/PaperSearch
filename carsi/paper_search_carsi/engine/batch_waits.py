"""Waiting on the user: human verification, the PDF step's checks, the per-article wait budget.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import inspect
import re
import time
from contextlib import ExitStack
from typing import Any
from urllib.parse import urlparse

from ..entitlements import UserMarkedNoEntitlement
from ..browser import challenge_interaction, challenges, watchdog
from .batch_common import (AWAY_WAIT_SEC, DownloadResult, _IP_BLOCK_STATUS_CODES, _observe_preview)

class UserWaitMixin:
    """Waiting on the user: human verification, the PDF step's checks, the per-article wait budget."""

    def _wait_for_challenge_with_deadline(
        self,
        page: Any,
        result: DownloadResult,
        deadline: float,
    ) -> bool:
        try:
            signature = inspect.signature(self._wait_for_challenge)
        except (TypeError, ValueError):
            return self._wait_for_challenge(page, result)
        accepts_deadline = "deadline" in signature.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
        )
        if accepts_deadline:
            return self._wait_for_challenge(page, result, deadline=deadline)
        return self._wait_for_challenge(page, result)

    # A wait off the school's login page (verification, the publisher's pages and
    # choosers, the PDF step): config ``browser_page_wait_timeout``, else this.
    PAGE_WAIT_SEC = 60

    @property
    def page_wait_sec(self) -> float:
        """How long a wait that is not the user's own login step may last; the
        school's login page has ``login_timeout_sec`` (user's choice, 2026-11-03)."""
        value = (getattr(self, "config", None) or {}).get("browser_page_wait_timeout")
        return self.PAGE_WAIT_SEC if value is None else max(10.0, float(value))

    @staticmethod
    def _visible_text_excerpt(body: str | bytes | None, limit: int = 600) -> str:
        if not body:
            return ""
        if isinstance(body, bytes):
            body = body[:65536].decode("utf-8", errors="ignore")
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body[:65536])
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:limit]

    @staticmethod
    def _is_explicit_block_page(body: str | bytes | None, markers: tuple[str, ...] = ()) -> bool:
        """Only an unmistakable block page ends the route without asking the user:
        "IP address ... blocked", or the site's own words (``markers``, its
        adapter's ``block_page_markers``)."""
        if not body:
            return False
        if isinstance(body, bytes):
            body = body[:8192].decode("utf-8", errors="ignore")
        text = body[:65536].lower()
        return any(marker in text for marker in markers) or ("ip address" in text and "block" in text)

    def _resolve_suspect_block(self, page: Any, result: DownloadResult, captured: dict[str, Any]) -> bool:
        """After a 403/429 on the PDF step, wait for the user before calling it a block.

        Only for an interactive (visible) browser, which the institutional
        bridge always requests; otherwise the old one-shot check applies.

        Publishers (ScienceDirect, Cloudflare-fronted hosts) answer the PDF
        request with a human-verification page. Every open tab is checked; the
        verification tab is brought to the front, the user is asked to
        complete it, and the loop waits until the PDF is captured (success),
        no verification/suspect page is left (the capture loop continues), a
        PDF naming neither DOI nor title came through (saved unconfirmed), or
        the bounded wait ends (only then ``ip_blocked``). Returns False when
        the route must stop.
        """
        suspect = captured.get("suspect_block")
        if not suspect or captured.get("block_reason") or captured.get("bytes"):
            return True
        if not self.require_interactive_browser:
            # Nobody can act in a non-interactive (headless/batch) browser:
            # one look at the tabs, wait only for a recognisable challenge.
            try:
                tabs = [p for p in list(page.context.pages) if not p.is_closed()]
            except Exception:
                tabs = [page]
            for candidate in tabs:
                try:
                    if self._is_challenge_page(candidate):
                        captured["suspect_block"] = None
                        return self._wait_for_challenge(candidate, result)
                except Exception:
                    continue
            captured["block_reason"] = "ip_blocked"
            self._event(result, "ip_blocked_response", suspect)
            return False
        suspect_host = (urlparse(suspect.split(" ", 1)[-1]).hostname or "").lower()
        started = time.time()
        try:
            return self._wait_out_suspect_block(page, result, captured, suspect, suspect_host, started)
        finally:
            self._note_wait(result, f"the PDF step's {suspect[:120]}", started,
                            "pdf" if captured.get("bytes") or captured.get("unconfirmed_pdf")
                            else captured.get("block_reason") or "page changed")

    def _wait_out_suspect_block(self, page: Any, result: DownloadResult, captured: dict[str, Any], suspect: str,
                                suspect_host: str, started: float) -> bool:
        deadline = started + self.page_wait_sec
        activity, activity_owned = self._observe_page_activity(page, result)
        automatic: dict[str, Any] = {}
        interaction = ExitStack()
        manual = False
        state = ""
        reporter = None
        attention_key = f"pdf-step:{id(self)}:{result.doi}"
        try:
            from .. import progress_reporter as reporter
        except Exception:
            reporter = None
        shown = ""  # "verification" | "login" | "unknown"
        verification_tab = None
        fallback = getattr(self, "_fallback_pdf", None)
        try:
            while time.time() < deadline:
                self._check_user_decision(result, page)
                if captured.get("bytes"):
                    self._event(result, "challenge_resolved", "pdf captured while waiting")
                    captured["suspect_block"] = None
                    return True
                if getattr(self, "_fallback_pdf", None) is not fallback:
                    # The verification let the PDF through as a download, and the tab
                    # stays on "Verification successful. Waiting for ..." (Science, a
                    # fresh profile, 2026-11-09). It names neither DOI nor title on its
                    # first pages: the capture ends here and saves it unconfirmed.
                    self._event(result, "challenge_resolved", "pdf arrived while waiting, unconfirmed")
                    captured["suspect_block"] = None
                    captured["unconfirmed_pdf"] = True
                    return False
                try:
                    pages = [p for p in list(page.context.pages) if not p.is_closed()]
                except Exception:
                    pages = [page]
                if not self._is_chromium(page):
                    # Firefox: the 403 was an earlier answer and PDF.js now shows
                    # the article (JAD on ScienceDirect); read it there. A PDF bound
                    # to the citation is known by the capture's own address (Karger's
                    # waited 30 s on an "unknown" page instead, 2026-11-02).
                    for candidate in pages:
                        body = self._viewer_pdf_for_record(candidate, result.doi,
                                                           article_pdf_urls=captured.get("article_pdf_urls"))
                        if body:
                            captured["bytes"], captured["url"] = body, str(candidate.url)
                            self._event(result, "challenge_resolved", "pdf shown in the viewer")
                            captured["suspect_block"] = None
                            return True
                state, tab = "", None
                for candidate in pages:
                    if (urlparse(str(candidate.url or "")).hostname or "").lower() == suspect_host:
                        self._raise_on_publisher_access_blocked(candidate)
                    try:
                        if (self._is_challenge_page(candidate)
                                or (candidate is verification_tab and self._challenge_continues(candidate))):
                            state, tab = "verification", candidate
                            break
                        if self._pdf_step_needs_login(candidate):
                            state = "login" if candidate == page or self._users_login_step(candidate) else "unknown"
                            tab = candidate
                            break
                    except (watchdog.BrowserUnresponsive, UserMarkedNoEntitlement):
                        raise
                    except Exception:
                        continue
                if not state and not automatic and shown not in {"verification", "login"}:
                    for candidate in pages:
                        try:
                            if suspect_host and (urlparse(str(candidate.url or "")).hostname or "").lower() == suspect_host:
                                state, tab = "unknown", candidate
                                break
                        except Exception:
                            continue
                if state == "unknown" and time.time() - started >= self.SUSPECT_UNKNOWN_GRACE_SEC:
                    captured["block_reason"] = "ip_blocked"
                    self._event(result, "ip_blocked_response", "PDF response remained blocked; no verification transition")
                    return False
                if not state:
                    if shown or automatic:
                        self._event(result, "challenge_resolved", f"{shown or 'verification'} page gone")
                    captured["suspect_block"] = None
                    return True  # the capture loop retries the PDF now
                if state == "login" and tab == page:
                    # The PDF request landed on the publisher's login/access
                    # wall in the working tab. Waiting would leave the user to
                    # do it by hand; stop this capture so fetch_one runs the
                    # automated institution login and then retries the PDF.
                    self._event(result, "pdf_step_login_required", str(getattr(page, "url", "") or ""))
                    captured["suspect_block"] = None
                    return False
                if state == "verification":
                    verification_tab = tab
                    self._raise_on_publisher_access_blocked(tab)
                    result._attention_page = tab
                    activity.observe(tab)
                    if not automatic:
                        deadline = min(deadline, self._wait_deadline(result))
                    if not manual and self._automatic_challenge_step(tab, result, automatic, deadline):
                        page.wait_for_timeout(min(1000, max(0, (deadline - time.time()) * 1000)))
                        continue
                activity.automatic_for(0)
                if state == "verification":
                    self._verification_attention(result, deadline)
                result._attention_page = tab
                if state != shown:
                    if state != "verification" and shown == "verification":
                        self._verification_attention(result, None)
                    if state in ("verification", "login"):
                        deadline = min(deadline, self._wait_deadline(result))
                    self._event(result, {"verification": "challenge_manual_wait", "login": "pdf_step_login_wait",
                                         "unknown": "pdf_step_unknown_wait"}[state], f"{state}: {suspect}")
                    # The capsule requests attention; leave desktop focus with
                    # the user until they choose to open the browser themselves.
                    if reporter is not None:
                        try:
                            if shown:
                                reporter.clear_attention(attention_key)
                            if state == "login":
                                reporter.set_attention(attention_key, "请在浏览器窗口完成机构登录",
                                                       current=result.doi, phase="机构登录", deadline=deadline)
                                reporter.report_stage("waiting_login", current=result.doi)
                        except Exception:
                            pass
                    shown = state
                activity.observe(tab)
                activity.check()
                if not manual:
                    interaction.enter_context(watchdog.pause_operation())
                    manual = True
                try:
                    _observe_preview(page)  # what the user is asked to act on
                    page.wait_for_timeout(min(1000, max(0, (deadline - time.time()) * 1000)))
                except (watchdog.BrowserUnresponsive, UserMarkedNoEntitlement):
                    raise
                except Exception:
                    time.sleep(min(1, max(0, deadline - time.time())))
            if state in ("verification", "login"):
                self._wait_ran_out(result)
            if state == "verification":
                # The verification page stayed up: nobody completed it. That
                # is a timeout, not evidence that the publisher blocked us.
                captured["block_reason"] = "challenge_or_viewer_timeout"
                self._event(result, "challenge_unresolved", f"{suspect} | verification not completed")
                return False
            captured["block_reason"] = "ip_blocked"
            self._event(result, "ip_blocked_response", f"{suspect} | no PDF after waiting ({shown or 'nothing shown'})")
            return False
        finally:
            self._verification_attention(result, None)
            activity.automatic_for(0)
            result._attention_page = None
            if activity_owned:
                activity.close()
            interaction.close()
            if shown and reporter is not None:
                try:
                    reporter.clear_attention(attention_key)
                except Exception:
                    pass

    def _check_user_decision(self, result: DownloadResult | None, page: Any = None) -> None:
        """Apply a button the user pressed in the progress window for this paper."""
        if result is None:
            return
        activity = getattr(result, "_page_activity", None)
        if activity is not None and not activity.closed:
            if page is not None:
                activity.observe(page)
        self._capture_reported_issues(page, result)
        try:
            from .. import entitlements
        except Exception:
            return
        try:
            action = entitlements.apply_user_decision(
                result.doi, str(getattr(getattr(self, "profile", None), "name", "") or ""),
                getattr(self, "_item_started", 0.0))
        except UserMarkedNoEntitlement as decision:
            self._event(result, "user_entitlement_decision", str(decision))
            raise
        if action:
            if action == entitlements.SHOW_BROWSER:
                self._show_download_browser(page, result)
                return
            self._event(result, "user_entitlement_decision", action)

    @staticmethod
    def _pdf_step_login_required(result: DownloadResult) -> bool:
        return any(event.get("state") == "pdf_step_login_required" for event in result.events)

    SUSPECT_UNKNOWN_GRACE_SEC = 30

    def _pdf_step_needs_login(self, page: Any) -> bool:
        """The PDF tab shows a login page or an access wall (an offer, a gate, a
        denial) instead of the PDF: the shared access rule's ``out``."""
        return self._looks_logged_out(page)

    _CHALLENGE_BODY_MARKERS = (
        "just a moment", "verify you are human", "checking your browser", "are you a robot",
        "please confirm you are a human", "attention required", "cf-chl", "cf_chl_opt",
        "challenge-platform", "challenges.cloudflare.com", "turnstile", "captcha",
        "人机验证", "安全验证", "请完成验证",
    )

    def _is_ip_block_response(self, status_code: int | None, body_or_text: str | bytes | None) -> bool:
        """Return True if this response looks like a publisher IP block.

        Detects two independent signals so a block is caught whichever path it
        surfaces on:
        - HTTP status 403 (ACS serves its block page with 403) or 429
        - Body text of a block page, e.g. "IP Address Blocked", "your IP
          address has been blocked", or the site's own words (the adapter's
          ``block_page_markers``: ACS's contact mailbox)

        A human-verification page (Cloudflare/Turnstile/captcha) is NOT a
        block even when served with 403/429: the user can complete it in the
        visible window, so the caller must wait for the challenge instead of
        ending the route. ``body_or_text`` may be bytes or str; only a prefix
        is inspected.
        """
        text = ""
        if body_or_text:
            if isinstance(body_or_text, bytes):
                try:
                    text = body_or_text[:8192].decode("utf-8", errors="ignore")
                except Exception:
                    text = ""
            else:
                text = body_or_text[:8192]
        text = text.lower()
        if text and any(marker in text for marker in self._CHALLENGE_BODY_MARKERS):
            return False
        if status_code is not None and status_code in _IP_BLOCK_STATUS_CODES:
            return True
        if not text:
            return False
        if any(marker in text for marker in self.adapter.block_page_markers):
            return True
        # "ip address" near "blocked" covers "IP Address Blocked" and
        # "your IP address has been blocked automatically".
        if "ip address" in text and "block" in text:
            return True
        return False

    @property
    def _user_away(self) -> bool:
        return (getattr(self, "config", None) or {}).get("user_wait") == "short"

    def _user_wait_deadline(self, result: DownloadResult) -> float:
        """One deadline for the verification waits in this article (at the article,
        the PDF step): ``login_timeout_sec`` from the first of them. The school
        login has its own (``_school_login_deadline``)."""
        deadline = getattr(result, "_user_wait_deadline", None)
        if deadline is None:
            deadline = result._user_wait_deadline = time.time() + self.login_timeout_sec
        return deadline

    def _school_login_deadline(self, result: DownloadResult) -> float:
        """The school login's own time: ``login_timeout_sec`` from when this article
        first reaches it, however often it is entered. A verification and the
        program's own steps before it never shorten it (Elsevier: a 22 s
        verification and choosing the school left 1 s of 30 on the school's login
        page, 2026-11-09; OUP's login has had its own since 2026-11-02)."""
        deadline = getattr(result, "_school_login_deadline", None)
        if deadline is None:
            deadline = result._school_login_deadline = time.time() + self.login_timeout_sec
        return deadline

    def _wait_deadline(self, result: DownloadResult, deadline: float | None = None) -> float:
        """End of a wait on the user that starts now, off the school's login page
        (verification pages): the caller's bound, the article's total, the page
        wait, and when the user seems away the short wait."""
        bounds = [self._user_wait_deadline(result), time.time() + self.page_wait_sec]
        if deadline is not None:
            bounds.append(deadline)
        if self._user_away:
            bounds.append(time.time() + AWAY_WAIT_SEC)
        return min(bounds)

    def _wait_ran_out(self, result: DownloadResult) -> None:
        """A wait on the user ended unanswered: the article reports a timeout."""
        if not getattr(result, "_user_wait_expired", False):
            result._user_wait_expired = True
            self._event(result, "user_wait_expired", "short wait" if self._user_away else "")

    def _automatic_challenge_step(self, page: Any, result: DownloadResult,
                                  attempt: dict[str, Any], deadline: float) -> bool:
        """Count dispatched clicks only; reserve time for an observed user step.

        An absent/loading widget stays automatic, including late arrivals. A
        visible widget we cannot operate hands off within the existing budget.
        """
        now = time.time()
        if not attempt:
            attempt.update(started=now, attempts=0, retry_at=now + 2)
            self._event(result, "challenge_wait", "automatic verification check")
        remaining = watchdog.operation_remaining()
        if "handoff_at" not in attempt:
            # Default 60 s wait: look automatically for 30 s and leave 30 s for
            # the user. Short waits retain half; the original deadline is fixed.
            after = float(self.config.get("browser_stall_notify_after", 30))
            budget = max(0, deadline - now)
            if remaining is not None:
                budget = min(budget, max(0, remaining))
            attempt["handoff_at"] = now + min(after, budget / 2)
        result._verification_notify_at = attempt["handoff_at"]
        automatic_end = min(deadline, now + remaining) if remaining is not None else deadline
        activity = getattr(result, "_page_activity", None)
        if activity is not None:
            activity.automatic_for(automatic_end - now)
        if challenge_interaction.needs_manual_verification(page):
            widget = challenge_interaction.verification_widget(page, manual_only=True)
            if widget and not attempt.get("widget"):
                attempt["widget"] = widget  # whose widget the user is asked to complete
                self._event(result, "challenge_observation", f"manual widget: {widget}")
            return False
        if ((attempt["attempts"] >= 3 and now >= attempt["retry_at"])
                or (attempt.get("unavailable") and now >= attempt["handoff_at"])):
            return False
        if now >= automatic_end:
            # No observed user action: the caller ends at its original bound.
            return True
        if now >= attempt["retry_at"] and attempt["attempts"] < 3:
            reasons = []
            outcome = challenge_interaction.click_checkbox(
                page, timeout_ms=min(2500, max(1, int((automatic_end - now) * 1000))),
                checkpoint=lambda: self._check_user_decision(result, page),
                observation=reasons.append,
            )
            reason = ", ".join(dict.fromkeys(reasons)) or outcome
            if reason != attempt.get("last_observation"):
                self._event(result, "challenge_observation", reason)
                attempt["last_observation"] = reason
            attempt["unavailable"] = outcome == "unavailable" and (not reasons or any(
                value.startswith(("actionability_timeout", "unsupported_geometry_or_title", "multiple_controls"))
                for value in reasons))
            attempt["retry_at"] = time.time() + (3 if outcome != "absent" else 1)
            if outcome == "clicked":
                attempt["attempts"] += 1
                if activity is not None:
                    activity.progress(page)
                self._event(result, "challenge_interaction",
                            f"checkbox clicked; attempt {attempt['attempts']}/3; awaiting verification")
        return True

    def _verification_attention(self, result: DownloadResult, deadline: float | None) -> None:
        from .. import progress_reporter
        key = f"verification:{id(self)}:{result.doi}"
        if deadline is None:
            if getattr(result, "_verification_attention", False):
                progress_reporter.clear_attention(key)
                progress = progress_reporter.read_state() or {}
                if progress.get("stage") == "waiting_verification":
                    progress_reporter.update(stage="checking_access", phase="安全验证等待已结束，正在检查页面")
            result._verification_attention = False
        elif time.time() < getattr(result, "_verification_notify_at", 0):
            return
        elif not getattr(result, "_verification_attention", False):
            progress_reporter.set_attention(key, "自动验证尚未完成，请在浏览器中检查并完成验证",
                                           current=result.doi, phase="安全验证", deadline=deadline)
            progress_reporter.report_stage("waiting_verification", current=result.doi)
            result._verification_attention = True
        else:
            progress_reporter.update_attention_deadline(key, deadline)

    def _wait_for_challenge(self, page: Any, result: DownloadResult, *, deadline: float | None = None) -> bool:
        """Wait while a verification page is up, until ``_wait_deadline``."""
        interaction = ExitStack()
        activity, activity_owned = self._observe_page_activity(page, result)
        automatic: dict[str, Any] = {}
        manual = False
        wait_interval_sec = 1  # a cleared verification goes on within a second
        started, phase_before = time.time(), ""
        verification_wait = None
        verification_deadline = None
        try:
            waited = False
            state_before = result.state
            checks = 0
            while True:
                self._check_user_decision(result, page)
                # While the interstitial is up, look only at title and URL.
                shell = self._challenge_shell(page)
                if not shell:
                    self._raise_on_publisher_access_blocked(page)
                if shell or self._is_challenge_page(page) or (waited and self._challenge_continues(page)):
                    if not waited:
                        deadline = self._wait_deadline(result, deadline)
                        started, phase_before = time.time(), self._phase(result, "verification")
                    waited = True
                    result.state = "challenge_or_viewer_timeout"
                    if verification_wait is not None:
                        verification_wait.observe(page, True)
                        deadline = verification_wait.deadline
                        self._verification_attention(result, deadline)
                        from .. import progress_reporter
                        progress_reporter.update_attention_deadline(
                            f"verification:{id(self)}:{result.doi}", None if verification_wait.paused else deadline)
                    if time.time() >= deadline:
                        break
                    result._attention_page = page
                    auto_pending = not manual and self._automatic_challenge_step(page, result, automatic, deadline)
                    if not auto_pending:
                        activity.automatic_for(0)
                    activity.check()
                    if not auto_pending and not manual:
                        result._attention_page = page
                        interaction.enter_context(watchdog.pause_operation())
                        manual = True
                        from .login_wait import LoginWait
                        verification_deadline = deadline
                        verification_wait = result._verification_wait = LoginWait(deadline, time.time)
                        verification_wait.observe(page, True)
                        self._verification_attention(result, deadline)
                        self._event(result, "challenge_manual_wait", "complete verification in visible browser")
                        if not any(s["why"] == "waiting for the user: verification" for s in result.snapshots):
                            self._snapshot(page, result, "waiting for the user: verification")
                    checks += 1
                    self._event(result, "challenge_wait", f"{'manual' if manual else 'automatic'} {checks}")
                    # Pump browser events while the user completes verification.
                    # Plain sleep can leave sync-API navigation state stale.
                    wait_ms = min(wait_interval_sec * 1000, max(0, (deadline - time.time()) * 1000))
                    if wait_ms <= 0:
                        break
                    _observe_preview(page)  # the verification page, for anyone checking in
                    remaining = watchdog.operation_remaining()
                    if remaining is not None and wait_ms >= remaining * 1000:
                        # No room for another polling interval. A scheduled
                        # delay running into the deadline is not a driver hang.
                        raise watchdog.BrowserBudgetExhausted(
                            "article page budget exhausted before next verification poll")
                    page.wait_for_timeout(wait_ms)
                    continue
                if waited:
                    # A completed verification is not a timeout (a later
                    # step, e.g. supplements, would skip the article page).
                    result.state = state_before
                    self._event(result, "challenge_resolved", getattr(page, "url", ""))
                return True
            self._raise_on_publisher_access_blocked(page)
            passed = not (self._is_challenge_page(page) or (waited and self._challenge_continues(page)))
            if passed:
                result.state = state_before
            else:
                self._wait_ran_out(result)
            return passed
        finally:
            self._verification_attention(result, None)
            activity.automatic_for(0)
            if verification_wait is not None:
                excluded = max(0, verification_wait.close() - verification_deadline)
                outer_wait = getattr(result, "_login_wait", None)
                if outer_wait is not None:
                    if not outer_wait.paused:
                        outer_wait.exclude_elapsed(excluded)
                elif isinstance(getattr(result, "_user_wait_deadline", None), (float, int)):
                    result._user_wait_deadline += excluded
                result._verification_wait = None
            interaction.close()
            if waited:
                self._phase(result, phase_before or "open")
                self._note_wait(result, "verification", started, "passed" if result.state != "challenge_or_viewer_timeout"
                                else "not completed")
            if activity_owned:
                activity.close()
            if getattr(result, "_attention_page", None) is page:
                result._attention_page = None

    def _challenge_continues(self, page: Any) -> bool:
        # Only after a recognized challenge: the outer page can change title
        # before its second, user-operated prompt is gone.
        return (challenges.continues_manual_challenge(self._title(page))
                or challenge_interaction.has_visible_recaptcha(page))

    def _challenge_shell(self, page: Any) -> bool:
        """Read only URL/title while a verification interstitial is active."""
        try:
            url = str(getattr(page, "url", "") or "")
        except Exception:
            url = ""
        return challenges.looks_like_challenge(url, self._title(page))

    def _is_challenge_page(self, page: Any) -> bool:
        """Apply engine block precedence before the independent recogniser.

        Read lazily: an interstitial or crawl-prevention URL needs no body read;
        an explicit publisher block must never turn into a verification wait.
        """
        if self._challenge_shell(page):
            return True
        if self._publisher_access_blocked(page):
            return False
        if challenges.is_challenge_path(str(getattr(page, "url", "") or "")):
            return True
        title = self._title(page)
        return (challenges.has_challenge_text(title, self._body_text(page, 1_200))
                or (challenges.continues_manual_challenge(title)
                    and challenge_interaction.is_image_verification(page))
                or self._verification_widget_page(page))

    def _verification_widget_page(self, page: Any) -> bool:
        """Another provider's verification widget makes up the page (reCAPTCHA, hCaptcha,
        sliders; ``challenge_interaction.verification_widget``). Not on the school's own
        sign-in, where a captcha is part of the login the user does."""
        host = (urlparse(str(getattr(page, "url", "") or "")).hostname or "").lower()
        return not self._is_idp_host(host) and bool(challenge_interaction.verification_widget(page))
