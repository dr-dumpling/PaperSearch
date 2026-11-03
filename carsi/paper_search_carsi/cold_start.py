"""Cold start: forget the school sessions of the download browser, keep the rest.

Acceptance runs from a cold start as well as signed in (ADR 0010). A cold
start forgets:

- the school's login: its identity provider, campus sites and the
  federation services that remember a school (CARSI, OpenAthens,
  SeamlessAccess, SAMS Sigma, Atypon's SSO hub);
- the publishers' sessions and remembered schools;
- every other site's cookies and site data: the Camoufox profile belongs to
  the download engine alone, so the rest are journal sites (cell.com,
  thelancet.com, ...) and their trackers.

It keeps bot-verification records (Cloudflare), personal publisher accounts
and cookie-consent choices. Besides the profile's own cookie store it filters
the files that put cookies back: the session cookies saved for the next
launch and the saved publisher cookies.
Firefox's session-restore files are removed whole. The plan lists hosts and
cookie names only, never values; nothing is changed until it is confirmed.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .browser.backend import SESSION_COOKIES_FILE, _pid_alive, _profile_owner_pid, camoufox_profile_dir
from .browser.cookies import _CLOUDFLARE_COOKIE_NAMES, PUBLISHER_DOMAINS
from .engine.batch_institution import InstitutionMixin, _school_auth_patterns

DELETE = ("school_login", "publisher", "other_site")
KEEP = ("verification", "personal_account", "consent")

# Personal publisher accounts (Elsevier's account system); extend when another
# publisher keeps personal sign-in on a host of its own.
PERSONAL_ACCOUNT_HOSTS = ("id.elsevier.com", "auth.elsevier.com")
# On those hosts the account system also remembers the chosen school
# (Elsevier: "id.inst", "id.wayf.result.acct"); that part goes.
_REMEMBERED_SCHOOL_NAME = re.compile(r"(?:^|[._-])(?:inst|institution|wayf|idp|shib)(?:[._-]|$)", re.I)
# Services that remember the chosen school or carry the federated login.
FEDERATION_HOSTS = ("carsi.edu.cn", "openathens.net", "seamlessaccess.org", "sams-sigma.com", "iam.atypon.com")
_CONSENT_NAME = re.compile(r"consent|optanon|cookielaw|gdpr", re.I)
# Cookie files the engine restores into a browser.
_CACHE_COOKIE_FILES = ("publisher_cookies.json",)


def _under(host: str, domains: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains if d)


def _publisher_domains() -> tuple[str, ...]:
    from .publishers.profiles import get_publisher_profile, list_publisher_profiles

    domains = {d.lower().removeprefix("www.") for n in list_publisher_profiles()
               for d in get_publisher_profile(n).base_domains}
    return tuple(sorted(domains | {d.lower() for d in PUBLISHER_DOMAINS}))


class Classifier:
    """Sorts a cookie (host, name) or a site's data (host) into the categories above."""

    def __init__(self, config: dict[str, Any]):
        self.school_tokens = tuple(t.lower() for t in _school_auth_patterns(config) if t)
        self.publishers = _publisher_domains()

    def __call__(self, host: str, name: str = "") -> str:
        host = (host or "").lower().lstrip(".").split(":")[0]
        if name and (name in _CLOUDFLARE_COOKIE_NAMES or name.startswith(("cf_chl", "__cf"))):
            return "verification"
        if _under(host, PERSONAL_ACCOUNT_HOSTS):
            return "school_login" if name and _REMEMBERED_SCHOOL_NAME.search(name) else "personal_account"
        if name and _CONSENT_NAME.search(name):
            return "consent"
        if (any(t in host for t in self.school_tokens) or InstitutionMixin._IDP_HOST_RE.match(host)
                or host.endswith((".edu.cn", ".edu")) or _under(host, FEDERATION_HOSTS)):
            return "school_login"
        if _under(host, self.publishers):
            return "publisher"
        return "other_site"


