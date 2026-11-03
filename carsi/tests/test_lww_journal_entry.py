"""LWW journal pages: the subscriber panel below the abstract means signed out; its Ovid institution entry is used."""
import os
import unittest

from paper_search_carsi.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_carsi.publishers.profiles import infer_publisher_profile_from_url

ARTICLE = "https://journals.lww.com/hep/abstract/10.1097/hep.0000000000001105~fixture"
OVID = "https://www.ovid.com/fixture/institutional"
PERSONAL = "https://journals.lww.com/fixture/personal"
SOCIETY = "https://journals.lww.com/fixture/aasld"


@unittest.skipUnless(os.environ.get("CARSI_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class LwwJournalEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
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
        abstract = "<p>" + "Abstract text. " * 600 + "</p>"  # pushes the panel past 5000 characters
        self.html = f'''<title>Exchangeable copper : Hepatology</title>{abstract}
          <h3>Full Text Access for Subscribers</h3>
          <a href="{PERSONAL}">Individual Subscribers Log in for access</a>
          <a href="{OVID}">Institutional Users Access through Ovid</a>
          <a href="{SOCIETY}">AASLD members log in here</a>'''

        def respond(route):
            self.requests.append(route.request.url)
            body = self.html if route.request.url == ARTICLE else "<title>Destination</title>"
            route.fulfill(status=200, content_type="text/html", body=body)

        self.context.route("**/*", respond)
        self.page = self.context.new_page()
        profile = infer_publisher_profile_from_url(ARTICLE)
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"}, profile=profile,
                                          institution_query="Example University")
        self.result = DownloadResult(doi="10.1097/hep.0000000000001105", status="failed", article_url=ARTICLE)

    def test_subscriber_panel_below_the_fold_is_signed_out_and_ovid_entry_is_used(self):
        self.page.goto(ARTICLE)
        self.assertTrue(self.d._looks_logged_out(self.page))
        self.assertTrue(self.d._click_sso_entry(self.page, self.result))
        self.page.wait_for_url(OVID)
        self.assertEqual(self.requests, [ARTICLE, OVID])
