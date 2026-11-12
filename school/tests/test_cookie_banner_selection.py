"""Cookie banners get the privacy-preserving answer, and a click a banner takes is
answered and tried again (BMJ's OneTrust banner over "Log in via institution",
2026-11-02). Only a consent prompt is a banner, answered at most twice per page,
never on the school's or a federation's pages (ACS's off-canvas menu "X" was
clicked 60 times in 90 s, 2026-11-02). Mocked pages for the engine's decisions;
the banner rule itself runs in a local Chrome page (opt-in fixture, all requests
answered locally)."""
import os
import time
import unittest
from unittest.mock import Mock

from patchright.sync_api import Error as PlaywrightError
from patchright.sync_api import TimeoutError as PlaywrightTimeout

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.model import PublisherProfile
from paper_search_school.publishers.profiles import get_publisher_profile

DOI = "10.1136/bmj-2026-101299"
ARTICLE = "https://www.fixture-press.example/content/395/bmj-2026-101299"
CHOOSER = "https://www.fixture-press.example/login/shibboleth?return=%2Fcontent%2F395"
PROFILE = PublisherProfile(name="Fixture Press", article_url_template="https://doi.org/{doi}", pdf_url_templates=(),
                           success_url_markers=("fixture-press.example/content/",), auth_url_markers=("/login",),
                           auth_title_markers=(), sso_text_markers=(), base_domains=("fixture-press.example",))
INTERCEPTED = ("Locator.click: Timeout 5000ms exceeded.\nCall log:\n  - attempting click action\n"
               '    - <div class="ot-sdk-row">…</div> from <div id="onetrust-banner-sdk">…</div> subtree intercepts pointer events\n')


def result():
    return DownloadResult(doi=DOI, status="failed", article_url=ARTICLE)


