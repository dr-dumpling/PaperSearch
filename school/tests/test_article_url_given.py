"""An article page given for a DOI doi.org does not know (PubMed's link to the publisher,
Annals of the Rheumatic Diseases 2026-11-16) is the page the downloader opens for it."""
import unittest

from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile

DOI = "10.1136/ard-2024-225982"
LINK = "https://linkinghub.elsevier.com/retrieve/pii/S0003-4967(25)00001-9"


class GivenArticleUrlTests(unittest.TestCase):
    def test_the_given_page_for_its_doi_only(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        self.assertEqual(d._article_url(DOI), "https://doi.org/" + DOI)
        d.use_article_url(DOI.upper(), LINK)
        self.assertEqual(d._article_url(DOI), LINK)
        self.assertEqual(d._article_url("10.1136/ard-2024-225872"), "https://doi.org/10.1136/ard-2024-225872")


if __name__ == "__main__":
    unittest.main()
