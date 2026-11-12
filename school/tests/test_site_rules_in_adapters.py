"""Site rules that were engine checks, now their adapters' (review 2026-11-02): the
same answers for their publishers, none for the others. Mocked pages only."""
import unittest
from unittest.mock import Mock

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile


def downloader(publisher, **config):
    return PublisherBatchDownloader(config, profile=get_publisher_profile(publisher), institution_query="Example University")


def page(url, text="", title=""):
    p = Mock(url=url)
    p.is_closed.return_value = False
    p.title.return_value = title
    p.locator.return_value.inner_text.return_value = text
    p.evaluate.return_value = None
    return p


class MovedSiteRulesTests(unittest.TestCase):
    def test_ieee_s_outage_page_ends_the_login_for_ieee_only(self):
        outage = page("https://ieeexplore.ieee.org/document/1", "IEEE Xplore is temporarily unavailable. Please try later.")
        mailbox = page("https://ieeexplore.ieee.org/document/1",
                       "This page is temporarily unavailable. Contact onlinesupport@ieee.org")
        self.assertEqual(downloader("ieee")._login_block_check(outage), "publisher_temporarily_unavailable")
        self.assertEqual(downloader("ieee")._login_block_check(mailbox), "publisher_temporarily_unavailable")
        self.assertEqual(downloader("acs")._login_block_check(outage), "")

    def test_thieme_s_chooser_is_its_adapter_s(self):
        chooser = "https://profile.thieme.de/HTML/sso/ejournals/shibboleth.htm"
        thieme = downloader("thieme")
        self.assertTrue(thieme._is_federation_chooser(chooser))
        self.assertTrue(thieme._is_federation_chooser(chooser.replace("shibboleth.htm", "shibboleth-idpsearch.htm")))
        self.assertFalse(thieme._is_federation_chooser("https://profile.thieme.de/HTML/sso/THIEME/login.htm"))
        self.assertFalse(thieme._is_federation_chooser(chooser.replace("https:", "http:")))
        self.assertFalse(downloader("wiley")._is_federation_chooser(chooser))

    def test_acs_s_block_page_mailbox_is_acs_s_own(self):
        body = "<html><body>Please contact ipblock@acs.org</body></html>"
        acs = downloader("acs")
        self.assertTrue(acs._is_ip_block_response(200, body))
        self.assertTrue(acs._is_explicit_block_page(body, acs.adapter.block_page_markers))
        self.assertFalse(downloader("elsevier")._is_ip_block_response(200, body))
        self.assertFalse(PublisherBatchDownloader._is_explicit_block_page(body))
        self.assertTrue(PublisherBatchDownloader._is_explicit_block_page("Your IP address has been blocked"))

    def test_annual_reviews_openathens_route_outside_school(self):
        d, result = downloader("annual-reviews"), DownloadResult(doi="10.1146/x", status="failed")
        shib = page("https://www.annualreviews.org/session/ext/shib?url=%2Fdoi%2F10.1146%2Fx")
        self.assertTrue(d._click_openathens_entry(shib, result))
        self.assertEqual(shib.goto.call_args.args[0], "https://www.annualreviews.org/session/ext/athens"
                                                      "?url=%2Fdoi%2F10.1146%2Fx&athensWayfSearch=Example+University")
        self.assertEqual(result.events[-1]["state"], "openathens_entry")
        athens = page("https://www.annualreviews.org/session/ext/athens?url=%2Fdoi%2F10.1146%2Fx")
        self.assertFalse(d._click_openathens_entry(athens, result))
        athens.evaluate.assert_not_called()  # no generic OpenAthens control there
        carsi = downloader("annual-reviews", publisher_institution_federation="carsi")
        self.assertFalse(carsi._click_openathens_entry(shib, result))
        other = page("https://www.example.org/session/ext/shib?url=%2F")
        self.assertFalse(downloader("wiley")._click_openathens_entry(other, result))
        other.goto.assert_not_called()

    def test_annual_reviews_school_search_on_its_openathens_page(self):
        d, result = downloader("annual-reviews"), DownloadResult(doi="10.1146/x", status="failed")
        athens = page("https://www.annualreviews.org/session/ext/athens?url=%2F")
        athens.locator.return_value.first.is_visible.return_value = False  # no "Option 2" box: the page's controls
        athens.evaluate.return_value = {"action": "openathens_search", "query": "Example University"}
        self.assertTrue(d.adapter.fill_institution_search(athens, result))
        self.assertEqual(athens.evaluate.call_args.args[1], "Example University")
        self.assertEqual(result.events[-1]["state"], "institution_selected")
        self.assertFalse(d.adapter.fill_institution_search(page("https://www.annualreviews.org/doi/10.1146/x"), result))


if __name__ == "__main__":
    unittest.main()
