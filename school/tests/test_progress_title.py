"""The title the progress capsule shows for the article being downloaded."""
import os
import unittest
from unittest.mock import Mock, patch

from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile


class ProgressTitleTests(unittest.TestCase):
    def setUp(self):
        self.d = PublisherBatchDownloader({}, profile=get_publisher_profile("aip"))
        self.update = self.enterContext(patch("paper_search_school.progress_reporter.update"))

    def test_without_a_citation_title_the_dublin_core_title_is_shown(self):
        """SIAM gives dc.Title only; the capsule showed the DOI (2026-11-08)."""
        self.d._expected_title = ""
        self.d._show_title(Mock(evaluate=Mock(return_value="  Quasi-Optimal Mesh\n Sequence ")))
        self.update.assert_called_once_with(title="Quasi-Optimal Mesh Sequence")
        self.assertEqual(self.d._expected_title, "")  # shown only, never checked against

    def test_the_citation_title_comes_first(self):
        self.d._expected_title = "Citation Title"
        page = Mock(evaluate=Mock(return_value="Dublin Core Title"))
        self.d._show_title(page)
        self.update.assert_called_once_with(title="Citation Title")
        page.evaluate.assert_not_called()


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local Chrome fixture opt-in")
class DublinCoreTitleBrowserTests(unittest.TestCase):
    def test_the_meta_name_is_matched_in_any_case(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.set_content('<meta name="dc.Title" content="Atypon Article">')
                self.assertEqual(PublisherBatchDownloader._dublin_core_title(page), "Atypon Article")
                page.set_content('<meta name="DC.title" content="Other Site">')
                self.assertEqual(PublisherBatchDownloader._dublin_core_title(page), "Other Site")
                page.set_content("<title>No metadata</title>")
                self.assertEqual(PublisherBatchDownloader._dublin_core_title(page), "")
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
