"""The federation layer: the federations' data, finding the user's school by
name across federations, and the publisher layers asking it (2026-11-11).
The schools here are fictional; the federations are real."""
from __future__ import annotations

import ast
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_search_school import federations
from paper_search_school.engine.batch import PublisherBatchDownloader
from paper_search_school.federations import schools
from paper_search_school.publishers.profiles import ELSEVIER_PROFILE

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "paper_search_school"
SCHOOL_LIST = ROOT / "tests" / "fixtures" / "carsi_school_list.js"

HARBOUR = {"type": "idp", "title": "The Harbour University", "title_langs": {"en": "The Harbour University"},
           "entity_id": "https://idp.harbour.edu.hk/idp/shibboleth", "registrationAuthority": ["https://hkaf.edu.hk"],
           "scope": "harbour.edu.hk"}
HARBOUR_METADATA = b"""<?xml version="1.0"?>
<md:EntitiesDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    xmlns:shibmd="urn:mace:shibboleth:metadata:1.0" xmlns:mdui="urn:oasis:names:tc:SAML:metadata:ui">
  <md:EntityDescriptor entityID="https://idp.harbour.edu.hk/idp/shibboleth">
    <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
      <md:Extensions>
        <shibmd:Scope regexp="false">harbour.edu.hk</shibmd:Scope>
        <mdui:UIInfo><mdui:DisplayName xml:lang="en">The Harbour University</mdui:DisplayName></mdui:UIInfo>
      </md:Extensions>
      <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
          Location="https://login.harbour.edu.hk/idp/profile/SAML2/Redirect/SSO"/>
    </md:IDPSSODescriptor>
  </md:EntityDescriptor>
</md:EntitiesDescriptor>"""


class FederationDataTests(unittest.TestCase):
    def test_builtin_federations_and_their_chooser_names(self):
        carsi, hkaf = federations.by_code("carsi"), federations.by_code("hkaf")
        self.assertEqual([f.code for f in federations.all_federations()][:1], ["carsi"])  # the default first
        for label in ("China CERNET Federation (CARSI)", "China (CARSI)"):
            self.assertTrue(carsi.matches(label) and not hkaf.matches(label), label)
        self.assertTrue(hkaf.matches("Hong Kong Access Federation") and not carsi.matches("Hong Kong Access Federation"))
        self.assertEqual(hkaf.option_among(["UK Higher Education", "Hong Kong  Access Federation", "Others"]),
                         "Hong Kong  Access Federation")
        self.assertIs(federations.by_registration_authority("https://hkaf.edu.hk/"), hkaf)
        self.assertIs(federations.configured({"publisher_institution_federation": "HKAF", "school_name": "X"}), hkaf)
        self.assertIsNone(federations.configured({"publisher_institution_federation": "hkaf"}))  # no school saved
        self.assertIs(federations.configured({"publisher_institution_federation": "carsi"}), federations.by_code("carsi"))
        self.assertIsNone(federations.configured({"carsi_enabled": True}))  # the old switch names no federation
        self.assertTrue(federations.on_discovery_page("https://ds.carsi.edu.cn/login"))


class PublisherLayersNameNoFederationTests(unittest.TestCase):
    """Guard (the layering): engine/ and adapters/ never name a federation, its
    hosts or its code; they ask the configured one. Docstrings and comments may."""

    def terms(self):
        # National federations; an identity service across them (OpenAthens) is the engine's own knowledge.
        found = [f for f in federations.all_federations() if f.kind == "federation"]
        words = re.compile(r"\b(?:" + "|".join(re.escape(f.name) for f in found) + r"|CERNET)\b")
        texts = [label.lower() for f in found for label in f.chooser_labels]
        texts += [h for f in found for h in (*f.discovery_hosts, *f.service_domains)]
        return words, texts, {f.code for f in found}

    def test_engine_and_adapters(self):
        words, texts, codes = self.terms()
        files = sorted((SRC / "engine").glob("*.py")) + sorted((SRC / "adapters").rglob("*.py"))
        problems = []
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                          if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                          and node.body and isinstance(node.body[0], ast.Expr)
                          and isinstance(node.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                    if words.search(node.value) or any(t in node.value.lower() for t in texts):
                        problems.append(f"{path.name}:{node.lineno} {node.value[:60]!r}")
                elif isinstance(node, ast.Compare):
                    for side in (node.left, *node.comparators):
                        if isinstance(side, ast.Constant) and str(side.value).lower() in codes:
                            problems.append(f"{path.name}:{node.lineno} compares with {side.value!r}")
                elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Attribute, ast.Name, ast.arg)):
                    name = getattr(node, "name", None) or getattr(node, "attr", None) \
                        or getattr(node, "id", None) or getattr(node, "arg", None)
                    if name and set(re.split(r"_+", name.lower())) & codes:
                        problems.append(f"{path.name}:{node.lineno} identifier {name}")
        self.assertEqual(problems, [])


class FindSchoolTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix="federations-"))
        shutil.copy(SCHOOL_LIST, self.data_dir / "carsi_school_list.js")
        (self.data_dir / "federation-hkaf.xml").write_bytes(HARBOUR_METADATA)
        self.rows: dict[str, list] = {}

    def find(self, query, *also, unavailable=False):
        def seamlessaccess(text, config):
            if unavailable:
                raise OSError("unreachable")
            return self.rows.get(text, [])
        with patch.object(schools, "_seamlessaccess", side_effect=seamlessaccess):
            return schools.find(query, {}, self.data_dir, also=also)

    def test_a_school_of_another_federation_by_its_english_name(self):
        self.rows["The Harbour University"] = [HARBOUR, {**HARBOUR, "title": "Harbour University Library",
                                                         "registrationAuthority": ["https://openathens.net"],
                                                         "entity_id": "https://idp.harbour.edu.hk/openathens"}]
        found = self.find("港湾大学", "The Harbour University")
        self.assertEqual(found.school, schools.School(
            "The Harbour University", "The Harbour University", HARBOUR["entity_id"], "hkaf", "harbour.edu.hk",
            ("login.harbour.edu.hk",)))
        config: dict = {}
        schools.save(config, found.school)
        self.assertEqual((config["publisher_institution_federation"], config["carsi_enabled"]), ("hkaf", False))
        self.assertEqual(schools.login_hosts(config), ("idp.harbour.edu.hk", "login.harbour.edu.hk"))
        self.assertEqual(schools.names(config), ("The Harbour University",))

    def test_a_carsi_school_by_its_chinese_name(self):
        found = self.find("示例大学")
        self.assertEqual((found.school.federation, found.school.name_en), ("carsi", "Example University"))

    def test_the_same_name_in_two_federations_is_asked(self):
        self.rows["Example University"] = [{**HARBOUR, "title": "The Example University",
                                            "title_langs": {"en": "The Example University"},
                                            "entity_id": "https://idp.example.edu.hk/idp/shibboleth"}]
        found = self.find("Example University")
        self.assertIsNone(found.school)
        self.assertEqual(sorted(s.federation for s in found.candidates), ["carsi", "hkaf"])
        self.assertEqual({s.summary()["federation"] for s in found.candidates}, {"CARSI", "HKAF"})

    def test_a_near_name_is_never_taken_alone(self):
        # A Chinese name can be a CARSI campus while the school itself is listed in English.
        found = self.find("示例师范")
        self.assertIsNone(found.school)
        self.assertEqual([s.name for s in found.candidates], ["示例师范大学"])

    def test_a_federation_not_supported_yet_is_told(self):
        self.rows["Northern University"] = [{"type": "idp", "title": "Northern University",
                                             "entity_id": "https://idp.northern.ac.uk/shibboleth",
                                             "registrationAuthority": ["http://ukfederation.org.uk"]}]
        found = self.find("Northern University")
        self.assertEqual((found.school, found.candidates), (None, []))
        self.assertEqual(found.unsupported, [("Northern University", "http://ukfederation.org.uk")])

    def test_the_federations_own_list_when_seamlessaccess_cannot_be_read(self):
        found = self.find("harbour.edu.hk", unavailable=True)
        self.assertEqual((found.school.federation, found.school.login_hosts), ("hkaf", ("login.harbour.edu.hk",)))
        self.assertIn("SeamlessAccess", found.unavailable)

    def test_an_entity_id_picks_that_school(self):
        self.rows[HARBOUR["entity_id"]] = [HARBOUR]
        self.assertEqual(self.find(HARBOUR["entity_id"]).school.entity_id, HARBOUR["entity_id"])

    def test_setup_reports_each_outcome(self):
        from paper_search_school import cli

        with patch.object(cli, "_data_dir", return_value=self.data_dir), \
                patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: self.rows.get(text, [])):
            config: dict = {}
            self.assertEqual(cli._find_school(config, "Nowhere", [])["error"], "school_not_found")
            self.rows["The Harbour University"] = [HARBOUR]
            self.assertIsNone(cli._find_school(config, "The Harbour University", []))
            self.assertEqual((config["publisher_institution_federation"], config["idp_login_hosts"]),
                             ("hkaf", ["login.harbour.edu.hk"]))
            ambiguous = cli._find_school(config, "示例", [])
            self.assertEqual((ambiguous["error"], ambiguous["candidates"][0]["federation"]), ("school_ambiguous", "CARSI"))


