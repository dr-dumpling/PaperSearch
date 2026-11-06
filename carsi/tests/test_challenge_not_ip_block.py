"""A human-verification page on the PDF step is waited for, never reported as an IP block."""
import unittest

from paper_search_carsi.engine.batch import PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import ELSEVIER_PROFILE

CLOUDFLARE = """<!DOCTYPE html><html><head><title>Just a moment...</title>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></head>
<body><h1>pdf.sciencedirectassets.com</h1><p>Verify you are human by completing the action below.</p></body></html>"""
ELSEVIER_ROBOT = "<html><title>ScienceDirect</title><body>Are you a robot? Please confirm you are a human.</body></html>"
CHINESE = "<html><body>请完成安全验证后继续访问</body></html>"
ACS_BLOCK = "<html><title>IP Address Blocked</title><body>Your IP address has been blocked. ipblock@acs.org</body></html>"


class ChallengeIsNotIpBlockTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE)

    def test_challenge_pages_with_403_or_429_are_not_blocks(self):
        for body in (CLOUDFLARE, ELSEVIER_ROBOT, CHINESE, CLOUDFLARE.encode()):
            for status in (403, 429, 503, 200):
                with self.subTest(status=status, body=str(body)[:30]):
                    self.assertFalse(self.d._is_ip_block_response(status, body))

    def test_real_blocks_are_still_detected(self):
        self.assertTrue(self.d._is_ip_block_response(403, ""))
        self.assertTrue(self.d._is_ip_block_response(429, None))
        self.assertTrue(self.d._is_ip_block_response(403, "<html>Forbidden</html>"))
        self.assertTrue(self.d._is_ip_block_response(200, ACS_BLOCK))
        self.assertTrue(self.d._is_ip_block_response(None, ACS_BLOCK.encode()))
        self.assertFalse(self.d._is_ip_block_response(200, "<html>ordinary article</html>"))


    def test_a_plain_http_403_is_not_the_publisher_blocking_the_browser(self):
        # 2026-10-31: the refetch of a ScienceDirect PDF got 403 and stopped the batch.
        from unittest.mock import Mock, patch
        self.d._pdf_request_headers = Mock(return_value={})
        for status, body, block in ((403, "<html>Forbidden</html>", None), (403, ACS_BLOCK, "ip_blocked")):
            resp = Mock(status_code=status, text=body, url="https://www.sciencedirect.com/x/pdfft", content=b"")
            with patch("requests.get", return_value=resp):
                self.assertEqual(self.d._fetch_pdf_url("https://www.sciencedirect.com/x/pdfft")[2], block)

    def test_a_403_showing_the_articles_own_page_is_not_a_verification(self):
        # World Scientific's PDF answered 403 with the abstract page (2026-11-03).
        self.d._expected_title = "Dual Multi-RAG: Multi-View Contrastive Learning for Code Completion"
        page = ("Dual Multi-RAG: Multi-View Contrastive Learning for Code Completion | International Journal of "
                "Software Engineering and Knowledge Engineering Purchase this article")
        self.assertTrue(self.d._article_page_answer(page))
        self.assertFalse(self.d._article_page_answer("Just a moment... Verify you are human"))
        self.d._expected_title = ""
        self.assertFalse(self.d._article_page_answer(page))  # without the title nothing is known


