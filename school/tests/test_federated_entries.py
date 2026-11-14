"""Institution entries observed on Karger, ACS, APS, Optica, Thieme and SAGE; all requests are intercepted."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from paper_search_school.engine.batch import DownloadResult, PublisherBatchDownloader
from paper_search_school.publishers.profiles import get_publisher_profile


def school_list(options, name="#InstitutionDropdown", i=1, **state):
    return {"i": i, "name": name, "shown": True, "disabled": False, "value": "", "options": options, **state}


class SchoolNameTests(unittest.TestCase):
    def test_federation_list_labels_match_the_configured_school(self):
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("acs"), institution_query="Example University")
        options = [["", "Select"], ["https://idp.a.example/idp/shibboleth", "EXAMPLE (CITY) UNIV"],
                   ["https://idp.b.example/idp/shibboleth", "EXAMPLE NORMAL UNIV"]]
        self.assertEqual(d._school_option([school_list(options)])[1:], ("https://idp.a.example/idp/shibboleth",
                                                                      "EXAMPLE (CITY) UNIV", "name"))
        self.assertIsNone(d._school_option([school_list(options[:1] + options[2:])]))
        self.assertIsNone(d._school_option([school_list(options + [["https://idp.c.example/x", "Example University"]])]))

    def test_configured_entity_id_wins(self):
        d = PublisherBatchDownloader({"idp_entity_id": "https://idp.b.example/idp/shibboleth"},
                                     profile=get_publisher_profile("acs"), institution_query="Example University")
        options = [["https://idp.a.example/idp/shibboleth", "EXAMPLE UNIV"],
                   ["https://idp.b.example/idp/shibboleth", "EXAMPLE NORMAL UNIV"]]
        self.assertEqual(d._school_option([school_list(options)])[2:], ("EXAMPLE NORMAL UNIV", "entityID"))

    def test_labels_carrying_their_address_and_chinese_names_match(self):
        d = PublisherBatchDownloader({"school_name": "示例大学", "school_name_en": "Example University"},
                                     profile=get_publisher_profile("acs"), institution_query="示例大学")
        self.assertEqual(d._canonical_school_name("EXAMPLE (CITY) UNIV | https://idp.example.edu.cn/idp/shibboleth"),
                         d._canonical_school_name("Example University"))
        self.assertEqual(d._canonical_school_name("Example University, Library"), d._canonical_school_name("Example University"))
        self.assertEqual(d._school_option([school_list([["", "Select"], ["x", "示例大学"]])])[1], "x")
        self.assertEqual(d._school_option([school_list([["", "Select"], ["y", "Example University (CARSI)"]])])[1], "y")
        self.assertIsNone(d._school_option([school_list([["", "Select"], ["z", "示例大学附属医院"]])]))

    def test_the_entity_id_comes_from_the_school_list_without_a_configured_one(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        fixture = Path(__file__).resolve().parent / "fixtures" / "carsi_school_list.js"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "carsi_school_list.js").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
            with patch("paper_search_school.config.DATA_DIR", Path(tmp)):
                d = PublisherBatchDownloader({"school_name": "示例大学"}, profile=get_publisher_profile("acs"),
                                             institution_query="示例大学")
                self.assertEqual(d._entity_id(), "https://idp.example.edu.cn/idp/shibboleth")
                self.assertEqual(PublisherBatchDownloader({"school_name": "不存在大学"})._entity_id(), "")
            self.assertEqual(PublisherBatchDownloader({"idp_entity_id": "https://idp.x.example/idp/shibboleth",
                                                       "school_name": "示例大学"})._entity_id(),
                             "https://idp.x.example/idp/shibboleth")


class InstitutionListRuleTests(unittest.TestCase):
    """The rule on mocked lists: federation, then the school, then the list's submit."""
    ENTITY = "https://idp.a.example/idp/shibboleth"
    FEDERATION = [["", "Select"], ["3", "Open Athens"], ["11", "China CERNET Federation (CARSI)"]]
    SCHOOLS = [["", "Select"], [ENTITY, "EXAMPLE (CITY) UNIV"], ["https://idp.b.example/idp/shibboleth", "OTHER UNIV"]]

    def setUp(self):
        self.d = PublisherBatchDownloader({"publisher_institution_federation": "carsi", "idp_entity_id": self.ENTITY},
                                          profile=get_publisher_profile("acs"), institution_query="Example University")
        self.d.LIST_WAIT_SEC = 1
        self.d._set_select = Mock()
        self.d._click_control = Mock()
        self.d._close_blank_overlay = Mock()
        self.page = Mock(url="https://pubs.acs.org/institutional-login?returnUrl=x")
        self.page.evaluate.return_value = "Access through Institution"  # the list's submit control
        self.result = DownloadResult(doi="10.1021/x", status="failed")

    def test_school_then_the_school_by_entity_id_then_submit(self):
        federation = school_list(self.FEDERATION, "#FederationDropdown", 0)
        empty, filled = school_list([["", "Select"]]), school_list(self.SCHOOLS, disabled=True)  # left disabled (ACS)
        self.d._page_selects = Mock(side_effect=[[federation, empty], [federation, empty], [federation, filled]])
        self.assertTrue(self.d._select_from_institution_lists(self.page, self.result))
        self.assertEqual([c.args[1:] for c in self.d._set_select.call_args_list],
                         [(federation, "11"), (filled, self.ENTITY)])
        self.d._click_control.assert_called_once()
        self.assertEqual([e["state"] for e in self.result.events],
                         ["institution_federation_selected", "institution_selected", "institution_list_submitted"])
        self.assertEqual(self.result.events[1]["detail"], "EXAMPLE (CITY) UNIV (entityID, #InstitutionDropdown)")
        # Once per page.
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))

    def test_a_filled_list_without_the_school_ends_the_login(self):
        self.d.config["idp_entity_id"] = "https://idp.c.example/idp/shibboleth"
        self.d.institution_query = "Third University"
        federation = school_list(self.FEDERATION, "#FederationDropdown", 0, value="11")
        self.d._page_selects = Mock(return_value=[federation, school_list(self.SCHOOLS)])
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertTrue(self.result._institution_not_listed)
        self.assertEqual(self.result.events[-1]["state"], "auto_institution_not_found")
        self.d._set_select.assert_not_called()

    def test_a_list_still_loading_waits_for_the_next_pass(self):
        federation = school_list(self.FEDERATION, "#FederationDropdown", 0, value="11")
        self.d._page_selects = Mock(return_value=[federation, school_list([["", "Select"]], disabled=True)])
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertFalse(getattr(self.result, "_institution_not_listed", False))
        self.assertEqual(self.result.events[-1], {**self.result.events[-1], "state": "institution_list_not_ready",
                                                  "detail": f"1 options @ {self.page.url}"})

    def test_a_header_journal_search_is_not_evidence_that_the_school_is_missing(self):
        federation = school_list(self.FEDERATION, "#FederationDropdown", 0, value="11")
        header = school_list([["all", "Search All"], ["j1", "Journal One"], ["j2", "Journal Two"]],
                             "#HeaderSearch", 2)
        self.d._page_selects = Mock(return_value=[header, federation, school_list([["", "Select"]])])
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertFalse(getattr(self.result, "_institution_not_listed", False))
        self.assertEqual(self.result.events[-1]["state"], "institution_list_not_ready")

    def test_a_generic_list_of_other_universities_still_confirms_the_school_is_missing(self):
        federation = school_list(self.FEDERATION, "#FederationDropdown", 0, value="11")
        self.d._page_selects = Mock(return_value=[federation, school_list(
            [["", "Select"], ["other", "Other University"]], "#results")])
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertTrue(self.result._institution_not_listed)

    def test_a_reload_at_the_same_address_with_its_first_federation_is_chosen_again(self):
        # Changed by the user only on the very page where CARSI was chosen: a chooser
        # that reloads at the same address with its first federation selected is a
        # new page (review 2026-11-02; it waited out the user's 3 minutes before).
        load = {"origin": 1000.5}
        self.page.evaluate.side_effect = lambda script, *args: (
            load["origin"] if script == self.d._PAGE_LOAD_JS else "Access through Institution")
        federation = school_list(self.FEDERATION, "#FederationDropdown", 0)  # its first entry selected
        self.d._page_selects = Mock(return_value=[federation, school_list([["", "Select"]], disabled=True)])
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))  # CARSI chosen, list loading
        # The same page shows another federation since: the user's choice, left alone.
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertEqual(self.d._set_select.call_count, 1)
        self.assertIn("institution_federation_user_choice", [e["state"] for e in self.result.events])
        load["origin"] = 2000.25  # reloaded at the same address
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertEqual(self.d._set_select.call_count, 2)
        self.assertEqual([e["state"] for e in self.result.events].count("institution_federation_selected"), 2)

    def test_pages_without_a_school_or_school_list_are_left_alone(self):
        self.d._page_selects = Mock(return_value=[school_list([["", "Country"], ["cn", "China"]], "#country", 0)])
        self.assertFalse(self.d._select_from_institution_lists(self.page, self.result))
        self.assertEqual(self.result.events, [])

    def test_thieme_denial_after_login_is_read_from_its_own_url(self):
        # The shared denial address (access_rules.DENIAL_URL_MARKERS), once this
        # item has been through the school's login.
        d = PublisherBatchDownloader({}, profile=get_publisher_profile("thieme"))
        d._item_result = SimpleNamespace(events=[])
        page = Mock()
        page.url = ("https://profile.thieme.de/HTML/sso/THIEME/login.htm?hook_url="
                    "https://www.thieme-connect.de/products/ejournals/pdf/10.1055/x.pdf&type=auth_denied")
        self.assertFalse(d._denied_after_login(page))  # no login yet: an ordinary login page
        d._item_result.events.append({"state": "institution_selected", "detail": "Example University"})
        self.assertFalse(d._denied_after_login(page))
        d._item_result._visited_idp = True
        self.assertTrue(d._denied_after_login(page))
        page.url = page.url.replace("type=auth_denied", "type=")
        self.assertFalse(d._denied_after_login(page))


