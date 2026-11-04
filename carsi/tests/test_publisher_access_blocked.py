"""Explicit Cloudflare block pages stop; interactive verification remains a wait."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

BODY = 'Sorry, you have been blocked\nYou are unable to access bmj.com'


class PublisherAccessBlockedTests(unittest.TestCase):
    def setUp(self):
        import test_wiley_capture as fixtures
        h = fixtures.WileyCaptureTests(methodName='runTest')
        self.addCleanup(h.doCleanups)
        h.setUp()
        self.batch = h.batch
        self.d = self.batch.PublisherBatchDownloader({},profile=h.profiles.SCIENCE_PROFILE)
        self.d._title = Mock(return_value='Attention Required! | Cloudflare')
        self.d._body_text = Mock(return_value=BODY)
        self.page = SimpleNamespace(on=Mock(), remove_listener=Mock(), url='https://journals.fixture.example/article',wait_for_load_state=Mock(),goto=Mock(),close=Mock(),is_closed=Mock(return_value=False),evaluate=Mock(return_value=None),title=Mock(return_value='Attention Required! | Cloudflare'))
        self.page.locator = Mock(return_value=SimpleNamespace(
            first=SimpleNamespace(text_content=Mock(return_value='Attention Required! | Cloudflare'))))
        self.result = self.batch.DownloadResult(doi='10.1000/fixture',status='failed')

    def test_explicit_block_is_not_a_verification_wait(self):
        self.assertTrue(self.d._publisher_access_blocked(self.page))
        self.assertFalse(self.d._is_challenge_page(self.page))
        with self.assertRaises(self.batch.PublisherAccessBlocked):
            self.d._wait_for_challenge(self.page,self.result)
        self.assertNotIn('challenge_manual_wait',[e['state'] for e in self.result.events])

    def test_initial_block_stops_before_login_and_pdf_capture(self):
        self.d._wait_for_challenge = Mock()
        self.d._complete_login_from_current_page = Mock()
        self.d._capture_pdf = Mock()
        self.d._hold_after_run = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            result=self.d.fetch_one(self.page,self.batch.PaperRecord(doi='10.1000/fixture'),Path(tmp))
        self.assertEqual(result.state,'publisher_access_blocked')
        self.d._wait_for_challenge.assert_not_called()
        self.d._complete_login_from_current_page.assert_not_called()
        self.d._capture_pdf.assert_not_called()
        self.batch.progress_reporter.report_stage.assert_called_with('route_failed',current='10.1000/fixture')
        phases=[call.kwargs.get('phase','') for call in self.batch.progress_reporter.update.call_args_list]
        self.assertIn('网站已阻止当前访问，此路径已停止',phases)

    def test_interactive_challenge_still_waits(self):
        self.d._title.return_value='Just a moment...'
        self.d._body_text.return_value='Verify you are human'
        self.assertFalse(self.d._publisher_access_blocked(self.page))
        self.assertTrue(self.d._is_challenge_page(self.page))

    def test_verification_changing_to_block_at_wait_deadline_stops(self):
        self.d._title.return_value = 'Just a moment...'
        self.d._body_text.return_value = 'Verify you are human'
        clock = [0.0]
        def blocked_after_wait(_milliseconds):
            clock[0] = 0.25
            self.d._title.return_value = 'Attention Required! | Cloudflare'
            self.d._body_text.return_value = BODY
        self.page.wait_for_timeout = Mock(side_effect=blocked_after_wait)
        with patch.object(self.batch.progress_reporter, 'set_attention', create=True), \
             patch.object(self.batch.progress_reporter, 'clear_attention', create=True) as clear, \
             patch.object(self.batch.time, 'time', side_effect=lambda: clock[0]), \
             self.assertRaises(self.batch.PublisherAccessBlocked):
            self.d._wait_for_challenge(self.page, self.result, deadline=0.25)
        clear.assert_not_called()  # the short automatic phase never opened an attention
        self.page.wait_for_timeout.assert_called_once_with(250.0)
        self.assertNotIn('challenge_resolved', [e['state'] for e in self.result.events])

    def test_expired_verification_deadline_never_waits_or_claims_resolution(self):
        self.d._title.return_value = 'Just a moment...'
        self.d._body_text.return_value = 'Verify you are human'
        self.page.wait_for_timeout = Mock()
        with patch.object(self.batch.progress_reporter, 'set_attention', create=True), \
             patch.object(self.batch.progress_reporter, 'clear_attention', create=True) as clear, \
             patch.object(self.batch.time, 'time', return_value=1.0):
            self.assertFalse(self.d._wait_for_challenge(self.page, self.result, deadline=1.0))
        clear.assert_not_called()  # an expired wait must not ask for manual interaction
        self.page.wait_for_timeout.assert_not_called()
        self.assertNotIn('challenge_resolved', [e['state'] for e in self.result.events])

    def test_article_url_retained_by_block_page_is_not_ready(self):
        self.d._is_success_article_url = Mock(return_value=True)
        with self.assertRaises(self.batch.PublisherAccessBlocked):
            self.d._article_access_available(self.page)

    def test_an_article_quoting_the_block_message_is_not_a_block_page(self):
        self.d._title.return_value='A study of web access failures'
        self.assertFalse(self.d._publisher_access_blocked(self.page))
        self.d._raise_on_publisher_access_blocked(self.page)

    def test_403_without_explicit_block_text_does_not_infer_a_subscription_denial(self):
        self.d._title.return_value='Forbidden'
        self.d._body_text.return_value='HTTP 403'
        self.assertFalse(self.d._publisher_access_blocked(self.page))


if __name__=='__main__': unittest.main()


class PublisherSideFailureTests(unittest.TestCase):
    setUp = PublisherAccessBlockedTests.setUp

    def test_a_site_that_does_not_answer_is_the_publishers_side(self):
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout
        self.d._publisher_access_blocked = Mock(return_value=False)
        self.d._hold_after_run = Mock()
        for exc in (PlaywrightError("Page.goto: NS_ERROR_NET_EMPTY_RESPONSE\nCall log:"),
                    PlaywrightTimeout("Page.goto: Timeout 60000ms exceeded.")):
            self.d._ensure_login = Mock(side_effect=exc)
            with tempfile.TemporaryDirectory() as tmp:
                result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi="10.1000/fixture"), Path(tmp))
            self.assertEqual(result.state, "publisher_unreachable")
            self.assertIn("publisher_unreachable", [e["state"] for e in result.events])
        self.d._ensure_login = Mock(side_effect=KeyError("a program error"))
        with tempfile.TemporaryDirectory() as tmp:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi="10.1000/fixture"), Path(tmp))
        self.assertEqual(result.state, "unexpected_error")

    def test_a_block_met_while_fetching_supplements_ends_that_step(self):
        tab = SimpleNamespace(url="https://journals.fixture.example/article", goto=Mock(), close=Mock(),
                              context=None, locator=Mock(return_value=SimpleNamespace(
                                  first=SimpleNamespace(text_content=Mock(return_value="Just a moment...")))))
        context = SimpleNamespace(new_page=Mock(return_value=tab))
        self.d._challenge_shell = Mock(return_value=True)
        self.d._wait_for_challenge = Mock(side_effect=self.batch.PublisherAccessBlocked("publisher_access_blocked"))
        with tempfile.TemporaryDirectory() as tmp:
            files = self.d.collect_supplements(context, "10.1000/fixture", Path(tmp), self.result)
        self.assertEqual(files[0]["reason"], "publisher_access_blocked")
        self.assertEqual(self.result.state, "publisher_access_blocked")  # the main text had failed

    def test_a_browser_closed_before_the_supplements_keeps_the_articles_result(self):
        # SID Symposium Digest: the window was closed during the login wait, and
        # TargetClosedError lost the item's result as source_exception (2026-11-02).
        from playwright.sync_api import Error as PlaywrightError
        context = SimpleNamespace(new_page=Mock(side_effect=PlaywrightError("Target page, context or browser has been closed")))
        self.result.state = self.result.reason = "login_page_closed"
        with tempfile.TemporaryDirectory() as tmp:
            files = self.d.collect_supplements(context, "10.1000/fixture", Path(tmp), self.result)
        self.assertEqual(files, [{"status": "skipped", "reason": "browser_closed", "url": "", "label": ""}])
        self.assertEqual(self.result.state, "login_page_closed")
        self.assertIn("supplements_skipped", [e["state"] for e in self.result.events])
