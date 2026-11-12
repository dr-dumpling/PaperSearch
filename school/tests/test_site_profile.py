"""The run-time profile of a site without a publisher profile (publishers/site.py)."""
import unittest

from paper_search_school.adapters import PublisherAdapter
from paper_search_school.adapters.base import adapter_class_for
from paper_search_school.publishers import profiles
from paper_search_school.publishers.model import PublisherProfile
from paper_search_school.publishers.site import SiteProfile, site_profile

DOI = "10.1017/s0007114526108629"


class SiteProfileTests(unittest.TestCase):
    def test_named_after_the_registrable_domain_of_the_landing_page(self):
        for url, domain in (
                ("https://www.cambridge.org/core/product/identifier/S0007114526108629/type/journal_article", "cambridge.org"),
                ("https://journals.physiology.org/doi/10.1152/ajpheart.00422.2026", "physiology.org"),
                ("https://www.degruyterbrill.com/document/doi/10.1515/cclm-2026-1298/html", "degruyterbrill.com"),
                ("http://journals.example.ac.uk/article/1", "example.ac.uk"),
                # A second-level country suffix, not the whole registry (review 2026-11-02).
                ("https://www.jstage.jst.go.jp/article/x/1/1/1_1/_article", "jst.go.jp"),
                ("https://koreascience.or.kr/article/JAKO202600000000001.page", "koreascience.or.kr"),
                ("https://WWW.Example.Org./x", "example.org")):
            with self.subTest(url=url):
                profile = site_profile(DOI, url)
                self.assertIsInstance(profile, SiteProfile)
                self.assertEqual(profile.name, "site:" + domain)
                self.assertEqual(profile.base_domains, (domain,))

    def test_the_doi_prefix_the_doi_org_article_address_and_no_pdf_formulas(self):
        profile = site_profile("10.1182/BLOOD.2025032360", "https://ashpublications.org/blood/article/148/16/2029/569436/x")
        self.assertEqual(profile.doi_prefixes, ("10.1182",))
        self.assertEqual(profile.article_url("10.1182/blood.2025032360"), "https://doi.org/10.1182/blood.2025032360")
        self.assertEqual(profile.pdf_url_templates, ())
        self.assertEqual(profile.pdf_urls("10.1182/blood.2025032360"), [])
        self.assertEqual(profile.success_url_markers, ())  # the engine's DOI / citation_doi rule decides
        self.assertIn("access through your institution", profile.sso_text_markers)
        self.assertIn("/login", profile.auth_url_markers)
        self.assertIn("suppl_file", profile.supplementary_url_markers)
        for markers in (profile.auth_url_markers, profile.auth_title_markers, profile.sso_text_markers,
                        profile.supplementary_url_markers):
            self.assertLessEqual(len(markers), 8)

    def test_only_the_shared_rules_apply(self):
        profile = site_profile(DOI, "https://www.cambridge.org/core/x")
        self.assertTrue(profile.generic)
        self.assertFalse(PublisherProfile.generic)
        self.assertFalse(any(p.generic for p in profiles.PUBLISHER_PROFILES.values()))
        self.assertIs(adapter_class_for(profile), PublisherAdapter)
        # Never one of the builtin profiles, nor reachable by name or DOI prefix.
        self.assertFalse(any(key.startswith("site:") for key in profiles.list_publisher_profiles()))
        self.assertIsNone(profiles.infer_publisher_profile(DOI))
        with self.assertRaises(ValueError):
            profiles.get_publisher_profile("site:cambridge.org")

    def test_no_profile_where_the_doi_leads_to_no_site_to_sign_in_on(self):
        for url in ("", "not a url", "ftp://files.example.org/a", "https://user:secret@www.example.org/a",
                    "https://www.example.org/content/article.PDF", "https://192.0.2.1/article", "https://localhost/a",
                    "https://doi.org/10.1017/x", "https://chooser.crossref.org/?doi=10.1017%2Fx",
                    "https://hdl.handle.net/10.1017/x",
                    "https://www.clinicalkey.com/#!/content/journal/1-s2.0-S0", "https://www.clinicalkey.com.au/x",
                    "https://kns.cnki.net/kcms/detail", "https://www.wanfangdata.com.cn/details", "https://www.cqvip.com/x"):
            with self.subTest(url=url):
                self.assertIsNone(site_profile(DOI, url))
        for doi in ("", "10.1017", "doi:10.1017/x", "11.1017/x", "10.12/x"):
            with self.subTest(doi=doi):
                self.assertIsNone(site_profile(doi, "https://www.cambridge.org/core/x"))


if __name__ == "__main__":
    unittest.main()
