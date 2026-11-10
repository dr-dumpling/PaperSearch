"""A site without a publisher profile whose article page offers no institution
entry the shared rules know ends at once as generic_institution_entry_missing,
with what was looked for and a snapshot. Mocked pages."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from paper_search_carsi.download_diagnostics import serialize_download_result
from paper_search_carsi.engine import batch, bridge
from paper_search_carsi.engine.batch import DownloadResult, PaperRecord, PublisherBatchDownloader
from paper_search_carsi.engine.batch_login import GENERIC_ENTRY_MISSING
from paper_search_carsi.publishers.profiles import get_publisher_profile
from paper_search_carsi.publishers.site import site_profile

DOI = "10.1017/s0007114526108629"
ARTICLE = "https://www.cambridge.org/core/journals/british-journal-of-nutrition/article/abs/x/ABC123"
CONTROLS = ['"Log in" -> /core/login', '"Access options" -> #access-block']


class GenericEntryMissingTests(unittest.TestCase):
    def downloader(self, profile=None, **config):
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi", **config},
                                     profile=profile or site_profile(DOI, ARTICLE), login_timeout_sec=300)
        for name in ("_dismiss_cookie_banners", "_institution_pdf_entitlement_missing", "_is_human_login_page",
                     "_challenge_shell", "_click_openathens_entry", "_select_institution"):
            setattr(d, name, Mock(return_value=False))
        d._snapshot = Mock()
        return d

    def page(self, url=ARTICLE):
        page = MagicMock()
        page.url = url
        page.evaluate.return_value = CONTROLS
        del page.new_page  # a page, not a context
        return page

    def login(self, d, page, entries=(False, False)):
        d._click_sso_entry = Mock(side_effect=list(entries))
        result = DownloadResult(doi=DOI, status="failed", article_url="https://doi.org/" + DOI)
        d._item_result = result
        with patch.object(batch.time, "sleep"), patch.object(d, "_school_login_deadline", return_value=0):
            signed_in = d._complete_login_from_current_page(page, result)
        return signed_in, result

    def test_no_entry_after_a_second_look_ends_with_what_was_looked_for(self):
        d = self.downloader()
        signed_in, result = self.login(d, self.page())
        self.assertFalse(signed_in)
        self.assertEqual(result.reason, GENERIC_ENTRY_MISSING)
        self.assertEqual(d._click_sso_entry.call_count, 2)  # one more look once the page has loaded
        looked_for = next(e["detail"] for e in result.events if e["state"] == "login_entry_missing")
        for words in ("access through your institution", "log in via your institution", "get access",
                      "institutional-login"):
            self.assertIn(words, looked_for)
        self.assertLess(len(looked_for), 500)  # kept whole in the record
        found = next(e["detail"] for e in result.events if e["state"] == "login_entry_controls")
        self.assertEqual(found, ARTICLE + ' | sign-in or access controls: "Log in" -> /core/login; '
                                          '"Access options" -> #access-block')
        d._snapshot.assert_called_once()
        self.assertEqual(d._snapshot.call_args.args[2], "login entry missing")

    def test_an_entry_found_at_the_second_look_goes_on_to_the_login(self):
        d = self.downloader()
        _, result = self.login(d, self.page(), entries=(False, True))
        self.assertNotEqual(result.reason, GENERIC_ENTRY_MISSING)
        self.assertNotIn("login_entry_missing", [e["state"] for e in result.events])

    def test_a_login_or_chooser_page_or_another_site_is_not_judged(self):
        for url in ("https://www.cambridge.org/core/login?ref=x", "https://wayfinder.openathens.net/?return=x",
                    "https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO"):
            with self.subTest(url=url):
                d = self.downloader()
                _, result = self.login(d, self.page(url), entries=(False,))
                self.assertNotEqual(result.reason, GENERIC_ENTRY_MISSING)
                self.assertEqual(d._click_sso_entry.call_count, 1)

    def test_profiles_with_rules_keep_their_endings(self):
        d = self.downloader(profile=get_publisher_profile("karger"))
        _, result = self.login(d, self.page("https://karger.com/anm/article/81/5/276/1/x"), entries=(False,))
        self.assertNotEqual(result.reason, GENERIC_ENTRY_MISSING)
        self.assertEqual(d._click_sso_entry.call_count, 1)

    def fetch(self, d, decision):
        d._write_diagnostic = Mock()
        d._hold_after_login = Mock()
        d._hold_after_run = Mock()
        d._title = Mock(return_value="Article")
        d._access_decision = Mock(return_value=decision)
        d._capture_pdf = Mock(return_value=(None, "", None))
        d._reopen_article_page = Mock()
        d._click_sso_entry = Mock(return_value=False)
        d._is_human_login_page = Mock(return_value=False)
        d._login_block_reason = Mock(return_value="")
        d._wait_for_challenge = Mock(return_value=True)
        d._is_challenge_page = Mock(return_value=False)
        page = self.page()
        page.is_closed.return_value = False
        page.locator.return_value.inner_text.return_value = ""
        with tempfile.TemporaryDirectory() as directory, patch.object(batch.time, "sleep"), \
                patch.object(batch, "open_page"), patch("paper_search_carsi.engine.batch_login.open_page"):
            return d.fetch_one(page, PaperRecord(doi=DOI), Path(directory))

    def test_the_article_ends_with_the_code_whether_signed_out_or_after_a_failed_pdf(self):
        for decision in (("out", "closed", "access gate: Access through your institution"), ("unknown", "", "")):
            with self.subTest(decision=decision):
                result = self.fetch(self.downloader(), decision)
                self.assertEqual((result.status, result.reason, result.state),
                                 ("failed", GENERIC_ENTRY_MISSING, GENERIC_ENTRY_MISSING))
                self.assertIn("login_entry_missing", [e["state"] for e in result.events])

    def test_reported_as_its_own_code(self):
        result = DownloadResult(doi=DOI, status="failed", state=GENERIC_ENTRY_MISSING, reason=GENERIC_ENTRY_MISSING)
        self.assertEqual(bridge._failure_reason_code(result), GENERIC_ENTRY_MISSING)
        self.assertEqual(bridge._FAILURE_KINDS[GENERIC_ENTRY_MISSING],
                         (GENERIC_ENTRY_MISSING, "review_publisher_profiles"))
        packet = serialize_download_result(result)
        self.assertEqual((packet["state"], packet["reason"]), (GENERIC_ENTRY_MISSING, GENERIC_ENTRY_MISSING))
        downloader = MagicMock()
        downloader.fetch_one.return_value = SimpleNamespace(ok=False, pdf_path=None, state=GENERIC_ENTRY_MISSING,
                                                            reason=GENERIC_ENTRY_MISSING)
        with tempfile.TemporaryDirectory() as temp, \
                patch("paper_search_carsi.browser.backend.is_available", return_value=True), \
                patch("paper_search_carsi.engine.batch.PublisherBatchDownloader", return_value=downloader):
            failure = bridge._try_browser_batch_download(DOI, Path(temp) / "out.pdf", {}, site_profile(DOI, ARTICLE))
        self.assertEqual((failure["error_type"], failure["action"], failure["artifacts"]["state"]),
                         (GENERIC_ENTRY_MISSING, "review_publisher_profiles", GENERIC_ENTRY_MISSING))


if __name__ == "__main__":
    unittest.main()
