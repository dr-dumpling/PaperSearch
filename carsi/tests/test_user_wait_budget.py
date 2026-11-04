"""Waits on the user share one budget per article; when the user seems away they are short."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from paper_search_carsi.browser import watchdog
from paper_search_carsi.engine import batch, bridge
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.batch_common import PublisherContentError
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE, get_publisher_profile

ARTICLE = "https://www.sciencedirect.com/science/article/pii/S0002916525005908"


class BlankPageTests(unittest.TestCase):
    """De Gruyter's article page showed no text for 9 s (2026-11-02): it is waited for."""

    def page(self, lengths):
        clock = [1000.0]
        page = Mock(url="https://www.degruyterbrill.com/document/doi/10.1515/x/html")
        def read_text(script):
            value = lengths.pop(0) if lengths else 0
            if isinstance(value, BaseException):
                raise value
            return value
        page.evaluate.side_effect = read_text
        page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0] + ms / 1000)
        clock_patch = patch.object(batch.time, "time", lambda: clock[0])
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        return page, clock

    def test_a_page_drawing_its_text_late_is_waited_for(self):
        d, result = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE), DownloadResult(doi="10.1515/x", status="failed")
        page, clock = self.page([0] * 19 + [11521])
        d._wait_for_page_text(page, result)
        self.assertEqual(clock[0], 1009)
        self.assertEqual(result.events[-1]["detail"], "blank page: 9 s, ended: text shown")

    def test_a_page_with_text_or_a_pdf_is_not_waited_for(self):
        d, result = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE), DownloadResult(doi="10.1515/x", status="failed")
        for first in (120, -1):
            page, clock = self.page([first])
            d._wait_for_page_text(page, result)
            self.assertEqual((clock[0], result.events), (1000.0, []))

    def test_a_page_drawing_after_twenty_seconds_is_still_allowed_to_load(self):
        # AIP passed verification but was discarded before its article appeared.
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        result = DownloadResult(doi="10.1515/x", status="failed")
        page, clock = self.page([0] * 51 + [11521])
        d._wait_for_page_text(page, result)
        self.assertEqual(clock[0], 1025)
        self.assertEqual(result.events[-1]["detail"], "blank page: 25 s, ended: text shown")

    def test_navigation_during_the_text_probe_does_not_mean_the_page_is_ready(self):
        from playwright.sync_api import Error
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        result = DownloadResult(doi="10.1515/x", status="failed")
        page, clock = self.page([Error("Execution context was destroyed, most likely because of a navigation"), 0, 120])
        d._wait_for_page_text(page, result)
        self.assertEqual(clock[0], 1000.5)

    def test_a_page_still_blank_is_the_publisher_s_page_not_loading(self):
        d, result = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE), DownloadResult(doi="10.1515/x", status="failed")
        page, clock = self.page([])
        with self.assertRaisesRegex(PublisherContentError, r"publisher_page_blank: .*degruyterbrill.* no text for 60 s"):
            d._wait_for_page_text(page, result)
        self.assertEqual(clock[0], 1060)

    def test_a_permanently_blank_page_obeys_the_configured_page_wait(self):
        d = PublisherBatchDownloader(config={"browser_page_wait_timeout": 15}, profile=ELSEVIER_PROFILE)
        result = DownloadResult(doi="10.1515/x", status="failed")
        page, clock = self.page([])
        with self.assertRaisesRegex(PublisherContentError, r"no text for 15 s"):
            d._wait_for_page_text(page, result)
        self.assertEqual(clock[0], 1015)


