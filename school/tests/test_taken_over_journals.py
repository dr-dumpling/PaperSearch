"""Journals a publisher took over keep their DOI prefix, which Crossref lists under the new
publisher (2026-11-22): Thieme's 10.1160 (Schattauer's Thrombosis and Haemostasis) and 10.3414,
Sage's 10.1191 (Hodder Arnold) and 10.1258 (Royal Society of Medicine Press). Their DOIs go to
that publisher, its article-page rules take their pages, and where a rule of a publisher's still
does not, the engine takes a page of its site whose address ends with the item's DOI."""
import re
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from paper_search_school.adapters.thieme import ThiemeAdapter
from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile, infer_publisher_profile

DOI = "10.1160/TH12-05-0346"
ARTICLE = "https://www.thieme-connect.de/products/ejournals/abstract/10.1160/th12-05-0346"


def own_prefix_only(adapter, url):
    """Thieme's article-page rule before 2026-11-22: its own 10.1055 only."""
    parsed = urlparse(url.lower())
    return bool(re.fullmatch(r"/products/ejournals/(?:abstract|fulltext|pdf)/10\.1055/[^/]+", parsed.path))


class TakenOverJournalsTests(unittest.TestCase):
    def test_their_dois_go_to_the_publisher_that_took_them_over(self):
        for doi, name in (("10.1160/TH12-05-0346", "Thieme"), ("10.3414/ME12-01-0001", "Thieme"),
                          ("10.1191/0269215504cr775xx", "SAGE"), ("10.1258/jrsm.95.7.371", "SAGE")):
            with self.subTest(doi=doi):
                self.assertEqual(infer_publisher_profile(doi).name, name)

    def test_sage_opens_their_articles_on_its_own_site(self):
        # Windows, 2026-11-22: doi.org sent 10.1191/0961203304lu521oa to Sage's old host (lup.sagepub.com/cgi/doi/...),
        # whose verification never cleared; every Sage DOI's page is journals.sagepub.com/doi/<DOI>.
        profile = get_publisher_profile("sage")
        for doi in ("10.1191/0961203304lu521oa", "10.1258/jrsm.2011.110306", "10.1177/09612033241306790"):
            with self.subTest(doi=doi):
                self.assertEqual(profile.article_url(doi), "https://journals.sagepub.com/doi/" + doi)

    def test_sage_takes_their_article_pages(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("sage"))
        for url in ("https://journals.sagepub.com/doi/10.1258/jrsm.95.7.371",
                    "https://journals.sagepub.com/doi/full/10.1191/0269215504cr775xx",
                    "https://journals.sagepub.com/doi/pdf/10.1177/00031348251234567"):
            with self.subTest(url=url):
                self.assertIs(d.adapter.is_article_page_url(url), True)
        for url in ("https://journals.sagepub.com/doi/1258/jrsm.95.7.371",  # no DOI
                    "https://journals.sagepub.com/action/ssostart?redirectUri=%2Fdoi%2F10.1258%2Fjrsm.95.7.371",
                    "https://www.example.org/doi/10.1258/jrsm.95.7.371"):
            with self.subTest(url=url):
                self.assertIs(d.adapter.is_article_page_url(url), False)


class AddressEndingWithTheDoiTests(unittest.TestCase):
    """The engine's backing for a publisher's rule that misses a page (batch_access
    ``_address_ends_with_this_doi``), shown with Thieme's rule as it was."""

    def setUp(self):
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                          profile=get_publisher_profile("thieme"))
        self.d._track_article_for_adapter(Mock(url=ARTICLE), DOI)
        narrow = patch.object(ThiemeAdapter, "is_success_article_url", own_prefix_only)
        narrow.start()
        self.addCleanup(narrow.stop)

    def test_a_page_of_the_site_whose_address_ends_with_the_doi_is_the_article(self):
        for url in (ARTICLE, ARTICLE + "/", ARTICLE + "?lang=en#sec-1",
                    "https://www.thieme-connect.de/products/ejournals/fulltext/10.1160/TH12-05-0346",
                    "https://thieme-connect.com/products/ejournals/abstract/10.1160%2Fth12-05-0346"):
            with self.subTest(url=url):
                self.assertTrue(self.d._is_success_article_url(url))

    def test_not_its_pdf_files_login_another_site_or_another_article(self):
        for url in ("https://www.thieme-connect.de/products/ejournals/pdf/10.1160/th12-05-0346.pdf",
                    "https://www.thieme-connect.de/media/10.1160/123/supmat/10-1160-th12-05-0346_s1.pdf",
                    "https://www.thieme-connect.de/products/ejournals/abstract/10.1160/th12-05-0346/references.html",
                    "https://www.thieme-connect.de/login/10.1160/th12-05-0346",
                    "https://profile.thieme.de/HTML/sso/THIEME/login.htm?hook_url=" + ARTICLE,
                    "https://www.example.org/products/ejournals/abstract/10.1160/th12-05-0346",
                    "https://www.thieme-connect.de/products/ejournals/abstract/10.1160/th12-05-9999",
                    "https://www.thieme-connect.de/products/ejournals/issue/10.1160/th12-05-0346x",
                    "", "about:blank"):
            with self.subTest(url=url):
                self.assertFalse(self.d._is_success_article_url(url))

    def test_only_the_item_being_downloaded(self):
        self.d._track_article_for_adapter(Mock(url=ARTICLE), "10.1160/TH12-05-9999")
        self.assertFalse(self.d._is_success_article_url(ARTICLE))
        self.d._track_article_for_adapter(Mock(url=ARTICLE), "")
        self.assertFalse(self.d._is_success_article_url(ARTICLE))

    def test_a_rule_that_takes_the_page_is_unchanged(self):
        own = "https://www.thieme-connect.de/products/ejournals/pdf/10.1055/s-0038-1677497.pdf"
        self.assertTrue(self.d._is_success_article_url(own))


if __name__ == "__main__":
    unittest.main()
