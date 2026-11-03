"""Preview frames: one per unchanged page, a bounded history, none after a success."""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock

from paper_search_carsi.browser import preview


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

    def test_a_successful_download_drops_its_frames(self):
        self.view.observe(force=True)
        self.page.url = "https://journal.example/fulltext/1"
        self.view.observe(force=True)
        preview.discard_frames(self.context)
        self.assertEqual(self.frames(), [])
        self.assertEqual(self.view.pages[0]["screenshot_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
