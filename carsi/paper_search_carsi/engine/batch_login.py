"""Institution login: the publisher's sign-in entry, a login on another site, SSO, waiting for the login to finish.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from types import SimpleNamespace
from urllib.parse import unquote, urljoin, urlparse

from . import access_rules
from .batch_common import (AWAY_WAIT_SEC, POLL_MS, DownloadResult, PublisherContentError, _is_browser_error,
                           _is_navigation_cut, open_page, pump_until, settle)

# A site without a publisher profile (publishers/site.py) whose article page
# offered no institution entry the shared rules know.
GENERIC_ENTRY_MISSING = "generic_institution_entry_missing"


class LoginMixin:
    """Institution login: the publisher's sign-in entry, a login on another site, SSO, waiting for the login to finish."""

    # While the login waits on a publisher's article page, its PDF is tried this
    # often, and at once when the page comes back from an IdP or a chooser.
    WAIT_PROBE_EVERY_SEC = 15

    def _hold_after_login(self, page: Any, result: DownloadResult) -> None:
        if not self.post_login_hold_sec:
            return
        self._event(result, "post_login_hold", f"{self.post_login_hold_sec}s")
        deadline = time.time() + self.post_login_hold_sec
        while time.time() < deadline:
            if self._is_human_login_page(page):
                self._event(result, "post_login_hold_login_page", getattr(page, "url", ""))
            elif self._looks_logged_out(page):
                self._event(result, "post_login_hold_auth_wall", getattr(page, "url", ""))
            else:
                self._event(result, "post_login_hold_article_access", getattr(page, "url", ""))
            time.sleep(min(5, max(1, int(deadline - time.time()))))

    def _hold_after_run(self, page: Any, result: DownloadResult) -> None:
        if not self.post_run_hold_sec:
            return
        self._event(result, "post_run_hold", f"{self.post_run_hold_sec}s")
        deadline = time.time() + self.post_run_hold_sec
        while time.time() < deadline:
            time.sleep(min(5, max(1, int(deadline - time.time()))))

    def _ensure_login(self, page: Any, result: DownloadResult) -> bool:
        own = self.adapter.ensure_login(page, result)
        if own is not None:
            return own
        open_page(page, result.article_url, timeout_ms=60_000)
        settle(page, 3_000)
        self._wait_past_redirect_page(page, result)
        self._reopen_after_gateway_error(page, result)
        self._raise_on_publisher_content_error(page)
        if not self._wait_for_challenge(page, result):
            return False
        self._wait_for_page_text(page, result)
        # A verification can let the page through to the publisher's redirect
        # page (RSC's silent sign-in check, judged as the article, 2026-11-01).
        self._wait_past_redirect_page(page, result)
        self._raise_on_publisher_content_error(page)
        self._dismiss_cookie_banners(page, result)
        snapshot = self._access_snapshot(page) if not self._is_auth_page(str(page.url)) else None
        if self._institution_pdf_entitlement_missing(page, snapshot=snapshot):
            return False
        if self._pdf_first_unless_signed_out(page, result, snapshot=snapshot):
            return True
        return self._complete_login_from_current_page(page, result)

    def _pdf_first_unless_signed_out(self, page: Any, result: DownloadResult,
                                   snapshot: SimpleNamespace | None = None) -> bool:
        """True unless the page says the reader is signed out (access_rules OUT).

        With the institution's session, or an open-access article, the PDF is
        taken. With nothing either way, or with only the reader's access (also
        a personal account's or ClinicalKey's, J Hepatol 2026-10-31), the PDF is
        tried first and the school's login follows once if it fails (batch.py)."""
        result._open_access_current = False
        verdict, basis, evidence = self._access_decision(page, snapshot) if snapshot is not None else self._access_decision(page)
        if verdict != access_rules.UNKNOWN:
            detail = f"{verdict} ({basis}): {evidence}"[:240]
            if next((e["detail"] for e in reversed(result.events) if e["state"] == "access_decision"), None) != detail:
                self._event(result, "access_decision", detail)
        if verdict == access_rules.OUT:
            return False
        open_to_all = basis == "reader" and access_rules.OPEN_TO_ALL.search(evidence.split("badge: ", 1)[-1])
        result._open_access_current = bool(open_to_all)
        if (basis != "session" and not open_to_all and not getattr(result, "_pdf_first", False)
                and not self._school_login_done()):
            result._pdf_first = True
            self._event(result, "access_unknown_pdf_first",
                        f"reader access without the institution's session: {evidence}" if verdict == access_rules.IN
                        else f"no access evidence either way; {self._checks_found_nothing(page, evidence)}")
        return True

    def _checks_found_nothing(self, page: Any, unread: str = "") -> str:
        """What the access rule looked for on a page that said nothing either way;
        ``unread`` (``_access_snapshot``): its text could not be read, and only its
        elements were looked at."""
        try:
            probe = self._access_probe(page)
        except Exception:
            probe = {}  # a record only
        labels = ", ".join(str(label)[:40] for label in (probe.get("labels") or ())[:3]) or "none"
        badges = ", ".join(str(badge)[:30] for badge in (probe.get("badges") or ())[:3]) or "none"
        if unread:
            return (f"{unread}; only the page's elements were checked: institution labels ({labels}), "
                    f"badges ({badges}), offers and gates none")
        return (f"checked: login page no; institution session no (labels: {labels}); abstract-only view no; "
                f"reader access no (badges: {badges}; no licence or full-text sections); "
                f"{type(self.adapter).__name__} page rule none; password field, denial line, offer or gate none")

    def _decision_text(self, page: Any) -> str:
        """The page and the access rule that judged it: ``<url> | out (closed): Buy this article``."""
        url = str(getattr(page, "url", "") or "")
        try:
            verdict, basis, evidence = self._access_decision(page)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return url[:200]
        return f"{url[:200]} | {verdict} ({basis or 'no rule'}): {evidence[:160]}"

    _PAGE_TEXT_JS = "() => document.contentType !== 'text/html' ? -1 : (document.body ? document.body.innerText.trim().length : 0)"

    def _wait_for_page_text(self, page: Any, result: DownloadResult) -> None:
        """Wait for the document before judging access, within the page budget.

        A verification can disappear before the article draws. The old fixed
        20 s cut this wait short even with automation time left (AIP,
        2026-11-04). The enclosing page operation still bounds the whole step.
        """
        def shown() -> bool:
            try:
                return page.evaluate(self._PAGE_TEXT_JS) != 0
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                return False  # a document being replaced has not been read yet
        started = time.time()
        if shown():
            return
        timeout_sec = self.page_wait_sec
        drawn = pump_until(page, shown, int(timeout_sec * 1000), step_ms=500)
        # Recorded however short: a blank page is worth knowing about.
        self._event(result, "wait", f"blank page: {time.time() - started:.0f} s, ended: "
                                    f"{'text shown' if drawn else f'its {timeout_sec:g} s'}")
        if not drawn:
            url = str(getattr(page, "url", "") or "")
            raise PublisherContentError(f"publisher_page_blank: {url[:160]} showed no text for {timeout_sec:g} s")

    def _wait_past_redirect_page(self, page: Any, result: DownloadResult, timeout_sec: float = 20) -> None:
        """Let a publisher's script redirect page (linkinghub "Redirecting") move on
        before the access check: it is neither the article nor a login page. A
        verification shown there is waited for by the challenge wait instead."""
        started = time.time()
        deadline = started + timeout_sec
        waited = False
        while (self.adapter.is_redirect_page(str(getattr(page, "url", "") or "")) and time.time() < deadline
               and not self._challenge_shell(page)):
            waited = True
            page.wait_for_timeout(POLL_MS)
        if waited:
            self._note_wait(result, "redirect page", started, "left" if time.time() < deadline else "its 20 s")
            self._event(result, "redirect_page_passed", str(getattr(page, "url", "") or "")[:160])

    def _reopen_after_gateway_error(self, page: Any, result: DownloadResult) -> None:
        """Open the article again, once, when the publisher's front proxy answered
        with its bare error page instead (its server did not answer in time). The
        same page again is the publisher's error, reported as such."""
        error = self._gateway_error_text(page)
        if not error:
            return
        self._event(result, "gateway_error_page", error[:160])
        time.sleep(5)  # the publisher's server did not answer: give it a moment before asking again
        open_page(page, result.article_url, timeout_ms=60_000)
        settle(page, 3_000)
        self._wait_past_redirect_page(page, result)
        error = self._gateway_error_text(page)
        if error:
            raise PublisherContentError(f"publisher_gateway_error: {error[:120]}")

    def _complete_login_from_current_page(self, page: Any, result: DownloadResult) -> bool:
        """The school's login from the current page (``_complete_login_steps``), then
        back to the article if it ended on another page (``_return_to_article_after_login``);
        a wait of more than 10 s records how it ended."""
        self._phase(result, "login")
        started, signed_in = time.time(), False
        try:
            from ..browser import watchdog
            # Human authentication has its own budget, not the automation's.
            with watchdog.pause_operation():
                signed_in = self._complete_login_steps(page, result)
                if signed_in:
                    self._return_to_article_after_login(page, result)
            return signed_in
        finally:
            last = next((e["state"] for e in reversed(result.events) if e["state"] != "wait"), "")
            self._note_wait(result, "school login", started, "signed in" if signed_in else (result.reason or last))

    def _complete_login_steps(self, page: Any, result: DownloadResult) -> bool:
        own = self.adapter.complete_login(page, result)
        if own is not None:
            return own
        manual_selection = self.config.get("publisher_institution_federation") == "carsi"
        if self._institution_pdf_entitlement_missing(page):
            return False
        result.state = "sso_required"
        self._event(result, "sso_start", page.url)
        self._dismiss_cookie_banners(page, result)
        sites_opened = sum(e["state"] == "login_page_opened" for e in result.events)
        entry_opened = self._click_sso_entry(page, result)
        if not entry_opened and self.profile.generic and self._may_offer_entry(page):
            # No rule knows when this site draws its entry: one more look once
            # the page has loaded (access boxes built by script).
            settle(page, 5_000)
            page.wait_for_timeout(2_000)
            self._dismiss_cookie_banners(page, result)
            entry_opened = self._click_sso_entry(page, result)
        if entry_opened:
            # The entry often lands on a Cloudflare check: leave it untouched
            # until it clears, then run the page assistance below.
            settle(page, 2_000)
            if self._challenge_shell(page) and not self._wait_for_challenge(page, result):
                return False
        if sum(e["state"] == "login_page_opened" for e in result.events) > sites_opened:
            # Signing in on another site (ScienceDirect for a journal): that
            # site's own entry is still to be opened (signed out there, 2026-10-31).
            entry_opened = False
        if not entry_opened and self.profile.generic and self._may_offer_entry(page):
            # A site without rules of its own: the shared rules found no way to the
            # school's login on its page, and there is nothing for the user to do here.
            result.reason = GENERIC_ENTRY_MISSING
            looked_for, controls = self._entry_lookup_evidence(page)
            self._event(result, "login_entry_missing", looked_for)
            self._event(result, "login_entry_controls", controls)
            self._snapshot(page, result, "login entry missing")
            return False
        if (manual_selection and self.adapter.requires_institution_entry and not entry_opened
                and not self._is_human_login_page(page)):
            result.reason = "publisher_institution_entry_missing"
            self._event(result, result.reason)
            self._snapshot(page, result, "login entry missing")
            return False
        if (getattr(result, "_pdf_retry_login", False) and not entry_opened
                and sum(e["state"] == "login_page_opened" for e in result.events) == sites_opened
                and not self._is_human_login_page(page) and not self._is_auth_page(str(page.url))):
            # The login after a failed PDF: a page without an institution entry
            # has no login to wait for (an open article whose PDF did not come).
            self._event(result, "login_entry_missing",
                        f"{str(page.url)[:160]} | no institution entry, access menu entry or institution sign-in link")
            self._snapshot(page, result, "login entry missing")
            return False
        settle(page, 5_000)
        self._dismiss_cookie_banners(page, result)
        if self._click_openathens_entry(page, result):
            settle(page, 2_000)
        self._select_institution(page, result)

        deadline = self._user_wait_deadline(result)
        last_state = ""
        last_auto_action = ""
        last_auto_action_at = 0.0
        visited_idp = False
        page_since, page_inputs = time.time(), ()
        outside_since = time.time()  # last seen on the user's own login step
        article_returns = 0
        session_returns = 0
        away_from_publisher = False  # on an IdP, federation or chooser page since the last probe
        returned = False  # back on the publisher's site after such a page: try the PDF
        last_probe = time.time()
        while time.time() < deadline:
            time.sleep(1)  # each pass checks the page again: a step done goes on within a second
            self._check_user_decision(result, page)
            if getattr(result, "_institution_not_listed", False):
                # The publisher's institution search has no entry for the school.
                result.reason = "institution_federation_unavailable"
                self._event(result, result.reason, "the school is not in the publisher's institution list")
                return False
            over, outside_since = self._page_wait_over(page, outside_since)
            if over:
                # Off the school's login page for a whole page wait (a publisher
                # page, a chooser, a redirect that goes nowhere): nobody is typing.
                self._event(result, "page_wait_ended",
                            f"{self._login_wait_page(page)} after {self.page_wait_sec:.0f} s")
                self._wait_ran_out(result)
                return False
            marker = f"{self._title(page)} | {getattr(page, 'url', '')[:160]}"
            here = urlparse(str(getattr(page, "url", "") or ""))
            on_publisher = self._on_publisher_host(here.geturl())
            if here.hostname and (not on_publisher or self._is_idp_host(here.netloc)):
                visited_idp = True
                if self._is_idp_host(here.netloc):
                    result._visited_idp = True  # the school's own login: a denial now is the school's
            if here.hostname and (not on_publisher or self._is_auth_page(here.geturl())):
                away_from_publisher = True
            elif here.hostname and away_from_publisher:
                away_from_publisher, returned = False, True
                result._login_round_trip = True
                self._event(result, "login_round_trip_returned", here.geturl()[:160])
            if (on_publisher and self._is_success_article_url(here.geturl())
                    and not self._is_auth_page(here.geturl()) and not self._challenge_shell(page)
                    and (returned or time.time() - last_probe >= self.WAIT_PROBE_EVERY_SEC)
                    and self._looks_logged_out(page)):
                # Whoever signed in (this program or the user), the article page may
                # give its PDF although it still looks signed out to the rules (ASCE's
                # "GET ACCESS" after the login waited out five minutes, 2026-11-02): try it.
                after_login, returned, last_probe = returned, False, time.time()
                if self._probe_pdf_while_waiting(page, result, after_login=after_login):
                    return False  # signed in, and the page still offers or denies the article
            elif (visited_idp and on_publisher and article_returns < 2
                  and not self._is_success_article_url(here.geturl())
                  and not self._is_auth_page(here.geturl())
                  and not self._challenge_shell(page)):
                # Back from the IdP on a publisher page that is neither the
                # article nor a login/chooser page (Taylor & Francis drops the
                # redirect and lands on its home page): open the article.
                article_returns += 1
                try:
                    open_page(page, result.article_url, timeout_ms=60_000)
                    self._event(result, "idp_return_article", here.geturl()[:160])
                    settle(page, 3_000)
                    if not self._challenge_shell(page) and not self._looks_logged_out(page):
                        return True
                except Exception as exc:
                    self._event(result, "idp_return_article_error", type(exc).__name__)
                continue
            if marker != last_state:
                self._event(result, "login_state", marker)
                last_state = marker
                confirmation = self._idp_confirmation(page)
                if confirmation:
                    # The user decides: the engine never agrees on their behalf.
                    self._event(result, "idp_confirmation_required", confirmation)
                page_since, page_inputs = time.time(), self._visible_input_values(page) if self._user_away else ()
            elif self._user_away:
                inputs = self._visible_input_values(page)
                if inputs != page_inputs:
                    # Someone is typing here: wait for them, within the article's total.
                    page_since, page_inputs = time.time(), inputs
                elif time.time() - page_since >= AWAY_WAIT_SEC:
                    # Nothing moved on this page and the user seems away.
                    self._wait_ran_out(result)
                    return False
            if self._challenge_shell(page):
                if not self._wait_for_challenge(page, result, deadline=deadline):
                    return False
                continue
            if self._return_from_login_site(page, result):
                continue
            if manual_selection:
                if self._is_challenge_page(page):
                    if not self._wait_for_challenge(page, result, deadline=deadline):
                        return False
                    continue
                block_reason = self._login_block_reason(page)
                if block_reason:
                    self._event(result, block_reason, getattr(self, "_block_evidence", ""))
                    return False
            stuck = self._stuck_on_school_site(page, result)
            if stuck:
                result.reason = result.state = "idp_no_return_to_publisher"
                result._stopped_host = urlparse(stuck).hostname or ""
                self._event(result, "idp_no_return_to_publisher",
                            f"{stuck[:200]} | {self._title(page)[:80]} | {self.SCHOOL_SITE_STAY_SEC} s without returning")
                self._snapshot(page, result, "login stopped on the school's site")
                return False
            if self._follow_federated_login_option(page, result):
                continue
            if self._is_human_login_page(page):
                if not any(s["why"] == "waiting for the user: school login" for s in result.snapshots):
                    self._snapshot(page, result, "waiting for the user: school login")
                continue
            if manual_selection and self.adapter.institution_chooser_open(page):
                # The publisher's own chooser: choose there; no generic
                # Continue/SSO action while the user may be interacting.
                self._select_institution(page, result)
                continue
            self._dismiss_cookie_banners(page, result)
            self._click_optional_continue(page, result)
            if self._is_challenge_page(page):
                if self._wait_for_challenge(page, result, deadline=deadline):
                    continue
                self._event(result, "challenge_or_viewer_timeout", self._body_text(page, 500))
                return False
            if self._return_to_record_article_if_needed(page, result, result.doi):
                if not self._looks_logged_out(page):
                    return True
                continue
            if self._article_access_available(page):
                return True
            # After the IdP some publishers (Taylor & Francis) land on their
            # home page with the institution session active: go back to the
            # article. CARSI is automated too, so this applies in every mode.
            if (session_returns < 2 and self._has_publisher_institution_session(page)
                    and not self._is_success_article_url(getattr(page, "url", ""))):
                # Bounded: a page type the rules do not know as an article
                # (ScienceDirect book chapters, 2026-10-31) reloaded forever.
                session_returns += 1
                try:
                    open_page(page, result.article_url, timeout_ms=60_000)
                    self._event(result, "institution_session_return_article", result.article_url)
                    settle(page, 3_000)
                    self._dismiss_cookie_banners(page, result)
                    if not self._looks_logged_out(page):
                        return True
                    continue
                except Exception as exc:
                    self._event(result, "institution_session_return_error", f"{type(exc).__name__}: {exc}")
            block_reason = self._login_block_reason(page)
            if block_reason:
                self._event(result, block_reason, getattr(self, "_block_evidence", "") or self._body_text(page, 500))
                return False
            if manual_selection:
                if self._open_adapter_login_page(page, result):
                    entry_opened = False  # the next site's own entry is still to be opened
                    continue
                if (not entry_opened and self._is_success_article_url(str(page.url))
                        and not self._has_visible_editable_input(page)):
                    # The first entry lookup can run before the article page has
                    # rendered its entry (a publisher's silent redirect; ScienceDirect
                    # right after linkinghub, 2026-10-31). Open the official entry
                    # once it appears, then leave the user's institution selection alone.
                    entry_opened = self._click_sso_entry(page, result)
                    if entry_opened:
                        continue
                self._select_institution(page, result)
                continue
            if marker != last_auto_action or time.time() - last_auto_action_at > 10:
                if self._select_institution(page, result):
                    settle(page, 2_000)
                    last_auto_action = marker
                    last_auto_action_at = time.time()
                    continue
                if self._looks_logged_out(page) and self._click_sso_entry(page, result):
                    settle(page, 2_000)
                    self._select_institution(page, result)
                    last_auto_action = marker
                    last_auto_action_at = time.time()
                    continue
                if self._click_openathens_entry(page, result):
                    settle(page, 2_000)
                    self._select_institution(page, result)
                    last_auto_action = marker
                    last_auto_action_at = time.time()
                    continue
                self._select_institution(page, result)
                last_auto_action = marker
                last_auto_action_at = time.time()
            if self._article_access_available(page):
                return True
        if not manual_selection and self._has_publisher_institution_session(page):
            try:
                open_page(page, result.article_url, timeout_ms=60_000)
                self._event(result, "institution_session_return_article", result.article_url)
                settle(page, 3_000)
                self._dismiss_cookie_banners(page, result)
                return not self._looks_logged_out(page)
            except Exception as exc:
                self._event(result, "institution_session_return_error", f"{type(exc).__name__}: {exc}")
        self._wait_ran_out(result)
        return False

    # The school's account cannot sign in (login state J). Shibboleth's own
    # words ("Your account is locked.", "Your password has expired.") and the
    # Chinese ones a CAS prints; "账号被锁定怎么办" help links name no state.
    _IDP_ACCOUNT_LOCKED_RE = re.compile(r"your account is locked|(?:账号|帐号|账户|帐户)(?:已经被|已被|已)锁定", re.I)
    _IDP_PASSWORD_EXPIRED_RE = re.compile(r"your password has expired|密码已(?:经)?过期", re.I)
    # The school's IdP asks the user to agree before it goes on (login state K):
    # Shibboleth's attribute-release and terms-of-use forms, whatever the language.
    _IDP_CONFIRMATION_JS = """() => document.querySelector('[name="_eventId_TermsRejected"]') ? 'terms-of-use'
        : document.querySelector('[name="_shib_idp_consentOptions"], [name="_shib_idp_consentIds"]') ? 'attribute-release' : ''"""
    _IDP_ERROR_RE = re.compile(r"未知错误|系统错误|服务异常|认证失败|出错了|\b5\d{4}\b.{0,20}错误|an unexpected error|error code|system error", re.I)

    def _idp_confirmation(self, page: Any) -> str:
        """What the school's IdP asks the user to agree to, if anything: Shibboleth's
        attribute release or terms of use, or a Duo second factor."""
        if not self._is_idp_host(urlparse(str(getattr(page, "url", "") or "")).netloc):
            return ""
        try:
            kind = page.evaluate(self._IDP_CONFIRMATION_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return ""
        if kind:
            return str(kind)
        return "duo" if "authentication with duo is required" in self._body_text(page, 2_000).lower() else ""

    def _federation_list_lacks_carsi(self, page: Any) -> str:
        """A federation list without CARSI: no route for a CARSI school, so waiting
        for a login cannot succeed. One rule for every chooser: a <select> named a
        federation (its id or name, or its placeholder: BMJ's #shib-fed-select,
        AACR's #FederationDropdown "--Select a Federation--" listing only the UK,
        US and German federations, 2026-11-02) with two or more entries, none of
        them CARSI. The list and its entries, or "" (a list with CARSI, or none)."""
        if self.config.get("publisher_institution_federation") != "carsi":
            return ""
        for select in self._page_selects(page):
            options = [o for o in select.get("options") or () if isinstance(o, (list, tuple)) and len(o) == 2]
            name = str(select.get("name") or "")
            placeholder = str(options[0][1]) if options else ""
            entries = [str(label) for value, label in options if str(value).strip() and str(label).strip()]
            if (not (re.search(r"fed", name, re.I) or re.search(r"federation", placeholder, re.I)) or len(entries) < 2
                    or any(self._CARSI_OPTION.search(label) for label in entries)):
                continue
            return f"{name}: {', '.join(label[:40] for label in entries[:6])}"
        return ""

    def _openathens_lacks_school(self, page: Any) -> bool:
        """OpenAthens's "Find your institution" answers "No institutions found" for
        the configured school: it lists OpenAthens members, not CARSI schools
        (Sage's OpenAthens route: no CARSI school is listed, 2026-11-01)."""
        if (self.config.get("publisher_institution_federation") != "carsi"
                or urlparse(str(getattr(page, "url", "") or "")).hostname != "login.openathens.net"):
            return False
        try:
            if page.get_by_text("No institutions found", exact=True).first.is_visible() is not True:
                return False
            typed = " ".join(str(page.locator("input[type='text']:visible").first.input_value(timeout=2_000) or "").split())
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False
        return typed.lower() in {name.lower() for name in self._institution_names()}

    # The words that made a block decision, for its record.
    _BLOCK_WORDS = re.compile(
        r"your account is locked|your password has expired|密码已(?:经)?过期|(?:账号|帐号|账户|帐户)(?:已经被|已被|已)锁定"
        r"|未知错误|系统错误|服务异常|认证失败|出错了|an unexpected error|error code|system error"
        r"|sorry, you have been blocked|no institutions found|not registered for use with this service"
        r"|application you have accessed is not registered|may not be enabled for this type of authentication"
        r"|can't find your institution|access to this resource has been restricted by your organization|oa-ap-4032"
        r"|temporarily unavailable|verify you are human|are you a robot|checking your browser|正在进行安全验证", re.I)

    def _login_block_reason(self, page: Any) -> str:
        """Why the login cannot go on here ("" = it can); the words or rule that
        decided are kept in ``_block_evidence`` for the event."""
        code = self._login_block_check(page)
        self._block_evidence = self._block_evidence_for(code, page) if code else ""
        return code

    def _block_evidence_for(self, code: str, page: Any) -> str:
        if code == "login_page_closed":
            return "the browser window was closed"
        if code == "institution_pdf_entitlement_missing":
            return self._denial_line(page)
        lists = self._federation_list_lacks_carsi(page) if code == "institution_federation_unavailable" else ""
        if lists:
            return f"the federation list has no CARSI entry ({lists})"[:240]
        url = urlparse(str(getattr(page, "url", "") or ""))
        text = f"{self._title(page)}\n{self._body_text(page, 2_000)}"
        found = self._BLOCK_WORDS.search(text)
        if found:
            quoted = " ".join(text[max(0, found.start() - 60):found.end() + 60].split())
            return f'{url.hostname or ""}: "{quoted[:200]}"'
        return f"{url.hostname or ''}{url.path[:80]} | {self._title(page)[:80]} ({type(self.adapter).__name__} rule)"

    def _login_block_check(self, page: Any) -> str:
        if page.is_closed() is True:
            return "login_page_closed"  # the user closed the window
        try:
            parsed_idp = urlparse(str(getattr(page, "url", "") or ""))
            if self._is_idp_host(parsed_idp.netloc):
                said = f"{self._title(page)} {self._body_text(page, 1_500)}"
                if self._IDP_ACCOUNT_LOCKED_RE.search(said):
                    return "idp_account_locked"
                if self._IDP_PASSWORD_EXPIRED_RE.search(said):
                    return "idp_password_expired"
            if self._is_idp_host(parsed_idp.netloc) and (
                    "error" in parsed_idp.path.lower()
                    or self._IDP_ERROR_RE.search(f"{self._title(page)} {self._body_text(page, 1_500)}")):
                # The school's identity provider rejected this sign-in (a school's
                # CAS answering "50000 未知错误"): waiting longer cannot help.
                return "idp_login_error"
        except Exception:
            pass
        if self._publisher_access_blocked(page):
            return "publisher_access_blocked"
        if self._federation_list_lacks_carsi(page) or self._openathens_lacks_school(page):
            return "institution_federation_unavailable"
        current_url = str(getattr(page, "url", "") or "").lower()
        haystack = f"{self._title(page)} {self._body_text(page, 2_000)}".lower()
        if self._is_challenge_page(page):
            return "challenge_or_viewer_timeout"
        if (
            "are you a robot" in haystack
            or "verify you are human" in haystack
            or "checking your browser" in haystack
            or "正在进行安全验证" in haystack
            or ("ray id:" in haystack and "cloudflare" in haystack)
        ):
            return "challenge_or_viewer_timeout"
        chooser = self.adapter.chooser_block_reason(page, current_url, haystack)
        if chooser is not None:
            return chooser
        if self._institution_pdf_entitlement_missing(page):
            return "institution_pdf_entitlement_missing"
        override = self.adapter.login_block_reason(page, haystack)
        if override is not None:
            return override
        if "unsupported request" in haystack and "not registered for use with this service" in haystack:
            return "institution_not_registered"
        if "application you have accessed is not registered" in haystack:
            return "institution_not_registered"
        if "your institution may not be enabled for this type of authentication" in haystack:
            return "institution_not_registered"
        if "can't find your institution" in haystack and "institution sign in" in haystack:
            return "institution_not_registered"
        # OpenAthens: the user's organisation has not granted this resource
        # (error OA-AP-4032, the second test school on AHA journals, 2026-11-01).
        if (urlparse(current_url).hostname or "").endswith(".openathens.net") and (
                "access to this resource has been restricted by your organization" in haystack
                or "oa-ap-4032" in haystack):
            return "institution_not_registered"
        return ""

    # After its login the school's IdP may leave the browser on the school's own
    # site instead of sending it back: a test school's CAS ended on its portal
    # home page (…/login/home.do), nothing more happened
    # and nothing there said why: the IdP does not release to a publisher the
    # school has not enabled (2026-11-02). A page there that is no login form, no
    # SAML hand-over and no "please wait" page, unchanged this long, ends the item.
    SCHOOL_SITE_STAY_SEC = 12
    _SCHOOL_PAGE_STATE_JS = r"""() => ({
        ready: document.readyState === 'complete',
        login: !!document.querySelector('input[type="password"], input[autocomplete="one-time-code"]')
            || /扫码|二维码|QR ?code|验证码|verification code/i.test((document.body && document.body.innerText || '').slice(0, 4000)),
        handover: !!document.querySelector('input[name="SAMLResponse"], input[name="SAMLRequest"], input[name="RelayState"]')
            || /^\s*(?:loading|please wait|redirecting|正在跳转|跳转中|请稍候|处理中)/i.test(document.title || '')})"""

    def _school_domain(self, result: DownloadResult | None) -> str:
        """The school's own registrable domain: its entityID's, else the IdP's this item visited."""
        host = urlparse(self._entity_id()).hostname or getattr(result, "_idp_host", "")
        return access_rules.registrable_domain(host) if host else ""

    def _school_or_federation_page(self, url: str, result: DownloadResult | None = None, *,
                                   include_publisher_chooser: bool = True) -> bool:
        """The school's IdP or another page of its own site (its registrable domain),
        or a federation's school chooser. Publisher-owned choosers are included
        by default; their cookie prompts can be answered separately. The school's
        own pages remain protected even if an adapter calls one a chooser."""
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        if self._is_idp_host(host):
            return True
        school = self._school_domain(result)
        if school and access_rules.registrable_domain(host) == school:
            return True
        if not include_publisher_chooser and self.adapter.is_institution_chooser(url):
            return False
        return self._is_federation_chooser(url)

    def _stuck_on_school_site(self, page: Any, result: DownloadResult) -> str:
        """The page's URL when the login has stayed on a page of the school's own
        site, after the school's login, for ``SCHOOL_SITE_STAY_SEC`` (see above)."""
        url = str(getattr(page, "url", "") or "")
        host = (urlparse(url).hostname or "").lower()
        if self._is_idp_host(host):
            result._idp_host = getattr(result, "_idp_host", "") or host
        school = self._school_domain(result)
        if (not school or access_rules.registrable_domain(host) != school or self._on_publisher_host(url)
                or self._idp_confirmation(page)):
            result._school_page = None
            return ""
        try:
            state = page.evaluate(self._SCHOOL_PAGE_STATE_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            state = None
        if isinstance(state, dict) and state.get("login"):
            result._school_login_seen = True  # the school's login form: the login has started
        if (not isinstance(state, dict) or not state.get("ready") or state.get("login") or state.get("handover")
                or not (getattr(result, "_visited_idp", False) or getattr(result, "_school_login_seen", False))):
            result._school_page = None
            return ""
        seen = getattr(result, "_school_page", None)
        if not seen or seen[0] != url:
            result._school_page = (url, time.time())
            return ""
        return url if time.time() - seen[1] >= self.SCHOOL_SITE_STAY_SEC else ""

    @staticmethod
    def _visible_input_values(page: Any) -> tuple[str, ...]:
        """What the visible text and password fields hold; a change means someone types."""
        try:
            values = page.evaluate("""() => [...document.querySelectorAll('input')]
                .filter(i => ['', 'text', 'email', 'password', 'tel', 'number'].includes((i.type || '').toLowerCase())
                             && i.getClientRects().length > 0)
                .map(i => i.value || '')""")
        except Exception:
            return ()
        return tuple(str(v) for v in values) if isinstance(values, list) else ()

    def _open_adapter_login_page(self, page: Any, result: DownloadResult | None) -> bool:
        """Go to the adapter's next login page, each once per item (an Elsevier
        journal's own institution login, then ScienceDirect's same article);
        True when navigated."""
        opened = ({e.get("detail") for e in result.events if e["state"] == "login_page_opened"}
                  if result is not None else set())
        target = next((url for url in self.adapter.login_page_urls(page) if url not in opened), None)
        if not target:
            return False
        if result is not None:
            result._login_site_from = str(getattr(page, "url", "") or "")
        open_page(page, target, timeout_ms=60_000)
        if result is not None:
            self._event(result, "login_page_opened", target)
        return True

    def _return_from_login_site(self, page: Any, result: DownloadResult) -> bool:
        """The adapter sent the login to another site (an Elsevier journal site's
        institution login is ScienceDirect's). Once that site shows the institution
        session or full-text access (also through ClinicalKey or a personal account,
        2026-10-31), open the article again on the journal's own site: whether the school
        has access, and which PDF to take, is that site's to answer. If the journal
        site still gives only the abstract, go back once to the login site's
        article, which then decides as before. True when navigated."""
        url = str(getattr(page, "url", "") or "")
        host = (urlparse(url).hostname or "").lower()
        source = getattr(result, "_login_site_from", "")
        fallback = getattr(result, "_login_site_fallback", "")
        if source and host != (urlparse(source).hostname or "").lower():
            if not (self._has_publisher_institution_session(page) or self._article_access_available(page)):
                return False
            result._login_site_from, result._login_site_fallback = "", url
            target, state = result.article_url or source, "login_site_left"
        elif (fallback and host != (urlparse(fallback).hostname or "").lower()
                and self.adapter.is_article_page_url(url) and self._looks_logged_out(page)):
            result._login_site_fallback = ""
            target, state = fallback, "login_site_fallback"
        else:
            return False
        open_page(page, target, timeout_ms=60_000)
        self._event(result, state, target[:160])
        settle(page, 3_000)
        self._wait_past_redirect_page(page, result)
        return True

    def _click_sso_entry(self, page: Any, result: DownloadResult | None = None) -> bool:
        """Open the institution login from this page: its entry, one inside the
        site's access menu (``_open_entry_from_access_menu``), or a hidden link to
        the site's institution sign-in (``_follow_hidden_institution_link``)."""
        return (self._click_page_sso_entry(page, result) or self._open_entry_from_access_menu(page, result)
                or self._follow_hidden_institution_link(page, result))

    # A link to the site's institution sign-in, shown or not, by its address or its
    # words: JAMA keeps "Sign In" (/signinshibboleth?returnUrl=<the article>) in an
    # account menu whose toggle is an icon without words, De Gruyter "Add
    # institutional access" (/login, its WAYF) in a closed menu (2026-11-02). Never a
    # personal account's, an OAuth sign-in or a registration.
    _HIDDEN_INSTITUTION_LINK_JS = r"""() => {
        const PATH = /shibboleth|\/wayf|ssostart|institutional-login|institution-login/i;
        const WORDS = /\binstitutional (?:login|log in|sign in|access)\b|\baccess through your (?:institution|organi[sz]ation)\b|\b(?:log|sign) ?in (?:via|through|with) (?:an |your )?institution\b/i;
        const NOT = /personal|individual|regist|oauth|sign-?up|purchase|subscribe|log-?out|sign-?out/i;
        for (const a of document.querySelectorAll('a[href]')) {
            let target;
            try { target = new URL(a.getAttribute('href'), location.href); } catch (_) { continue; }
            const label = (a.textContent || a.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
            if (!/^https?:$/.test(target.protocol) || !(PATH.test(target.pathname) || WORDS.test(label))
                    || NOT.test(target.pathname + ' ' + label)) continue;
            return {href: target.href, label: label.slice(0, 80), shown: a.getClientRects().length > 0};
        }
        return null;
    }"""

    def _follow_hidden_institution_link(self, page: Any, result: DownloadResult | None) -> bool:
        """When no institution entry shows: a link on the page, even hidden, whose
        address is the site's own institution sign-in is opened by its address,
        once per page. Only the publisher's own address that selects no IdP."""
        url = str(getattr(page, "url", "") or "")
        tried = getattr(result, "_hidden_entries", set()) if result is not None else set()
        if (result is None or url in tried or urlparse(url).scheme != "https" or not self._on_publisher_host(url)
                or self._is_auth_page(url) or self._is_human_login_page(page)
                or self._has_visible_editable_input(page)
                or page.locator('input[name*="institution" i]:visible, input[placeholder*="institution" i]:visible, '
                                'input[name*="school" i]:visible, input[placeholder*="school" i]:visible').count()):
            return False  # never while the user may be choosing or typing here
        result._hidden_entries = tried | {url}
        try:
            link = page.evaluate(self._HIDDEN_INSTITUTION_LINK_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False
        href = str(link.get("href") or "") if isinstance(link, dict) else ""
        if not href:
            return False
        if not self._manual_institution_target_allowed(href):
            self._event(result, "hidden_entry_refused", href[:200])
            return False
        open_page(page, href, timeout_ms=30_000)
        self._event(result, "sso_entry_clicked",
                    f"hidden institution link{'' if not link.get('shown') else ' (shown)'}: "
                    f"\"{link.get('label') or ''}\" -> {href}"[:300])
        return True

    # Controls that open a site's access menu or login panel instead of a page:
    # "GET ACCESS" and "Login / Register" on ascelibrary.org (2026-11-02), "Access
    # options", "Sign in". A link to a login page is not one of them.
    _ACCESS_MENU_JS = r"""() => {
        const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
        const MENU = /^(?:get access|access options|(?:log ?in|sign ?in)(?: ?\/ ?register)?|register ?\/ ?(?:log ?in|sign ?in))$/i;
        const TOGGLES = ['aria-haspopup', 'aria-expanded', 'aria-controls', 'data-toggle', 'data-bs-toggle', 'data-target'];
        for (const el of document.querySelectorAll('button, [role="button"], a')) {
            if (!shown(el) || el.closest('form')) continue;
            const label = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
            // A screen-reader hint can be part of innerText ("Sign In Open Menu").
            const menuLabel = label.replace(/\s+open menu$/i, '');
            if (!MENU.test(menuLabel)) continue;
            const href = (el.getAttribute('href') || '').trim();
            if (el.tagName === 'A' && href && !href.startsWith('#') && !/^javascript:/i.test(href)
                    && !TOGGLES.some(name => el.hasAttribute(name))) continue;
            el.click();
            return label;
        }
        return '';
    }"""
    # The institution entry, by its words or its address: never a personal login,
    # a registration or a purchase, never a control of a form with a password field.
    _INSTITUTION_ENTRY_JS = r"""() => {
        const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
        const WORDS = /\b(?:institutional (?:login|log in|sign in|access|users)|access through your (?:institution|organi[sz]ation)|(?:log|sign) ?in (?:via|through|with) (?:an |your )?institution|shibboleth|openathens)\b|^institution(?:al)?$/i;
        const PATHS = /\/action\/ssostart|\/wayf|shibboleth|\/sso\/|openathens/i;
        const NOT = /personal|individual|register|purchase|\bbuy\b|subscribe|member/i;
        const controls = [...document.querySelectorAll('a, button, [role="button"]')];
        for (const [index, el] of controls.entries()) {
            if (!shown(el)) continue;
            // A link inside a login form opens a page and submits nothing (BMJ's
            // "Log in via institution" sits in its login box, 2026-11-02).
            const form = el.closest('form');
            if (el.tagName !== 'A' && form && form.querySelector('input[type="password"]')) continue;
            const label = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
            const href = el.tagName === 'A' && el.href && !/^javascript:/i.test(el.href) ? el.href : '';
            let path = '';
            try { path = href ? new URL(href).pathname : ''; } catch (_) {}
            if (NOT.test(label) || !(WORDS.test(label) || PATHS.test(path))) continue;
            return {label: label.slice(0, 120), href, index};
        }
        return null;
    }"""

    def _open_entry_from_access_menu(self, page: Any, result: DownloadResult | None) -> bool:
        """Open the site's access menu once per page and take the institution entry
        inside it: the adapter's own rule, else ``_INSTITUTION_ENTRY_JS``. An
        address is opened only when it is the publisher's own and selects no IdP."""
        url = str(getattr(page, "url", "") or "")
        tried = getattr(result, "_access_menus", set()) if result is not None else set()
        if (result is None or url in tried or not self._on_publisher_host(url) or self._is_auth_page(url)
                or self._is_human_login_page(page) or self._has_visible_editable_input(page)):
            return False
        try:
            label = page.evaluate(self._ACCESS_MENU_JS)
            if not label:
                return False
            result._access_menus = tried | {url}  # opened once: a second click would close it
            self._event(result, "access_menu_opened", str(label)[:120])
            entry = None
            if pump_until(page, lambda: bool(page.evaluate(self._INSTITUTION_ENTRY_JS)), 2_500):
                if self.adapter.open_institution_entry(page, result):
                    return True
                entry = page.evaluate(self._INSTITUTION_ENTRY_JS)
            if not isinstance(entry, dict):
                return False
            href = str(entry.get("href") or "")
            if href and not self._manual_institution_target_allowed(href):
                self._event(result, "access_menu_entry_refused", href[:200])
                return False
            if href:
                open_page(page, href, timeout_ms=30_000)
            elif not self._click_control(page, page.locator('a, button, [role="button"]').nth(int(entry.get("index") or 0)),
                                         result, f"access-menu entry: {entry.get('label') or ''}"[:120]):
                return False  # nothing was clicked (script_click_failed)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "access_menu_error", f"{type(exc).__name__}: {str(exc)[:160]}")
            return False
        self._event(result, "sso_entry_clicked", f"access-menu: {entry.get('label') or href}"[:200])
        return True

    def _click_page_sso_entry(self, page: Any, result: DownloadResult | None = None) -> bool:
        own = self.adapter.own_institution_entry(page, result)
        if own is not None:
            return own
        if self._open_adapter_login_page(page, result):
            return True
        if self._is_human_login_page(page):
            return False
        parsed = urlparse(str(getattr(page, "url", "") or ""))
        host = (parsed.hostname or "").lower()
        opened = self.adapter.open_institution_entry(page, result)
        if opened is not None:
            return opened
        if host == "openathens.net" or host.endswith(".openathens.net"):
            # The federation page is already an SSO step. Generic OpenAthens
            # text/ancestor matching can click its logo or account sign-in.
            return False
        if self.config.get("publisher_institution_federation") == "carsi":
            return self._click_manual_institution_entry(page, result)
        sso_selectors = (
            "button:has-text('Access Through Your Institution')",
            "button:has-text('Access through your institution')",
            "a:has-text('Access Through Your Institution')",
            "a:has-text('Access through your institution')",
            "[role='button']:has-text('Access Through Your Institution')",
            "[role='button']:has-text('Access through your institution')",
            "button:has-text('Institutional Access')",
            "a:has-text('Institutional Access')",
            "button:has-text('Institutional Sign In')",
        )
        sso_selectors = (*self.adapter.sso_selectors, *sso_selectors)
        for selector in sso_selectors:
            try:
                control = page.locator(selector).first
                if not control.is_visible(timeout=1_500):
                    continue
                text = ""
                href = ""
                try:
                    text = control.inner_text(timeout=1_000)
                except Exception:
                    pass
                try:
                    href = control.get_attribute("href", timeout=1_000) or ""
                except Exception:
                    pass
                detail = {"selector": selector, "text": text[:200], "href": href[:300]}
                try:
                    clicked = self._click_control(page, control, result, f"institution entry: {selector}")
                except Exception:
                    control.click(timeout=10_000, no_wait_after=True, force=True)
                    clicked = True
                if not clicked:
                    continue  # nothing was clicked (script_click_failed)
                if result is not None:
                    self._event(result, "sso_entry_clicked", json.dumps(detail, ensure_ascii=False))
                return True
            except Exception:
                continue
        if self.adapter.click_institution_control(page, result):
            return True
        markers = [marker.lower() for marker in self.profile.sso_text_markers]
        try:
            clicked = page.evaluate(
                """
                (markers) => {
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const candidates = [...document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"],div,span')]
                    .filter(visible);
                  const exactMarkers = [
                    'access through your institution',
                    'access through institution',
                    'access through your organization',
                    'institutional login',
                    'log in through your institution',
                    'log in via your institution',
                    'provided by your institution',
                    'username/password provided by your institution',
                    'log in with username/password provided by your institution'
                  ];
                  const clickableSelector = 'a,button,[role="button"],input[type="button"],input[type="submit"]';
                  const textOf = (el) => [
                    el.innerText || '',
                    el.textContent || '',
                    el.value || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || ''
                  ].join(' ').replace(/\\s+/g, ' ').trim().toLowerCase();
                  const detailOf = (el) => ({
                    text: textOf(el).slice(0, 180),
                    href: ((el.href || el.getAttribute('href') || '') + '').toLowerCase().slice(0, 240)
                  });
                  const matches = (el) => {
                    const text = textOf(el);
                    const href = ((el.href || el.getAttribute('href') || el.getAttribute('formaction') || '') + '').toLowerCase();
                    return exactMarkers.some(marker => text.includes(marker) || href.includes(marker))
                        || markers.some(marker => text.includes(marker) || href.includes(marker))
                        || href.includes('ssostart');
                  };
                  const clickMatched = (el) => {
                    const target = el.matches(clickableSelector)
                      ? el
                      : (el.closest(clickableSelector) || el.querySelector(clickableSelector));
                    if (!target) return null;
                    const detail = detailOf(el);
                    target.click();
                    return detail;
                  };
                  for (const el of candidates.filter((candidate) => candidate.matches(clickableSelector))) {
                    const matched = matches(el);
                    if (matched) {
                      const detail = clickMatched(el);
                      if (detail) return detail;
                    }
                  }
                  for (const el of candidates) {
                    const matched = matches(el);
                    if (matched) {
                      const detail = clickMatched(el);
                      if (detail) return detail;
                    }
                  }
                  return null;
                }
                """,
                markers,
            )
            if clicked:
                if result is not None:
                    self._event(result, "sso_entry_clicked", json.dumps(clicked, ensure_ascii=False))
                return True
        except Exception as exc:
            if result is not None:
                self._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
            return False
        return False

    def _may_offer_entry(self, page: Any) -> bool:
        """A page of the publisher's own where its institution entry would be: not
        a login, IdP or chooser page, no verification, no school login form."""
        url = str(getattr(page, "url", "") or "")
        return (url.startswith("http") and self._on_publisher_host(url) and not self._is_auth_page(url)
                and not self._challenge_shell(page) and not self._is_human_login_page(page))

    # The page's own sign-in and access controls, for the record of a missing entry.
    _SIGN_IN_CONTROLS_JS = r"""() => {
        const WORDS = /institution|log ?in|sign ?in|access|athens|shibboleth|wayf|sso|机构|登录/i;
        const seen = [];
        for (const el of document.querySelectorAll('a, button, [role="button"]')) {
            if (seen.length >= 8) break;
            if (!el.getClientRects().length) continue;
            const label = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 60);
            const href = el.tagName === 'A' ? (el.getAttribute('href') || '').slice(0, 120) : '';
            if (WORDS.test(label + ' ' + href)) seen.push(href ? `"${label}" -> ${href}` : `"${label}"`);
        }
        return seen;
    }"""

    def _entry_lookup_evidence(self, page: Any) -> tuple[str, str]:
        """``(looked for, found)``: what the entry lookup looked for, and the page
        with its own sign-in and access controls (where a rule for the site starts)."""
        try:
            controls = page.evaluate(self._SIGN_IN_CONTROLS_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            controls = []
        labels = (sorted(self._INSTITUTION_ENTRY_LABELS) if self.config.get("publisher_institution_federation") == "carsi"
                  else list(self.profile.sso_text_markers))
        found = "; ".join(str(c) for c in controls[:8]) if isinstance(controls, list) and controls else "none"
        return (f"looked for: entries ({', '.join(labels)}); access menus (get access, access options, "
                f"log in / register); sign-in links (shibboleth, /wayf, ssostart, institutional-login)",
                f"{str(getattr(page, 'url', '') or '')[:160]} | sign-in or access controls: {found}")

    def _manual_institution_target_allowed(self, href: str) -> bool:
        target = urlparse(href)
        if (target.scheme != "https" or target.username or target.password
                or not any(target.hostname == domain or (target.hostname or "").endswith("." + domain)
                           for domain in self.profile.base_domains)):
            return False
        # Reject remembered IdPs, including selected entities in nested return URLs.
        lowered = unquote(unquote(href)).lower()
        if re.search(r"(?:[?&;]|^)(?:entityid|idp|institutionid|organizationid|homeorg|providerid)=", lowered):
            return False
        return not any(part in target.path.lower() for part in
                       ("/institutionlogin", "/idp/", "/entity/"))

    # The labels of an institution entry, the whole label in lower case (CARSI mode).
    _INSTITUTION_ENTRY_LABELS = frozenset({
        "access through your institution", "access through institution",
        "access through your organization", "institutional access",
        "institutional login", "institutional sign in", "log in via an institution",
        "log in through your institution", "log in via your institution", "log in via institution",
    })

    def _click_manual_institution_entry(self, page: Any, result: DownloadResult | None) -> bool:
        """Open a generic publisher chooser without selecting an institution."""
        if page.locator('input[name*="institution" i]:visible, input[placeholder*="institution" i]:visible, '
                        'input[name*="school" i]:visible, input[placeholder*="school" i]:visible').count():
            return False
        for control in page.locator('a,button,[role="button"],input[type="button"]').all():
            try:
                if not control.is_visible():
                    continue
                label = (control.inner_text(timeout=2_000) or control.get_attribute("aria-label", timeout=2_000)
                         or control.get_attribute("value", timeout=2_000) or "")
                if re.sub(r"\s+", " ", label).strip().lower() not in self._INSTITUTION_ENTRY_LABELS:
                    continue
                # Default submit buttons can inherit a form action and hidden
                # selected IdP fields. Never submit a form in manual mode; a link
                # opens its (checked) address and submits nothing.
                if control.evaluate("el => el.tagName !== 'A' && Boolean(el.form || el.closest('form'))"):
                    continue
                href = control.get_attribute("href", timeout=2_000) or control.get_attribute("formaction", timeout=2_000) or ""
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                continue  # gone or changed while the page moved on (JAMA Pediatrics, 2026-11-02)
            if href and not self._manual_institution_target_allowed(urljoin(str(page.url), href)):
                continue
            if not self._click_control(page, control, result, f"institution entry: {label.strip()[:80]}"):
                continue  # nothing was clicked (script_click_failed)
            if result is not None:
                self._event(result, "sso_entry_clicked", "generic-institution-chooser")
            return True
        return False

    def _has_visible_editable_input(self, page: Any) -> bool:
        """Someone may be typing here: a visible editable field holds a value. Read
        on every pass of the login wait; a page navigating meanwhile ("Execution
        context was destroyed") ended the item as an unexpected error (review
        2026-11-02). Cut off by a navigation: True, the answer on which every
        caller leaves the page to the user (no entry, menu or link is opened, a
        password box stays the user's login), and the read is recorded. Other
        browser errors (a closed page) are the caller's, as before."""
        try:
            return bool(page.evaluate('''() => [...document.querySelectorAll('input,textarea')]
                .some(el => !el.disabled && !el.readOnly && el.checkVisibility()
                    && (el.tagName==='TEXTAREA' || ['text','search','email','password','url','tel',
                        'number','date','time','datetime-local','month','week'].includes(el.type))
                    && String(el.value||'').length>0)'''))
        except Exception as exc:
            if not _is_navigation_cut(exc):
                raise
            self._event(getattr(self, "_item_result", None), "page_read_interrupted",
                        f"typed fields, taken as typing: {type(exc).__name__}: {(str(exc).splitlines() or [''])[0][:160]}")
            return True

    # Institution choosers on another host. The school choice there is
    # automated like on the publisher's own pages; a password field on them
    # still means the page belongs to the user. A publisher's own chooser on
    # another host of its own is its adapter's ``is_institution_chooser``.
    _FEDERATION_CHOOSERS = (
        ("wayfinder.openathens.net", "/"),
        # "Find your institution" (Sage's OpenAthens route, 2026-11-01); the
        # OpenAthens account form there has a password field and stays the user's.
        ("login.openathens.net", "/auth"),
        ("ds.carsi.edu.cn", "/"),
        # SeamlessAccess's discovery page behind its button (AIP, 2026-11-03): it was
        # taken for the user's own login and the school was typed by hand.
        ("service.seamlessaccess.org", "/ds"),
    )

    def _is_federation_chooser(self, url: str) -> bool:
        if self.adapter.is_institution_chooser(url):
            return True
        parsed = urlparse(url)
        return parsed.scheme == "https" and any(
            parsed.hostname == host and parsed.path.startswith(path) for host, path in self._FEDERATION_CHOOSERS)

    def _on_publisher_host(self, url: str) -> bool:
        """The publisher's own site: a profile domain, or an article page its
        adapter recognises on another host (Elsevier journals' own sites)."""
        host = (urlparse(url).hostname or "").lower()
        if any(host == domain or host.endswith("." + domain) for domain in self.profile.base_domains):
            return True
        return self.adapter.is_article_page_url(url) is True

    def _page_wait_over(self, page: Any, outside_since: float) -> tuple[bool, float]:
        """Whether a login wait has been off the user's own login step for a whole
        page wait, and when that step was last seen (now, when on it)."""
        now = time.time()
        if self._users_login_step(page):
            return False, now
        return now - outside_since >= self.page_wait_sec, outside_since

    def _users_login_step(self, page: Any) -> bool:
        """The user's own step of the login, which may take the long wait
        (``login_timeout_sec``): the school's login page (a password field, or the
        school's identity provider), or a school chooser when no school is
        configured or the user chooses by hand. Any other page off the publisher's
        site is not: Atypon's iam.atypon.com hub, where AHA's login stopped on
        2026-11-03, was taken for the school's page and waited three minutes."""
        url = str(getattr(page, "url", "") or "")
        if self._school_password_box(page, url) or self._is_idp_host(urlparse(url).netloc):
            return True
        return self._is_auth_page(url) and (not self.institution_query or bool(getattr(self, "_manual_school", False)))

    def _login_wait_page(self, page: Any) -> str:
        """Where a login that waited on the user ended (ADR 0012):

        - ``school_login``: the school's own login page, the user's step;
        - ``school_choice``: a school chooser with no school configured, also the user's;
        - ``institution_chooser``: a chooser where the configured school was to be chosen;
        - ``publisher``: the publisher's own pages: the login was never reached;
        - ``other`` or ``closed``.
        """
        if page.is_closed() is True:
            return "closed"
        url = str(getattr(page, "url", "") or "")
        # The school's own page, by the same test as the long wait: a publisher's
        # SSO hub (iam.atypon.com) is no school login (2026-11-03).
        if self._school_password_box(page, url) or self._is_idp_host(urlparse(url).netloc):
            return "school_login"
        if self._is_auth_page(url):
            return "institution_chooser" if self.institution_query else "school_choice"
        return "publisher" if self._on_publisher_host(url) else "other"

    def _is_human_login_page(self, page: Any) -> bool:
        current_url = str(getattr(page, "url", "") or "")
        host = (urlparse(current_url).netloc or "").lower()
        if self.config.get("publisher_institution_federation") == "carsi":
            if self._school_password_box(page, current_url):
                return True
            if not self._on_publisher_host(current_url):
                return not self._is_federation_chooser(current_url)
        return self._is_idp_host(host)

    def _school_password_box(self, page: Any, url: str) -> bool:
        """A password or one-time-code field that is not a personal account's box on the publisher's site."""
        return bool(page.locator('input[type="password"]:visible, input[autocomplete="one-time-code"]:visible').count()
                    and not self._personal_login_box(page, url))

    def _personal_login_box(self, page: Any, url: str) -> bool:
        """The password field is a personal account's login box on the publisher's
        own article page, nobody typing in it: BMJ shows one next to "Log in via
        institution", and the article page was waited on for 5 minutes as if it
        were the school's login (2026-11-02)."""
        return (self._on_publisher_host(url) and self._is_success_article_url(url) and not self._is_auth_page(url)
                and not self._has_visible_editable_input(page))

    def _follow_federated_login_option(self, page: Any, result: DownloadResult) -> bool:
        """The publisher's login page offers an institutional option next to the
        personal form (Wolters Kluwer's "OpenAthens | Institutional")."""
        return bool(self.adapter.follow_federated_login(page, result))

    # Cookie and consent banners, in the page, its open shadow roots and its
    # frames. A banner is a box below <body> whose own text is about cookies,
    # consent, privacy or tracking and which offers a consent choice (accept,
    # reject, only necessary). A menu's or panel's close "X" is not one: on ACS
    # the class "gdpr-visible" of <body> made its off-canvas menu a banner, and its
    # "X" was clicked 60 times in 90 s (2026-11-02). In a banner the privacy-
    # preserving choice comes first (OneTrust's "Reject All", then "Reject"/
    # "Decline"/"Only necessary"/"拒绝"), its own close button next, and an
    # accepting button only when it offers neither and covers the page or a
    # control the engine had to click (BMJ's OneTrust banner over "Log in via
    # institution", 2026-11-02). Banners in ``skip`` (answered twice on this page)
    # are left alone. A school's IdP form is never touched.
    _COOKIE_BANNER_JS = r"""({blocking, skip}) => {
        if (document.querySelector('[name^="_eventId_"], [name="_shib_idp_consentIds"]')) return null;
        const REJECT = /^(?:reject(?: all)?(?: cookies)?|reject (?:all )?(?:non-essential|optional|additional)(?: cookies)?|decline(?: all)?(?: cookies)?|refuse(?: all)?(?: cookies)?|deny(?: all)?|(?:only|use only) (?:necessary|essential|required)(?: cookies)?|(?:necessary|essential|required) (?:cookies )?only|use (?:only )?(?:necessary|essential) cookies(?: only)?|continue without accepting|拒绝(?:全部|所有)?(?:cookies?)?|仅(?:限)?(?:接受)?必要(?:的)?(?:cookies?)?)$/i;
        const CLOSE = /^(?:close|close banner|dismiss|×|✕|x)$/i;
        const ACCEPT = /^(?:accept(?: all)?(?: cookies)?|i accept|accept and (?:close|continue)|allow(?: all)?(?: cookies)?|agree|i agree|agree and (?:close|continue)|got it|同意|接受(?:全部|所有)?(?:cookies?)?)$/i;
        // What a consent prompt's own text is about, in the languages met so far.
        const ABOUT = /cookie|consent|privacy|gdpr|tracking|tracker|隐私|隱私|クッキー|쿠키|datenschutz|confidentialit|privacidad|einwillig/i;
        const CONTROLS = 'button,a,[role="button"],input[type="button"],input[type="submit"]';
        // A box holding the site's navigation or main content is the page, not a prompt.
        const PAGE_PARTS = 'nav,main,[role="navigation"],[role="menu"],[role="menubar"],[role="main"]';
        const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
        const label = el => (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title')
            || el.textContent || '').replace(/\s+/g, ' ').trim();
        const up = node => node.parentElement || (node.getRootNode && node.getRootNode() !== document && node.getRootNode().host) || null;
        const roots = [document];
        for (let i = 0; i < roots.length && roots.length < 40; i++)
            for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
        const consentChoice = el => /^onetrust-(?:reject-all|accept-btn)-handler$/.test(el.id || '')
            || REJECT.test(label(el)) || ACCEPT.test(label(el));
        // The banner around a control: the nearest box below <body>, at most a few
        // thousand characters, about cookies or consent and offering a consent choice.
        // Each box is judged once per call: a page has hundreds of links.
        const judged = new Map();
        const judge = node => {
            if (!judged.has(node)) {
                let verdict = 'no';
                const text = (node.textContent || '').length > 20000 || node.matches(PAGE_PARTS)
                    || node.querySelector(PAGE_PARTS) ? null : (node.innerText || '');
                if (text === null || text.length > 8000) verdict = 'page';
                else if (ABOUT.test(text) && [...node.querySelectorAll(CONTROLS)].some(c => shown(c) && consentChoice(c)))
                    verdict = 'banner';
                judged.set(node, verdict);
            }
            return judged.get(node);
        };
        const bannerOf = el => {
            for (let node = up(el), n = 0; node && n < 12; node = up(node), n++) {
                if (node === document.body || node === document.documentElement) return null;
                const verdict = judge(node);
                if (verdict !== 'no') return verdict === 'banner' ? node : null;
            }
            return null;
        };
        // Over the page: a fixed or sticky box around the control, a tenth of the window or more.
        const covers = el => {
            for (let node = up(el), n = 0; node && n < 14; node = up(node), n++) {
                if (node.nodeType !== 1 || !['fixed', 'sticky'].includes(getComputedStyle(node).position)) continue;
                const r = node.getBoundingClientRect();
                if (r.width * r.height >= 0.1 * window.innerWidth * window.innerHeight) return true;
            }
            return false;
        };
        const keyOf = box => (box.id ? '#' + box.id
            : box.tagName.toLowerCase() + '.' + String(box.className || '').trim().split(/\s+/).slice(0, 3).join('.')).slice(0, 80);
        const found = roots.flatMap(root => [...root.querySelectorAll(CONTROLS)])
            .filter(shown).map(el => ({el, text: label(el), box: bannerOf(el)}))
            .filter(c => c.box && c.text && c.text.length <= 60).map(c => ({...c, key: keyOf(c.box)}));
        const open = found.filter(c => !skip.includes(c.key));
        const onetrust = open.find(c => c.el.id === 'onetrust-reject-all-handler');
        let choice = onetrust ? {...onetrust, kind: 'reject'} : null;
        for (const [kind, re] of [['reject', REJECT], ['close', CLOSE], ['accept', ACCEPT]]) {
            if (choice) break;
            const c = open.find(c => re.test(c.text) && (kind !== 'accept' || blocking || covers(c.el)));
            if (c) choice = {...c, kind};
        }
        if (!choice) {
            const left = found.find(c => skip.includes(c.key));
            return left ? {left: left.key} : null;
        }
        choice.el.click();
        return {kind: choice.kind, label: choice.text.slice(0, 80), banner: choice.key};
    }"""

    # Answers per banner and page; one still shown after them is left alone
    # (ACS's misread menu was clicked 60 times in 90 s, 2026-11-02).
    BANNER_ANSWERS = 2

    # An advertisement over the page (NEJM's lightbox over the article, 2026-11-03):
    # a fixed layer under the window's centre, over at least half the window, with
    # its own close control, and without a form, an embedded page, or sign-in,
    # institution or cookie words. Closed by that control; its text is returned.
    _AD_OVERLAY_JS = r"""() => {
        const vw = innerWidth, vh = innerHeight;
        const KEEP = /institution|log ?in|sign ?in|athens|shibboleth|password|cookie|consent|privacy|机构|登录/i;
        const CLOSER = /close|dismiss|关闭/i;
        const layers = new Set();
        for (const hit of document.elementsFromPoint(vw / 2, vh / 2)) {
            for (let el = hit; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
                if (getComputedStyle(el).position === 'fixed') layers.add(el);
            }
        }
        for (const el of layers) {
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
            const r = el.getBoundingClientRect();
            const w = Math.min(r.right, vw) - Math.max(r.left, 0), h = Math.min(r.bottom, vh) - Math.max(r.top, 0);
            if (w <= 0 || h <= 0 || w * h < 0.5 * vw * vh) continue;
            if (el.querySelector('input, select, textarea, iframe')) continue;
            const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
            if (!text || KEEP.test(text)) continue;
            const close = [...el.querySelectorAll('a, button, [role="button"]')].find(c => c.getClientRects().length && (
                CLOSER.test([c.getAttribute('aria-label'), c.getAttribute('title'), String(c.className)].join(' '))
                || /^[×✕✖xX]$/.test((c.innerText || '').trim())));
            if (!close) continue;
            close.click();
            return text.slice(0, 120);
        }
        return '';
    }"""
    AD_CLOSES = 2

    def _close_advertisement_overlay(self, page: Any, result: DownloadResult | None = None) -> bool:
        """Close an advertisement over the page (``_AD_OVERLAY_JS``), at most
        ``AD_CLOSES`` times per page, never on the school's or a federation's
        pages; True when one was closed."""
        item = result if result is not None else getattr(self, "_item_result", None)
        where = str(getattr(page, "url", "") or "").split("#", 1)[0]
        if not where.startswith("http") or self._school_or_federation_page(where, item):
            return False
        closes = getattr(item, "_ad_closes", None)
        if closes is None:
            closes = {}
            if item is not None:
                item._ad_closes = closes
        if closes.get(where, 0) >= self.AD_CLOSES:
            return False
        try:
            closed = page.evaluate(self._AD_OVERLAY_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False  # the page moved on meanwhile
        if not closed or not isinstance(closed, str):
            return False
        closes[where] = closes.get(where, 0) + 1
        self._event(result, "advertisement_closed", f"{closed[:120]} | {where[:160]}")
        return True

    def _dismiss_cookie_banners(self, page: Any, result: DownloadResult | None = None, *,
                                blocking: bool = False) -> bool:
        """Answer a cookie banner (``_COOKIE_BANNER_JS``) in the page or one of its
        frames, at most ``BANNER_ANSWERS`` times per banner and page. The school's
        and external federation pages stay protected; a publisher-owned chooser
        may answer its own cookie prompt (``_school_or_federation_page``).
        ``blocking``: the banner covered a control the engine clicked. An
        advertisement over the page is closed first (``_close_advertisement_overlay``).
        True when either was done."""
        closed = self._close_advertisement_overlay(page, result)
        item = result if result is not None else getattr(self, "_item_result", None)
        answered = getattr(item, "_banner_answers", None)
        if answered is None:
            answered = {}
            if item is not None:
                item._banner_answers = answered
        targets = [page]
        try:
            frames = page.frames
            if isinstance(frames, (list, tuple)):
                targets += [frame for frame in list(frames)[1:12]
                            if str(getattr(frame, "url", "") or "").startswith("http")]
        except Exception:
            pass
        for target in targets:
            where = str(getattr(target, "url", "") or "").split("#", 1)[0]
            if self._school_or_federation_page(where, item, include_publisher_chooser=False):
                continue
            skip = [key for (url, key), count in answered.items() if url == where and count >= self.BANNER_ANSWERS]
            try:
                clicked = target.evaluate(self._COOKIE_BANNER_JS, {"blocking": bool(blocking), "skip": skip})
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                continue  # a frame gone meanwhile; the banner is a convenience, never the item's end
            if not isinstance(clicked, dict):
                continue
            if clicked.get("label"):
                banner = str(clicked.get("banner") or "banner")
                answered[(where, banner)] = answered.get((where, banner), 0) + 1
                self._event(result, "cookie_banner_dismissed", f'{clicked.get("kind")} "{clicked.get("label")}" in {banner}')
                return True
            if clicked.get("left") and (where, "left " + str(clicked["left"])) not in answered:
                answered[(where, "left " + str(clicked["left"]))] = 0  # recorded once
                self._event(result, "cookie_banner_left",
                            f'{clicked["left"]} still shown after {self.BANNER_ANSWERS} answers; left alone | {where[:160]}')
        return closed

    def _click_control(self, page: Any, control: Any, result: DownloadResult | None, what: str, *,
                       timeout_ms: int = 5_000) -> bool:
        """Click ``control`` as the user would. When another element takes the click
        (Playwright: "... intercepts pointer events", a cookie banner over BMJ's
        "Log in via institution", 2026-11-02), answer the banner and click once
        more, then fall back to the script's click. A click that never happens in
        time (ASCO's "/action/ssostart" button, visible and enabled, 2026-11-02)
        is the script's click at once. Other failures are raised. True when
        clicked or the page moved on meanwhile; False when nothing was clicked
        (``_script_click``)."""
        before = str(getattr(page, "url", "") or "")
        try:
            control.click(timeout=timeout_ms, no_wait_after=True)
            return True
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            if "intercepts pointer events" not in str(exc):
                if not _is_browser_error(exc, "TimeoutError"):
                    raise
                return self._script_click(page, control, result, f"{what} (the click timed out)", timeout_ms, before)
            blocker = next((line.strip(" -") for line in str(exc).splitlines() if "intercepts pointer events" in line), "")
        self._event(result, "click_intercepted", f"{what}: {blocker}"[:300])
        if self._dismiss_cookie_banners(page, result, blocking=True):
            try:
                control.click(timeout=timeout_ms, no_wait_after=True)
                return True
            except Exception as again:
                if not _is_browser_error(again):
                    raise
        return self._script_click(page, control, result, what, timeout_ms, before)

    def _script_click(self, page: Any, control: Any, result: DownloadResult | None, what: str, timeout_ms: int,
                      before: str) -> bool:
        """The script's click on ``control``; True when done. When it fails, the
        control gone (nothing matches it any more) or the page at another address
        than ``before`` is the page moving on after the first click (Thieme's
        Shibboleth Continue, whose click timed out while the page left,
        2026-11-02): recorded, True. Otherwise nothing was clicked
        (``script_click_failed``): False, and the caller does not go on as if it
        had been (review 2026-11-02)."""
        try:
            control.evaluate("el => el.click()", timeout=timeout_ms)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            if self._control_gone(page, control, before):
                self._event(result, "click_target_gone", what[:200])
                return True
            self._event(result, "script_click_failed",
                        f"{what}: {type(exc).__name__}: {(str(exc).splitlines() or [''])[0]}"[:300])
            return False
        self._event(result, "script_click", what[:200])
        return True

    @staticmethod
    def _control_gone(page: Any, control: Any, before: str) -> bool:
        """The page has left ``before``, or ``control`` matches nothing any more.
        A count that cannot be read says neither."""
        if str(getattr(page, "url", "") or "") != before:
            return True
        try:
            return control.count() == 0
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return False

    def _click_openathens_entry(self, page: Any, result: DownloadResult) -> bool:
        if self.config.get("publisher_institution_federation") == "carsi":
            return False
        current_url = str(getattr(page, "url", "") or "")
        lower_url = current_url.lower()
        parsed = urlparse(current_url)
        host = (parsed.netloc or "").lower()
        if self.adapter.is_institution_chooser(current_url):
            # Keep the publisher's own chooser. OpenAthens is a separate
            # account route, not a required step before selection.
            return False
        if host.endswith("openathens.net") or self._is_idp_host(host):
            return False
        own = self.adapter.openathens_entry(page, result)
        if own is not None:
            return own

        try:
            clicked = page.evaluate(
                """
                () => {
                  const candidates = [...document.querySelectorAll('a,button,input[type="button"],input[type="submit"]')];
                  for (const el of candidates) {
                    const text = [
                      el.innerText || '',
                      el.textContent || '',
                      el.value || '',
                      el.getAttribute('aria-label') || '',
                      el.getAttribute('title') || ''
                    ].join(' ').toLowerCase();
                    const href = ((el.href || el.getAttribute('formaction') || '') + '').toLowerCase();
                    if ((text.includes('openathens') || href.includes('openathens'))
                        && !text.includes('shibboleth')) {
                      el.click();
                      return {text: text.slice(0, 160), href: href.slice(0, 240)};
                    }
                  }
                  return null;
                }
                """
            )
            if clicked:
                self._event(result, "openathens_entry", json.dumps(clicked, ensure_ascii=False))
                return True
        except Exception:
            return False
        return False

    # A button named exactly "Next" (RSC's institution search: <button aria-label="Next">
    # around a <span>Next</span>, which button:text-is('Next') misses, 2026-11-01).
    _NEXT_BUTTON = "role=button[name=Next]"

    def _click_optional_continue(self, page: Any, result: DownloadResult, *, after_selection: bool = False) -> None:
        """Click a Continue/Yes/consent button, but never on an institution chooser.

        ``after_selection`` is set only right after this code clicked an entry
        matching the user's configured institution; otherwise a chooser page is
        left entirely to the user (no default option is ever submitted).
        """
        if self.config.get("publisher_institution_federation") == "carsi" and not after_selection:
            return
        if not after_selection and self._page_has_institution_chooser(page):
            if not any(e["state"] == "institution_continue_withheld" for e in result.events):
                self._event(result, "institution_continue_withheld", "institution chooser is left to the user")
            return
        selectors = (
            "button:has-text('提交并继续')",
            "button:has-text('继续')",
            "button:has-text('Submit and continue')",
            "button:has-text('Continue')",
            self._NEXT_BUTTON,
            "button:has-text('Yes')",
            "[role='button']:has-text('Yes')",
            "a:has-text('Yes')",
            "input[value='Yes']",
            "input[type='submit']",
        )
        for selector in selectors:
            try:
                button = (page.get_by_role("button", name="Next", exact=True) if selector == self._NEXT_BUTTON
                          else page.locator(selector)).first
                if button.is_visible(timeout=1_500):
                    try:
                        text = (button.inner_text(timeout=1_000) or "").strip().lower()
                    except Exception:
                        text = ""
                    if "continue reading" in text:
                        continue
                    button.click(timeout=5_000, no_wait_after=True)
                    self._event(result, "institution_continue", selector)
                    return
            except Exception as exc:
                if after_selection:
                    # Our own selection's Continue failed: keep why (RSC's Next, 2026-11-01).
                    self._event(result, "institution_continue_error", f"{selector}: {type(exc).__name__}: {str(exc)[:300]}")
                continue
        if after_selection:
            self._click_chosen_entry_submit(page, result)

    # The entry this code chose (``_click_unique_institution_entry`` marks it).
    _CHOSEN_ENTRY = "[data-paper-search-entry]"

    def _click_chosen_entry_submit(self, page: Any, result: DownloadResult) -> None:
        """The chooser's own submit button after this code chose the school ("Access
        through your institution", Springer Nature's WAYF): only one inside the
        chosen entry's own form or box (``_LIST_SUBMIT_JS``), never the first submit
        of the page, which can be the header's search (review 2026-11-02)."""
        try:
            submit = page.evaluate(self._LIST_SUBMIT_JS, [self._CHOSEN_ENTRY, "button[type='submit']"])
            if not submit:
                return
            page.locator("[data-paper-search-submit]").first.click(timeout=5_000, no_wait_after=True)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "institution_continue_error",
                        f"the chosen entry's submit: {type(exc).__name__}: {(str(exc).splitlines() or [''])[0][:300]}")
            return
        self._event(result, "institution_continue", f"button[type='submit'] by the chosen entry: {submit}"[:200])
