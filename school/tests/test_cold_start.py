"""Cold start: school sessions go, verification records, personal accounts and consent stay."""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from paper_search_school import cold_start
from paper_search_school.browser.backend import SESSION_COOKIES_FILE

CONFIG = {"idp_entity_id": "https://idp.school.edu.cn/idp/shibboleth"}
COOKIES = [
    (".sciencedirect.com", "cf_clearance"),        # verification: kept
    (".sciencedirect.com", "SD_SESSION"),          # publisher session
    ("www.sciencedirect.com", "OptanonConsent"),   # consent: kept
    ("id.elsevier.com", "ELS_SESSION"),            # personal account: kept
    ("id.elsevier.com", "id.inst"),                # but the school it remembers goes
    ("idp.school.edu.cn", "JSESSIONID"),           # the school's IdP
    ("ds.carsi.edu.cn", "_saml_idp"),              # CARSI remembers the school
    ("service.seamlessaccess.org", "ps"),          # SeamlessAccess
    ("webvpn.school.edu.cn", "wengine_vpn_ticket"),  # campus site
    ("www.cell.com", "JSESSIONID"),                # journal site
]


def build(root: Path) -> tuple[Path, Path]:
    profile, cache = root / "publisher-chrome", root / "cache"
    default = profile / "Default"
    (default / "Sessions").mkdir(parents=True)
    cache.mkdir()
    # closing() as in the cold start itself: an open connection keeps the file locked on Windows.
    with closing(sqlite3.connect(default / "Cookies")) as db, db:
        db.execute("CREATE TABLE cookies (creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL,"
                   " top_frame_site_key TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,"
                   " encrypted_value BLOB NOT NULL, path TEXT NOT NULL)")
        db.executemany("INSERT INTO cookies VALUES (?, ?, '', ?, '', x'00', '/')",
                       [(i, h, n) for i, (h, n) in enumerate(COOKIES)])
    for origin in ("https_service.seamlessaccess.org_0.indexeddb.leveldb",
                   "https_www.sciencedirect.com_0.indexeddb.blob", "https_id.elsevier.com_0.indexeddb.leveldb",
                   "chrome-extension_abc_0.indexeddb.leveldb"):
        (default / "IndexedDB" / origin).mkdir(parents=True)
        (default / "IndexedDB" / origin / "000003.log").write_text("x")
    (default / "Local Storage" / "leveldb").mkdir(parents=True)
    (default / "Local Storage" / "leveldb" / "000003.log").write_bytes(
        b"\x00META:https://service.seamlessaccess.org\x00\x01k\x00META:https://id.elsevier.com\x00")
    (default / "Session Storage").mkdir()
    (default / "Session Storage" / "000003.log").write_text("x")
    session = [{"name": n, "value": "v", "domain": h, "path": "/"} for h, n in COOKIES]
    (profile / SESSION_COOKIES_FILE).write_text(json.dumps({"saved_at": 1, "cookies": session}))
    (cache / "publisher_cookies.json").write_text(json.dumps(session[:4]))
    (cache / "publisher_cookies.txt").write_text(
        "# Netscape HTTP Cookie File\n" + "".join(f"{h}\tTRUE\t/\tTRUE\t0\t{n}\tv\n" for h, n in COOKIES[:4]))
    (default / "Sessions" / "Session_13438509334969058").write_bytes(b"SNSS")
    (default / "Sessions" / "Tabs_13438509335217404").write_bytes(b"SNSS")
    return profile, cache


def rows(cookies: Path) -> int:
    with closing(sqlite3.connect(cookies)) as db:
        return db.execute("SELECT count(*) FROM cookies").fetchone()[0]


class ColdStartTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile, self.cache = build(Path(tmp.name))
        self.run = cold_start.ColdStart(self.profile, self.cache, CONFIG)

    def test_the_plan_lists_names_only_and_changes_nothing(self):
        plan = self.run.plan()
        hosts = {c: {i["host"] for i in plan["delete"][c]["items"]} for c in cold_start.DELETE}
        self.assertEqual(hosts["school_login"], {"idp.school.edu.cn", "ds.carsi.edu.cn", "id.elsevier.com",
                                                 "service.seamlessaccess.org", "webvpn.school.edu.cn"})
        self.assertEqual(hosts["publisher"], {"sciencedirect.com"})
        self.assertEqual(hosts["other_site"], {"www.cell.com"})
        self.assertEqual({c: plan["keep"][c]["cookies"] for c in cold_start.KEEP},
                         {"verification": 1, "personal_account": 1, "consent": 1, "own_school": 0})
        self.assertNotIn('"v"', json.dumps(plan))  # no cookie value ever appears
        self.assertEqual(sorted(plan["site_data"]["delete"]),
                         ["https_service.seamlessaccess.org_0.indexeddb.leveldb",
                          "https_www.sciencedirect.com_0.indexeddb.blob"])
        self.assertEqual(plan["site_data"]["local_storage_hosts"], ["service.seamlessaccess.org"])
        self.assertEqual(sorted(Path(f["path"]).name for f in plan["files"] if f["action"] == "delete"),
                         ["Local Storage", "Session Storage", "Session_13438509334969058", "Tabs_13438509335217404"])
        self.assertEqual(rows(self.profile / "Default" / "Cookies"), len(COOKIES))

    def test_applying_keeps_verification_personal_accounts_and_consent(self):
        done = self.run.apply()
        self.assertEqual(done["cookies"], 7)
        with closing(sqlite3.connect(self.profile / "Default" / "Cookies")) as db:
            left = set(db.execute("SELECT host_key, name FROM cookies"))
        self.assertEqual(left, {(".sciencedirect.com", "cf_clearance"), ("www.sciencedirect.com", "OptanonConsent"),
                                ("id.elsevier.com", "ELS_SESSION")})
        saved = json.loads((self.profile / SESSION_COOKIES_FILE).read_text())
        self.assertEqual({c["name"] for c in saved["cookies"]}, {"cf_clearance", "OptanonConsent", "ELS_SESSION"})
        self.assertEqual(saved["saved_at"], 1)
        self.assertEqual({c["name"] for c in json.loads((self.cache / "publisher_cookies.json").read_text())},
                         {"cf_clearance", "OptanonConsent", "ELS_SESSION"})
        self.assertNotIn("SD_SESSION", (self.cache / "publisher_cookies.txt").read_text())
        self.assertIn("# Netscape", (self.cache / "publisher_cookies.txt").read_text())
        storage = sorted(p.name for p in (self.profile / "Default" / "IndexedDB").iterdir())
        self.assertEqual(storage, ["chrome-extension_abc_0.indexeddb.leveldb", "https_id.elsevier.com_0.indexeddb.leveldb"])
        # One database for every site: it goes whole when it holds a site to forget.
        self.assertFalse((self.profile / "Default" / "Local Storage").exists())
        self.assertEqual(done["local_storage"], 1)
        self.assertEqual(list((self.profile / "Default" / "Sessions").iterdir()), [])
        self.assertFalse((self.profile / "Default" / "Session Storage").exists())

    def test_before_another_school_the_publishers_personal_account_goes_too(self):
        # User, 2026-11-21: a test of another school passed with the last one's access, Elsevier's remember.me (kept as
        # a personal account) signing the visit in through it. Verification records and consent still stay.
        classify = cold_start.Classifier(CONFIG, accounts=True)
        self.assertEqual([classify("id.elsevier.com", n) for n in ("remember.me", "quickstart", "PF", "OptanonConsent", "__cf_bm")],
                         ["school_login", "school_login", "school_login", "consent", "verification"])
        self.assertEqual(cold_start.Classifier(CONFIG)("id.elsevier.com", "remember.me"), "personal_account")
        done = cold_start.ColdStart(self.profile, self.cache, CONFIG, accounts=True).apply()
        self.assertEqual(done["cookies"], 8)
        with closing(sqlite3.connect(self.profile / "Default" / "Cookies")) as db:
            left = set(db.execute("SELECT host_key, name FROM cookies"))
        self.assertEqual(left, {(".sciencedirect.com", "cf_clearance"), ("www.sciencedirect.com", "OptanonConsent")})
        self.assertNotIn("ELS_SESSION", (self.cache / "publisher_cookies.json").read_text())

    def test_before_another_school_the_school_signing_in_keeps_its_own_sign_in(self):
        # Windows, 2026-11-22: forgetting one test school's sign-in took the other's too, whose login then asked for a
        # picture code. The school about to sign in keeps its own (not a federation service other schools share).
        own = {**CONFIG, "idp_login_hosts": ["cas.school.edu.cn", "login.openathens.net"], "idp_domains": ["school.edu.cn"]}
        classify = cold_start.Classifier(own, accounts=True, keep_own=True)
        self.assertEqual([classify(h, "JSESSIONID") for h in ("idp.school.edu.cn", "cas.school.edu.cn", "webvpn.school.edu.cn",
                                                             "idp.other.edu.cn", "ds.carsi.edu.cn", "login.openathens.net")],
                         ["own_school", "own_school", "own_school", "school_login", "school_login", "school_login"])
        self.assertEqual(cold_start.Classifier(own, accounts=True)("idp.school.edu.cn", "JSESSIONID"), "school_login")
        done = cold_start.ColdStart(self.profile, self.cache, own, accounts=True, keep_own=True).apply()
        with closing(sqlite3.connect(self.profile / "Default" / "Cookies")) as db:
            left = set(db.execute("SELECT host_key, name FROM cookies"))
        self.assertEqual(left, {(".sciencedirect.com", "cf_clearance"), ("www.sciencedirect.com", "OptanonConsent"),
                                ("idp.school.edu.cn", "JSESSIONID"), ("webvpn.school.edu.cn", "wengine_vpn_ticket")})
        self.assertEqual(done["cookies"], 6)

    def test_another_profile_leaves_the_configured_cache_alone(self):
        before = (self.cache / "publisher_cookies.json").read_text()
        run = cold_start.for_config({**CONFIG, "cache_dir": str(self.cache)}, str(self.profile))
        self.assertEqual([Path(f["path"]).name for f in run.plan()["files"] if f["action"] == "filter"],
                         [SESSION_COOKIES_FILE])
        run.apply()
        self.assertEqual((self.cache / "publisher_cookies.json").read_text(), before)

    def test_a_running_browser_blocks_the_cold_start(self):
        os.symlink(f"host-{os.getppid()}", self.profile / "SingletonLock")
        self.assertTrue(self.run.plan()["browser_running"])
        with self.assertRaises(RuntimeError):
            self.run.apply()
        self.assertEqual(rows(self.profile / "Default" / "Cookies"), len(COOKIES))

    def test_windows_keeps_cookies_under_network(self):
        network = self.profile / "Default" / "Network"
        network.mkdir()
        (self.profile / "Default" / "Cookies").rename(network / "Cookies")
        self.assertEqual(self.run.apply()["cookies"], 7)
        self.assertEqual(rows(network / "Cookies"), 3)

    def test_the_cookie_store_is_closed_again(self):
        # Windows, 2026-11-18: Chrome cannot open a cookie file the cold start still holds.
        opened, real = [], sqlite3.connect

        def connect(*args, **kwargs):
            opened.append(real(*args, **kwargs))
            return opened[-1]

        with patch.object(cold_start.sqlite3, "connect", side_effect=connect):
            self.run.plan()
            self.run.apply()
        self.assertGreaterEqual(len(opened), 3)
        for db in opened:
            with self.assertRaises(sqlite3.ProgrammingError):  # "Cannot operate on a closed database."
                db.execute("SELECT 1")