class CookieBannerAnswerTests(unittest.TestCase):
    def test_a_publisher_chooser_cookie_prompt_is_answered(self):
        d = PublisherBatchDownloader(config={}, profile=get_publisher_profile("thieme"))
        page = Mock(frames=[], url="https://profile.thieme.de/HTML/sso/ejournals/shibboleth.htm")
        page.evaluate.return_value = {"kind": "reject", "label": "Reject", "banner": "#cookie-consent"}
        r = result()
        self.assertTrue(d._dismiss_cookie_banners(page, r))
        page.evaluate.assert_called_once_with(d._COOKIE_BANNER_JS, {"blocking": False, "skip": []})
        self.assertEqual(r.events[-1]["state"], "cookie_banner_dismissed")

    def test_the_answer_is_recorded_with_its_kind_and_banner(self):
        page = Mock(frames=[])
        page.evaluate.return_value = {"kind": "reject", "label": "Reject All", "banner": "#onetrust-banner-sdk"}
        d, r = PublisherBatchDownloader(config={}), result()
        self.assertTrue(d._dismiss_cookie_banners(page, r))
        page.evaluate.assert_called_once_with(d._COOKIE_BANNER_JS, {"blocking": False, "skip": []})
        self.assertEqual(r.events[-1]["state"], "cookie_banner_dismissed")
        self.assertEqual(r.events[-1]["detail"], 'reject "Reject All" in #onetrust-banner-sdk')

    def test_a_banner_in_a_frame_is_answered_there(self):
        main, frame, blank = Mock(url="https://www.fixture-press.example/"), Mock(url="https://cmp.example/m"), Mock(url="about:blank")
        page = Mock(frames=[main, frame, blank])
        page.evaluate.return_value = None
        frame.evaluate.return_value = {"kind": "reject", "label": "Reject", "banner": "#sp_message"}
        d, r = PublisherBatchDownloader(config={}), result()
        self.assertTrue(d._dismiss_cookie_banners(page, r, blocking=True))
        frame.evaluate.assert_called_once_with(d._COOKIE_BANNER_JS, {"blocking": True, "skip": []})
        blank.evaluate.assert_not_called()

    def test_no_banner_and_a_broken_frame_change_nothing(self):
        frame = Mock(url="https://cmp.example/m")
        frame.evaluate.side_effect = PlaywrightError("frame was detached")
        page = Mock(frames=[Mock(url="https://x.example/"), frame])
        page.evaluate.return_value = None
        d, r = PublisherBatchDownloader(config={}), result()
        self.assertFalse(d._dismiss_cookie_banners(page, r))
        self.assertEqual(r.events, [])

    def test_cookie_reads_do_not_hide_program_or_watchdog_errors(self):
        from paper_search_school.browser.watchdog import BrowserOperationTimeout
        for error in (KeyError("program error"), BrowserOperationTimeout("operation expired")):
            with self.subTest(error=type(error).__name__):
                d = PublisherBatchDownloader(config={}, profile=PROFILE)
                d._close_advertisement_overlay = Mock(return_value=False)
                page = Mock(frames=[], url=ARTICLE)
                page.evaluate.side_effect = error
                with self.assertRaises(type(error)):
                    d._dismiss_cookie_banners(page, result())


    def test_a_banner_still_shown_is_answered_twice_then_left_once(self):
        def evaluate(script, options=None):
            if script == PublisherBatchDownloader._AD_OVERLAY_JS:
                return ""  # no advertisement over the page
            if "#ot" in options["skip"]:
                return {"left": "#ot"}
            return {"kind": "reject", "label": "Reject All", "banner": "#ot"}
        page = Mock(frames=[], url=ARTICLE)
        page.evaluate.side_effect = evaluate
        d, r = PublisherBatchDownloader(config={}, profile=PROFILE), result()
        self.assertEqual([d._dismiss_cookie_banners(page, r) for _ in range(5)], [True, True, False, False, False])
        self.assertEqual([e["state"] for e in r.events],
                         ["cookie_banner_dismissed", "cookie_banner_dismissed", "cookie_banner_left"])
        self.assertIn("#ot still shown after 2 answers", r.events[-1]["detail"])
        page.url = ARTICLE + "?page=2"  # another page: answered again
        self.assertTrue(d._dismiss_cookie_banners(page, r))

    def test_the_school_s_and_the_federation_s_pages_are_left_alone(self):
        d = PublisherBatchDownloader(config={"idp_entity_id": "https://idp.school.edu.cn/idp/shibboleth"}, profile=PROFILE)
        for url in ("https://cas.school.edu.cn/esc-sso/login/page", "https://lib.school.edu.cn/portal",
                    "https://ds.carsi.edu.cn/discovery?entityID=x", "https://wayfinder.openathens.net/?return=x"):
            with self.subTest(url=url):
                page = Mock(frames=[], url=url)
                self.assertFalse(d._dismiss_cookie_banners(page, result()))
                page.evaluate.assert_not_called()
        page = Mock(frames=[], url=ARTICLE)
        page.evaluate.return_value = None
        self.assertFalse(d._dismiss_cookie_banners(page, result()))
        self.assertEqual(page.evaluate.call_count, 2)  # the publisher's own page: an advertisement, then a banner


