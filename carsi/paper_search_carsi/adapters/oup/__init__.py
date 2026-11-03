"""Oxford Academic: journals on academic.oup.com (Silverchair).

One site type so far, Oxford's own journals and the society journals it hosts
(Endocrine Society, ...). Its sign-in is its own flow (``complete_login``): one
deadline per article from the first attempt, up to three attempts, and only the page's own
institutional control is ever clicked, never a form. The PDF endpoint
(``/<journal>/article-pdf/...``) redirects to a Silverchair CDN copy, accepted
only with that redirect as its provenance. Its institution chooser is SAMS
Sigma's Shibboleth discovery page (``oup2-ds.sams-sigma.com``), a list of
every member school with a filter box; the configured school is chosen there.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

from ...engine.batch_common import AWAY_WAIT_SEC, open_page
from ...engine.router import _append_oxford_candidates
from ..base import PublisherAdapter, SupplementLink, register

HOST = "academic.oup.com"
CDN_HOST = "watermark02.silverchair.com"
_ARTICLE = re.compile(r"/[^/]+/(?:advance-)?article(?:-abstract|-pdf)?/")
_PDF = re.compile(r"/[^/]+/(?:advance-)?article-pdf/")
_ENTRY = "a.js-shibboleth-action.at-institutional-sign-in"
CDN_FILES = "oup.silverchair-cdn.com"
# Links in the article's "Supplementary data" section, with their text.
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('[class*="supplementary-material"] a[href]')]
    .map(a => ({href: a.href, label: (a.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""
_STOP = {"login_retries_exhausted", "login_timeout", "login_page_closed",
         "login_credentials_rejected", "institution_not_registered",
         "institution_pdf_entitlement_missing"}


@register
class OUPAdapter(PublisherAdapter):
    publisher = "oxford academic"
    validates_article_pdf = True
    keeps_pdf_out_of_downloads = True
    native_pdf_patterns = (f"https://{HOST}/*/article-pdf/*", f"https://{HOST}/*/advance-article-pdf/*",
                           f"https://{CDN_HOST}/*.pdf*")
    pdf_cdn_redirects = True
    article_pdf_candidates_only = True
    diagnostic_screenshots = False
    returns_from_home_page = True

    # --- pages and PDFs -------------------------------------------------------

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        urls: list[str] = []
        _append_oxford_candidates(urls, doi, source_url)
        return urls

    def is_article_page_url(self, url: str) -> bool | None:
        parsed = urlparse((url or "").lower())
        return parsed.scheme == "https" and parsed.hostname == HOST and bool(_ARTICLE.match(parsed.path))

    def is_article_pdf_url(self, url: str, doi: str = "") -> bool | None:
        parsed = urlparse(url)
        path = unquote(parsed.path).lower()
        if (parsed.scheme != "https" or parsed.hostname != HOST
                or not _PDF.match(path) or not path.endswith(".pdf") or self.d._is_supplementary_url(url)):
            return False
        if not doi:
            return True
        parts = doi.lower().split("/", 2)
        if len(parts) != 3 or parts[0] != "10.1093":
            return False
        return (f"/doi/{doi.lower()}/" in path
                or (path.startswith(f"/{parts[1]}/article-pdf/")
                    and path.rsplit("/", 1)[-1] == parts[2] + ".pdf"))

    def is_institution_chooser(self, url: str) -> bool:
        host = (urlparse(url or "").hostname or "").lower()
        return host.endswith(".sams-sigma.com") and "-ds." in f"{host}."

    def is_pdf_cdn_url(self, url: str, doi: str) -> bool:
        """A CDN filename alone is insufficient; callers also require provenance."""
        parsed = urlparse(url)
        parts = doi.lower().split("/", 2)
        return (len(parts) == 3 and parts[0] == "10.1093"
                and parsed.scheme == "https" and parsed.hostname == CDN_HOST
                and unquote(parsed.path).lower().rsplit("/", 1)[-1] == parts[2] + ".pdf"
                and not self.d._is_supplementary_url(url))

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """The "Supplementary data" files on Silverchair's CDN, whose path names the
        DOI with "_" for "/" (``.../10.1093_labmed_lmag082/3/lmag082_supplementary_data.zip``).
        The same file is linked from several places; figure slides are not files."""
        key = (doi or "").lower().replace("/", "_")
        links: list[SupplementLink] = []
        seen: set[str] = set()
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) and key else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            path = unquote(target.path)
            if (target.scheme != "https" or target.hostname != CDN_FILES
                    or f"/{key}/" not in path.lower() or path in seen):
                continue
            seen.add(path)
            name = path.rsplit("/", 1)[-1]
            links.append(SupplementLink(target._replace(fragment="").geturl(), f"{name} {row.get('label') or ''}".strip()))
        return links

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        # The generic ancestor-text matcher can click the Oxford logo
        # inside a header containing institution text, sending us home.
        for control in page.locator(_ENTRY).all():
            if control.is_visible(timeout=1_500):
                control.click(timeout=10_000, no_wait_after=True)
                if result is not None:
                    self.d._event(result, "sso_entry_clicked", "oxford-institution-control")
                return True
        return False

    # --- sign-in ----------------------------------------------------------------

    def ensure_login(self, page: Any, result: Any) -> bool | None:
        """Open the article within ``login_timeout_sec``, then the PDF first or the
        sign-in, whose own deadline starts with its first attempt (``complete_login``)."""
        d = self.d
        opened_by = time.monotonic() + d.login_timeout_sec
        try:
            open_page(page, result.article_url,
                      timeout_ms=max(1, min(60_000, int(d.login_timeout_sec * 1000))))
        except Exception as exc:
            if not self.retryable_navigation_error(exc):
                raise
            d._event(result, "login_navigation_interrupted", type(exc).__name__)
            return self.complete_login(page, result)
        time.sleep(min(1, max(0, opened_by - time.monotonic())))
        if time.monotonic() >= opened_by:
            result.reason = "login_timeout"
            return False
        d._wait_past_redirect_page(page, result)
        d._raise_on_publisher_content_error(page)
        if not d._wait_for_challenge(page, result, deadline=time.time() + max(0, opened_by - time.monotonic())):
            return False
        d._raise_on_publisher_content_error(page)
        d._dismiss_cookie_banners(page, result)
        if d._institution_pdf_entitlement_missing(page):
            return False
        if d._pdf_first_unless_signed_out(page, result):
            return True
        return d._complete_login_from_current_page(page, result)

    def login_state(self, page: Any, deadline: float | None = None) -> str:
        """Observe once with a bounded read; return only a fixed category."""
        d = self.d
        if page.is_closed():
            return "login_page_closed"
        d._raise_on_publisher_access_blocked(page)
        budget = 750 if deadline is None else max(1, min(750, int((deadline - time.monotonic()) * 1000)))
        text = page.locator("body").inner_text(timeout=budget)[:12_000].lower()
        title = d._title(page).lower()
        challenge_selectors = (
            'iframe[src*="challenges.cloudflare.com"]:visible, '
            'iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible, '
            'iframe[title*="challenge" i]:visible, [data-sitekey]:visible'
        )
        if (any(marker in title + " " + text[:1200] for marker in (
                "just a moment", "verify you are human", "checking your browser",
                "are you a robot", "security verification", "正在进行安全验证"))
                or any(frame.locator(challenge_selectors).count() for frame in page.frames)):
            return "verification"
        credential_errors = (
            "incorrect password", "invalid password", "invalid credentials",
            "incorrect username or password", "用户名或密码错误", "密码错误",
        )
        if any(marker in text for marker in credential_errors):
            return "login_credentials_rejected"
        if any(marker in text for marker in (
            "application you have accessed is not registered",
            "your institution may not be enabled for this type of authentication",
        )) or ("unsupported request" in text and "not registered for use with this service" in text):
            return "institution_not_registered"
        if self.is_institution_chooser(str(page.url)):
            return "institution_chooser"  # the school is chosen by the engine's assistance
        # Never let generic Continue/submit actions touch a credential form.
        # Visibility checks read no input values and do not wait for selectors.
        human_form = False
        for frame in page.frames:
            if frame.locator('input[type="password"]:visible, input[autocomplete="username"]:visible, input[type="email"]:visible').count():
                human_form = True
                if frame != page.main_frame:
                    budget = 750 if deadline is None else max(1, min(750, int((deadline - time.monotonic()) * 1000)))
                    frame_text = frame.locator("body").inner_text(timeout=budget)[:12_000].lower()
                    if any(marker in frame_text for marker in credential_errors):
                        return "login_credentials_rejected"
        if human_form:
            return "human_login"
        host = (urlparse(str(page.url)).hostname or "").lower()
        if d._is_success_article_url(str(page.url)):
            # After the school's login a denial ends the item as not subscribed
            # (Brain 1968, AJE 1985: the school chosen three times, 2026-11-02).
            if d._institution_pdf_entitlement_missing(page):
                return "institution_pdf_entitlement_missing"
            # An empty page retaining an article URL is not a successful return.
            if not d._looks_logged_out(page) and page.locator("h1.wi-article-title").is_visible():
                return "article_ready"
        if host != HOST and any(
                frame.locator('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):visible, select:visible').count()
                for frame in page.frames):
            return "human_login"
        if any(marker in text for marker in (
            "temporarily unavailable", "bad gateway", "gateway timeout",
            "session has expired", "session timed out", "authentication request has expired",
            "err_connection_timed_out", "err_connection_reset",
        )):
            return "transient_error"
        return "publisher_login" if host == HOST else "redirect_wait"

    @staticmethod
    def retryable_navigation_error(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if not type(exc).__module__.startswith("playwright."):
            return False
        if type(exc).__name__ == "TimeoutError":
            return True
        return any(marker in str(exc) for marker in (
            "net::ERR_CONNECTION_TIMED_OUT", "net::ERR_TIMED_OUT",
            "net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_CLOSED",
            "net::ERR_NETWORK_CHANGED", "net::ERR_EMPTY_RESPONSE",
            # Firefox's word for a navigation another one replaced (AJE 1985, 2026-11-02).
            "NS_BINDING_ABORTED",
            "Execution context was destroyed", "Frame was detached", "because of a navigation",
        ))

    @staticmethod
    def action_timeout(deadline: float) -> int:
        return max(1, min(2_000, int((deadline - time.monotonic()) * 1000)))

    def advance_login(self, page: Any, result: Any, deadline: float) -> bool:
        """Only the observed Oxford institution control; no generic form submit."""
        if time.monotonic() >= deadline:
            return False
        if (urlparse(str(page.url)).hostname or "").lower() != HOST:
            return False
        for control in page.locator(_ENTRY).all():
            if control.is_visible():
                control.click(timeout=self.action_timeout(deadline), no_wait_after=True)
                self.d._event(result, "sso_entry_clicked", "oxford-institution-control")
                return True
        return False

    def complete_login(self, page: Any, result: Any) -> bool | None:
        """Initial attempt plus two retries, on one page and one total deadline."""
        d = self.d
        max_attempts = 3
        if result.reason in _STOP:
            return False
        # These request-local attributes are deliberately absent from asdict().
        if not hasattr(result, "_oxford_login_deadline"):
            # From the first attempt: set when the article opened, the PDF tried
            # first (40-90 s) took that much of the user's time (review 2026-11-02).
            result._oxford_login_deadline = time.monotonic() + d.login_timeout_sec
        if not hasattr(result, "_oxford_login_attempt"):
            result._oxford_login_attempt = 1
            d._event(result, "sso_start", "oxford")
            d._event(result, "login_attempt_started", "1/3")
        deadline = result._oxford_login_deadline
        attempt = result._oxford_login_attempt
        last_marker = None
        last_progress_at = time.monotonic()
        action_done = False
        pending_retry = ""
        waiting = None  # (since, page marker, typed values) while the page is the user's
        while time.monotonic() < deadline:
            try:
                state = self.login_state(page, deadline)
                if time.monotonic() >= deadline:
                    break
                parsed = urlparse(str(page.url))
                marker = (state, parsed.hostname, parsed.path)
                if marker != last_marker:
                    d._event(result, "login_observed", state)
                    last_marker = marker
                    last_progress_at = time.monotonic()
                    action_done = False
                if state == "article_ready":
                    result.reason = ""
                    return True
                if state in {"login_page_closed", "login_credentials_rejected",
                             "institution_not_registered", "institution_pdf_entitlement_missing",
                             "publisher_temporarily_unavailable"}:
                    result.reason = state
                    d._event(result, "login_stopped", state)
                    return False
                if state in {"verification", "human_login", "institution_chooser"}:
                    # A stale redirect timer must never reload a human form.
                    pending_retry = ""
                    last_progress_at = time.monotonic()
                    if state == "institution_chooser":
                        d._select_institution(page, result)
                    if d._user_away:
                        # The user seems away: as everywhere, a page of theirs on
                        # which nothing moves and nothing is typed ends the article.
                        typed = d._visible_input_values(page)
                        if waiting is None or waiting[1:] != (marker, typed):
                            waiting = (time.monotonic(), marker, typed)
                        elif time.monotonic() - waiting[0] >= AWAY_WAIT_SEC:
                            d._wait_ran_out(result)
                            result.reason = "login_timeout"
                            d._event(result, "login_stopped", result.reason)
                            return False
                else:
                    if state == "transient_error":
                        pending_retry = "transient_error"
                    elif state == "publisher_login" and not action_done and getattr(result, "_oxford_login_entry_attempt", 0) == attempt:
                        pending_retry = "returned_auth_wall"
                    elif time.monotonic() - last_progress_at >= 45:
                        pending_retry = "redirect_stalled"
                    if pending_retry:
                        if attempt >= max_attempts:
                            result.reason = "login_retries_exhausted"
                            d._event(result, "login_stopped", result.reason)
                            return False
                        d._event(result, "login_retry_wait", f"{attempt + 1}/3")
                        page.wait_for_timeout(min(3_000 * attempt, max(1, int((deadline - time.monotonic()) * 1000))))
                        if time.monotonic() >= deadline:
                            break
                        # Recheck after backoff: the user or redirect may have
                        # completed while the browser dispatched pending events.
                        after_wait = self.login_state(page, deadline)
                        if time.monotonic() >= deadline:
                            break
                        if after_wait not in {"transient_error", "publisher_login", "redirect_wait"}:
                            pending_retry = ""
                            continue
                        attempt += 1
                        result._oxford_login_attempt = attempt
                        d._event(result, "login_attempt_started", f"{attempt}/3")
                        pending_retry = ""
                        last_progress_at = time.monotonic()
                        action_done = False
                        open_page(page, result.article_url,
                                  timeout_ms=max(1, min(15_000, int((deadline - time.monotonic()) * 1000))))
                        continue
                    if state == "publisher_login" and not action_done:
                        action_done = self.advance_login(page, result, deadline)
                        if action_done:
                            result._oxford_login_entry_attempt = attempt
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                if remaining_ms:
                    page.wait_for_timeout(min(1_000, remaining_ms))
            except Exception as exc:
                if page.is_closed():
                    result.reason = "login_page_closed"
                    d._event(result, "login_stopped", result.reason)
                    return False
                # Only browser navigation/timeouts are retryable. Programming
                # errors must retain the normal unexpected_error path.
                if not self.retryable_navigation_error(exc):
                    raise
                d._event(result, "login_navigation_interrupted", type(exc).__name__)
                pending_retry = "navigation_error"
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining > 0:
                    page.wait_for_timeout(min(1_000, remaining))
        result.reason = "login_timeout"
        d._event(result, "login_stopped", result.reason)
        return False
