"""The user's school: what setup saved, and finding it by the name the user gave.

Setup saves the school's names, its SAML entityID, the hosts of its login
pages and the federation it belongs to. The config keys keep their first names
(``carsi_idp_name``, ``carsi_idp_name_en``): they hold the school of any federation.

Finding a school reads only the federations' own data (the user, 2026-11-11):
CARSI's member list, SeamlessAccess's index of the schools of eduGAIN's
federations, and a federation's own member list (its SAML metadata). A school
without a login entry there cannot sign in through a federation at all, so no
other source is asked. The names a school is listed under are its federation's
(the local language and English); a name in another language comes with the
school's English name from the caller (``also``).

One rule decides: one school whose name (or domain, or entityID) is exactly
what was given is the school; otherwise the matches are candidates for the
user to pick from once, a single partial match too (see ``_Found.decide``).
"""
from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

from . import Federation, all_federations, by_code, by_registration_authority, configured

SEAMLESSACCESS = "https://md.seamlessaccess.org/entities/"
METADATA_MAX_AGE_SEC = 7 * 24 * 3600
_NS = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "shibmd": "urn:mace:shibboleth:metadata:1.0",
       "mdui": "urn:oasis:names:tc:SAML:metadata:ui", "mdrpi": "urn:oasis:names:tc:SAML:metadata:rpi"}
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


@dataclass(frozen=True)
class School:
    name: str
    name_en: str
    entity_id: str
    federation: str
    domain: str = ""
    login_hosts: tuple[str, ...] = ()
    # Every domain the school's entry is registered for (tells the same school in two routes).
    scopes: tuple[str, ...] = field(default=(), compare=False)

    def summary(self) -> dict[str, str]:
        federation = by_code(self.federation)
        return {"name": self.name, "name_en": self.name_en, "federation": federation.name if federation else self.federation,
                "country": federation.country if federation else "", "domain": self.domain, "entity_id": self.entity_id}


@dataclass
class Lookup:
    school: School | None = None
    candidates: list[School] = field(default_factory=list)
    # Exact matches in federations not supported yet: (school name, its registrationAuthority).
    unsupported: list[tuple[str, str]] = field(default_factory=list)
    # Sources that could not be read, by name.
    unavailable: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- saved

def names(config: dict[str, Any]) -> tuple[str, ...]:
    """The saved school's names: as its federation lists it, then in English."""
    found = [str(config.get(key) or "").strip() for key in ("carsi_idp_name", "carsi_idp_name_en")]
    return tuple(dict.fromkeys(n for n in found if n))


def name(config: dict[str, Any]) -> str:
    """The saved school's name, typed into choosers ("" when none is saved)."""
    return str(config.get("carsi_idp_name") or "").strip()


def login_hosts(config: dict[str, Any]) -> tuple[str, ...]:
    """The hosts of the saved school's login pages: its entityID's host
    (``https://idp.example.edu.cn/idp/shibboleth`` -> ``idp.example.edu.cn``) and
    the login hosts its federation lists for it; empty without one."""
    hosts = [str(h).strip().lower() for h in config.get("idp_login_hosts") or () if str(h).strip()]
    entity_id = str(config.get("idp_entity_id", "") or "").strip()
    if entity_id.startswith("https://"):
        hosts.insert(0, (urlparse(entity_id).hostname or "").lower())
    return tuple(dict.fromkeys(h for h in hosts if h))


def domains(config: dict[str, Any]) -> tuple[str, ...]:
    """The saved school's own domains (its entry's scopes): any page under them is
    the school's side of the login, its portal and single sign-on included
    (a portal on another host of the school's domain, 2026-11-11)."""
    return tuple(str(d).strip().lower().lstrip(".") for d in config.get("idp_domains") or () if str(d).strip())


def login_pages(config: dict[str, Any]) -> tuple[str, ...]:
    """Where the saved school's own login pages begin on a service shared by many
    schools (its OpenAthens sign-in page), saved by setup from its route's data;
    ``*`` stands for any one path segment."""
    return tuple(str(p).strip().lower() for p in config.get("idp_login_pages") or () if str(p).strip())


