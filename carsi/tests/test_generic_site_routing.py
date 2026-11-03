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

from paper_search_carsi.engine import bridge

DOI = "10.1182/blood.2025032360"
LANDING = "https://ashpublications.org/blood/article/148/16/2029/569436/TRANSFORM-1-phase-3-study"
CONFIG = {"publisher_institution_federation": "carsi", "carsi_idp_name": "Example University"}


class GenericSiteRoutingTests(unittest.TestCase):
    def run_bridge(self, doi=DOI, landing=LANDING, remembered=None, wait=0):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            config = {**CONFIG, "cache_dir": temp}
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch.object(bridge, "_try_external_instsci", return_value=None))
            resolve = stack.enter_context(patch.object(bridge, "_resolve_doi", return_value=landing))
            stack.enter_context(patch("paper_search_carsi.browser.backend.is_available", return_value=True))
            self.decision = stack.enter_context(patch("paper_search_carsi.entitlements.decision_for",
                                                      return_value=remembered))
            stack.enter_context(patch("paper_search_carsi.entitlements.journal_identity",
                                      return_value={"issn": [], "journal": "Blood", "publisher": ""}))
            self.progress = stack.enter_context(patch("paper_search_carsi.progress_reporter.update"))
            self.wait = stack.enter_context(patch("paper_search_carsi.rate_limit.wait_seconds", return_value=wait))
            self.record = stack.enter_context(patch("paper_search_carsi.rate_limit.record"))
            self.downloader = MagicMock()
            self.downloader.fetch_one.return_value = SimpleNamespace(
                ok=False, pdf_path=None, state="pdf_not_captured", reason="pdf_not_captured")
            self.factory = stack.enter_context(patch("paper_search_carsi.engine.batch.PublisherBatchDownloader",
                                                     return_value=self.downloader))
            result = bridge.try_institutional(doi, Path(temp) / "out.pdf", config)
            self.resolve = resolve
        return result

    def test_no_profile_goes_to_the_publisher_driver_with_the_site_profile(self):
        result = self.run_bridge()
        self.resolve.assert_called_once_with(DOI)
        profile = self.factory.call_args.kwargs["profile"]
        self.assertEqual(profile.name, "site:ashpublications.org")
        self.assertTrue(profile.generic)
        self.assertEqual(profile.article_url(DOI), "https://doi.org/" + DOI)
        self.assertEqual(self.downloader.fetch_one.call_args.args[1].doi, DOI)
        self.assertEqual(result["artifacts"]["publisher"], "site:ashpublications.org")
        self.assertEqual(result["error_type"], "download_failed")

    def test_the_hourly_limit_the_progress_window_and_remembered_decisions_name_the_site(self):
        self.run_bridge()
        self.wait.assert_called_once_with("site:ashpublications.org", 100)
        self.record.assert_called_once_with("site:ashpublications.org")
        self.assertEqual(self.progress.call_args.kwargs["publisher"], "site:ashpublications.org")
        self.assertEqual(self.decision.call_args.args[1], "site:ashpublications.org")
        result = self.run_bridge(wait=120)
        self.factory.assert_not_called()
        self.assertEqual((result["error_type"], result["publisher"], result["retry_after_sec"]),
                         ("rate_limited", "site:ashpublications.org", 120))
        result = self.run_bridge(remembered={"decision": "skip", "key": "publisher:site:ashpublications.org"})
        self.factory.assert_not_called()
        self.assertEqual(result["reason"], "user_marked_no_entitlement")

    def test_a_doi_resolving_to_no_site_ends_as_unsupported_publisher(self):
        for landing in (None, "https://ashpublications.org/blood/article-pdf/148/16/2029/x/main.pdf",
                        "https://www.clinicalkey.com/#!/content/journal/1-s2.0-S0"):
            with self.subTest(landing=landing):
                result = self.run_bridge(landing=landing)
                self.factory.assert_not_called()
                self.assertEqual((result["error_type"], result["action"]),
                                 ("unsupported_publisher", "review_publisher_profiles"))

    def test_profiles_keep_their_route(self):
        # A profile by DOI prefix: an unresolved DOI ends as before (no result).
        self.assertIsNone(self.run_bridge(doi="10.1016/j.example.2026.1", landing=None))
        # A profile by the landing's host is used, not the site profile.
        self.run_bridge(doi="10.1164/rccm.201908-1590ST", landing="https://academic.oup.com/ajrccm/article/200/8/e70/8497012")
        self.assertFalse(self.factory.call_args.kwargs["profile"].generic)
        self.assertEqual(self.factory.call_args.kwargs["profile"].base_domains, ("academic.oup.com",))


if __name__ == "__main__":
    unittest.main()
