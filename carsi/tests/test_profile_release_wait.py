"""Back-to-back downloads wait for the previous browser to release the persistent profile."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_search_carsi.browser import backend


class ProfileReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def lock(self, pid):
        os.symlink(f"host.local-{pid}", self.dir / "SingletonLock")

    def test_unlocked_or_stale_profile_launches_immediately(self):
        self.assertTrue(backend.wait_for_profile_release(str(self.dir), timeout=0))
        self.lock(999999)
        self.assertTrue(backend.wait_for_profile_release(str(self.dir), timeout=0))

    def test_waits_until_the_owner_exits(self):
        import threading
        owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.2)"])
        self.addCleanup(owner.kill)
        # Reap the child as soon as it exits (a real previous browser is reaped
        # by the system once its own parent has gone); a zombie still answers kill -0.
        threading.Thread(target=owner.wait, daemon=True).start()
        self.lock(owner.pid)
        self.assertTrue(backend.wait_for_profile_release(str(self.dir), timeout=10))

    def test_gives_up_after_the_timeout_and_still_lets_the_launch_report(self):
        owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(owner.kill)
        self.lock(owner.pid)
        self.assertFalse(backend.wait_for_profile_release(str(self.dir), timeout=0.6))

    def test_launch_persistent_context_waits_first(self):
        with patch.object(backend, "wait_for_profile_release") as wait, \
             patch.object(backend, "_launch_camoufox_persistent", return_value="ctx") as launch:
            self.assertEqual(backend.launch_persistent_context(str(self.dir), config={}), "ctx")
        wait.assert_called_once_with(str(backend.camoufox_profile_dir(self.dir)))
        launch.assert_called_once()

    def hold_parentlock(self, seconds):
        """Another process holding Firefox's .parentlock (macOS has no lock symlink)."""
        import threading
        lock = self.dir / ".parentlock"
        lock.touch()
        code = ("import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR); "
                "fcntl.lockf(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(float(sys.argv[2]))")
        owner = subprocess.Popen([sys.executable, "-c", code, str(lock), str(seconds)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(owner.kill)
        self.assertEqual(owner.stdout.readline().strip(), "held")
        threading.Thread(target=owner.wait, daemon=True).start()
        return owner

    @unittest.skipIf(sys.platform == "win32", "fcntl locks")
    def test_a_held_parentlock_is_waited_for_until_released(self):
        (self.dir / ".parentlock").touch()
        self.assertEqual(backend.profile_holder(str(self.dir)), "")  # a file left behind holds nothing
        self.hold_parentlock(1.2)
        self.assertEqual(backend.profile_holder(str(self.dir)), ".parentlock held")
        self.assertTrue(backend.wait_for_profile_release(str(self.dir), timeout=10))
        self.assertEqual(backend.profile_holder(str(self.dir)), "")

    @unittest.skipIf(sys.platform == "win32", "fcntl locks")
    def test_a_parentlock_held_too_long_lets_the_launch_report(self):
        self.hold_parentlock(30)
        self.assertFalse(backend.wait_for_profile_release(str(self.dir), timeout=0.6))

    def test_the_launch_records_who_held_the_profile(self):
        with patch.object(backend, "profile_holder", return_value=".parentlock held"), \
             patch.object(backend, "wait_for_profile_release", return_value=True), \
             patch.object(backend, "_launch_camoufox_persistent", return_value="ctx"):
            backend.launch_persistent_context(str(self.dir), config={})
        self.assertEqual(backend.LAST_LAUNCH["holder"], ".parentlock held")
        self.assertTrue(backend.LAST_LAUNCH["released"])
        self.assertIn("waited", backend.LAST_LAUNCH)


class BrowserStartRecordTests(unittest.TestCase):
    def test_the_start_line_says_who_held_the_profile_and_a_relaunch(self):
        from paper_search_carsi.engine.batch import PublisherBatchDownloader
        line = PublisherBatchDownloader._browser_start_line
        self.assertEqual(line({"holder": "free", "waited": 0.0, "released": True, "seconds": 3.1}),
                         "profile free; launch 3.1 s")
        self.assertEqual(line({"holder": ".parentlock held", "waited": 4.2, "released": True, "seconds": 2.9,
                               "relaunch": "the browser closed at the first page"}),
                         "relaunch: the browser closed at the first page; profile .parentlock held, "
                         "waited 4.2 s, released; launch 2.9 s")

    def test_a_browser_closed_at_the_first_page_is_relaunched_once(self):
        from pathlib import Path as P
        from unittest.mock import MagicMock
        from paper_search_carsi.engine import bridge
        from paper_search_carsi.engine.batch import DownloadResult
        from paper_search_carsi.publishers.profiles import get_publisher_profile
        doi = "10.1093/oxfordjournals.aje.a114096"
        closed = DownloadResult(doi=doi, status="failed", state="unexpected_error", events=[
            {"state": "browser_start", "detail": "profile free; launch 3.0 s"},
            {"state": "article_open", "detail": "https://doi.org/" + doi},
            {"state": "unexpected_exception", "detail": "TargetClosedError: Page.goto: Target page, context or browser has been closed"}])
        later = DownloadResult(doi=doi, status="failed", state="sso_required", reason="sso_required")
        first, second = MagicMock(), MagicMock()
        downloader = MagicMock()
        downloader._launch_context.side_effect = [first, second]
        downloader.fetch_one.side_effect = [closed, later]
        with tempfile.TemporaryDirectory() as tmp, \
             patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
             patch("paper_search_carsi.browser.backend.is_available", return_value=True):
            bridge._try_browser_batch_download(doi, P(tmp) / "x.pdf", {}, get_publisher_profile("oxfordacademic"))
        self.assertEqual(downloader.fetch_one.call_count, 2)
        self.assertEqual(downloader._launch_context.call_args_list[1].kwargs, {"relaunch": "the browser closed at the first page"})
        first.close.assert_called()
        second.close.assert_called_once()
        # Any other failure, or a later TargetClosedError, is not relaunched.
        self.assertFalse(bridge._browser_closed_at_start(later))
        self.assertFalse(bridge._browser_closed_at_start(DownloadResult(doi=doi, status="failed", state="unexpected_error", events=[
            {"state": "article_open"}, {"state": "sso_start"}, {"state": "unexpected_exception", "detail": "TargetClosedError: x"}])))


if __name__ == "__main__":
    unittest.main()