def on_login_page(config: dict[str, Any], url: str) -> bool:
    """``url`` begins with one of the saved school's login pages (``login_pages``)."""
    lower = str(url or "").lower()
    for page in login_pages(config):
        pattern = re.escape(page).replace(r"\*", "[^/?#]+")
        if re.match(pattern, lower):
            return True
    return False


def entity_id(config: dict[str, Any], data_dir: Path) -> str:
    """The saved school's entityID: ``idp_entity_id``, else, for a CARSI school
    saved by name only (before setup used the member list), CARSI's entry for
    that name in the copy of its list setup saved (a download never fetches it)."""
    configured_id = str(config.get("idp_entity_id") or "").strip()
    if configured_id:
        return configured_id
    saved = name(config)
    if not saved:
        return ""
    from ..carsi_schools import CACHE_FILE, choose_school, parse_school_list

    cache = Path(data_dir) / CACHE_FILE
    if not cache.is_file():
        return ""
    try:
        school, _ = choose_school(parse_school_list(cache.read_text(encoding="utf-8")), saved)
    except ValueError:
        return ""
    return school.entity_id if school else ""


def save(config: dict[str, Any], school: School) -> None:
    """Make ``school`` the user's school, with its federation."""
    federation = by_code(school.federation)
    scopes = school.scopes or ((school.domain,) if school.domain else ())
    pages = [page for template in (federation.school_login_pages if federation else ())
             for page in ([template.replace("{scope}", scope) for scope in scopes] if "{scope}" in template
                          else [template])]
    config.update(carsi_idp_name=school.name, carsi_idp_name_en=school.name_en, idp_entity_id=school.entity_id,
                  idp_login_hosts=list(school.login_hosts), idp_login_pages=pages,
                  idp_domains=[d for d in scopes if "." in d],
                  publisher_institution_federation=school.federation, carsi_enabled=school.federation == "carsi")


def institutional_configured(config: dict[str, Any]) -> bool:
    """Some institutional route is configured: a federation, or a school saved
    under the old switch (``carsi_enabled``) before federations were named."""
    return bool(configured(config) or (config.get("carsi_enabled") and name(config)))


# --------------------------------------------------------------------------- finding

def _key(text: str) -> str:
    """Case, spaces, hyphens, punctuation and a leading "The" do not count."""
    return re.sub(r"[\W_]+", "", re.sub(r"^the\s+", "", str(text or "").casefold().strip()))


def _host(text: str) -> str:
    text = str(text or "").strip().lower()
    return (urlparse(text).hostname or "") if "://" in text else text.removeprefix("www.")


def _is_entity_id(text: str) -> bool:
    return text.startswith(("https://", "http://", "urn:"))


class _Found:
    """Candidates by entityID, an exact match outranking a partial one."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[School, bool]] = {}

    def add(self, school: School, exact: bool) -> None:
        known = self.rows.get(school.entity_id)
        if known is None or (exact and not known[1]):
            self.rows[school.entity_id] = (school, exact)

    def _primary(self) -> None:
        """A school also listed in a secondary route (OpenAthens) under the same
        domain or name signs in through its federation: that entry goes."""
        primary = [s for s, _ in self.rows.values() if not _secondary(s)]
        domains = {d for s in primary for d in s.scopes}
        names = {_key(s.name_en) for s in primary}
        for entity, (school, _) in list(self.rows.items()):
            if _secondary(school) and (set(school.scopes) & domains or _key(school.name_en) in names):
                del self.rows[entity]

    def decide(self) -> tuple[School | None, list[School]]:
        """The one exact match; else the candidates, a single partial match too:
        across federations a near name can be another school (a Chinese name
        matches a campus in CARSI, the school itself is listed in English)."""
        self._primary()
        exact = [s for s, e in self.rows.values() if e]
        if len(exact) == 1:
            return exact[0], []
        if exact:
            return None, exact
        partial = [s for s, e in self.rows.values() if not e]
        return None, sorted(partial, key=lambda s: (len(s.name), s.name))


def _secondary(school: School) -> bool:
    federation = by_code(school.federation)
    return bool(federation and federation.secondary)


# An entry its federation marks as not for use (an old server, a test).
_RETIRED = re.compile(r"\bdo not use\b|\btest\b|\blegacy\b", re.I)


_PARTS = re.compile(r"\s+[-\u2013\u2014]\s+")
_BRACKETED = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


def _names(titles: Iterable[str]) -> list[str]:
    """The names a school is listed under, and their parts: "NHU - National
    Harbour University" (an abbreviation before the name), "北大学 (Kita
    University) – OpenAthens" (a second name in brackets, the route after a dash)."""
    names = [str(t).strip() for t in titles if str(t or "").strip()]
    found = list(names)
    for name in names:
        for part in _PARTS.split(name):
            bracketed = _BRACKETED.match(part.strip())
            found += [part.strip(), *([bracketed.group(1).strip(), bracketed.group(2).strip()] if bracketed else [])]
    return list(dict.fromkeys(n for n in found if n))


