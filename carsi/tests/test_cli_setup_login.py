"""setup / login CLI behaviour in a subprocess with an isolated data dir; no browser is opened."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHOOL_LIST = ROOT / "tests" / "fixtures" / "carsi_school_list.js"


def run_cli(data_dir: str, *args: str) -> tuple[int, str, str]:
    env = {**os.environ, "CARSI_DATA_DIR": data_dir, "PYTHONPATH": str(ROOT), "CARSI_PROGRESS_BAR": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "paper_search_carsi.cli", *args],
        capture_output=True, text=True, env=env, timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr


class SetupLoginCliTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="carsi-cli-")

    def test_setup_shows_settings_without_changing_anything(self):
        code, out, _ = run_cli(self.data_dir, "setup")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertFalse(payload["updated"])
        self.assertFalse(payload["settings"]["carsi_enabled"])
        self.assertEqual(payload["settings"]["data_dir"], self.data_dir)

    def use_school_list(self):
        # The data directory's copy of the CARSI member list; nothing is downloaded.
        shutil.copy(SCHOOL_LIST, Path(self.data_dir) / "carsi_school_list.js")

    def test_setup_carsi_enables_federation_and_optional_hint(self):
        self.use_school_list()
        code, out, _ = run_cli(self.data_dir, "setup", "--carsi", "--institution", "Example University")
        self.assertEqual(code, 0, out)
        settings = json.loads(out)["settings"]
        self.assertEqual(settings["federation"], "carsi")
        self.assertTrue(settings["carsi_enabled"])
        self.assertEqual(settings["carsi_institution_hint"], "示例大学")
        self.assertEqual(settings["carsi_institution_en"], "Example University")
        self.assertEqual(settings["idp_entity_id"], "https://idp.example.edu.cn/idp/shibboleth")

        code, out, _ = run_cli(self.data_dir, "config", "get", "publisher_institution_federation")
        self.assertEqual(json.loads(out)["publisher_institution_federation"], "carsi")

        code, out, _ = run_cli(self.data_dir, "setup", "--no-carsi")
        self.assertFalse(json.loads(out)["settings"]["carsi_enabled"])

    def test_setup_carsi_school_must_be_one_member_school(self):
        self.use_school_list()
        run_cli(self.data_dir, "setup", "--carsi", "--institution", "example.edu.cn")
        code, out, _ = run_cli(self.data_dir, "setup", "--institution", "示例")
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["error"], "carsi_school_ambiguous")
        self.assertEqual([c["name"] for c in payload["candidates"]], ["示例大学", "示例师范大学"])
        self.assertEqual(payload["candidates"][1]["entity_id"], "https://idp.example-normal.edu.cn/idp/shibboleth")
        code, out, _ = run_cli(self.data_dir, "setup", "--institution", "Nowhere Institute")
        self.assertEqual((code, json.loads(out)["error"]), (1, "carsi_school_not_found"))
        settings = json.loads(run_cli(self.data_dir, "setup")[1])["settings"]
        self.assertEqual(settings["carsi_institution_hint"], "示例大学")  # unchanged
        code, out, _ = run_cli(self.data_dir, "setup", "--institution", "https://idp.example-normal.edu.cn/idp/shibboleth")
        self.assertEqual(json.loads(out)["settings"]["carsi_institution_en"], "Example Normal University")

    def test_setup_lists_carsi_schools(self):
        self.use_school_list()
        code, out, _ = run_cli(self.data_dir, "setup", "--list-carsi-schools")
        self.assertEqual((code, json.loads(out)["count"]), (0, 3))
        code, out, _ = run_cli(self.data_dir, "setup", "--list-carsi-schools", "normal")
        self.assertEqual([s["name_en"] for s in json.loads(out)["schools"]], ["Example Normal University"])

    def test_check_asks_to_redo_a_school_saved_by_name_only(self):
        run_cli(self.data_dir, "setup", "--carsi")
        run_cli(self.data_dir, "config", "set", "carsi_idp_name", "示例大学")
        items = {c["item"]: c for c in json.loads(run_cli(self.data_dir, "setup", "--check")[1])["checks"]}
        self.assertEqual(items["carsi_school"]["status"], "missing")
        self.assertIn("setup --carsi --institution", items["carsi_school"]["detail"])
        self.use_school_list()
        run_cli(self.data_dir, "setup", "--institution", "示例大学")
        items = {c["item"]: c for c in json.loads(run_cli(self.data_dir, "setup", "--check")[1])["checks"]}
        self.assertEqual(items["carsi_school"]["status"], "ok")

    def test_without_carsi_the_name_is_saved_as_typed(self):
        self.use_school_list()
        run_cli(self.data_dir, "setup", "--carsi", "--institution", "Example University")
        code, out, _ = run_cli(self.data_dir, "setup", "--no-carsi", "--institution", "Overseas Institute")
        settings = json.loads(out)["settings"]
        self.assertEqual((code, settings["carsi_institution_hint"]), (0, "Overseas Institute"))
        self.assertEqual((settings["carsi_institution_en"], settings["idp_entity_id"]), ("", ""))

    def test_setup_carsi_works_without_a_school(self):
        code, out, _ = run_cli(self.data_dir, "setup", "--carsi")
        self.assertEqual(code, 0, out)
        settings = json.loads(out)["settings"]
        self.assertTrue(settings["carsi_enabled"])
        self.assertEqual(settings["carsi_institution_hint"], "")

    def test_campus_gateway_keys_left_in_an_old_config_enable_nothing(self):
        # WebVPN and EZProxy are not routes of this backend; an old config file may still name them.
        (Path(self.data_dir) / "config.json").write_text(json.dumps({
            "vpnsci_enabled": True, "vpnsci_school": "Fixture University", "vpnsci_base_url": "https://vpn.fixture.example",
            "ezproxy_enabled": True, "ezproxy_login_url": "https://ezproxy.fixture.example/login?url=",
        }))
        code, out, _ = run_cli(self.data_dir, "setup", "--check")
        self.assertIn(code, (0, 2))
        payload = json.loads(out)
        items = {c["item"]: c for c in payload["checks"]}
        self.assertEqual(items["institutional_route"]["status"], "missing")
        self.assertNotIn("webvpn_enabled", payload["settings"])

    def test_setup_check_reports_missing_route(self):
        code, out, _ = run_cli(self.data_dir, "setup", "--check")
        payload = json.loads(out)
        self.assertIn(code, (0, 2))
        items = {c["item"]: c for c in payload["checks"]}
        self.assertEqual(items["institutional_route"]["status"], "missing")
        self.assertIn("browser_backend", items)

    def test_setup_check_reports_chrome_and_warns_when_it_is_older_than_tested(self):
        import plistlib
        app = Path(self.data_dir) / "elsewhere" / "Google Chrome.app" / "Contents"
        program = app / "MacOS" / "Google Chrome"
        (app / "MacOS" / "155.0.7000.1").mkdir(parents=True)  # Windows keeps a version folder beside chrome.exe
        program.write_text("#!/bin/sh\necho 'Google Chrome 155.0.7000.1'\n")  # Linux asks --version
        program.chmod(0o755)
        with open(app / "Info.plist", "wb") as handle:  # macOS reads the bundle
            plistlib.dump({"CFBundleShortVersionString": "155.0.7000.1"}, handle)
        (Path(self.data_dir) / "config.json").write_text(json.dumps({"chrome_executable": str(program)}))
        code, out, _ = run_cli(self.data_dir, "setup", "--check")
        payload = json.loads(out)
        self.assertEqual(payload["browser"], {"browser": "Google Chrome", "path": str(program), "version": "155.0.7000.1",
                                              "tested": "156.0.8078.80", "outdated": True,
                                              "driver": payload["browser"]["driver"]})
        self.assertTrue(payload["browser"]["driver"].startswith("patchright "))
        self.assertIn("155.0.7000.1 低于测试过的 156.0.8078.80", payload["warnings"][0])
        items = {c["item"]: c for c in payload["checks"]}
        self.assertEqual(items["browser_backend"]["status"], "ok")
        self.assertIn(str(program), items["browser_backend"]["detail"])

    def test_login_asks_for_a_doi_then_for_the_school_before_any_browser(self):
        for setup in ((), ("setup", "--carsi")):
            if setup:
                run_cli(self.data_dir, *setup)
            with self.subTest(setup=setup):
                code, out, _ = run_cli(self.data_dir, "login")
                self.assertEqual(code, 2)
                payload = json.loads(out)
                self.assertEqual(payload["error"], "doi_required")
                self.assertIn("--doi", payload["hint"])
        run_cli(self.data_dir, "setup", "--no-carsi")
        code, out, _ = run_cli(self.data_dir, "login", "--doi", "10.1016/j.arth.2022.02.032")
        self.assertEqual((code, json.loads(out)["error"]), (2, "school_not_configured"))

    def test_login_takes_a_doi_only(self):
        # The cookie-capturing window (--kind custom, --publisher, --url) is gone (2026-11-09).
        for extra in (("--kind", "custom"), ("--publisher", "elsevier"), ("--url", "https://example.org")):
            code, _, err = run_cli(self.data_dir, "login", *extra)
            self.assertEqual(code, 2)
            self.assertIn("unrecognized arguments", err)

    def test_sensitive_values_are_masked(self):
        run_cli(self.data_dir, "config", "set", "elsevier_api_key", "secret-fixture-key")
        code, out, _ = run_cli(self.data_dir, "setup")
        self.assertNotIn("secret-fixture-key", out)
        code, out, _ = run_cli(self.data_dir, "config", "get", "elsevier_api_key")
        self.assertEqual(json.loads(out)["elsevier_api_key"], "***configured***")
        code, out, _ = run_cli(self.data_dir, "config", "list")
        self.assertNotIn("secret-fixture-key", out)


if __name__ == "__main__":
    unittest.main()
