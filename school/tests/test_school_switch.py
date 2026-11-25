"""没权限时换下一所学校 (school_switch.py; user, 2026-11-21): a paper the school has no access to (没权限) tried with the
next saved school, the default one first; at once for a download on its own, at its end for a batch's papers (user,
2026-11-22), where a paper is tried with the one school it is given."""
import json
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
            # The batch asks for them by name and entityID (server.school_switch_state), none while the switch is off.
            from paper_search_school import server
            with patch.object(server, "load_config", return_value=config):
                self.assertEqual(json.loads(server.school_switch_state()), {"on": True, "schools": [
                    {"name": "甲大学", "entity_id": A["idp_entity_id"]}, {"name": "乙大学", "entity_id": B["idp_entity_id"]}],
                    "group": True, "retry": False})
            with patch.object(server, "load_config", return_value={**config, "school_switch": False}):
                self.assertEqual(json.loads(server.school_switch_state()), {"on": False, "schools": [], "group": False, "retry": False})
            # 失败后自动重试 (user, 2026-11-24): off unless turned on, whatever the school switch.
            with patch.object(server, "load_config", return_value={**config, "school_switch": False, "batch_retry_failed": True}):
                self.assertIs(json.loads(server.school_switch_state())["retry"], True)
        with patch("paper_search_school.school_login.module", return_value=None):
            self.assertEqual(school_switch.schools(config), [])  # no Pro, no switching
            self.assertFalse(school_switch.grouping(config))

    def test_every_no_access_switches_and_nothing_else(self):
        self.assertTrue(school_switch.no_access(NO_ACCESS))
        # Every failure under 没权限 (user, 2026-11-22): the school's sign-in not enabled for the publisher (IEEE, AHA's
        # OpenAthens), no route for it there, or the user's mark, made with the default school.
        for code in ("institution_not_registered", "institution_federation_unavailable", "no_entitlement"):
            with self.subTest(code=code):
                self.assertTrue(school_switch.no_access({"success": False, "error_type": code}))
        for other in (None, {"success": True}, {**NO_ACCESS, "reason_code": "institution_login_failed"},
                      {"success": False, "error_type": "login_failed"}, {"success": False, "error_type": "access_blocked"}):
            with self.subTest(other=other):
                self.assertFalse(school_switch.no_access(other))
        self.assertTrue(school_switch.enabled({}))
        self.assertFalse(school_switch.enabled({"school_switch": False}))


