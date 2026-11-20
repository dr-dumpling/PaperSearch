"""Optica (formerly OSA, DOI prefix 10.1364) publisher-batch profile (#59).

Before #59 there was no entry in PUBLISHER_PROFILES, so `publisher-batch
--publisher optica` and prefix-based inference fell through to the generic
channel with no Optica-specific PDF routes.
"""

import unittest

from paper_search_school.publishers.profiles import (
    _PROFILE_ALIASES,
    get_publisher_profile,
    infer_publisher_profile,
)


class OpticaProfileTests(unittest.TestCase):
    def test_resolves_by_key_and_aliases(self):
        for name in ("optica", "osa", "opg"):
            self.assertEqual(get_publisher_profile(name).name, "Optica")

    def test_inferred_from_doi_prefix(self):
        profile = infer_publisher_profile("10.1364/OL.47.013297")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "Optica")

    def test_pdf_urls_use_viewmedia_doi_shape(self):
        profile = get_publisher_profile("optica")
        urls = profile.pdf_urls("10.1364/OL.47.013297")
        self.assertTrue(urls)
        for url in urls:
            self.assertIn("opg.optica.org/viewmedia.cfm", url)
            self.assertIn("uri=10.1364", url)
        self.assertIn("uri=10.1364/OL.47.013297", urls[0])       # raw
        self.assertIn("uri=10.1364%2FOL.47.013297", urls[-1])    # quoted variant

    def test_urls_are_doi_quoted_safe(self):
        profile = get_publisher_profile("optica")
        for url in profile.pdf_urls("10.1364/OL.47.013297"):
            self.assertNotIn("{", url)

    def test_alias_table_contains_sage_school_unaffected(self):
        # sanity: the alias map still resolves other publishers
        self.assertIn("wiley", _PROFILE_ALIASES)


if __name__ == "__main__":
    unittest.main()


class OpticaLoginTests(unittest.TestCase):
    """2026-11-18: after the institutional login Optica's home page said the organisation had no
    access through SSO; it was taken for the article and the run waited until it timed out."""

    def adapter(self):
        from paper_search_school.adapters.optica import OpticaAdapter

        return OpticaAdapter.__new__(OpticaAdapter)

    def test_the_home_page_is_not_the_article(self):
        adapter = self.adapter()
        for url in ("https://opg.optica.org/default.cfm", "https://opg.optica.org/"):
            self.assertIs(adapter.looks_logged_out(None, url, "optica publishing group"), True)
        self.assertIsNone(adapter.looks_logged_out(None, "https://opg.optica.org/ao/fulltext.cfm?uri=ao-65-28-9917", "abstract"))

    def test_an_organisation_without_sso_access_stops_the_login(self):
        adapter = self.adapter()
        text = "Your organization does not  have access via SSO. Please contact your librarian. Journals Conferences"
        self.assertEqual(adapter.login_block_reason(None, text.lower()), "institution_not_registered")
        self.assertIsNone(adapter.login_block_reason(None, "openathens: example university (logout) journals"))

