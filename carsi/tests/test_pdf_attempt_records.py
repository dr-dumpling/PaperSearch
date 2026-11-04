"""Each PDF attempt and each decision point in the article's record (2026-11-02):
the address or control, where the tab ended, the answer, how it ended, the
seconds; small pictures of the page with its form fields masked. Mocked pages."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock

from paper_search_carsi.download_diagnostics import serialize_download_result
from paper_search_carsi.engine import pdf_guard
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1016/s0140-6736(75)92262-x"
ARTICLE = "https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(75)92262-X/fulltext"
SHOW_PDF = "https://www.thelancet.com/action/showPdf?pii=S0140-6736(75)92262-X"


def synthetic_pdf(text):
    import pymupdf
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), text)
        return document.tobytes() + b"\n%" + b"x" * 6000


class TitleReadTests(unittest.TestCase):
    def test_a_page_title_does_not_use_an_unbounded_browser_call(self):
        from paper_search_carsi.browser.watchdog import BrowserOperationTimeout
        page = MagicMock()
        page.title.side_effect = BrowserOperationTimeout("Page.title did not return")
        page.locator.return_value.first.text_content.return_value = "  Article\n title  "
        self.assertEqual(PublisherBatchDownloader._title(page), "Article title")
        page.title.assert_not_called()

    def test_navigation_uses_the_same_bounded_title_read(self):
        from paper_search_carsi.browser.watchdog import BrowserOperationTimeout
        from paper_search_carsi.engine.batch_common import open_page
        page = MagicMock(url=ARTICLE)
        page.title.side_effect = BrowserOperationTimeout("Page.title did not return")
        page.locator.return_value.first.text_content.return_value = "Article title"
        page.evaluate.return_value = ["interactive", 1000]
        open_page(page, ARTICLE)
        page.title.assert_not_called()

    def test_batch_login_title_checks_preserve_browser_interrupts(self):
        from paper_search_carsi.browser.watchdog import BrowserOperationTimeout
        page = MagicMock()
        page.title.side_effect = BrowserOperationTimeout("Page.title did not return")
        page.locator.return_value.first.text_content.return_value = "Welcome"
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.assertTrue(d._looks_like_logged_in(page, "https://fixture.example/login"))
        page.title.assert_not_called()
        page.locator.return_value.first.text_content.side_effect = BrowserOperationTimeout("page budget exhausted")
        with self.assertRaises(BrowserOperationTimeout):
            d._looks_like_logged_in(page, "https://fixture.example/login")

    def test_an_unavailable_title_is_optional_but_browser_interrupts_are_not(self):
        from playwright.sync_api import TimeoutError
        from paper_search_carsi.browser.watchdog import BrowserOperationTimeout
        page = MagicMock()
        page.locator.return_value.first.text_content.side_effect = TimeoutError("title not readable")
        self.assertEqual(PublisherBatchDownloader._title(page), "")
        for exc in (BrowserOperationTimeout("page budget exhausted"), RuntimeError("program error")):
            with self.subTest(error=type(exc).__name__):
                page.locator.return_value.first.text_content.side_effect = exc
                with self.assertRaises(type(exc)):
                    PublisherBatchDownloader._title(page)


class AttemptRecordTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.d._is_challenge_page = Mock(return_value=False)
        self.d._access_verdict = Mock(return_value="unknown")
        self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        self.page = Mock(url=ARTICLE)

    def record(self, captured, how="url", url=SHOW_PDF):
        self.d._record_pdf_attempt(self.result, self.page, {"how": how, "url": url, "started": time.time() - 4.2},
                                   captured)
        return self.result.pdf_attempts[-1]

    def test_a_pdf_address_that_showed_the_article_page(self):
        nav = {"url": ARTICLE, "status": 200, "type": "text/html", "size": ""}
        entry = self.record({"nav": nav, "bytes": None, "block_reason": None, "landed_html": ARTICLE})
        self.assertEqual({k: entry[k] for k in ("how", "url", "final_url", "status", "type", "outcome")},
                         {"how": "url", "url": SHOW_PDF, "final_url": ARTICLE, "status": 200, "type": "text/html",
                          "outcome": "html page"})
        self.assertGreaterEqual(entry["seconds"], 4.0)
        event = next(e for e in reversed(self.result.events) if e["state"] == "pdf_attempt")
        self.assertIn("-> html page; 200 text/html", event["detail"])
        self.assertEqual(self.result.snapshots[0]["why"], "pdf attempt failed")  # the first failure is pictured
        self.d._access_verdict.return_value = "out"
        self.assertEqual(self.record({"nav": nav, "bytes": None, "block_reason": None})["outcome"], "paywall")

    def test_pdf_login_block_and_identity_outcomes(self):
        pdf = {"url": SHOW_PDF, "status": 200, "type": "application/pdf", "size": "123456"}
        self.assertEqual(self.record({"nav": pdf, "bytes": b"%PDF-1.7", "block_reason": None})["outcome"], "pdf ok")
        self.assertEqual(self.record({"nav": None, "bytes": None, "block_reason": "ip_blocked"})["outcome"],
                         "blocked (ip_blocked)")
        login = {"url": "https://www.thelancet.com/action/showLogin?uri=x", "status": 200, "type": "text/html"}
        self.assertEqual(self.record({"nav": login, "bytes": None, "block_reason": None})["outcome"], "login page")
        self.d._last_identity = {"verdict": "other", "doi": False, "title": None, "other_dois": ["10.1016/other"]}
        entry = self.record({"nav": pdf, "bytes": None, "block_reason": None}, how="click", url="Download PDF")
        self.assertEqual(entry["outcome"], "identity rejected")
        self.assertEqual(entry["identity"]["other_dois"], ["10.1016/other"])

    def test_the_identity_rule_keeps_its_evidence(self):
        verdict, found = pdf_guard.classify_with_evidence(synthetic_pdf("Another article\nDOI: 10.1016/other.2020.1"), DOI)
        self.assertEqual(verdict, "other")
        self.assertEqual((found["doi"], found["other_dois"]), (False, ["10.1016/other.2020.1"]))
        self.d._capture_doi = DOI
        self.d._expected_title = ""
        self.assertFalse(self.d._accept_pdf_body(synthetic_pdf("Another article\nDOI: 10.1016/other.2020.1"), SHOW_PDF))
        self.assertEqual(self.d._last_identity["verdict"], "other")
        self.assertEqual(self.d._last_identity["other_dois"], ["10.1016/other.2020.1"])

    def test_attempts_reach_the_diagnostic(self):
        self.record({"nav": None, "bytes": None, "block_reason": None})
        packet = serialize_download_result(self.result, diagnostic=True)
        self.assertEqual(packet["pdf_attempts"][0]["outcome"], "no pdf")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d._run_dir = Path(self.tmp.name)
        self.result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        self.page = MagicMock()
        self.page.url = ARTICLE
        self.page.locator.return_value.first.text_content.return_value = "Article"
        self.page.screenshot.side_effect = lambda path, **kwargs: Path(path).write_bytes(b"jpeg")

    def test_a_snapshot_keeps_url_title_and_a_masked_picture_five_at_most(self):
        for n in range(7):
            self.d._snapshot(self.page, self.result, "pdf attempt failed" if n else "not subscribed")
        self.assertEqual(len(self.result.snapshots), 5)
        first = self.result.snapshots[0]
        self.assertEqual((first["why"], first["url"], first["title"]), ("not subscribed", ARTICLE, "Article"))
        self.assertTrue(Path(first["screenshot"]).is_file())
        self.assertTrue(first["screenshot"].endswith("snapshot-1-not-subscribed.jpg"))
        kwargs = self.page.screenshot.call_args.kwargs
        self.assertEqual(kwargs["type"], "jpeg")
        self.assertIn("mask", kwargs)  # form fields are masked, never shown
        self.page.locator.assert_called_with("input, textarea, select")
        self.assertEqual(serialize_download_result(self.result, diagnostic=True)["snapshots"][0]["why"], "not subscribed")

    def test_a_successful_article_keeps_no_pictures(self):
        self.d._snapshot(self.page, self.result, "waiting for the user: school login")
        picture = Path(self.result.snapshots[0]["screenshot"])
        self.d._drop_snapshot_pictures(self.result)
        self.assertFalse(picture.exists())
        self.assertNotIn("screenshot", self.result.snapshots[0])
        self.assertEqual(self.result.snapshots[0]["url"], ARTICLE)

    def test_a_failed_screenshot_keeps_the_url_and_title(self):
        self.page.screenshot.side_effect = RuntimeError("page closed")
        self.d._snapshot(self.page, self.result, "login entry missing")
        self.assertEqual(self.result.snapshots[0]["url"], ARTICLE)
        self.assertNotIn("screenshot", self.result.snapshots[0])
        self.assertEqual(self.result.events[-1]["state"], "snapshot")
