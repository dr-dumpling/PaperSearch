"""Continue is never clicked on an institution chooser unless this code just picked the user's own institution."""
import os
import unittest
from unittest.mock import Mock

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import PUBLISHER_PROFILES

THIEME = PUBLISHER_PROFILES["thieme"]
CHOOSER = '''<title>Thieme - Shibboleth</title><h1>Institutional Login via Shibboleth</h1>
<p>Please select your institution</p>
<select id="institution"><option>Beijing Normal University</option><option>Fudan University</option>
<option>Peking University</option><option>Hong Mu-lan University</option><option>Zhejiang University</option></select>
<button id="go" onclick="document.title='SUBMITTED'">Continue</button>'''
SEARCH = '''<title>Find your institution</title><input placeholder="Search for your institution">
<button onclick="document.title='SUBMITTED'">Continue</button>'''
LOGIN = '''<title>Sign in</title><input name="user"><input type="password" name="pw">
<input type="submit" value="Continue" onclick="document.title='SUBMITTED'">'''
CONSENT = '''<title>Terms</title><header><input type="search" placeholder="Search this site"></header>
<p>Do you accept the terms?</p><button onclick="document.title='SUBMITTED'">Yes</button>'''


def downloader(config=None, query=""):
    return PublisherBatchDownloader(config if config is not None else {"carsi_enabled": True, "carsi_idp_name": "红木兰大学"},
                                    profile=THIEME, institution_query=query)


class MockPageTests(unittest.TestCase):
    def test_chooser_url_and_detection_errors_withhold_continue(self):
        d = downloader()
        for url in ("https://profile.thieme.de/HTML/sso/ejournals/shibboleth.htm",
                    "https://www.tandfonline.com/action/ssostart", "https://ds.carsi.edu.cn/ds/index.html"):
            page = Mock(); page.url = url
            result = DownloadResult(doi="10.1055/x", status="failed")
            d._click_optional_continue(page, result)
            page.locator.assert_not_called()
            self.assertIn("institution_continue_withheld", [e["state"] for e in result.events])
        page = Mock(); page.url = "https://example.org/page"; page.evaluate.side_effect = RuntimeError("context destroyed")
        d._click_optional_continue(page, DownloadResult(doi="10.1055/x", status="failed"))
        page.locator.assert_not_called()

    def test_explicit_carsi_never_clicks_continue(self):
        page = Mock(); page.url = "https://example.org/terms"; page.evaluate.return_value = False
        downloader({"publisher_institution_federation": "carsi"})._click_optional_continue(page, DownloadResult(doi="10.1/x", status="failed"))
        page.locator.assert_not_called()
        page.evaluate.assert_not_called()

    def test_unmatched_search_no_longer_submits_blindly(self):
        d = downloader(query="红木兰大学")
        d.profile = type(THIEME)(**{**THIEME.__dict__, "institution_input_selectors": ("input#q",)})
        page = Mock(); page.url = "https://publisher.example/institution"
        box = Mock(); box.is_visible.return_value = True
        page.locator.return_value.first = box
        page.locator.return_value.first.click.side_effect = RuntimeError("no such entry")
        page.evaluate.return_value = None  # no element contains the configured name
        d._click_optional_continue = Mock()
        result = DownloadResult(doi="10.1/x", status="failed")
        with unittest.mock.patch("paper_search_carsi.engine.batch.time.sleep"):
            self.assertFalse(d._select_institution(page, result))
        d._click_optional_continue.assert_not_called()
        self.assertIn("institution_selection_required", [e["state"] for e in result.events])


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class RealPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.driver.stop()

    def open(self, html, url="https://publisher.example/page"):
        context = self.browser.new_context(service_workers="block"); self.addCleanup(context.close)
        context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
        page = context.new_page(); page.goto(url)
        return page

    def run_continue(self, html, url="https://publisher.example/page", **kw):
        page = self.open(html, url)
        downloader()._click_optional_continue(page, DownloadResult(doi="10.1055/x", status="failed"), **kw)
        page.wait_for_timeout(200)
        return page.title()

    def test_thieme_dropdown_default_is_never_submitted(self):
        self.assertNotEqual(self.run_continue(CHOOSER, "https://profile.thieme.de/HTML/sso/ejournals/shibboleth.htm"), "SUBMITTED")
        self.assertNotEqual(self.run_continue(CHOOSER), "SUBMITTED")  # dropdown alone, without the URL hint

    def test_institution_search_and_login_forms_are_left_to_the_user(self):
        self.assertNotEqual(self.run_continue(SEARCH), "SUBMITTED")
        self.assertNotEqual(self.run_continue(LOGIN), "SUBMITTED")

    def test_consent_page_with_a_site_search_box_still_continues(self):
        self.assertEqual(self.run_continue(CONSENT), "SUBMITTED")

    def test_after_matching_selection_continue_is_allowed(self):
        self.assertEqual(self.run_continue(SEARCH, after_selection=True), "SUBMITTED")

    def test_after_a_chosen_entry_only_its_own_submit_is_pressed(self):
        # The page's first button[type=submit] can be the header's search (review
        # 2026-11-02): only the submit of the chosen entry's own form or box counts.
        header = """<title>WAYF</title><header><form onsubmit="document.title='SEARCHED';return false">
            <input name="q"><button type="submit">Search</button></form></header>"""
        entries = "<ul><li data-paper-search-entry>Example University</li><li>Other University</li></ul>"
        own_form = (header + """<form onsubmit="document.title='SUBMITTED';return false">""" + entries
                    + '<button type="submit">Access through your institution</button></form>')
        self.assertEqual(self.run_continue(own_form, after_selection=True), "SUBMITTED")
        # Nothing chosen by this code: nothing pressed.
        self.assertEqual(self.run_continue(own_form.replace(" data-paper-search-entry", ""), after_selection=True), "WAYF")
        # A chooser without a submit of its own: the header's is not taken for it.
        self.assertEqual(self.run_continue(header + "<div>" + entries + "</div>", after_selection=True), "WAYF")


