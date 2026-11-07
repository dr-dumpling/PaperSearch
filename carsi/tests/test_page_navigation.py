"""The login's and its returns' navigations go on once the page can be read, not
at DOMContentLoaded: pubs.acs.org showed its article 4.5 s after the request and
held DOMContentLoaded back until 33 s on an ad script that never answered
(probe, 2026-11-02); each return to the article took 32-40 s. Mocked pages for
the wait's rule; a local Chrome page whose script never loads for the real one
(opt-in fixture, all requests answered locally)."""
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from paper_search_carsi.engine import batch_common
from paper_search_carsi.engine import supplements
from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.engine.batch_common import _DOCUMENT_STATE_JS, open_page
from paper_search_carsi.publishers.profiles import ACS_PROFILE

ARTICLE = "https://www.fixture-press.example/doi/10.1000/xyz"


def page_with(states):
    page = MagicMock()
    page.url = ARTICLE
    page.locator.return_value.first.text_content.return_value = "Article"
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
    def test_aborted_redirect_continues_only_after_a_main_frame_commit(self):
        from patchright.sync_api import Error
        for committed in (False, True):
            with self.subTest(committed=committed):
                page = page_with([["interactive", 3000]])
                page.main_frame.url = ARTICLE
                callbacks = {}
                page.on.side_effect = lambda name, callback: callbacks.update({name:callback})
                def goto(*args, **kwargs):
                    if committed:
                        callbacks['framenavigated'](page.main_frame)
                    raise Error('Page.goto: net::ERR_ABORTED at https://publisher.example/article')
                page.goto.side_effect = goto
                if committed:
                    opened(page, ready_ms=250)
                else:
                    with self.assertRaisesRegex(Error, 'ERR_ABORTED'):
                        opened(page, ready_ms=250)
                page.goto.assert_called_once()
                page.remove_listener.assert_called_once_with('framenavigated',callbacks['framenavigated'])

    def test_network_errors_remain_errors_even_after_a_document_commit(self):
        from patchright.sync_api import Error
        page=page_with([["interactive",3000]])
        page.goto.side_effect=Error('Page.goto: net::ERR_CONNECTION_REFUSED at https://publisher.example/')
        with self.assertRaisesRegex(Error,'CONNECTION_REFUSED'):
            opened(page,ready_ms=250)
        page.remove_listener.assert_called_once()

    def test_a_dropped_connection_is_tried_again(self):
        from patchright.sync_api import Error
        dropped = Error('Page.goto: net::ERR_CONNECTION_CLOSED at https://doi.org/10.1000/xyz')
        page = page_with([["interactive", 3000]])
        page.goto.side_effect = [dropped, dropped, "response"]
        with patch.object(batch_common.time, "time", lambda: page.clock[0]):
            self.assertEqual(open_page(page, ARTICLE, ready_ms=250), "response")
        self.assertEqual(page.goto.call_count, 3)
        self.assertEqual([c.args[0] for c in page.wait_for_timeout.call_args_list[:2]], [2_000, 5_000])
        # Still dropped after the retries: the publisher did not answer.
        page = page_with([["interactive", 3000]])
        page.goto.side_effect = [dropped, dropped, dropped]
        with self.assertRaisesRegex(Error, 'ERR_CONNECTION_CLOSED'):
            opened(page, ready_ms=250)
        self.assertEqual(page.goto.call_count, 3)
        page.remove_listener.assert_called_once()

    def test_the_error_page_cutting_a_retry_short_is_still_the_dropped_connection(self):
        from patchright.sync_api import Error
        dropped = Error('Page.goto: net::ERR_CONNECTION_CLOSED at https://doi.org/10.1080/x')
        aborted = Error('Page.goto: net::ERR_ABORTED at https://doi.org/10.1080/x')
        page = page_with([["interactive", 3000]])
        page.goto.side_effect = [dropped, aborted, "response"]
        with patch.object(batch_common.time, "time", lambda: page.clock[0]):
            self.assertEqual(open_page(page, ARTICLE, ready_ms=250), "response")
        # All three tries cut: reported as the dropped connection, a network failure.
        page = page_with([["interactive", 3000]])
        page.goto.side_effect = [dropped, aborted, aborted]
        with self.assertRaisesRegex(Error, 'ERR_CONNECTION_CLOSED') as caught:
            opened(page, ready_ms=250)
        self.assertTrue(batch_common._is_network_failure(caught.exception))
        self.assertEqual(page.goto.call_count, 3)

    def test_errors_that_retrying_does_not_fix_end_at_once(self):
        from patchright.sync_api import Error, TimeoutError
        for error in (Error('Page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://x.example/'),
                      TimeoutError('Page.goto: Timeout 60000ms exceeded.'), RuntimeError('net::ERR_CONNECTION_CLOSED')):
            with self.subTest(error=str(error)):
                page = page_with([["interactive", 3000]])
                page.goto.side_effect = error
                with self.assertRaises(type(error)):
                    opened(page, ready_ms=250)
                page.goto.assert_called_once()

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
        page.locator.return_value.first.text_content.return_value = "Just a moment..."
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
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def test_a_busy_renderer_cannot_hold_the_title_read_until_it_recovers(self):
        context = self.browser.new_context(service_workers="block")
        self.addCleanup(context.close)
        context.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body="<title>Article title</title><p>Article text</p>"))
        page = context.new_page()
        page.goto(ARTICLE)
        # A temporary renderer stall used to hold Page.title without its own
        # timeout, consuming the page budget before the first PDF attempt.
        page.evaluate("""() => { window.busy = false; setTimeout(() => {
            window.busy = true;
            const end = performance.now() + 3500;
            while (performance.now() < end) {}
            window.busy = false;
        }, 0); }""", isolated_context=False)
        page.wait_for_timeout(100)
        started = time.monotonic()
        self.assertEqual(PublisherBatchDownloader._title(page), "")
        self.assertLess(time.monotonic() - started, 2.5)
        # Patchright's wait_for_function cannot see the page's own globals: poll its world.
        until = time.monotonic() + 5
        while page.evaluate("() => window.busy", isolated_context=False) is not False:
            self.assertLess(time.monotonic(), until)
            page.wait_for_timeout(50)
        self.assertEqual(PublisherBatchDownloader._title(page), "Article title")

    def test_svg_icon_titles_do_not_replace_the_document_title(self):
        context = self.browser.new_context(service_workers="block")
        self.addCleanup(context.close)
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=(
            "<title>Article title</title><body><svg><title>Download icon</title></svg>"
            "<svg><title>Menu icon</title></svg><p>Article text</p>")))
        page = context.new_page()
        page.goto(ARTICLE)
        self.assertEqual(PublisherBatchDownloader._title(page), "Article title")

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

    def collect_article_links(self, html, expected):
        doi = "10.1021/offline2026"
        article = "https://pubs.acs.org/jacsat/article/148/1/100/5461066/fixture"
        context = self.browser.new_context(service_workers="block")
        self.addCleanup(context.close)
        held_routes = []

        def respond(route):
            if "ads.fixture.example" in route.request.url:
                held_routes.append(route)
                return  # The article can be read, but DOMContentLoaded never fires.
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        context.route("**/*", respond)
        page = context.new_page()
        original_goto = page.goto
        original_close = page.close

        def bounded_goto(url, **kwargs):
            # Bound the old implementation's failure; commit-based navigation
            # has no reason to spend this time waiting for the stalled script.
            kwargs["timeout"] = min(kwargs.get("timeout", 60_000), 2_500)
            return original_goto(url, **kwargs)

        def close_after_pending_requests():
            for route in held_routes:
                route.abort()
            original_close()

        downloader = PublisherBatchDownloader({}, profile=replace(ACS_PROFILE, article_url_template=article))
        result = DownloadResult(doi=doi, status="success", final_url=article)
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp, patch.object(page, "goto", side_effect=bounded_goto), \
                patch.object(page, "close", side_effect=close_after_pending_requests), \
                patch.object(supplements, "collect", return_value=[]) as collect:
            downloader.collect_supplements(SimpleNamespace(new_page=lambda: page), doi, Path(tmp), result)
        collect.assert_called_once()
        self.assertEqual([link.url for link in collect.call_args.args[1]], expected)
        self.assertLess(time.monotonic() - started, 9)

    def test_supplement_discovery_ignores_a_stalled_script_after_the_article(self):
        supplement = "https://pubs.acs.org/jacsat/article-supplement/5461066/pdf/S1.pdf"
        html = ('<title>Article</title><meta name="citation_doi" content="10.1021/offline2026">'
                + '<h1>Supporting information fixture</h1><p>' + "Methods and results. " * 40 + '</p>'
                + f'<a href="{supplement}">Supporting Information</a>'
                + '<script src="https://ads.fixture.example/gpt.js"></script>')
        self.collect_article_links(html, [supplement])

    def test_supplement_discovery_waits_for_a_blank_article_to_draw_its_links(self):
        supplement = "https://pubs.acs.org/jacsat/article-supplement/5461066/pdf/S1.pdf"
        html = ('<title>Loading article</title><body><script>setTimeout(() => {'
                + 'document.body.innerHTML = \'<h1>Supporting information fixture</h1>'
                + f'<a href="{supplement}">Supporting Information</a>\';'
                + '}, 3500);</script></body>')
        self.collect_article_links(html, [supplement])


if __name__ == "__main__":
    unittest.main()