class PublisherLayersAskTheFederationTests(unittest.TestCase):
    def downloader(self, code):
        config = {"publisher_institution_federation": code, "school_name": "The Harbour University",
                  "idp_entity_id": HARBOUR["entity_id"]}
        return PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query="The Harbour University")

    def test_the_schools_federation_is_chosen_in_a_list(self):
        lists = [{"i": 0, "name": "#federation", "options": [["", "Select"], ["9", "China CERNET Federation (CARSI)"],
                                                              ["14", "Hong Kong Access Federation"]]}]
        self.assertEqual(self.downloader("hkaf")._federation_option(lists)[1:], ("14", "Hong Kong Access Federation"))
        self.assertEqual(self.downloader("carsi")._federation_option(lists)[1:], ("9", "China CERNET Federation (CARSI)"))

    def test_a_list_without_the_schools_federation_ends_the_login(self):
        d = self.downloader("hkaf")
        d._page_selects = lambda page: [{"i": 0, "name": "#FederationDropdown", "options": [
            ["", "--Select a Federation--"], ["1", "China CERNET Federation (CARSI)"], ["2", "InCommon"]]}]
        self.assertTrue(d._federation_list_lacks_ours(Mock()))
        self.assertTrue(d._is_idp_host("login.harbour.edu.hk") is False)  # only hosts saved by setup
        d.config["idp_login_hosts"] = ["login.harbour.edu.hk"]
        self.assertTrue(d._is_idp_host("login.harbour.edu.hk"))


