"""Elsevier ID's "Enter your organizational email": the same field as "Find your
organization", for an email only. The school's name went in there (Windows,
2026-11-11); "Access via another organization" goes back to the search by name."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile

DOI = "10.1016/j.example.2026.01.001"
CHOOSER = "https://id.elsevier.com/as/AbCdE/resume/as/authorization.ping"
EMAIL_STEP = """<title>Enter your organizational email</title>
<form method="post" action="/as/AbCdE/resume/as/authorization.ping">
  <h1 class="els-h1-txt">Enter your organizational email</h1>
  <label id="emaillabel">Organizational email</label>
  <input type="text" id="bdd-email" name="email" aria-labelledby="emaillabel emailerror">
  <button type="submit" id="bdd-elsPrimaryBtn" class="els-primaryBtn" name="action">Continue</button>
  <button type="submit" id="bdd-elsSecondaryBtn" class="els-secondaryBtn btn-border" name="action"
          value="other">Access via another organization</button>
</form>"""
# Elsevier ID with a school chosen before in this browser (2026-11-13).
REMEMBERED = """<title>Access through your organization</title>
<form method="post" action="/as/AbCdE/resume/as/authorization.ping">
  <h1>Access through your organization</h1><p>You will be sent to</p>
  <button type="submit" id="bdd-elsPrimaryBtn" class="instImgLink" name="action" value="inst">
    <div class="els-institution-group">Synthetic University B (Synthetic University B)</div></button>
  <button type="submit" id="bdd-elsPrimaryBtn3" class="els-primaryBtn" name="action" value="go">Access through your organization</button>
  <button type="submit" id="bdd-elsSecondaryBtn-tryAnotherWay" name="action" value="another">Try Another way</button>
</form>"""
# A search by name keeps the field (its label here is made up: it names more than an email).
SEARCH = """<title>Find your organization</title><h1>Find your organization</h1>
<label id="emaillabel">Organization name or email</label><input type="text" id="bdd-email" name="email">"""


def downloader():
    return PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                    profile=get_publisher_profile("elsevier"), institution_query="Synthetic University A")


class EmailStepTests(unittest.TestCase):
    def setUp(self):
        self.d = downloader()
        self.result = DownloadResult(doi=DOI, status="failed", article_url="https://www.sciencedirect.com/")

    def test_the_email_step_is_left_before_any_school_is_typed(self):
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(return_value=True))
        with patch.object(self.d, "_select_from_institution_lists") as lists:
            self.assertTrue(self.d._select_institution(page, self.result))
        lists.assert_not_called()
        self.assertEqual([e["state"] for e in self.result.events], ["elsevier_email_step_left"])

    def test_only_elsevier_ids_pages_are_looked_at(self):
        page = SimpleNamespace(url="https://www.sciencedirect.com/science/article/pii/S0000", evaluate=Mock(return_value=True))
        self.assertFalse(self.d.adapter.leave_email_step(page, self.result))
        page.evaluate.assert_not_called()
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(return_value=False))
        self.assertFalse(self.d.adapter.leave_email_step(page, self.result))
        self.assertEqual(self.result.events, [])

    def test_another_remembered_school_is_left_for_the_search(self):
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(side_effect=[False, {"school": "Synthetic University B"}, True]))
        self.assertTrue(self.d.adapter.leave_email_step(page, self.result))
        self.assertEqual([e["state"] for e in self.result.events], ["elsevier_remembered_school_left"])
        # The configured school remembered, or no school configured: nothing is clicked.
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(side_effect=[False, {"school": "Synthetic University A (SUA)"}]))
        self.assertFalse(self.d.adapter.leave_email_step(page, self.result))
        self.d.institution_query = ""
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(side_effect=[False]))
        self.assertFalse(self.d.adapter.leave_email_step(page, self.result))
        self.assertEqual(len(self.result.events), 1)

    def test_a_page_moving_on_while_read_is_looked_at_again_later(self):
        error = type("Error", (Exception,), {"__module__": "patchright._impl._errors"})
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(side_effect=error("Execution context was destroyed")))
        self.assertFalse(self.d.adapter.leave_email_step(page, self.result))
        page = SimpleNamespace(url=CHOOSER, evaluate=Mock(side_effect=ValueError("a bug")))
        with self.assertRaises(ValueError):
            self.d.adapter.leave_email_step(page, self.result)


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class EmailStepBrowserTests(unittest.TestCase):
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
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.posted = []

        def respond(route):
            if route.request.method == "POST":
                self.posted.append(route.request.post_data or "")
                route.fulfill(status=200, content_type="text/html", body=SEARCH)
                return
            route.fulfill(status=200, content_type="text/html", body=self.html)
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.d = downloader()
        self.result = DownloadResult(doi=DOI, status="failed", article_url="https://www.sciencedirect.com/")

    def test_access_via_another_organization_is_clicked_and_nothing_typed(self):
        self.html = EMAIL_STEP
        self.page.goto(CHOOSER)
        self.assertTrue(self.d.adapter.leave_email_step(self.page, self.result))
        self.page.wait_for_function("document.title === 'Find your organization'")
        self.assertEqual(len(self.posted), 1)
        self.assertIn("action=other", self.posted[0])
        self.assertIn("email=&", self.posted[0] + "&")  # the email field went back empty

    def test_try_another_way_is_clicked_for_another_remembered_school(self):
        self.html = REMEMBERED
        self.page.goto(CHOOSER)
        self.assertTrue(self.d.adapter.leave_email_step(self.page, self.result))
        self.page.wait_for_function("document.title === 'Find your organization'")
        self.assertEqual(len(self.posted), 1)
        self.assertIn("action=another", self.posted[0])
        # The configured school remembered: the page is left as it is.
        self.posted.clear()
        self.html = REMEMBERED.replace("Synthetic University B", "Synthetic University A")
        self.page.goto(CHOOSER)
        self.assertFalse(self.d.adapter.leave_email_step(self.page, self.result))
        self.assertEqual(self.posted, [])

    def test_the_search_by_name_is_left_alone(self):
        self.html = SEARCH
        self.page.goto(CHOOSER)
        self.assertFalse(self.d.adapter.leave_email_step(self.page, self.result))
        self.assertEqual(self.posted, [])


if __name__ == "__main__":
    unittest.main()