class AnotherSchoolTests(unittest.TestCase):
    """User, 2026-11-21: switched to another school, the download browser stayed signed in with the last one."""

    def setUp(self):
        cold_start._signed_in_path().unlink(missing_ok=True)

    def test_a_sign_in_of_another_school_forgotten_first_a_test_always_signed_out(self):
        from unittest.mock import patch

        applied = []

        class Run:
            profile = "/tmp/profile"

            def __init__(self, busy=False):
                self.busy = busy

            def apply(self):
                if self.busy:
                    raise RuntimeError("the download browser is using this profile; close it first")
                applied.append(True)
                return {}

        a, b = {"idp_entity_id": "https://idp.a.edu/idp"}, {"idp_entity_id": "https://idp.b.edu/idp"}
        with patch.object(cold_start, "for_config", return_value=Run()) as made:
            self.assertEqual(cold_start.before_sign_in(a), "")  # none known yet: kept, nothing forgotten
            self.assertEqual(cold_start.signed_in_school(), "https://idp.a.edu/idp")
            self.assertEqual(cold_start.before_sign_in(a), "")
            self.assertEqual(applied, [])
            self.assertEqual(cold_start.before_sign_in(b), "cleared")
            self.assertEqual((len(applied), cold_start.signed_in_school()), (1, "https://idp.b.edu/idp"))
            # The personal publisher accounts with it (they keep the last school's access).
            self.assertEqual(made.call_args.kwargs, {"accounts": True, "keep_own": True})
            self.assertEqual(cold_start.before_sign_in(b, always=True), "cleared")  # a test: signed out whatever it was
            self.assertEqual(len(applied), 2)
            self.assertEqual(made.call_args.kwargs, {"accounts": True, "keep_own": False})
        with patch.object(cold_start, "for_config", return_value=Run(busy=True)), \
                patch("paper_search_school.browser.profiles.wait_for_profile_release", return_value=False) as waited:
            self.assertEqual(cold_start.before_sign_in(a), "busy")
            self.assertEqual(cold_start.signed_in_school(), "https://idp.b.edu/idp")  # nothing changed
            waited.assert_called_once_with("/tmp/profile", timeout=10)
        # A browser just closed (the batch's, switching to the next school) lets go of the profile within the wait.
        letting_go = Run(busy=True)
        with patch.object(cold_start, "for_config", return_value=letting_go), \
                patch("paper_search_school.browser.profiles.wait_for_profile_release",
                      side_effect=lambda path, timeout: setattr(letting_go, "busy", False) or True):
            self.assertEqual(cold_start.before_sign_in(a), "cleared")
            self.assertEqual(cold_start.signed_in_school(), "https://idp.a.edu/idp")
        self.assertEqual(cold_start.before_sign_in({}), "")


if __name__ == "__main__":
    unittest.main()