class AsiaAndOpenAthensTests(unittest.TestCase):
    """Singapore, Japan, Korea, Malaysia, and OpenAthens as a secondary route (2026-11-11)."""

    def setUp(self):
        self.data_dir = Path(tempfile.mkdtemp(prefix="federations-asia-"))
        shutil.copy(SCHOOL_LIST, self.data_dir / "carsi_school_list.js")

    def find(self, rows, query):
        with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
            return schools.find(query, {}, self.data_dir)

    def test_chooser_names_and_kinds(self):
        self.assertTrue(federations.by_code("gakunin").matches("Academic Access Management Federation in Japan (GakuNin)"))
        self.assertTrue(federations.by_code("sifulan").matches("Malaysian Access Federation (SIFULAN)"))
        self.assertIs(federations.by_registration_authority("http://kafe.kreonet.net"), federations.by_code("kafe"))
        athens = federations.by_code("openathens")
        self.assertEqual((athens.kind, athens.secondary, athens.openathens_entries), ("service", True, True))
        self.assertTrue(athens.matches("OpenAthens Federation"))

    def test_an_abbreviated_listing_is_exact_and_a_retired_entry_is_skipped(self):
        listed = {"type": "idp", "title": "NHU - National Harbour University", "entity_id": "https://idp.nhu.edu.sg/idp",
                  "registrationAuthority": ["https://www.singaren.net.sg"], "scope": "nhu.edu.sg"}
        retired = {**listed, "title": "NHU - National Harbour University (Legacy AD FS - DO NOT USE)",
                   "entity_id": "https://old.nhu.edu.sg/idp"}
        found = self.find({"National Harbour University": [listed, retired]}, "National Harbour University")
        self.assertEqual((found.school.federation, found.school.entity_id), ("sgaf", "https://idp.nhu.edu.sg/idp"))

    def test_a_name_in_brackets_and_after_a_dash_counts(self):
        athens = {"type": "idp", "title": "北大学 (Kita University) – OpenAthens", "entity_id": "https://idp.kita.ac.jp/oa",
                  "registrationAuthority": ["https://openathens.net"], "scope": "kita.ac.jp"}
        for query in ("北大学", "Kita University"):
            self.assertEqual(self.find({query: [athens]}, query).school.federation, "openathens", query)

    def test_the_federation_entry_goes_before_the_same_schools_openathens_entry(self):
        federation = {"type": "idp", "title": "Kita University", "title_langs": {"en": "Kita University", "ja": "北大学"},
                      "entity_id": "https://idp.kita.ac.jp/idp/shibboleth", "registrationAuthority": ["https://www.gakunin.jp"],
                      "scope": "kita.ac.jp"}
        athens = {"type": "idp", "title": "Kita University Library", "entity_id": "https://idp.kita.ac.jp/entity",
                  "registrationAuthority": ["https://openathens.net"], "scope": "kita.ac.jp,123.kita.ac.jp"}
        found = self.find({"北大学": [federation, athens]}, "北大学")
        self.assertEqual(found.school.federation, "gakunin")
        self.assertEqual(found.candidates, [])

    def test_a_school_only_on_openathens_signs_in_there(self):
        athens = {"type": "idp", "title": "Universiti Contoh", "entity_id": "https://idp.contoh.edu.my/entity",
                  "registrationAuthority": ["https://openathens.net"], "scope": "contoh.edu.my"}
        found = self.find({"Universiti Contoh": [athens]}, "Universiti Contoh")
        self.assertEqual(found.school.federation, "openathens")
        config: dict = {}
        schools.save(config, found.school)
        self.assertEqual(config["idp_login_pages"], ["https://login.openathens.net/auth/*/o/"])
        d = PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query="Universiti Contoh")
        own = "https://login.openathens.net/auth/contoh.edu.my/o/123?t=x"
        self.assertTrue(d._on_school_login_page(own))
        self.assertFalse(d._is_federation_chooser(own))  # the user's own sign-in, not a chooser
        self.assertTrue(d._is_federation_chooser("https://login.openathens.net/auth?t=find"))
        # The segment is the organization's OpenAthens name, not always its domain (2026-11-11).
        self.assertTrue(d._on_school_login_page("https://login.openathens.net/auth/contoh.edu/o/72069892?t=x"))
        self.assertFalse(d._on_school_login_page("https://login.openathens.net/auth?t=find"))
        self.assertFalse(d._on_school_login_page("https://login.openathens.net/auth/contoh.edu/?t=x"))
        page = Mock(url=own)
        page.locator.return_value.count.return_value = 0  # "Choose how to sign in": links, no field
        page.evaluate.return_value = False
        self.assertTrue(d._idp_user_action(page))

    def test_openathens_entries_only_on_that_route(self):
        page = Mock(url="https://www.example-publisher.org/doi/10.1/x")
        page.evaluate.return_value = None
        for code, asked in (("hkaf", False), ("openathens", True)):
            d = PublisherBatchDownloader({"publisher_institution_federation": code, "school_name": "Universiti Contoh"},
                                         profile=ELSEVIER_PROFILE, institution_query="Universiti Contoh")
            d.adapter.is_institution_chooser = lambda url: False
            d.adapter.openathens_entry = lambda page, result: None
            page.evaluate.reset_mock()
            d._click_openathens_entry(page, Mock(events=[]))
            self.assertEqual(page.evaluate.called, asked, code)


