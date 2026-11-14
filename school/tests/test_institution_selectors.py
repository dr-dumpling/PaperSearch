"""Institution selection is driven by the user's configured name; the package names no school."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE, PublisherProfile

SRC = Path(__file__).resolve().parents[1] / "paper_search_school"


def downloader(query="", config=None, profile=ELSEVIER_PROFILE):
    return PublisherBatchDownloader(config or {}, profile=profile, institution_query=query)


class NoBuiltinSchoolTests(unittest.TestCase):
    """Guard: no school name or campus IdP host is baked into rules or routes."""

    FORBIDDEN = re.compile(r"tsinghua|qinghua|清华|peking|pku\.edu|fudan\.edu", re.I)

    def test_builtin_profiles_name_no_school(self):
        for path in sorted((SRC / "publishers" / "builtin").glob("*.json")):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(self.FORBIDDEN.search(text), path.name)
            profile = json.loads(text)["profile"]
            for selector in profile.get("institution_result_selectors", []):
                self.assertTrue("{institution}" in selector or not re.search(r"[A-Z][a-z]+ University|大学", selector), selector)

    def test_engine_routes_and_data_name_no_school(self):
        files = list((SRC / "engine").glob("*.py"))
        files += [SRC / "carsi_schools.py", SRC / "cli.py", SRC / "config.py"]
        files += list((SRC / "data").glob("*.json"))
        for path in files:
            self.assertIsNone(self.FORBIDDEN.search(path.read_text(encoding="utf-8")), path.name)


class ResultSelectorTests(unittest.TestCase):
    def test_no_configured_institution_means_nothing_to_click(self):
        self.assertEqual(downloader("")._institution_result_selectors(), ())
        self.assertEqual(downloader("   ")._institution_result_selectors(), ())

    def test_selectors_follow_the_configured_name_and_its_english_name(self):
        config = {"school_name": "示例大学", "school_name_en": "Example University"}
        selectors = downloader("示例大学", config=config)._institution_result_selectors()
        self.assertIn("button:has-text('示例大学')", selectors)
        self.assertIn("button:has-text('Example University')", selectors)  # saved by setup from the CARSI list
        self.assertEqual(len(selectors), len(set(selectors)))
        # Another school being chosen does not borrow the configured school's English name.
        other = downloader("Other College", config=config)._institution_result_selectors()
        self.assertIn("li:has-text('Other College')", other)
        self.assertFalse(any("Example University" in s for s in other))
        self.assertFalse(any("Example" in s for s in downloader("示例大学")._institution_result_selectors()))

    def test_profile_templates_only_name_the_placeholder(self):
        profile = PublisherProfile(name="Fixture", article_url_template="https://doi.org/{doi}", pdf_url_templates=(),
                                   success_url_markers=(), auth_url_markers=(), auth_title_markers=(), sso_text_markers=(),
                                   institution_result_selectors=(".ui-menu-item:has-text('{institution}')", ".ui-menu-item:first-child"))
        selectors = downloader("O'Brien College", profile=profile)._institution_result_selectors()
        self.assertIn(".ui-menu-item:has-text('O\\'Brien College')", selectors)
        self.assertEqual(selectors[-1], ".ui-menu-item:first-child")
        self.assertEqual(downloader("", profile=profile)._institution_result_selectors(), ())


class IdpHostTests(unittest.TestCase):
    def test_generic_campus_idp_hosts_are_recognised_without_configuration(self):
        d = downloader("")
        for host in ("idp.example.edu.cn", "id.example.edu.cn", "ids.lzu.edu.cn", "sso.example.edu", "cas.example.edu.cn:8443"):
            self.assertTrue(d._is_idp_host(host), host)
        for host in ("www.sciencedirect.com", "login.openathens.net", "wayfinder.openathens.net", "idp.evil.example", ""):
            self.assertFalse(d._is_idp_host(host), host)

    def test_the_configured_entity_id_host_extends_the_match(self):
        host = "idp-lib.example.edu.cn"  # not a generic campus IdP name
        self.assertFalse(downloader("示例大学")._is_idp_host(host))
        d = downloader("示例大学", config={"idp_entity_id": f"https://{host}/idp/shibboleth"})
        self.assertTrue(d._is_idp_host(host))
        self.assertFalse(d._is_idp_host("www.example.com"))
        self.assertFalse(downloader("Example University")._is_idp_host("www.university.com"))


ENTITY = "https://idp.example.edu.cn/idp/shibboleth"


class EntityIdEntryTests(unittest.TestCase):
    """The entry carrying the configured entityID is the school; names are the fallback."""
    def setUp(self):
        # Fake pages are no verification pages (the school search skips those).
        patcher = patch.object(PublisherBatchDownloader, "_is_challenge_page", return_value=False)
        patcher.start(); self.addCleanup(patcher.stop)


    def test_entity_id_is_recognised_in_links_and_hidden_fields(self):
        carries = PublisherBatchDownloader._carries_entity_id
        elsevier = "%7B%22acctName%22%3A%22Example+University%22%2C%22entityId%22%3A%22https%3A%2F%2Fidp.example.edu.cn%2Fidp%2Fshibboleth%22%7D"
        for text in (f"/wayf?entityID={ENTITY}&x=1", elsevier, elsevier.replace("%", "%25"),
                     '{"entityId":"https:\\/\\/idp.example.edu.cn\\/idp\\/shibboleth"}'):
            self.assertTrue(carries(text, ENTITY), text)
        for text in (ENTITY + "2", ENTITY.replace("example", "other"), "https://idp.example.edu.cn/idp", ""):
            self.assertFalse(carries(text, ENTITY), text)
        self.assertFalse(carries(ENTITY, ""))

    def chooser(self, items, config=None):
        d = downloader("示例大学", config=config or {"school_name": "示例大学", "school_name_en": "Example University",
                                                    "idp_entity_id": ENTITY})
        page = Mock(); page.url = "https://id.elsevier.com/as/authorization"
        page.evaluate.side_effect = [items, True]
        return d, page

    def clicked_index(self, page):
        return page.evaluate.call_args_list[1].args[1][1]

    def test_the_entry_with_the_entity_id_beats_a_name_match(self):
        items = [{"i": 3, "t": "Example University", "h": "", "ids": "https://idp.other.edu.cn/idp/shibboleth"},
                 {"i": 7, "t": "示例大学(Example University) (Example University)", "h": "", "ids": f"x {ENTITY}"}]
        d, page = self.chooser(items)
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertTrue(d._click_unique_institution_entry(page, result, page.url))
        self.assertEqual(self.clicked_index(page), 7)
        self.assertIn("(entityID)", [e for e in result.events if e["state"] == "institution_selected"][0]["detail"])

    def test_two_entries_with_the_entity_id_are_one_school_but_two_names_tie(self):
        twins = [{"i": 1, "t": "Example University", "h": "", "ids": ENTITY},
                 {"i": 2, "t": "Example University", "h": "", "ids": ENTITY}]
        d, page = self.chooser(twins)
        self.assertTrue(d._click_unique_institution_entry(page, DownloadResult(doi="10.1/x", status="failed"), page.url))
        self.assertEqual(self.clicked_index(page), 1)
        d, page = self.chooser([dict(it, ids="") for it in twins])
        self.assertFalse(d._click_unique_institution_entry(page, DownloadResult(doi="10.1/x", status="failed"), page.url))

    def test_the_entry_gets_a_real_click_and_a_scripts_click_only_when_that_fails(self):
        from patchright.sync_api import TimeoutError as PlaywrightTimeout
        items = [{"i": 0, "t": "Example University", "h": "", "ids": ""}]
        d, page = self.chooser(items)
        self.assertTrue(d._click_unique_institution_entry(page, DownloadResult(doi="10.1/x", status="failed"), page.url))
        page.locator.assert_called_with("[data-paper-search-entry]")
        page.locator.return_value.first.click.assert_called_once_with(timeout=3_000)
        self.assertEqual(page.evaluate.call_count, 2)  # entries, then marking the entry
        d, page = self.chooser(items)
        page.evaluate.side_effect = [items, True, True]
        page.locator.return_value.first.click.side_effect = PlaywrightTimeout("Locator.click: Timeout 3000ms exceeded.")
        self.assertTrue(d._click_unique_institution_entry(page, DownloadResult(doi="10.1/x", status="failed"), page.url))
        self.assertIn("el.click()", page.evaluate.call_args.args[0])

    def test_without_an_entity_id_the_name_decides(self):
        items = [{"i": 3, "t": "Example University", "h": "", "ids": ENTITY},
                 {"i": 4, "t": "Example University Hospital", "h": "", "ids": ""}]
        d, page = self.chooser(items, config={"school_name": "示例大学", "school_name_en": "Example University"})
        self.assertTrue(d._click_unique_institution_entry(page, DownloadResult(doi="10.1/x", status="failed"), page.url))
        self.assertEqual(self.clicked_index(page), 3)

    def test_a_curly_apostrophe_in_the_school_name_matches_a_straight_one(self):
        d = downloader("示例大学", config={"school_name": "示例大学", "school_name_en": "Xi\u2019an Example University"})
        self.assertEqual(d._institution_match_score("Xi'an Example University"), 3)
        self.assertEqual(d._institution_match_score("XI\u2019AN EXAMPLE UNIVERSITY"), 3)

    def test_the_english_name_is_typed_with_a_straight_apostrophe(self):
        d = downloader("示例大学", config={"school_name": "示例大学", "school_name_en": "Xi\u2019an Example University"})
        d._click_unique_institution_entry = Mock(return_value=False)
        d._institution_search_selectors = lambda page: ("input#organisation",)
        page = Mock(); page.url = "https://id.example.org/organisation"
        page.evaluate.return_value = []
        page.locator.return_value.all.return_value = []
        box = Mock(); box.is_visible.return_value = True
        box.input_value.side_effect = ["", "Xi'an Example University"]  # before and after typing
        page.locator.side_effect = lambda selector: Mock(first=box, **{"all.return_value": []})
        self.assertFalse(d._assist_configured_institution(page, DownloadResult(doi="10.1/x", status="failed")))
        box.press_sequentially.assert_called_once_with("Xi'an Example University", delay=40)

    def test_keys_lost_while_the_search_loads_are_typed_again(self):
        d = downloader("Example University")
        d._click_unique_institution_entry = Mock(return_value=False)
        d._institution_search_selectors = lambda page: ("input#organisation",)
        page = Mock(); page.url = "https://wayf.example.org/search"
        box = Mock(); box.is_visible.return_value = True
        box.input_value.side_effect = ["", "ple University"]  # empty before typing, the tail after it
        page.locator.side_effect = lambda selector: Mock(first=box, **{"all.return_value": []})
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertFalse(d._assist_configured_institution(page, result))
        self.assertEqual(box.press_sequentially.call_count, 2)
        box.fill.assert_called_once_with("")
        self.assertIn("institution_search_retyped", [e["state"] for e in result.events])

    def test_unsuccessful_search_selection_is_not_proof_the_school_is_absent(self):
        d = downloader("Example University")
        d._click_unique_institution_entry = Mock(return_value=False)
        d._institution_search_selectors = lambda page: ("input#organisation",)
        page = Mock(); page.url = "https://wayf.example.org/search"
        box = Mock(); box.is_visible.return_value = True
        box.input_value.side_effect = ["", "Example University"]
        page.locator.side_effect = lambda selector: Mock(first=box, **{"all.return_value": []})
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertFalse(d._assist_configured_institution(page, result))
        self.assertFalse(getattr(result, "_institution_not_listed", False))
        self.assertIn("institution_list_not_ready", [e["state"] for e in result.events])

    def test_an_unreadable_search_box_does_not_stall_the_choice(self):
        from patchright.sync_api import TimeoutError as PlaywrightTimeout
        d = downloader("Example University")
        d._click_unique_institution_entry = Mock(side_effect=[False, True])
        d._institution_search_selectors = lambda page: ("input#organisation",)
        page = Mock(); page.url = "https://wayf.example.org/search"
        box = Mock(); box.is_visible.return_value = True
        box.input_value.side_effect = ["", PlaywrightTimeout("Timeout 2000ms exceeded.")]
        page.locator.side_effect = lambda selector: Mock(first=box, **{"all.return_value": []})
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertTrue(d._assist_configured_institution(page, result))
        self.assertEqual(box.input_value.call_args_list[-1].kwargs, {"timeout": 2_000})
        box.press_sequentially.assert_called_once()  # not typed again
        self.assertIn("auto_institution_search", [e["state"] for e in result.events])

    def test_dropdown_option_valued_with_the_entity_id_is_selected(self):
        d = downloader("示例大学", config={"school_name": "示例大学", "idp_entity_id": ENTITY})
        d._click_control = Mock()
        page = Mock(); page.url = "https://ds.carsi.edu.cn/discovery"
        select = {"i": 0, "name": "#idp", "shown": True, "disabled": False, "value": "",
                  "options": [["", "Choose"], ["https://idp.other.edu.cn/idp/shibboleth", "Other"], [ENTITY, "示例大学"]]}
        page.evaluate.side_effect = lambda script, *args: [select] if script == d._SELECTS_JS else "Continue"
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertTrue(d._select_from_institution_lists(page, result))
        # Chosen as the page's own script does, shown list or not (ACS, 2026-11-02).
        page.evaluate.assert_any_call(d._SET_SELECT_JS, [0, ENTITY])
        page.locator.return_value.first.select_option.assert_not_called()
        d._click_control.assert_called_once()

    def test_a_blank_overlay_left_over_the_chooser_is_closed(self):
        d = downloader("示例大学", config={"school_name": "示例大学", "idp_entity_id": ENTITY})
        page = Mock(); page.evaluate.return_value = "div#globalModalOverlay.modal-overlay.js-modal-overlay"
        result = DownloadResult(doi="10.1/x", status="failed")
        d._close_blank_overlay(page, result)
        page.evaluate.assert_called_once_with(d._BLANK_OVERLAY_JS)
        self.assertEqual(result.events[-1]["state"], "overlay_closed")
        page.evaluate.return_value = None
        d._close_blank_overlay(page, DownloadResult(doi="10.1/x", status="failed"))


class ElsevierAccessEntryTests(unittest.TestCase):
    def test_remembered_institution_entry_is_generic(self):
        d = downloader("")
        self.assertTrue(d.adapter.remembered_institution_entry("Purchase PDF\nAccess through Fixture University\n"))
        for text in ("Access through your institution", "Access through another organization", "access through your organisation:"):
            self.assertFalse(d.adapter.remembered_institution_entry(text), text)

    def test_configured_institution_must_match_the_entry(self):
        d = downloader("Fixture University")
        self.assertTrue(d.adapter.remembered_institution_entry("Access through Fixture University"))
        self.assertFalse(d.adapter.remembered_institution_entry("Access through Other University"))
        self.assertFalse(hasattr(downloader("Fixture University", profile=PublisherProfile(
            name="Wiley", article_url_template="https://doi.org/{doi}", pdf_url_templates=(), success_url_markers=(),
            auth_url_markers=(), auth_title_markers=(), sso_text_markers=())).adapter, "remembered_institution_entry"))


class OpenAthensWayfinderTests(unittest.TestCase):
    def page(self, url):
        page = Mock()
        page.url = url
        return page

    def test_without_configured_entity_id_the_user_picks(self):
        page = self.page("https://wayfinder.openathens.net/?return=https://connect.openathens.net/x")
        d = downloader("Example University")
        self.assertFalse(d._select_openathens_wayfinder(page, DownloadResult(doi="10.1/x", status="failed")))
        page.goto.assert_not_called()

    def test_configured_entity_id_is_the_only_identity_sent(self):
        page = self.page("https://wayfinder.openathens.net/?return=https://connect.openathens.net/x")
        d = downloader("Example University", config={"idp_entity_id": "https://idp.example.edu.cn/idp/shibboleth"})
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertTrue(d._select_openathens_wayfinder(page, result))
        target = page.goto.call_args.args[0]
        self.assertIn("entityID=https%3A%2F%2Fidp.example.edu.cn%2Fidp%2Fshibboleth", target)
        self.assertTrue(target.startswith("https://connect.openathens.net/x?"))
        for host in ("http://idp.example.edu.cn/idp/shibboleth", "idp.example.edu.cn"):
            page.goto.reset_mock()
            self.assertFalse(downloader("x", config={"idp_entity_id": host})._select_openathens_wayfinder(page, result))
            page.goto.assert_not_called()


class CarsiDiscoveryAssistTests(unittest.TestCase):
    def setUp(self):
        # Fake pages are no verification pages (the school search skips those).
        patcher = patch.object(PublisherBatchDownloader, "_is_challenge_page", return_value=False)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_publisher_pages_are_left_to_the_federation_step(self):
        d = downloader("Example University", config={"publisher_institution_federation": "carsi"})
        page = Mock(); page.url = "https://www.tandfonline.com/action/ssostart"
        self.assertFalse(d._assist_federation_discovery(page, DownloadResult(doi="10.1/x", status="failed")))
        page.locator.assert_not_called()

    def test_school_discovery_page_gets_the_configured_name_and_only_a_matching_click(self):
        d = downloader("Example University", config={"publisher_institution_federation": "carsi"})
        page = Mock(); page.url = "https://ds.carsi.edu.cn/ds/index.html"
        box = Mock(); box.is_visible.return_value = True; box.input_value.return_value = ""
        match = Mock(); match.is_visible.return_value = True
        miss = Mock(); miss.is_visible.return_value = False
        def locator(selector):
            loc = Mock()
            if selector == "#searchInstitution":
                loc.first = box
            elif "Example University" in selector:
                loc.first = match
            else:
                loc.first = miss
            return loc
        page.locator.side_effect = locator
        result = DownloadResult(doi="10.1/x", status="failed")
        with unittest.mock.patch("paper_search_school.engine.batch.time.sleep"):
            self.assertTrue(d._select_institution(page, result))
        box.fill.assert_called_once_with("Example University")
        match.click.assert_called_once()
        miss.click.assert_not_called()
        self.assertEqual([e["state"] for e in result.events if e["state"] == "institution_selected"], ["institution_selected"])

    def test_user_input_is_never_overwritten_and_empty_name_stays_manual(self):
        page = Mock(); page.url = "https://ds.carsi.edu.cn/ds/index.html"; page.frames = []
        box = Mock(); box.is_visible.return_value = True; box.input_value.return_value = "typed by user"
        page.locator.return_value.first = box
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertFalse(downloader("Example University", config={"publisher_institution_federation": "carsi"})._select_institution(page, result))
        box.fill.assert_not_called()
        self.assertFalse(downloader("", config={"publisher_institution_federation": "carsi"})._select_institution(page, result))
        box.fill.assert_not_called()
        box.press_sequentially.assert_not_called()
        box.click.assert_not_called()
        self.assertIn("institution_selection_required", [e["state"] for e in result.events])


class FederationListWithoutCarsiTests(unittest.TestCase):
    """A federation list that names no CARSI entry ends the login at once."""

    def lists(self, *lists):
        d = downloader("Example University", config={"publisher_institution_federation": "carsi"})
        d._page_selects = lambda page: list(lists)
        return d._federation_list_lacks_ours(Mock())

    def test_aacr_s_list_of_three_federations(self):
        # aacrjournals.org/institutional-login, 2026-11-02.
        aacr = {"i": 0, "name": "#FederationDropdown", "options": [
            ["", "--Select a Federation--"], ["1", "UK federation (United Kingdom)"],
            ["2", "InCommon (United States)"], ["3", "DFN-AAI (Germany)"]]}
        school = {"i": 1, "name": "#InstitutionDropdown", "options": [["", "Select Institution"]]}
        self.assertEqual(self.lists(aacr, school), "#FederationDropdown: UK federation (United Kingdom), "
                                                   "InCommon (United States), DFN-AAI (Germany)")

    def test_a_list_named_by_its_placeholder_or_with_school_or_a_school_list(self):
        placeholder = {"i": 0, "name": "select", "options": [
            ["", "Select your federation"], ["uk", "UK Access Management Federation"], ["us", "InCommon"]]}
        self.assertTrue(self.lists(placeholder))
        jama = {"i": 0, "name": "#ddlFederations", "options": [
            ["", "Select"], ["12", "InCommon"], ["49", "China CERNET Federation (CARSI)"]]}
        schools = {"i": 1, "name": "#ddlInstitutions", "options": [["", "Select"], ["a", "Other University"],
                                                                   ["b", "Another University"]]}
        self.assertEqual(self.lists(jama, schools), "")
        unfilled = {"i": 0, "name": "#federation", "options": [["", "Select your federation"], ["uk", "UK federation"]]}
        self.assertEqual(self.lists(unfilled), "")

    def test_a_link_list_the_browser_cannot_read_now_settles_nothing(self):
        from patchright._impl._errors import Error

        d = downloader("Example University", config={"publisher_institution_federation": "carsi"})
        d._page_selects = lambda page: []
        d._on_publisher_host = lambda url: True
        page = Mock(url="https://chooser.fixture-press.example/wayf")
        page.locator.return_value.first.is_visible.side_effect = Error("Locator.is_visible: value: expected boolean, got object")
        self.assertEqual(d._federation_list_lacks_ours(page), "")

    def test_only_in_school_mode(self):
        d = downloader("Example University", config={})
        d._page_selects = Mock()
        self.assertEqual(d._federation_list_lacks_ours(Mock()), "")
        d._page_selects.assert_not_called()


class LoginBlockReasonTests(unittest.TestCase):
    def blocked(self, url, text):
        d = downloader("Example University", config={"publisher_institution_federation": "carsi"})
        for name in ("_publisher_access_blocked", "_federation_list_lacks_ours", "_openathens_lacks_school",
                     "_is_challenge_page", "_institution_pdf_entitlement_missing"):
            setattr(d, name, lambda page: False)
        d._title = lambda page: "Error | OpenAthens"
        d._body_text = lambda page, limit=2000: text
        page = Mock(url=url); page.is_closed.return_value = False
        return d._login_block_reason(page)

    def test_an_organisation_that_restricts_the_resource_on_openathens_is_no_access(self):
        page_text = ("Access to this resource has been restricted by your organization "
                     "Error OA-AP-4032-01: Access denied The user has not been granted access to this resource.")
        url = "https://login.openathens.net/en-US/saml/2/sso/example.edu.cn/o/1/c/oafed?SAMLRequest=x"
        self.assertEqual(self.blocked(url, page_text), "institution_not_registered")
        self.assertEqual(self.blocked("https://www.example.org/help", page_text), "")
        self.assertEqual(self.blocked(url, "Find your institution"), "")


    def test_the_chinese_unsupported_request_page_means_the_school_has_not_enabled_the_publisher(self):
        idp = "https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO?execution=e1s1"
        said = "Web登陆服务 - 不支持的请求 您访问的应用未注册使用此服务"
        self.assertEqual(self.blocked(idp, said), "institution_not_registered")
        self.assertEqual(self.blocked("https://www.example.org/help", said), "")

    def test_a_chooser_that_says_the_chosen_school_has_no_access_is_no_access(self):
        wayf = "https://login.degruyterbrill.com/wayf/6aef3cf066b7ec87b9d125085d568e33"
        said = "Example University Example University does not have access to this resource"
        self.assertEqual(self.blocked(wayf, said), "institution_pdf_entitlement_missing")
        self.assertEqual(self.blocked(wayf, "Other University does not have access to this resource"), "")

    def test_a_locked_account_or_an_expired_password_ends_the_login(self):
        idp = "https://cas.example.edu.cn/cas/login?service=x"
        self.assertEqual(self.blocked(idp, "Web Login Service - Your account is locked."), "idp_account_locked")
        self.assertEqual(self.blocked(idp, "登录失败：您的账号已被锁定，请 30 分钟后再试"), "idp_account_locked")
        self.assertEqual(self.blocked(idp, "Your password has expired."), "idp_password_expired")
        # A help link names no state, and neither does a publisher page.
        self.assertEqual(self.blocked(idp, "账号被锁定怎么办？ 忘记密码"), "")
        self.assertEqual(self.blocked("https://www.example.org/help", "Your account is locked."), "")


class IdpConfirmationTests(unittest.TestCase):
    def test_the_user_is_asked_to_agree_on_the_idp_page(self):
        d = downloader("Example University", config={"publisher_institution_federation": "carsi"})
        d._body_text = lambda page, limit=2000: "Information Release"
        page = Mock(url="https://idp.example.edu.cn/idp/profile/SAML2/Redirect/SSO?execution=e1s2")
        page.evaluate.return_value = "attribute-release"
        self.assertEqual(d._idp_confirmation(page), "attribute-release")
        page.evaluate.return_value = ""
        d._body_text = lambda page, limit=2000: "Authentication with Duo is required for the requested service."
        self.assertEqual(d._idp_confirmation(page), "duo")
        page.url = "https://www.example.org/article"
        page.evaluate.return_value = "attribute-release"
        self.assertEqual(d._idp_confirmation(page), "")


class ChallengePageTests(unittest.TestCase):
    def challenge(self, url, title, text):
        d = downloader("Example University")
        d._challenge_shell = lambda page: False
        d._publisher_access_blocked = lambda page: False
        d._title = lambda page: title
        d._body_text = lambda page, limit=2000: text
        return d._is_challenge_page(Mock(url=url))

    def test_silverchairs_crawl_prevention_page_is_a_verification(self):
        governor = ("https://academic.oup.com/crawlprevention/governor?content=%2fnutritionreviews%2fadvance-article"
                    "%2fdoi%2f10.1093%2fnutrit%2fnuag155%2f8980887")
        said = ("We are sorry, but we are experiencing unusual traffic at this time. Please help us confirm that "
                "you are not a robot and we will take you to your content. Take me to my Content")
        self.assertTrue(self.challenge(governor, "Validate User", said))
        self.assertTrue(self.challenge("https://journal.example/article/1", "Validate User", said))
        article = "https://academic.oup.com/nutritionreviews/advance-article/doi/10.1093/nutrit/nuag155/8980887"
        self.assertFalse(self.challenge(article, "Nutrition Reviews", "Robot-assisted surgery: a review"))


class LeftPageTests(unittest.TestCase):
    def test_a_navigation_that_cuts_off_the_wait_has_left_the_page(self):
        from patchright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout
        page = Mock()
        page.wait_for_url.side_effect = PlaywrightError("net::ERR_ABORTED; maybe frame was detached?")
        self.assertTrue(PublisherBatchDownloader._left_page(page, "https://site.example/action/ssostart"))
        page.wait_for_url.side_effect = PlaywrightTimeout("Timeout 5000ms exceeded.")
        self.assertFalse(PublisherBatchDownloader._left_page(page, "https://site.example/action/ssostart"))
        page.wait_for_url.side_effect = KeyError("a program error")
        with self.assertRaises(KeyError):
            PublisherBatchDownloader._left_page(page, "https://site.example/action/ssostart")


class SeamlessAccessButtonTests(unittest.TestCase):
    URL = "https://publisher.example/institutional-login"

    def page(self, label="Access through\nyour institution", loaded=True):
        page = Mock(); page.url = self.URL
        page.frames = [Mock(url="https://publisher.example/"), *([Mock(url="https://service.seamlessaccess.org/ps/")] if loaded else [])]
        self.button = Mock(); self.button.is_visible.return_value = True; self.button.inner_text.return_value = label
        self.change = Mock(); self.change.is_visible.return_value = True
        page.locator.side_effect = lambda selector: Mock(first=self.button if "federated" in selector else self.change)
        return page

    def test_pressed_once_ready_and_once_more_when_nothing_happened(self):
        d = downloader("Example University")
        d._left_page = Mock(return_value=False)
        result = DownloadResult(doi="10.1/x", status="failed")
        self.assertFalse(d._open_seamlessaccess_chooser(self.page(loaded=False), result))
        self.button.click.assert_not_called()
        page = self.page()
        self.assertTrue(d._open_seamlessaccess_chooser(page, result))
        self.assertTrue(d._open_seamlessaccess_chooser(page, result))
        self.assertFalse(d._open_seamlessaccess_chooser(page, result))
        self.assertEqual(self.button.click.call_count, 2)
        self.change.click.assert_not_called()

    def test_seamlessaccess_discovery_is_a_federation_chooser(self):
        # AIP's SeamlessAccess button led there, and the school was typed by hand (2026-11-03).
        d = downloader("Example University")
        self.assertTrue(d._is_federation_chooser(
            "https://service.seamlessaccess.org/ds/?entityID=https%3A%2F%2Fsp.silverchair.com%2Faipp%2Fproduction%2Fshibboleth"))
        self.assertFalse(d._is_federation_chooser("https://service.seamlessaccess.org/cta/"))

    def test_the_newer_button_in_its_own_frame_is_pressed(self):
        # AIP's institutional login: SeamlessAccess's button in its /cta/ frame (2026-11-03).
        d = downloader("Example University")
        d._left_page = Mock(return_value=False)

        def page_with(label, frame=True):
            page = Mock(); page.url = self.URL
            hidden = Mock(); hidden.is_visible.return_value = False
            page.locator.return_value = Mock(first=hidden)
            cta = Mock(url="https://service.seamlessaccess.org/cta/")
            self.inner = Mock(); self.inner.is_visible.return_value = True; self.inner.inner_text.return_value = label
            self.change = Mock(); self.change.is_visible.return_value = True
            cta.locator.side_effect = lambda selector: Mock(first=self.change if selector == "#dsbutton" else self.inner)
            page.frames = [Mock(url=self.URL), *([cta] if frame else [])]
            return page

        self.assertTrue(d._open_seamlessaccess_chooser(page_with("Access through your institution"),
                                                       DownloadResult(doi="10.1/x", status="failed")))
        self.inner.click.assert_called_once()
        self.assertTrue(d._open_seamlessaccess_chooser(page_with("Access through Example University"),
                                                       DownloadResult(doi="10.1/x", status="failed")))
        self.inner.click.assert_called_once()  # the configured school, remembered there: pressed as it is
        self.assertTrue(d._open_seamlessaccess_chooser(page_with("Access through Other College"),
                                                       DownloadResult(doi="10.1/x", status="failed")))
        self.change.click.assert_called_once()
        self.inner.click.assert_not_called()
        self.assertFalse(d._open_seamlessaccess_chooser(page_with("Access through your institution", frame=False),
                                                        DownloadResult(doi="10.1/x", status="failed")))

    def test_another_remembered_school_is_changed_but_the_configured_one_is_left_to_its_own_step(self):
        d = downloader("Example University")
        page = self.page("Access through Other College")
        self.assertTrue(d._open_seamlessaccess_chooser(page, DownloadResult(doi="10.1/x", status="failed")))
        self.change.click.assert_called_once()
        self.button.click.assert_not_called()
        page = self.page("Access through Example University")
        self.assertFalse(d._open_seamlessaccess_chooser(page, DownloadResult(doi="10.1/x", status="failed")))
        self.change.click.assert_not_called()
        self.button.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
