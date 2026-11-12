"""ACS routing/capture fixtures using an isolated loader and synthetic content.

python -B -m unittest discover -s tests -p test_acs_capture.py -v
SCHOOL_LOCAL_BROWSER_TEST=1 enables the two local Chrome cases as well.
All browser requests are fulfilled/aborted; no live article, saved profile,
user configuration, or credential store is accessed. Metadata binds a PDF URL;
it is not evidence of institutional authorization or session persistence.
"""

import os
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import test_wiley_capture as fixtures


DOI = "10.1021/acs.est.3c01495"
TITLE = "Synthetic ACS article capture fixture"
ARTICLE = "https://pubs.acs.org/esthag/article/57/43/16166/484355/Fixture-title"
ABSTRACT = ARTICLE.replace("/article/", "/article-abstract/")
LEGACY_ARTICLE = "https://pubs.acs.org/doi/" + DOI
PDF = "https://pubs.acs.org/esthag/article-pdf/57/43/16166/12570484/es3c01495.pdf"
SUPPLEMENT = "https://pubs.acs.org/doi/suppl/" + DOI + "/suppl_file/fixture.pdf"
OTHER_PDF = PDF.replace("12570484/es3c01495", "12570485/other-article")


def synthetic_pdf():
    import pymupdf

    with pymupdf.open() as document:
        for index in range(10):
            page = document.new_page()
            page.insert_text((40, 50), TITLE + "\nDOI: " + DOI)
            page.insert_text((40, 110), "Abstract\n" +
                             (f"Synthetic local fixture page {index}.\n" * 25))
        return document.tobytes(deflate=False)


