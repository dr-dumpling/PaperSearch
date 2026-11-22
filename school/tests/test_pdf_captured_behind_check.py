"""A PDF captured while the tab still shows the verification page is used at once, and a
site's download-limit notice is the failure's reason (ScienceDirect, 2026-11-21: after
"You have reached the daily bulk download limit" on View PDF, the PDF address passed
Cloudflare and its 10 MB answer was captured, but the wait went on for the check to clear
and the article failed after 60 s, twice). Mocked pages, and a local Chrome fixture
(opt-in) for the dialog's text."""
import os
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine import batch, bridge
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE
from tests.thread_clock import this_thread_only

DOI = "10.1016/j.jare.2026.10.057"
PDF_URL = "https://www.sciencedirect.com/science/article/pii/S2090123226008477/pdfft"
ARTICLE = "https://www.sciencedirect.com/science/article/pii/S2090123226008477"
BODY = b"%PDF-1.7\n" + b"x" * 20000
LIMIT = "You have reached the daily bulk download limit Close Why?"


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class PdfCapturedBehindTheCheckTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE, pdf_timeout_sec=60)
        self.clock = Clock()
        self.page = Mock(url="https://pdf.sciencedirectassets.com/279952/AIP/main.pdf")
        self.page.wait_for_timeout.side_effect = lambda ms: self.clock.sleep(ms / 1000)

    def test_the_wait_ends_when_the_pdf_has_come(self):
        d, captured = self.d, {"bytes": None}
        result = DownloadResult(doi=DOI, status="failed", state="pdf_capture")
        polls = {"n": 0}

        def wait(ms):
            self.clock.sleep(ms / 1000)
            polls["n"] += 1
            if polls["n"] == 3:  # the PDF's answer arrives; the tab stays on the check
                captured["bytes"] = BODY

        self.page.wait_for_timeout.side_effect = wait
        fake_time, fake_sleep = this_thread_only(self.clock.time, self.clock.sleep)
        with patch.object(batch.time, "time", fake_time), patch.object(batch.time, "sleep", fake_sleep), \
             patch.object(d, "_check_user_decision"), \
             patch.object(d, "_observe_page_activity", return_value=(Mock(), False)), \
             patch.object(d, "_challenge_shell", return_value=True), \
             patch.object(d, "_automatic_challenge_step", return_value=True), \
             patch.object(d, "_verification_attention"), \
             patch.object(d, "_snapshot"):
            passed = d._wait_for_challenge_with_deadline(self.page, result, self.clock.now + 60,
                                                         until=lambda: bool(captured["bytes"]))
        self.assertTrue(passed)
        self.assertEqual(result.state, "pdf_capture")
        states = [e["state"] for e in result.events]
        self.assertIn("challenge_wait_ended", states)
        self.assertNotIn("user_wait_expired", states)
        self.assertLess(self.clock.now - 1_000.0, 10)

    def test_the_pdf_navigation_reads_the_pdf_that_came_during_the_check(self):
        d, captured = self.d, {"bytes": None, "url": ""}
        seen = {}

        def verification(page_, result_, deadline, until=None):
            seen["before"] = until()
            captured.update(bytes=BODY, url=PDF_URL + "/main.pdf")
            seen["after"] = until()
            return True

        fake_time, fake_sleep = this_thread_only(self.clock.time, self.clock.sleep)
        with patch.object(batch.time, "time", fake_time), patch.object(batch.time, "sleep", fake_sleep), \
             patch.object(d, "_raise_on_publisher_content_error"), \
             patch.object(d, "_pdf_step_hit_wall", return_value=False), \
             patch.object(d, "_landed_on_html", return_value=""), \
             patch.object(d, "_is_challenge_page", return_value=True), \
             patch.object(d, "_wait_for_challenge_with_deadline", side_effect=verification):
            body, url = d._capture_pdf_via_async_navigation(
                self.page, PDF_URL, DownloadResult(doi=DOI, status="failed"), captured)
        self.assertEqual(seen, {"before": False, "after": True})
        self.assertEqual((body, url), (BODY, PDF_URL + "/main.pdf"))


class DownloadLimitNoticeTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE)
        self.page = Mock(url=ARTICLE + "?via%3Dihub")

    def test_a_dialog_saying_the_downloads_are_used_up_is_kept(self):
        for said in (LIMIT, "You have exceeded the maximum number of PDF downloads for today.",
                     "今日下载次数已达到上限"):
            with self.subTest(said=said):
                self.page.evaluate.return_value = said
                result = DownloadResult(doi=DOI, status="failed")
                self.d._note_download_limit(self.page, result)
                self.assertTrue(result._download_limit)
                self.assertEqual(result.events[-1]["state"], "publisher_download_limit")
                self.assertIn("www.sciencedirect.com", result.events[-1]["detail"])

    def test_other_dialogs_and_unreadable_pages_say_nothing(self):
        for answer in ("We use cookies to improve your experience. Accept all", "",
                       "Download PDF Download full issue", RuntimeError("Target closed")):
            with self.subTest(answer=answer):
                self.page.evaluate.side_effect = answer if isinstance(answer, Exception) else None
                self.page.evaluate.return_value = None if isinstance(answer, Exception) else answer
                result = DownloadResult(doi=DOI, status="failed")
                self.d._note_download_limit(self.page, result)
                self.assertFalse(getattr(result, "_download_limit", ""))
                self.assertEqual(result.events, [])

    def test_a_failed_pdf_attempt_reads_the_dialogs(self):
        self.page.evaluate.return_value = LIMIT
        result = DownloadResult(doi=DOI, status="failed")
        with patch.object(self.d, "_snapshot"), patch.object(self.d, "_is_auth_page", return_value=False), \
             patch.object(self.d, "_is_challenge_page", return_value=False):
            self.d._record_pdf_attempt(result, self.page, {"how": "click", "url": PDF_URL}, {"bytes": None})
        self.assertEqual(result.pdf_attempts[-1]["outcome"], "no pdf")
        self.assertIn("daily bulk download limit", result._download_limit)

    def test_the_notice_is_why_an_article_without_its_pdf_failed(self):
        result = DownloadResult(doi=DOI, status="failed", state="challenge_or_viewer_timeout",
                                reason="challenge_or_viewer_timeout")
        result._download_limit = LIMIT
        self.assertEqual(bridge._failure_reason_code(result), "publisher_download_limit")
        self.assertEqual(bridge._FAILURE_KINDS["publisher_download_limit"], ("access_blocked", "review_access"))

    def test_the_users_own_ending_is_kept(self):
        for state in ("user_skipped", "batch_stopped", "browser_closed"):
            with self.subTest(state=state):
                result = DownloadResult(doi=DOI, status="failed", state=state, reason=state)
                result._download_limit = LIMIT
                self.assertEqual(bridge._failure_reason_code(result), state)


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class DownloadLimitDialogPageTests(unittest.TestCase):
    """The dialogs' text as Chrome reads it: a react-modal portal over an article whose own
    text talks of downloads and limits."""

    PAGE = """<!doctype html><html><body class="ReactModal__Body--open">
    <div id="root"><main><h1>Methadone induces phospholipidosis</h1>
    <p>These opioids limit relapse; the download limit of the assay was 5 ng.</p>
    <a href="pdfft">View PDF</a></main></div>
    <div class="ReactModalPortal"><div class="ReactModal__Overlay ReactModal__Overlay--after-open">
    <div class="ReactModal__Content ReactModal__Content--after-open" tabindex="-1">
    <p>You have reached the daily bulk download limit</p><button>Close</button><a href="#">Why?</a>
    </div></div></div>
    <div role="dialog" style="display:none">Hidden: too many downloads</div>
    </body></html>"""

    def test_only_the_visible_dialogs_text_is_read(self):
        from patchright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.set_content(self.PAGE)
                said = " ".join(page.evaluate(PublisherBatchDownloader._DIALOG_TEXT_JS).split())
            finally:
                browser.close()
        self.assertTrue(said.startswith("You have reached the daily bulk download limit"), said)
        self.assertNotIn("assay", said)  # the article's own text
        self.assertNotIn("Hidden", said)  # a dialog not shown
        self.assertRegex(said, PublisherBatchDownloader._DOWNLOAD_LIMIT)


if __name__ == "__main__":
    unittest.main()
