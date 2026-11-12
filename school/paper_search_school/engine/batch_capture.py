"""Getting the PDF: the article's PDF control, the browser's viewer and downloads, fetching again.

Part of ``PublisherBatchDownloader`` (batch.py), which combines the mixins."""

from __future__ import annotations

from ..browser import watchdog

import base64
import inspect
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from . import access_rules
from .page_activity import transfer
from .batch_common import (
    page_operation,
    POLL_MS,
    pump_until,
    settle,
    DownloadResult,
    MIN_PDF_BYTES,
    PDF_URL_RE,
    _IN_REFERENCES_JS,
    _REFERENCE_AREA,
    _IP_BLOCK_STATUS_CODES,
    _is_browser_error,
    goto_retrying,
)


class CaptureMixin:
    """Getting the PDF: the article's PDF control, the browser's viewer and downloads, fetching again."""

    # A probe of the PDF while the login waits: its whole time, and how often one
    # address is asked in one item (a publisher may block repeated PDF requests).
    WAIT_PROBE_SEC = 20
    _PROBE_TRIES_PER_URL = 3

    def _pdf_step_hit_wall(self, page: Any, result: DownloadResult, captured: dict[str, Any] | None = None) -> bool:
        """The PDF step's tab landed on a login, IdP or chooser page, an offer, a
        gate or a denial (access_rules OUT) instead of the PDF: stop the capture
        at once, so that fetch_one signs in and tries again, instead of waiting
        for a 403 (Taylor & Francis /action/showLogin, ScienceDirect's "Access
        through <school>", 2026-11-02)."""
        url = str(getattr(page, "url", "") or "")
        if (not url.startswith("http") or self.adapter.is_redirect_page(url)
                or self._challenge_shell(page) or self._pdf_viewer_present(page)):
            return False
        verdict, basis, evidence = self._access_decision(page)
        if verdict != access_rules.OUT or self._institution_pdf_entitlement_missing(page):
            return False
        self._event(result, "pdf_step_login_required", f"{url[:240]} | {basis}: {evidence[:160]}")
        if captured is not None:
            captured["login_wall"] = True
        return True

    def _probe_pdf_while_waiting(self, page: Any, result: DownloadResult, *, after_login: bool) -> bool:
        """While the login waits: this article's PDF from an open tab or fetched
        with the browser's session (``_probe_pdf``); found, the item ends with it
        (``PdfFoundWhileWaiting``). Not found right after the school's login while
        the page still denies or offers the article: True, the item ends as not
        subscribed. Otherwise False: the wait goes on."""
        from .batch_user import PdfFoundWhileWaiting

        self._event(result, "pdf_probe", "after the login round trip" if after_login else "while waiting")
        found = self._probe_pdf(page, result)
        if found:
            raise PdfFoundWhileWaiting(*found)
        if not after_login:
            return False
        evidence = self._no_access_after_login(page, result)
        if not evidence:
            return False
        result.reason = "institution_pdf_entitlement_missing"
        self._event(result, "no_access_after_login", evidence[:300])
        self._snapshot(page, result, "not subscribed")
        return True

    # PDF attempts that came back as a web page (``_record_pdf_attempt``).
    _WEB_PAGE_OUTCOMES = frozenset({"html page", "paywall"})

    def _pdf_sent_to_article_after_login(self, page: Any, result: DownloadResult, since: int) -> bool:
        """After this item's school login the PDF attempts from ``since`` on were
        sent to the article's own web page, with no PDF, login, verification or
        block. Missing entitlement additionally requires the page's denial,
        purchase offer or abstract-only evidence. A redirect alone can also
        happen on a freely readable article and does not prove missing access."""
        def plain(url: Any) -> str:
            parsed = urlparse(str(url or ""))
            return f"{parsed.hostname}{parsed.path}".lower().rstrip("/")

        attempts = result.pdf_attempts[since:]
        sent_back = [a for a in attempts if a.get("outcome") in self._WEB_PAGE_OUTCOMES
                     and plain(a.get("final_url")) != plain(a.get("url"))
                     and self._is_success_article_url(str(a.get("final_url") or ""))]
        url = str(getattr(page, "url", "") or "")
        if (not sent_back or not self._school_login_done()
                or any(a.get("outcome") not in self._WEB_PAGE_OUTCOMES | {"no pdf"} for a in attempts)
                or self._is_auth_page(url) or self._is_challenge_page(page)):
            return False
        evidence = self._no_access_after_login(page, result)
        if not evidence:
            return False
        last = sent_back[-1]
        result.reason = "institution_pdf_entitlement_missing"
        self._event(result, "no_access_after_login",
                    f"PDF after the school login sent to the article's web page: {str(last.get('url'))[:120]} -> "
                    f"{str(last.get('final_url'))[:160]} | {evidence[:160]}")
        self._snapshot(page, result, "not subscribed")
        return True

    # The article page fetches a PDF address itself: the browser's own session,
    # network and TLS, the tab left where it is. Only a PDF's body comes back.
    _FETCH_PDF_JS = r"""async ({url, timeout}) => {
        const control = new AbortController();
        const timer = setTimeout(() => control.abort(), timeout);
        try {
            const response = await fetch(url, {credentials: 'include', redirect: 'follow', signal: control.signal});
            const type = response.headers.get('content-type') || '';
            if (!response.ok || !/pdf|octet-stream/i.test(type)) return {status: response.status, url: response.url, body: ''};
            const bytes = new Uint8Array(await response.arrayBuffer());
            let binary = '';
            for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
            return {status: response.status, url: response.url, body: btoa(binary)};
        } catch (error) {
            return {status: 0, url, body: '', error: String(error).slice(0, 200)};
        } finally {
            clearTimeout(timer);
        }
    }"""

    def _probe_pdf(self, page: Any, result: DownloadResult) -> tuple[bytes, str] | None:
        """This article's PDF without navigating the tab and without waiting on the
        user: what an open tab's PDF viewer shows, or one of the article's PDF
        candidates (``_pdf_candidates``) fetched by the article page itself,
        within ``WAIT_PROBE_SEC``. Only a PDF whose first pages name this
        article counts (pdf_guard). A 403/429 ends probing for the item."""
        doi = result.doi
        probe_started = time.time()
        deadline = probe_started + self.WAIT_PROBE_SEC
        saved = (getattr(self, "_capture_doi", ""), getattr(self, "_expected_title", ""),
                 getattr(self, "_fallback_pdf", None))
        self._capture_doi = (doi or "").lower()
        self._expected_title = self._citation_title(page) or getattr(self, "_record_title", "")
        self._show_title(page)
        try:
            try:
                tabs = [tab for tab in list(page.context.pages) if not tab.is_closed()]
            except Exception:
                tabs = [page]
            if not self._is_chromium(page):
                for tab in tabs[:8]:
                    body = self._viewer_pdf_for_record(tab, doi)
                    if body:
                        self._event(result, "pdf_probe_captured", f"viewer {len(body)} bytes")
                        return body, str(getattr(tab, "url", "") or "")
            if getattr(result, "_probe_refused", False):
                return None
            tries = getattr(result, "_probe_tries", None)
            if tries is None:
                tries = result._probe_tries = {}
            for url in self._pdf_candidates(page, doi)[:4]:
                remaining = deadline - time.time()
                if remaining < 1:
                    break
                if tries.get(url, 0) >= self._PROBE_TRIES_PER_URL or self._is_supplementary_url(url):
                    continue
                tries[url] = tries.get(url, 0) + 1
                try:
                    with transfer(result):
                        fetched = page.evaluate(self._FETCH_PDF_JS, {"url": url, "timeout": int(min(10, remaining) * 1000)})
                except Exception as exc:
                    if not _is_browser_error(exc):
                        raise
                    continue  # the page moved on meanwhile
                if not isinstance(fetched, dict):
                    continue
                if fetched.get("status") in _IP_BLOCK_STATUS_CODES:
                    # Never ask again in this item: a publisher's block must not grow.
                    result._probe_refused = True
                    self._event(result, "pdf_probe_refused", f"{fetched.get('status')} {url}"[:300])
                    return None
                try:
                    body = base64.b64decode(str(fetched.get("body") or ""), validate=True)
                except (ValueError, TypeError):
                    continue
                final = str(fetched.get("url") or url)
                if body and self._accept_pdf_body(body, final):
                    self._event(result, "pdf_probe_captured", f"{len(body)} bytes {final}"[:300])
                    return body, final
            return None
        finally:
            self._note_wait(result, "a PDF probe", probe_started, "done")
            self._capture_doi, self._expected_title, self._fallback_pdf = saved

    @page_operation
    def _capture_pdf(self, page: Any, doi: str, result: DownloadResult) -> tuple[bytes | None, str, str | None]:
        """Run the capture channels; a PDF without DOI/title evidence is used
        only when nothing better arrived, and is marked unconfirmed."""
        self._phase(result, "pdf")
        self._capture_doi = (doi or "").lower()
        self._expected_title = self._citation_title(page) or getattr(self, "_record_title", "")
        self._show_title(page)
        self._fallback_pdf = None
        tried_before = len(result.pdf_attempts)
        try:
            from ..browser.preview import pause as pause_preview

            with pause_preview(getattr(page, "context", None)):
                try:
                    body, url, block = self._capture_pdf_channels(page, doi, result)
                    if (body is None and not block and len(result.pdf_attempts) == tried_before
                            and not result.reason and self._wait_for_pdf_candidates(page, doi, result)):
                        body, url, block = self._capture_pdf_channels(page, doi, result)
                except watchdog.BrowserBudgetExhausted as exc:
                    # The step's time ran out between browser calls, so the browser is fine. A PDF
                    # the article's own link already gave is saved unconfirmed for PaperSearch to
                    # check, not lost with the time (Science, 2026-11-09).
                    if self._fallback_pdf is None:
                        raise
                    self._event(result, "pdf_budget_exhausted", str(exc))
                    body, url, block = None, "", None
            if body is None and not block and self._fallback_pdf is not None:
                body, url = self._fallback_pdf
                self._event(result, "pdf_saved_unconfirmed", f"{url} | no DOI or title on the first pages")
            if body is None and not block and len(result.pdf_attempts) == tried_before and not result.reason:
                # Nothing was tried: say what the page offered (Thieme after the school
                # login ended "PDF not captured" without a trace, 2026-11-02).
                self._event(result, "pdf_step_nothing_tried", self._nothing_tried_evidence(page, doi))
            return body, url, block
        finally:
            self._fallback_pdf = None

    @staticmethod
    def _chromium_pdf_patterns(native: tuple[str, ...]) -> list[dict[str, str]]:
        """Responses Chrome pauses during the PDF step: the adapter's PDF addresses,
        and every document the tab opens wherever it is served. A PDF address can
        redirect to a delivery host no adapter lists (JAMA's articlepdf to
        Silverchair's watermark host, 2026-11-07); the checks on each paused
        response decide, and other documents go on at once."""
        return [*({"urlPattern": pattern, "requestStage": "Response"} for pattern in native),
                {"urlPattern": "*", "resourceType": "Document", "requestStage": "Response"}]

    PDF_CANDIDATE_WAIT_MS = 8_000

    def _wait_for_pdf_candidates(self, page: Any, doi: str, result: DownloadResult) -> bool:
        """A page that offered no PDF address may still be loading or about to move
        on: Thieme right after the school login, on its token address before the
        article (2026-11-02 on Firefox, 2026-11-07 on Chrome). Look again for a
        while; True once it offers one."""
        def offered() -> bool:
            try:
                return bool(self._pdf_candidates(page, doi))
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                return False  # the page is moving on: look at it again

        started = time.time()
        if not pump_until(page, offered, self.PDF_CANDIDATE_WAIT_MS, step_ms=500):
            return False
        self._event(result, "pdf_candidates_appeared",
                    f"after {time.time() - started:.1f} s at {str(getattr(page, 'url', ''))[:160]}")
        return True

    def _nothing_tried_evidence(self, page: Any, doi: str) -> str:
        """The page and its access verdict, and the PDF addresses it offered."""
        try:
            candidates = self._pdf_candidates(page, doi)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            candidates = []
        return (f"{self._decision_text(page)} | candidates: "
                f"{', '.join(str(url)[:120] for url in candidates[:3]) or 'none'}")[:400]

    def _identity_title(self) -> str:
        """The article's title for an identity check: the page's citation title, else the record's."""
        return getattr(self, "_expected_title", "") or getattr(self, "_record_title", "") or ""

    _CITATION_DOI_JS = "() => !!document.querySelector('meta[name=\"citation_doi\"]')"

    def _await_citation_metadata(self, page: Any, result: DownloadResult) -> None:
        """The citation metadata, read once the page has loaded: Karger's was read
        right after the login's return and the PDF step gave up within 6 s while
        the page carried it (2026-11-02). At most 10 s for the load, 5 s more for
        the tags; nothing waits when they are there."""
        def present() -> bool:
            try:
                return page.evaluate(self._CITATION_DOI_JS) is True
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                return False  # the page is still moving

        if present():
            return
        started = time.time()
        settle(page, 10_000)
        found = pump_until(page, present, 5_000)
        waited = time.time() - started
        self._event(result, "wait" if waited > 10 else "citation_metadata_wait",
                    f"citation metadata: {waited:.0f} s, ended: {'citation_doi present' if found else 'still missing'}")

    @staticmethod
    def _citation_title(page: Any) -> str:
        """The article page's own title metadata (citation_title)."""
        try:
            value = page.evaluate(
                "() => (document.querySelector('meta[name=\"citation_title\"]') || {}).content || ''")
        except Exception:
            return ""
        return " ".join(value.split()) if isinstance(value, str) else ""

    @staticmethod
    def _dublin_core_title(page: Any) -> str:
        """The article page's Dublin Core title (dc.Title), which Atypon sites such
        as SIAM give without a citation_title (2026-11-08). For display only."""
        try:
            value = page.evaluate(
                "() => (document.querySelector('meta[name=\"dc.title\" i]') || {}).content || ''")
        except Exception:
            return ""
        return " ".join(value.split()) if isinstance(value, str) else ""

    def _show_title(self, page: Any = None) -> None:
        """The article's title in the progress window, once its page names it: the
        title the identity check uses, else the page's Dublin Core title (only shown,
        never checked against: the capsule showed the DOI instead, 2026-11-08)."""
        title = getattr(self, "_expected_title", "") or (self._dublin_core_title(page) if page is not None else "")
        if not title or title == getattr(self, "_shown_title", ""):
            return
        self._shown_title = title
        try:
            from .. import progress_reporter

            progress_reporter.update(title=title)
        except Exception:
            pass

    # Figshare links: their files are found by its own API in the attachment step.
    _FIGSHARE_LINKED_JS = "() => !!document.querySelector('a[href*=\"figshare.com\"]')"

    def _remember_listed_supplements(self, page: Any, doi: str, result: DownloadResult) -> None:
        """The files the article page lists, read before the PDF takes its tab: the
        attachment step then need not load the page again (AHA's page took more
        than that step's 60 s once, 2026-11-08). Only from an adapter that reads
        them without leaving the page, and not beside Figshare links."""
        read = getattr(self.adapter, "listed_supplement_links", None)
        if read is None or getattr(result, "_listed_supplements", None):
            return
        try:
            links = read(page, doi)
            if links and not page.evaluate(self._FIGSHARE_LINKED_JS):
                result._listed_supplements = list(links)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise

    def _capture_pdf_channels(self, page: Any, doi: str, result: DownloadResult) -> tuple[bytes | None, str, str | None]:
        """Capture the PDF for ``doi`` from ``page``.

        Returns ``(body, url, block_reason)`` where ``block_reason`` is
        ``"ip_blocked"`` if a publisher IP-block signal (403/429 or block page)
        was observed during capture, else ``None``.
        """
        self._event(result, "pdf_capture_started")
        self._remember_listed_supplements(page, doi, result)
        captured: dict[str, Any] = {"bytes": None, "url": "", "deferred_url": "", "block_reason": None,
                                    "suspect_block": None, "closed": False, "readers": set()}
        cdp_session = None
        native_redirects: dict[str, list[Any]] = {}
        cdn_redirects: dict[str, list[Any]] = {}
        if self.adapter.binds_pdf_to_citation or self.adapter.metadata_pdf_patterns:
            self._await_citation_metadata(page, result)
        metadata_pdf_urls = set(self._metadata_pdf_urls(page, doi))
        bound = self._bound_pdf_urls(page, doi)
        if bound == []:
            # The article page without citation metadata: its own links naming the
            # article (its DOI or its article id) are this capture's candidates.
            # A page whose metadata names another DOI is not this article's.
            missing, why = self._citation_pdf_missing(page, doi)
            bound = self._article_pdf_links_on_page(page, doi) if missing else []
            self._event(result, "publisher_pdf_link_unverified",
                        why + ("" if not missing else f"; {len(bound)} link(s) naming the article: {', '.join(bound)[:300]}"
                               if bound else "; no link names the article"))
        bound_pdf_urls = frozenset(bound) if bound is not None else None
        captured["article_pdf_urls"] = bound_pdf_urls  # a viewer's PDF is judged by it while waiting too
        article_options = {"article_pdf_urls": bound_pdf_urls} if bound_pdf_urls is not None else {}
        if bound_pdf_urls is not None and not bound_pdf_urls:
            return None, "", None
        # Rejected browser attachments must not be retried as plain HTTP PDFs.
        # Keep this evidence local to this capture, never on the downloader/session.
        rejected_pdf_urls: set[str] = set()
        fallback_options = ({"doi": doi, "rejected_urls": rejected_pdf_urls}
                            if self._uses_article_pdf_validation() else {})
        fallback_options.update(article_options)

        def entitlement_denied() -> bool:
            if not self._institution_pdf_entitlement_missing(page):
                return False
            result.reason = result.state = "institution_pdf_entitlement_missing"
            return True

        if entitlement_denied():
            return None, "", None

        def on_native_request(event: dict[str, Any]) -> None:
            # Network events retain redirect provenance even when Chrome hands
            # the final response to its PDF viewer or download manager.
            request_id = event["requestId"]
            redirect = event.get("redirectResponse")
            if not redirect:
                native_redirects.pop(request_id, None)
                return
            history = native_redirects.setdefault(request_id, [])
            if len(history) <= 20:
                history.append(SimpleNamespace(
                    url=redirect.get("url", ""), headers=redirect.get("headers", {}),
                ))
            url = event.get("request", {}).get("url", "")
            response = SimpleNamespace(url=url, status=200, headers={}, history=history)
            urls = self._response_urls(response)
            # Kept by address too: Chrome can answer the final PDF under another
            # request id. The bound PDF's own file on its CDN is one (RSC, 2026-11-07).
            if ((self.adapter.is_pdf_cdn_url(url, doi) or self._bound_pdf_copy(url, response, doi, article_options))
                    and self._response_matches_article(response, doi, **article_options)):
                cdn_redirects[url] = list(history)
            if (any(hop in rejected_pdf_urls for hop in urls)
                    or (self._article_pdf_url_matches(url, doi, **article_options)
                        and (len(history) > 20 or not self._response_matches_article(response, doi, **article_options)))):
                # Chrome may restart the final PDF under a new networkId.
                # Keep rejection by URL for this capture, across that restart.
                rejected_pdf_urls.update(urls)

        def on_paused_response(event: dict[str, Any]) -> None:
            request_id = event["requestId"]
            response_completed = False
            headers: dict[str, str] = {}
            url = ""
            try:
                headers = {
                    header["name"].lower(): header["value"]
                    for header in event.get("responseHeaders", [])
                }
                url = event.get("request", {}).get("url", "")
                history = native_redirects.get(event.get("networkId", ""), []) or cdn_redirects.get(url, [])
                if (self.adapter.discards_unbound_pdfs
                        and "application/pdf" in headers.get("content-type", "").lower()
                        and (url in rejected_pdf_urls or self._is_supplementary_url(url)
                             or self._is_supplementary_url(headers.get("content-disposition", ""))
                             or not (self._article_pdf_url_matches(url, doi, **article_options)
                                     # The bound PDF's own file on the host its address redirects
                                     # to (RSC's article-pdf -> rscj.silverchair-cdn.com, 2026-11-07).
                                     or self._bound_pdf_copy(url, SimpleNamespace(url=url, history=history),
                                                             doi, article_options)))):
                    rejected_pdf_urls.add(url)
                    return
                if ("application/pdf" in headers.get("content-type", "").lower()
                        and self._is_partial_pdf_response(SimpleNamespace(
                            status=event.get("responseStatusCode"), headers=headers))):
                    captured["deferred_url"] = url
                    self._event(result, "partial_pdf_response", "native")
                    return
                if url in rejected_pdf_urls:
                    return
                if metadata_pdf_urls and (url.split("?", 1)[0] not in metadata_pdf_urls
                        or self._is_supplementary_url(headers.get("content-disposition", ""))):
                    rejected_pdf_urls.add(url)
                    return
                if (
                    not captured["bytes"]
                    and 200 <= event.get("responseStatusCode", 0) < 300
                    and "application/pdf" in headers.get("content-type", "").lower()
                    and not self._is_supplementary_url(url)
                ):
                    # Native Chrome PDF responses may be unreadable through
                    # response.body(). Apply the same article/attachment guards
                    # before reading the response through CDP instead.
                    if self._uses_article_pdf_validation():
                        response = SimpleNamespace(
                            url=url, headers=headers,
                            status=event.get("responseStatusCode", 0), history=history,
                        )
                        final_pdf = (self._article_pdf_url_matches(url, doi, **article_options)
                                     or self.adapter.is_pdf_cdn_url(url, doi)
                                     # The bound PDF's own file on the host its address redirects
                                     # to, as _response_matches_article accepts it (JAMA's
                                     # articlepdf -> Silverchair's watermarked copy, 2026-11-07).
                                     or self._bound_pdf_copy(url, response, doi, article_options))
                        if (len(history) > 20 or not final_pdf
                                or not self._response_matches_article(response, doi, **article_options)):
                            rejected_pdf_urls.update(self._response_urls(response))
                            return
                    with transfer(result):
                        payload = cdp_session.send("Fetch.getResponseBody", {"requestId": request_id})
                    body = (
                        base64.b64decode(payload["body"], validate=True)
                        if payload.get("base64Encoded")
                        else payload["body"].encode("latin-1")
                    )
                    if self._accept_pdf_body(body, url):
                        if self.adapter.keeps_pdf_out_of_downloads:
                            # We own the validated bytes and save them under the
                            # DOI below. Do not also hand the response to Chrome's
                            # download manager, which exposes a UUID temp file.
                            cdp_session.send("Fetch.fulfillRequest", {
                                "requestId": request_id, "responseCode": 204,
                                "responseHeaders": [], "body": "",
                            })
                            response_completed = True
                        captured["bytes"] = body
                        captured["url"] = url
                        self._event(result, "browser_pdf_response_captured", f"{len(body)} bytes")
                    elif self._uses_article_pdf_validation():
                        rejected_pdf_urls.add(url)
            except Exception as exc:
                self._event(result, "browser_pdf_response_error", type(exc).__name__)
            finally:
                if (not response_completed and self.adapter.discards_unbound_pdfs
                        and url in rejected_pdf_urls and "application/pdf" in headers.get("content-type", "").lower()):
                    # A rejected attachment must not reach Chrome's download
                    # manager while the capture reports that it was refused.
                    try:
                        cdp_session.send("Fetch.fulfillRequest", {
                            "requestId": request_id, "responseCode": 204,
                            "responseHeaders": [], "body": "",
                        })
                        response_completed = True
                    except Exception as exc:
                        self._event(result, "browser_response_discard_error", type(exc).__name__)
                if not response_completed:
                    try:
                        cdp_session.send("Fetch.continueRequest", {"requestId": request_id})
                    except Exception as exc:
                        self._event(result, "browser_response_continue_error", type(exc).__name__)

        def on_response(response: Any) -> None:
            # A response handled after this capture is over reads nothing: a body
            # read that never returned there (after AIAA's blocked PDF) stopped the
            # watchdog for the whole process, and the next article with it
            # (Chicago, browser_unresponsive, 2026-11-07).
            if captured["closed"]:
                return
            # The tab's own document answers, for the attempt's record.
            try:
                request = getattr(response, "request", None)
                if (request is not None and getattr(request, "resource_type", "") == "document"
                        and getattr(response, "frame", None) is page.main_frame):
                    headers = getattr(response, "headers", None) or {}
                    captured["nav"] = {"url": str(response.url), "status": response.status,
                                       "type": str(headers.get("content-type") or "").split(";")[0],
                                       "size": str(headers.get("content-length") or "")}
            except Exception:
                pass
            if captured["bytes"] or captured["block_reason"]:
                return
            try:
                url = response.url
                if url in rejected_pdf_urls:
                    return
                if metadata_pdf_urls and "pdf" in (response.headers.get("content-type") or "").lower() and url.split("?", 1)[0] not in metadata_pdf_urls:
                    rejected_pdf_urls.add(url)
                    return
                status = getattr(response, "status", None)
                if self.adapter.pdf_cdn_redirects and status is not None and 300 <= status < 400:
                    # A redirect has no PDF body. Remember only an observed
                    # current-DOI endpoint redirect, then validate its final PDF.
                    target = urljoin(url, response.headers.get("location", ""))
                    history = [SimpleNamespace(url=url, headers=response.headers)]
                    candidate = SimpleNamespace(url=target, status=200, headers={}, history=history)
                    if self._response_matches_article(candidate, doi):
                        cdn_redirects[target] = history
                    return
                if self.adapter.passes_over_redirects and status is not None and 300 <= status < 400:
                    return
                # Detect a publisher IP-block response before anything else:
                # a 403/429 on a PDF/article endpoint means our IP is blocked,
                # and continuing to churn只会加深封锁。
                if (status in _IP_BLOCK_STATUS_CODES and not captured["block_reason"]
                        and self._is_pdf_candidate_url(url) and not self._is_supplementary_url(url)):
                    provenance = SimpleNamespace(url=url, status=200, headers=response.headers,
                        request=getattr(response, "request", None), history=getattr(response, "history", ()))
                    relevant = (self._response_matches_article(provenance, doi, **article_options)
                                if self._uses_article_pdf_validation() else True)
                    if relevant:
                        try:
                            with watchdog.owned_by(captured["readers"]):
                                snippet = response.text()[:8192] if hasattr(response, "text") else response.body()
                        except Exception:
                            snippet = ""
                        text = self._visible_text_excerpt(snippet)
                        if self._is_explicit_block_page(snippet, self.adapter.block_page_markers):
                            captured["block_reason"] = "ip_blocked"
                            self._event(result, "ip_blocked_response", f"{status} {url} | {text}")
                        elif self._article_page_answer(text):
                            # The article's own page (its title) answered: a paywall,
                            # no verification to wait for; the attempt ends as a page.
                            self._event(result, "pdf_step_article_page", f"{status} {url} | {text}")
                        elif not captured["suspect_block"]:
                            # A 403/429 on the PDF step is often a human-verification
                            # page (rendered in the PDF tab). Never end the route
                            # here: the capture loop waits for the user first.
                            captured["suspect_block"] = f"{status} {url}"
                            self._event(result, "suspect_block_response", f"{status} {url} | {text}")
                content_type = (response.headers.get("content-type") or "").lower()
                if self._is_supplementary_url(url):
                    return
                if self._is_partial_pdf_response(response):
                    if "pdf" in content_type or self._is_pdf_candidate_url(url):
                        captured["deferred_url"] = url
                        self._event(result, "partial_pdf_response", "browser")
                    return
                checked_response = response
                if url in cdn_redirects:
                    checked_response = SimpleNamespace(url=url, status=status, headers=response.headers,
                        request=getattr(response, "request", None), history=cdn_redirects[url])
                if not self._response_matches_article(checked_response, doi, **article_options):
                    if not self._refusal_answer(response):
                        rejected_pdf_urls.update(self._response_urls(response))
                    return
                if "pdf" not in content_type and not self._is_pdf_candidate_url(url):
                    return
                if self._should_defer_response_body(url):
                    captured["deferred_url"] = url
                    return
                with transfer(result), watchdog.owned_by(captured["readers"]):
                    body = response.body()
                # Body-level block-page detection (some block pages are 200
                # with an HTML "IP Address Blocked" body).
                if not body[:5] == b"%PDF-" and not captured["block_reason"]:
                    if self._is_ip_block_response(None, body):
                        captured["block_reason"] = "ip_blocked"
                        self._event(result, "ip_blocked_body", url)
                if self._accept_pdf_body(body, url):
                    captured["bytes"] = body
                    captured["url"] = url
                elif self._uses_article_pdf_validation() and body.startswith(b"%PDF-"):
                    rejected_pdf_urls.update(self._response_urls(response))
                    self._event(result, self.adapter.pdf_rejected_event, "non_article_or_invalid_pdf")
            except Exception:
                return

        def on_request_failed(request: Any) -> None:
            # A request for a PDF address that ended without an answer: what the
            # browser said and after how long, for the record (Karger's PDF
            # navigation ended aborted after 46 s, and whether the click's own
            # request had failed was not known, 2026-11-02).
            try:
                url = str(request.url)
                if not self._is_pdf_candidate_url(url) or self._is_supplementary_url(url):
                    return
                started = float((request.timing or {}).get("startTime") or 0) / 1000
                lasted = f" after {time.time() - started:.1f} s" if started > 0 else ""
                self._event(result, "pdf_request_failed", f"{url[:200]} | {request.failure or 'failed'}{lasted}"[:300])
            except Exception:
                pass  # the record never ends the capture

        pending: dict[str, Any] = {}

        def begin(how: str, url: str, started: float) -> None:
            """A new PDF attempt: the previous one goes to the record first."""
            finish()
            captured["nav"] = None
            self._last_identity = None
            pending.update(how=how, url=url, started=started)

        def finish() -> None:
            if pending:
                self._record_pdf_attempt(result, page, dict(pending), captured)
                pending.clear()

        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        # PDF requests come from the article page, as a reader's click would
        # (Ovid answers one without that Referer with a redirect, 2026-11-01).
        article_page = str(getattr(page, "url", "") or "")
        try:
            native_pdf_patterns = ((self.adapter.metadata_pdf_patterns if metadata_pdf_urls else ())
                                   or self.adapter.native_pdf_patterns)
            browser = getattr(page.context, "browser", None)
            if browser is not None and browser.browser_type.name == "chromium":
                cdp_session = page.context.new_cdp_session(page)
                if self._uses_article_pdf_validation():
                    cdp_session.on("Network.requestWillBeSent", on_native_request)
                    cdp_session.send("Network.enable")
                cdp_session.on("Fetch.requestPaused", on_paused_response)
                cdp_session.send("Fetch.enable", {"patterns": self._chromium_pdf_patterns(native_pdf_patterns)})
            self._return_to_record_article_if_needed(page, result, doi)
            # A login can return directly to a PDF before these listeners were
            # installed. PDF.js has no article button or metadata to discover.
            current_pdf_url = str(getattr(page, "url", "") or "")
            if (self._is_pdf_candidate_url(current_pdf_url) and not self._is_supplementary_url(current_pdf_url)
                    and self._native_viewer_pdf_allowed(current_pdf_url, **fallback_options)):
                if entitlement_denied():
                    return None, "", None
                if not self._is_chromium(page):
                    begin("url", current_pdf_url, time.time())
                    body, final_url = self._capture_native_viewer_pdf(page, current_pdf_url, result, **fallback_options)
                    if body:
                        captured["bytes"], captured["url"] = body, final_url
                        return body, final_url, None
                    finish()
            else:
                current_pdf_url = ""
            # The article page's own PDF links, read before the click: the click can
            # end on a reader page that links no PDF (ASM's "PDF/EPUB", while the
            # article page shows "Download PDF", 2026-11-02).
            before_click = self._pdf_candidates(page, doi) if bound_pdf_urls is None else []
            click_started = time.time()
            fallback = getattr(self, "_fallback_pdf", None)
            if self._click_pdf_entry(page, result, doi=doi, bound=bound_pdf_urls):
                begin("click", self._clicked_pdf_control(result), click_started)
                # Until the PDF (or a block) arrives, or Firefox shows one it may
                # read in its viewer. OUP's watermarked PDF URL names no article,
                # so its response is what counts (BJS, 2026-11-01).
                pump_until(page, lambda: bool(captured["bytes"] or captured["block_reason"]
                                              or getattr(self, "_fallback_pdf", None) is not fallback) or (
                    not self._is_chromium(page) and self._pdf_viewer_present(page)
                    and self._native_viewer_pdf_allowed(str(getattr(page, "url", "") or ""), **fallback_options)), 5_000)
                if captured["bytes"] or captured["block_reason"]:
                    return captured["bytes"], str(captured["url"]), captured["block_reason"]
                if getattr(self, "_fallback_pdf", None) is not fallback:
                    # The article's own PDF link gave a PDF naming neither DOI nor title.
                    # The page's other addresses give the same file (Science's reader and
                    # PDF addresses took the rest of the minute every time, 2026-11-09):
                    # it is saved now, unconfirmed, for PaperSearch to check.
                    return None, "", None
                self._wait_past_redirect_page(page, result)  # e.g. a sign-in round trip first
                if not self._resolve_suspect_block(page, result, captured):
                    return None, "", captured["block_reason"]
                if captured["block_reason"]:
                    return None, "", captured["block_reason"]
                if not captured["bytes"] and self._pdf_step_hit_wall(page, result):
                    return None, "", None
                if not captured["bytes"]:
                    if self._uses_article_pdf_validation() and not self._wait_for_challenge(page, result):
                        return None, "", captured["block_reason"]
                    if entitlement_denied():
                        return None, "", None
                    self._raise_on_publisher_content_error(page)
                    if not self._is_chromium(page) and self._pdf_viewer_present(page):
                        # Firefox shows the clicked PDF in PDF.js: read it there
                        # instead of downloading it again (ARD, 8 MB: ~50 s).
                        body, final_url = self._capture_native_viewer_pdf(
                            page, str(getattr(page, "url", "") or ""), result, **fallback_options)
                        if body:
                            captured["bytes"] = body
                            captured["url"] = final_url
                if not captured["bytes"] and not captured["block_reason"]:
                    self._event(result, "pdf_http_refetch", str(captured["deferred_url"] or getattr(page, "url", ""))[:200])
                    body, final_url, block_reason = self._fetch_page_state_pdf(
                        page, extra_urls=[str(captured["deferred_url"])], **fallback_options)
                    if body:
                        captured["bytes"] = body
                        captured["url"] = final_url
                    if block_reason and not captured["block_reason"]:
                        captured["block_reason"] = block_reason
            # A validated PDF is already in hand. Reading the viewer DOM for
            # more links can block (Royal Society, 2026-11-04) and turn this
            # successful capture into a page-budget timeout.
            if captured["bytes"] or captured["block_reason"]:
                return captured["bytes"], str(captured["url"]), captured["block_reason"]
            candidates = [current_pdf_url, *(list(bound_pdf_urls) if bound_pdf_urls is not None
                          else [*metadata_pdf_urls, *self._pdf_candidates(page, doi), *before_click])]
            # In-page anchors (#pane-pcw-references, #addtoany …) are the same
            # document; try each URL once.
            candidates = list(dict.fromkeys(str(url).split("#", 1)[0] for url in candidates if url))
            for pdf_url in candidates:
                if captured["bytes"] or captured["block_reason"] or getattr(self, "_fallback_pdf", None) is not None:
                    break  # a PDF naming neither DOI nor title is in hand: saved unconfirmed, as after the click
                if pdf_url in rejected_pdf_urls:
                    continue
                if entitlement_denied():
                    return None, "", None
                self._raise_on_publisher_content_error(page)
                self._event(result, "pdf_candidate", pdf_url)
                begin("url", pdf_url, time.time())
                if self._should_use_async_pdf_navigation(pdf_url):
                    body, final_url = self._capture_pdf_via_async_navigation(page, pdf_url, result, captured)
                    if body:
                        captured["bytes"] = body
                        captured["url"] = final_url
                        break
                    if captured.get("login_wall"):
                        return None, "", None
                    if self._is_challenge_page(page):
                        return None, final_url, captured["block_reason"]
                    continue
                try:
                    response = goto_retrying(page, pdf_url, timeout_ms=self.pdf_timeout_ms,
                                             **({"referer": article_page} if article_page.startswith("https://") else {}))
                    if not self._resolve_suspect_block(page, result, captured):
                        return None, "", captured["block_reason"]
                    if captured["block_reason"]:
                        return None, "", captured["block_reason"]
                    if not captured["bytes"] and self._pdf_step_hit_wall(page, result):
                        return None, "", None
                    if response is not None and not captured["bytes"]:
                        response_url = str(getattr(response, "url", "") or "")
                        if self._is_partial_pdf_response(response) or self._should_defer_response_body(response_url):
                            captured["deferred_url"] = response_url
                        elif getattr(response, "status", None) == 304:
                            # Revalidated cache hit: no body to check, while the
                            # browser shows its cached copy. Not a rejection;
                            # the viewer copy is read (and validated) below.
                            self._event(result, "pdf_cached_response", response_url)
                        elif not self._response_matches_article(response, doi, **article_options):
                            if not self._refusal_answer(response):
                                rejected_pdf_urls.update(self._response_urls(response))
                        else:
                            with transfer(result):
                                body = response.body()
                            if self._accept_pdf_body(body, response_url):
                                captured["bytes"] = body
                                captured["url"] = response.url
                            elif self._uses_article_pdf_validation() and body.startswith(b"%PDF-"):
                                rejected_pdf_urls.update(self._response_urls(response))
                                self._event(result, self.adapter.pdf_rejected_event, "non_article_or_invalid_pdf")
                    if not captured["bytes"] and pdf_url not in rejected_pdf_urls:
                        body, final_url = self._capture_native_viewer_pdf(page, pdf_url, result, **fallback_options)
                        if body:
                            captured["bytes"] = body
                            captured["url"] = final_url
                    if not captured["bytes"]:
                        body, final_url, block_reason = self._fetch_page_state_pdf(
                            page, response, [str(captured["deferred_url"])], **fallback_options)
                        if body:
                            captured["bytes"] = body
                            captured["url"] = final_url
                        if block_reason and not captured["block_reason"]:
                            captured["block_reason"] = block_reason
                except Exception as exc:
                    self._event(result, "pdf_navigation_error", f"{type(exc).__name__}: {exc}")
                    if (not captured["bytes"] and not captured["block_reason"] and pdf_url not in rejected_pdf_urls
                            and not self._is_download_navigation_abort(exc)):
                        # e.g. Firefox "Response body ... was evicted" while PDF.js shows the file
                        body, final_url = self._capture_native_viewer_pdf(page, pdf_url, result, **fallback_options)
                        if body:
                            captured["bytes"] = body
                            captured["url"] = final_url
                    if (not captured["bytes"] and not captured["block_reason"] and pdf_url not in rejected_pdf_urls
                            and self._is_download_navigation_abort(exc)):
                        body, final_url = self._capture_browser_download(page, pdf_url, result, **fallback_options)
                        if body:
                            captured["bytes"] = body
                            captured["url"] = final_url
                if captured["block_reason"]:
                    return None, "", captured["block_reason"]
                if captured["bytes"]:
                    # In hand, as after the click: the tab may still show the check,
                    # Chrome's PDF having been kept out of it (a check at the PDF
                    # address, 2026-11-02).
                    break
                response_before_wait = captured.get("nav")
                if not self._wait_for_challenge(page, result):
                    return None, str(getattr(page, "url", "") or ""), captured["block_reason"]
                if entitlement_denied():
                    return None, "", None
                pump_until(page, lambda: bool(captured["bytes"]), 3_000)
                if not captured["bytes"]:
                    # A new PDF during verification can leave the tab on its
                    # completion page. Only that new response warrants retrying
                    # the candidate through the existing validated fallback.
                    response_after_wait = captured.get("nav") or {}
                    retry = ([pdf_url] if response_after_wait is not response_before_wait
                             and str(response_after_wait.get("type", "")).lower() == "application/pdf" else [])
                    body, final_url, block_reason = self._fetch_page_state_pdf(
                        page, extra_urls=[*retry, str(captured["deferred_url"])], **fallback_options)
                    if body:
                        captured["bytes"] = body
                        captured["url"] = final_url
                        break
                    if block_reason and not captured["block_reason"]:
                        captured["block_reason"] = block_reason
        finally:
            captured["closed"] = True
            # A response still being read is not wanted any more (see watchdog.abandon).
            if watchdog.abandon(captured["readers"]):
                self._event(result, "pdf_response_read_abandoned", "capture ended")
            finish()
            if cdp_session is not None:
                try:
                    cdp_session.send("Fetch.disable")
                except Exception as exc:
                    self._event(result, "browser_capture_disable_error", type(exc).__name__)
                finally:
                    try:
                        cdp_session.detach()
                    except Exception as exc:
                        self._event(result, "browser_capture_detach_error", type(exc).__name__)
            for event, listener in (("response", on_response), ("requestfailed", on_request_failed)):
                try:
                    page.remove_listener(event, listener)
                except Exception:
                    pass
        return captured["bytes"], str(captured["url"]), captured["block_reason"]

    def _article_page_answer(self, text: str) -> bool:
        """A 403/429 answer to the PDF step that is the article's own page: it prints
        the article's title, which no verification page does. World Scientific's PDF
        answered 403 with the article's abstract page and was waited on for 31 s,
        twice (2026-11-03)."""
        from .pdf_guard import title_printed

        return title_printed(text, getattr(self, "_expected_title", "") or "")

    @staticmethod
    def _clicked_pdf_control(result: DownloadResult) -> str:
        """The control the PDF step just clicked, from its event: its address, else its label."""
        detail = next((e.get("detail", "") for e in reversed(result.events) if e.get("state") == "pdf_button_clicked"), "")
        try:
            clicked = json.loads(detail)
        except (TypeError, ValueError):
            return str(detail)[:300]
        return str(clicked.get("href") or clicked.get("text") or detail)[:300] if isinstance(clicked, dict) else str(detail)[:300]

    def _record_pdf_attempt(self, result: DownloadResult, page: Any, attempt: dict[str, Any],
                            captured: dict[str, Any]) -> None:
        """One PDF attempt in the record (``pdf_attempts`` and a ``pdf_attempt``
        event): the address or control, where the tab ended, the answer's status,
        type and size, how it ended and the seconds spent. A PDF refused by the
        identity rule keeps pdf_guard's evidence (doi, title, other_dois)."""
        try:
            nav = captured.get("nav") or {}
            final = str(nav.get("url") or getattr(page, "url", "") or "")
            identity = getattr(self, "_last_identity", None)
            if captured.get("bytes"):
                outcome = "pdf ok"
            elif captured.get("block_reason"):
                outcome = f"blocked ({captured['block_reason']})"
            elif identity and identity.get("verdict") in ("other", "invalid"):
                outcome = "identity rejected" if identity.get("verdict") == "other" else "invalid pdf"
            elif captured.get("login_wall") or self._is_auth_page(final):
                outcome = "login page"
            elif self._is_challenge_page(page):
                outcome = "verification page"
            elif captured.get("landed_html") or "html" in str(nav.get("type") or ""):
                outcome = "paywall" if self._access_verdict(page) == access_rules.OUT else "html page"
            elif identity:
                outcome = "pdf without DOI or title (kept as fallback)"
            else:
                outcome = "no pdf"
            entry = {"how": attempt.get("how", ""), "url": str(attempt.get("url") or "")[:300],
                     "final_url": final[:300], "status": nav.get("status"), "type": nav.get("type") or "",
                     "size": nav.get("size") or (str(len(captured["bytes"])) if captured.get("bytes") else ""),
                     "outcome": outcome, "seconds": round(time.time() - float(attempt.get("started") or time.time()), 1)}
            if identity:
                entry["identity"] = identity
            result.pdf_attempts.append(entry)
            self._event(result, "pdf_attempt",
                        f"{entry['how']} {entry['url'][:160]} -> {outcome}; {entry['status'] or '-'} "
                        f"{entry['type'] or '-'} {entry['size'] or '-'} bytes; ended at {final[:160]}; {entry['seconds']} s")
            if outcome != "pdf ok" and not any(s["why"] == "pdf attempt failed" for s in result.snapshots):
                self._snapshot(page, result, "pdf attempt failed")
        except Exception as exc:  # the record never ends the capture
            self._event(result, "pdf_attempt_record_error", f"{type(exc).__name__}: {str(exc)[:160]}")

    # Every link's address, label and visibility in one round trip: asking per
    # link took ~25 s on a Nature page with hundreds of links.
    _LINKS_JS = """() => [...document.querySelectorAll('a[href]')].map(a => ({
        href: a.getAttribute('href') || '',
        label: [a.innerText, a.getAttribute('title'), a.getAttribute('aria-label')].join(' '),
        visible: a.getClientRects().length > 0 && getComputedStyle(a).visibility !== 'hidden',
        in_references: !!a.closest(REFERENCES)
    }))""".replace("REFERENCES", repr(_REFERENCE_AREA))

    def _click_article_link(self, page: Any, result: DownloadResult, matches: Any, detail: str, *,
                            drop_download: bool) -> bool:
        """Click the first visible link outside the references, not an attachment,
        whose address ``matches``; in this tab (and, with ``drop_download``,
        without the anchor's download hint). False without one."""
        try:
            links = page.evaluate(self._LINKS_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            links = []
        for link in links if isinstance(links, list) else []:
            try:
                href = urljoin(str(getattr(page, "url", "") or ""), str(link.get("href") or ""))
                label = str(link.get("label") or "").lower()
                if (not link.get("visible") or link.get("in_references") or self._is_supplementary_url(href)
                        or any(word in label for word in ("supplement", "supporting", "disclosure", "icmje"))
                        or not matches(href)):
                    continue
                # Bind the observed address, not its old position: dynamic pages
                # may insert/reorder anchors between discovery and clicking.
                raw_href = str(link.get("href") or "")
                escaped = "".join(f"\\{ord(char):x} " if char in '\\"\n\r\f\0' else char
                                  for char in raw_href)
                control = None
                for candidate in page.locator(f'a[href="{escaped}"]').all():
                    if not candidate.is_visible(timeout=1_500) or candidate.evaluate(_IN_REFERENCES_JS):
                        continue
                    current_label = str(candidate.evaluate(
                        "el => [el.innerText, el.getAttribute('title'), el.getAttribute('aria-label')].join(' ')"
                    ) or "").lower()
                    if any(word in current_label for word in ("supplement", "supporting", "disclosure", "icmje")):
                        continue
                    control = candidate
                    break
                if control is None:
                    continue
                control.evaluate("el => el.setAttribute('target', '_self')")
                if drop_download:
                    # A download hint makes Chrome write a UUID file even when the
                    # capture took the body (Springer, ACS).
                    control.evaluate("el => el.removeAttribute('download')")
                if not self._click_control(page, control, result, f"pdf link: {detail}"):
                    continue  # nothing was clicked (script_click_failed)
                self._event(result, "pdf_button_clicked", detail)
                return True
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                self._event(result, "pdf_button_error", f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}")
        return False

    def _click_pdf_entry(self, page: Any, result: DownloadResult, *, doi: str = "",
                         bound: frozenset[str] | None = None) -> bool:
        opened = self.adapter.open_pdf_entry(page, result)
        if opened is not None:
            return opened
        # The citation PDF bound to this DOI (ACS, JAMA, Silverchair), or this
        # capture's links naming the article (``bound``): its own control, clicked
        # so that the site's access check runs (JAMA js-pdfaccess).
        cited = frozenset(bound or self._bound_pdf_urls(page, doi) or self._metadata_pdf_urls(page, doi))
        if cited:
            return self._click_article_link(page, result, lambda href: href.split("?", 1)[0].split("#", 1)[0] in cited,
                                            "current-doi-metadata-pdf", drop_download=True)
        if self._uses_article_pdf_validation():
            bound = self._bound_pdf_urls(page, doi)
            article_options = {"article_pdf_urls": frozenset(bound)} if bound is not None else {}
            # Do not let generic first-PDF selectors click an attachment.
            # The normal candidate loop still supplies canonical DOI endpoints.
            return bool(doi) and self._click_article_link(
                page, result, lambda href: self._article_pdf_url_matches(href, doi, **article_options),
                "current-doi-article-pdf", drop_download=self.adapter.keeps_pdf_out_of_downloads)
        if self._access_gate_visible(page):
            self._event(result, "pdf_entry_gated", "get access / access through institution shown")
            return False
        # A link naming this article that serves a PDF (access_rules' D rule,
        # ``_article_pdf_link``) comes before any control that merely says "PDF".
        keys = self._article_keys(str(getattr(page, "url", "") or ""), doi)
        if doi and self._click_article_link(
                page, result, lambda href: self._article_pdf_link(href, keys, str(getattr(page, "url", "") or "")),
                "current-doi-pdf-link", drop_download=self.adapter.keeps_pdf_out_of_downloads):
            return True
        selectors = (
            "a.xpl-btn-pdf",
            ".xpl-btn-pdf",
            "a.stats-document-lh-action-downloadPdf_3",
            "[title*='PDF']",
            "[aria-label*='PDF']",
            "button:has-text('PDF')",
            "a:has-text('PDF')",
        )
        for selector in selectors:
            try:
                # The first match can be a reference's "Full Text (PDF)" link.
                control = next((c for c in page.locator(selector).all()[:20]
                                if c.is_visible() and not c.evaluate(_IN_REFERENCES_JS, timeout=2_000)), None)
                if control is None:
                    continue
                text = ""
                href = ""
                try:
                    text = control.inner_text(timeout=1_000)
                except Exception as exc:
                    if not _is_browser_error(exc):
                        raise
                try:
                    href = control.get_attribute("href", timeout=1_000) or ""
                except Exception as exc:
                    if not _is_browser_error(exc):
                        raise
                if (self._is_supplementary_url(href)
                        or re.search(r"\b(?:supplement(?:ary|al)?|supporting information|disclosure form)\b", text, re.I)):
                    continue
                detail = {"selector": selector, "text": text[:200], "href": href[:300]}
                if not self._click_control(page, control, result, f"pdf control: {selector}"):
                    continue  # nothing was clicked (script_click_failed)
                self._event(result, "pdf_button_clicked", json.dumps(detail, ensure_ascii=False))
                return True
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                # Kept, not dropped: three such 10 s click timeouts made Sage's silent
                # 30 s before its PDF (a toolbar copy outside the viewport, 2026-11-02).
                self._event(result, "pdf_button_error",
                            f"{selector}: {type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}")
                continue

        try:
            clicked = page.evaluate(
                """
                () => {
                  const REFERENCE_AREA = "#references, .references, #bibliography, .bibliography, .ref-list, .biblioentry, .citations, .citation, .c-article-references";
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const textOf = (el) => [
                    el.innerText || '',
                    el.textContent || '',
                    el.value || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.className || '',
                    el.id || ''
                  ].join(' ').replace(/\\s+/g, ' ').trim();
                  const controls = [...document.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]')]
                    .filter(visible);
                  // Sharing, login, password, purchase and advertising actions, and
                  // other sites, are never the PDF (_NOT_PDF_LINK in batch_pdf_urls.py).
                  const NOT_PDF = /\\/action\\/(?:showlogin|clickthrough|requestresetpassword|ssostart|registration|showpurchase)|\\/(?:login|logon|signin|sign-in|register|registration|share|sharer|cart|checkout|purchase|subscribe)(?:[\\/.]|$)|password|\\/ads?\\/|doubleclick|addtoany/i;
                  const isPdfControl = (el) => {
                    const haystack = textOf(el).toLowerCase();
                    const raw = ((el.href || el.getAttribute('href') || el.getAttribute('formaction') || '') + '');
                    let target = null;
                    try { target = raw && !/^javascript:/i.test(raw) ? new URL(raw, location.href) : null; } catch (_) {}
                    const site = (host) => host.split('.').slice(-2).join('.');
                    if (target && (site(target.hostname) !== site(location.hostname) || NOT_PDF.test(target.pathname))) return false;
                    const href = target ? (target.pathname + target.search).toLowerCase() : '';
                    if (href.includes('/servlet/linkout') || el.closest(REFERENCE_AREA)) return false;
                    if (/supplement|supporting.information|disclosure.form|moesm/.test(haystack + ' ' + href)
                        || href.includes('/mediaobjects/') || href.includes('/esm/')) return false;
                    if (haystack.includes('reference') || haystack.includes('citation')) return false;
                    if (haystack.includes('download references')) return false;
                    return /(^|\\s)pdf(\\s|$)/i.test(textOf(el))
                      || haystack.includes('download pdf')
                      || haystack.includes('xpl-btn-pdf')
                      || href.includes('/pdf')
                      || href.includes('stamppdf')
                      || href.includes('/stamp/');
                  };
                  const target = controls.find(isPdfControl);
                  if (!target) return null;
                  const detail = {
                    text: textOf(target).slice(0, 200),
                    href: ((target.href || target.getAttribute('href') || target.getAttribute('formaction') || '') + '').slice(0, 300)
                  };
                  target.click();
                  return detail;
                }
                """
            )
            if isinstance(clicked, (dict, str)) and clicked:
                self._event(result, "pdf_button_clicked", json.dumps(clicked, ensure_ascii=False))
                return True
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            self._event(result, "pdf_button_error", f"{type(exc).__name__}: {exc}")
        return False


    def _fetch_page_state_pdf(
        self,
        page: Any,
        response: Any | None = None,
        extra_urls: list[str] | None = None,
        *,
        doi: str = "",
        rejected_urls: set[str] | None = None,
        article_pdf_urls: frozenset[str] | None = None,
    ) -> tuple[bytes | None, str, str | None]:
        """Try to fetch a PDF from URLs visible in the page state.

        Returns ``(body, url, block_reason)`` — ``block_reason`` is propagated
        up from :meth:`_fetch_pdf_url` so an IP block observed on the plain-HTTP
        fallback path is not lost.
        """
        if self._is_challenge_page(page) or self._institution_pdf_entitlement_missing(page):
            return None, "", None
        validate_article = self._uses_article_pdf_validation()
        article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
        if validate_article and not doi:
            return None, "", None
        for fallback_url in self._page_state_pdf_urls(page, response, extra_urls):
            if not self._is_pdf_candidate_url(fallback_url) or self._is_supplementary_url(fallback_url):
                continue
            if validate_article and (fallback_url in (rejected_urls or ())
                          or not self._article_pdf_url_matches(fallback_url, doi, **article_options)):
                continue
            body, final_url, block_reason = self._fetch_pdf_url_with_browser_state(
                fallback_url, page, **({"doi": doi, **article_options} if validate_article else {}))
            if validate_article and final_url in (rejected_urls or ()):
                continue
            if body and self._accept_pdf_body(body, final_url):
                return body, final_url, None
            if block_reason:
                # Keep trying only the URL that produced a real PDF; but remember
                # the block signal so the caller can escalate even if no PDF is
                # ever captured.
                return None, final_url, block_reason
        return None, "", None

    def _page_state_pdf_urls(
        self,
        page: Any,
        response: Any | None = None,
        extra_urls: list[str] | None = None,
    ) -> list[str]:
        raw_values: list[str] = list(extra_urls or [])
        if response is not None:
            raw_values.append(str(getattr(response, "url", "") or ""))
        raw_values.append(str(getattr(page, "url", "") or ""))
        raw_values.append(self._title(page))

        urls: list[str] = []
        for value in raw_values:
            if value.startswith("http"):
                urls.append(value)
            urls.extend(match.group(0).rstrip(").,;") for match in PDF_URL_RE.finditer(value))
        return list(dict.fromkeys(url for url in urls if url.startswith("http")))

    def _should_defer_response_body(self, url: str) -> bool:
        return self.adapter.defers_pdf_response_body and self._is_pdf_candidate_url(url)

    def _capture_browser_download(
        self, page: Any, pdf_url: str, result: DownloadResult, *,
        doi: str = "", rejected_urls: set[str] | None = None,
        article_pdf_urls: frozenset[str] | None = None,
    ) -> tuple[bytes | None, str]:
        article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
        if self._uses_article_pdf_validation() and (
            not doi or not self._article_pdf_url_matches(pdf_url, doi, **article_options)
            or pdf_url in (rejected_urls or ())
        ):
            return None, pdf_url
        expect_download = getattr(page, "expect_download", None)
        if expect_download is None:
            return None, pdf_url
        try:
            with expect_download(timeout=self.pdf_timeout_ms) as download_info:
                try:
                    goto_retrying(page, pdf_url, timeout_ms=self.pdf_timeout_ms)
                except Exception as exc:
                    if not self._is_download_navigation_abort(exc):
                        raise
            download = download_info.value
            if (self._uses_article_pdf_validation()
                    and self._is_supplementary_url(str(getattr(download, "suggested_filename", "") or ""))):
                return None, pdf_url
            with transfer(result):
                path = download.path()
            body = Path(path).read_bytes()
            final_url = str(getattr(download, "url", "") or pdf_url)
            if self._uses_article_pdf_validation() and (
                not self._article_pdf_url_matches(final_url, doi, **article_options)
                or pdf_url in (rejected_urls or ()) or final_url in (rejected_urls or ())
            ):
                return None, final_url
            if self._accept_pdf_body(body, final_url):
                return body, final_url
        except Exception as exc:
            self._event(result, "download_capture_error", f"{type(exc).__name__}: {exc}")
        return None, pdf_url

    @staticmethod
    def _is_chromium(page: Any) -> bool:
        browser = getattr(getattr(page, "context", None), "browser", None)
        return browser is not None and getattr(browser.browser_type, "name", "") == "chromium"

    def _viewer_pdf_for_record(self, tab: Any, doi: str, *,
                               article_pdf_urls: frozenset[str] | None = None) -> bytes | None:
        """The PDF a Firefox tab shows in PDF.js, when it may belong to this article
        (at the capture's bound citation PDF, ``article_pdf_urls``, when it has one)."""
        url = str(getattr(tab, "url", "") or "")
        article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
        if self._uses_article_pdf_validation() and not self._article_pdf_url_matches(url, doi, **article_options):
            return None
        if not self._pdf_viewer_present(tab):
            return None
        body = self._capture_loaded_pdf_viewer(tab, url)
        return body if body and self._accept_pdf_body(body, url) else None

    @staticmethod
    def _pdf_viewer_present(page: Any) -> bool:
        """The page is Firefox's own PDF.js viewer showing a PDF document.

        A publisher's HTML reader built on PDF.js (Wiley's ePDF) has a
        ``PDFViewerApplication`` too, but no PDF document to read here.
        """
        try:
            return bool(page.evaluate("""() => { try { const w = window.wrappedJSObject || window;
                const doc = w.document;
                const uri = String((doc && doc.documentURI) || "");
                return !!w.PDFViewerApplication && (uri.startsWith("resource://pdf.js/")
                    || String((doc && doc.contentType) || "") === "application/pdf");
                } catch (_) { return false; } }"""))
        except Exception:
            return False

    def _native_viewer_pdf_allowed(
        self, pdf_url: str, *, doi: str = "", rejected_urls: set[str] | None = None,
        article_pdf_urls: frozenset[str] | None = None,
    ) -> bool:
        """Whether a PDF shown at ``pdf_url`` may be read from the viewer: with
        article validation, only at a URL that names this article."""
        article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
        return not self._uses_article_pdf_validation() or bool(
            doi and self._article_pdf_url_matches(pdf_url, doi, **article_options)
            and pdf_url not in (rejected_urls or ()))

    def _capture_native_viewer_pdf(
        self, page: Any, pdf_url: str, result: DownloadResult, *,
        doi: str = "", rejected_urls: set[str] | None = None,
        article_pdf_urls: frozenset[str] | None = None,
    ) -> tuple[bytes | None, str]:
        """Read the PDF from Firefox's built-in viewer after navigating to ``pdf_url``.

        Firefox can evict the navigation response body once PDF.js renders it,
        so ``response.body()`` fails although the document is on screen. The
        viewer is polled until its document is fully loaded (bounded by the PDF
        timeout). A document read and judged by its text (kept as the fallback,
        or another article's) ends the wait: read again it says the same.
        Chromium pages have no ``PDFViewerApplication`` and return after one probe.
        """
        if not self._native_viewer_pdf_allowed(
                pdf_url, doi=doi, rejected_urls=rejected_urls, article_pdf_urls=article_pdf_urls):
            return None, pdf_url
        started = time.time()
        deadline = started + min(60.0, max(10.0, self.pdf_timeout_ms / 1000))
        while time.time() < deadline:
            is_viewer = self._pdf_viewer_present(page)
            if not is_viewer and time.time() - started > 5:
                return None, pdf_url
            if is_viewer:
                body = self._capture_loaded_pdf_viewer(page, pdf_url)
                self._last_identity = None
                if body and self._accept_pdf_body(body, pdf_url):
                    self._event(result, "pdf_native_viewer_captured", f"{len(body)} bytes")
                    self._note_wait(result, "the PDF viewer", started, "pdf read")
                    return body, pdf_url
                if body and self._last_identity:
                    # A correction notice printing its own DOI and the corrected
                    # article's was read again for 60 s (NEJM Evidence, 2026-11-03).
                    self._note_wait(result, "the PDF viewer", started, "pdf read, not settled by its text")
                    return None, pdf_url
            page.wait_for_timeout(2 * POLL_MS)
        self._note_wait(result, "the PDF viewer", started, "no readable PDF in its time")
        return None, pdf_url

    # A new document has finished loading in the tab since the PDF navigation
    # started (the marker set before it is gone): its content type, else "".
    _NAVIGATED_DOCUMENT_JS = ("() => !window.__paperSearchPdfNavigation && document.readyState === 'complete'"
                              " ? String(document.contentType || '') : ''")
    # How long a finished HTML page may still move on by script (a redirect page)
    # before the PDF address counts as failed; longer at an address that itself
    # looks like a PDF's (ScienceDirect's /pdfft page forwards to the PDF).
    HTML_LANDING_GRACE_SEC = 3
    HTML_LANDING_GRACE_AT_PDF_ADDRESS_SEC = 10

    def _landed_on_html(self, page: Any, landing: dict[str, Any]) -> str:
        """The PDF navigation has ended on an ordinary web page, no PDF and no
        verification, for its grace time: the page's URL; "" while it may still
        become the PDF. The Lancet's /action/showPdf and /pdfs/....pdf showed the
        article's own page to a personal account and each waited out 60 s
        (2026-11-02); JAMA's articlepdf redirects to the article the same way."""
        try:
            kind = page.evaluate(self._NAVIGATED_DOCUMENT_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return ""  # the document is changing right now
        url = str(getattr(page, "url", "") or "")
        if (not isinstance(kind, str) or "html" not in kind.lower() or self.adapter.is_redirect_page(url)
                or self._challenge_shell(page)):
            landing.clear()
            return ""
        if landing.get("url") != url:
            landing.update(url=url, since=time.time())
            return ""
        grace = (self.HTML_LANDING_GRACE_AT_PDF_ADDRESS_SEC if self._is_pdf_candidate_url(url)
                 else self.HTML_LANDING_GRACE_SEC)
        return url if time.time() - landing["since"] >= grace else ""

    def _capture_pdf_via_async_navigation(
        self,
        page: Any,
        pdf_url: str,
        result: DownloadResult,
        captured: dict[str, Any] | None = None,
    ) -> tuple[bytes | None, str]:
        try:
            page.evaluate("(url) => { window.__paperSearchPdfNavigation = true; window.location.href = url; }", pdf_url)
            self._event(result, "pdf_async_navigation", pdf_url)
        except Exception as exc:
            self._event(result, "pdf_async_navigation_error", f"{type(exc).__name__}: {exc}")
            return None, ""

        started = time.time()
        outcome = {"why": "its time ran out"}
        try:
            return self._follow_pdf_navigation(page, pdf_url, result, captured, started, outcome)
        finally:
            self._note_wait(result, f"PDF navigation {pdf_url[:160]}", started, outcome["why"])

    def _follow_pdf_navigation(self, page: Any, pdf_url: str, result: DownloadResult, captured: dict[str, Any] | None,
                               started: float, outcome: dict[str, str]) -> tuple[bytes | None, str]:
        timeout_sec = max(10, int(self.pdf_timeout_ms / 1000))
        deadline = started + timeout_sec
        attempted: set[str] = set()
        wall_checked = time.time()
        landing: dict[str, Any] = {}
        while time.time() < deadline:
            page.wait_for_timeout(200)
            if captured and captured["bytes"]:
                outcome["why"] = "pdf"
                return captured["bytes"], str(captured["url"])
            if time.time() - wall_checked >= 2:
                # The Lancet's showPdf, with only a personal account, waited out its
                # 60 s on a page that was no PDF (2026-11-02).
                wall_checked = time.time()
                if self._pdf_step_hit_wall(page, result, captured):
                    outcome["why"] = "login or access wall"
                    return None, ""
                landed = self._landed_on_html(page, landing)
                if landed:
                    outcome["why"] = "html page"
                    self._event(result, "pdf_candidate_html", f"{landed[:200]} | {self._title(page)[:80]} "
                                f"after {time.time() - started:.0f} s")
                    if captured is not None:
                        captured["landed_html"] = landed
                    return None, ""
            self._raise_on_publisher_content_error(page)
            if self._is_challenge_page(page):
                # Human verification gets its own budget: the user's time must
                # not use up the PDF step, and once the check clears the PDF
                # gets its full time again.
                challenge_deadline = time.time() + max(self.page_wait_sec, timeout_sec)
                if not self._wait_for_challenge_with_deadline(page, result, challenge_deadline):
                    return None, str(getattr(page, "url", "") or "")
                deadline = time.time() + timeout_sec
                attempted.clear()
                continue
            # Firefox can leave the native PDF.js shell visible while
            # the document is already available (or while its loading task is
            # idle).  Read that document in the viewer's own realm before
            # falling back to a second HTTP request, which may lose the
            # authenticated browser session or signed URL.
            viewer_body = self._capture_loaded_pdf_viewer(page, pdf_url)
            if viewer_body:
                return viewer_body, pdf_url
            for candidate_url in self._page_state_pdf_urls(page):
                if candidate_url in attempted:
                    continue
                attempted.add(candidate_url)
                if not self._is_pdf_candidate_url(candidate_url) or self._is_supplementary_url(candidate_url):
                    continue
                self._event(result, "pdf_state_candidate", candidate_url)
                body, final_url, _block_reason = self._fetch_pdf_url_with_browser_state(candidate_url, page)
                if body:
                    return body, final_url
            page.wait_for_timeout(2 * POLL_MS)
        return None, ""

    def _capture_loaded_pdf_viewer(self, page: Any, source_url: str, *,
                                   output: Path | None = None, max_bytes: int | None = None) -> bytes | Path | None:
        """Read a PDF already loaded by Firefox's native PDF.js viewer.

        The viewer runs in a privileged native realm.  Accessing its
        ``PDFViewerApplication`` through the automation realm can produce
        Xray wrappers, so the script uses ``wrappedJSObject`` and native
        ``Blob``/``FileReader`` constructors.  An initialized but idle viewer
        is started once per source URL; a marker on the native window prevents
        repeated ``app.open`` calls while the document loads.
        """
        script = r"""
        async ({sourceUrl, maxBytes}) => {
            try {
                const nativeWindow = window.wrappedJSObject || window;
                const nativeLocation = String(nativeWindow.location?.href || "");
                const nativeDocument = nativeWindow.document;
                const documentUri = String(nativeDocument?.documentURI || "");
                const app = nativeWindow.PDFViewerApplication;
                // Older builds expose the resource:// viewer shell; Firefox 156
                // keeps the https PDF URL on a document whose
                // contentType is application/pdf.
                const isNativePdfViewer = nativeLocation.startsWith("resource://pdf.js/")
                    || documentUri.startsWith("resource://pdf.js/")
                    || (!!app && String(nativeDocument?.contentType || "") === "application/pdf");
                if (!isNativePdfViewer || !app) return null;
                // In some Firefox builds location.href is the signed source
                // URL; in others it is the resource:// viewer shell.  Prefer
                // the former and otherwise use the URL supplied by Python.
                const target = /^https?:/i.test(nativeLocation)
                    ? nativeLocation : String(sourceUrl || "");
                const attempts = nativeWindow.__schoolPdfViewerOpenAttempts
                    || (nativeWindow.__schoolPdfViewerOpenAttempts = Object.create(null));

                if (!app.pdfDocument && !app.pdfLoadingTask && app.initialized === true
                    && /^https?:/i.test(target) && !attempts[target]) {
                    attempts[target] = true;
                    try {
                        const args = nativeWindow.JSON.parse(
                            nativeWindow.JSON.stringify({url: target})
                        );
                        app.open(args);
                    } catch (_) {
                        // Keep the marker: a failed initialization must not be
                        // retried on every polling tick.
                    }
                    return null;
                }

                if (!app.pdfDocument || typeof app.pdfDocument.getData !== "function") {
                    return null;
                }
                if (maxBytes) {
                    const info = await app.pdfDocument.getDownloadInfo();
                    if (info.length > maxBytes) return {oversized: info.length};
                }
                const data = await app.pdfDocument.getData();
                if (maxBytes && data.byteLength > maxBytes) return {oversized: data.byteLength};
                // Crossing the Xray/automation boundary with one large Blob
                // causes a large transient allocation. Keep the native bytes
                // here and transfer at most 1 MiB per bridge call instead.
                if (data.byteLength > 1024 * 1024) {
                    const token = String(Date.now()) + ":" + String(Math.random());
                    nativeWindow.__schoolPdfTransfer = {token, data};
                    return {transfer: token, size: data.byteLength};
                }
                // The viewer's own Blob cannot iterate an array handed over the
                // Xray boundary (Firefox 156: "Permission denied to access
                // property Symbol.iterator"); this realm's constructors can.
                let blob;
                try {
                    blob = new Blob([data], {type: "application/pdf"});
                } catch (_) {
                    blob = new nativeWindow.Blob([data], {type: "application/pdf"});
                }
                return await new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result);
                    reader.onerror = () => resolve(null);
                    reader.readAsDataURL(blob);
                });
            } catch (_) {
                return null;
            }
        }
        """
        try:
            encoded = page.evaluate(script, {"sourceUrl": source_url, "maxBytes": max_bytes})
        except Exception:
            return None
        if isinstance(encoded, dict) and "oversized" in encoded:
            from .supplements import SupplementTooLarge
            raise SupplementTooLarge(encoded["oversized"])
        if isinstance(encoded, dict) and isinstance(encoded.get("transfer"), str):
            return self._read_viewer_chunks(page, encoded["transfer"], encoded.get("size"), output=output)
        if not isinstance(encoded, str) or not encoded.startswith("data:"):
            return None
        try:
            _, payload = encoded.split(",", 1)
            body = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError):
            return None
        if len(body) > MIN_PDF_BYTES and body.startswith(b"%PDF-"):
            if output is not None:
                output.write_bytes(body)
                return output
            return body
        return None

    @staticmethod
    def _read_viewer_chunks(page: Any, token: str, size: Any, *, output: Path | None = None) -> bytes | Path | None:
        """Bound bridge/Blob allocations while preserving exact bytes and cleanup."""
        read_chunk = r"""async ({token, offset, length}) => {
            try {
                const w = window.wrappedJSObject || window;
                const transfer = w.__schoolPdfTransfer;
                if (!transfer || transfer.token !== token) return null;
                const part = transfer.data.subarray(offset, offset + length);
                let blob;
                try { blob = new Blob([part], {type: "application/pdf"}); }
                catch (_) { blob = new w.Blob([part], {type: "application/pdf"}); }
                return await new Promise(resolve => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result);
                    reader.onerror = () => resolve(null);
                    reader.readAsDataURL(blob);
                });
            } catch (_) { return null; }
        }"""
        body = bytearray()
        sink = None
        complete = False
        try:
            if type(size) is not int or size <= MIN_PDF_BYTES:
                return None
            if output is not None:
                sink = output.open("wb")
            for offset in range(0, size, 1024 * 1024):
                length = min(1024 * 1024, size - offset)
                encoded = page.evaluate(read_chunk, {"token": token, "offset": offset, "length": length})
                if not isinstance(encoded, str) or not encoded.startswith("data:"):
                    return None
                part = base64.b64decode(encoded.split(",", 1)[1], validate=True)
                if len(part) != length or (offset == 0 and not part.startswith(b"%PDF-")):
                    return None
                if sink is not None:
                    sink.write(part)
                else:
                    body.extend(part)
            complete = True
            if output is not None:
                return output
            return bytes(body) if body.startswith(b"%PDF-") else None
        except Exception:
            if output is not None:
                raise
            return None
        finally:
            if sink is not None:
                sink.close()
            if output is not None and not complete:
                output.unlink(missing_ok=True)
            try:
                page.evaluate("""token => { const w = window.wrappedJSObject || window;
                    if (w.__schoolPdfTransfer?.token === token) delete w.__schoolPdfTransfer; }""", token)
            except Exception:
                pass  # Navigation/closing already discarded the old viewer realm.

    def _should_use_async_pdf_navigation(self, url: str) -> bool:
        return self.adapter.async_pdf_navigation and self._is_pdf_candidate_url(url)

    @staticmethod
    def _is_download_navigation_abort(exc: Exception) -> bool:
        message = str(exc)
        return "Download is starting" in message or "net::ERR_ABORTED" in message

    def _fetch_pdf_url_with_browser_state(self, url: str, page: Any, *, doi: str = "",
                                         article_pdf_urls: frozenset[str] | None = None) -> tuple[bytes | None, str, str | None]:
        if self._uses_article_pdf_validation():
            article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
            return self._fetch_pdf_url(url, page=page, doi=doi, **article_options)
        try:
            signature = inspect.signature(self._fetch_pdf_url)
        except (TypeError, ValueError):
            return self._fetch_pdf_url(url)
        accepts_page = "page" in signature.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
        )
        if accepts_page:
            return self._fetch_pdf_url(url, page=page)
        return self._fetch_pdf_url(url)

    def _fetch_pdf_url(self, url: str, *, page: Any | None = None, doi: str = "",
                       article_pdf_urls: frozenset[str] | None = None) -> tuple[bytes | None, str, str | None]:
        """Fetch a PDF URL with the browser's cookies/headers.

        Returns ``(body, final_url, block_reason)``. ``block_reason`` is
        ``"ip_blocked"`` when the publisher returned a 403/429 or an IP-block
        page (so the caller can stop the batch instead of churning); ``None``
        otherwise.
        """
        article_options = {"article_pdf_urls": article_pdf_urls} if article_pdf_urls is not None else {}
        if self._uses_article_pdf_validation() and (not doi or not self._article_pdf_url_matches(url, doi, **article_options)):
            return None, url, None
        headers = self._pdf_request_headers(url, page)
        # Resolve the egress proxy for this page's context so plain-HTTP
        # requests go through the same proxy as the browser.  When no
        # proxy-pool is configured the lookup returns None (direct IP).
        proxies = None
        if page is not None:
            ctx = getattr(page, "context", None)
            if ctx is not None:
                ctx_proxy = self._context_proxy.get(id(ctx))
                if ctx_proxy:
                    from ..network import proxy_dict
                    proxies = proxy_dict(ctx_proxy)
        try:
            with transfer(getattr(self, "_item_result", None)):
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=(10, 60),
                    allow_redirects=True,
                    proxies=proxies,
                )
            # This request is not the browser: a 403/429 here (bot protection,
            # ScienceDirect's challenge, 2026-10-31) says nothing about the
            # browser's access and must not stop the batch. Only a block page counts.
            if self._is_ip_block_response(None, resp.text):
                return None, resp.url, "ip_blocked"
            if self._is_partial_pdf_response(resp):
                return None, resp.url, None
            if not self._response_matches_article(resp, doi, **article_options):
                return None, resp.url, None
            body = resp.content
            if self._accept_pdf_body(body, resp.url):
                return body, resp.url, None
        except Exception:
            return None, url, None
        return None, resp.url, None

    def _pdf_request_headers(self, url: str, page: Any | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"User-Agent": "scansci-pdf/1.5"}
        if page is None:
            return headers

        try:
            user_agent = page.evaluate("() => navigator.userAgent")
            if isinstance(user_agent, str) and user_agent.strip():
                headers["User-Agent"] = user_agent.strip()
        except Exception:
            pass

        referer = str(getattr(page, "url", "") or "")
        if referer.startswith("http"):
            headers["Referer"] = referer

        try:
            context = getattr(page, "context", None)
            cookies = context.cookies(url) if context is not None else []
            cookie_header = "; ".join(
                f"{cookie.get('name')}={cookie.get('value')}"
                for cookie in cookies
                if cookie.get("name") and cookie.get("value") is not None
            )
            if cookie_header:
                headers["Cookie"] = cookie_header
        except Exception:
            pass
        return headers

    def _uses_article_pdf_validation(self) -> bool:
        return self.adapter.validates_article_pdf

    @staticmethod
    def _refusal_answer(response: Any) -> bool:
        """A 403/429: a block or a human check at the address (``suspect_block``),
        no answer about whose PDF it serves. It never refuses the address: the
        check loads the same address again and the PDF comes (Karger behind
        Cloudflare answered 200 application/pdf after its 403, and the refused
        address kept that PDF from being read, 2026-11-02)."""
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "status_code", None)
        return status in _IP_BLOCK_STATUS_CODES

    @staticmethod
    def _is_partial_pdf_response(response: Any) -> bool:
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "status_code", None)
        headers = getattr(response, "headers", {}) or {}
        return status == 206 or any(
            isinstance(value, str) and bool(value.strip())
            for value in (headers.get("content-range"), headers.get("Content-Range"))
        )

    def _accept_pdf_body(self, body: bytes, url: str) -> bool:
        """A complete PDF from a non-supplementary URL whose front matter names
        this article (its DOI or exact title). A PDF without either is kept as
        the capture's fallback; one that labels another article is refused."""
        if not body.startswith(b"%PDF-") or len(body) <= MIN_PDF_BYTES:
            return False
        if self._is_supplementary_url(url):
            return False
        if self.adapter.requires_complete_pdf:
            # Never label a truncated or damaged transfer as saved.
            from .. import pdf_text

            if not pdf_text.complete(body):
                return False
            try:
                if not pdf_text.page_count(body):
                    return False
            except pdf_text.PdfError:
                return False
        from .pdf_guard import classify_with_evidence

        verdict, found = classify_with_evidence(body, getattr(self, "_capture_doi", "") or "",
                                                getattr(self, "_expected_title", "") or "")
        if verdict == "match":
            return True
        self._last_identity = {"verdict": verdict, **({"doi": found.get("doi"), "title": found.get("title"),
                                                       "other_dois": list(found.get("other_dois") or ())[:5],
                                                       "not_article": found.get("not_article")} if found else {})}
        if verdict == "unknown" and getattr(self, "_fallback_pdf", None) is None:
            self._fallback_pdf = (body, url)
        return False
