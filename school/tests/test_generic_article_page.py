"""The article page on a site without a publisher profile (batch_access
``_names_this_article``): an address of the site carrying the DOI, or a page
whose citation_doi is the DOI. Profiles with their own markers keep them."""
import unittest
from unittest.mock import Mock

from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile
from paper_search_school.publishers.site import site_profile

DOI = "10.1182/blood.2025032360"
ARTICLE = "https://ashpublications.org/blood/article/148/16/2029/569436/TRANSFORM-1-phase-3-study"


def page(url, citation=None):
    tab = Mock(url=url)
    tab.evaluate.return_value = {"dois": citation or [], "pdfs": [], "links": []}
    return tab


class GenericArticlePageTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                          profile=site_profile(DOI, ARTICLE))
        self.tab = page(ARTICLE)
        self.d._track_article_for_adapter(self.tab, DOI)

    def test_an_address_of_the_site_carrying_the_doi(self):
        for url in ("https://ashpublications.org/blood/article/doi/10.1182/BLOOD.2025032360/569436/x",
                    "https://ashpublications.org/doi/full/10.1182%2Fblood.2025032360",
                    "https://www.ashpublications.org/viewer?doi=10.1182/blood.2025032360#top"):
            with self.subTest(url=url):
                self.assertTrue(self.d._is_success_article_url(url))
        self.tab.evaluate.assert_not_called()  # the address alone decides

    def test_not_a_login_page_another_site_or_another_article(self):
        for url in ("https://ashpublications.org/action/ssostart?redirectUri=%2Fdoi%2F10.1182%2Fblood.2025032360",
                    "https://ashpublications.org/login?returnUrl=/doi/10.1182/blood.2025032360",
                    "https://doi.org/10.1182/blood.2025032360",
                    "https://ashpublications.org.evil.example/doi/10.1182/blood.2025032360",
                    "https://ashpublications.org/doi/10.1182/blood.2025099999",
                    "", "about:blank"):
            with self.subTest(url=url):
                self.assertFalse(self.d._is_success_article_url(url))

    def test_the_open_page_whose_citation_doi_is_the_doi_and_remembered_for_the_item(self):
        self.assertFalse(self.d._is_success_article_url(ARTICLE))  # no citation_doi yet
        self.tab.evaluate.return_value = {"dois": ["https://doi.org/10.1182/BLOOD.2025032360"], "pdfs": [], "links": []}
        self.assertTrue(self.d._is_success_article_url(ARTICLE))
        self.assertTrue(self.d._is_success_article_url(ARTICLE + "#sec-1"))
        # Remembered: the tab has moved on (an attempt's final URL, the login's start page).
        self.tab.url = "https://ashpublications.org/"
        self.tab.evaluate.reset_mock()
        self.tab.evaluate.return_value = {"dois": [], "pdfs": [], "links": []}
        self.assertTrue(self.d._is_success_article_url(ARTICLE))
        self.tab.evaluate.assert_not_called()
        self.assertFalse(self.d._is_success_article_url("https://ashpublications.org/"))
        # The next item starts afresh.
        self.d._track_article_for_adapter(page(ARTICLE), "10.1182/blood.2025099999")
        self.assertFalse(self.d._is_success_article_url(ARTICLE))

    def test_a_page_naming_another_doi_or_several_is_not_this_article(self):
        for dois in (["10.1182/blood.2025099999"], [DOI, "10.1182/blood.2025099999"], []):
            with self.subTest(dois=dois):
                self.d._citation_pages = None
                self.tab.evaluate.return_value = {"dois": dois, "pdfs": [], "links": []}
                self.assertFalse(self.d._is_success_article_url(ARTICLE))
        # Only the open page is read: another address is not judged by it.
        self.tab.evaluate.return_value = {"dois": [DOI], "pdfs": [], "links": []}
        self.assertFalse(self.d._is_success_article_url(ARTICLE.replace("569436", "569437")))

    def test_profiles_with_their_own_markers_keep_them(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("karger"))
        tab = page("https://karger.com/some/page/10.1159/000123456", citation=["10.1159/000123456"])
        d._track_article_for_adapter(tab, "10.1159/000123456")
        self.assertEqual(d._is_success_article_url("https://www.example.org/10.1159/000123456"), False)
        self.assertTrue(d._is_success_article_url("https://karger.com/anm/article/81/5/276/1/x"))


if __name__ == "__main__":
    unittest.main()