def _matches(given: Iterable[str], listed_names: Iterable[str], scopes: Iterable[str], entity: str) -> tuple[bool, bool]:
    """(exact, partial) for what was given against one listed school."""
    keys = {_key(n) for n in listed_names} - {""}
    hosts = {s.lower() for s in scopes if s}
    exact = partial = False
    for text in given:
        key, host = _key(text), _host(text)
        if not key:
            continue
        if text == entity or key in keys or host in hosts:
            exact = True
        elif any(key in k for k in keys) or any(host and host in h for h in hosts):
            partial = True
    return exact, partial and not exact


def _from_carsi_list(given: list[str], config: dict[str, Any], data_dir: Path, found: _Found, lookup: Lookup) -> None:
    from ..carsi_schools import find_schools, load_school_list

    try:
        schools = load_school_list(config, data_dir)
    except Exception:
        lookup.unavailable.append("CARSI")
        return
    for text in given:
        exact, partial = find_schools(schools, text)
        for school, is_exact in [(s, True) for s in exact] + [(s, False) for s in partial]:
            found.add(School(school.name, school.name_en, school.entity_id, "carsi", school.domain), is_exact)


def _seamlessaccess(text: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    from ..network import fetch

    url = (SEAMLESSACCESS + quote("{sha1}" + hashlib.sha1(text.encode()).hexdigest(), safe="")
           if _is_entity_id(text) else SEAMLESSACCESS + "?q=" + quote(text))
    response = fetch(url, config, headers={"Accept": "application/json"})
    if response.status_code == 404:
        return []
    response.raise_for_status()
    rows = response.json()
    return [rows] if isinstance(rows, dict) else [r for r in rows if isinstance(r, dict)]


def _from_seamlessaccess(given: list[str], config: dict[str, Any], found: _Found, lookup: Lookup,
                         carsi_listed: bool) -> None:
    for text in given:
        try:
            rows = _seamlessaccess(text, config)
        except Exception:
            if "SeamlessAccess" not in lookup.unavailable:
                lookup.unavailable.append("SeamlessAccess")
            return
        for row in rows:
            entity = str(row.get("entity_id") or row.get("entityID") or "")
            title = str(row.get("title") or "")
            if (row.get("type") != "idp" or not entity or str(row.get("hidden")).lower() == "true"
                    or _RETIRED.search(title)):
                continue
            titles = _names([*(row.get("title_langs") or {}).values(), title])
            scopes = [s.strip().lower() for s in str(row.get("scope") or row.get("domain") or "").split(",") if s.strip()]
            exact, partial = _matches([text], titles, scopes, entity)
            if not (exact or partial):
                continue
            authorities = [str(a) for a in row.get("registrationAuthority") or ()]
            federation = next((f for f in map(by_registration_authority, authorities) if f), None)
            if federation is None:
                if exact:
                    lookup.unsupported.append((title or entity, ", ".join(authorities)))
                continue
            if federation.member_list == "carsi" and carsi_listed:
                continue  # CARSI's own list is the source for its schools
            english = str((row.get("title_langs") or {}).get("en") or title)
            found.add(School(english, english, entity, federation.code, scopes[0] if scopes else "",
                             scopes=tuple(scopes)), exact)


def _metadata(federation: Federation, config: dict[str, Any], data_dir: Path) -> ET.Element:
    """The federation's member list (SAML metadata), from a copy under a week old."""
    cache = Path(data_dir) / f"federation-{federation.code}.xml"
    if cache.exists() and time.time() - cache.stat().st_mtime < METADATA_MAX_AGE_SEC:
        return ET.fromstring(cache.read_bytes())
    from ..network import fetch

    response = fetch(federation.metadata_url, config)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(response.content)
    return root


def _metadata_schools(federation: Federation, root: ET.Element) -> list[tuple[School, list[str], list[str]]]:
    """(school, its names, its scopes) for every school in a federation's metadata."""
    schools = []
    for entity in root.iter(f"{{{_NS['md']}}}EntityDescriptor"):
        idp = entity.find("md:IDPSSODescriptor", _NS)
        entity_id = entity.get("entityID") or ""
        if idp is None or not entity_id:
            continue
        display = {n.get(_LANG) or "": (n.text or "").strip()
                   for n in idp.findall("md:Extensions/mdui:UIInfo/mdui:DisplayName", _NS)}
        organization = [(n.text or "").strip() for n in entity.findall("md:Organization/md:OrganizationDisplayName", _NS)]
        listed = _names([*display.values(), *organization])
        english = display.get("en") or (organization[0] if organization else entity_id)
        if _RETIRED.search(english):
            continue
        scopes = [(s.text or "").strip().lower() for s in idp.findall("md:Extensions/shibmd:Scope", _NS)]
        locations = ((urlparse(s.get("Location") or "").hostname or "").lower()
                     for s in idp.findall("md:SingleSignOnService", _NS))
        hosts = tuple(dict.fromkeys(h for h in locations if h))
        schools.append((School(english, english, entity_id, federation.code, scopes[0] if scopes else "", hosts,
                               tuple(scopes)), listed, scopes))
    return schools


def _from_metadata(given: list[str], config: dict[str, Any], data_dir: Path, found: _Found, lookup: Lookup) -> None:
    """Each federation's own member list, when SeamlessAccess could not be read."""
    for federation in all_federations():
        if not federation.metadata_url:
            continue
        try:
            root = _metadata(federation, config, data_dir)
        except Exception:
            lookup.unavailable.append(federation.name)
            continue
        for school, listed, scopes in _metadata_schools(federation, root):
            exact, partial = _matches(given, listed, scopes, school.entity_id)
            if exact or partial:
                found.add(school, exact)


def _with_login_hosts(school: School, config: dict[str, Any], data_dir: Path) -> School:
    """The school with the hosts of its login pages from its federation's metadata."""
    federation = by_code(school.federation)
    if school.login_hosts or federation is None or not federation.metadata_url:
        return school
    try:
        root = _metadata(federation, config, data_dir)
    except Exception:
        return school  # its entityID's host still tells its login page
    listed = next((s for s, _, _ in _metadata_schools(federation, root) if s.entity_id == school.entity_id), None)
    if listed is None:
        return school
    return School(school.name, school.name_en, school.entity_id, school.federation,
                  school.domain or listed.domain, listed.login_hosts, school.scopes)


def find(query: str, config: dict[str, Any], data_dir: Path, *, also: Iterable[str] = ()) -> Lookup:
    """The school named ``query`` (any language, its domain or entityID), with
    ``also`` its other names (the English one, given by the caller)."""
    given = list(dict.fromkeys(t.strip() for t in (query, *also) if t and t.strip()))
    lookup, found = Lookup(), _Found()
    if not given:
        return lookup
    _from_carsi_list(given, config, data_dir, found, lookup)
    _from_seamlessaccess(given, config, found, lookup, carsi_listed="CARSI" not in lookup.unavailable)
    if "SeamlessAccess" in lookup.unavailable:
        _from_metadata(given, config, data_dir, found, lookup)
    school, candidates = found.decide()
    lookup.school = _with_login_hosts(school, config, data_dir) if school else None
    lookup.candidates = candidates[:10]
    return lookup
