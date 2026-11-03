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
    profile, cache = root / "publisher-camoufox", root / "cache"
    (profile / "sessionstore-backups").mkdir(parents=True)
    cache.mkdir()
    with sqlite3.connect(profile / "cookies.sqlite") as db:
        db.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT, name TEXT, value TEXT,"
                   " host TEXT, path TEXT, expiry INTEGER)")
        db.executemany("INSERT INTO moz_cookies (name, value, host, path, expiry) VALUES (?, 'v', ?, '/', 0)",
                       [(n, h) for h, n in COOKIES])
    with sqlite3.connect(profile / "webappsstore.sqlite") as db:
        db.execute("CREATE TABLE webappsstore2 (originAttributes TEXT, originKey TEXT, scope TEXT, key TEXT, value TEXT)")
        db.executemany("INSERT INTO webappsstore2 VALUES ('', ?, '', 'k', 'v')",
                       [(h[::-1] + ".:https:443",) for h in ("service.seamlessaccess.org", "id.elsevier.com")])
    for origin in ("https+++service.seamlessaccess.org", "https+++www.sciencedirect.com^partitionKey=x",
                   "https+++id.elsevier.com", "moz-extension+++abc"):
        (profile / "storage" / "default" / origin / "ls").mkdir(parents=True)
        (profile / "storage" / "default" / origin / "ls" / "data.sqlite").write_text("x")
    session = [{"name": n, "value": "v", "domain": h, "path": "/"} for h, n in COOKIES]
    (profile / SESSION_COOKIES_FILE).write_text(json.dumps({"saved_at": 1, "cookies": session}))
    (cache / "publisher_cookies.json").write_text(json.dumps(session[:4]))
    (cache / "publisher_cookies.txt").write_text(
        "# Netscape HTTP Cookie File\n" + "".join(f"{h}\tTRUE\t/\tTRUE\t0\t{n}\tv\n" for h, n in COOKIES[:4]))
    (profile / "sessionstore.jsonlz4").write_bytes(b"mozLz40\0")
    (profile / "sessionstore-backups" / "previous.jsonlz4").write_bytes(b"mozLz40\0")
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
                         ["https+++service.seamlessaccess.org", "https+++www.sciencedirect.com^partitionKey=x"])
        self.assertEqual(plan["site_data"]["local_storage_hosts"], ["service.seamlessaccess.org"])
        self.assertEqual(sorted(Path(f["path"]).name for f in plan["files"] if f["action"] == "delete"),
                         ["previous.jsonlz4", "sessionstore.jsonlz4"])
        with sqlite3.connect(self.profile / "cookies.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM moz_cookies").fetchone()[0], len(COOKIES))

    def test_applying_keeps_verification_personal_accounts_and_consent(self):
        done = self.run.apply()
        self.assertEqual(done["cookies"], 7)
        with sqlite3.connect(self.profile / "cookies.sqlite") as db:
            left = set(db.execute("SELECT host, name FROM moz_cookies"))
        self.assertEqual(left, {(".sciencedirect.com", "cf_clearance"), ("www.sciencedirect.com", "OptanonConsent"),
                                ("id.elsevier.com", "ELS_SESSION")})
        saved = json.loads((self.profile / SESSION_COOKIES_FILE).read_text())
        self.assertEqual({c["name"] for c in saved["cookies"]}, {"cf_clearance", "OptanonConsent", "ELS_SESSION"})
        self.assertEqual(saved["saved_at"], 1)
        self.assertEqual({c["name"] for c in json.loads((self.cache / "publisher_cookies.json").read_text())},
                         {"cf_clearance", "OptanonConsent", "ELS_SESSION"})
        self.assertNotIn("SD_SESSION", (self.cache / "publisher_cookies.txt").read_text())
        self.assertIn("# Netscape", (self.cache / "publisher_cookies.txt").read_text())
        storage = sorted(p.name for p in (self.profile / "storage" / "default").iterdir())
        self.assertEqual(storage, ["https+++id.elsevier.com", "moz-extension+++abc"])
        with sqlite3.connect(self.profile / "webappsstore.sqlite") as db:
            self.assertEqual([r[0] for r in db.execute("SELECT originKey FROM webappsstore2")], ["moc.reivesle.di.:https:443"])
        self.assertFalse((self.profile / "sessionstore.jsonlz4").exists())

    def test_another_profile_leaves_the_configured_cache_alone(self):
        before = (self.cache / "publisher_cookies.json").read_text()
        run = cold_start.for_config({**CONFIG, "cache_dir": str(self.cache)}, str(self.profile))
        self.assertEqual([Path(f["path"]).name for f in run.plan()["files"] if f["action"] == "filter"],
                         [SESSION_COOKIES_FILE])
        run.apply()
        self.assertEqual((self.cache / "publisher_cookies.json").read_text(), before)

    def test_a_running_browser_blocks_the_cold_start(self):
        os.symlink(f"host:+{os.getppid()}", self.profile / "lock")
        self.assertTrue(self.run.plan()["browser_running"])
        with self.assertRaises(RuntimeError):
            self.run.apply()
        with sqlite3.connect(self.profile / "cookies.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM moz_cookies").fetchone()[0], len(COOKIES))


if __name__ == "__main__":
    unittest.main()
