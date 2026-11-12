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
        self.assertEqual(school, "https://idp.example.edu.cn/idp/shibboleth")
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


if __name__ == "__main__":
    unittest.main()
