"""Preview frames: one per unchanged page, a bounded history, none after a success."""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_search_school.browser import preview


class FakePage:
    def __init__(self):
        self.url, self._title = "https://journal.example/abstract/1", "Article"
        self.context = None

    def title(self):
        return self._title

    def is_closed(self):
        return False

    def on(self, *_args):
        pass

    def locator(self, _selector):
        return MagicMock(count=MagicMock(return_value=0))

    def screenshot(self, **kwargs):
        assert kwargs.get("type") == "jpeg"
        return b"\xff\xd8frame"


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.page = FakePage()
        self.context = MagicMock()
        self.context.pages = [self.page]
        self.context.new_cdp_session.side_effect = RuntimeError("no CDP")  # use page.screenshot
        self.page.context = self.context
        identity = {"run_id": str(uuid.uuid4()), "current": "10.1000/x"}
        self.view = preview.BrowserPreview(self.context, Path(self.tmp.name), identity)
        preview._OBSERVERS[self.context] = self.view

    def tearDown(self):
        preview._OBSERVERS.pop(self.context, None)
        self.tmp.cleanup()

    def frames(self):
        return sorted(p.name for p in self.view.directory.glob("*.jpg"))

    def test_an_unchanged_page_keeps_only_its_newest_frame(self):
        for _ in range(4):
            self.view.observe(force=True)
        self.assertEqual(len(self.frames()), 1)
        self.assertEqual(self.frames(), [self.view.pages[0]["image_name"]])

    def test_changed_pages_are_kept_up_to_the_limit(self):
        for index in range(preview.MAX_KEPT_FRAMES + 4):
            self.page.url = f"https://journal.example/step/{index}"
            self.view.observe(force=True)
        self.assertEqual(len(self.frames()), preview.MAX_KEPT_FRAMES + 1)  # history + newest

    def test_navigation_only_marks_dirty_and_never_reads_the_browser_in_a_callback(self):
        page = MagicMock()
        self.view._attach_page(page)
        callback = page.on.call_args.args[1]
        with patch.object(self.view, "observe") as observe:
            callback()
        observe.assert_not_called()
        page.title.assert_not_called()
        page.screenshot.assert_not_called()
        self.assertEqual(self.view.page_revisions[page], 1)
        self.assertEqual(self.view.last_observed, 0)

    def test_preview_propagates_stops_instead_of_hiding_them(self):
        from paper_search_school.browser.watchdog import BrowserOperationTimeout
        from paper_search_school.entitlements import UserStoppedBatch
        for error in (BrowserOperationTimeout("page budget"), UserStoppedBatch("stop")):
            with self.subTest(error=type(error).__name__), \
                    patch.object(self.view, "_capture", side_effect=error):
                with self.assertRaises(type(error)):
                    preview.observe_page(self.page, force=True)

    def test_preview_leaves_the_remaining_page_budget_to_the_download(self):
        from paper_search_school.browser.watchdog import operation
        self.view.observe(force=True)
        frame = self.view.pages[0]["image_name"]
        with operation(0.5, "prepare article"), patch.object(self.view, "_capture") as capture:
            self.view.observe(force=True)
        capture.assert_not_called()
        self.assertEqual(self.view.pages[0]["image_name"], frame)

    def test_a_successful_download_drops_its_frames(self):
        self.view.observe(force=True)
        self.page.url = "https://journal.example/fulltext/1"
        self.view.observe(force=True)
        preview.discard_frames(self.context)
        self.assertEqual(self.frames(), [])
        self.assertEqual(self.view.pages[0]["screenshot_status"], "unavailable")

    def test_pdf_capture_does_not_wait_for_an_optional_preview(self):
        from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
        from paper_search_school.browser.watchdog import BrowserOperationTimeout

        downloader = PublisherBatchDownloader(config={})
        downloader._citation_title = MagicMock(return_value="Expected article")
        body = MagicMock()
        body.inner_text.return_value = "Current article evidence"
        self.page.locator = MagicMock(return_value=body)

        def capture(page, doi, result):
            self.assertEqual(downloader._body_text(page), "Current article evidence")
            return b"pdf bytes", "https://journal.example/current.pdf", None

        downloader._capture_pdf_channels = capture
        result = DownloadResult(doi="10.1000/x", status="error")
        with patch.object(self.view, "_capture", side_effect=BrowserOperationTimeout("stalled preview")) as shot:
            self.assertEqual(downloader._capture_pdf(self.page, result.doi, result)[0], b"pdf bytes")
            shot.assert_not_called()
            # This only suppresses incidental previews during capture. A later
            # observation must still propagate browser/user interruption.
            with self.assertRaises(BrowserOperationTimeout):
                self.view.observe(force=True)

    def test_pdf_capture_failure_restores_preview_observation(self):
        from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
        from paper_search_school.entitlements import UserStoppedBatch

        downloader = PublisherBatchDownloader(config={})
        downloader._citation_title = MagicMock(return_value="Expected article")
        downloader._capture_pdf_channels = MagicMock(side_effect=UserStoppedBatch("stop"))
        with self.assertRaises(UserStoppedBatch):
            downloader._capture_pdf(self.page, "10.1000/x", DownloadResult(doi="10.1000/x", status="error"))
        self.view.observe(force=True)
        self.assertEqual(self.view.pages[0]["screenshot_status"], "available")


if __name__ == "__main__":
    unittest.main()
