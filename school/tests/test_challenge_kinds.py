"""Which kind of verification a page is, for the record (browser/challenge/kinds.py; the user, 2026-11-25)."""
import os
import unittest
from unittest.mock import Mock

from paper_search_school.browser.challenge import kinds
from paper_search_school.download_diagnostics import serialize_download_result
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.engine.bridge import _browser_artifacts
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE

ANCHOR = "https://www.google.com/recaptcha/api2/anchor?ar=1&k=6Lc_fixture&co=x&hl=en&v=1&size=normal"
INVISIBLE = ANCHOR.replace("size=normal", "size=invisible")
BFRAME = "https://www.google.com/recaptcha/api2/bframe?hl=en&v=1&k=6Lc_fixture"
H_BOX = "https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=checkbox&id=0&sitekey=x"
H_PUZZLE = H_BOX.replace("frame=checkbox", "frame=challenge")
TURNSTILE = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv/x/0x4/auto/fbE/new/normal"


def frame(src, shown=True):
    return {"src": src, "shown": shown}


class ClassifyTests(unittest.TestCase):
    def kind(self, **seen):
        seen.setdefault("url", "https://publisher.example/doi/10.1/x")
        seen.setdefault("title", "Human Verification")
        return kinds.classify(seen)

    def test_the_users_nine_kinds(self):
        cases = {
            "recaptcha_v2": dict(frames=[frame(ANCHOR), frame(BFRAME, shown=False)]),
            "recaptcha_v3": dict(scripts=["https://www.google.com/recaptcha/api.js?render=6Lc_fixture"]),
            "hcaptcha": dict(frames=[frame(H_BOX), frame(H_PUZZLE, shown=False)]),
            "cloudflare": dict(url="https://publisher.example/doi/10.1/x?__cf_chl_rt_tk=abc", title="Just a moment..."),
            "image_code": dict(image_code=True),
            "recaptcha_v2_image": dict(frames=[frame(ANCHOR), frame(BFRAME)]),
            "hcaptcha_image": dict(frames=[frame(H_BOX), frame(H_PUZZLE)]),
            "funcaptcha_image": dict(frames=[frame("https://client-api.arkoselabs.com/fc/gc/?token=x")]),
            "awswaf_image": dict(scripts=["https://abc.us-east-1.captcha.awswaf.com/abc/jsapi.js"]),
        }
        for want, seen in cases.items():
            with self.subTest(want=want):
                self.assertEqual(self.kind(**seen), want)
                self.assertIn(want, kinds.LABELS)

    def test_a_puzzle_that_is_up_counts_before_its_box_and_the_box_before_cloudflares_page(self):
        self.assertEqual(self.kind(title="Just a moment...", frames=[frame(ANCHOR), frame(BFRAME)]), "recaptcha_v2_image")
        self.assertEqual(self.kind(title="Just a moment...", frames=[frame(H_BOX)]), "hcaptcha")
        # reCAPTCHA v3's badge beside a visible box: the box stops the reader.
        self.assertEqual(self.kind(recaptcha_badge=True, frames=[frame(ANCHOR)]), "recaptcha_v2")
        # A hidden puzzle frame is only waiting: not the puzzle.
        self.assertEqual(self.kind(frames=[frame(BFRAME, shown=False)]), "other")

    def test_cloudflare_by_its_page_and_turnstile_on_another(self):
        self.assertEqual(self.kind(title="请稍候…"), "cloudflare")
        self.assertEqual(self.kind(cloudflare=True), "cloudflare")
        self.assertEqual(self.kind(scripts=["https://publisher.example/cdn-cgi/challenge-platform/h/b/orchestrate/x"]),
                         "cloudflare")
        self.assertEqual(self.kind(frames=[frame(TURNSTILE)]), "turnstile")
        self.assertEqual(self.kind(title="Just a moment...", frames=[frame(TURNSTILE)]), "cloudflare")

    def test_v3_only_when_nothing_else_is_there(self):
        self.assertEqual(self.kind(frames=[frame(INVISIBLE)]), "recaptcha_v3")
        self.assertEqual(self.kind(recaptcha_badge=True), "recaptcha_v3")
        # reCAPTCHA's script loaded for a box drawn by the page: no v3.
        self.assertEqual(self.kind(scripts=["https://www.google.com/recaptcha/api.js?render=explicit"]), "other")
        self.assertEqual(self.kind(frames=[frame(INVISIBLE)], image_code=True), "image_code")

    def test_other_providers_and_addresses_that_only_look_alike(self):
        self.assertEqual(self.kind(geetest=True), "geetest")
        self.assertEqual(self.kind(page_frames=["https://geo.captcha-delivery.com/captcha/?initialCid=x"]), "datadome")
        self.assertEqual(self.kind(page_frames=["https://turing.captcha.qcloud.com/cap_union_new_show"]), "tencent")
        self.assertEqual(self.kind(frames=[frame("https://evil.example/recaptcha/api2/bframe")]), "other")
        self.assertEqual(self.kind(frames=[frame("https://hcaptcha.com.evil.example/captcha/x#frame=challenge")]), "other")
        self.assertEqual(self.kind(scripts=["https://captcha.awswaf.com.evil.example/x.js"]), "other")
        self.assertEqual(self.kind(), "other")

    def test_a_page_not_read_beyond_its_title_and_address(self):
        page = Mock(url="https://publisher.example/x?__cf_chl_tk=1")
        page.title.return_value = "Just a moment..."
        self.assertEqual(kinds.identify(page, title_and_url_only=True), "cloudflare")
        page.evaluate.assert_not_called()


