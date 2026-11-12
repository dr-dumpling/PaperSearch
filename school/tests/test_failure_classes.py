"""Where a login wait ended decides who it is on (ADR 0012); the codes survive the records."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from paper_search_school.download_diagnostics import serialize_download_result
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.engine.bridge import _FAILURE_KINDS, _failure_reason_code
from paper_search_school.publishers.profiles import get_publisher_profile


def page(url):
    return Mock(url=url, is_closed=Mock(return_value=False))


class LoginWaitPageTests(unittest.TestCase):
    def downloader(self, school="Hong Mu-lan University"):
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                     profile=get_publisher_profile("taylor & francis"), institution_query=school)
        d._is_human_login_page = Mock(return_value=False)
        d._school_password_box = Mock(return_value=False)
        return d

    def test_the_kinds_of_page_a_wait_can_end_on(self):
        d = self.downloader()
        # Neurological Research, cold start: the wait ran out on the article itself.
        self.assertEqual(d._login_wait_page(page("https://www.tandfonline.com/doi/full/10.1080/01616412.2026.2757106")),
                         "publisher")
        chooser = page("https://www.tandfonline.com/action/ssostart?redirectUri=%2Fdoi%2Ffull%2F10.1080%2Fx")
        self.assertEqual(d._login_wait_page(chooser), "institution_chooser")
        self.assertEqual(self.downloader(school="")._login_wait_page(chooser), "school_choice")
        d._school_password_box = Mock(return_value=True)
        self.assertEqual(d._login_wait_page(page("https://cas.example.edu.cn/esc-sso/login/page")), "school_login")
        closed = page("about:blank")
        closed.is_closed.return_value = True
        self.assertEqual(d._login_wait_page(closed), "closed")

    def test_a_failed_login_records_where_its_wait_ended(self):
        d = self.downloader()
        d._login_block_reason = Mock(return_value=None)
        d._write_diagnostic = Mock()
        result = DownloadResult(doi="10.1080/01616412.2026.2757106", status="failed")
        result._user_wait_expired = True
        d._login_failed(page("https://www.tandfonline.com/doi/full/10.1080/01616412.2026.2757106"), result,
                        Path(tempfile.mkdtemp()))
        self.assertEqual((result.reason, result.login_wait_page), ("sso_required", "publisher"))
        self.assertEqual([(e["state"], e["detail"]) for e in result.events], [("login_wait_ended", "publisher")])
        d._write_diagnostic.assert_called_once()
        # A login that ended without waiting on the user records no wait page.
        result = DownloadResult(doi="10.1080/x", status="failed")
        d._login_failed(page("https://www.tandfonline.com/doi/full/10.1080/x"), result, Path(tempfile.mkdtemp()))
        self.assertEqual(result.login_wait_page, "")


def _failure_kind(result):
    return _FAILURE_KINDS.get(_failure_reason_code(result), ("download_failed", ""))


class FailureKindTests(unittest.TestCase):
    def result(self, reason, wait_page="", expired=True):
        r = DownloadResult(doi="10.1/x", status="failed", reason=reason, state=reason, login_wait_page=wait_page)
        r._user_wait_expired = expired
        return r

    def test_a_timeout_is_the_users_only_on_a_page_with_a_step_for_the_user(self):
        self.assertEqual(_failure_kind(self.result("sso_required", "school_login"))[0], "login_timeout")
        self.assertEqual(_failure_kind(self.result("sso_required", "school_choice"))[0], "login_timeout")
        self.assertEqual(_failure_kind(self.result("sso_required", "publisher"))[0], "login_not_reached")
        self.assertEqual(_failure_kind(self.result("sso_required", "institution_chooser"))[0], "login_not_reached")
        # Oxford Academic's own login flow ends as login_timeout; the same rule applies.
        self.assertEqual(_failure_kind(self.result("login_timeout", "publisher"))[0], "login_not_reached")
        # Without the page (records written before), the old reading stays.
        self.assertEqual(_failure_kind(self.result("sso_required"))[0], "login_timeout")
        self.assertEqual(_failure_kind(self.result("sso_required", expired=False)), ("paywall", "login_required"))
        self.assertEqual(_failure_kind(self.result("institution_federation_unavailable"))[0],
                         "institution_federation_unavailable")
        self.assertEqual(_failure_kind(self.result("pdf_not_captured"))[0], "download_failed")


class RecordCodesTests(unittest.TestCase):
    def test_codes_and_the_wait_page_survive_the_record(self):
        for reason in ("unsupported_platform", "institution_federation_unavailable", "user_skipped",
                       "pdf_wrong_article", "login_not_reached"):
            record = serialize_download_result(DownloadResult(doi="10.1/x", status="failed", reason=reason, state=reason))
            self.assertEqual((record["state"], record["reason"]), (reason, reason))
        result = DownloadResult(doi="10.1/x", status="failed", reason="sso_required", state="sso_required",
                                events=[{"state": "login_wait_ended", "detail": "publisher"}])
        self.assertEqual(serialize_download_result(result)["events"][0], {"state": "login_wait_ended", "category": "publisher"})



class DenialEvidenceTests(unittest.TestCase):
    def test_the_publishers_words_are_kept_when_the_school_is_not_subscribed(self):
        import json
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("elsevier"))
        d._access_state = Mock(return_value=("logged_in_no_entitlement", ["Brought to you by:Hong Mu-Lan University"]))
        sciencedirect = Mock(url="https://www.sciencedirect.com/science/chapter/edited-volume/abs/pii/B9780443222535000285")
        sciencedirect.locator.return_value.inner_text.return_value = (
            "Brought to you by:\nHong Mu-Lan University\n"
            "Hong Mu-lan University does not subscribe to this content on ScienceDirect.\nPurchase chapter")
        result = DownloadResult(doi="10.1016/b978-0-443-22253-5.00028-5", status="failed",
                                reason="institution_pdf_entitlement_missing", state="institution_pdf_entitlement_missing")
        d._write_diagnostic(sciencedirect, result, Path(tempfile.mkdtemp()))
        # The rule, the page's words and why they are the school's (2026-11-02).
        words = ('denial line: "Hong Mu-lan University does not subscribe to this content on ScienceDirect."'
                 " (the institution's session)")
        self.assertEqual([(e["state"], e["detail"]) for e in result.events], [("entitlement_denied", words)])
        saved = json.loads(Path(result.diagnostic_path).read_text(encoding="utf-8"))
        self.assertIn({"state": "entitlement_denied", "detail": words}, [{k: e[k] for k in ("state", "detail")} for e in saved["events"]])
        # Other failures add nothing.
        other = DownloadResult(doi="10.1/x", status="failed", reason="pdf_not_captured", state="pdf_not_captured")
        d._write_diagnostic(sciencedirect, other, Path(tempfile.mkdtemp()))
        self.assertEqual(other.events, [])


if __name__ == "__main__":
    unittest.main()