if __name__ == "__main__":
    unittest.main()


class RepeatedSchoolChoiceTests(unittest.TestCase):
    """NEJM signed the school in and sent the browser back to its chooser; the school
    was chosen there again every 4 s until the wait ran out (2026-11-03)."""

    CHOOSER = "https://www.nejm.org/action/ssostart?redirectUri=%2Fdoi%2F10.1056%2FNEJMoa2605812"

    def test_the_article_is_opened_again_once_then_nothing_is_chosen(self):
        from unittest.mock import Mock, patch
        from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
        from paper_search_carsi.publishers.profiles import get_publisher_profile
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                     profile=get_publisher_profile("nejm"), institution_query="Hong Mu-lan University")
        result = DownloadResult(doi="10.1056/nejmoa2605812", status="failed")
        result.article_url = "https://doi.org/10.1056/nejmoa2605812"
        page = Mock(url=self.CHOOSER)
        d._has_publisher_institution_session = Mock(return_value=False)
        d._select_from_institution_lists = Mock(return_value=True)
        for _ in range(3):  # chosen on the chooser, which came back each time
            result.events.append({"state": "auto_institution_entry", "detail": f"Hong Mu-lan University @ {self.CHOOSER}"})
        with patch("paper_search_carsi.engine.batch_institution.open_page") as opened, \
             patch("paper_search_carsi.engine.batch_institution.settle"):
            self.assertTrue(d._select_institution(page, result))
            opened.assert_called_once_with(page, result.article_url, timeout_ms=60_000)
            self.assertFalse(d._select_institution(page, result))
            self.assertFalse(d._select_institution(page, result))
        self.assertEqual(opened.call_count, 1)
        d._select_from_institution_lists.assert_not_called()
        states = [e["state"] for e in result.events]
        self.assertEqual((states.count("institution_choice_returned_article"), states.count("institution_choice_stopped")),
                         (1, 1))
        # Elsewhere, or fewer times here, the school is chosen as before.
        other = Mock(url="https://www.tandfonline.com/action/ssostart?redirectUri=%2Fdoi%2Fx")
        self.assertTrue(d._select_institution(other, result))

