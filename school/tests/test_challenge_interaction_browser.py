"""Real native checkbox interaction; every browser request is fulfilled locally.

SCHOOL_LOCAL_BROWSER_TEST=1 enables them (Chrome, headless). These fixtures do not
contact Cloudflare and cannot establish live verification success rates.
"""
import json
import os
import time
import unittest
from unittest.mock import Mock, patch

from paper_search_school.browser.challenge_interaction import click_checkbox, observe_checkbox, prepare_context
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import SPRINGER_PROFILE
from test_pdf_after_check import article_pdf

ORIGIN = "https://link.springer.com"
DOI = "10.1007/s00000-026-00001-1"
ARTICLE = ORIGIN + "/article/" + DOI
PDF = ORIGIN + "/content/pdf/" + DOI + ".pdf"
FRAME = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/fixture"


def checkbox_html(*, closed=False, checked=False, ready_ms=3000, pass_on_click=1, retry_ms=None, readable=True):
    # Native DOM and closed shadow DOM have the same checkbox geometry. Patchright
    # reads a checkbox inside a closed shadow root; ``readable=False`` draws the
    # box without one, so only its position and the readiness signal remain.
    style = 'position:absolute;left:20px;top:24px;width:16px;height:16px;margin:0'
    control = (f'<input type="checkbox" style="{style}" ' + ('checked' if checked else '') + '>' if readable
               else f'<span style="{style};display:block;border:1px solid #888"></span>')
    return ("<style>body{margin:0}</style><div id='widget'></div><script>"
            + ("const root = document.querySelector('#widget').attachShadow({mode:'closed'});" if closed
               else "const root = document.querySelector('#widget');")
            + f"root.innerHTML = {control!r};"
            + "const input=root.firstElementChild, clicks=[];"
            + "const ready=()=>parent.postMessage({source:'cloudflare-challenge',event:'interactiveBegin'},'*');"
            + "input.addEventListener('click', () => {"
            + "clicks.push(performance.now());document.documentElement.dataset.clicks=JSON.stringify(clicks);"
            + f"if(clicks.length==={pass_on_click})parent.postMessage('passed','*');"
            + (f"else setTimeout(()=>{{input.checked=false;ready();}},{retry_ms});" if retry_ms is not None else "")
            + "});"
            + f"setTimeout(ready,{ready_ms});"
            + "</script>")


def check_page(*, pdf=False, overlay=False, outer_closed=False):
    on_pass = ("document.cookie='fixture_pass=1;path=/';location.reload();" if pdf
               else "document.title='Article';document.body.innerHTML='<p>Article ready</p>';")
    frame = (f"<iframe src='{FRAME}' title='Widget containing a Cloudflare security challenge' "
             "style='width:300px;height:65px;border:0'></iframe>")
    widget = ("<div id='outer'></div><script>document.querySelector('#outer')"
              ".attachShadow({mode:'closed'}).innerHTML=" + repr(frame) + ";</script>"
              if outer_closed else frame)
    return ("<title>Just a moment...</title><p>Verify you are human</p>" + widget
            + ("<div style='position:fixed;inset:0;z-index:9999;background:white'>Overlay</div>" if overlay else "")
            + "<script>window.addEventListener('message', e => {"
            "if(e.origin==='https://challenges.cloudflare.com' && e.data?.source==='cloudflare-challenge' && e.data.event==='interactiveBegin')document.documentElement.dataset.fixtureReady='true';"
            "if(e.origin==='https://challenges.cloudflare.com' && e.data==='passed'){" + on_pass + "}})</script>")


