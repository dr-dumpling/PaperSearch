"""没权限时换下一所学校 (school_switch.py; user, 2026-11-21): an article the school has no access to tried with the
next saved school, the default one first; a journal's school remembered for the rest of the task."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_search_school import orchestrator, school_switch

A = {"school_name": "甲大学", "idp_entity_id": "https://idp.a.example/idp"}
B = {"school_name": "乙大学", "idp_entity_id": "https://idp.b.example/idp"}
C = {"school_name": "丙大学", "idp_entity_id": "https://idp.c.example/idp"}
D = {"school_name": "丁大学", "idp_entity_id": "https://idp.d.example/idp"}
NO_ACCESS = {"success": False, "error_type": "paywall", "reason_code": "institution_pdf_entitlement_missing",
             "action": "review_entitlement"}


def config_with(current, *others):
    return {**current, "saved_schools": [current, *others]}


class WhoTakesPartTests(unittest.TestCase):
    def setUp(self):
        school_switch._GOT.clear()

    def test_the_default_school_then_each_one_pro_signs_in_with(self):
        accounts = {B["idp_entity_id"]: {"username": "u", "password": "p", "enabled": True},
                    C["idp_entity_id"]: {"username": "u", "password": "p", "enabled": False},  # auto sign-in off
                    D["idp_entity_id"]: {"username": "u", "password": "p", "enabled": True}}
        fills = {B["idp_entity_id"], C["idp_entity_id"]}  # D: one Pro does not fill in
        config = config_with(A, B, C, D, {"school_name": "戊大学", "idp_entity_id": "https://idp.e.example/idp"})  # no account
        with patch("paper_search_school.school_login.module", return_value=object()), \
                patch("paper_search_school.school_login.saved", side_effect=lambda c, entity: accounts.get(entity)), \
                patch("paper_search_school.school_login.fills_for", side_effect=lambda entity, pro=None: entity in fills):
            self.assertEqual([school_switch.name(s) for s in school_switch.schools(config)], ["甲大学", "乙大学"])
            self.assertTrue(school_switch.grouping(config))
            self.assertFalse(school_switch.grouping({**config, "school_switch": False}))
        with patch("paper_search_school.school_login.module", return_value=None):
            self.assertEqual(school_switch.schools(config), [])  # no Pro, no switching
            self.assertFalse(school_switch.grouping(config))

    def test_only_no_access_switches(self):
        self.assertTrue(school_switch.no_access(NO_ACCESS))
        for other in (None, {"success": True}, {**NO_ACCESS, "reason_code": "institution_login_failed"},
                      {"success": False, "error_type": "login_failed"}, {"success": False, "error_type": "access_blocked"}):
            with self.subTest(other=other):
                self.assertFalse(school_switch.no_access(other))
        self.assertTrue(school_switch.enabled({}))
        self.assertFalse(school_switch.enabled({"school_switch": False}))


class RememberedTests(unittest.TestCase):
    def setUp(self):
        school_switch._GOT.clear()

    def test_a_journals_school_for_the_rest_of_the_task_alone(self):
        task = ["batch-1"]
        with patch("paper_search_school.progress_reporter.batch_id", side_effect=lambda: task[0]), \
                patch.object(school_switch, "journal", side_effect=lambda doi: "issn:1234-5678" if "j1" in doi else "issn:9999-0000"), \
                patch.object(school_switch, "schools", return_value=[A, B, C]):
            with patch.object(school_switch, "schools", return_value=[A]):
                self.assertEqual(school_switch.order_for({}, "10.1/j1.1"), [A])  # one school: no journal looked up
            self.assertEqual(school_switch.journal.call_count, 0)
            self.assertEqual(school_switch.order_for({}, "10.1/j1.1"), [A, B, C])
            school_switch.remember("10.1/j1.1", B["idp_entity_id"])
            self.assertEqual(school_switch.order_for({}, "10.1/j1.2"), [B, A, C])  # its journal's school first
            self.assertEqual(school_switch.order_for({}, "10.1/j2.1"), [A, B, C])  # another journal: the default first
            task[0] = "batch-2"
            self.assertEqual(school_switch.order_for({}, "10.1/j1.3"), [A, B, C])  # another task starts again
            task[0] = ""
            school_switch.remember("10.1/j1.4", C["idp_entity_id"])
            self.assertEqual(school_switch.remembered("10.1/j1.4"), "")  # a download on its own: nothing kept


class DownloadTests(unittest.TestCase):
    """orchestrator._download_impl going down the schools."""

    def run_download(self, answers, turns, *, busy_at=None, config=None):
        folder = Path(tempfile.mkdtemp())
        config = {"output_dir": str(folder), **A, **(config or {})}
        tried, phases, remembered, closed = [], [], [], []
        answers = iter(answers)

        def fetched(doi, output_path, config):
            tried.append(config["school_name"])
            answer = next(answers)
            if answer.get("success"):
                Path(output_path).write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
                return {**answer, "file": str(output_path)}
            return dict(answer)

        signs = []

        def signed(config, always=False):
            signs.append(config["school_name"])
            return "busy" if busy_at is not None and len(signs) == busy_at else ""

        with patch("paper_search_school.cold_start.before_sign_in", side_effect=signed), \
                patch.object(orchestrator, "load_config", side_effect=lambda: dict(config)), \
                patch.object(orchestrator, "cache_get", return_value=None), patch.object(orchestrator, "cache_set"), \
                patch.object(orchestrator, "try_institutional", side_effect=fetched), \
                patch.object(orchestrator, "is_pdf_file", return_value=True), \
                patch.object(school_switch, "order_for", return_value=turns), \
                patch.object(school_switch, "remember", side_effect=lambda doi, entity: remembered.append(entity)), \
                patch("paper_search_school.progress_reporter.update", side_effect=lambda **kw: phases.append(kw.get("phase"))), \
                patch("paper_search_school.browser.batch_session.active_batch",
                      SimpleNamespace(get=lambda: SimpleNamespace(close=lambda: closed.append(True)))):
            result = orchestrator.download_institutional("10.1000/test", folder)
        return result, tried, phases, remembered, closed

    def test_no_access_then_the_next_school_and_the_results_say_which(self):
        result, tried, phases, remembered, closed = self.run_download([NO_ACCESS, {"success": True, "source": "institutional"}], [A, B, C])
        self.assertTrue(result["success"])
        self.assertEqual(tried, ["甲大学", "乙大学"])
        self.assertEqual(phases, ["没权限，换乙大学"])
        self.assertEqual(closed, [True])  # the batch's browser let go of the last school's sign-in
        self.assertEqual(remembered, [B["idp_entity_id"]])
        self.assertEqual(result["school"], "乙大学")

    def test_the_default_school_that_got_it_said_by_no_name(self):
        result, tried, phases, remembered, _ = self.run_download([{"success": True}], [A, B])
        self.assertEqual((tried, phases, remembered), (["甲大学"], [], [A["idp_entity_id"]]))
        self.assertNotIn("school", result)

    def test_a_journals_school_first_named_though_tried_first(self):
        # Its journal's school of this task first: not the default one, so the results say whose.
        result, tried, *_ = self.run_download([{"success": True}], [B, A])
        self.assertEqual((tried, result.get("school")), (["乙大学"], "乙大学"))

    def test_none_with_access_says_how_many_were_tried(self):
        result, tried, phases, remembered, _ = self.run_download([NO_ACCESS, NO_ACCESS, NO_ACCESS], [A, B, C])
        self.assertFalse(result["success"])
        self.assertEqual(tried, ["甲大学", "乙大学", "丙大学"])
        self.assertEqual(phases, ["没权限，换乙大学", "没权限，换丙大学"])
        self.assertEqual((result["schools_tried"], remembered), (3, []))

    def test_a_sign_in_that_failed_is_not_another_accounts(self):
        failed = {"success": False, "error_type": "login_failed", "action": "login_required"}
        result, tried, phases, *_ = self.run_download([failed], [A, B])
        self.assertEqual((tried, phases, result.get("schools_tried")), (["甲大学"], [], None))

    def test_one_school_alone_when_the_switch_is_off(self):
        result, tried, *_ = self.run_download([NO_ACCESS], [], config={"school_switch": False})
        self.assertEqual((tried, result.get("schools_tried")), (["甲大学"], None))

    def test_a_browser_that_keeps_the_last_sign_in_ends_the_turns(self):
        # The second before_sign_in (the switch to 乙) finds the profile still in use: 乙 is not tried with 甲's session.
        result, tried, phases, *_ = self.run_download([NO_ACCESS], [A, B, C], busy_at=2)
        self.assertEqual((tried, phases), (["甲大学"], ["没权限，换乙大学"]))
        self.assertFalse(result["success"])
        self.assertNotIn("schools_tried", result)


if __name__ == "__main__":
    unittest.main()