class UserWaitBudgetTests(unittest.TestCase):
    def downloader(self, **config):
        d = PublisherBatchDownloader(config=config, profile=ELSEVIER_PROFILE, login_timeout_sec=180)
        d._check_user_decision = Mock()
        d._raise_on_publisher_access_blocked = Mock()
        return d

    def verification_page(self):
        """A page that stays on a verification check; waiting advances a fake clock."""
        clock = [1000.0]
        page = Mock(url=ARTICLE)
        page.frames = []
        page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0] + ms / 1000)
        clock_patch = patch.object(batch.time, "time", lambda: clock[0])
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        return page, clock

    def test_waits_on_the_user_share_one_budget_per_article(self):
        d = self.downloader()
        d._challenge_shell = Mock(return_value=True)
        d._is_challenge_page = Mock(return_value=True)
        page, clock = self.verification_page()
        result = DownloadResult(doi="10.1016/x", status="failed")
        # A verification page waits a page wait (60 s); later ones in the same article
        # (e.g. after the school login) each get one, within the article's 180 s.
        for end in (1060, 1120, 1180, 1180):
            self.assertFalse(d._wait_for_challenge(page, result))
            self.assertEqual(clock[0], end)
        self.assertTrue(result._user_wait_expired)

    def test_when_the_user_seems_away_each_wait_is_short(self):
        d = self.downloader(user_wait="short")
        page, clock = self.verification_page()
        result = DownloadResult(doi="10.1016/x", status="failed")
        # A verification that passes on its own after 25 s (checked every second) ...
        d._challenge_shell = Mock(side_effect=[True] * 25 + [False] * 2)
        d._is_challenge_page = Mock(return_value=False)
        self.assertTrue(d._wait_for_challenge(page, result))
        self.assertEqual(clock[0], 1025)
        # ... and the next wait gets its own short wait, not the rest of a shared one.
        d._challenge_shell = Mock(return_value=True)
        d._is_challenge_page = Mock(return_value=True)
        self.assertFalse(d._wait_for_challenge(page, result))
        self.assertEqual(clock[0], 1025 + batch.AWAY_WAIT_SEC)
        self.assertTrue(result._user_wait_expired)

    def login_loop(self, d, page, result, clock):
        for name in ("_dismiss_cookie_banners", "_click_openathens_entry", "_select_institution",
                     "_click_sso_entry", "_institution_pdf_entitlement_missing", "_challenge_shell",
                     "_follow_federated_login_option", "_return_to_record_article_if_needed",
                     "_article_access_available", "_has_publisher_institution_session",
                     "_is_success_article_url", "_on_publisher_host", "_is_idp_host",
                     "_is_challenge_page", "_click_optional_continue", "_looks_logged_out"):
            setattr(d, name, Mock(return_value=False))
        d._login_block_reason = Mock(return_value=None)
        d._title = Mock(return_value="Sign in")
        d._is_human_login_page = Mock(return_value=True)
        with patch.object(batch.time, "sleep", lambda sec: clock.__setitem__(0, clock[0] + sec)), \
                patch.object(batch.time, "time", lambda: clock[0]):
            return d._complete_login_from_current_page(page, result)

    def test_when_the_user_seems_away_an_untouched_login_page_ends_after_the_short_wait(self):
        d = self.downloader(user_wait="short")
        d._visible_input_values = Mock(return_value=("", ""))
        clock = [1000.0]
        page = Mock(url="https://cas.school.example/login")
        result = DownloadResult(doi="10.1002/x", status="failed", article_url=ARTICLE)
        self.assertFalse(self.login_loop(d, page, result, clock))
        self.assertTrue(result._user_wait_expired)
        # 9 s of entry steps, then a minute on the same page; far short of the 180-second total.
        self.assertLess(clock[0] - 1000, 9 + batch.AWAY_WAIT_SEC + 6)

    def test_someone_typing_on_the_login_page_is_waited_for(self):
        d = self.downloader(user_wait="short")
        typed = iter(range(1000))
        d._visible_input_values = Mock(side_effect=lambda page: (str(next(typed)), ""))
        clock = [1000.0]
        page = Mock(url="https://cas.school.example/login")
        result = DownloadResult(doi="10.1002/x", status="failed", article_url=ARTICLE)
        self.assertFalse(self.login_loop(d, page, result, clock))
        # Waited to the article's total (180 s after the entry steps), not just the short wait.
        self.assertGreaterEqual(clock[0] - 1000, 180)
        self.assertTrue(result._user_wait_expired)

    def test_a_login_that_waited_out_on_the_user_is_reported_as_a_login_timeout(self):
        result = DownloadResult(doi="10.1016/x", status="failed")
        result.state = result.reason = "sso_required"
        result._user_wait_expired = True
        engine = MagicMock()
        engine.fetch_one.return_value = result
        with patch.object(watchdog, "fired", None), \
                patch.object(batch, "PublisherBatchDownloader", return_value=engine), \
                patch("paper_search_carsi.browser.backend.is_available", return_value=True):
            out = bridge._try_browser_batch_download("10.1016/x", Path("/tmp/out/x.pdf"), {"user_wait": "short"},
                                                     get_publisher_profile("elsevier"))
        self.assertEqual(out["error_type"], "login_timeout")


if __name__ == "__main__":
    unittest.main()
