"""Cold start: forget the school sessions of the download browser, keep the rest.

Acceptance runs from a cold start as well as signed in (ADR 0010). A cold
start forgets:

- the school's login: its identity provider, campus sites and the
  federation services that remember a school (CARSI, OpenAthens,
  SeamlessAccess, SAMS Sigma, Atypon's SSO hub);
- the publishers' sessions and remembered schools;
- every other site's cookies and site data: the Chrome profile belongs to
  the download engine alone, so the rest are journal sites (cell.com,
  thelancet.com, ...) and their trackers.

It keeps bot-verification records (Cloudflare), personal publisher accounts
and cookie-consent choices; before a sign-in with another school (``before_sign_in``)
the personal accounts go too: Elsevier's keeps the school's access with it, while that school's own sign-in (its
login hosts and domains) stays, as it would come back as it is. Besides the profile's own cookie store it filters
the files that put cookies back: the session cookies saved for the next
launch and the saved publisher cookies. IndexedDB goes per site. Chrome keeps
every site's local storage in one database, which goes whole when it holds a
site to forget (the kept categories live in cookies). Chrome's session-restore
files and session storage are removed whole. The plan lists hosts and cookie
names only, never values; nothing is changed until it is confirmed.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from . import federations
from .browser.backend import SESSION_COOKIES_FILE, chrome_profile_dir, profile_holder
from .browser.cookies import _CLOUDFLARE_COOKIE_NAMES, PUBLISHER_DOMAINS
from .engine.batch_institution import InstitutionMixin, _school_auth_patterns
from .schools import lookup as school_lookup

DELETE = ("school_login", "publisher", "other_site")
KEEP = ("verification", "personal_account", "consent", "own_school")

# Personal publisher accounts (Elsevier's account system); extend when another
# publisher keeps personal sign-in on a host of its own.
PERSONAL_ACCOUNT_HOSTS = ("id.elsevier.com", "auth.elsevier.com")
# On those hosts the account system also remembers the chosen school
# (Elsevier: "id.inst", "id.wayf.result.acct"); that part goes.
_REMEMBERED_SCHOOL_NAME = re.compile(r"(?:^|[._-])(?:inst|institution|wayf|idp|shib)(?:[._-]|$)", re.I)
# Services that remember the chosen school or carry the federated login.
FEDERATION_HOSTS = (*federations.service_domains(), "openathens.net", "seamlessaccess.org", "sams-sigma.com",
                    "iam.atypon.com")
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
    """Sorts a cookie (host, name) or a site's data (host) into the categories above. ``accounts``: the personal
    publisher accounts are forgotten as a school's login (another school to sign in with). ``keep_own``: the sign-in of
    ``config``'s school, the one about to sign in, is kept (its login hosts and domains, not a service other schools
    sign in on): forgetting another school's need not make it type its password again, which its login answered with
    a picture code after a few that day (a test school, Windows, 2026-11-22)."""

    def __init__(self, config: dict[str, Any], accounts: bool = False, keep_own: bool = False):
        self.school_tokens = tuple(t.lower() for t in _school_auth_patterns(config) if t)
        self.publishers = _publisher_domains()
        self.accounts = accounts
        own = (*school_lookup.login_hosts(config), *school_lookup.domains(config)) if keep_own else ()
        self.own = tuple(h for h in dict.fromkeys(own) if h and not _under(h, FEDERATION_HOSTS))

    def __call__(self, host: str, name: str = "") -> str:
        host = (host or "").lower().lstrip(".").split(":")[0]
        if name and (name in _CLOUDFLARE_COOKIE_NAMES or name.startswith(("cf_chl", "__cf"))):
            return "verification"
        if self.own and _under(host, self.own):
            return "own_school"
        if _under(host, PERSONAL_ACCOUNT_HOSTS):
            # Elsevier's account keeps the school it was signed in through (remember.me signs the next visit in with
            # it, the school's access and all: a test of another school passed with the last one's, user 2026-11-21).
            if self.accounts:
                return "consent" if name and _CONSENT_NAME.search(name) else "school_login"
            return "school_login" if name and _REMEMBERED_SCHOOL_NAME.search(name) else "personal_account"
        if name and _CONSENT_NAME.search(name):
            return "consent"
        if (any(t in host for t in self.school_tokens) or InstitutionMixin._IDP_HOST_RE.match(host)
                or host.endswith((".edu.cn", ".edu")) or _under(host, FEDERATION_HOSTS)):
            return "school_login"
        if _under(host, self.publishers):
            return "publisher"
        return "other_site"


_INDEXEDDB_DIR = re.compile(r"^https?_(.+)_\d+\.indexeddb\.(?:leveldb|blob)$")
# A site's entry in Chrome's local storage database: "META:<origin>".
_LOCAL_STORAGE_ORIGIN = re.compile(rb"META:https?://([a-z0-9.-]+)")


def _storage_host(dirname: str) -> str:
    """``https_www.sciencedirect.com_0.indexeddb.leveldb`` -> host; '' for anything else."""
    found = _INDEXEDDB_DIR.match(dirname)
    return found.group(1) if found else ""


def _netscape_rows(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]


class ColdStart:
    def __init__(self, profile: Path, cache_dir: Path | None, config: dict[str, Any], accounts: bool = False,
                 keep_own: bool = False):
        self.profile = profile
        self.cache_dir = cache_dir  # None: the profile only, no saved cookie files
        self.classify = Classifier(config, accounts, keep_own)

    # -- reading ------------------------------------------------------------

    @property
    def _default(self) -> Path:
        return self.profile / "Default"

    def _cookies_db(self) -> Path:
        """Chrome's cookie store: ``Default/Network/Cookies`` (Windows), else ``Default/Cookies``."""
        network = self._default / "Network" / "Cookies"
        return network if network.exists() else self._default / "Cookies"

    def _cookie_rows(self) -> list[tuple[int, str, str]]:
        path = self._cookies_db()
        if not path.exists():
            return []
        # closing(): a connection's own ``with`` only commits. Left open, it keeps Chrome's
        # cookie file locked on Windows until the garbage collector gets to it.
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            return list(db.execute("SELECT rowid, host_key, name FROM cookies"))

    def _local_storage_hosts(self) -> list[str]:
        """The sites with an entry in Chrome's local storage database."""
        hosts: set[str] = set()
        store = self._default / "Local Storage" / "leveldb"
        for path in sorted(store.iterdir()) if store.is_dir() else []:
            if path.suffix in (".log", ".ldb"):
                try:
                    hosts.update(h.decode() for h in _LOCAL_STORAGE_ORIGIN.findall(path.read_bytes()))
                except OSError:
                    continue
        return sorted(hosts)

    def _cookie_files(self) -> list[Path]:
        files = [self.profile / SESSION_COOKIES_FILE]
        if self.cache_dir is not None:
            files += [self.cache_dir / n for n in _CACHE_COOKIE_FILES]
            files += sorted((self.cache_dir / "school_cookies").glob("*.json"))
        return [f for f in files if f.is_file()]

    @staticmethod
    def _file_cookies(path: Path) -> tuple[Any, list[dict[str, Any]]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", []) if isinstance(data, dict) else data
        return data, [c for c in cookies if isinstance(c, dict)]

    def _session_files(self) -> list[Path]:
        """Chrome's session restore (tabs, and their session cookies) and session storage."""
        sessions = self._default / "Sessions"
        files = sorted(p for p in sessions.iterdir() if p.is_file()) if sessions.is_dir() else []
        storage = self._default / "Session Storage"
        return files + ([storage] if storage.is_dir() else [])

    # -- the plan -----------------------------------------------------------

    def plan(self) -> dict[str, Any]:
        cookies: dict[str, dict[str, set[str]]] = {c: {} for c in DELETE + KEEP}
        for _id, host, name in self._cookie_rows():
            cookies[self.classify(host, name)].setdefault(host.lstrip("."), set()).add(name)
        site_data: dict[str, list[str]] = {"delete": [], "keep": []}
        storage = self._default / "IndexedDB"
        for entry in sorted(storage.iterdir()) if storage.is_dir() else []:
            host = _storage_host(entry.name)
            if host:
                site_data["delete" if self.classify(host) in DELETE else "keep"].append(entry.name)
        local = [h for h in self._local_storage_hosts() if self.classify(h) in DELETE]
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
        if local:
            files.append({"path": str(self._default / "Local Storage"), "action": "delete",
                          "why": "Chrome local storage, one database for all sites"})
        files += [{"path": str(p), "action": "delete", "why": "Chrome session restore and session storage"}
                  for p in self._session_files()]
        return {
            "profile": str(self.profile),
            "browser_running": bool(profile_holder(str(self.profile))),
            "delete": {c: {"hosts": len(cookies[c]), "cookies": sum(len(v) for v in cookies[c].values()),
                           "items": [{"host": h, "names": sorted(n)} for h, n in sorted(cookies[c].items())]}
                       for c in DELETE},
            "keep": {c: {"hosts": len(cookies[c]), "cookies": sum(len(v) for v in cookies[c].values())} for c in KEEP},
            "site_data": {"delete": site_data["delete"], "keep": len(site_data["keep"]), "local_storage_hosts": local},
            "files": files,
        }

    # -- applying -----------------------------------------------------------

    def apply(self) -> dict[str, Any]:
        holder = profile_holder(str(self.profile))
        if holder:
            raise RuntimeError(f"the download browser ({holder}) is using this profile; close it first")
        done: dict[str, Any] = {"cookies": 0, "site_data": 0, "local_storage": 0, "files": []}
        path = self._cookies_db()
        if path.exists():
            gone = [i for i, host, name in self._cookie_rows() if self.classify(host, name) in DELETE]
            with closing(sqlite3.connect(path)) as db, db:
                db.executemany("DELETE FROM cookies WHERE rowid = ?", [(i,) for i in gone])
            done["cookies"] = len(gone)
        storage = self._default / "IndexedDB"
        for entry in sorted(storage.iterdir()) if storage.is_dir() else []:
            host = _storage_host(entry.name)
            if host and self.classify(host) in DELETE:
                shutil.rmtree(entry)
                done["site_data"] += 1
        local = [h for h in self._local_storage_hosts() if self.classify(h) in DELETE]
        if local:
            shutil.rmtree(self._default / "Local Storage")
            done["local_storage"] = len(local)
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
            if file.is_dir():
                shutil.rmtree(file)
            else:
                file.unlink()
            done["files"].append({"path": str(file), "removed": "file"})
        return done


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def for_config(config: dict[str, Any], profile: str | None = None, cache_dir: str | None = None,
               accounts: bool = False, keep_own: bool = False) -> ColdStart:
    """The cold start for the configured download profile (Chrome's own directory)
    and the configured cache. Another profile comes with only the cache named for
    it: the configured cache belongs to the configured profile."""
    from .config import DATA_DIR
    from .engine.batch_common import _resolve_profile_dir

    if profile:
        return ColdStart(Path(profile), Path(cache_dir) if cache_dir else None, config, accounts, keep_own)
    cache = cache_dir or config.get("cache_dir", str(DATA_DIR / "cache"))
    return ColdStart(chrome_profile_dir(_resolve_profile_dir(config)), Path(cache), config, accounts, keep_own)


# -- another school's sign-in --------------------------------------------------------------------
# Switched to another school, the download browser stayed signed in with the last one: the publisher's page opened
# through it, and the new school's account was never used (user, 2026-11-21). The school the browser last signed in
# with is kept; a download with another forgets that sign-in first, as a cold start does (the publishers' sessions and
# remembered schools with it; verification records, personal accounts and consent choices kept).

def _signed_in_path() -> Path:
    from .data_home import default_data_dir

    return default_data_dir() / "browser_school.json"


def signed_in_school() -> str:
    """The school the download browser last signed in with ("" not known)."""
    try:
        data = json.loads(_signed_in_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("school") or "") if isinstance(data, dict) else ""


def before_sign_in(config: dict[str, Any], *, always: bool = False) -> str:
    """Before a download signs in with ``config``'s school: the browser last signed in with another forgets that
    sign-in (``always``, the settings' 测试登录: whatever it was, so that the account is what the test tries).
    "cleared"; "" when there was nothing to forget (the same school, or none known yet: kept from now on); "busy"
    when the download browser is open (nothing changed)."""
    entity = str(config.get("idp_entity_id") or "").strip()
    if not entity:
        return ""
    last = signed_in_school()
    if not always and (not last or last == entity):
        if not last:
            _signed_in_path().parent.mkdir(parents=True, exist_ok=True)
            _write_json(_signed_in_path(), {"school": entity})
        return ""
    # The personal publisher accounts too: Elsevier's signs the next visit in with the last school's access. The school
    # about to sign in keeps its own sign-in, but not for a test (``always``): its account is what the test tries.
    run = for_config(config, accounts=True, keep_own=not always)
    try:
        run.apply()
    except RuntimeError:
        # A browser just closed (a batch's, for the next school) takes a few seconds to let go of the profile.
        from .browser.profiles import wait_for_profile_release

        if not wait_for_profile_release(str(run.profile), timeout=10):
            return "busy"
        try:
            run.apply()
        except RuntimeError:
            return "busy"
    _signed_in_path().parent.mkdir(parents=True, exist_ok=True)
    _write_json(_signed_in_path(), {"school": entity})
    return "cleared"
