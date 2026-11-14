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

    # Denmark's federation is called WAYF, the general name of a school-choosing
    # page ("Where Are You From"), which the publisher layers know on their own.
    GENERAL_WORDS = {"wayf"}

    def terms(self):
        # National federations; an identity service across them (OpenAthens) is the engine's own knowledge.
        found = [f for f in federations.all_federations() if f.kind == "federation"]
        names = [f.name for f in found if f.name.lower() not in self.GENERAL_WORDS]
        words = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r"|CERNET)\b")
        texts = [label.lower() for f in found for label in f.chooser_labels if label.lower() not in self.GENERAL_WORDS]
        texts += [h for f in found for h in (*f.discovery_hosts, *f.service_domains)]
        # Whole words only: a short name ("RASH") inside a longer word ("Crashpad") is no name.
        texts = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in texts) + r")(?![\w-])")
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
                    if words.search(node.value) or texts.search(node.value.lower()):
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
        # Its own OpenAthens sign-in page, named by its domain, is its login page too (2026-11-14).
        self.assertEqual(config["idp_login_pages"], ["https://login.openathens.net/auth/harbour.edu.hk/o/"])
        self.assertTrue(schools.on_login_page(config, "https://login.openathens.net/auth/harbour.edu.hk/o/805?t=x"))
        self.assertFalse(schools.on_login_page(config, "https://login.openathens.net/auth/other.edu.hk/o/805"))

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
                                             "entity_id": "https://idp.northern.example/shibboleth",
                                             "registrationAuthority": ["https://federation.example.org"]}]
        found = self.find("Northern University")
        self.assertEqual((found.school, found.candidates), (None, []))
        self.assertEqual(found.unsupported, [("Northern University", "https://federation.example.org")])

    def test_the_federations_own_list_when_seamlessaccess_cannot_be_read(self):
        # Offline: the other federations' lists are not read from the network here.
        with patch("paper_search_school.network.fetch", side_effect=OSError("offline")):
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

    def test_federations_added_by_region(self):
        # India, Turkey, Sri Lanka, Bangladesh, Pakistan, Oman; the United States (2026-11-12);
        # China's CSTCloud, Saudi Arabia, Cyprus, Israel, Iran, Azerbaijan (2026-11-13);
        # Western Europe: the UK, Ireland, France, the Netherlands, Belgium, Luxembourg (2026-11-13);
        # Northern, Central, Southern and Eastern Europe (2026-11-13).
        for code, authority, label in (
                ("infed", "http://inflibnet.ac.in", "INFLIBNET Access Management Federation (INFED)"),
                ("yetkim", "https://yetkim.org.tr", "YETKIM Identity Federation"),
                ("liaf", "https://liaf.ac.lk/", "LEARN Identity Access Federation"),
                ("tigerfed", "https://tigerfed.net.bd", "TIGERfed"),
                ("pkifed", "https://pkifed.pk", "Pakistan Identity Federation"),
                ("omren", "http://www.omren.om", "OMREN Identity Federation"),
                ("incommon", "https://incommon.org/", "InCommon Federation"),
                ("cstcloud", "https://www.cstcloud.net", "CSTCloud Federation"),
                ("maeen", "https://www.maeen.sa", "Maeen Identity Federation"),
                ("cynet", "https://cif.cynet.ac.cy/", "CyNet Identity Federation"),
                ("iucc", "http://iif.iucc.ac.il", "IUCC Identity Federation"),
                ("irfed", "https://irfed.ir", "IRFED"),
                ("azsciencenet", "https://edugain.azsciencenet.az", "AzScienceNet Identity Federation"),
                ("ukfederation", "http://ukfederation.org.uk", "UK Higher Education"),
                ("edugate", "http://www.heanet.ie", "Ireland - Edugate Federation"),
                ("renater", "https://federation.renater.fr", "Fédération Éducation-Recherche (Renater)"),
                ("surfconext", "http://www.surfconext.nl", "SURFconext"),
                ("belnet", "http://federation.belnet.be", "Belnet Federation"),
                ("eduidlu", "http://eduid.lu", "eduID Luxembourg"),
                ("wayf", "https://www.wayf.dk", "WAYF"),
                ("swamid", "http://www.swamid.se/", "SWAMID"),
                ("haka", "http://www.csc.fi/haka", "Haka Federation"),
                ("feide", "http://feide.no/", "FEIDE"),
                ("dfnaai", "https://www.aai.dfn.de", "DFN-AAI"),
                ("switchaai", "http://rr.aai.switch.ch/", "Switch edu-ID"),
                ("aconet", "http://eduid.at", "ACOnet Identity Federation"),
                ("pionierid", "https://aai.pionier.net.pl", "PIONIER.Id"),
                ("eduidcz", "http://www.eduid.cz/", "eduID.cz"),
                ("safeid", "http://safeid.sk", "safeID"),
                ("eduidhu", "http://eduid.hu", "eduId.hu"),
                ("sir", "http://www.rediris.es/", "SIR (RedIRIS)"),
                ("rctsaai", "https://www.fccn.pt", "RCTSaai"),
                ("idem", "http://www.idem.garr.it/", "IDEM GARR AAI"),
                ("grnet", "http://aai.grnet.gr/", "GRNET"),
                ("ricerkanet", "https://id.ricerka.net.mt", "RiċerkaNET Identity Federation"),
                ("arnesaai", "http://aai.arnes.si", "ArnesAAI Slovenska izobraževalno raziskovalna federacija"),
                ("aaieduhr", "http://www.srce.hr", "AAI@EduHr"),
                ("iamres", "https://federacija.iamres.ac.rs/", "iAMRES"),
                ("idedume", "https://federacija-idedume.ucg.ac.me/", "IDeduME"),
                ("aaiedumk", "https://rr.aaiedu.mk", "AAIEduMk"),
                ("rash", "https://eduid.rash.al", "RASH"),
                ("bif", "https://bif.bren.bg", "BIF"),
                ("roedunetid", "http://eduid.roedu.net", "RoEduNetID"),
                ("taat", "http://taat.edu.ee", "TAAT"),
                ("laife", "https://idp.laife.lv/", "LAIFE"),
                ("litnet", "https://fedi.litnet.lt", "LITNET FEDI"),
                ("febas", "https://febas.basnet.by", "FEBAS"),
                ("peano", "https://peano.uran.ua", "PEANO"),
                ("leaf", "http://federations.renam.md/", "LEAF")):
            federation = federations.by_code(code)
            self.assertIs(federations.by_registration_authority(authority), federation, code)
            self.assertTrue(federation.matches(label), code)
            others = [f.code for f in federations.all_federations() if f.code != code and f.matches(label)]
            self.assertEqual(others, [], code)
        # Short all-capital names match only as written: the same words in other names do not.
        for code, label in (("sir", "Sir Harbour College"), ("idem", "Idem Library"), ("leaf", "Leaf Institute"),
                            ("rash", "Rash Institute"), ("bif", "Bif Network"), ("taat", "Taat College")):
            self.assertFalse(federations.by_code(code).matches(label), code)
        listed = {"type": "idp", "title": "Harbour University",
                  "title_langs": {"en": "Harbour University", "tr": "Liman Üniversitesi"},
                  "entity_id": "https://kimlik.liman.edu.tr/idp", "registrationAuthority": ["https://yetkim.org.tr/"],
                  "scope": "liman.edu.tr"}
        found = self.find({"Liman Üniversitesi": [listed]}, "Liman Üniversitesi")
        self.assertEqual((found.school.federation, found.school.name, found.school.name_en),
                         ("yetkim", "Liman Üniversitesi", "Harbour University"))

    def test_a_school_listed_under_one_name_in_every_language_keeps_the_english_name_given(self):
        listed = {"type": "idp", "title": "Universitat de Liman",
                  "title_langs": {"es": "Universitat de Liman", "ca": "Universitat de Liman", "en": "Universitat de Liman"},
                  "entity_id": "https://www.example.es/sir/limanidp", "registrationAuthority": ["http://www.rediris.es/"],
                  "scope": "liman.es"}
        rows = {"Universitat de Liman": [listed], "University of Liman": []}
        with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
            found = schools.find("Universitat de Liman", {}, self.data_dir, also=["University of Liman", "liman.es"])
        self.assertEqual((found.school.federation, found.school.name, found.school.name_en),
                         ("sir", "Universitat de Liman", "University of Liman"))
        # A school listed with an English name of its own keeps it.
        english = {**listed, "title_langs": {"es": "Universitat de Liman", "en": "Liman University"}}
        rows["Universitat de Liman"] = [english]
        with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
            found = schools.find("Universitat de Liman", {}, self.data_dir, also=["University of Liman"])
        self.assertEqual(found.school.name_en, "Liman University")
        # Listed only as part of a longer name: the English name given is searched first.
        staff = {**listed, "title": "Liman University - Staff",
                 "title_langs": {"en": "Liman University - Staff", "sr": "Univerzitet Liman - Zaposleni"}}
        rows.update({"Univerzitet Liman": [staff], "Liman University": [staff]})
        with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
            found = schools.find("Univerzitet Liman", {}, self.data_dir, also=["Liman University"])
        self.assertEqual((found.school.name, found.school.name_en, found.school.entry_name),
                         ("Liman University", "Liman University", "Liman University - Staff"))
        # Listed with an abbreviation or a code beside the school's name: named as given, the
        # English name given (accents allowed) searched first, the listed name last (2026-11-14).
        for title, local, english in (("ULB - Universidade de Sao Liman", "Universidade de São Liman", "University of São Liman"),
                                      ("Escuela Politécnica de Liman - epl", "Escuela Politécnica de Liman",
                                       "Liman Polytechnic School")):
            abbreviated = {**listed, "title": title, "title_langs": {"en": title}}
            rows.update({local: [abbreviated], schools._plain(local): [abbreviated], english: []})
            with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
                found = schools.find(local, {}, self.data_dir, also=[english])
            self.assertEqual((found.school.name, found.school.name_en, found.school.entry_name), (local, english, title))

    def test_a_local_name_is_saved_with_single_spaces(self):
        listed = {"type": "idp", "title": "Harbour University",
                  "title_langs": {"en": "Harbour University", "el": "Πανεπιστήμιο  Λιμανιού "},
                  "entity_id": "https://idp.limani.gr/idp", "registrationAuthority": ["http://aai.grnet.gr/"],
                  "scope": "limani.gr"}
        found = self.find({"Πανεπιστήμιο Λιμανιού": [listed]}, "Πανεπιστήμιο Λιμανιού")
        self.assertEqual((found.school.federation, found.school.name), ("grnet", "Πανεπιστήμιο Λιμανιού"))

    def test_a_school_listed_shorter_than_its_full_name_is_asked_about(self):
        short = {"type": "idp", "title": "Kita Bay", "entity_id": "urn:mace:incommon:kitabay.edu",
                 "registrationAuthority": ["https://incommon.org"], "scope": "kitabay.edu"}
        press = {"type": "idp", "title": "The Kita Bay University Press", "entity_id": "https://idp.press.kbu.edu/entity",
                 "registrationAuthority": ["https://openathens.net"], "scope": "press.kbu.edu"}
        found = self.find({"Kita Bay University": [short, press]}, "Kita Bay University")
        self.assertIsNone(found.school)
        self.assertEqual([s.name for s in found.candidates], ["Kita Bay", "The Kita Bay University Press"])
        # One word alone is not enough: "Kita" is inside many names.
        one = {**short, "title": "Kita"}
        self.assertEqual(self.find({"Kita Bay University": [one]}, "Kita Bay University").candidates, [])

    def test_a_name_ending_with_its_login_servers_word_is_exact(self):
        listed = {"type": "idp", "title": "Harbour Technical University IdP", "entity_id": "https://idp.htu.edu.az/idp",
                  "registrationAuthority": ["https://edugain.azsciencenet.az"], "scope": "htu.edu.az"}
        found = self.find({"Harbour Technical University": [listed]}, "Harbour Technical University")
        self.assertEqual((found.school and found.school.federation, found.candidates), ("azsciencenet", []))
        self.assertEqual(found.school.name, "Harbour Technical University")  # saved, and searched for, without it
        sso = {**listed, "title": "Harbour Technical University Single Sign-On Service"}
        self.assertEqual(self.find({"Harbour Technical University": [sso]}, "Harbour Technical University").school.name,
                         "Harbour Technical University")

    def test_a_school_found_by_its_domain_under_a_shared_entry_keeps_the_given_name(self):
        shared = {"type": "idp", "title": "Harbour Research ID", "entity_id": "https://passport.harbour.cn/idp",
                  "registrationAuthority": ["https://www.cstcloud.net/"], "scope": "passport.harbour.cn,kbi.ac.cn,lbi.ac.cn"}
        rows = {"港湾生物所": [], "Kita Bay Institute": [], "kbi.ac.cn": [shared]}
        with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
            found = schools.find("港湾生物所", {}, self.data_dir, also=["Kita Bay Institute", "kbi.ac.cn"])
        self.assertEqual((found.school.name, found.school.name_en, found.school.entity_id),
                         ("港湾生物所", "Kita Bay Institute", "https://passport.harbour.cn/idp"))
        # The entry's own name is kept, searched last: some choosers list the shared entry by it.
        self.assertEqual(found.school.entry_name, "Harbour Research ID")
        config = {}
        schools.save(config, found.school)
        self.assertEqual(schools.names(config), ("港湾生物所", "Kita Bay Institute", "Harbour Research ID"))
        d = PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query="港湾生物所")
        self.assertEqual(d._search_queries(list(d._institution_names())),
                         ["Kita Bay Institute", "港湾生物所", "Harbour Research ID"])
        # Only its domain given: the entry's own name stays.
        self.assertEqual(self.find({"kbi.ac.cn": [shared]}, "kbi.ac.cn").school.name, "Harbour Research ID")
        # The English name is the one given beside the school's own, even when that
        # one is ASCII too, or the English one has accents.
        for also, english in ((["Kita Bay Institute"], "Kita Bay Institute"), (["Kīta Bāy Institute"], "Kīta Bāy Institute"),
                              ([], "Kitan tutkimuslaitos")):
            with patch.object(schools, "_seamlessaccess", side_effect=lambda text, config: rows.get(text, [])):
                found = schools.find("Kitan tutkimuslaitos", {}, self.data_dir, also=[*also, "kbi.ac.cn"])
            self.assertEqual((found.school.name, found.school.name_en), ("Kitan tutkimuslaitos", english), also)

    def test_accents_do_not_count(self):
        listed = {"type": "idp", "title": "Universite du Port (UP)", "entity_id": "https://idp.port.be/idp",
                  "registrationAuthority": ["http://federation.belnet.be/"], "scope": "port.be"}
        self.assertEqual(self.find({"Université du Port": [listed]}, "Université du Port").school.federation, "belnet")
        # SeamlessAccess finding it only without the accents.
        self.assertEqual(self.find({"Universite du Port": [listed]}, "Université du Port").school.federation, "belnet")
        listed = {**listed, "title": "Liman Universitesi", "registrationAuthority": ["https://yetkim.org.tr/"]}
        self.assertEqual(self.find({"Lİman Ünİversİtesİ": [listed]}, "Lİman Ünİversİtesİ").candidates, [])
        # Japanese voicing marks are part of the name.
        self.assertNotEqual(schools._key("ガクエン"), schools._key("カクエン"))

    def test_one_school_listed_twice_in_its_federation_is_its_plainest_entry(self):
        main = {"type": "idp", "title": "Harbour University", "entity_id": "https://idp.harbour.nl/a",
                "registrationAuthority": ["http://www.surfconext.nl/"], "scope": "harbour.nl"}
        second = {**main, "title": "Harbour University (Entra)", "entity_id": "https://idp.harbour.nl/b"}
        found = self.find({"Harbour University": [main, second]}, "Harbour University")
        self.assertEqual((found.school.entity_id, found.candidates), ("https://idp.harbour.nl/a", []))
        # A national entry covering the school's domain is another entry, not the school's second.
        own = {"type": "idp", "title": "Harbour University", "entity_id": "https://idp.harbour.edu.pk/idp",
               "registrationAuthority": ["https://pkifed.pk"], "scope": "harbour.edu.pk"}
        shared = {"type": "idp", "title": "National Login Pakistan", "entity_id": "https://idp2.national.pk/idp",
                  "registrationAuthority": ["https://pkifed.pk"], "scope": "national.pk,harbour.edu.pk"}
        found = self.find({"harbour.edu.pk": [own, shared]}, "harbour.edu.pk")
        self.assertIsNone(found.school)
        self.assertEqual(len(found.candidates), 2)

    def test_a_carsi_school_also_listed_by_cstcloud_stays_carsi(self):
        # Both federations list the same entityID for some schools (2026-11-13): it is
        # one school, signing in through CARSI, the user's default.
        harbour = {"type": "idp", "title": "Harbour University", "title_langs": {"zh": "港湾大学", "en": "Harbour University"},
                   "entity_id": "https://idp.harbour.edu.cn/idp/shibboleth", "registrationAuthority": ["https://www.cstcloud.net/"],
                   "scope": "harbour.edu.cn"}
        carsi = schools.School("港湾大学", "Harbour University", "https://idp.harbour.edu.cn/idp/shibboleth", "carsi",
                               "harbour.edu.cn")
        with patch.object(schools, "_from_school_list",
                          side_effect=lambda given, config, data_dir, found, lookup: found.add(carsi, True)):
            found = self.find({"港湾大学": [harbour]}, "港湾大学")
        self.assertEqual((found.school.federation, found.candidates), ("carsi", []))

    def test_the_same_school_on_openathens_under_its_librarys_host_goes(self):
        federation = {"type": "idp", "title": "Harbour University of Engineering", "entity_id": "https://idp.hue.ac.bd/idp",
                      "registrationAuthority": ["https://tigerfed.net.bd"], "scope": "hue.ac.bd"}
        athens = {"type": "idp", "title": "Harbour University of Engineering (HUE)", "entity_id": "https://idp.lib.hue.ac.bd/oa",
                  "registrationAuthority": ["https://openathens.net"], "scope": "lib.hue.ac.bd"}
        found = self.find({"Harbour University of Engineering": [federation, athens]}, "Harbour University of Engineering")
        self.assertEqual((found.school.federation, found.candidates), ("tigerfed", []))

    def test_and_written_as_an_ampersand_is_the_same_name(self):
        # Two schools of this name in two countries are both asked about, not the one written with "and".
        here = {"type": "idp", "title": "National University of Harbour & Bay (NUHB)", "entity_id": "https://sso.nuhb.edu.pk/idp",
                "registrationAuthority": ["https://pkifed.pk"], "scope": "nuhb.edu.pk"}
        there = {"type": "idp", "title": "National University of Harbour and Bay", "entity_id": "https://idp.nuhb.ac.zw/entity",
                 "registrationAuthority": ["https://openathens.net"], "scope": "nuhb.ac.zw"}
        found = self.find({"National University of Harbour and Bay": [here, there]}, "National University of Harbour and Bay")
        self.assertIsNone(found.school)
        self.assertEqual({s.federation for s in found.candidates}, {"pkifed", "openathens"})

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

    def test_brackets_inside_and_a_name_in_another_script_count(self):
        # OpenAthens in Taiwan lists "English (ABBR) 中文" in one title (2026-11-12).
        athens = {"type": "idp", "title": "National Harbour Bay University (NHBU) 海灣大學",
                  "entity_id": "https://idp.nhbu.edu.tw/entity", "registrationAuthority": ["https://openathens.net"],
                  "scope": "nhbu.edu.tw"}
        for query in ("National Harbour Bay University", "海灣大學", "NHBU"):
            found = self.find({query: [athens]}, query)
            self.assertEqual((found.school and found.school.federation, found.candidates), ("openathens", []), query)
        # A longer name in the other script is still only near: it is asked, never taken alone.
        self.assertIsNone(self.find({"國立海灣大學": [athens]}, "國立海灣大學").school)

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
        # Recorded once, however often the page is looked at before the login ends.
        self.assertFalse(d._click_unique_institution_entry(page, result, page.url))
        self.assertEqual(len(result.events), 1)

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


