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
    def run_bridge(self, doi=DOI, landing=LANDING, remembered=None, wait=0, pubmed=None, days=0, unknown=False):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            config = {**CONFIG, "cache_dir": temp}
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
            stack.enter_context(patch.object(bridge, "_try_external_instsci", return_value=None))
            resolve = stack.enter_context(patch.object(bridge, "_resolve_doi", return_value=landing))
            self.pubmed = stack.enter_context(patch.object(bridge, "_pubmed_article", return_value=pubmed))
            stack.enter_context(patch.object(bridge, "_published_days_ago", return_value=days))
            self.unknown = stack.enter_context(patch.object(bridge, "_doi_unknown_to_doi_org", return_value=unknown))
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


    def test_a_doi_doi_org_never_knew_opens_the_publishers_link_pubmed_lists(self):
        # Annals of the Rheumatic Diseases, 2026-11-16: BMJ DOIs of 2024-25 never registered,
        # PubMed listing Elsevier's link; the browser opens it, the driver going on as for any paper.
        link = "https://linkinghub.elsevier.com/retrieve/pii/S0003-4967(25)00001-9"
        result = self.run_bridge(doi="10.1136/ard-2024-225982", landing=None,
                                 pubmed={"pmid": "39739385", "url": link})
        self.pubmed.assert_called_once_with("10.1136/ard-2024-225982")
        self.factory.assert_called_once()
        self.assertEqual(self.factory.call_args.kwargs["profile"].name, "Elsevier")
        self.downloader.use_article_url.assert_called_once_with("10.1136/ard-2024-225982", link)
        self.assertEqual(self.downloader.fetch_one.call_args.args[1].doi, "10.1136/ard-2024-225982")
        self.assertEqual(result["error_type"], "download_failed")
        # Without a profile for the DOI, the link's site names one.
        self.run_bridge(landing=None, pubmed={"pmid": "1", "url": link})
        self.assertEqual(self.factory.call_args.kwargs["profile"].name, "Elsevier")

    def test_a_doi_never_registered_for_a_paper_published_long_ago_is_said_so(self):
        # PubMed has the paper a month and more, with no link but doi.org's, and doi.org says it has no such DOI.
        result = self.run_bridge(doi="10.1016/j.example.2026.1", landing=None, pubmed={"pmid": "1", "url": ""},
                                 days=330, unknown=True)
        self.factory.assert_not_called()
        self.assertEqual((result["error_type"], result["action"]), ("doi_not_registered", "review_publisher_error"))
        # A paper of the last days, or doi.org not answering: not yet registered, try again later.
        for days, unknown in ((3, True), (330, False)):
            with self.subTest(days=days, unknown=unknown):
                result = self.run_bridge(doi="10.1016/j.example.2026.1", landing=None,
                                         pubmed={"pmid": "1", "url": ""}, days=days, unknown=unknown)
                self.assertEqual(result["error_type"], "doi_not_resolved")
        # doi.org knowing the DOI asks PubMed nothing.
        self.run_bridge(doi="10.1016/j.example.2026.1", landing="https://www.sciencedirect.com/science/article/pii/S0")
        self.pubmed.assert_not_called()


class PubmedLinkTests(unittest.TestCase):
    """PubMed's link to the publisher (LinkOut), read from E-utilities' answers."""

    def answers(self, *bodies):
        responses = [MagicMock(**{"json.return_value": body}) for body in bodies]
        return patch("requests.get", side_effect=responses)

    def test_the_publishers_own_link_not_doi_orgs_nor_pubmed_centrals(self):
        search = {"esearchresult": {"idlist": ["39739385"]}}
        links = {"linksets": [{"idurllist": [{"objurls": [
            {"url": {"value": "https://dx.doi.org/10.1136/ard-2024-225982"}},
            {"url": {"value": "https://pmc.ncbi.nlm.nih.gov/articles/pmid/39739385/"}},
            {"url": {"value": "https://linkinghub.elsevier.com/retrieve/pii/S0003-4967(25)00001-9"}}]}]}]}
        with self.answers(search, links) as get:
            found = bridge._pubmed_article("10.1136/ard-2024-225982")
        self.assertEqual(found, {"pmid": "39739385", "url": "https://linkinghub.elsevier.com/retrieve/pii/S0003-4967(25)00001-9"})
        self.assertEqual(get.call_args_list[0].kwargs["params"]["term"], '"10.1136/ard-2024-225982"[aid]')
        # Only doi.org's link (Springer): the paper, without a link.
        with self.answers(search, {"linksets": [{"idurllist": [{"objurls": [
                {"url": {"value": "https://dx.doi.org/10.1007/x"}}]}]}]}):
            self.assertEqual(bridge._pubmed_article("10.1007/x"), {"pmid": "39739385", "url": ""})

    def test_no_single_record_or_no_answer_is_none(self):
        for ids in ([], ["1", "2"]):
            with self.subTest(ids=ids), self.answers({"esearchresult": {"idlist": ids}}):
                self.assertIsNone(bridge._pubmed_article("10.1/x"))
        import requests
        with patch("requests.get", side_effect=requests.ConnectionError("down")):
            self.assertIsNone(bridge._pubmed_article("10.1/x"))
            self.assertFalse(bridge._doi_unknown_to_doi_org("10.1/x"))
            self.assertEqual(bridge._published_days_ago({"pmid": "1", "url": ""}), 0)

    def test_doi_orgs_own_no_and_the_papers_age(self):
        with self.answers({"responseCode": 100}, {"responseCode": 1}):
            self.assertTrue(bridge._doi_unknown_to_doi_org("10.1136/ard-2024-225982"))
            self.assertFalse(bridge._doi_unknown_to_doi_org("10.1136/ard-2024-225872"))
        with self.answers({"result": {"1": {"sortpubdate": "2024/12/20 00:00"}}}):
            self.assertGreater(bridge._published_days_ago({"pmid": "1", "url": ""}), 300)


if __name__ == "__main__":
    unittest.main()
