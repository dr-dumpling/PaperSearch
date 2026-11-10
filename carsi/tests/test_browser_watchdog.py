"""A browser call that never returns ends the item, not the batch (2026-10-31)."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_search_carsi.browser import watchdog
from paper_search_carsi.engine import bridge
from paper_search_carsi.engine.batch import DownloadResult
from paper_search_carsi.publishers.profiles import get_publisher_profile


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(watchdog._inflight.clear)
        self.addCleanup(watchdog._call_deadlines.clear)
        self.addCleanup(watchdog._abandoned.clear)
        patcher = patch.object(watchdog, "fired", None)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_a_call_past_the_limit_is_cancelled_once(self):
        now = time.monotonic()
        loop = MagicMock(); loop.is_closed.return_value = False
        stuck = object()
        watchdog._inflight.update({1: (now - 10, "Page.goto", [], loop, object(), None),
                                   2: (now - 300, "Page.title", ["  caller\n"], loop, stuck, None)})
        with patch("paper_search_carsi.log.dump_stacks") as dump:
            self.assertTrue(watchdog.check(240))
            self.assertTrue(watchdog.check(240))
        loop.call_soon_threadsafe.assert_called_once_with(watchdog._cancel, stuck)
        self.assertEqual(watchdog.fired["call"], "Page.title")
        dump.assert_called_once()  # every thread's stack, once
        self.assertIn("Page.title", dump.call_args.args[0])

    def test_operation_deadline_cancels_a_call_shorter_than_the_global_limit(self):
        now = time.monotonic()
        loop = MagicMock(); loop.is_closed.return_value = False
        coro = object()
        watchdog._inflight[1] = (now - 20, "Page.evaluate", [], loop, coro, None)
        watchdog._call_deadlines[1] = (now - watchdog.OPERATION_GRACE_SEC - 1, "article preparation")
        with patch("paper_search_carsi.log.dump_stacks"):
            self.assertTrue(watchdog.check(90))
        self.assertEqual(watchdog.failure_code(), "browser_operation_timeout")
        self.assertEqual(watchdog.fired["operation"], "article preparation")
        loop.call_soon_threadsafe.assert_called_once_with(watchdog._cancel, coro)

    def test_a_call_sent_just_before_the_deadline_may_finish(self):
        # Science's PDF step (2026-11-09): a title read sent as the budget ran out
        # was cut at once ("waited 0s") and ended the article as a stalled browser.
        now = time.monotonic()
        loop = MagicMock(); loop.is_closed.return_value = False
        watchdog._inflight[1] = (now - 0.5, "Locator.text_content", [], loop, object(), None)
        watchdog._call_deadlines[1] = (now - 0.1, "_capture_pdf")
        self.assertFalse(watchdog.check(90))
        self.assertIsNone(watchdog.fired)
        loop.call_soon_threadsafe.assert_not_called()

    def test_calls_share_one_budget_and_late_candidates_are_not_sent(self):
        clock, sent = [100.0], []

        class Fake:
            def _sync(self, coro):
                sent.append(list(watchdog._call_deadlines.values())[0][0])
                clock[0] += 4
                coro.close()

        async def evaluate():
            return None

        self.install_on(Fake)
        with patch.object(watchdog.time, "monotonic", side_effect=lambda: clock[0]), \
                patch("paper_search_carsi.log.dump_stacks"):
            with watchdog.operation(6, "pdf candidates"):
                Fake()._sync(evaluate())
                Fake()._sync(evaluate())
                late = evaluate()
                with self.assertRaises(watchdog.BrowserBudgetExhausted):
                    Fake()._sync(late)
            with watchdog.operation(6, "next article"):
                Fake()._sync(evaluate())
        self.assertEqual(sent, [106, 106, 114])  # the expired call was skipped; the next article still runs
        self.assertIsNone(watchdog.fired)
        self.assertIsNone(late.cr_frame)
        self.assertEqual(watchdog._call_deadlines, {})
        self.assertEqual(watchdog._inflight, {})

    def test_human_wait_pauses_automation_and_nested_budgets_do_not_extend_it(self):
        clock = [100.0]
        with patch.object(watchdog.time, "monotonic", side_effect=lambda: clock[0]):
            with watchdog.operation(60, "article"):
                clock[0] = 110
                with watchdog.pause_operation(), watchdog.operation(180, "school login"):
                    self.assertEqual(watchdog._local.budgets, [[290, "school login"]])
                    clock[0] = 210
                self.assertEqual(watchdog._local.budgets, [[260, "article"]])
                with watchdog.operation(600, "nested"):
                    self.assertEqual(min(b[0] for b in watchdog._local.budgets), 260)
            self.assertEqual(watchdog._local.budgets, [])

    def test_stacks_go_to_the_stack_file(self):
        from paper_search_carsi import log
        with patch.object(log, "_stack_file", None):
            self.assertFalse(log.dump_stacks("nothing registered"))
        with tempfile.TemporaryFile("w+") as stacks, patch.object(log, "_stack_file", stacks):
            self.assertTrue(log.dump_stacks("browser_unresponsive: Page.title waited 300s"))
            stacks.seek(0)
            text = stacks.read()
        self.assertIn("browser_unresponsive: Page.title", text)
        self.assertIn("in dump_stacks", text)  # the stack itself, innermost frame first

    def test_calls_within_the_limit_are_left_alone(self):
        loop = MagicMock()
        watchdog._inflight[1] = (time.monotonic() - 100, "Page.goto", [], loop, object(), None)
        self.assertFalse(watchdog.check(240))
        loop.call_soon_threadsafe.assert_not_called()

    def install_on(self, fake):
        from patchright._impl import _sync_base
        patches = [patch.object(_sync_base, "SyncBase", fake), patch.object(watchdog, "_installed", False),
                   patch.object(watchdog.threading, "Thread")]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        watchdog.install()

    def test_sync_calls_are_timed_while_running(self):
        seen = {}

        class Fake:
            def _sync(self, coro):
                seen.update(watchdog._inflight)
                return "done"

        async def evaluate():
            return None

        self.install_on(Fake)
        coro = evaluate()
        try:
            self.assertEqual(Fake()._sync(coro), "done")
        finally:
            coro.close()
        self.assertEqual([entry[1] for entry in seen.values()],
                         ["WatchdogTests.test_sync_calls_are_timed_while_running.<locals>.evaluate"])
        self.assertEqual(watchdog._inflight, {})

    def test_a_cancelled_call_and_every_later_call_raise(self):
        import asyncio

        class Fake:
            def _sync(self, coro):
                coro.close()
                watchdog.fired = {"call": "Page.evaluate", "seconds": 241}
                raise asyncio.CancelledError()

        async def evaluate():
            return None

        self.install_on(Fake)
        with self.assertRaises(watchdog.BrowserUnresponsive):
            Fake()._sync(evaluate())
        later = evaluate()
        with self.assertRaises(watchdog.BrowserUnresponsive):
            Fake()._sync(later)
        self.assertIsNone(later.cr_frame)  # closed, never sent

    def test_an_abandoned_read_ends_in_its_handler_and_the_browser_goes_on(self):
        """A response read in an event handler that never returns is dropped when its
        capture ends; 90 s later it ended the next article (JAMA after AIAA, 2026-11-08)."""
        import asyncio
        from greenlet import greenlet, getcurrent
        test = getcurrent()

        class Fake:
            def _sync(self, coro):
                coro.close()
                if getcurrent() is not test:
                    test.switch()  # the handler waits for an answer that does not come
                    raise asyncio.CancelledError()
                return "answered"

        async def body():
            return b""

        self.install_on(Fake)
        readers, ended = set(), []

        def on_response():
            try:
                with watchdog.owned_by(readers):
                    Fake()._sync(body())
            except Exception as exc:
                ended.append(type(exc).__name__)

        handler = greenlet(on_response)
        handler.switch()
        self.assertEqual(len(watchdog._inflight), 1)
        self.assertEqual(watchdog.abandon(set()), 0)  # another capture's readers: left alone
        self.assertEqual(watchdog.abandon(readers), 1)
        self.assertEqual(watchdog._inflight, {})
        self.assertFalse(watchdog.check(0))  # nothing left to time out
        handler.switch()
        self.assertEqual(ended, ["CallAbandoned"])
        self.assertEqual(readers, set())
        self.assertIsNone(watchdog.fired)
        self.assertEqual(Fake()._sync(body()), "answered")  # the next article's calls go through

    def test_a_late_optional_call_is_abandoned_within_its_own_limit(self):
        """A preview frame that never came was cancelled by the watchdog after 90 s and
        ended the article as browser_unresponsive (Thieme after the login, 2026-11-08)."""
        import asyncio

        class Fake:
            delay = 5.0

            def _sync(self, coro):
                coro.close()
                deadline = time.monotonic() + self.delay
                while not watchdog._abandoned and time.monotonic() < deadline:
                    time.sleep(0.01)
                if watchdog._abandoned:
                    raise asyncio.CancelledError()
                return "frame"

        async def capture():
            return b""

        real_thread = watchdog.threading.Thread
        self.install_on(Fake)
        # install_on stubs Thread to keep the watch thread away; the limit's timer is real.
        restore = patch.object(watchdog.threading, "Thread", real_thread)
        restore.start(); self.addCleanup(restore.stop)
        started = time.monotonic()
        with self.assertRaises(watchdog.CallAbandoned), watchdog.call_limit(0.2):
            Fake()._sync(capture())
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNone(watchdog.fired)
        self.assertEqual(watchdog._inflight, {})
        Fake.delay = 0.05
        with watchdog.call_limit(1):
            self.assertEqual(Fake()._sync(capture()), "frame")
        time.sleep(0.05)
        self.assertEqual(watchdog._abandoned, set())


class BridgeTests(unittest.TestCase):
    def test_an_unresponsive_browser_is_reported_as_such(self):
        downloader = MagicMock()
        downloader.fetch_one.return_value = DownloadResult(doi="10.1/x", status="failed", state="unexpected_error",
                                                           reason="Error: Connection closed")
        with patch.object(watchdog, "fired", {"call": "Page.title", "seconds": 245}), \
                patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
                patch("paper_search_carsi.browser.backend.is_available", return_value=True):
            out = bridge._try_browser_batch_download("10.1/x", Path("/tmp/out/x.pdf"), {"supplements": "with"},
                                                     get_publisher_profile("elsevier"))
        self.assertEqual(out["error_type"], "browser_unresponsive")
        self.assertEqual(out["supplements"][0]["reason"], "browser_unresponsive")
        downloader.collect_supplements.assert_not_called()

    def test_an_ego_install_without_chrome_still_downloads(self):
        downloader = MagicMock()
        downloader.fetch_one.return_value = DownloadResult(doi="10.1/x", status="failed", state="pdf_not_captured",
                                                           reason="pdf_not_captured")
        with patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
                patch("paper_search_carsi.browser.backend.is_available", return_value=False), \
                patch("paper_search_carsi.browser.engine.resolve_backend", return_value="ego"):
            out = bridge._try_browser_batch_download("10.1/x", Path("/tmp/out/x.pdf"), {"browser_backend": "ego"},
                                                     get_publisher_profile("taylor & francis"))
        downloader.fetch_one.assert_called_once()
        self.assertEqual(out["error_type"], "download_failed")

    def test_a_failure_before_the_article_still_leaves_its_cause(self):
        import json
        import tempfile
        downloader = MagicMock()
        downloader._launch_context.side_effect = RuntimeError("ego relay closed the connection")
        out_dir = Path(tempfile.mkdtemp())
        with patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
                patch("paper_search_carsi.browser.backend.is_available", return_value=True):
            out = bridge._try_browser_batch_download("10.1002/art.70156", out_dir / "x.pdf", {},
                                                     get_publisher_profile("wiley"))
        self.assertEqual(out["error_type"], "source_exception")
        self.assertEqual((out["artifacts"]["publisher"], out["artifacts"]["state"]), ("Wiley", "unexpected_error"))
        saved = json.loads(Path(out["artifacts"]["diagnostic"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["events"], [{"state": "unexpected_exception",
                                            "detail": "RuntimeError: ego relay closed the connection"}])
        self.assertIn("RuntimeError", saved["traceback"])

    def test_startup_watchdog_keeps_its_specific_failure_class(self):
        import json
        import tempfile
        for error, code in ((watchdog.BrowserUnresponsive("browser launch stalled"), "browser_unresponsive"),
                            (watchdog.BrowserOperationTimeout("launch budget"), "browser_operation_timeout")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                downloader = MagicMock()
                downloader._launch_context.side_effect = error
                with patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader), \
                        patch("paper_search_carsi.browser.backend.is_available", return_value=True):
                    out = bridge._try_browser_batch_download("10.1175/jcli-d-22-0924.1", Path(tmp) / "x.pdf",
                                                             {"supplements": "with"}, get_publisher_profile("ams"))
                self.assertEqual((out["error_type"], out["artifacts"]["state"]), (code, code))
                self.assertEqual(out["action"], "review_browser")
                saved = json.loads(Path(out["artifacts"]["diagnostic"]).read_text())
                self.assertEqual((saved["state"], saved["reason"]), (code, code))
                self.assertIn(type(error).__name__, saved["traceback"])
                downloader.fetch_one.assert_not_called()
                downloader.collect_supplements.assert_not_called()


if __name__ == "__main__":
    unittest.main()