class LoginRouteTests(unittest.TestCase):
    """A host the login reached after it left the publisher through a federation,
    a login service or an address asking for the school, before it came back, is
    the school's side (2026-11-12)."""

    ENTITY = "https://idp.kita.edu.tw/openathens"
    SYSTEM_LOGIN = "https://idm.kita.unisys.edu.tw/sso/KITA/saml2/login/?SAMLRequest=fVJN"
    TO_SCHOOL = (
        "https://www.sciencedirect.com/science/article/pii/S0000000000000000",
        "https://id.elsevier.com/as/authorization.oauth2?client_id=SDFE",
        "https://auth.elsevier.com/ShibAuth/institutionLogin?entityID=https%3A%2F%2Fidp.kita.edu.tw%2Fopenathens",
        "https://login.openathens.net/saml/2/sso/kita.edu.tw?SAMLRequest=fZFN",
        "https://login.openathens.net/auth/kita.edu.tw/o/12345678?t=abc",
    )

    def setUp(self):
        config = {"publisher_institution_federation": "openathens", "school_name": "Kita University",
                  "school_name_en": "Kita University", "idp_entity_id": self.ENTITY, "idp_domains": ["kita.edu.tw"],
                  "idp_login_pages": ["https://login.openathens.net/auth/*/o/"]}
        self.d = PublisherBatchDownloader(config, profile=ELSEVIER_PROFILE, institution_query="Kita University")
        self.result = Mock(events=[])
        self.d._event = lambda result, state, detail: result.events.append({"state": state, "detail": detail})
        self.page, self.handlers = Mock(), {}
        self.page.on.side_effect = lambda event, handler: self.handlers.__setitem__(event, handler)
        self.stop = self.d._follow_login_route(self.page, self.result)

    def go(self, *urls):
        for url in urls:
            self.handlers["request"](Mock(url=url, frame=self.page.main_frame,
                                          **{"is_navigation_request.return_value": True}))

    def test_the_host_after_the_schools_openathens_sign_in_is_the_schools(self):
        self.assertFalse(self.d._is_idp_host("idm.kita.unisys.edu.tw"))
        self.go(*self.TO_SCHOOL, self.SYSTEM_LOGIN)
        self.assertTrue(self.d._is_idp_host("idm.kita.unisys.edu.tw"))
        self.assertEqual([e["detail"] for e in self.result.events if e["state"] == "school_side_host"],
                         ["idm.kita.unisys.edu.tw after login.openathens.net"])
        page = Mock(url=self.SYSTEM_LOGIN)
        self.d._assist_configured_institution = Mock(return_value=True)
        self.d.adapter.leave_email_step = lambda page, result: False
        self.assertFalse(self.d._select_institution(page, self.result))
        self.d._assist_configured_institution.assert_not_called()

    def test_the_way_back_and_the_publishers_other_hosts_are_not(self):
        self.go("https://doi.org/10.1016/j.example.2024.01.001", "https://www.example-society.org/article/1")
        self.go(*self.TO_SCHOOL, "https://login.openathens.net/saml/2/consume",
                "https://www.sciencedirect.com/science/article/pii/S0000000000000000",
                "https://pdf.sciencedirectassets.com/271/1-s2.0-S0000/main.pdf")
        for host in ("doi.org", "www.example-society.org", "pdf.sciencedirectassets.com"):
            self.assertFalse(self.d._is_idp_host(host), host)
        self.assertFalse(any(e["state"] == "school_side_host" for e in self.result.events))

    def test_a_sign_in_hub_asking_for_the_school_is_not(self):
        asking = "/action/ssostart?idp=https%3A%2F%2Fidp.kita.edu.tw%2Fopenathens"
        self.go("https://www.example-society.org" + asking, "https://iam.hub.example" + asking,
                "https://iam.hub.example/sso/landing", "https://login.openathens.net/auth/kita.edu.tw/o/12345678",
                self.SYSTEM_LOGIN)
        self.assertFalse(self.d._is_idp_host("iam.hub.example"))
        self.assertTrue(self.d._is_idp_host("idm.kita.unisys.edu.tw"))
        self.assertFalse(self.d._names_identity_provider(self.SYSTEM_LOGIN))

    def test_the_publishers_own_chooser_and_its_journal_site_are_not(self):
        chooser = "https://id.elsevier.com/as/authorization.oauth2?client_id=JBS"
        self.go("https://doi.org/10.1016/j.example.2024.01.001",
                "https://www.harbourjournal.org/article/S0883-5403(24)00627-2/abstract", chooser,
                "https://www.harbourjournal.org/action/consumeSsoCookie?redirectUri=x")
        self.go(chooser, "https://www.bayjournal.org/action/consumeSsoCookie?redirectUri=x")
        self.assertFalse(any(e["state"] == "school_side_host" for e in self.result.events))

    def test_the_schools_login_server_not_answering_ends_the_login(self):
        self.go(*self.TO_SCHOOL, self.SYSTEM_LOGIN)
        aborted = Mock(url=self.SYSTEM_LOGIN, failure="net::ERR_ABORTED", frame=self.page.main_frame,
                       **{"is_navigation_request.return_value": True})
        self.handlers["requestfailed"](aborted)
        error_page = Mock(url="chrome-error://chromewebdata/", **{"is_closed.return_value": False})
        self.assertFalse(self.d._on_browser_error_page(error_page))
        self.handlers["requestfailed"](Mock(url=self.SYSTEM_LOGIN, failure="net::ERR_CONNECTION_TIMED_OUT",
                                            frame=self.page.main_frame, **{"is_navigation_request.return_value": True}))
        self.assertEqual(self.d._login_block_reason(error_page), "idp_login_error")
        self.assertIn("idm.kita.unisys.edu.tw: net::ERR_CONNECTION_TIMED_OUT", self.d._block_evidence)

    def test_the_next_item_starts_afresh(self):
        self.go(*self.TO_SCHOOL, self.SYSTEM_LOGIN)
        self.stop()
        self.assertEqual({c.args for c in self.page.remove_listener.call_args_list},
                         {(event, handler) for event, handler in self.handlers.items()})
        self.assertFalse(self.d._is_idp_host("idm.kita.unisys.edu.tw"))


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
        campus = {"t": "Kita University - Campus Hanako Sato"}
        self.assertEqual(self.settle(d, result, [(1, campus), (1, {"t": "Kita University Abu Dhabi"})]), (False, False))
        d, result = self.downloader()
        faculty = {"t": "Kita University Graduate School of Informatics Library"}
        self.assertEqual(self.settle(d, result, [(1, faculty)]), (False, False))
        # The same unit marked by its publisher as signing in no one settles nothing on its own.
        d, result = self.downloader()
        marked = {**faculty, "ids": '{"entityId":null}'.replace('"', "%22")}
        self.assertEqual(self.settle(d, result, [(1, marked), (1, {"t": "Kita University of Advanced Science"})]),
                         (False, True))

    def test_a_search_listing_only_schools_of_other_names_settles_later(self):
        d, result = self.downloader()
        scored = [(0, {"t": "University of Southtown"}), (0, {"t": "University of Northtown"}),
                  (0, {"t": "Westtown College"})]
        from paper_search_school.engine import batch_institution
        page = Mock()
        d._body_text = lambda page, limit=2000: ""
        for at, ends in ((100.0, False), (100.0 + d.SEARCH_SETTLED_SEC, False), (100.0 + 2 * d.SEARCH_SETTLED_SEC, True)):
            with patch.object(batch_institution.time, "time", return_value=at):
                self.assertIs(d._search_lists_no_school(page, result, self.URL, scored), ends, at)
        self.assertIn("3 unrelated entries", result.events[-1]["detail"])
        # A search box saying its list is closed shows no results, whatever the page lists.
        d, result = self.downloader()
        d._body_text = lambda page, limit=2000: ""
        result._search_box = (self.URL, "#search")
        closed = Mock(**{"evaluate.return_value": True})
        for at in (100.0, 100.0 + 2 * d.SEARCH_SETTLED_SEC):
            with patch.object(batch_institution.time, "time", return_value=at):
                self.assertFalse(d._search_lists_no_school(closed, result, self.URL, scored))
        # The page's own links listed before the search are no results of it, however many.
        d, result = self.downloader()
        d._body_text = lambda page, limit=2000: ""
        result._search_baseline = (self.URL, {"About Fixture Press", "Cookie settings", "Help"})
        links = [(0, {"t": "About Fixture Press"}), (0, {"t": "Cookie settings"}), (0, {"t": "Help"})]
        for at in (100.0, 100.0 + 2 * d.SEARCH_SETTLED_SEC):
            with patch.object(batch_institution.time, "time", return_value=at):
                self.assertFalse(d._search_lists_no_school(page, result, self.URL, links))
        with patch.object(batch_institution.time, "time", return_value=300.0):
            self.assertFalse(d._search_lists_no_school(page, result, self.URL, links + scored))
        with patch.object(batch_institution.time, "time", return_value=300.0 + 2 * d.SEARCH_SETTLED_SEC):
            self.assertTrue(d._search_lists_no_school(page, result, self.URL, links + scored))
        self.assertIn("3 unrelated entries: Northtown", result.events[-1]["detail"].replace("University of ", ""))
        # Two links of the page's own are no search's results.
        d, result = self.downloader()
        d._body_text = lambda page, limit=2000: ""
        with patch.object(batch_institution.time, "time", return_value=500.0):
            self.assertFalse(d._search_lists_no_school(page, result, self.URL, scored[:2]))
        self.assertIsNone(result._search_miss)

    def test_a_search_showing_nothing_is_tried_again_by_the_next_name(self):
        d, result = self.downloader(name="Kita University", local="北大学")
        result.events = [{"state": "auto_institution_search", "detail": f"Kita University @ {self.URL}"}]
        result._search_box, result._search_baseline = (self.URL, "#search"), (self.URL, {"Help"})
        box = Mock(**{"input_value.return_value": "Kita University"})
        page = Mock(**{"locator.return_value.first": box, "evaluate.return_value": True})  # its list closed
        from paper_search_school.engine import batch_institution
        result._search_typed_at = 100.0
        with patch.object(batch_institution.time, "time", return_value=103.0):
            self.assertFalse(d._search_again_by_another_name(page, result, self.URL, ["北大学", "Kita University"]))
        with patch.object(batch_institution.time, "time", return_value=107.0):
            self.assertTrue(d._search_again_by_another_name(page, result, self.URL, ["北大学", "Kita University"]))
        box.press_sequentially.assert_called_once_with("北大学", delay=40)
        self.assertEqual(result.events[-1]["detail"], f"北大学 @ {self.URL}")
        # Every name tried, or a box holding the user's own text: nothing more is typed.
        with patch.object(batch_institution.time, "time", return_value=200.0):
            self.assertFalse(d._search_again_by_another_name(page, result, self.URL, ["北大学", "Kita University"]))
        result.events.pop()
        box.input_value.return_value = "Kita"
        with patch.object(batch_institution.time, "time", return_value=300.0):
            self.assertFalse(d._search_again_by_another_name(page, result, self.URL, ["北大学", "Kita University"]))

    def test_settled_results_without_the_school_try_its_next_name_first(self):
        # Its own name in Latin letters with no accent: the English one is searched first.
        d, result = self.downloader(name="Kita University", local="Kitan yliopisto")
        self.assertEqual(d._search_queries(["Kitan yliopisto", "Kita University"]), ["Kita University", "Kitan yliopisto"])
        result.events = [{"state": "auto_institution_search", "detail": f"Kita University @ {self.URL}"}]
        result._search_box, result._search_baseline = (self.URL, "#search"), (self.URL, {"Help"})
        box = Mock(**{"input_value.return_value": "Kita University"})
        page = Mock(**{"locator.return_value.first": box, "evaluate.return_value": False})
        d._body_text = lambda page, limit=2000: ""
        scored = [(1, {"t": "Kita University of Advanced Science"})]
        from paper_search_school.engine import batch_institution
        for at in (100.0, 100.0 + d.SEARCH_SETTLED_SEC):
            with patch.object(batch_institution.time, "time", return_value=at):
                self.assertFalse(d._search_lists_no_school(page, result, self.URL, scored))
        box.press_sequentially.assert_called_once_with("Kitan yliopisto", delay=40)
        self.assertFalse(getattr(result, "_institution_not_listed", False) is True)
        # The next name settles the same: no name is left, the school is not listed.
        box.input_value.return_value = "Kitan yliopisto"
        for at, ends in ((200.0, False), (200.0 + d.SEARCH_SETTLED_SEC, True)):
            with patch.object(batch_institution.time, "time", return_value=at):
                self.assertIs(d._search_lists_no_school(page, result, self.URL, scored), ends)
        self.assertEqual(box.press_sequentially.call_count, 1)

    def test_an_address_rewritten_without_its_percent_encoding_is_the_same_page(self):
        d, result = self.downloader()
        typed_at = self.URL + "?return=https%3A%2F%2Fsp.fixture-press.example%2FLogin"
        result.events = [{"state": "auto_institution_search", "detail": f"Kita University @ {typed_at}"}]
        page = Mock()
        from paper_search_school.engine import batch_institution
        scored = [(1, {"t": "Kita University of Advanced Science"})]
        shown = self.URL + "?return=https://sp.fixture-press.example/Login"
        with patch.object(batch_institution.time, "time", return_value=100.0):
            self.assertFalse(d._search_lists_no_school(page, result, shown, scored))
        with patch.object(batch_institution.time, "time", return_value=100.0 + d.SEARCH_SETTLED_SEC):
            self.assertTrue(d._search_lists_no_school(page, result, shown, scored))

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

    def test_punctuation_and_accents_do_not_count(self):
        d, _ = self.downloader(name='Kita University "St. Hanako"', local="Universitat de Kità")
        self.assertEqual(d._institution_match_score("Kita University St Hanako"), 3)
        self.assertEqual(d._institution_match_score("Universitat de Kita"), 3)
        self.assertEqual(d._institution_match_score("Kita University St Hanako, Library"), 2)
        self.assertEqual(d._institution_match_score("Kita University St Hanako Bitola"), 1)
        # A login server's words after the name: the school's entry ("<entry> Single Sign-On Service").
        self.assertEqual(d._institution_match_score("Universitat de Kita Single Sign-On Service"), 2)
        self.assertEqual(d._institution_match_score("Universitat de Kita IdP"), 2)
        self.assertEqual(d._institution_match_score("Universitat de Kita Login Portal Bitola"), 1)

    def test_the_schools_own_names_and_a_leading_the(self):
        d, _ = self.downloader(name="Kita University", local="北大学")
        self.assertEqual(d._institution_match_score("北大学 Kita University"), 3)
        self.assertEqual(d._institution_match_score("The Kita University"), 3)
        self.assertEqual(d._institution_match_score("Kita University of Advanced Science"), 1)
