"""Routing in the bridge for a DOI whose site has no publisher profile: the
profile built for the site the DOI resolves to goes to the publisher driver,
and the hourly limit, the progress window and remembered "no access"
decisions go by that site. No network, no browser."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from paper_search_school.engine import bridge

DOI = "10.9999/generic-fixture.2026"
LANDING = "https://journals.fixture.example/blood/article/148/16/2029/569436/TRANSFORM-1-phase-3-study"
CONFIG = {"publisher_institution_federation": "carsi", "school_name": "Example University"}


class GenericSiteRoutingTests(unittest.TestCase):
    def run_bridge(self, doi=DOI, landing=LANDING, remembered=None, wait=0):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            config = {**CONFIG, "cache_dir": temp}
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch.object(bridge, "_try_external_instsci", return_value=None))
            resolve = stack.enter_context(patch.object(bridge, "_resolve_doi", return_value=landing))
            stack.enter_context(patch("paper_search_school.browser.backend.is_available", return_value=True))
            self.decision = stack.enter_context(patch("paper_search_school.entitlements.decision_for",
                                                      return_value=remembered))
            stack.enter_context(patch("paper_search_school.entitlements.journal_identity",
                                      return_value={"issn": [], "journal": "Fixture Journal", "publisher": ""}))
            self.progress = stack.enter_context(patch("paper_search_school.progress_reporter.update"))
            self.wait = stack.enter_context(patch("paper_search_school.rate_limit.wait_seconds", return_value=wait))
            self.record = stack.enter_context(patch("paper_search_school.rate_limit.record"))
            self.downloader = MagicMock()
            self.downloader.fetch_one.return_value = SimpleNamespace(
                ok=False, pdf_path=None, state="pdf_not_captured", reason="pdf_not_captured")
            self.factory = stack.enter_context(patch("paper_search_school.engine.batch.PublisherBatchDownloader",
                                                     return_value=self.downloader))
            result = bridge.try_institutional(doi, Path(temp) / "out.pdf", config)
            self.resolve = resolve
        return result

    def test_no_profile_goes_to_the_publisher_driver_with_the_site_profile(self):
        result = self.run_bridge()
        self.resolve.assert_called_once_with(DOI)
        profile = self.factory.call_args.kwargs["profile"]
        self.assertEqual(profile.name, "site:fixture.example")
        self.assertTrue(profile.generic)
        self.assertEqual(profile.article_url(DOI), "https://doi.org/" + DOI)
        self.assertEqual(self.downloader.fetch_one.call_args.args[1].doi, DOI)
        self.assertEqual(result["artifacts"]["publisher"], "site:fixture.example")
        self.assertEqual(result["error_type"], "download_failed")

    def test_the_hourly_limit_the_progress_window_and_remembered_decisions_name_the_site(self):
        self.run_bridge()
        self.wait.assert_called_once_with("site:fixture.example", 100)
        self.record.assert_called_once_with("site:fixture.example")
        self.assertEqual(self.progress.call_args.kwargs["publisher"], "site:fixture.example")
        self.assertEqual(self.decision.call_args.args[1], "site:fixture.example")
        result = self.run_bridge(wait=120)
        self.factory.assert_not_called()
        self.assertEqual((result["error_type"], result["publisher"], result["retry_after_sec"]),
                         ("rate_limited", "site:fixture.example", 120))
        result = self.run_bridge(remembered={"decision": "skip", "key": "publisher:site:fixture.example"})
        self.factory.assert_not_called()
        self.assertEqual(result["reason"], "user_marked_no_entitlement")

    def test_a_doi_resolving_to_no_site_ends_as_unsupported_publisher(self):
        for landing in (None, "https://journals.fixture.example/blood/article-pdf/148/16/2029/x/main.pdf",
                        "https://www.clinicalkey.com/#!/content/journal/1-s2.0-S0"):
            with self.subTest(landing=landing):
                result = self.run_bridge(landing=landing)
                self.factory.assert_not_called()
                self.assertEqual((result["error_type"], result["action"]),
                                 ("unsupported_publisher", "review_publisher_profiles"))

    def test_a_doi_not_at_doi_org_yet_opens_the_publishers_own_article_page(self):
        # Science, 2026-11-15: online days before doi.org knew its DOI; the profile's own
        # article address opens it, the driver going on as for any other paper.
        result = self.run_bridge(doi="10.1126/scitranslmed.aea3879", landing=None)
        self.factory.assert_called_once()
        self.assertEqual(self.factory.call_args.kwargs["profile"].name, "Science")
        self.assertEqual(self.downloader.fetch_one.call_args.args[1].doi, "10.1126/scitranslmed.aea3879")
        self.assertEqual(result["error_type"], "download_failed")

    def test_a_doi_not_at_doi_org_where_only_doi_org_leads_to_the_article_says_so(self):
        # A profile reaching its articles through doi.org (Elsevier): no browser, and not a login matter.
        result = self.run_bridge(doi="10.1016/j.example.2026.1", landing=None)
        self.factory.assert_not_called()
        self.assertEqual((result["error_type"], result["reason"], result["action"]),
                         ("doi_not_resolved", "doi_not_resolved", "retry_later"))
        # A profile by the landing's host is used, not the site profile.
        self.run_bridge(doi="10.1164/rccm.201908-1590ST", landing="https://academic.oup.com/ajrccm/article/200/8/e70/8497012")
        self.assertFalse(self.factory.call_args.kwargs["profile"].generic)
        self.assertEqual(self.factory.call_args.kwargs["profile"].base_domains, ("academic.oup.com",))


if __name__ == "__main__":
    unittest.main()