@unittest.skipUnless(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") == "1", "local browser fixture opt-in")
class FederatedEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from patchright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.requests = []
        self.html = "<title>Offline article</title>"
        def respond(route):
            self.requests.append(route.request.url)
            route.fulfill(status=200, content_type="text/html", body=self.html)
        self.context.route("**/*", respond)
        self.page = self.context.new_page()

    def downloader(self, publisher, **config):
        return PublisherBatchDownloader({"publisher_institution_federation": "carsi", **config},
                                        profile=get_publisher_profile(publisher),
                                        institution_query="Example University")

    def test_karger_gateway_is_reached_even_when_the_menu_link_swallows_the_click(self):
        gateway = "https://karger.com/ExternalAuthentication/OpenAthensKeystoneLogin?returnUrl=x"
        self.html = f'<a href="{gateway}" onclick="return false">Access via Shibboleth and OpenAthens</a>'
        article = "https://karger.com/anm/article-abstract/81/5/276/1/Offline"
        self.page.goto(article)
        result = DownloadResult(doi="10.1159/1", status="failed")
        self.assertTrue(self.downloader("karger")._click_sso_entry(self.page, result))
        self.assertEqual(self.requests, [article, gateway])

    def silverchair_form(self, schools):
        options = "".join(f"<option value='{v}'>{t}</option>" for v, t in schools)
        self.html = f"""<title>Access through Institution | ACS Publications</title>
          <input id="institutionSearchInput" aria-label="University or Organization Name">
          <select id="FederationDropdown"><option value="">Select</option><option value="3">Open Athens</option>
            <option value="11">China CERNET Federation (CARSI)</option></select>
          <select id="InstitutionDropdown"><option value="">Select</option></select>
          <a href="javascript:;" id="shibbolethSelectBtn"
             onclick="location.href='/shib?entity='+encodeURIComponent(document.querySelector('#InstitutionDropdown').value)">Access through Institution</a>
          <script>document.querySelector('#FederationDropdown').addEventListener('change', e => {{
            const list = document.querySelector('#InstitutionDropdown');
            // Like the live page: the old options stay while the list reloads disabled.
            list.disabled = true;
            list.insertAdjacentHTML('beforeend', "<option value='stale'>STALE ENTRY</option>");
            setTimeout(() => {{
              list.innerHTML = "<option value=''>Select</option>";
              if (e.target.value === '11') list.insertAdjacentHTML('beforeend', `{options}`);
              list.disabled = false;
            }}, 1500);
          }});</script>"""
        self.page.goto("https://pubs.acs.org/institutional-login?returnUrl=%2Fdoi%2F10.1021%2Fx")

    def test_acs_form_selects_school_then_the_school_and_submits_once(self):
        self.silverchair_form([("https://idp.a.example/idp/shibboleth", "EXAMPLE (CITY) UNIV"),
                               ("https://idp.b.example/idp/shibboleth", "EXAMPLE NORMAL UNIV")])
        result = DownloadResult(doi="10.1021/x", status="failed")
        self.assertTrue(self.downloader("acs")._select_institution(self.page, result))
        self.page.wait_for_url("**/shib?entity=*")
        self.assertIn("idp.a.example", self.page.url)
        states = [e["state"] for e in result.events]
        self.assertEqual(states, ["institution_federation_selected", "institution_selected", "institution_list_submitted"])

    def test_acs_list_left_disabled_after_loading_is_chosen_by_entity_id(self):
        """ACS 2026-11-02: the school list arrived (211 entries) and stayed disabled."""
        self.silverchair_form([("https://idp.b.example/idp/shibboleth", "EXAMPLE NORMAL UNIV"),
                               ("https://idp.a.example/idp/shibboleth", "SOMETHING ELSE (CITY) UNIV")])
        self.page.evaluate("() => { const f = document.querySelector('#FederationDropdown'); f.value = '11';"
                           " f.dispatchEvent(new Event('change')); }")
        self.page.wait_for_function("document.querySelector('#InstitutionDropdown').options.length > 2")
        self.page.evaluate("() => { document.querySelector('#InstitutionDropdown').disabled = true; }")
        d = self.downloader("acs", idp_entity_id="https://idp.a.example/idp/shibboleth")
        result = DownloadResult(doi="10.1021/x", status="failed")
        self.assertTrue(d._select_institution(self.page, result))
        self.page.wait_for_url("**/shib?entity=*")
        self.assertIn("idp.a.example", self.page.url)

    def test_hidden_federation_and_school_lists_are_set_and_go_is_pressed(self):
        """JAMA 2026-11-02: both lists hidden behind a search box; choosing the
        federation fills the school list by a postback; "Go" submits."""
        self.html = """<title>Sign in via Shibboleth</title><form id="aspnetForm" action="/signinshibboleth/go">
          <div class="panel"><input type="text"> <label><input type="checkbox" name="remember"> Remember my institution</label>
          <input type="submit" value="Go" onclick="location.href='/go?idp='+encodeURIComponent(document.querySelector('#ddlInstitutions').value);return false;">
          <select id="ddlFederations" style="display:none" onchange="setTimeout(() => {
              document.querySelector('#ddlInstitutions').innerHTML = this.value === '49'
                ? `<option value=''>Select Institution</option><option value='https://idp.b.example/idp/shibboleth'>Other University</option>`
                  + `<option value='https://idp.a.example/idp/shibboleth'>Example University</option>` : '';
            }, 300)">
            <option value="">Select Federation</option><option value="2">InCommon</option>
            <option value="49">China (CARSI)</option><option value="52">China (CSTCloudFederation)</option></select>
          <select id="ddlInstitutions" style="display:none"></select></div>
          <p>Find your institution by entering it in the field above.</p></form>"""
        self.page.goto("https://jamanetwork.com/signinshibboleth?returnUrl=%2Fjournals%2Fjama%2Ffullarticle%2F1")
        result = DownloadResult(doi="10.1001/jama.1", status="failed")
        self.assertTrue(self.downloader("jama")._select_institution(self.page, result))
        self.page.wait_for_url("**/go?idp=*")
        self.assertIn("idp.a.example", self.page.url)
        self.assertFalse(self.page.evaluate("() => document.querySelector('[name=remember]') === null"))
        self.assertEqual([e["state"] for e in result.events][:3],
                         ["institution_federation_selected", "institution_selected", "institution_list_submitted"])

    def test_hidden_school_submit_is_used_before_an_unrelated_visible_store_link(self):
        """The institution form's native controls can all be behind a custom UI."""
        self.html = """<form id="webform"><div hidden>
          <select id="institution"><option value="idp">Example University</option></select>
          <input id="choose" type="submit" value="Select"
            onclick="location.href='/institution-login';return false;">
          </div><a class="btn" href="https://store.example/">Go</a></form>"""
        self.page.goto("https://publisher.example/institution")
        d = self.downloader("jama")
        self.assertEqual(self.page.evaluate(d._LIST_SUBMIT_JS, [0, None]), "Select")
        self.assertEqual(self.page.locator('[data-paper-search-submit]').get_attribute('id'), 'choose')
        self.assertTrue(d._click_control(self.page, self.page.locator('[data-paper-search-submit]'),
                                        DownloadResult(doi="10.1001/jama.1", status="failed"),
                                        'institution list submit', timeout_ms=100))
        self.page.wait_for_url('**/institution-login')
        self.assertFalse(any('store.example' in url for url in self.requests))

    def test_unrelated_hidden_purchase_submit_is_not_a_school_submit(self):
        self.html = """<form><div hidden><select><option>Example University</option></select>
          <input type="submit" value="Subscribe now"></div></form>
          <form><button>Continue</button></form>"""
        self.page.goto("https://publisher.example/institution")
        self.assertIsNone(self.page.evaluate(PublisherBatchDownloader._LIST_SUBMIT_JS, [0, None]))

    def test_acs_form_without_a_unique_school_is_left_to_the_user(self):
        self.silverchair_form([("https://idp.b.example/idp/shibboleth", "EXAMPLE NORMAL UNIV")])
        result = DownloadResult(doi="10.1021/x", status="failed")
        d = self.downloader("acs")
        d.LIST_WAIT_SEC = 3
        d._select_institution(self.page, result)
        self.assertNotIn("institution_list_submitted", [e["state"] for e in result.events])
        self.assertIn("auto_institution_not_found", [e["state"] for e in result.events])
        self.assertTrue(self.page.url.startswith("https://pubs.acs.org/institutional-login"))

    def test_aps_uses_federated_sign_in_not_the_aps_account_form(self):
        article = "https://journals.aps.org/pre/abstract/10.1103/PhysRevE.1"
        federated = "https://journals.aps.org/auth/openathens/login?rt=https%3A%2F%2Fjournals.aps.org%2Fpre%2Fabstract%2F10.1103%2FPhysRevE.1"
        self.html = f"""<div id="inline-unauthorized-page"><a href="/auth/apsmember/login">APS Member Log In</a>
            <a href="/login_inst_user?rt=x">Log in with username/password provided by your institution</a></div>
            <div hidden><a href="{federated}">Sign in via your Institution</a></div>"""
        self.page.goto(article)
        d = self.downloader("aps")
        self.assertTrue(d._looks_logged_out(self.page))
        result = DownloadResult(doi="10.1103/PhysRevE.1", status="failed")
        self.assertTrue(d.adapter.institution_sign_in(self.page, result))
        self.assertEqual(self.requests, [article, federated])
        self.html = '<div id="inline-unauthorized-page"><a href="/login_inst_user?rt=x">Log in with username/password provided by your institution</a></div>'
        self.page.goto(article)
        self.assertFalse(d.adapter.institution_sign_in(self.page, result))
        self.assertEqual(self.requests[-1], article)

    def test_optica_not_accessible_page_goes_to_institutional_login(self):
        article = "https://opg.optica.org/ol/abstract.cfm?uri=ol-49-14-3926"
        auth = "https://auth.optica.org/connect/authorize?client_id=osap&redirect_uri=x"
        self.html = f"""<a id="loginModal" href="#">LOGIN</a><strong>Not Accessible</strong>
            <p>Your library or personal account may give you access</p>
            <div hidden><input type="email" placeholder="Email"><a href="https://auth.optica.org.evil.example/connect/authorize">Institutional Login</a>
            <a href="{auth}">Institutional Login</a></div><a href="viewmedia.cfm?uri=ol-49-14-3926&seq=0">PDF Article</a>"""
        self.page.goto(article)
        d = self.downloader("optica")
        self.assertTrue(d._looks_logged_out(self.page))
        result = DownloadResult(doi="10.1364/ol.527743", status="failed")
        self.assertTrue(d._click_sso_entry(self.page, result))
        self.assertEqual(self.requests, [article, auth])
        self.assertIn("optica-institutional-login", [e.get("detail") for e in result.events])

    def test_lww_login_page_follows_openathens_institutional_once(self):
        login = "https://login.wolterskluwer.com/as/x/resume/as/authorization.ping"
        athens = "https://login.wolterskluwer.com/pf/adapter2adapter.ping?client_id=HLRP.Ovid_com"
        self.html = f"""<title>Ovid Login</title><input id="username"><input id="password" type="password">
            <button id="btnSubmit">Sign In</button><a id="athensLoginUrl" href="{athens}">OpenAthens | Institutional</a>"""
        self.page.goto(login)
        d = self.downloader("lww")
        result = DownloadResult(doi="10.1249/x", status="failed")
        self.assertTrue(d._follow_federated_login_option(self.page, result))
        self.assertEqual(self.requests, [login, athens])
        self.page.goto(login)
        self.assertFalse(d._follow_federated_login_option(self.page, result))
        self.html = '<input type="password"><a id="athensLoginUrl" href="https://evil.example/">OpenAthens</a>'
        self.page.goto(login)
        self.assertFalse(d._follow_federated_login_option(self.page, DownloadResult(doi="10.1249/y", status="failed")))

    def test_bmj_institution_login_without_school_ends_at_once(self):
        article = "https://heart.bmj.com/content/112/22/1264"
        shib = "https://heart.bmj.com/login/shibboleth?subcode=bmjjournals&uri=x"
        self.html = f"""<a href="/user/login">Log in</a><a href="https://members.society.example/journal">Log in via BCS</a>
            <a href="{shib}">Log in via Institution</a><a href="#">Buy this article ($64)</a>"""
        self.page.goto(article)
        d = self.downloader("bmj")
        self.assertTrue(d._looks_logged_out(self.page))
        result = DownloadResult(doi="10.1136/x", status="failed")
        self.assertTrue(d._click_sso_entry(self.page, result))
        self.assertEqual(self.requests, [article, shib])
        self.html = """<select id="shib-fed-select"><option>Select your institution location...</option>
            <option>China (CAS)</option><option>UK Access Management Federation</option></select>"""
        self.page.goto(shib)
        self.assertEqual(d._login_block_reason(self.page), "institution_federation_unavailable")
        self.html = """<select id="shib-fed-select"><option>Select...</option><option>China CERNET Federation (CARSI)</option></select>"""
        self.page.goto(shib)
        self.assertNotEqual(d._login_block_reason(self.page), "institution_federation_unavailable")

    def test_sage_covered_access_link_still_opens_the_panel(self):
        article = "https://journals.sagepub.com/doi/10.1177/0000000000"
        sso = "https://journals.sagepub.com/action/ssostart?redirectUri=%2Fdoi%2F10.1177%2F0000000000"
        self.html = f"""<a href="#core-collateral-purchase-access" style="position:relative"
              onclick="document.querySelector('#panel').innerHTML='<a href=&quot;{sso}&quot;>Access through your institution</a>'">Access</a>
            <div style="position:fixed;inset:0;background:transparent;z-index:9"></div><div id="panel"></div>"""
        self.page.goto(article)
        result = DownloadResult(doi="10.1177/0000000000", status="failed")
        self.downloader("sage")._click_sso_entry(self.page, result)
        self.assertEqual([e["state"] for e in result.events], ["sage_access_click_dispatched", "sso_entry_clicked"])
        self.assertEqual(self.requests, [article, sso])


    def test_sage_institution_tab_already_open_under_an_overlay_is_left_as_it_is(self):
        # 2026-11-14: the tab was open (aria-expanded="true"), a click on it timed out and ended the article.
        article = "https://journals.sagepub.com/doi/10.1177/0000000001"
        sso = "https://journals.sagepub.com/action/ssostart?redirectUri=%2Fdoi%2F10.1177%2F0000000001"
        self.html = f"""<a href="#core-collateral-purchase-access" style="position:relative"
              onclick="document.querySelector('#panel').innerHTML='<button type=&quot;button&quot; aria-expanded=&quot;true&quot;>Institution</button>';
                       setTimeout(() => document.querySelector('#panel').insertAdjacentHTML('beforeend',
                         '<a href=&quot;{sso}&quot;>Access through your institution</a>'), 1500)">Access</a>
            <div style="position:fixed;inset:0;background:transparent;z-index:9"></div><div id="panel"></div>"""
        self.page.goto(article)
        result = DownloadResult(doi="10.1177/0000000001", status="failed")
        self.downloader("sage")._click_sso_entry(self.page, result)
        self.assertEqual([e["state"] for e in result.events], ["sage_access_click_dispatched", "sso_entry_clicked"])
        self.assertEqual(self.requests, [article, sso])


class ChooserPageTests(unittest.TestCase):
    def page(self, url, password=False):
        page = Mock(); page.url = url
        page.evaluate.return_value = ""
        page.locator.return_value.inner_text.return_value = ""
        page.locator.return_value.count.return_value = 1 if password else 0
        return page

    def test_federation_choosers_on_other_hosts_are_automated_but_password_pages_are_not(self):
        d = PublisherBatchDownloader({"publisher_institution_federation": "carsi"},
                                     profile=get_publisher_profile("thieme"), institution_query="Example University")
        self.assertFalse(d._is_human_login_page(self.page("https://profile.thieme.de/HTML/sso/ejournals/shibboleth.htm")))
        self.assertFalse(d._is_human_login_page(self.page("https://wayfinder.openathens.net/?return=x")))
        self.assertFalse(d._is_human_login_page(self.page("https://profile.thieme.de/HTML/sso/THIEME/login.htm")))
        self.assertTrue(d._is_human_login_page(self.page("https://wayfinder.openathens.net/?return=x", password=True)))
        self.assertFalse(d._is_human_login_page(self.page("https://idp.school.example/login")))
        self.assertFalse(d._is_human_login_page(self.page("https://wayfinder.openathens.net.evil.example/")))


if __name__ == "__main__":
    unittest.main()
