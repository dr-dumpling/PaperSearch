from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_search_carsi.browser import watchdog
from paper_search_carsi.engine.batch import PublisherBatchDownloader, DownloadResult, PaperRecord
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE


class PublisherManualWaitTests(unittest.TestCase):
    def setUp(self):
        self.downloader = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE, login_timeout_sec=1)
        self.page = Mock(url='https://www.sciencedirect.com/science/article/pii/S0002916525005908')
        self.page.frames = []
        del self.page.new_page
        self.downloader._title = Mock(return_value='Just a moment...')
        self.downloader._body_text = Mock(return_value='Verify you are human')
        self.downloader._write_diagnostic = Mock()
        self.downloader._hold_after_run = Mock()

    def test_challenge_at_article_url_is_not_fulltext_access(self):
        self.downloader._looks_logged_out = Mock(return_value=False)
        self.assertFalse(self.downloader._article_access_available(self.page))
        self.downloader._looks_logged_out.assert_not_called()

    def test_expired_verification_never_attempts_pdf_or_relogin(self):
        self.downloader._ensure_login = Mock(return_value=False)
        self.downloader._capture_pdf = Mock()
        self.downloader._complete_login_from_current_page = Mock()
        with tempfile.TemporaryDirectory() as temp, patch('paper_search_carsi.engine.batch.time.sleep'):
            result = self.downloader.fetch_one(self.page, PaperRecord(doi='10.1000/test'), Path(temp))
        self.assertFalse(result.ok)
        self.assertEqual(result.state, 'challenge_or_viewer_timeout')
        self.downloader._capture_pdf.assert_not_called()
        self.downloader._complete_login_from_current_page.assert_not_called()
        self.assertNotIn('login_completed_after_timeout', [event['state'] for event in result.events])

    def test_manual_completion_processes_events_then_continues_same_page(self):
        self.downloader.login_timeout_sec = 60
        def browser_wait(_milliseconds):
            self.downloader._title.return_value = 'Article title'
            self.downloader._body_text.return_value = 'Research article'
            # ScienceDirect's "Full text access" label by the title (access_rules.PROBE_JS)
            self.downloader._access_probe = Mock(return_value={'badges': ['Full text access']})
        self.page.wait_for_timeout.side_effect = browser_wait
        result = DownloadResult(doi='10.1000/test', status='failed')
        self.assertTrue(self.downloader._wait_for_challenge(self.page, result))
        self.page.wait_for_timeout.assert_called_once_with(1000)
        self.page.goto.assert_not_called()
        self.assertTrue(self.downloader._article_access_available(self.page))
        self.assertIn('challenge_resolved', [event['state'] for event in result.events])

    def test_spent_article_budget_during_verification_is_not_a_browser_failure(self):
        self.downloader.login_timeout_sec = 60
        def verify_near_deadline(page, result):
            with watchdog.operation(0.5, "_prepare_article"):
                return self.downloader._wait_for_challenge(page, result)
        self.downloader._ensure_login = verify_near_deadline
        with tempfile.TemporaryDirectory() as temp:
            result = self.downloader.fetch_one(self.page, PaperRecord(doi='10.1000/test'), Path(temp))
        self.page.wait_for_timeout.assert_not_called()
        self.assertEqual(result.reason, 'challenge_or_viewer_timeout')
        self.assertEqual(result.state, 'challenge_or_viewer_timeout')
        self.assertNotIn('browser_operation_timeout', [event['state'] for event in result.events])

    def test_content_error_at_landing_page_stops_before_login(self):
        self.downloader._body_text.return_value = 'CPE00001 There was a problem providing the content you requested'
        self.downloader._complete_login_from_current_page = Mock()
        self.downloader._capture_pdf = Mock()
        with tempfile.TemporaryDirectory() as temp, patch('paper_search_carsi.engine.batch.time.sleep'):
            result = self.downloader.fetch_one(self.page, PaperRecord(doi='10.1000/test'), Path(temp))
        self.assertEqual(result.state, 'publisher_content_error')
        self.page.goto.assert_called_once()
        self.downloader._complete_login_from_current_page.assert_not_called()
        self.downloader._capture_pdf.assert_not_called()

    def test_pdf_challenge_does_not_try_another_pdf_candidate(self):
        d = self.downloader
        self.page.context.browser = None
        d._return_to_record_article_if_needed = Mock(return_value=False)
        d._click_pdf_entry = Mock(return_value=False)
        d._pdf_candidates = Mock(return_value=['https://www.sciencedirect.com/first.pdf', 'https://www.sciencedirect.com/second.pdf'])
        d._should_use_async_pdf_navigation = Mock(return_value=True)
        d._capture_pdf_via_async_navigation = Mock(return_value=(None, self.page.url))
        result = DownloadResult(doi='10.1000/test', status='failed')
        self.assertIsNone(d._capture_pdf(self.page, result.doi, result)[0])
        d._capture_pdf_via_async_navigation.assert_called_once()


if __name__ == '__main__':
    unittest.main()
