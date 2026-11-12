"""Observed Nature access grant is distinct from affiliations and help copy."""
import unittest
from unittest.mock import Mock
from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.publishers.profiles import SPRINGER_PROFILE


class NatureAccessTests(unittest.TestCase):
    def check(self, body, url="https://www.nature.com/articles/s41584-026-01378-2"):
        page = Mock(url=url)
        page.locator.return_value.inner_text.return_value = body
        return PublisherBatchDownloader({}, profile=SPRINGER_PROFILE)._has_publisher_institution_session(page)

    def test_actual_access_grant_beyond_header_is_recognized_without_school_hardcoding(self):
        for institution in ("Hong Mu-lan University", "Another Research Institute"):
            self.assertTrue(self.check("Article abstract " * 700 + "\nYou have full access to this article via " + institution + ".\nLibraries & institutions"))

    def test_affiliations_generic_help_and_quote_do_not_prove_access(self):
        for body in ("Department of Medicine, Example University", "Libraries & institutions",
                     "If You have full access to this article via Example University.",
                     '\"You have full access to this article via Example University.\"',
                     "You have full access to this article via your institution.",
                     "You have full access to this article via personal subscription.",
                     "FAQ\nYou have full access to this article via Example University.",
                     "You have full access to this article via ."):
            with self.subTest(body=body):
                self.assertFalse(self.check(body))

    def test_grant_on_untrusted_host_is_not_publisher_authorization(self):
        self.assertFalse(self.check("You have full access to this article via Example University.",
                                    "https://www.nature.com.other.example/articles/test"))