class RecordTests(unittest.TestCase):
    def downloader(self):
        d = PublisherBatchDownloader(config={}, profile=ELSEVIER_PROFILE)
        d._event = lambda result, state, detail="": result.events.append({"state": state, "detail": detail})
        return d

    def test_an_event_when_first_seen_or_changed_and_the_kind_on_the_result(self):
        d, result = self.downloader(), DownloadResult(doi="10.1/x", status="failed")
        page = Mock(url="https://publisher.example/doi/10.1/x", frames=[])
        page.title.return_value = "Human Verification"
        page.evaluate.return_value = {"frames": [frame(ANCHOR)], "scripts": []}
        d._note_challenge_type(page, result)
        d._note_challenge_type(page, result)
        page.evaluate.return_value = {"frames": [frame(ANCHOR), frame(BFRAME)], "scripts": []}
        d._note_challenge_type(page, result)
        # A later look that tells less keeps what was told.
        page.evaluate.return_value = {"frames": [], "scripts": []}
        d._note_challenge_type(page, result)
        self.assertEqual([e["detail"] for e in result.events if e["state"] == "challenge_type"],
                         ["recaptcha_v2: reCAPTCHA v2", "recaptcha_v2_image: reCAPTCHA v2 图像识别"])
        self.assertEqual(result.challenge_type, "recaptcha_v2_image")

    def test_the_record_and_the_backends_answer_carry_a_known_kind_only(self):
        result = DownloadResult(doi="10.1/x", status="failed", state="challenge_or_viewer_timeout",
                                reason="challenge_or_viewer_timeout", challenge_type="hcaptcha_image")
        self.assertEqual(serialize_download_result(result)["challenge_type"], "hcaptcha_image")
        self.assertEqual(_browser_artifacts(result, ELSEVIER_PROFILE).get("challenge_type"), "hcaptcha_image")
        result.challenge_type = "made-up"
        self.assertNotIn("challenge_type", serialize_download_result(result))
        self.assertNotIn("challenge_type", _browser_artifacts(result, ELSEVIER_PROFILE))


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class PageReadTests(unittest.TestCase):
    """``read`` on synthetic verification pages, every address answered by the fixture."""

    def identify(self, body, url="https://publisher.example/verify"):
        from patchright.sync_api import sync_playwright
        from fixture_network import network_is_the_fixture

        def local(route):
            if route.request.url.split("#", 1)[0] == url:
                route.fulfill(status=200, content_type="text/html",
                              body="<html><head><title>Human Verification</title></head><body>%s</body></html>" % body)
            else:
                route.fulfill(status=200, content_type="text/html", body="<html><body></body></html>")

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                network_is_the_fixture(self)
                context = browser.new_context()
                context.route("**/*", local)
                page = context.new_page()
                page.goto(url)
                return kinds.identify(page)
            finally:
                browser.close()

    def test_frames_scripts_and_elements_as_the_providers_draw_them(self):
        hidden = '<div style="visibility:hidden;position:absolute;top:-10000px"><iframe src="%s" width=400 height=580></iframe></div>'
        shown = '<iframe src="%s" width=304 height=78></iframe>'
        cases = {
            "recaptcha_v2": shown % ANCHOR + hidden % BFRAME,
            "recaptcha_v2_image": shown % ANCHOR + '<div><iframe src="%s" width=400 height=580></iframe></div>' % BFRAME,
            "hcaptcha": shown % H_BOX + hidden % H_PUZZLE,
            "hcaptcha_image": shown % H_BOX + '<iframe src="%s" width=400 height=600></iframe>' % H_PUZZLE,
            "funcaptcha_image": shown % "https://client-api.arkoselabs.com/fc/gc/?token=x",
            "awswaf_image": '<div id="amzn-captcha-container"></div><button id="amzn-captcha-verify-button">Begin</button>',
            "image_code": '<form><img src="/captcha/image?id=7" width=120 height=40 alt="captcha">'
                          '<input type="text" name="answer"><button>Submit</button></form>',
            "recaptcha_v3": '<script src="https://www.google.com/recaptcha/api.js?render=6Lc_fixture"></script>',
            "cloudflare": '<div id="challenge-stage"></div>',
        }
        for want, body in cases.items():
            with self.subTest(want=want):
                self.assertEqual(self.identify(body), want)


if __name__ == "__main__":
    unittest.main()