class SuspectBlockResolutionTests(unittest.TestCase):
    """A 403/429 on the PDF step waits for the user before it may become ip_blocked."""

    def setUp(self):
        from unittest.mock import MagicMock
        from paper_search_carsi.engine.batch import DownloadResult
        self.d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE, require_interactive_browser=True)
        self.d.login_timeout_sec = 300
        self.article, self.pdf_tab = MagicMock(), MagicMock()
        self.article.url = "https://www.sciencedirect.com/science/article/pii/S1"
        self.pdf_tab.url = "https://pdf.sciencedirectassets.com/1/main.pdf"
        for p in (self.article, self.pdf_tab):
            p.is_closed.return_value = False
        self.article.context.pages = [self.article, self.pdf_tab]
        self.result = DownloadResult(doi="10.1016/x", status="failed")
        self.captured = {"block_reason": None, "bytes": None,
                         "suspect_block": "403 https://pdf.sciencedirectassets.com/1/main.pdf"}
        self.attention = {}
        import paper_search_carsi.progress_reporter as pr
        self.patches = [unittest.mock.patch.object(pr, "set_attention", side_effect=lambda k, m, **kw: self.attention.update({k: m})),
                        unittest.mock.patch.object(pr, "clear_attention", side_effect=lambda k: self.attention.pop(k, None)),
                        unittest.mock.patch.object(pr, "report_stage")]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        self.d._pdf_step_needs_login = lambda p: False

    def test_suspect_tab_that_advances_quickly_does_not_request_intervention(self):
        ticks = []
        def user_completes(ms):
            ticks.append(ms)
            self.assertFalse(self.attention)  # a short automatic redirect stays quiet
            if len(ticks) == 2:
                self.pdf_tab.url = "https://www.sciencedirect.com/science/article/pii/S1"  # verification done, tab moved on
        self.article.wait_for_timeout.side_effect = user_completes
        self.d._is_challenge_page = lambda p: False  # unknown wording: the suspect host alone keeps us waiting
        self.assertTrue(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertIsNone(self.captured["block_reason"])
        self.assertEqual(len(ticks), 2)
        self.pdf_tab.bring_to_front.assert_not_called()
        states = [e["state"] for e in self.result.events]
        self.assertIn("pdf_step_unknown_wait", states)
        self.assertIn("challenge_resolved", states)
        self.assertEqual(self.attention, {})  # the reminder is cleared afterwards

    def test_pdf_captured_during_the_wait_is_success(self):
        def captured_now(ms):
            self.captured["bytes"] = b"%PDF-1.7 ..."
        self.article.wait_for_timeout.side_effect = captured_now
        self.d._is_challenge_page = lambda p: p is self.pdf_tab
        self.assertTrue(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertIsNone(self.captured["block_reason"])

    def test_unfinished_verification_is_a_timeout_not_a_block(self):
        self.d.PAGE_WAIT_SEC = 0.05
        self.d.login_timeout_sec = 0
        self.d._is_challenge_page = lambda p: p is self.pdf_tab
        with unittest.mock.patch.object(PublisherBatchDownloader, "PAGE_WAIT_SEC", 0.05):
            self.article.wait_for_timeout.side_effect = lambda ms: __import__("time").sleep(0.03)
            self.assertFalse(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertEqual(self.captured["block_reason"], "challenge_or_viewer_timeout")
        self.assertIn("challenge_unresolved", [e["state"] for e in self.result.events])
        self.assertEqual(self.attention, {})

    def test_only_after_the_bounded_wait_is_an_unexplained_403_an_ip_block(self):
        self.d.login_timeout_sec = 0
        self.d._is_challenge_page = lambda p: False
        with unittest.mock.patch.object(PublisherBatchDownloader, "PAGE_WAIT_SEC", 0.05), \
                unittest.mock.patch.object(PublisherBatchDownloader, "SUSPECT_UNKNOWN_GRACE_SEC", 60):
            self.article.wait_for_timeout.side_effect = lambda ms: __import__("time").sleep(0.03)
            self.assertFalse(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertEqual(self.captured["block_reason"], "ip_blocked")

    def test_terminal_state_of_a_blocked_capture(self):
        from paper_search_carsi.engine.batch import _block_state
        self.assertEqual(_block_state("challenge_or_viewer_timeout"), "challenge_or_viewer_timeout")
        self.assertEqual(_block_state("ip_blocked"), "ip_blocked")

    def test_no_verification_or_suspect_tab_hands_back_to_the_capture_loop(self):
        self.pdf_tab.url = "https://www.sciencedirect.com/other"
        self.d._is_challenge_page = lambda p: False
        self.assertTrue(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertIsNone(self.captured["block_reason"])
        self.article.wait_for_timeout.assert_not_called()

    def test_nothing_suspect_changes_nothing(self):
        self.captured["suspect_block"] = None
        self.assertTrue(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.article.wait_for_timeout.assert_not_called()

    def test_access_wall_asks_for_institution_login_and_retries_once_logged_in(self):
        logged_in = {"done": False}
        def user_logs_in(ms):
            logged_in["done"] = True
        self.article.wait_for_timeout.side_effect = user_logs_in
        self.d._is_challenge_page = lambda p: False
        self.d._pdf_step_needs_login = lambda p: p is self.pdf_tab and not logged_in["done"]
        self.d._users_login_step = self.d._pdf_step_needs_login
        self.pdf_tab.url = "https://onlinelibrary.wiley.com/doi/epdf/10.1002/x"
        self.captured["suspect_block"] = "403 https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/x"
        with unittest.mock.patch.object(PublisherBatchDownloader, "SUSPECT_UNKNOWN_GRACE_SEC", 0):
            self.assertTrue(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertIsNone(self.captured["block_reason"])
        self.assertIn("pdf_step_login_wait", [e["state"] for e in self.result.events])
        self.assertEqual(self.attention, {})

    def test_unknown_page_grace_is_not_a_successful_verification(self):
        self.d._is_challenge_page = lambda p: False
        with unittest.mock.patch.object(PublisherBatchDownloader, "SUSPECT_UNKNOWN_GRACE_SEC", 0):
            self.assertFalse(self.d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertEqual(self.captured["block_reason"], "ip_blocked")
        self.assertNotIn("challenge_resolved", [e["state"] for e in self.result.events])
        self.article.wait_for_timeout.assert_not_called()

    def test_non_interactive_browser_keeps_the_one_shot_decision(self):
        d = PublisherBatchDownloader({}, profile=ELSEVIER_PROFILE)
        d._is_challenge_page = lambda p: False
        self.assertFalse(d._resolve_suspect_block(self.article, self.result, self.captured))
        self.assertEqual(self.captured["block_reason"], "ip_blocked")
        self.article.wait_for_timeout.assert_not_called()

    def test_explicit_block_page_detection(self):
        self.assertTrue(PublisherBatchDownloader._is_explicit_block_page(ACS_BLOCK))
        self.assertFalse(PublisherBatchDownloader._is_explicit_block_page(CLOUDFLARE))
        self.assertFalse(PublisherBatchDownloader._is_explicit_block_page("<html>Forbidden</html>"))
        self.assertFalse(PublisherBatchDownloader._is_explicit_block_page(""))
        excerpt = PublisherBatchDownloader._visible_text_excerpt(CLOUDFLARE)
        self.assertIn("Verify you are human", excerpt)
        self.assertNotIn("<script", excerpt)


if __name__ == "__main__":
    unittest.main()