class InteractionFixture:
    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        prepare_context(self.context)
        self.page = self.context.new_page()
        self.frame_body = checkbox_html()
        self.body = check_page()
        self.pdf_body = article_pdf(DOI)
        self.pdf_answers = []

        def respond(route):
            url = route.request.url
            if url == FRAME:
                route.fulfill(content_type="text/html", body=self.frame_body)
            elif url == PDF:
                passed = "fixture_pass=1" in route.request.all_headers().get("cookie", "")
                self.pdf_answers.append(200 if passed else 403)
                route.fulfill(status=200 if passed else 403,
                              content_type="application/pdf" if passed else "text/html",
                              body=self.pdf_body if passed else check_page(pdf=True))
            else:
                route.fulfill(content_type="text/html", body=self.body)
        self.context.route("**/*", respond)

    def open_widget(self):
        self.page.goto(ARTICLE)
        # Wait for the frame document, not a network or third-party widget.
        frame = next(frame for frame in self.page.frames if frame.url == FRAME)
        frame.wait_for_selector("#widget", state="attached")
        observe_checkbox(self.page)

    def test_checkbox_passes_in_same_context_without_manual_attention(self):
        for closed, outer_closed in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(closed_shadow=closed, outer_closed=outer_closed):
                self.frame_body = checkbox_html(closed=closed)
                self.body = check_page(outer_closed=outer_closed)
                self.open_widget()
                d = PublisherBatchDownloader({}, profile=SPRINGER_PROFILE, require_interactive_browser=True)
                result = DownloadResult(doi=DOI, status="failed", state="article_loaded")
                with patch("paper_search_school.progress_reporter.set_attention") as attention:
                    self.assertTrue(d._wait_for_challenge(self.page, result))
                attention.assert_not_called()
                self.assertEqual(self.page.title(), "Article")
                self.assertEqual(result.state, "article_loaded")
                self.assertTrue(any("checkbox clicked" in e["detail"] for e in result.events))

    def test_overlay_prevents_the_native_click(self):
        self.frame_body = checkbox_html(closed=True)
        self.body = check_page(overlay=True)
        self.open_widget()
        self.page.wait_for_function("document.documentElement.dataset.fixtureReady === 'true'")
        self.assertEqual(click_checkbox(self.page, timeout_ms=500, checkpoint=lambda: None), "unavailable")
        self.assertEqual(self.page.title(), "Just a moment...")

    def test_closed_widget_can_retry_after_overlay_clears_without_new_readiness(self):
        self.frame_body = checkbox_html(closed=True)
        self.body = check_page(overlay=True)
        self.open_widget()
        self.page.wait_for_function("document.documentElement.dataset.fixtureReady === 'true'")
        click = lambda: click_checkbox(self.page, timeout_ms=750, checkpoint=lambda: None)
        self.assertEqual(click(), "unavailable")
        self.page.get_by_text("Overlay", exact=True).evaluate("element => element.remove()")
        self.assertEqual(click(), "clicked")
        self.page.wait_for_function("document.title === 'Article'", timeout=2000)

    def test_late_closed_widget_is_clicked_after_idle_threshold_without_false_reminder(self):
        self.frame_body = checkbox_html(closed=True, ready_ms=35000)
        self.body = check_page(outer_closed=True)
        self.open_widget()
        d = PublisherBatchDownloader({"browser_page_wait_timeout": 40},
                                     profile=SPRINGER_PROFILE, require_interactive_browser=True)
        result = DownloadResult(doi=DOI, status="failed", state="article_loaded")
        with patch("paper_search_school.progress_reporter.set_attention") as attention:
            self.assertTrue(d._wait_for_challenge(self.page, result),
                            [(e["state"], e["detail"]) for e in result.events])
        clicks = [e for e in result.events if e["state"] == "challenge_interaction"]
        self.assertEqual(len(clicks), 1)
        self.assertIn("checkbox clicked; attempt 1/3", clicks[0]["detail"])
        self.assertEqual(self.page.title(), "Article")
        attention.assert_not_called()

    def test_checked_checkbox_is_not_toggled(self):
        self.frame_body = checkbox_html(checked=True)
        self.open_widget()
        self.assertEqual(click_checkbox(self.page, timeout_ms=750, checkpoint=lambda: None), "unavailable")
        self.assertTrue(self.page.frames[1].locator('input[type="checkbox"]').is_checked())

    def test_closed_widget_requires_readiness_from_the_cloudflare_frame(self):
        self.frame_body = checkbox_html(closed=True, ready_ms=60000, readable=False)
        self.open_widget()
        click = lambda: click_checkbox(self.page, timeout_ms=1500, checkpoint=lambda: None)
        self.assertEqual(click(), "absent")
        # The article cannot announce readiness on behalf of the iframe.
        self.page.evaluate("""() => window.postMessage({
            source:'cloudflare-challenge',event:'interactiveBegin'}, '*')""")
        self.assertEqual(click(), "absent")
        frame = next(frame for frame in self.page.frames if frame.url == FRAME)
        frame.evaluate("""() => parent.postMessage({
            source:'unrelated-widget',event:'interactiveBegin'}, '*')""")
        self.assertEqual(click(), "absent")
        frame.evaluate("""() => parent.postMessage({
            source:'cloudflare-challenge',event:'interactiveBegin'}, '*')""")
        self.page.wait_for_function("document.documentElement.dataset.fixtureReady === 'true'")
        self.assertEqual(click(), "clicked")
        # postMessage is asynchronous; a dispatched click precedes its parent's handler.
        self.page.wait_for_function("document.title === 'Article'", timeout=2000)
        self.assertEqual(self.page.title(), "Article")

    def test_closed_widget_is_not_clicked_again_without_fresh_readiness(self):
        self.frame_body = checkbox_html(closed=True, pass_on_click=0, readable=False)
        self.body = check_page(outer_closed=True)
        self.open_widget()
        self.page.wait_for_function("document.documentElement.dataset.fixtureReady === 'true'")
        click = lambda: click_checkbox(self.page, timeout_ms=1500, checkpoint=lambda: None)
        self.assertEqual(click(), "clicked")
        self.page.wait_for_timeout(100)
        self.assertEqual(click(), "absent")
        frame = next(frame for frame in self.page.frames if frame.url == FRAME)
        times = json.loads(frame.locator("html").get_attribute("data-clicks"))
        self.assertEqual(len(times), 1)
        self.assertEqual(self.page.title(), "Just a moment...")

    def test_immediate_retry_signal_is_not_erased_after_a_dispatched_click(self):
        self.frame_body = checkbox_html(closed=True, pass_on_click=2, retry_ms=0)
        self.body = check_page(outer_closed=True)
        self.open_widget()
        self.page.wait_for_function("document.documentElement.dataset.fixtureReady === 'true'")
        click = lambda: click_checkbox(self.page, timeout_ms=2500, checkpoint=lambda: None)
        self.assertEqual(click(), "clicked")
        self.page.wait_for_timeout(100)
        self.assertEqual(click(), "clicked")
        self.page.wait_for_function("document.title === 'Article'", timeout=2000)

    def test_third_click_finds_widget_after_layout_and_viewport_changes(self):
        self.frame_body = checkbox_html(closed=True, pass_on_click=3, retry_ms=400)
        self.body = check_page(outer_closed=True)
        self.open_widget()
        positions, times = [], []
        def tracked_click(page, **kwargs):
            frame = next(frame for frame in page.frames if frame.url == FRAME)
            box = frame.frame_element().bounding_box()
            outcome = click_checkbox(page, **kwargs)
            if outcome == "clicked":
                positions.append((box["x"], box["y"]))
                times.append(time.monotonic())
                if len(times) < 3:
                    page.set_viewport_size({"width": 900 + len(times) * 100, "height": 700})
                    page.evaluate("n => { document.body.style.paddingLeft=(n*120)+'px';"
                                  "document.body.style.paddingTop=(n*70)+'px'; }", len(times))
            return outcome
        d = PublisherBatchDownloader({}, profile=SPRINGER_PROFILE, require_interactive_browser=True)
        result = DownloadResult(doi=DOI, status="failed", state="article_loaded")
        with patch("paper_search_school.browser.challenge_interaction.click_checkbox", side_effect=tracked_click), \
                patch("paper_search_school.progress_reporter.set_attention") as attention:
            self.assertTrue(d._wait_for_challenge(self.page, result))
        self.assertEqual(len(times), 3)
        self.assertEqual(len(set(positions)), 3)
        self.assertTrue(all(b - a >= 3 for a, b in zip(times, times[1:])))
        self.assertEqual(self.page.title(), "Article")
        attention.assert_not_called()

    def test_pdf_capture_continues_after_checkbox_verification(self):
        self.frame_body = checkbox_html(closed=True)
        self.body = (f'<title>Offline article</title><meta name="citation_doi" content="{DOI}">'
                     f'<a href="{PDF}">Download PDF</a>')
        self.page.goto(ARTICLE)
        d = PublisherBatchDownloader({}, profile=SPRINGER_PROFILE, require_interactive_browser=True,
                                     login_timeout_sec=15, pdf_timeout_sec=15)
        d._fetch_pdf_url = Mock(return_value=(None, "", None))
        result = DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)
        with patch("paper_search_school.progress_reporter.set_attention") as attention:
            body, url, blocked = d._capture_pdf(self.page, DOI, result)
        self.assertEqual(self.pdf_answers[:2], [403, 200])
        self.assertEqual((body, url, blocked), (self.pdf_body, PDF, None))
        self.assertTrue(any("checkbox clicked" in e["detail"] for e in result.events))
        attention.assert_not_called()


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class ChromeInteractionTests(InteractionFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class BackendInteractionTests(InteractionFixture, unittest.TestCase):
    """The browser as the backend launches it (Chrome through Patchright)."""

    @classmethod
    def setUpClass(cls):
        from paper_search_school.browser.backend import launch
        cls.browser = launch(headless=True, humanize=False, config={})

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