def _storage_host(dirname: str) -> str:
    """``https+++www.sciencedirect.com^partitionKey=...`` -> host; '' for non-web origins."""
    origin = dirname.split("^", 1)[0]
    if not origin.startswith(("https+++", "http+++")):
        return ""
    return origin.split("+++", 1)[1].split("+", 1)[0]


def _webappsstore_host(origin_key: str) -> str:
    """``moc.tcerideicneics.www.:https:443`` -> www.sciencedirect.com."""
    return origin_key.split(":", 1)[0][::-1].lstrip(".")


def _netscape_rows(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]


class ColdStart:
    def __init__(self, profile: Path, cache_dir: Path | None, config: dict[str, Any]):
        self.profile = profile
        self.cache_dir = cache_dir  # None: the profile only, no saved cookie files
        self.classify = Classifier(config)

    # -- reading ------------------------------------------------------------

    def _cookie_rows(self) -> list[tuple[int, str, str]]:
        path = self.profile / "cookies.sqlite"
        if not path.exists():
            return []
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return list(db.execute("SELECT id, host, name FROM moz_cookies"))

    def _webappsstore_rows(self) -> list[str]:
        path = self.profile / "webappsstore.sqlite"
        if not path.exists():
            return []
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            return [row[0] for row in db.execute("SELECT DISTINCT originKey FROM webappsstore2")]

    def _cookie_files(self) -> list[Path]:
        files = [self.profile / SESSION_COOKIES_FILE]
        if self.cache_dir is not None:
            files += [self.cache_dir / n for n in _CACHE_COOKIE_FILES]
            files += sorted((self.cache_dir / "carsi_cookies").glob("*.json"))
        return [f for f in files if f.is_file()]

    @staticmethod
    def _file_cookies(path: Path) -> tuple[Any, list[dict[str, Any]]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", []) if isinstance(data, dict) else data
        return data, [c for c in cookies if isinstance(c, dict)]

    def _session_files(self) -> list[Path]:
        backups = self.profile / "sessionstore-backups"
        files = [self.profile / "sessionstore.jsonlz4"] + (sorted(backups.iterdir()) if backups.is_dir() else [])
        return [f for f in files if f.is_file()]

    # -- the plan -----------------------------------------------------------

    def plan(self) -> dict[str, Any]:
        owner = _profile_owner_pid(str(self.profile))
        cookies: dict[str, dict[str, set[str]]] = {c: {} for c in DELETE + KEEP}
        for _id, host, name in self._cookie_rows():
            cookies[self.classify(host, name)].setdefault(host.lstrip("."), set()).add(name)
        site_data: dict[str, list[str]] = {"delete": [], "keep": []}
        storage = self.profile / "storage" / "default"
        for entry in sorted(storage.iterdir()) if storage.is_dir() else []:
            host = _storage_host(entry.name)
            if host:
                site_data["delete" if self.classify(host) in DELETE else "keep"].append(entry.name)
        local = sorted({_webappsstore_host(k) for k in self._webappsstore_rows()
                        if self.classify(_webappsstore_host(k)) in DELETE})
        files = []
        for path in self._cookie_files():
            try:
                _data, rows = self._file_cookies(path)
            except (OSError, ValueError):
                files.append({"path": str(path), "action": "unreadable"})
                continue
            remove = sum(self.classify(str(c.get("domain", "")), str(c.get("name", ""))) in DELETE for c in rows)
            files.append({"path": str(path), "action": "filter", "remove": remove, "keep": len(rows) - remove})
            twin = path.with_suffix(".txt")
            if path.name == "publisher_cookies.json" and twin.is_file():
                lines = [r for r in _netscape_rows(twin) if len(r) >= 7 and not r[0].startswith("#")]
                gone = sum(self.classify(r[0], r[5]) in DELETE for r in lines)
                files.append({"path": str(twin), "action": "filter", "remove": gone, "keep": len(lines) - gone})
        files += [{"path": str(p), "action": "delete", "why": "Firefox session restore (tabs and session cookies)"}
                  for p in self._session_files()]
        return {
            "profile": str(self.profile),
            "browser_running": bool(owner and _pid_alive(owner)),
            "delete": {c: {"hosts": len(cookies[c]), "cookies": sum(len(v) for v in cookies[c].values()),
                           "items": [{"host": h, "names": sorted(n)} for h, n in sorted(cookies[c].items())]}
                       for c in DELETE},
            "keep": {c: {"hosts": len(cookies[c]), "cookies": sum(len(v) for v in cookies[c].values())} for c in KEEP},
            "site_data": {"delete": site_data["delete"], "keep": len(site_data["keep"]), "local_storage_hosts": local},
            "files": files,
        }

    # -- applying -----------------------------------------------------------

    def apply(self) -> dict[str, Any]:
        owner = _profile_owner_pid(str(self.profile))
        if owner and _pid_alive(owner):
            raise RuntimeError(f"the download browser (pid {owner}) is using this profile; close it first")
        done: dict[str, Any] = {"cookies": 0, "site_data": 0, "local_storage": 0, "files": []}
        path = self.profile / "cookies.sqlite"
        if path.exists():
            gone = [i for i, host, name in self._cookie_rows() if self.classify(host, name) in DELETE]
            with sqlite3.connect(path) as db:
                db.executemany("DELETE FROM moz_cookies WHERE id = ?", [(i,) for i in gone])
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            done["cookies"] = len(gone)
        storage = self.profile / "storage" / "default"
        for entry in sorted(storage.iterdir()) if storage.is_dir() else []:
            host = _storage_host(entry.name)
            if host and self.classify(host) in DELETE:
                shutil.rmtree(entry)
                done["site_data"] += 1
        local = self.profile / "webappsstore.sqlite"
        if local.exists():
            keys = [k for k in self._webappsstore_rows() if self.classify(_webappsstore_host(k)) in DELETE]
            with sqlite3.connect(local) as db:
                db.executemany("DELETE FROM webappsstore2 WHERE originKey = ?", [(k,) for k in keys])
            with sqlite3.connect(local) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            done["local_storage"] = len(keys)
        for file in self._cookie_files():
            try:
                data, rows = self._file_cookies(file)
            except (OSError, ValueError):
                continue
            kept = [c for c in rows if self.classify(str(c.get("domain", "")), str(c.get("name", ""))) not in DELETE]
            _write_json(file, {**data, "cookies": kept} if isinstance(data, dict) else kept)
            done["files"].append({"path": str(file), "removed": len(rows) - len(kept)})
            twin = file.with_suffix(".txt")
            if file.name == "publisher_cookies.json" and twin.is_file():
                rows_txt = _netscape_rows(twin)
                keep_txt = [r for r in rows_txt if len(r) < 7 or r[0].startswith("#")
                            or self.classify(r[0], r[5]) not in DELETE]
                twin.write_text("".join("\t".join(r) + "\n" for r in keep_txt), encoding="utf-8")
                done["files"].append({"path": str(twin), "removed": len(rows_txt) - len(keep_txt)})
        for file in self._session_files():
            file.unlink()
            done["files"].append({"path": str(file), "removed": "file"})
        return done


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def for_config(config: dict[str, Any], profile: str | None = None, cache_dir: str | None = None) -> ColdStart:
    """The cold start for the configured download profile (Camoufox's own directory)
    and the configured cache. Another profile comes with only the cache named for
    it: the configured cache belongs to the configured profile."""
    from .config import DATA_DIR
    from .engine.batch_common import _resolve_profile_dir

    if profile:
        return ColdStart(Path(profile), Path(cache_dir) if cache_dir else None, config)
    cache = cache_dir or config.get("cache_dir", str(DATA_DIR / "cache"))
    return ColdStart(camoufox_profile_dir(_resolve_profile_dir(config)), Path(cache), config)
