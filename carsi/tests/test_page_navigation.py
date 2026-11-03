"""The login's and its returns' navigations go on once the page can be read, not
at DOMContentLoaded: pubs.acs.org showed its article 4.5 s after the request and
held DOMContentLoaded back until 33 s on an ad script that never answered
(probe, 2026-11-02); each return to the article took 32-40 s. Mocked pages for
the wait's rule; a local Chrome page whose script never loads for the real one
(opt-in fixture, all requests answered locally)."""
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from paper_search_carsi.engine import batch_common
from paper_search_carsi.engine.batch_common import _DOCUMENT_STATE_JS, open_page

ARTICLE = "https://www.fixture-press.example/doi/10.1000/xyz"


def page_with(states):
    page = MagicMock()
    page.url = ARTICLE
    page.title.return_value = "Article"
    sequence = iter(states)
    last = [None]

    def evaluate(script, *args):
        assert script == _DOCUMENT_STATE_JS
        last[0] = next(sequence, last[0])
        return last[0]
    page.evaluate.side_effect = evaluate
    clock = [1000.0]
    page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0] + ms / 1000)
    page.clock = clock
    return page


def opened(page, **kwargs):
    with patch.object(batch_common.time, "time", lambda: page.clock[0]):
        open_page(page, ARTICLE, **kwargs)


class OpenPageTests(unittest.TestCase):
    def test_the_navigation_commits_and_a_parsed_page_goes_on_at_once(self):
        page = page_with([["interactive", 3000]])
        opened(page, timeout_ms=30_000, referer="https://doi.org/")
        page.goto.assert_called_once_with(ARTICLE, wait_until="commit", timeout=30_000, referer="https://doi.org/")
        page.wait_for_timeout.assert_not_called()

    def test_a_page_still_loading_goes_on_once_its_text_stops_growing(self):
        page = page_with([["loading", 0], ["loading", 900], ["loading", 5200]])
        opened(page)
        self.assertAlmostEqual(page.clock[0] - 1000, 1.5)  # 5200 characters for a second, polled every 0.25 s

    def test_a_verification_page_is_left_untouched(self):
        page = page_with([["loading", 0]])
        page.title.return_value = "Just a moment..."
        opened(page)
        page.evaluate.assert_not_called()  # the challenge wait takes it, without scripts on the page

    def test_an_empty_page_is_waited_for_at_most_ready_ms(self):
        page = page_with([["loading", 0]])
        opened(page, ready_ms=5_000)
        self.assertAlmostEqual(page.clock[0] - 1000, 5)


class PumpUntilTests(unittest.TestCase):
    def test_a_slow_condition_is_bounded_by_the_clock_not_by_passes(self):
        # A check taking 2 s made twenty passes of a 5 s wait last 47 s (review 2026-11-02).
        clock = [0.0]

        def slow_check():
            clock[0] += 2
            return False
        page = MagicMock()
        page.wait_for_timeout.side_effect = lambda ms: clock.__setitem__(0, clock[0] + ms / 1000)
        with patch.object(batch_common.time, "monotonic", lambda: clock[0]):
            self.assertFalse(batch_common.pump_until(page, slow_check, 5_000))
        self.assertLessEqual(clock[0], 5 + 2)  # at most the pass that crossed the deadline
        self.assertEqual(page.wait_for_timeout.call_count, 2)

    def test_the_condition_holding_ends_the_wait_at_once(self):
        page = MagicMock()
        answers = iter([False, False, True])
        self.assertTrue(batch_common.pump_until(page, lambda: next(answers), 5_000))
        self.assertEqual(page.wait_for_timeout.call_count, 2)


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class OpenPagePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def test_a_script_that_never_answers_does_not_hold_the_article(self):
        context = self.browser.new_context(service_workers="block")
        self.addCleanup(context.close)
        article = ("<title>Article</title><h1>Investigation of a synthetic binding site</h1>"
                   + "<p>Abstract. " + "Results and methods of the synthetic study. " * 40 + "</p>"
                   + '<script src="https://ads.fixture.example/gpt.js"></script><footer>Footer</footer>')

        def respond(route):
            if "ads.fixture.example" in route.request.url:
                return  # never answered, as the ad script was
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=article)
        context.route("**/*", respond)
        page = context.new_page()
        started = time.time()
        open_page(page, ARTICLE, ready_ms=15_000)
        self.assertLess(time.time() - started, 8)
        self.assertEqual(page.evaluate("document.readyState"), "loading")  # DOMContentLoaded still held back
        self.assertIn("synthetic binding site", page.locator("h1").inner_text())


if __name__ == "__main__":
    unittest.main()
