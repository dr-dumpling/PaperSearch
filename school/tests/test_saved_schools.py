"""Several saved schools, one the current one (user, 2026-11-17): setup keeps the school before
it, `use` switches, `forget` removes, `schools` lists; a download may use another saved school
for itself alone; nothing switches on its own."""
from __future__ import annotations

import json
import tempfile
import unittest

import shutil
from pathlib import Path

from paper_search_school.schools import saved as saved_schools
from paper_search_school.report_sanitizer import Redactor
from tests.test_cli_setup_login import SCHOOL_LIST, run_cli


def school(name: str, name_en: str, entity: str) -> dict:
    return {"school_name": name, "school_name_en": name_en, "school_entry_name": "", "idp_entity_id": entity,
            "idp_login_hosts": [], "idp_login_pages": [], "idp_domains": [entity.split("/")[2].split(".", 1)[1]],
            "publisher_institution_federation": "carsi", "carsi_enabled": True}


RED = school("红木兰大学", "Red Magnolia University", "https://idp.redmagnolia.edu.cn/idp/shibboleth")
HERON = school("灰鹭学院", "Grey Heron College", "https://idp.greyheron.edu.cn/idp/shibboleth")


class SavedSchoolsTests(unittest.TestCase):
    def config(self) -> dict:
        return {**RED, "saved_schools": [HERON], "elsevier_api_key": "secret-api-key-123"}

    def test_the_current_school_is_saved_beside_the_others_once(self):
        cfg = self.config()
        saved_schools.remember(cfg)
        saved_schools.remember(cfg)
        self.assertEqual([s["school_name"] for s in saved_schools.saved(cfg)], ["灰鹭学院", "红木兰大学"])
        self.assertEqual([s["name"] for s in [saved_schools.summary(e, cfg) for e in saved_schools.saved(cfg)] if s["current"]],
                         ["红木兰大学"])

    def test_found_by_name_english_name_domain_or_entity_id_else_a_part_of_a_name(self):
        cfg = self.config()
        for query in ("灰鹭学院", "grey heron college", "greyheron.edu.cn", "https://idp.greyheron.edu.cn/idp/shibboleth", "Heron"):
            self.assertEqual([s["school_name"] for s in saved_schools.find(cfg, query)], ["灰鹭学院"], query)
        self.assertEqual(len(saved_schools.find(cfg, "edu.cn")), 2)
        self.assertEqual(saved_schools.find(cfg, "Nowhere"), [])

    def test_a_download_uses_another_saved_school_for_itself_alone(self):
        cfg = self.config()
        self.assertEqual(saved_schools.use_for_download(cfg, "Grey Heron College"), "")
        self.assertEqual((cfg["school_name"], cfg["idp_entity_id"]), ("灰鹭学院", HERON["idp_entity_id"]))
        self.assertEqual(saved_schools.use_for_download(self.config(), "Nowhere"), "school_not_saved")
        self.assertEqual(saved_schools.use_for_download(self.config(), "edu.cn"), "school_ambiguous")

    def test_the_current_school_is_not_forgotten(self):
        cfg = self.config()
        saved_schools.remember(cfg)
        self.assertFalse(saved_schools.forget(cfg, RED))
        self.assertTrue(saved_schools.forget(cfg, HERON))
        self.assertEqual([s["school_name"] for s in saved_schools.saved(cfg)], ["红木兰大学"])

    def test_reports_leave_out_every_saved_schools_names(self):
        redactor = Redactor(self.config())
        for name in ("红木兰大学", "Grey Heron College", "灰鹭学院", "greyheron.edu.cn"):
            self.assertIn(name, redactor.terms)
        self.assertIn("idp.greyheron.edu.cn", redactor.school_hosts)
        self.assertIn("secret-api-key-123", redactor.secrets)


class SavedSchoolsCliTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="school-saved-")
        shutil.copy(SCHOOL_LIST, Path(self.data_dir) / "carsi_school_list.js")

    def cli(self, *args: str) -> tuple[int, dict]:
        code, out, _ = run_cli(self.data_dir, *args)
        return code, json.loads(out)

    def test_setup_keeps_the_school_before_and_use_switches_between_them(self):
        self.cli("setup", "--carsi", "--institution", "Example Normal University")
        code, out = self.cli("setup", "--carsi", "--institution", "Example University")
        self.assertEqual((code, out["settings"]["school_name"], out["settings"]["saved_schools"]),
                         (0, "示例大学", ["示例师范大学", "示例大学"]))
        code, out = self.cli("schools")
        self.assertEqual([(s["name"], s["current"]) for s in out["schools"]], [("示例师范大学", False), ("示例大学", True)])
        code, out = self.cli("use", "Example Normal University")
        self.assertEqual((code, out["switched"], out["added"], out["school"]["name"]), (0, True, False, "示例师范大学"))
        self.assertEqual(self.cli("setup")[1]["settings"]["idp_entity_id"], "https://idp.example-normal.edu.cn/idp/shibboleth")
        # The current one stays; another goes.
        code, out = self.cli("forget", "示例师范")
        self.assertEqual((code, out["error"]), (1, "school_is_current"))
        code, out = self.cli("forget", "Example University")
        self.assertEqual((code, [s["name"] for s in out["schools"]]), (0, ["示例师范大学"]))
        code, out = self.cli("use", "示例")
        self.assertEqual(code, 0)  # the one saved school left


if __name__ == "__main__":
    unittest.main()