class ACSCaptureTests(unittest.TestCase):
    # Reuse only the isolated loader/primitives, not Wiley's test methods.
    control = fixtures.WileyCaptureTests.control
    response = fixtures.WileyCaptureTests.response

    locator = fixtures.WileyCaptureTests.locator

    def setUp(self):
        fixtures.WileyCaptureTests.setUp(self)
        # The page's visible institution labels and badges (access_rules.PROBE_JS).
        self.labels, self.badges = [], []
        self.d._access_probe = lambda page: {"labels": list(self.labels), "badges": list(self.badges)}
        self.d.profile = self.profiles.ACS_PROFILE
        self.d.login_timeout_sec = 1
        self.d.pdf_timeout_ms = 3_000
        self.page.url = ARTICLE
        self.body = "Subscribed\nSynthetic article text"
        self.page.evaluate.return_value = {"dois": [DOI], "pdfs": [PDF]}
        self.result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)

    def test_new_and_legacy_article_routes_are_recognized(self):
        for url in (ARTICLE, ABSTRACT, ARTICLE.rsplit("/", 1)[0],
                    ABSTRACT.rsplit("/", 1)[0], LEGACY_ARTICLE,
                    "https://pubs.acs.org/doi/abs/" + DOI,
                    # The DOI form of the 2026 pages (2026-11-02).
                    "https://pubs.acs.org/jacsat/article-abstract/doi/10.1021/jacs.6c12304/5461066/Investigation-of-Cu-II?redirectedFrom=fulltext",
                    "https://pubs.acs.org/jacsat/article/doi/10.1021/jacs.6c12304/5461066/Investigation-of-Cu-II"):
            with self.subTest(url=url):
                self.assertTrue(self.d._is_success_article_url(url))

    def test_lookalike_hosts_and_non_article_routes_are_rejected(self):
        for url in (ARTICLE.replace("pubs.acs.org", "pubs.acs.org.example.invalid"),
                    LEGACY_ARTICLE.replace("pubs.acs.org", "pubs.acs.org.example.invalid"),
                    "https://example.invalid/?next=" + LEGACY_ARTICLE,
                    "https://pubs.acs.org.example.invalid/esthag/article/57/43/16166/484355",
                    "https://pubs.acs.org/esthag/issue/57/43", PDF):
            with self.subTest(url=url):
                self.assertFalse(self.d._is_success_article_url(url))

    def test_abstract_page_requires_login_even_with_subscribed_label(self):
        self.page.url = ABSTRACT
        self.result.article_url = ABSTRACT
        self.d._complete_login_from_current_page = Mock(return_value=False)
        for text in ("Abstract\nGet access", "Subscribed\nAbstract"):
            with self.subTest(text=text):
                self.body = text
                self.d._complete_login_from_current_page.reset_mock()
                self.assertTrue(self.d._looks_logged_out(self.page))
                self.assertFalse(self.d._ensure_login(self.page, self.result))
                self.d._complete_login_from_current_page.assert_called_once_with(self.page, self.result)

    def test_full_subscribed_page_does_not_restart_sso_for_footer_link(self):
        self.body = "Subscribed\nSynthetic article text\nFooter: Access through your institution"
        self.badges = ["Subscribed"]  # the badge by the title
        self.d._complete_login_from_current_page = Mock()
        self.assertEqual(self.d._access_verdict(self.page), "in")
        self.assertTrue(self.d._ensure_login(self.page, self.result))
        self.d._complete_login_from_current_page.assert_not_called()

    def test_visible_specific_university_dropdown_is_institution_session(self):
        for label in ("Fixture University", "示例大学", "Fixture University"):
            with self.subTest(label=label):
                self.labels = [label]
                self.assertTrue(self.d._has_publisher_institution_session(self.page))

    def test_empty_or_hidden_dropdown_is_not_institution_session(self):
        # PROBE_JS lists visible labels only; an empty one names nobody.
        for labels in ([], [""], ["  "]):
            with self.subTest(labels=labels):
                self.labels = labels
                self.assertFalse(self.d._has_publisher_institution_session(self.page))

    def test_generic_dropdown_labels_are_not_institution_session(self):
        for label in ("Institution", "Institutional login", "Institutional access",
                      "Sign In", "Log In", "Access through your institution",
                      "Select an institution", "Select your institution"):
            with self.subTest(label=label):
                self.labels = [label]
                self.assertFalse(self.d._has_publisher_institution_session(self.page))

    def test_university_author_affiliation_is_not_institution_banner(self):
        self.body = "Author affiliations\nDepartment of Chemistry, Fixture University\nAbstract"
        self.assertFalse(self.d._has_publisher_institution_session(self.page))

    def test_personal_sign_in_is_not_institution_banner(self):
        self.body = "Sign In\nPersonal account\nFixture University\nArticle abstract"
        self.page.title.return_value = "ACS personal account Sign In"
        self.assertFalse(self.d._has_publisher_institution_session(self.page))

    def test_university_dropdown_on_malicious_host_is_not_institution_session(self):
        self.labels = ["Fixture University"]
        for url in (ARTICLE.replace("pubs.acs.org", "pubs.acs.org.example.invalid"),
                    ARTICLE.replace("pubs.acs.org", "fakepubs.acs.org"),
                    ARTICLE.replace("pubs.acs.org", "pubs.acs.org@example.invalid"),
                    "https://example.invalid/?next=" + ARTICLE):
            with self.subTest(url=url):
                self.page.url = url
                self.assertFalse(self.d._has_publisher_institution_session(self.page))

    def test_metadata_binds_non_doi_filename_and_normalizes_query(self):
        self.assertNotIn(DOI, PDF)
        # The engine's one citation rule (batch_pdf_urls), within ACS's own PDF addresses.
        self.page.evaluate.return_value = {"dois": [DOI.upper()], "pdfs": [PDF + "?download=1"]}
        self.assertEqual(self.d._metadata_pdf_urls(self.page, DOI), [PDF])

    def test_wrong_or_missing_metadata_doi_does_not_bind_pdf(self):
        for doi in (DOI + "0", "10.1021/acs.est.3c01496", ""):
            with self.subTest(doi=doi):
                self.page.evaluate.return_value = {"dois": [doi], "pdfs": [PDF]}
                self.assertEqual(self.d._metadata_pdf_urls(self.page, DOI), [])

    def test_metadata_rejects_external_host_wrong_scheme_and_wrong_endpoint(self):
        for url in (PDF.replace("pubs.acs.org", "files.example.invalid"),
                    PDF.replace("pubs.acs.org", "pubs.acs.org.example.invalid"),
                    PDF.replace("https:", "http:"),
                    "https://pubs.acs.org/doi/pdf/" + DOI,
                    ARTICLE, PDF.replace(".pdf", ".html")):
            with self.subTest(url=url):
                self.page.evaluate.return_value = {"dois": [DOI], "pdfs": [url]}
                self.assertEqual(self.d._metadata_pdf_urls(self.page, DOI), [])

    def test_metadata_rejects_supplement_even_on_article_pdf_path(self):
        for url in (SUPPLEMENT, PDF.replace("es3c01495.pdf", "supporting-information.pdf"),
                    PDF.replace("/12570484/", "/suppl_file/")):
            with self.subTest(url=url):
                self.page.evaluate.return_value = {"dois": [DOI], "pdfs": [url]}
                self.assertEqual(self.d._metadata_pdf_urls(self.page, DOI), [])

    def test_click_selects_metadata_bound_main_after_supplement_and_unrelated_pdf(self):
        supplement = self.control(SUPPLEMENT, "Supporting information PDF")
        other = self.control(OTHER_PDF, "Download PDF")
        main = self.control(PDF, "Download PDF")
        self.controls = [supplement, other, main]
        self.assertTrue(self.d._click_pdf_entry(self.page, self.result, doi=DOI))
        supplement.click.assert_not_called()
        other.click.assert_not_called()
        main.click.assert_called_once()

    def test_unrelated_link_does_not_replace_missing_metadata_bound_link(self):
        other = self.control(OTHER_PDF, "Download PDF")
        self.controls = [other]
        self.assertFalse(self.d._click_pdf_entry(self.page, self.result, doi=DOI))
        other.click.assert_not_called()

    def test_incidental_unbound_response_cannot_win_main_pdf_capture(self):
        main_body = synthetic_pdf()
        other = self.response(OTHER_PDF, main_body)
        self.d._pdf_candidates = Mock(return_value=[])
        self.d._fetch_page_state_pdf = Mock(return_value=(None, "", None))

        def navigate(url, **kwargs):
            self.handlers["response"](other)
            response = self.response(url, main_body)
            self.handlers["response"](response)
            return response

        self.page.goto.side_effect = navigate
        body, url, block = self.d._capture_pdf(self.page, DOI, self.result)
        self.assertEqual(body, main_body)
        self.assertEqual(url, PDF)
        self.assertIsNone(block)
        other.body.assert_not_called()
        self.assertEqual(self.page.goto.call_count, 1)
        self.d._fetch_page_state_pdf.assert_not_called()
        self.assertEqual(self.handlers, {})


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1",
                     "local Chrome fixture requires explicit env gate")
class ACSNativeCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright

        cls.driver = sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser = cls.driver.chromium.launch(
            channel="chrome", headless=True, timeout=15_000,
            args=["--disable-background-networking", "--disable-component-update",
                  "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"],
        )
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        harness = ACSCaptureTests(methodName="runTest")
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.d = harness.d
        del self.d._access_probe  # the real page's labels
        self.batch = harness.batch
        self.d._fetch_page_state_pdf = Mock(return_value=(None, "", None))
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.context.set_default_timeout(3_000)
        self.context.set_default_navigation_timeout(3_000)

    def capture(self, disposition):
        import pymupdf

        data = synthetic_pdf()
        self.assertGreater(len(data), 5_000)
        with pymupdf.open(stream=data, filetype="pdf") as document:
            self.assertEqual(len(document), 10)
            self.assertIn(DOI, document[0].get_text())
            self.assertIn(TITLE, document[0].get_text())
        html = f'''<!doctype html><html><head><title>{TITLE}</title>
            <meta name="citation_title" content="{TITLE}">
            <meta name="citation_doi" content="{DOI}">
            <meta name="citation_pdf_url" content="{PDF}"></head>
            <body><button class="btn-reset dropdown-toggle institution at-institution">Fixture University</button>
            <h1>{TITLE}</h1><p>Subscribed</p><p>Synthetic fixture text.</p>
            <a href="{SUPPLEMENT}" target="_blank" download>Supporting information PDF</a>
            <a href="{OTHER_PDF}" target="_blank" download>Related article PDF</a>
            <a id="main-pdf" href="{PDF}" target="_blank" download="es3c01495.pdf">Download PDF</a>
            </body></html>'''
        requests = []
        navigations = []

        def respond(route):
            url = route.request.url
            requests.append(url)
            if route.request.is_navigation_request():
                navigations.append(url)
            if url == ARTICLE:
                route.fulfill(status=200, content_type="text/html", body=html)
            elif url in (PDF, SUPPLEMENT, OTHER_PDF):
                # Wrong links also return PDF bytes, so selection is meaningful.
                route.fulfill(status=200, headers={"Content-Type": "application/pdf",
                              "Content-Disposition": disposition}, body=data)
            else:
                route.abort()

        self.context.route("**/*", respond)
        page = self.context.new_page()
        downloads = []
        page.on("download", lambda download: downloads.append(download))
        page.goto(ARTICLE, wait_until="domcontentloaded")
        self.assertTrue(self.d._has_publisher_institution_session(page))
        result = self.batch.DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        body, url, block = self.d._capture_pdf(page, DOI, result)
        page.wait_for_timeout(250)
        self.assertEqual(body, data)
        self.assertEqual(url, PDF)
        self.assertIsNone(block)
        self.assertEqual(len(downloads), 0)
        self.assertEqual(requests.count(PDF), 1, requests)
        self.assertEqual(requests.count(ARTICLE), 1, requests)
        self.assertNotIn(SUPPLEMENT, requests)
        self.assertNotIn(OTHER_PDF, requests)
        self.assertEqual(Counter(navigations), Counter({ARTICLE: 1, PDF: 1}))
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(page.locator("#main-pdf").get_attribute("target"), "_self")
        self.assertIsNone(page.locator("#main-pdf").get_attribute("download"))
        self.d._fetch_page_state_pdf.assert_not_called()
        self.d._fetch_pdf_url_with_browser_state.assert_not_called()
        self.d._save_publisher_session.assert_not_called()
        states = [event["state"] for event in result.events]
        self.assertEqual(states.count("browser_pdf_response_captured"), 1, states)
        self.assertFalse(any(state in states for state in (
            "browser_pdf_response_error", "browser_response_continue_error",
            "browser_capture_disable_error", "browser_capture_detach_error")), result.events)

    def test_metadata_bound_attachment_click_captures_once_without_chrome_download(self):
        self.capture('attachment; filename="es3c01495.pdf"')

    def test_metadata_bound_inline_click_captures_once_without_chrome_download(self):
        self.capture('inline; filename="es3c01495.pdf"')


if __name__ == "__main__":
    unittest.main()
