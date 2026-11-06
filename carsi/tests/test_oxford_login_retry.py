"""Same-page Oxford retry behavior, with a deterministic clock and no network."""
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

DOI = '10.1093/jnci/fixture123'
ARTICLE = 'https://academic.oup.com/jnci/advance-article/doi/' + DOI + '/12345'


class OxfordLoginRetryTests(unittest.TestCase):
    def setUp(self):
        import test_wiley_capture as fixtures
        harness = fixtures.WileyCaptureTests(methodName='runTest')
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        self.batch = harness.batch
        self.d = self.batch.PublisherBatchDownloader({}, profile=harness.profiles.OXFORD_ACADEMIC_PROFILE,
                                                    login_timeout_sec=200)
        self.result = self.batch.DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)
        self.now = 0.0
        self.enterContext(patch.object(self.batch.time, 'monotonic', side_effect=lambda: self.now))
        self.page = Mock(url=ARTICLE)
        self.page.frames = []
        self.page.is_closed.return_value = False
        self.page.wait_for_timeout.side_effect = self.wait
        self.d.adapter.advance_login = Mock(return_value=True)
        self.state = 'publisher_login'
        self.d.adapter.login_state = Mock(side_effect=lambda page, deadline=None: self.state)

    def wait(self, milliseconds):
        self.now += milliseconds / 1000

    def events(self, name):
        return [event['detail'] for event in self.result.events if event['state'] == name]

    def test_the_discovery_page_is_left_to_the_school_assistance(self):
        # 2026-11-01: SAMS Sigma's list was read as a human login and waited on for 5 min.
        self.state = 'institution_chooser'
        self.d._select_institution = Mock(side_effect=lambda page, result: setattr(self, 'state', 'article_ready'))
        self.assertTrue(self.d.adapter.complete_login(self.page, self.result))
        self.d._select_institution.assert_called_once_with(self.page, self.result)
        self.d.adapter.advance_login.assert_not_called()
        self.assertTrue(self.d.adapter.is_institution_chooser(
            'https://oup2-ds.sams-sigma.com/?entityID=https%3A%2F%2Foup-sp.sams-sigma.com%2Fshibboleth'))
        self.assertFalse(self.d.adapter.is_institution_chooser('https://oup-sp.sams-sigma.com/Shibboleth.sso/Login'))

    def test_an_away_user_ends_the_wait_on_their_page_after_the_short_wait(self):
        self.d.config['user_wait'] = 'short'
        self.state = 'human_login'
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.result.reason, 'login_timeout')
        self.assertTrue(60 <= self.now < 200)  # the short wait, not the article's whole budget

    def test_stalled_redirect_recovers_on_same_page_and_context(self):
        def navigate(*args, **kwargs):
            self.state = 'article_ready'
        self.page.goto.side_effect = navigate
        self.assertTrue(self.d._complete_login_from_current_page(self.page, self.result))
        self.page.goto.assert_called_once()
        self.assertEqual(self.page.goto.call_args.args[0], ARTICLE)
        self.assertEqual(self.events('login_attempt_started'), ['1/3', '2/3'])
        self.assertTrue(all(call.args[0] is self.page for call in self.d.adapter.login_state.call_args_list))
        self.page.context.new_page.assert_not_called()
        self.assertLessEqual(self.now, 200)

    def test_manual_login_can_finish_after_the_original_deadline(self):
        self.d.config['user_wait'] = 'short'
        self.state = 'human_login'
        frame = Mock(evaluate=Mock(side_effect=lambda *args: int(self.now >= 2)))
        self.page.frames = [frame]
        def human_wait(ms):
            self.wait(ms)
            if self.now >= 400:
                self.state = 'article_ready'
        self.page.wait_for_timeout.side_effect = human_wait
        self.assertTrue(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.now, 400)
        self.assertEqual(self.result._oxford_login_deadline, 598)
        self.assertIsNone(self.result._login_wait)
        self.page.goto.assert_not_called()
        self.d.adapter.advance_login.assert_not_called()

    def test_repeated_transient_failure_stops_after_two_retries(self):
        self.state = 'transient_error'
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.page.goto.call_count, 2)
        self.assertEqual(self.events('login_attempt_started'), ['1/3', '2/3', '3/3'])
        self.assertEqual(self.result.reason, 'login_retries_exhausted')
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.page.goto.call_count, 2)
        self.assertEqual(self.now, 9)

    def test_a_slow_page_read_cannot_expire_a_paused_login_near_its_deadline(self):
        self.d.login_timeout_sec = 5
        self.page.frames = [Mock(evaluate=Mock(side_effect=lambda *args: int(self.now >= 4)))]
        def read_login(page, deadline=None):
            if self.now >= 5:
                self.now += 2
                return 'article_ready'
            return 'human_login'
        self.d.adapter.login_state.side_effect = read_login
        self.assertTrue(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.now, 7)
        self.assertEqual(self.result._oxford_login_deadline, 8)

    def test_total_deadline_is_shared_across_reentry_and_navigation(self):
        self.d.login_timeout_sec = 50
        def slow_navigation(*args, **kwargs):
            self.now += kwargs['timeout'] / 1000
            raise TimeoutError('synthetic navigation timeout')
        self.page.goto.side_effect = slow_navigation
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertLessEqual(self.now, 50)
        self.assertEqual(self.result.reason, 'login_timeout')
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertLessEqual(self.now, 50)
        self.assertEqual(self.events('login_attempt_started'), ['1/3', '2/3'])
        self.assertLessEqual(self.page.goto.call_args.kwargs['timeout'], 2000)

    def test_slow_observation_cannot_report_success_or_navigate_after_deadline(self):
        self.d.login_timeout_sec = 1
        def slow_read(page, deadline=None):
            self.now += 2
            return 'article_ready'
        self.d.adapter.login_state.side_effect = slow_read
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.result.reason, 'login_timeout')
        self.page.goto.assert_not_called()
        self.d.adapter.advance_login.assert_not_called()

    def test_success_on_third_attempt_cannot_allow_a_fourth_entry(self):
        self.result._oxford_login_attempt = 3
        self.result._oxford_login_deadline = 200
        self.result._oxford_login_entry_attempt = 3
        self.state = 'article_ready'
        self.assertTrue(self.d.adapter.complete_login(self.page, self.result))
        self.state = 'publisher_login'
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.result.reason, 'login_retries_exhausted')
        self.d.adapter.advance_login.assert_not_called()

    def test_certificate_and_policy_errors_are_not_retryable(self):
        from playwright._impl._errors import Error
        for message in ('net::ERR_CERT_AUTHORITY_INVALID', 'net::ERR_BLOCKED_BY_ADMINISTRATOR'):
            self.assertFalse(self.d.adapter.retryable_navigation_error(Error(message)))
        self.assertTrue(self.d.adapter.retryable_navigation_error(Error('net::ERR_CONNECTION_TIMED_OUT')))
        self.assertFalse(self.d.adapter.retryable_navigation_error(ValueError('net::ERR_CONNECTION_TIMED_OUT')))

    def test_human_password_and_verification_waits_never_navigate_or_click(self):
        for state in ('human_login', 'verification'):
            with self.subTest(state=state):
                self.state = state
                self.now = 0
                result = self.batch.DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)
                self.assertFalse(self.d.adapter.complete_login(self.page, result))
                self.assertEqual(self.now, 200)
                self.assertEqual(result.reason, 'login_timeout')
        self.page.goto.assert_not_called()
        self.d.adapter.advance_login.assert_not_called()
        self.page.locator.assert_not_called()

    def test_human_form_appearing_during_backoff_cancels_retry(self):
        self.state = 'transient_error'
        def appeared(ms):
            self.wait(ms)
            self.state = 'human_login'
        self.page.wait_for_timeout.side_effect = appeared
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.page.goto.assert_not_called()
        self.assertEqual(self.events('login_attempt_started'), ['1/3'])

    def test_terminal_failure_categories_do_not_retry(self):
        for state in ('login_page_closed', 'login_credentials_rejected',
                      'institution_not_registered', 'institution_pdf_entitlement_missing'):
            with self.subTest(state=state):
                self.state = state
                result = self.batch.DownloadResult(doi=DOI, status='failed', article_url=ARTICLE)
                self.assertFalse(self.d.adapter.complete_login(self.page, result))
                self.assertEqual(result.reason, state)
        self.page.goto.assert_not_called()
        self.d.adapter.advance_login.assert_not_called()

    def test_programming_error_is_not_swallowed_as_a_transient_failure(self):
        self.d.adapter.login_state.side_effect = ValueError('synthetic invalid state')
        with self.assertRaises(ValueError):
            self.d.adapter.complete_login(self.page, self.result)
        self.page.goto.assert_not_called()

    def test_a_first_navigation_that_times_out_goes_on_to_the_login_with_its_own_budget(self):
        # The article's opening is bounded by itself; the login's budget starts with
        # its first attempt (review 2026-11-02).
        self.d.login_timeout_sec = 10
        def initial_timeout(*args, **kwargs):
            self.now += kwargs['timeout'] / 1000
            raise TimeoutError('synthetic initial timeout')
        self.page.goto.side_effect = initial_timeout
        self.assertFalse(self.d._ensure_login(self.page, self.result))
        self.assertEqual(self.now, 20)
        self.assertEqual(self.result.reason, 'login_timeout')
        self.assertEqual(self.events('login_attempt_started'), ['1/3'])
        self.d.adapter.advance_login.assert_called_once()

    def test_the_login_budget_starts_with_its_first_attempt_not_with_the_article(self):
        # The PDF tried first took 60 s of the user's 200 (review 2026-11-02).
        for name in ('_wait_past_redirect_page', '_raise_on_publisher_content_error', '_dismiss_cookie_banners'):
            setattr(self.d, name, Mock())
        self.d._wait_for_challenge = Mock(return_value=True)
        self.d._institution_pdf_entitlement_missing = Mock(return_value=False)
        self.d._pdf_first_unless_signed_out = Mock(return_value=True)
        with patch.object(self.batch.time, 'sleep'):
            self.assertTrue(self.d._ensure_login(self.page, self.result))
        self.now += 60  # the PDF step
        self.state = 'human_login'
        self.assertFalse(self.d.adapter.complete_login(self.page, self.result))
        self.assertEqual(self.result.reason, 'login_timeout')
        self.assertEqual(self.now, 260)  # 60 + 200, not 200 from the article's opening

    def test_login_failure_diagnostic_is_unmasked_and_takes_no_oxford_screenshot(self):
        import json
        self.page.url = 'https://identity.example/sso?synthetic-token=private-fixture'
        self.result.reason = 'login_timeout'
        self.result.events = [{'state':'login_observed','detail':'private-fixture'}]
        with tempfile.TemporaryDirectory() as temp:
            self.d._write_diagnostic(self.page, self.result, Path(temp))
            diagnostic = Path(self.result.diagnostic_path).read_text()
            self.assertIn('private-fixture',diagnostic)  # diagnostic files are unmasked by user decision
            self.assertEqual(json.loads(diagnostic)['reason'],'login_timeout')
            self.assertEqual(list(Path(temp).rglob('*.png')),[])
        self.page.screenshot.assert_not_called()

    def test_pdf_stage_relogin_failure_reason_is_not_lost(self):
        del self.page.new_page
        self.d._ensure_login = Mock(return_value=True)
        self.d._looks_logged_out = Mock(side_effect=[False, True, True])
        self.d._article_access_available = Mock(return_value=False)
        self.d._capture_pdf = Mock(return_value=(None,'',None))
        self.d._hold_after_login = Mock()
        self.d._login_block_reason = Mock(return_value='')
        self.d._write_diagnostic = Mock()
        def failed(page, result):
            result.reason = 'login_retries_exhausted'
            return False
        self.d._complete_login_from_current_page = failed
        with tempfile.TemporaryDirectory() as temp:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(temp))
        self.assertEqual(result.state,'login_retries_exhausted')

    def test_failure_reason_survives_fetch_one(self):
        del self.page.new_page
        self.d._ensure_login = lambda page, result: self.d.adapter.complete_login(page, result)
        self.d._article_access_available = Mock(return_value=False)
        self.d._login_block_reason = Mock(return_value='')
        self.d._write_diagnostic = Mock()
        self.state = 'transient_error'
        with tempfile.TemporaryDirectory() as temp:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(temp))
        self.assertEqual(result.state, 'login_retries_exhausted')
        self.assertEqual(self.page.goto.call_count, 2)

    def test_challenge_poll_respects_a_fractional_remaining_budget(self):
        self.d._raise_on_publisher_access_blocked = Mock()
        self.d._is_challenge_page = Mock(return_value=True)
        with patch.object(self.batch.time, 'time', side_effect=lambda: self.now), patch.object(
                self.batch.progress_reporter, 'set_attention', create=True), patch.object(
                self.batch.progress_reporter, 'clear_attention', create=True):
            self.assertFalse(self.d._wait_for_challenge(self.page, self.result, deadline=0.25))
        self.assertEqual(self.now, 0.25)
        self.page.wait_for_timeout.assert_called_once_with(250)

    def test_closed_article_page_keeps_terminal_login_reason_without_access_probe(self):
        del self.page.new_page
        self.page.is_closed.return_value = True
        def closed(page, result):
            result.reason = 'login_page_closed'
            return False
        self.d._ensure_login = closed
        self.d._write_diagnostic = Mock()
        self.d._looks_logged_out = Mock()
        self.d._capture_pdf = Mock()
        with tempfile.TemporaryDirectory() as temp:
            result = self.d.fetch_one(self.page, self.batch.PaperRecord(doi=DOI), Path(temp))
        self.assertFalse(result.ok)
        self.assertEqual(result.state, 'login_page_closed')
        self.d._looks_logged_out.assert_not_called()
        self.d._capture_pdf.assert_not_called()
        self.page.locator.assert_not_called()


if __name__ == '__main__':
    unittest.main()