class DownloadTests(unittest.TestCase):
    """orchestrator._download_impl going down the schools."""

    def run_download(self, answers, turns, *, busy_at=None, config=None, last="", batch="", school=None):
        folder = Path(tempfile.mkdtemp())
        config = {"output_dir": str(folder), **A, "saved_schools": [A, B, C], **(config or {})}
        tried, phases, closed = [], [], []
        self.marks_off = []
        answers = iter(answers)

        self.entry_turns = []

        def fetched(doi, output_path, config):
            tried.append(config["school_name"])
            self.entry_turns.append(config.get("institution_entry_turn", 0))
            self.marks_off.append(bool(config.get(school_switch.MARKS_OFF)))
            answer = next(answers)
            if answer.get("success"):
                Path(output_path).write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
                return {**answer, "file": str(output_path)}
            return dict(answer)

        signs = self.signs = []

        def signed(config, always=False):
            signs.append(config["school_name"])
            return "busy" if busy_at is not None and len(signs) == busy_at else ""

        with patch("paper_search_school.cold_start.before_sign_in", side_effect=signed), \
                patch("paper_search_school.cold_start.signed_in_school", return_value=last), \
                patch("paper_search_school.progress_reporter.batch_id", return_value=batch), \
                patch.object(orchestrator, "load_config", side_effect=lambda: dict(config)), \
                patch.object(orchestrator, "cache_get", return_value=None), patch.object(orchestrator, "cache_set"), \
                patch.object(orchestrator, "try_institutional", side_effect=fetched), \
                patch.object(orchestrator, "is_pdf_file", return_value=True), \
                patch.object(school_switch, "schools", return_value=turns), \
                patch("paper_search_school.progress_reporter.update", side_effect=lambda **kw: phases.append(kw.get("phase"))), \
                patch("paper_search_school.browser.batch_session.active_batch",
                      SimpleNamespace(get=lambda: SimpleNamespace(close=lambda: closed.append(True)))):
            result = orchestrator.download_institutional("10.1000/test", folder, **({"school": school} if school else {}))
        return result, tried, phases, closed

    def test_no_access_then_the_next_school_and_the_results_say_which(self):
        result, tried, phases, closed = self.run_download([NO_ACCESS, {"success": True, "source": "institutional"}], [A, B, C])
        self.assertTrue(result["success"])
        self.assertEqual(tried, ["甲大学", "乙大学"])
        self.assertEqual(phases, ["没权限，换乙大学"])
        self.assertEqual(closed, [True])  # the batch's browser let go of the last school's sign-in
        self.assertEqual(result["school"], "乙大学")
        self.assertEqual(self.marks_off, [False, True])  # the user's marks, made with the default school, not for 乙

    def test_the_default_school_that_got_it_said_by_no_name(self):
        result, tried, phases, _ = self.run_download([{"success": True}], [A, B])
        self.assertEqual((tried, phases), (["甲大学"], []))
        self.assertNotIn("school", result)

    def test_a_school_whose_sign_in_the_publisher_does_not_take_is_followed_by_the_next(self):
        refused = {"success": False, "error_type": "institution_not_registered", "action": "review_browser"}
        result, tried, phases, _ = self.run_download([refused, {"success": True, "source": "institutional"}], [A, B])
        self.assertEqual((result["success"], tried, phases, result["school"]), (True, ["甲大学", "乙大学"], ["没权限，换乙大学"], "乙大学"))

    def test_a_batchs_paper_stays_with_its_school(self):
        # A batch switches once at its end for all its papers without access (user, 2026-11-22): not here.
        result, tried, phases, closed = self.run_download([NO_ACCESS], [A, B], batch="batch-1")
        self.assertEqual((tried, phases, closed, result.get("schools_tried")), (["甲大学"], [], [], None))

    def test_the_school_a_batch_names_is_said_and_the_users_marks_do_not_skip_it(self):
        # The batch's end: its papers without access with the next school, named for each.
        result, tried, phases, _ = self.run_download([{"success": True}], [A, B], batch="batch-1", school=B["idp_entity_id"])
        self.assertEqual((tried, phases, result["school"], self.marks_off), (["乙大学"], [], "乙大学", [True]))
        # The default school named: no name said, its marks stand.
        result, tried, *_ = self.run_download([{"success": True}], [A, B], batch="batch-1", school=A["idp_entity_id"])
        self.assertEqual((tried, "school" in result, self.marks_off), (["甲大学"], False, [False]))

    def test_the_schools_entries_by_one_name_one_after_another(self):
        # JAMA, Windows 2026-11-22: a test school's name two or three times in its search; the first (its library's proxy)
        # waited on a picture code. The next entry, with the same school, before any other school.
        waited = {"success": False, "error_type": "login_timeout", "action": "review_browser", "same_name_entries": 3}
        result, tried, phases, closed = self.run_download([waited, {"success": True}], [A, B])
        self.assertTrue(result["success"])
        self.assertEqual((tried, self.entry_turns, phases), (["甲大学", "甲大学"], [0, 1], []))
        self.assertNotIn("school", result)
        # All three did not do: then the next school, from its first entry.
        refused = {**NO_ACCESS, "same_name_entries": 3}
        result, tried, phases, _ = self.run_download([refused, refused, refused, {"success": True}], [A, B])
        self.assertEqual((tried, self.entry_turns), (["甲大学"] * 3 + ["乙大学"], [0, 1, 2, 0]))
        self.assertEqual(result["school"], "乙大学")
        # One entry, or a failure that is not the entry's (a blocked site): not tried again.
        for answer in ({**NO_ACCESS, "same_name_entries": 1},
                       {"success": False, "error_type": "access_blocked", "same_name_entries": 2}):
            with self.subTest(answer=answer):
                result, tried, *_ = self.run_download([answer], [A])
                self.assertEqual(tried, ["甲大学"])

    def test_none_with_access_says_how_many_were_tried(self):
        result, tried, phases, _ = self.run_download([NO_ACCESS, NO_ACCESS, NO_ACCESS], [A, B, C])
        self.assertFalse(result["success"])
        self.assertEqual(tried, ["甲大学", "乙大学", "丙大学"])
        self.assertEqual(phases, ["没权限，换乙大学", "没权限，换丙大学"])
        self.assertEqual(result["schools_tried"], 3)

    def test_a_sign_in_that_failed_is_not_another_accounts(self):
        failed = {"success": False, "error_type": "login_failed", "action": "login_required"}
        result, tried, phases, _ = self.run_download([failed], [A, B])
        self.assertEqual((tried, phases, result.get("schools_tried")), (["甲大学"], [], None))

    def test_one_school_alone_when_the_switch_is_off(self):
        result, tried, *_ = self.run_download([NO_ACCESS], [], config={"school_switch": False})
        self.assertEqual((tried, result.get("schools_tried")), (["甲大学"], None))

    def test_the_default_school_after_another_schools_article_forgets_that_sign_in(self):
        # Windows, 2026-11-22: the article after one the second school got (Wiley) went back to the default school, but the batch's
        # browser, still open, kept the second school's sign-in, each article waiting 10 s for the profile. It is closed first.
        result, tried, phases, closed = self.run_download([{"success": True}], [A, B], last=B["idp_entity_id"])
        self.assertTrue(result["success"])
        self.assertEqual((tried, phases, closed, self.signs), (["甲大学"], [], [True], ["甲大学"]))
        # The same school's browser stays open.
        *_, closed = self.run_download([{"success": True}], [A, B], last=A["idp_entity_id"])
        self.assertEqual(closed, [])

    def test_a_browser_that_keeps_the_last_sign_in_ends_the_turns(self):
        # The second before_sign_in (the switch to 乙) finds the profile still in use: 乙 is not tried with 甲's session.
        result, tried, phases, _ = self.run_download([NO_ACCESS], [A, B, C], busy_at=2)
        self.assertEqual((tried, phases), (["甲大学"], ["没权限，换乙大学"]))
        self.assertFalse(result["success"])
        self.assertNotIn("schools_tried", result)


if __name__ == "__main__":
    unittest.main()
