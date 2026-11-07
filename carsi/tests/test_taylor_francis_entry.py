"""Taylor & Francis: the access box decides "signed out", and its institution link is opened."""
import os
import unittest

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import get_publisher_profile

DOI = "10.1080/0142159x.2026.2752868"
ARTICLE = "https://www.tandfonline.com/doi/full/10.1080/0142159X.2026.2752868"
CHOOSER = "https://www.tandfonline.com/action/ssostart?redirectUri=%2Fdoi%2Ffull%2F10.1080%2F0142159X.2026.2752868"
OTHER = "/action/ssostart?redirectUri=%2Fdoi%2Ffull%2F10.1080%2F01616412.2026.2757106"


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class TaylorFrancisEntryTests(unittest.TestCase):
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
        self.requests = []
        # Medical Teacher: the access box came after a long abstract (5,455 characters in).
        self.article_html = ("<title>Past-behavioural question-based multiple mini-interviews</title>"
                             "<h1>Article</h1><p>" + "Abstract text. " * 450 + "</p>"
                             "<div class='access-box'><h3>Log in via your institution</h3>"
                             f"<a href='{OTHER}'>Access through your institution</a>"
                             f"<a href='{CHOOSER}'>Access through your institution</a></div>")
        def respond(route):
            self.requests.append(route.request.url)
            body = self.article_html if route.request.url == ARTICLE else (
                "<title>Taylor &amp; Francis Online</title><select id='shib-search--fed'>"
                "<option>Select your region or federation</option></select>")
            route.fulfill(status=200, content_type="text/html", body=body)
        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                          profile=get_publisher_profile("taylor & francis"),
                                          institution_query="Synthetic University A")
        self.result = DownloadResult(doi=DOI, status="failed", article_url="https://doi.org/" + DOI)

    def test_access_box_past_a_long_abstract_means_signed_out(self):
        self.page.goto(ARTICLE)
        self.assertGreater(self.d._body_text(self.page, 200_000).lower().find("log in via your institution"), 5_000)
        self.assertTrue(self.d._looks_logged_out(self.page))
        self.assertFalse(self.d._article_access_available(self.page))
        self.article_html = "<title>Readable article</title><h1>Article</h1><p>Full text</p>"
        self.page.goto(ARTICLE)
        self.assertFalse(self.d._looks_logged_out(self.page))

    def test_this_articles_institution_link_is_opened(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.assertEqual(self.page.url, CHOOSER)
        self.assertEqual(self.requests, [ARTICLE, CHOOSER])
        self.assertIn(("sso_entry_clicked", "tandf-institution-link"),
                      [(e["state"], e["detail"]) for e in self.result.events])


if __name__ == "__main__":
    unittest.main()