class SchoolSignInRoutesTests(unittest.TestCase):
    """A school a publisher lists only without a sign-in through it, and the
    school's own login page left to the user (2026-11-11)."""

    def downloader(self):
        config = {"publisher_institution_federation": "kafe", "school_name": "Harbour University",
                  "idp_entity_id": "https://sso.harbour.ac.kr/sso"}
        return PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query="Harbour University")

    @staticmethod
    def entry(text, entity):
        data = '{"acctId":"1","acctName":"Harbour+University","entityId":%s,"derivedFlowType":"EIA"}' % entity
        return {"i": 0, "t": text, "h": "", "ids": data.replace('"', "%22")}

    def test_elsevier_entries_name_their_route(self):
        adapter = self.downloader().adapter
        self.assertIs(adapter.institution_entry_signs_in('{"entityId":null}'), False)
        self.assertIs(adapter.institution_entry_signs_in('{"entityId":"https://sso.harbour.ac.kr/sso"}'), True)
        self.assertIsNone(adapter.institution_entry_signs_in("https://example.org/entry"))

    def test_a_school_listed_only_without_a_sign_in_has_no_route(self):
        d = self.downloader()
        page = Mock(url="https://id.elsevier.com/as/authorization.oauth2")
        page.evaluate.return_value = [self.entry("Harbour University", "null"), self.entry("Harbour University", "null")]
        result = Mock(events=[])
        d._event = lambda result, state, detail: result.events.append({"state": state, "detail": detail})
        self.assertFalse(d._click_unique_institution_entry(page, result, page.url))
        self.assertTrue(result._institution_not_listed)
        self.assertEqual([e["state"] for e in result.events], ["auto_institution_not_found"])

    def test_the_entry_with_the_schools_sign_in_is_still_chosen(self):
        d = self.downloader()
        page = Mock(url="https://id.elsevier.com/as/authorization.oauth2")
        page.evaluate.side_effect = [[self.entry("Harbour University", "null"),
                                      self.entry("Harbour University", '"https://sso.harbour.ac.kr/sso"')], True]
        result = Mock(events=[])
        d._event = lambda result, state, detail: result.events.append({"state": state, "detail": detail})
        d._left_page = lambda page, before: True
        self.assertTrue(d._click_unique_institution_entry(page, result, page.url))
        self.assertIn("(entityID)", next(e["detail"] for e in result.events if e["state"] == "institution_selected"))

    def test_an_ip_or_vpn_only_school_ends_the_login(self):
        adapter = self.downloader().adapter
        page = Mock(url="https://id.elsevier.com/as/X/resume/as/authorization.ping?client_id=JBS")
        text = "Instructions from your organization Harbour University can grant access through either an IP address or a VPN."
        self.assertEqual(adapter.login_block_reason(page, text), "institution_federation_unavailable")

    def test_nothing_is_chosen_on_the_schools_login_page(self):
        d = self.downloader()
        page = Mock(url="https://sso.harbour.ac.kr/sso/login")
        d._assist_configured_institution = Mock(return_value=True)
        d.adapter.leave_email_step = lambda page, result: False
        self.assertFalse(d._select_institution(page, Mock(events=[])))
        d._assist_configured_institution.assert_not_called()


class SchoolSideTests(unittest.TestCase):
    """Every page under the school's domains, and the identity services schools
    sign in with, are the school's side of the login (2026-11-11)."""

    def test_the_schools_domains_and_identity_services(self):
        config: dict = {}
        schools.save(config, schools.School("Harbour University", "Harbour University", "https://idf.harbour.edu.my/idp",
                                            "sifulan", "harbour.edu.my", scopes=("harbour.edu.my",)))
        self.assertEqual(config["idp_domains"], ["harbour.edu.my"])
        d = PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query="Harbour University")
        for host in ("portal-id.harbour.edu.my", "harbour.edu.my", "login.microsoftonline.com", "harbour.okta.com"):
            self.assertTrue(d._is_idp_host(host), host)
        for host in ("www.sciencedirect.com", "notharbour.edu.my", "id.elsevier.com"):
            self.assertFalse(d._is_idp_host(host), host)
        page = Mock(url="https://portal-id.harbour.edu.my/sso/login")
        d._assist_configured_institution = Mock(return_value=True)
        self.assertFalse(d._select_institution(page, Mock(events=[])))
        d._assist_configured_institution.assert_not_called()


