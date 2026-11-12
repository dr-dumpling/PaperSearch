"""Publisher restarts use only the existing, scoped publisher cookie cache."""
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_school.publishers.profiles import ACS_PROFILE, ELSEVIER_PROFILE, SPRINGER_PROFILE


class PublisherSessionReuseTests(unittest.TestCase):
    def test_legacy_session_marker_is_normalized_only_at_browser_boundary(self):
        from paper_search_school.browser.cookies import _restore_cookies_to_context
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            expiry = time.time() + 300
            saved = [
                dict(name='legacy', value='fixture', domain='.sciencedirect.com', path='/', expires=0),
                dict(name='persistent', value='fixture', domain='.sciencedirect.com', path='/', expires=expiry),
            ]
            path = cache/'publisher_cookies.json'
            path.write_text(json.dumps(saved))
            context = Mock()
            self.assertTrue(_restore_cookies_to_context(context, {'cache_dir': directory}))
            restored = context.add_cookies.call_args.args[0]
            self.assertEqual(restored[0]['expires'], -1)
            self.assertEqual(restored[1]['expires'], expiry)
            self.assertEqual(json.loads(path.read_text()), saved)

    def test_success_saves_publisher_session_and_next_launch_restores_missing_only(self):
        self._assert_session_reuse(ELSEVIER_PROFILE, '.sciencedirect.com')

    def test_acs_success_saves_session_and_restart_keeps_fresh_live_cookies(self):
        self._assert_session_reuse(ACS_PROFILE, '.acs.org')

    def test_nature_success_saves_session_and_restart_keeps_fresh_live_cookies(self):
        self._assert_session_reuse(SPRINGER_PROFILE, '.nature.com')

    def test_springer_success_saves_session_and_restart_keeps_fresh_live_cookies(self):
        self._assert_session_reuse(SPRINGER_PROFILE, '.link.springer.com')

    def test_declared_custom_publisher_reuses_session_without_a_name_allowlist(self):
        custom = replace(ELSEVIER_PROFILE, name='Fixture Press', base_domains=('journals.fixture.example',))
        self._assert_session_reuse(custom, '.journals.fixture.example')

    def _assert_session_reuse(self, profile, publisher_domain):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'cache_dir': str(root/'cache'), 'chrome_profile_dir': str(root/'profile')}
            original = PublisherBatchDownloader(config=config, profile=profile)
            page = Mock(spec=['context', 'url', 'close', 'wait_for_load_state', 'on', 'remove_listener'])
            page.url = 'https://www.sciencedirect.com/science/article/pii/S0000000000000000'
            def cookie(name, value, domain=publisher_domain, expires=-1):
                return dict(name=name, value=value, domain=domain, path='/', expires=expires,
                            secure=True, httpOnly=True, sameSite='None')
            page.context.cookies.return_value = [
                cookie('session', 'fixture-session'), cookie('live', 'old-fixture'),
                cookie('expired', 'expired-fixture', expires=1),
                cookie('idp', 'excluded-fixture', domain='login.university.example'),
            ]
            original._ensure_login = Mock(return_value=True)
            original._looks_logged_out = Mock(return_value=False)
            original._access_decision = Mock(return_value=('in', 'session', ''))  # signed in
            original._title = Mock(return_value='Session fixture')
            original._hold_after_login = Mock()
            original._hold_after_run = Mock()
            original._capture_pdf = Mock(return_value=(b'%PDF-1.7\n'+b'x'*6000, 'https://example.invalid/fixture.pdf', None))
            original._text_matches_record = Mock(return_value=True)
            original._accept_pdf_body = Mock(return_value=True)
            with patch('paper_search_school.engine.batch.time.sleep'), patch(
                'paper_search_school.engine.batch.pdf_extractor.extract_from_bytes', return_value='Session fixture'
            ):
                result = original.fetch_one(page, PaperRecord(doi='10.1000/fixture'), root/'download')
            self.assertTrue(result.ok)
            self.assertIn('publisher_session_saved', [e['state'] for e in result.events])
            saved = json.loads((root/'cache/publisher_cookies.json').read_text())
            self.assertNotIn('idp', [c['name'] for c in saved])
            self.assertEqual(next(c for c in saved if c['name']=='session')['expires'], -1)

            restarted = PublisherBatchDownloader(config=config, profile=profile)
            context = Mock()
            context.pages = []
            context.cookies.return_value = [cookie('live', 'fresh-fixture')]
            with patch('paper_search_school.browser.engine.get_persistent_context', return_value=context) as launch:
                self.assertIs(restarted._launch_context(), context)
            self.assertEqual(launch.call_args.args[0], root/'profile')
            restored = context.add_cookies.call_args.args[0]
            self.assertEqual([c['name'] for c in restored], ['session'])
            self.assertEqual(restored[0]['expires'], -1)
            self.assertTrue(restored[0]['secure'])
            self.assertTrue(restored[0]['httpOnly'])
            self.assertEqual(restored[0]['sameSite'], 'None')

    def test_save_failure_is_explicit_and_contains_no_exception_text(self):
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        page = Mock()
        page.context.cookies.side_effect = RuntimeError('SECRET cookie token')
        result = DownloadResult(doi='10.1000/fixture', status='success')
        d._save_publisher_session(page, result)
        self.assertEqual(result.events[-1]['state'], 'publisher_session_save_failed')
        self.assertNotIn('SECRET', json.dumps(result.events))


if __name__ == '__main__':
    unittest.main()
