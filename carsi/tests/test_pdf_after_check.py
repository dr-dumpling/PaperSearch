"""A PDF address behind a human check: its first answer is a 403 "Just a moment..."
page whose script sets a cookie and loads the same address again, which then
answers with the PDF. Karger's Cerebrovascular Diseases PDF did this on
2026-11-02: the 403 marked the address as not this article's, so the PDF that
came after the check (200 application/pdf, 2.4 MB) was never read and the item
ended "PDF not captured". The rule is the engine's: a site that binds its PDF to
the citation (Karger) and one whose PDF address names the DOI (Springer) are
both tried, in Chrome (headless, no saved profile).

CARSI_LOCAL_BROWSER_TEST=1 opts in; every request is answered locally."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import SPRINGER_PROFILE, get_publisher_profile

KARGER = SimpleNamespace(
    profile=get_publisher_profile("karger"), doi="10.1159/000000001",
    article="https://karger.com/crd/article/146/6/772/123/Offline-article",
    pdf="https://karger.com/crd/article-pdf/146/6/772/123/000000001.pdf", cites_pdf=True)
SPRINGER = SimpleNamespace(
    profile=SPRINGER_PROFILE, doi="10.1007/s00000-026-00001-1",
    article="https://link.springer.com/article/10.1007/s00000-026-00001-1",
    pdf="https://link.springer.com/content/pdf/" + quote("10.1007/s00000-026-00001-1", safe="") + ".pdf",
    cites_pdf=False)
THIEME = SimpleNamespace(
    profile=get_publisher_profile("thieme"), doi="10.1055/s-fixture-12345",
    article="https://www.thieme-connect.de/products/ejournals/abstract/10.1055/s-fixture-12345",
    pdf="https://www.thieme-connect.de/products/ejournals/pdf/10.1055/s-fixture-12345.pdf",
    cites_pdf=False)
# Cloudflare's interstitial in short: a 403 that passes by itself and loads the address again.
CHECK = ('<title>Just a moment...</title><p>Enable JavaScript and cookies to continue</p>'
         '<script>setTimeout(() => { document.cookie = "check=passed; path=/"; location.reload(); }, 1000)</script>')


def article_pdf(doi: str) -> bytes:
    import pymupdf
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), "Synthetic main article\nDOI: " + doi)
        return document.tobytes() + b"\n%" + b"x" * 6000


class CheckAtPdfAddress:
    """The fixture, run by a browser's own test class below."""

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.answers = []
        self.html = ""
        self.case = None

        def respond(route):
            url = route.request.url.split("#", 1)[0]
            if self.case is not None and url == self.case.pdf:
                if "check=passed" in (route.request.all_headers().get("cookie") or ""):
                    self.answers.append(200)
                    route.fulfill(status=200, content_type="application/pdf", body=self.body,
                                  headers={"Content-Disposition": 'inline; filename="main.pdf"'})
                elif self.abort_first and not self.answers:
                    self.answers.append("aborted")
                    route.abort("aborted")
                else:
                    self.answers.append(403)
                    route.fulfill(status=403, content_type="text/html", body=CHECK)
                return
            route.fulfill(status=200, content_type="text/html", body=self.html)
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.abort_first = False

    def capture(self, case, *, control_navigates: bool):
        self.case, self.body = case, article_pdf(case.doi)
        cited = f'<meta name="citation_pdf_url" content="{case.pdf}">' if case.cites_pdf else ""
        hold = "" if control_navigates else ' onclick="event.preventDefault()"'
        self.html = (f'<title>Offline article</title><meta name="citation_doi" content="{case.doi}">{cited}'
                     f'<a href="{case.pdf}"{hold}>Download PDF</a>')
        self.page.goto(case.article)
        # The user's visible browser; nothing leaves the fixture.
        d = PublisherBatchDownloader({}, profile=case.profile, require_interactive_browser=True,
                                     login_timeout_sec=8, pdf_timeout_sec=10)
        d.SUSPECT_UNKNOWN_GRACE_SEC = 2
        d._fetch_pdf_url = Mock(return_value=(None, "", None))
        result = DownloadResult(doi=case.doi, status="failed", article_url=case.article)
        return d._capture_pdf(self.page, case.doi, result), result

    def test_the_pdf_after_the_check_is_captured(self):
        for case in (KARGER, SPRINGER):
            for control_navigates in (True, False):  # the click, else the address itself
                with self.subTest(site=case.profile.name, control_navigates=control_navigates):
                    self.answers.clear()
                    self.context.clear_cookies()
                    (body, url, blocked), result = self.capture(case, control_navigates=control_navigates)
                    states = [e["state"] for e in result.events]
                    self.assertEqual(self.answers[:2], [403, 200])
                    self.assertIn("suspect_block_response", states)
                    self.assertEqual((body, url, blocked), (self.body, case.pdf, None),
                                     [a["outcome"] for a in result.pdf_attempts])
                    self.assertEqual(result.pdf_attempts[-1]["outcome"], "pdf ok")


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class ChromeCheckAtPdfAddressTests(CheckAtPdfAddress, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()


if __name__ == "__main__":
    unittest.main()