class InterceptedClickTests(unittest.TestCase):
    def setUp(self):
        self.d, self.r, self.page, self.control = PublisherBatchDownloader(config={}), result(), Mock(), Mock()

    def test_a_click_taken_by_a_banner_answers_it_and_clicks_again(self):
        self.control.click.side_effect = [PlaywrightTimeout(INTERCEPTED), None]
        self.d._dismiss_cookie_banners = Mock(return_value=True)
        self.d._click_control(self.page, self.control, self.r, "institution entry")
        self.d._dismiss_cookie_banners.assert_called_once_with(self.page, self.r, blocking=True)
        self.assertEqual(self.control.click.call_count, 2)
        self.control.evaluate.assert_not_called()
        self.assertEqual(self.r.events[0]["state"], "click_intercepted")
        self.assertIn('id="onetrust-banner-sdk"', self.r.events[0]["detail"])

    def test_still_covered_it_falls_back_to_the_script_click(self):
        self.control.click.side_effect = [PlaywrightTimeout(INTERCEPTED), PlaywrightTimeout(INTERCEPTED)]
        self.d._dismiss_cookie_banners = Mock(return_value=True)
        self.d._click_control(self.page, self.control, self.r, "pdf link")
        self.control.evaluate.assert_called_once_with("el => el.click()", timeout=5_000)
        self.assertEqual([e["state"] for e in self.r.events], ["click_intercepted", "script_click"])

    def test_nothing_to_answer_goes_straight_to_the_script_click(self):
        self.control.click.side_effect = [PlaywrightTimeout(INTERCEPTED)]
        self.d._dismiss_cookie_banners = Mock(return_value=False)
        self.d._click_control(self.page, self.control, self.r, "pdf link")
        self.assertEqual(self.control.click.call_count, 1)
        self.control.evaluate.assert_called_once_with("el => el.click()", timeout=5_000)

    def test_a_click_that_times_out_is_the_script_s_click(self):
        # ASCO's "/action/ssostart" button, visible and enabled, not clicked in 5 s (2026-11-02).
        self.control.click.side_effect = PlaywrightTimeout("Locator.click: Timeout 5000ms exceeded.\n - element is outside of the viewport")
        self.d._click_control(self.page, self.control, self.r, "institution entry")
        self.control.evaluate.assert_called_once_with("el => el.click()", timeout=5_000)
        self.assertEqual([(e["state"], e["detail"]) for e in self.r.events],
                         [("script_click", "institution entry (the click timed out)")])

    def test_a_control_gone_by_the_script_click_is_the_page_moving_on(self):
        # Thieme's Shibboleth Continue (2026-11-02): the click timed out while the page
        # left, and the script's click found the control gone; the item went on.
        self.control.click.side_effect = PlaywrightTimeout("Locator.click: Timeout 5000ms exceeded.")
        self.control.evaluate.side_effect = PlaywrightTimeout("Locator.evaluate: Timeout 5000ms exceeded.")
        self.control.count.return_value = 0
        self.assertTrue(self.d._click_control(self.page, self.control, self.r, "institution list submit"))
        self.assertEqual([(e["state"], e["detail"]) for e in self.r.events],
                         [("click_target_gone", "institution list submit (the click timed out)")])

    def test_a_script_click_that_fails_on_a_control_still_there_clicked_nothing(self):
        # Any browser error was taken for a control gone, and the caller went on as if
        # it had clicked (review 2026-11-02). Gone only when no match is left or the
        # page left its address.
        self.page.url = "https://www.fixture-press.example/login/shibboleth"
        self.control.click.side_effect = PlaywrightTimeout("Locator.click: Timeout 5000ms exceeded.")
        self.control.evaluate.side_effect = PlaywrightError("Locator.evaluate: Element is not attached to the DOM")
        self.control.count.return_value = 1
        self.assertFalse(self.d._click_control(self.page, self.control, self.r, "institution entry"))
        self.assertEqual(self.r.events[-1]["state"], "script_click_failed")
        self.assertIn("Element is not attached", self.r.events[-1]["detail"])
        self.control.count.side_effect = PlaywrightError("Execution context was destroyed")
        self.assertFalse(self.d._click_control(self.page, self.control, self.r, "institution entry"))
        def leaves(**kwargs):
            self.page.url = ARTICLE  # the page moved on while the click waited
            raise PlaywrightTimeout("Locator.click: Timeout 5000ms exceeded.")
        self.control.click.side_effect = leaves
        self.assertTrue(self.d._click_control(self.page, self.control, self.r, "institution entry"))
        self.assertEqual(self.r.events[-1]["state"], "click_target_gone")

    def test_other_failures_are_the_caller_s(self):
        self.control.click.side_effect = PlaywrightError("Element is not attached to the DOM")
        with self.assertRaises(PlaywrightError):
            self.d._click_control(self.page, self.control, self.r, "pdf control")
        self.control.evaluate.assert_not_called()