class SearchListsNoSchoolTests(unittest.TestCase):
    """A publisher's search that lists other schools only, or nothing, ends the
    login at once; the school's own units keep it open (2026-11-11)."""

    URL = "https://id.example-publisher.org/find"

    def downloader(self, name="Kita University", local=""):
        config = {"publisher_institution_federation": "gakunin", "school_name": local or name,
                  "school_name_en": name, "idp_entity_id": "https://idp.kita.ac.jp/idp/shibboleth"}
        d = PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query=local or name)
        result = Mock(events=[{"state": "auto_institution_search", "detail": f"{name} @ {self.URL}"}])
        result._search_miss = None
        d._event = lambda result, state, detail: result.events.append({"state": state, "detail": detail})
        return d, result

    def settle(self, d, result, scored, body=""):
        page = Mock()
        d._body_text = lambda page, limit=2000: body
        from paper_search_school.engine import batch_institution
        with patch.object(batch_institution.time, "time", return_value=100.0):
            first = d._search_lists_no_school(page, result, self.URL, scored)
        with patch.object(batch_institution.time, "time", return_value=100.0 + d.SEARCH_SETTLED_SEC):
            second = d._search_lists_no_school(page, result, self.URL, scored)
        return first, second

    def test_other_schools_only(self):
        d, result = self.downloader()
        scored = [(1, {"t": "Kita University of Advanced Science"}), (0, {"t": "Help"})]
        self.assertEqual(self.settle(d, result, scored), (False, True))
        self.assertTrue(result._institution_not_listed)
        self.assertIn("other entries", result.events[-1]["detail"])

    def test_the_search_saying_it_found_none(self):
        d, result = self.downloader()
        self.assertEqual(self.settle(d, result, [(0, {"t": "Help"})], body="No results found"), (False, True))

    def test_the_schools_own_library_keeps_the_search_open(self):
        d, result = self.downloader()
        self.assertEqual(self.settle(d, result, [(1, {"t": "Kita University Main Library"})]), (False, False))
        d, result = self.downloader()
        faculty = {"t": "Kita University Graduate School of Informatics Library"}
        self.assertEqual(self.settle(d, result, [(1, faculty)]), (False, False))
        # The same unit marked by its publisher as signing in no one settles nothing on its own.
        d, result = self.downloader()
        marked = {**faculty, "ids": '{"entityId":null}'.replace('"', "%22")}
        self.assertEqual(self.settle(d, result, [(1, marked), (1, {"t": "Kita University of Advanced Science"})]),
                         (False, True))

    def test_a_long_address_cut_short_in_the_record_is_the_same_page(self):
        d, result = self.downloader()
        long_url = self.URL + "?state=" + "x" * 600
        result.events = [{"state": "auto_institution_search", "detail": f"Kita University @ {long_url}"[:500]}]
        page = Mock()
        from paper_search_school.engine import batch_institution
        scored = [(1, {"t": "Kita University of Advanced Science"})]
        with patch.object(batch_institution.time, "time", return_value=100.0):
            self.assertFalse(d._search_lists_no_school(page, result, long_url, scored))
        with patch.object(batch_institution.time, "time", return_value=100.0 + d.SEARCH_SETTLED_SEC):
            self.assertTrue(d._search_lists_no_school(page, result, long_url, scored))

    def test_nothing_searched_here_settles_nothing(self):
        d, result = self.downloader()
        result.events = []
        self.assertEqual(self.settle(d, result, [(1, {"t": "Kita University of Advanced Science"})]), (False, False))

    def test_the_schools_own_names_and_a_leading_the(self):
        d, _ = self.downloader(name="Kita University", local="北大学")
        self.assertEqual(d._institution_match_score("北大学 Kita University"), 3)
        self.assertEqual(d._institution_match_score("The Kita University"), 3)
        self.assertEqual(d._institution_match_score("Kita University of Advanced Science"), 1)
