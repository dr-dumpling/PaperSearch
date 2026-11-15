"""A publisher without a login route for the school: its later articles do not wait for one."""
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from paper_search_school import login_routes
from paper_search_school.engine import bridge
from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile

CONFIG = {"publisher_institution_federation": "carsi", "school_name": "红木兰大学",
          "school_name_en": "Hong Mu-lan University", "idp_entity_id": "https://idp.example.edu.cn/idp/shibboleth"}


class LoginRoutesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"SCHOOL_DATA_DIR": folder.name})
        env.start()
        self.addCleanup(env.stop)

    def test_kept_by_publisher_and_school_for_half_an_hour(self):
        school = login_routes.school_key(CONFIG)
        self.assertEqual(school, "https://idp.example.edu.cn/idp/shibboleth | 红木兰大学")
        # Schools signing in through one shared entry are kept apart by their names.
        shared = {"idp_entity_id": "https://idp.example.no", "school_name": "Universitetet i Kita"}
        self.assertNotEqual(login_routes.school_key(shared), login_routes.school_key({**shared, "school_name": "Bay University"}))
        self.assertEqual(login_routes.school_key({"school_name_en": "Kita University"}), "kita university")
        self.assertTrue(login_routes.remember("Science", school, "10.1126/science.aed8207", now=1000))
        self.assertEqual(login_routes.missing_since("science", school, now=1060), "10.1126/science.aed8207")
        self.assertEqual(login_routes.missing_since("Science", "another school", now=1060), "")
        self.assertEqual(login_routes.missing_since("BMJ", school, now=1060), "")
        self.assertEqual(login_routes.missing_since("Science", school, now=1000 + login_routes.KEEP_SEC + 1), "")
        self.assertFalse(login_routes.remember("", school, "10.1/x"))
        self.assertEqual(login_routes.school_key({}), "")
        # The backend writes it when an article ends without a route.
        bridge._remember_missing_route("BMJ", CONFIG, "10.1136/bjsports-2026-111824")
        self.assertEqual(login_routes.missing_since("BMJ", school), "10.1136/bjsports-2026-111824")

    def test_a_later_article_of_that_publisher_ends_before_its_login(self):
        # Science, 2026-11-11: the second article waited the same 60 s for a school not listed.
        login_routes.remember("Science", login_routes.school_key(CONFIG), "10.1126/science.aed8207")
        d = PublisherBatchDownloader(CONFIG, profile=get_publisher_profile("science"), institution_query="红木兰大学")
        page = Mock(url="https://www.science.org/doi/10.1126/scitranslmed.adz4081")
        result = DownloadResult(doi="10.1126/scitranslmed.adz4081", status="failed")
        with patch.object(d.adapter, "complete_login", return_value=None), \
                patch.object(d, "_institution_pdf_entitlement_missing", return_value=False):
            self.assertFalse(d._complete_login_steps(page, result))
        self.assertEqual(result.reason, "institution_federation_unavailable")
        self.assertNotIn("sso_start", [e["state"] for e in result.events])
        # Another school, or no record: the login goes on as before.
        self.assertEqual(login_routes.missing_since("Science", "https://idp.other.edu.cn/idp/shibboleth"), "")

    def test_only_a_list_seen_without_the_school_is_remembered(self):
        # Science, 2026-11-15: an article whose login came back to Science's own login
        # page ended as "no route", and every later one of the batch on that finding.
        profile = get_publisher_profile("science")

        def artifacts(events, not_listed):
            result = DownloadResult(doi="10.1126/scitranslmed.aed4678", status="failed")
            result.state = "institution_federation_unavailable"
            result.events = [{"at": "15:22:00", "state": state, "detail": ""} for state in events]
            if not_listed:
                result._institution_not_listed = True
            return bridge._browser_artifacts(result, profile)

        self.assertTrue(artifacts(["auto_institution_search"], True).get("route_missing"))
        # The school was chosen in the list: the list has it, whatever ended the login.
        self.assertNotIn("route_missing", artifacts(["auto_institution_search", "institution_selected"], True))
        # Ended on an earlier article's finding: not written again, so it does not last on.
        self.assertNotIn("route_missing", artifacts(["institution_federation_unavailable"], False))

    def test_a_list_the_school_was_chosen_in_is_not_taken_for_one_without_it(self):
        d = PublisherBatchDownloader(CONFIG, profile=get_publisher_profile("science"), institution_query="红木兰大学")
        url = "https://www.science.org/action/authenticateSharedSP"
        result = DownloadResult(doi="10.1126/scitranslmed.aed4678", status="failed")
        result.events = [{"at": "15:22:10", "state": "auto_institution_search", "detail": f"Hong Mu-lan University @ {url}"},
                         {"at": "15:22:12", "state": "institution_selected", "detail": "Hong Mu-lan University (entityID)"}]
        page = Mock(url=url)
        page.evaluate.side_effect = AssertionError("nothing to read: the school was chosen here")
        self.assertFalse(d._search_lists_no_school(page, result, url, [(1, {"t": "Hong Mu-lan University Library"})]))
        self.assertFalse(getattr(result, "_institution_not_listed", False))

    def test_the_sites_line_naming_the_reader_s_school_is_no_entry(self):
        d = PublisherBatchDownloader(CONFIG, profile=get_publisher_profile("science"), institution_query="红木兰大学")
        page = Mock()
        page.evaluate.return_value = [{"t": "brought to you byHong Mu-lan University", "h": "", "ids": ""},
                                      {"t": "Access provided by Hong Mu-lan University", "h": "", "ids": ""},
                                      {"t": "Hong Mu-lan University", "h": "", "ids": "https://idp.example.edu.cn/idp/shibboleth"}]
        self.assertEqual([it["t"] for it in d._listed_entries(page)], ["Hong Mu-lan University"])


if __name__ == "__main__":
    unittest.main()