class PersonalLoginBoxTests(unittest.TestCase):
    """A password field on the publisher's article page is a personal account's box,
    not the school's login (BMJ waited 5 minutes on its article page, 2026-11-02)."""

    def page(self, url, typed=False):
        page = Mock(url=url)
        page.locator.return_value.count.return_value = 1  # a visible password field
        page.evaluate.return_value = typed  # _has_visible_editable_input
        return page

    def test_the_article_page_with_a_login_box_is_not_the_user_s_login(self):
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=PROFILE)
        self.assertFalse(d._is_human_login_page(self.page(ARTICLE)))

    def test_a_page_navigating_during_the_typing_check_stays_the_user_s(self):
        # Read on every pass of the login wait; "Execution context was destroyed" there
        # ended the item as an unexpected error (review 2026-11-02).
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=PROFILE)
        d._item_result = result()
        page = self.page(ARTICLE)
        page.evaluate.side_effect = PlaywrightError(
            "Page.evaluate: Execution context was destroyed, most likely because of a navigation")
        self.assertTrue(d._is_human_login_page(page))
        self.assertEqual(d._item_result.events[-1]["state"], "page_read_interrupted")
        for error in (PlaywrightError("Target page, context or browser has been closed"), KeyError("program error")):
            page.evaluate.side_effect = error  # not a navigation: the caller's, as before
            with self.assertRaises(type(error)):
                d._has_visible_editable_input(page)

    def test_someone_typing_there_or_a_login_page_stays_the_user_s(self):
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=PROFILE)
        self.assertTrue(d._is_human_login_page(self.page(ARTICLE, typed=True)))
        self.assertTrue(d._is_human_login_page(self.page("https://www.fixture-press.example/login?x=1")))
        self.assertTrue(d._is_human_login_page(self.page("https://idp.school.example.edu.cn/idp/profile/SAML2")))


BANNER = """<div id="onetrust-banner-sdk" style="position:fixed;left:0;right:0;bottom:0;height:45vh;background:#222;color:#fff;z-index:9">
  <p>We and our partners use cookies.</p>{buttons}</div>"""
