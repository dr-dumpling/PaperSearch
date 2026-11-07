"""Cold start: school sessions go, verification records, personal accounts and consent stay."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paper_search_carsi import cold_start
from paper_search_carsi.browser.backend import SESSION_COOKIES_FILE

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
    with sqlite3.connect(default / "Cookies") as db:
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
                         {"verification": 1, "personal_account": 1, "consent": 1})
        self.assertNotIn('"v"', json.dumps(plan))  # no cookie value ever appears
        self.assertEqual(sorted(plan["site_data"]["delete"]),
                         ["https_service.seamlessaccess.org_0.indexeddb.leveldb",
                          "https_www.sciencedirect.com_0.indexeddb.blob"])
        self.assertEqual(plan["site_data"]["local_storage_hosts"], ["service.seamlessaccess.org"])
        self.assertEqual(sorted(Path(f["path"]).name for f in plan["files"] if f["action"] == "delete"),
                         ["Local Storage", "Session Storage", "Session_13438509334969058", "Tabs_13438509335217404"])
        with sqlite3.connect(self.profile / "Default" / "Cookies") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM cookies").fetchone()[0], len(COOKIES))

    def test_applying_keeps_verification_personal_accounts_and_consent(self):
        done = self.run.apply()
        self.assertEqual(done["cookies"], 7)
        with sqlite3.connect(self.profile / "Default" / "Cookies") as db:
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
        with sqlite3.connect(self.profile / "Default" / "Cookies") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM cookies").fetchone()[0], len(COOKIES))

    def test_windows_keeps_cookies_under_network(self):
        network = self.profile / "Default" / "Network"
        network.mkdir()
        (self.profile / "Default" / "Cookies").rename(network / "Cookies")
        self.assertEqual(self.run.apply()["cookies"], 7)
        with sqlite3.connect(network / "Cookies") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM cookies").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
