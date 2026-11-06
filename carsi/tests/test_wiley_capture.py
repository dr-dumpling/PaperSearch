"""In-memory Wiley selection/capture and shared entitlement regressions.

No package startup, real config, cookies, browser, or network. Uses the existing
PyMuPDF dependency to construct parseable synthetic PDFs entirely in memory.
Run with the existing venv: python -B -m unittest discover -s tests -p test_wiley_capture.py -v
"""

import importlib
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import DEFAULT, Mock, patch

import pymupdf


SOURCE = Path(__file__).resolve().parents[1] / "paper_search_carsi"
PACKAGE = "_wiley_capture_test"
DOI = "10.1002/offline.2026"
ARTICLE = "https://onlinelibrary.wiley.com/doi/" + DOI
PDF = "https://onlinelibrary.wiley.com/doi/pdfdirect/" + DOI
SUPPLEMENT = "https://onlinelibrary.wiley.com/doi/suppl/" + DOI + "/supinfo/form.pdf"


def pdf_bytes(heading="Offline article title", pages=1, doi=DOI):
    with pymupdf.open() as doc:
        for index in range(pages):
            page = doc.new_page()
            page.insert_text((40, 50), heading if index == 0 else "Continuation")
            page.insert_text((40, 90), ("Offline article title\nDOI: " if doi == DOI else "Another article\nDOI: ") + doi)
            page.insert_text((40, 140), "Abstract\nWe completed an ICMJE disclosure form.\nResults")
        # Legal trailing PDF comment keeps tiny fixtures above the existing size gate.
        return doc.tobytes() + b"\n%" + b"x" * 6000


def link_rows(test, script):
    """The page's link list for the one-round-trip PDF link lookup; otherwise
    whatever the test set as evaluate.return_value."""
    if "querySelectorAll('a[href]')" in script and "visible:" in script:
        return [{"href": c.get_attribute("href"), "label": c.inner_text(), "visible": c.is_visible()}
                for c in test.controls]
    return DEFAULT


class Handlers(list):
    """Playwright allows the capture and activity observer to share an event."""
    def __call__(self, *args):
        for callback in list(self):
            callback(*args)


class WileyCaptureTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(sys.modules))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.object(socket, "getaddrinfo", side_effect=AssertionError("network forbidden")))
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(SOURCE)]
        sys.modules[PACKAGE] = package
        for _sub in ("browser", "engine", "publishers", "extractors", "_core"):
            _m = types.ModuleType(PACKAGE + "." + _sub)
            _m.__path__ = [str(SOURCE / _sub)]
            sys.modules[_m.__name__] = _m

        def module(name, **attrs):
            value = types.ModuleType(PACKAGE + "." + name)
            value.__dict__.update(attrs)
            sys.modules[value.__name__] = value
            return value

        module("config", load_config=Mock(side_effect=AssertionError("config forbidden")),
               parse_proxy_pool=lambda *a, **k: [],
               DEFAULT_CONFIG={"browser_stall_notify_after": 30, "browser_page_wait_timeout": 60})
        module("progress_reporter", update=Mock(), report_stage=Mock(),
               has_attention=Mock(return_value=False), set_attention=Mock(),
               update_attention_deadline=Mock(), clear_attention=Mock())
        self.extractor = module("extractors.pdf_extractor", extract_from_bytes=Mock(return_value="Offline article"))
        module("extractors", pdf_extractor=self.extractor)
        self.batch = importlib.import_module(PACKAGE + ".engine.batch")
        self.profiles = importlib.import_module(PACKAGE + ".publishers.profiles")
        self.router = importlib.import_module(PACKAGE + ".engine.router")
        self.d = self.batch.PublisherBatchDownloader(config={}, profile=self.profiles.WILEY_PROFILE)
        self.enterContext(patch.object(self.batch.time, "sleep"))
        self.d._save_publisher_session = Mock(side_effect=AssertionError("credential I/O forbidden"))
        self.d._write_diagnostic = Mock()
        self.d._fetch_pdf_url_with_browser_state = Mock(return_value=(None, "", None))
        self.d._dismiss_cookie_banners = Mock()
        self.handlers = {}

        def add_listener(event, callback):
            self.handlers.setdefault(event, Handlers()).append(callback)

        def remove_listener(event, callback):
            listeners = self.handlers.get(event, [])
            if callback in listeners:
                listeners.remove(callback)
            if not listeners:
                self.handlers.pop(event, None)

        self.body = "Article abstract"
        self.controls = []
        self.page = types.SimpleNamespace(
            url=ARTICLE, context=types.SimpleNamespace(browser=None),
            title=Mock(return_value="Article title"),
            wait_for_timeout=Mock(), wait_for_load_state=Mock(), evaluate=Mock(return_value=[], side_effect=lambda script, *a: link_rows(self, script)),
            on=add_listener, remove_listener=remove_listener,
            goto=Mock(), close=Mock(), is_closed=Mock(return_value=False),
        )
        self.page.locator = self.locator
        self.result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        self.article = pdf_bytes()
        self.disclosure = pdf_bytes("ICMJE DISCLOSURE FORM", pages=6)
        self.other = pdf_bytes("Another article", doi="10.1002/other.2026")  # e.g. a stale viewer tab
        self.d._capture_doi = DOI  # set by _capture_pdf; direct helper calls need it too

    def locator(self, selector):
        if selector == "head > title":
            return types.SimpleNamespace(first=types.SimpleNamespace(text_content=self.page.title))
        if selector == "body":
            return types.SimpleNamespace(inner_text=lambda **kw: self.body)
        if selector == "a[href]":
            return types.SimpleNamespace(all=lambda: self.controls, nth=lambda index: self.controls[index])
        if selector.startswith('a[href="'):
            href = selector[len('a[href="'):-2]
            return types.SimpleNamespace(all=lambda: [c for c in self.controls if c.get_attribute("href") == href])
        return Mock()


    def control(self, href, text="PDF"):
        element = Mock()
        element.get_attribute.side_effect = lambda name, **kw: href if name == "href" else ""
        element.inner_text.return_value = text
        element.is_visible.return_value = True
        element.evaluate.side_effect = lambda script: text if "[el.innerText" in script else False
        return element

    def response(self, url, body, origin=None, status=200, disposition=""):
        request = types.SimpleNamespace(url=url, redirected_from=None)
        if origin:
            request.redirected_from = types.SimpleNamespace(url=origin, redirected_from=None)
        return types.SimpleNamespace(url=url, status=status, request=request,
            headers={"content-type": "application/pdf", "content-disposition": disposition},
            body=Mock(return_value=body), text=lambda: "Forbidden" if status==403 else "")

    def capture(self, response_factory):
        def navigate(url, **kw):
            response = response_factory(url)
            self.page.url = response.url
            self.handlers["response"](response)
            return response
        self.page.goto.side_effect = navigate
        return self.d._capture_pdf(self.page, DOI, self.result)

    def enable_http_fixture(self, response):
        # Restore the real HTTP fallback, replacing only the transport and
        # cookie-header construction. No credential store or socket is touched.
        del self.d._fetch_pdf_url_with_browser_state
        self.d._pdf_request_headers = Mock(return_value={})
        return self.enterContext(patch.object(self.batch.requests, "get", return_value=response))

    def http_response(self, url=PDF, disposition="", history=()):
        return types.SimpleNamespace(
            url=url, status_code=200, content=self.article, text="",
            headers={"Content-Disposition": disposition}, history=list(history),
            request=types.SimpleNamespace(url=url),
        )

    def test_browser_disposition_rejection_cannot_be_reaccepted_by_http(self):
        transport = self.enable_http_fixture(self.http_response())
        self.d._pdf_candidates = Mock(return_value=[PDF])
        # No disclosure heading: rejection must survive through metadata alone,
        # even if the HTTP response would omit the filename on replay.
        body, _, _ = self.capture(lambda url: self.response(
            url, self.article, disposition='attachment; filename="ICMJE-disclosure.pdf"'))
        self.assertIsNone(body)
        transport.assert_not_called()

    def test_rejected_browser_endpoint_preserves_other_article_http_fallback(self):
        other = PDF.replace("/pdfdirect/", "/pdf/")
        transport = self.enable_http_fixture(self.http_response(other))
        self.d._pdf_candidates = Mock(return_value=[PDF, other])
        def responses(url):
            if url == PDF:
                return self.response(url, self.article, disposition='attachment; filename="ICMJE-disclosure.pdf"')
            return self.response(url, b"<html>PDF viewer</html>")
        self.assertEqual(self.capture(responses)[0], self.article)
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args[0], other)

    def test_http_rejects_disclosure_filename_without_first_page_marker(self):
        transport = self.enable_http_fixture(self.http_response(disposition='attachment; filename="ICMJE-disclosure.pdf"'))
        self.page.url = PDF
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page, doi=DOI)[0])
        transport.assert_called_once()

    def test_http_fallback_requires_expected_doi_before_request(self):
        transport = self.enable_http_fixture(self.http_response())
        self.page.url = PDF.replace(DOI, "10.1002/other")
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page, doi=DOI)[0])
        self.page.url = PDF
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page)[0])
        self.assertIsNone(self.d._fetch_pdf_url(PDF, page=self.page)[0])
        transport.assert_not_called()

    def test_http_redirect_provenance_and_disposition_checked_on_every_hop(self):
        transport = self.enable_http_fixture(self.http_response())
        self.page.url = PDF
        origin = PDF.replace("onlinelibrary.wiley.com", "acrjournals.onlinelibrary.wiley.com")
        asset = "https://files.example.invalid/document.pdf"
        transport.return_value = self.http_response(asset, history=[self.http_response(origin)])
        self.assertEqual(self.d._fetch_page_state_pdf(self.page, doi=DOI)[0], self.article)
        for response in (
            self.http_response(asset),  # No trusted redirect provenance.
            self.http_response(PDF.replace(DOI, "10.1002/other"), history=[self.http_response(PDF)]),
            self.http_response(asset, history=[self.http_response(origin, disposition='filename="ICMJE-disclosure.pdf"')]),
            self.http_response(asset, history=[self.http_response(SUPPLEMENT)]),
        ):
            transport.return_value = response
            self.assertIsNone(self.d._fetch_page_state_pdf(self.page, doi=DOI)[0])

    def test_http_cannot_accept_previously_rejected_final_asset_via_another_endpoint(self):
        asset = "https://files.example.invalid/document.pdf"
        self.enable_http_fixture(self.http_response(asset, history=[self.http_response(PDF)]))
        self.page.url = PDF
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page, doi=DOI, rejected_urls={asset})[0])

    def test_browser_rejection_is_local_to_one_capture(self):
        transport = self.enable_http_fixture(self.http_response())
        self.d._pdf_candidates = Mock(return_value=[PDF])
        self.assertIsNone(self.capture(lambda url: self.response(
            url, self.article, disposition='filename="ICMJE-disclosure.pdf"'))[0])
        transport.assert_not_called()
        self.assertEqual(self.capture(lambda url: self.response(url, b"<html>PDF viewer</html>"))[0], self.article)
        transport.assert_called_once()

    def test_selects_current_article_not_first_pdf_or_disclosure_label(self):
        supplement = self.control(SUPPLEMENT)
        wrong_article = self.control(PDF.replace(DOI, "10.1002/other"))
        disclosure_label = self.control(PDF, "ICMJE Disclosure Form PDF")
        article = self.control("/doi/pdfdirect/" + DOI, "Download PDF")
        self.controls = [supplement, wrong_article, disclosure_label, article]
        self.assertTrue(self.d._click_pdf_entry(self.page, self.result, doi=DOI))
        for rejected in self.controls[:-1]:
            rejected.click.assert_not_called()
        article.click.assert_called_once()
        article.evaluate.assert_any_call("el => el.setAttribute('target', '_self')")

    def test_only_supplements_do_not_trigger_generic_click(self):
        self.controls = [self.control(SUPPLEMENT), self.control("https://files.example.invalid/form.pdf")]
        self.assertFalse(self.d._click_pdf_entry(self.page, self.result, doi=DOI))
        # Reading the link list is fine; the generic first-PDF clicker must not run.
        self.assertFalse(any("isPdfControl" in str(call.args[0]) for call in self.page.evaluate.call_args_list))

    def test_candidate_router_keeps_exact_doi_templates_and_drops_attachments(self):
        discovered = [SUPPLEMENT, PDF + "extra", "https://files.example.invalid/disclosure.pdf", PDF]
        urls = self.router.build_pdf_candidates(self.profiles.WILEY_PROFILE, DOI,
                    source_url=ARTICLE, discovered_urls=discovered)
        self.assertEqual(urls, self.profiles.WILEY_PROFILE.pdf_urls(DOI))
        self.assertTrue(self.router.is_wiley_article_pdf_url(PDF.replace("10.1002/", "10.1002%2F"), DOI))
        self.assertFalse(self.router.is_wiley_article_pdf_url(PDF.replace("wiley.com", "wiley.com.example.invalid"), DOI))
        self.assertTrue(self.d._is_supplementary_url(SUPPLEMENT.replace("/suppl/", "%2Fsuppl%2F")))

    def test_response_requires_current_doi_provenance_and_safe_disposition(self):
        asset = "https://files.example.invalid/document.pdf"
        self.assertFalse(self.d._wiley_response_matches_article(self.response(asset, self.article), DOI))
        self.assertTrue(self.d._wiley_response_matches_article(self.response(asset, self.article, origin=PDF), DOI))
        self.assertFalse(self.d._wiley_response_matches_article(self.response(asset, self.article, origin=SUPPLEMENT), DOI))
        self.assertFalse(self.d._wiley_response_matches_article(self.response(PDF, self.article,
                            disposition='attachment; filename="ICMJE-disclosure.pdf"'), DOI))

    def test_wiley_subdomain_is_valid_article_and_redirect_origin(self):
        subdomain_pdf = PDF.replace("onlinelibrary.wiley.com", "acrjournals.onlinelibrary.wiley.com")
        self.assertTrue(self.router.is_wiley_article_pdf_url(subdomain_pdf, DOI))
        self.assertTrue(self.d._wiley_response_matches_article(
            self.response("https://files.example.invalid/document.pdf", self.article, origin=subdomain_pdf), DOI))

    def test_wiley_hostname_cannot_be_spoofed_by_suffix_or_query(self):
        for host in ("acrjournals.onlinelibrary.wiley.com.example.invalid",
                     "notonlinelibrary.wiley.com", "example.invalid"):
            with self.subTest(host=host):
                forged = f"https://{host}/doi/pdfdirect/{DOI}?next={PDF}"
                self.assertFalse(self.router.is_wiley_article_pdf_url(forged, DOI))
                self.assertFalse(self.d._wiley_response_matches_article(
                    self.response("https://files.example.invalid/document.pdf", self.article, origin=forged), DOI))
        # A trusted hostname does not make a PDF endpoint hidden in query valid.
        self.assertFalse(self.router.is_wiley_article_pdf_url(
            "https://acrjournals.onlinelibrary.wiley.com/doi/" + DOI + "?next=" + PDF, DOI))

    def test_main_text_is_told_by_its_front_matter_and_its_url(self):
        # A body that mentions a disclosure form is the article; an attachment's
        # own heading at the top is not, whatever its URL (pdf_guard, the rule
        # shared with PaperSearch); supplement URLs are never the main text.
        self.assertTrue(self.d._accept_pdf_body(pdf_bytes(), PDF))
        for heading in ("ICMJE DISCLOSURE FORM", "Supporting Information", "Supplementary Appendix"):
            with self.subTest(heading=heading):
                self.assertFalse(self.d._accept_pdf_body(pdf_bytes(heading), PDF))
        self.assertFalse(self.d._accept_pdf_body(self.article, SUPPLEMENT))
        self.assertFalse(self.d._accept_pdf_body(self.other, PDF))
        self.assertFalse(self.d._accept_pdf_body(b"%PDF-" + b"broken"*1000, PDF))

    def test_other_article_response_is_rejected_then_real_article_is_captured(self):
        def responses(url):
            return self.response(url, self.other if url == PDF else self.article)
        body, url, block = self.capture(responses)
        self.assertEqual(body, self.article)
        self.assertEqual(self.page.goto.call_count, 2)
        self.assertEqual(url, self.profiles.WILEY_PROFILE.pdf_urls(DOI)[1])
        self.assertIsNone(block)
        self.assertNotIn("response", self.handlers)

    def test_response_body_navigation_cannot_bypass_supplement_filter(self):
        def responses(url):
            return self.response(SUPPLEMENT, self.disclosure, origin=url) if url == PDF else self.response(url, self.article)
        body, _, _ = self.capture(responses)
        self.assertEqual(body, self.article)
        self.assertEqual(self.page.goto.call_count, 2)

    def test_pdf_challenge_does_not_try_next_endpoint_or_http(self):
        self.d._wait_for_challenge = Mock(return_value=False)
        def responses(url):
            self.body = "Verify you are human"
            return self.response(url, b"<html>Verification</html>")
        self.assertIsNone(self.capture(responses)[0])
        self.assertEqual(self.page.goto.call_count, 1)
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_incidental_pdf_cannot_win_response_race(self):
        incidental = self.response("https://files.example.invalid/form.pdf", self.disclosure)
        def responses(url):
            self.handlers["response"](incidental)
            return self.response(url, self.article)
        self.assertEqual(self.capture(responses)[0], self.article)
        incidental.body.assert_not_called()

    def test_other_article_only_returns_no_pdf_not_success(self):
        self.assertIsNone(self.capture(lambda url: self.response(url, self.other))[0])
        self.assertEqual(self.page.goto.call_count, 3)
        self.d._save_publisher_session.assert_not_called()

    def test_fetch_one_saves_article_after_rejecting_another_article(self):
        self.d._ensure_login = Mock(return_value=True)
        self.d.adapter.reader_has_access = Mock(return_value=True)  # an entitled reader
        self.d._save_publisher_session = Mock()
        def navigate(url, **kw):
            response = self.response(url, self.other if url == PDF else self.article)
            self.page.url = response.url
            self.handlers["response"](response)
            return response
        self.page.goto.side_effect = navigate
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
            self.assertTrue(result.ok)
            self.assertEqual(Path(result.pdf_path).read_bytes(), self.article)
        self.assertEqual(self.page.goto.call_count, 2)
        self.d._save_publisher_session.assert_called_once()

    def test_final_success_boundary_refuses_another_article_without_saving(self):
        self.d._ensure_login = Mock(return_value=True)
        self.d.adapter.reader_has_access = Mock(return_value=True)  # an entitled reader
        self.d._capture_pdf = Mock(return_value=(self.other, PDF, None))
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
            self.assertEqual(list(Path(directory).rglob("*.pdf")), [])  # diagnostic specimens are allowed; a rejected PDF is not
        self.assertFalse(result.ok)
        self.assertEqual(result.state, "pdf_wrong_article")
        self.d._save_publisher_session.assert_not_called()

    def test_page_state_fetch_does_not_follow_supplement(self):
        self.page.url = SUPPLEMENT
        self.assertIsNone(self.d._fetch_page_state_pdf(self.page)[0])
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_other_publisher_routing_is_generic_and_supplement_urls_are_never_main_text(self):
        self.d.profile = self.profiles.ELSEVIER_PROFILE
        self.assertFalse(self.d._accept_pdf_body(self.disclosure, SUPPLEMENT))
        self.assertTrue(self.d._wiley_response_matches_article(self.response(SUPPLEMENT, self.disclosure), DOI))

    def test_confirmed_entitlement_failure_does_not_relogin_or_capture(self):
        self.body = "Access provided by Offline University.\nYou do not have access to this article."
        self.d._complete_login_from_current_page = Mock()
        self.d._capture_pdf = Mock()
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "institution_pdf_entitlement_missing")
        self.assertEqual(result.state, result.reason)
        self.assertFalse(self.d._looks_logged_out(self.page))
        self.d._complete_login_from_current_page.assert_not_called()
        self.d._capture_pdf.assert_not_called()

    def test_denial_discovered_during_capture_stops_further_endpoints(self):
        self.body = "Brought to you by Offline University. Article abstract."
        def responses(url):
            self.body += "\nYou do not have access to this PDF."
            return self.response(url, b"<html>No access</html>")
        self.assertIsNone(self.capture(responses)[0])
        self.assertEqual(self.page.goto.call_count, 1)
        self.assertEqual(self.result.state, "institution_pdf_entitlement_missing")
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_explicit_entitlement_denial_is_not_hidden_by_generic_403(self):
        self.body = "Brought to you by Offline University. Article abstract."
        self.d._ensure_login = Mock(return_value=True)
        self.d._complete_login_from_current_page = Mock()
        def navigate(url, **kw):
            self.body += "\nYou do not have access to this PDF."
            response = self.response(url, b"<html>Fulltext denied</html>", status=403)
            self.page.url = response.url
            self.handlers["response"](response)
            return response
        self.page.goto.side_effect = navigate
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
        self.assertEqual(result.state, "institution_pdf_entitlement_missing")
        self.assertEqual(self.page.goto.call_count, 1)
        self.d._complete_login_from_current_page.assert_not_called()

    def test_403_without_auth_and_denial_never_becomes_entitlement_missing(self):
        self.body = "403 Forbidden. Loading..."
        body, _, block = self.capture(lambda url: self.response(url, b"Forbidden", status=403))
        self.assertIsNone(body)
        self.assertEqual(block, "ip_blocked")  # Existing block category, not entitlement proof.
        self.assertNotEqual(self.result.state, "institution_pdf_entitlement_missing")
        self.assertEqual(self.page.goto.call_count, 1)
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_blocked_first_candidate_never_requests_second_candidate_or_http(self):
        second = PDF.replace("/pdfdirect/", "/pdf/")
        self.d._pdf_candidates = Mock(return_value=[PDF, second])
        for status, blocked_body in (
            (403, b"Forbidden"),
            (429, b"Too many requests"),
            (200, b"Your IP address has been blocked"),
        ):
            with self.subTest(status=status):
                self.page.url = ARTICLE
                self.page.goto.reset_mock()
                self.d._fetch_pdf_url_with_browser_state.reset_mock()
                # A later endpoint would succeed: the block must stop the loop,
                # not just survive in the diagnostic after more requests.
                body, _, block = self.capture(lambda url: self.response(
                    url, blocked_body if url == PDF else self.article,
                    status=status if url == PDF else 200))
                self.assertIsNone(body)
                self.assertEqual(block, "ip_blocked")
                self.assertEqual(self.page.goto.call_count, 1)
                self.assertEqual(self.page.goto.call_args.args[0], PDF)
                self.d._fetch_pdf_url_with_browser_state.assert_not_called()
                self.assertNotIn("response", self.handlers)

    def test_block_from_pdf_button_stops_before_candidates_and_http(self):
        def click(*args, **kwargs):
            self.page.url = PDF
            self.handlers["response"](self.response(PDF, b"Forbidden", status=403))
            return True
        self.d._click_pdf_entry = Mock(side_effect=click)
        body, _, block = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertIsNone(body)
        self.assertEqual(block, "ip_blocked")
        self.page.goto.assert_not_called()
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()
        self.assertNotIn("response", self.handlers)

    def test_http_block_stops_later_candidates_and_fallback_replay(self):
        self.d._pdf_candidates = Mock(return_value=[PDF, PDF.replace("/pdfdirect/", "/pdf/")])
        self.d._fetch_pdf_url_with_browser_state.return_value = (None, PDF, "ip_blocked")
        body, _, block = self.capture(lambda url: self.response(url, b"<html>PDF viewer</html>"))
        self.assertIsNone(body)
        self.assertEqual(block, "ip_blocked")
        self.assertEqual(self.page.goto.call_count, 1)
        self.d._fetch_pdf_url_with_browser_state.assert_called_once()
        self.assertNotIn("response", self.handlers)

    def test_fetch_one_block_precedes_login_even_when_page_looks_logged_out(self):
        self.d._ensure_login = Mock(return_value=True)
        self.d._capture_pdf = Mock(return_value=(None, PDF, "ip_blocked"))
        # Only the page returned by capture looks logged out, so no login is
        # needed before the blocked request. The post-capture branch is real.
        self.d._looks_logged_out = Mock(side_effect=lambda page: self.d._capture_pdf.called)
        self.d._complete_login_from_current_page = Mock(return_value=False)
        self.d._article_access_available = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(directory))
            self.assertEqual(list(Path(directory).rglob("*.pdf")), [])  # diagnostic specimens are allowed; a rejected PDF is not
        self.assertFalse(result.ok)
        self.assertEqual((result.state, result.reason), ("ip_blocked", "ip_blocked"))
        self.d._capture_pdf.assert_called_once()
        self.d._complete_login_from_current_page.assert_not_called()
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()
        self.d._save_publisher_session.assert_not_called()

    def test_unrelated_asset_403_does_not_stop_current_article_capture(self):
        incidental = self.response("https://assets.example.invalid/style.css", b"Forbidden", status=403)
        def responses(url):
            self.handlers["response"](incidental)
            return self.response(url, self.article)
        body, _, block = self.capture(responses)
        self.assertEqual(body, self.article)
        self.assertIsNone(block)
        self.assertEqual(self.page.goto.call_count, 1)
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()

    def test_external_pdf_403_does_not_stop_current_article_capture(self):
        self.d._pdf_candidates = Mock(return_value=[PDF])
        incidental = self.response("https://assets.fixture.invalid/unrelated.pdf", b"Forbidden", status=403)
        incidental.text = Mock(return_value="Forbidden")
        def responses(url):
            self.handlers["response"](incidental)
            return self.response(url, self.article)
        body, final_url, block = self.capture(responses)
        self.assertEqual(body, self.article)
        self.assertEqual(final_url, PDF)
        self.assertIsNone(block)
        self.page.goto.assert_called_once()
        self.assertEqual(self.page.goto.call_args.args[0], PDF)
        incidental.text.assert_not_called()
        incidental.body.assert_not_called()
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()
        self.assertFalse(any(event["state"] == "ip_blocked_response" for event in self.result.events))
        self.assertNotIn("response", self.handlers)

    def test_other_doi_pdf_403_does_not_stop_current_article_capture(self):
        self.d._pdf_candidates = Mock(return_value=[PDF])
        incidental = self.response(PDF.replace(DOI, "10.1002/other"), b"Forbidden", status=403)
        incidental.text = Mock(return_value="Forbidden")
        def responses(url):
            self.handlers["response"](incidental)
            return self.response(url, self.article)
        body, final_url, block = self.capture(responses)
        self.assertEqual(body, self.article)
        self.assertEqual(final_url, PDF)
        self.assertIsNone(block)
        self.page.goto.assert_called_once()
        self.assertEqual(self.page.goto.call_args.args[0], PDF)
        incidental.text.assert_not_called()
        incidental.body.assert_not_called()
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()
        self.assertFalse(any(event["state"] == "ip_blocked_response" for event in self.result.events))
        self.assertNotIn("response", self.handlers)

    def test_no_entitlement_claim_without_both_positive_signals(self):
        cases = (
            "You do not have access to this article. Log in through your institution.",
            "Tsinghua University China. Institutional access. You do not have access to this article.",
            "Access provided by Offline University. Loading...",
            "Access provided by Offline University. 403 Forbidden.",
            "Access provided by Offline University. Abstract; no PDF link.",
            "Access provided by Offline University. No access. Purchase PDF.",
            "Brought to you by Offline University. Article preview. Purchase PDF.",
            "Access provided by Offline University. Verify you are human. You do not have access to this PDF.",
        )
        for text in cases:
            with self.subTest(case=cases.index(text)):
                self.body = text
                self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))
                self.assertNotEqual(self.d._login_block_reason(self.page), "institution_pdf_entitlement_missing")

    def test_conditional_faq_and_quoted_denials_are_not_entitlement_evidence(self):
        for help_text in (
            "If you do not have access to this article, contact your librarian.",
            "If your institution does not have access to this content, please log in.",
            "FAQ: You do not have access to this article.",
            "FAQ\nYou do not have access to this article.",
            "If\nyou do not have access to this article.",
            'The message "You do not have access to this PDF" may appear.',
            "Why do you not have access to this article?",
            "You do not have access to this article?",
            "You do not have access to this article!",
            "Example\nYou do not have access to this article.",
            "You do not have access to this article.\nPlease contact your librarian.",
            "Access provided by Offline University. You do not have access to this article.",
        ):
            with self.subTest(help_text=help_text):
                self.body = "Access provided by Offline University.\n" + help_text
                self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))
                self.assertNotEqual(self.d._login_block_reason(self.page), "institution_pdf_entitlement_missing")

    def test_complete_denial_line_remains_valid(self):
        for denial in (
            "Access provided by Offline University.\nYou do not have access to this article.",
            "Access provided by Offline University\nYou do not have access to this PDF",
            "Access provided by Offline University\nYour institution does not have access to this content.",
        ):
            self.body = denial
            self.assertTrue(self.d._institution_pdf_entitlement_missing(self.page))

    def test_only_a_complete_denial_line_is_denial(self):
        # The engine takes the one shared denial rule (access_rules.has_denial_line).
        classify = importlib.import_module(PACKAGE + ".engine.access_rules").has_denial_line
        for denial in (
            "You do not have access to this article.",
            "  YOU\tDO NOT HAVE ACCESS TO THIS PDF  ",
            "Your institution has not subscribed to this content",
            "If you do not have access to this article, contact your librarian.",
            "If\n\nYou do not have access to this article.",
            'Example\n"You do not have access to this article."',
            "You do not have access to this article.\nPlease contact your librarian.",
            "FAQ\nUnrelated line\nYou do not have access to this article.",
            "Help\nYou do not have access to this article.",
            "You do not have access to this article?",
            "Access provided by Offline University. You do not have access to this article.",
        ):
            with self.subTest(denial=denial):
                self.body = "Access provided by Offline University\n" + denial
                self.assertEqual(self.d._institution_pdf_entitlement_missing(self.page), classify(self.body))

    def test_institution_name_on_other_host_is_not_authenticated_session(self):
        self.body = "Access provided by Offline University. You do not have access to this article."
        self.page.url = "https://onlinelibrary.wiley.com.example.invalid/doi/" + DOI
        self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))
        self.page.url = "https://idp.example.invalid/login"
        self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))

    def test_non_article_page_does_not_require_body_read_for_entitlement(self):
        self.page.url = "about:blank"
        self.d._body_text = Mock(side_effect=AssertionError("no article body"))
        self.assertFalse(self.d._institution_pdf_entitlement_missing(self.page))
        self.d._body_text.assert_not_called()

    def test_shared_entitlement_guard_also_applies_to_elsevier(self):
        self.d.profile = self.profiles.ELSEVIER_PROFILE
        self.page.url = "https://www.sciencedirect.com/science/article/pii/S0000000000000000"
        self.body = "Brought to you by Offline University.\nYou do not have access to this PDF."
        self.assertEqual(self.d._login_block_reason(self.page), "institution_pdf_entitlement_missing")
        self.assertFalse(self.d._article_access_available(self.page))
        self.assertFalse(self.d._looks_logged_out(self.page))


if __name__ == "__main__":
    unittest.main()