ONETRUST = ('<button id="onetrust-accept-btn-handler" onclick="window.answer=\'accept\';this.parentNode.remove()">I Accept</button>'
            '<button id="onetrust-reject-all-handler" onclick="window.answer=\'reject\';this.parentNode.remove()">Reject All</button>')


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class CookieBannerPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block", viewport={"width": 1200, "height": 800})
        self.addCleanup(self.context.close)
        self.pages = {}
        self.requests = []

        def respond(route):
            self.requests.append(route.request.url)
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=self.pages.get(route.request.url, "<title>Elsewhere</title><h1>Elsewhere</h1>"))
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=PROFILE,
                                          institution_query="Synthetic University A")
        self.r = result()

    def open(self, html):
        self.pages[ARTICLE] = "<title>Article</title><h1>Article</h1>" + html
        self.page.goto(ARTICLE)

    def answer(self):
        # The fixture's own handlers set it in the page's world; Patchright evaluates in an isolated one.
        return self.page.evaluate("() => window.answer || null", isolated_context=False)

    # NEJM's lightbox over the article (2026-11-03), its structure as recorded there.
    AD = ('<div class="fancybox-overlay fancybox-overlay-fixed" style="position:fixed;left:0;top:0;width:100%;'
          'height:100%;z-index:10000909;background:rgba(0,0,0,.6)">{body}'
          '<a class="fancybox-item fancybox-close" href="javascript:;" style="position:absolute;top:8px;right:8px;'
          'display:block;width:36px;height:36px" onclick="window.answer=\'closed\';'
          'this.parentNode.remove()"></a></div>')
    AD_BODY = ('<div style="margin:15vh auto;width:60vw;background:#fff"><h2>FREE ANNUAL COLLECTION</h2>'
               '<p>Valvular Heart Disease: Evidence Based Practice Update</p>'
               '<a href="https://store.fixture.example/signup">Download Now</a></div>')

    def test_an_advertisement_over_the_page_is_closed(self):
        self.open(self.AD.format(body=self.AD_BODY))
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertEqual(self.answer(), "closed")
        self.assertEqual(self.r.events[-1]["state"], "advertisement_closed")
        self.assertIn("FREE ANNUAL COLLECTION", self.r.events[-1]["detail"])
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))  # gone

    def test_sign_in_layers_forms_and_small_layers_are_left_alone(self):
        layers = {
            "sign-in words": self.AD.format(body='<div style="margin:15vh auto;width:60vw;background:#fff">'
                                                 '<a href="/action/ssostart">Sign in via your institution</a></div>'),
            "a form": self.AD.format(body='<div style="margin:15vh auto;width:60vw;background:#fff">'
                                          '<p>Get the newsletter</p><input type="email"></div>'),
            "a small layer": ('<div style="position:fixed;right:10px;bottom:10px;width:300px;height:60px">'
                              'Have questions about this article? <button onclick="window.answer=\'closed\'">×</button>'
                              '</div>'),
        }
        for name, html in layers.items():
            with self.subTest(name):
                self.r = result()
                self.open(html)
                self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))
                self.assertIsNone(self.answer())

    def test_onetrust_is_rejected_not_accepted(self):
        self.open(BANNER.format(buttons=ONETRUST))
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertEqual(self.answer(), "reject")
        self.assertEqual(self.r.events[-1]["detail"], 'reject "Reject All" in #onetrust-banner-sdk')
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))  # declined once: gone

    def test_necessary_only_and_chinese_reject_are_preferred_to_accept(self):
        for label in ("Use necessary cookies only", "Only necessary", "Decline", "拒绝"):
            with self.subTest(label=label):
                self.r = result()  # each its own article: a banner is answered twice per article page
                self.open('<div class="cookie-notice" style="position:fixed;bottom:0;width:100%;height:40vh">'
                          '<button onclick="window.answer=\'accept\'">Accept all cookies</button>'
                          f'<button onclick="window.answer=\'reject\'">{label}</button></div>')
                self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
                self.assertEqual(self.answer(), "reject")

    def test_accept_only_when_the_banner_covers_the_page(self):
        small = ('<div class="cookie-bar"><span>We use cookies.</span>'
                 '<button onclick="window.answer=\'accept\'">Accept all cookies</button></div>')
        self.open(small)
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertIsNone(self.answer())
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r, blocking=True))  # it took a click
        self.assertEqual(self.answer(), "accept")
        self.open(BANNER.format(buttons='<button onclick="window.answer=\'accept\'">Accept all cookies</button>'))
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertEqual(self.answer(), "accept")

    def test_controls_outside_a_banner_and_an_idp_form_are_never_touched(self):
        self.open('<p>The imperative to save the Paris Climate Agreement</p>'
                  '<button onclick="window.answer=\'other\'">Reject</button><button onclick="window.answer=\'other\'">Accept</button>')
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))
        self.open('<form id="consent-form"><input type="hidden" name="_shib_idp_consentIds" value="mail">'
                  '<div class="consent"><button name="_eventId_AttributeReleaseRejected" onclick="window.answer=\'idp\'">Reject</button>'
                  '<button name="_eventId_proceed" onclick="window.answer=\'idp\'">Accept</button></div></form>')
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertIsNone(self.answer())

    def test_a_banner_in_an_open_shadow_root(self):
        self.open('<div id="host"></div><script>const root = document.getElementById("host").attachShadow({mode: "open"});'
                  'root.innerHTML = `<div id="cmp-consent" style="position:fixed;bottom:0;width:100%;height:30vh">'
                  '<p>We use cookies to measure the audience.</p>'
                  '<button onclick="window.answer=\'accept\'">Accept</button>'
                  '<button onclick="window.answer=\'reject\'">Reject all</button></div>`;</script>')
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertEqual(self.answer(), "reject")

    def test_a_menu_or_panel_close_is_never_a_banner_answer(self):
        """ACS: <body class="... gdpr-visible"> and an off-canvas menu with "X";
        the menu's links name privacy and cookies but offer no consent choice."""
        menu = ('<script>document.body.className = "off-canvas pg_Article pg_article gdpr-visible"</script>'
                '<div class="off-canvas-panel" style="position:fixed;left:0;top:0;width:320px;height:100vh;background:#fff">'
                '<button class="close" onclick="window.answer=\'closed\'">X</button>'
                '<nav><a href="#">Journals</a> <a href="#">Privacy Policy</a> <a href="#">Manage Cookies</a></nav></div>'
                '<div role="dialog" style="position:fixed;right:0;top:0;width:300px;height:200px">'
                '<p>Recommended articles</p><button onclick="window.answer=\'closed\'">Close</button></div>')
        self.open(menu)
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertFalse(self.d._dismiss_cookie_banners(self.page, self.r, blocking=True))
        self.assertIsNone(self.answer())
        self.assertEqual(self.r.events, [])
        # A short page whose wrapper also holds a real prompt: the prompt is answered, the menu left alone.
        self.open('<div id="app">' + menu + '<div class="consent" style="position:fixed;bottom:0;width:100%;height:30vh">'
                  '<p>We use cookies.</p><button onclick="window.answer=\'accept\'">Accept</button></div></div>')
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertEqual(self.answer(), "accept")

    def test_a_banner_that_stays_is_answered_twice_then_left_alone(self):
        stays = ('<button id="onetrust-accept-btn-handler" onclick="window.answer=\'accept\'">I Accept</button>'
                 '<button id="onetrust-reject-all-handler" onclick="window.count=(window.count||0)+1">Reject All</button>')
        self.open(BANNER.format(buttons=stays))
        self.assertEqual([self.d._dismiss_cookie_banners(self.page, self.r) for _ in range(4)], [True, True, False, False])
        self.assertEqual(self.page.evaluate("() => window.count", isolated_context=False), 2)
        self.assertIsNone(self.answer())
        self.assertEqual([e["state"] for e in self.r.events],
                         ["cookie_banner_dismissed", "cookie_banner_dismissed", "cookie_banner_left"])

    def test_a_long_page_with_many_links_is_judged_quickly(self):
        links = "".join(f'<p>Paragraph {i} of the article, with <a href="#r{i}">reference {i}</a>.</p>' for i in range(1500))
        self.open(f'<main><section>{links}</section></main>' + BANNER.format(buttons=ONETRUST))
        started = time.time()
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertLess(time.time() - started, 3)
        self.assertEqual(self.answer(), "reject")

    def test_a_chinese_privacy_prompt_is_declined(self):
        self.open('<div style="position:fixed;bottom:0;width:100%;height:25vh">我们重视您的隐私，使用必要的技术保存偏好。'
                  '<button onclick="window.answer=\'accept\'">同意</button>'
                  '<button onclick="window.answer=\'reject\'">拒绝</button></div>')
        self.assertTrue(self.d._dismiss_cookie_banners(self.page, self.r))
        self.assertEqual(self.answer(), "reject")

    def test_the_covered_institution_link_in_a_login_box_is_opened(self):
        """BMJ: the login box holds a password form and "Log in via institution";
        the banner covers the link. The entry is answered and clicked."""
        self.pages[CHOOSER] = "<title>Choose</title><h1>Find your institution</h1>"
        self.open('<div style="height:420px"></div><form><input name="u"><input type="password" name="p">'
                  '<button>Login</button><a href="' + CHOOSER + '">Log in via institution</a></form>'
                  + BANNER.format(buttons=ONETRUST))
        self.assertFalse(self.d._is_human_login_page(self.page))  # a personal box, nobody typing
        self.assertTrue(self.d._click_sso_entry(self.page, self.r))
        self.page.wait_for_url(CHOOSER, timeout=5_000)
        states = [e["state"] for e in self.r.events]
        self.assertIn("click_intercepted", states)
        self.assertIn("cookie_banner_dismissed", states)
        self.assertIn('reject "Reject All"', next(e["detail"] for e in self.r.events if e["state"] == "cookie_banner_dismissed"))


if __name__ == "__main__":
    unittest.main()
