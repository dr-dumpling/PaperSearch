"""The user's school: what setup saved, and finding it by the name the user gave.

Setup saves the school's names, its SAML entityID, the hosts of its login
pages and the federation it belongs to. The config keys keep their first names
(``school_name``, ``school_name_en``): they hold the school of any federation.

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
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
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
    # The login entry's own name, when the school is named as the user named it: a
    # shared entry (a national one, "Feide") is listed by it on some choosers.
    entry_name: str = field(default="", compare=False)

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
    """The saved school's names: as its federation lists it, then in English, then
    its shared login entry's own name (a publisher's chooser listing login entries
    lists a national one by it, 2026-11-13)."""
    found = [str(config.get(key) or "").strip() for key in ("school_name", "school_name_en", "school_entry_name")]
    return tuple(dict.fromkeys(n for n in found if n))


def name(config: dict[str, Any]) -> str:
    """The saved school's name, typed into choosers ("" when none is saved)."""
    return str(config.get("school_name") or "").strip()


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
    # Its own sign-in page on a login service shared by schools (OpenAthens), named by
    # its domain: a publisher may list only that entry of the school (its library's,
    # 2026-11-14).
    pages += [template.replace("*", scope, 1) for service in all_federations()
              if service.kind == "service" and service is not federation
              for template in service.school_login_pages if "*" in template for scope in scopes if "." in scope]
    config.update(school_name=school.name, school_name_en=school.name_en, school_entry_name=school.entry_name,
                  idp_entity_id=school.entity_id, idp_login_hosts=list(school.login_hosts), idp_login_pages=pages,
                  idp_domains=[d for d in scopes if "." in d],
                  publisher_institution_federation=school.federation, carsi_enabled=school.federation == "carsi")


def institutional_configured(config: dict[str, Any]) -> bool:
    """Some institutional route is configured: a federation, or a school saved
    under the old switch (``carsi_enabled``) before federations were named."""
    return bool(configured(config) or (config.get("carsi_enabled") and name(config)))


# --------------------------------------------------------------------------- finding

def _plain(text: str) -> str:
    """Accents on Latin and Greek letters do not count ("Universite" listed for
    "Université", 2026-11-13); other scripts' marks (Japanese voicing) stay."""
    return unicodedata.normalize("NFC", re.sub(r"[\u0300-\u036f]", "", unicodedata.normalize("NFD", str(text or ""))))


def _key(text: str) -> str:
    """Case, spaces, hyphens, punctuation, accents and a leading "The" do not
    count; "&" is "and" (a school listed as "Science & Technology", 2026-11-12)."""
    text = re.sub(r"^the\s+", "", _plain(text).casefold().strip())
    return re.sub(r"[\W_]+", "", text.replace("&", " and "))


def _host(text: str) -> str:
    text = str(text or "").strip().lower()
    return (urlparse(text).hostname or "") if "://" in text else text.removeprefix("www.")


def _is_entity_id(text: str) -> bool:
    return text.startswith(("https://", "http://", "urn:"))


class _Found:
    """Candidates by entityID, an exact match outranking a partial one."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[School, bool]] = {}
        # The entries found by one of their names, not only by a domain or entityID.
        self.named: set[str] = set()

    def add(self, school: School, exact: bool, named: bool = True) -> None:
        if named:
            self.named.add(school.entity_id)
        known = self.rows.get(school.entity_id)
        if known is None or (exact and not known[1]):
            self.rows[school.entity_id] = (school, exact)

    def _primary(self) -> None:
        """A school also listed in a secondary route (OpenAthens) signs in through
        its federation: that entry goes (``_same_school``)."""
        primary = [s for s, _ in self.rows.values() if not _secondary(s)]
        for entity, (school, _) in list(self.rows.items()):
            if _secondary(school) and any(_same_school(school, p) for p in primary):
                del self.rows[entity]

    def decide(self) -> tuple[School | None, list[School]]:
        """The one exact match; else the candidates, a single partial match too:
        across federations a near name can be another school (a Chinese name
        matches a campus in CARSI, the school itself is listed in English)."""
        self._primary()
        exact = [s for s, e in self.rows.values() if e]
        if len(exact) > 1:
            exact = [_one_school(exact)] if _one_school(exact) else exact
        if len(exact) == 1:
            return exact[0], []
        if exact:
            return None, exact
        partial = [s for s, e in self.rows.values() if not e]
        return None, sorted(partial, key=lambda s: (len(s.name), s.name))


def _same_school(other: School, school: School) -> bool:
    """``other`` is ``school`` listed again: under its domain or a host of it (its
    library's), or under its name, an abbreviation in brackets aside, with a domain
    of the same country (2026-11-12: two countries' universities share a name)."""
    if any(o == d or o.endswith("." + d) for o in other.scopes for d in school.scopes):
        return True
    name = _key(_BRACKET.sub(" ", other.name_en))
    if not name or name != _key(_BRACKET.sub(" ", school.name_en)):
        return False
    if not (other.scopes and school.scopes):
        return True
    return bool({d.rsplit(".", 1)[-1] for d in other.scopes} & {d.rsplit(".", 1)[-1] for d in school.scopes})


def _one_school(schools: list[School]) -> School | None:
    """One school listed several times in one federation under a domain of its own
    (a second login server, an alumni-only one: 2026-11-13): its entry with the
    plainest name, the one the others' names contain. A shared entry (a national
    one covering the school's domain) has another name and keeps them apart."""
    if len({s.federation for s in schools}) != 1 or not set.intersection(*(set(s.scopes) for s in schools)):
        return None
    plain = min(schools, key=lambda s: (len(s.name), s.name))
    return plain if all(_key(plain.name) in _key(s.name) for s in schools) else None


def _secondary(school: School) -> bool:
    federation = by_code(school.federation)
    return bool(federation and federation.secondary)


# An entry its federation marks as not for use (an old server, a test).
_RETIRED = re.compile(r"\bdo not use\b|\btest\b|\blegacy\b", re.I)


_PARTS = re.compile(r"\s+[-\u2013\u2014]\s+")
_BRACKET = re.compile(r"\(([^()]+)\)")
# Chinese, Japanese and Korean writing, beside a name in Latin letters.
# A word naming the login server, not the school, at the end of a listed name
# ("<School> IdP", "<entry> Single Sign-On Service": 2026-11-13).
_SERVER_WORD = re.compile(r"\s+(?:IdP|Identity\s+Provider|SSO|Single\s+Sign[- ]?On(?:\s+Service)?)$", re.I)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af][\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\s・·]*")


def _names(titles: Iterable[str]) -> list[str]:
    """The names a school is listed under, and their parts: "NHU - National
    Harbour University" (an abbreviation before the name), "北大学 (Kita
    University) – OpenAthens" (a second name in brackets, the route after a dash),
    "National Harbour Bay University (NHBU) 海灣大學" (brackets inside, and a name in
    another script beside the English one: OpenAthens in Taiwan, 2026-11-12),
    "Harbour University IdP" (the login server's word after the name)."""
    names = [str(t).strip() for t in titles if str(t or "").strip()]
    found = list(names)
    for name in names:
        for part in _PARTS.split(name):
            part = part.strip()
            outside = re.sub(r"\s+", " ", _BRACKET.sub(" ", part)).strip()
            found += [part, outside, _SERVER_WORD.sub("", outside), *(m.strip() for m in _BRACKET.findall(part))]
            if _CJK.search(outside) and re.search(r"[A-Za-z]{2}", _CJK.sub(" ", outside)):
                found += [m.strip() for m in _CJK.findall(outside)] + [re.sub(r"\s+", " ", _CJK.sub(" ", outside)).strip()]
    return list(dict.fromkeys(n for n in found if n))


def _words(text: str) -> list[str]:
    """The words of a name, as ``_key`` compares them."""
    words = [w for w in re.split(r"[\W_]+", _plain(text).casefold().replace("&", " and ")) if w]
    return words[1:] if words[:1] == ["the"] else words


def _listed_inside(text: str, listed_names: Iterable[str]) -> bool:
    """A listed name of two words or more found word for word in what was given:
    a school listed shorter than its full name ("Kita Bay" for "Kita Bay
    University", 2026-11-12), only ever asked about."""
    given = _words(text)
    for name in listed_names:
        part = _words(name)
        if len(part) >= 2 and any(given[i:i + len(part)] == part for i in range(len(given) - len(part) + 1)):
            return True
    return False


def _matches(given: Iterable[str], listed_names: Iterable[str], scopes: Iterable[str], entity: str) -> tuple[bool, bool]:
    """(exact, partial) for what was given against one listed school."""
    listed_names = list(listed_names)
    keys = {_key(n) for n in listed_names} - {""}
    hosts = {s.lower() for s in scopes if s}
    exact = partial = False
    for text in given:
        key, host = _key(text), _host(text)
        if not key:
            continue
        if text == entity or key in keys or host in hosts:
            exact = True
        elif (any(key in k for k in keys) or any(host and host in h for h in hosts)
              or _listed_inside(text, listed_names)):
            partial = True
    return exact, partial and not exact


def _from_school_list(given: list[str], config: dict[str, Any], data_dir: Path, found: _Found, lookup: Lookup) -> None:
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
    # Its search keeps accents: a name given with them is also searched without
    # ("Université" listed as "Universite", 2026-11-13).
    for text in dict.fromkeys([*given, *(_plain(t) for t in given)]):
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
            english = listed_english = _SERVER_WORD.sub("", str((row.get("title_langs") or {}).get("en") or title)).strip()
            part = ""
            if exact:
                # The English name given, publishers' likelier name for the school, when the
                # list has none of its own: the school only as part of a longer name ("<school>
                # - Staff", "<ABBR> - <school>"), or one name in every language ("Universitat de
                # Liman", 2026-11-13). The names given beside the first are the English ones;
                # accents allowed ("University of São Liman", 2026-11-14).
                listed = {_key(v) for v in [*(row.get("title_langs") or {}).values(), title] if str(v or "").strip()}
                own = _own_names(given)
                parts = {_key(n) for n in titles}
                part = next((" ".join(t.split()) for t in own if _key(t) in parts and _key(t) not in listed), "")
                other = [t for t in [*own[1:], *own[:1]] if _plain(t).isascii() and _key(t) not in listed]
                english = other[0] if other and (part or len(listed) == 1) else listed_english
            # The name in the school's own language when that is the one given: publishers
            # may list it so (a French name searched in English found nothing, 2026-11-13).
            # Spaces as written once (a Greek name listed with a trailing space, 2026-11-13).
            local = next((" ".join(str(v).split()) for k, v in (row.get("title_langs") or {}).items()
                          if k != "en" and any(_key(t) == _key(v) for t in given)), listed_english)
            found.add(School(local, english, entity, federation.code, scopes[0] if scopes else "",
                             scopes=tuple(scopes)), exact, named=_named(given, titles))


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
        english = _SERVER_WORD.sub("", display.get("en") or (organization[0] if organization else entity_id)).strip()
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
                found.add(school, exact, named=_named(given, listed))


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
    return replace(school, domain=school.domain or listed.domain, login_hosts=listed.login_hosts)


def _named(given: Iterable[str], listed_names: Iterable[str]) -> bool:
    """One of the names given is one the entry is listed under."""
    keys = {_key(n) for n in listed_names} - {""}
    return any(_key(t) in keys for t in given)


def _own_names(given: Iterable[str]) -> list[str]:
    """What was given as the school's names: no entityID, no domain."""
    return [t for t in given if not _is_entity_id(t) and not re.fullmatch(r"[\w-]+(?:\.[\w-]+)+", t)]


def _named_as_given(school: School, given: list[str]) -> School:
    """A school found only by its domain, under a login entry many schools share
    (a school system's ID, a national entry: 2026-11-13), is named as the user named it: that
    name is what publishers' choosers list it under. Its English name is the one
    given beside it, accents allowed, else the first name if in Latin letters, else
    the entry's: a name in the school's own language may be ASCII ("Kitan
    yliopisto" beside "Kita University", 2026-11-13)."""
    own = _own_names(given)
    if not own:
        return school
    english = next((t for t in [*own[1:], own[0]] if _plain(t).isascii()), school.name_en)
    return replace(school, name=own[0], name_en=english, entry_name=school.name)


def _named_by_its_part(school: School, given: list[str]) -> School:
    """A school listed under a longer name, an abbreviation or code beside the
    school's ("<ABBR> - <school>", "<school> - <code>", 2026-11-14), and found by
    that part: named as given, the name publishers list it under; the listed name
    is its entry's own, searched last."""
    parts = {_key(n) for n in _names([school.name])}
    part = next((" ".join(t.split()) for t in _own_names(given)
                 if _key(t) in parts and _key(t) != _key(school.name)), "")
    return replace(school, name=part, entry_name=school.name) if part else school


def find(query: str, config: dict[str, Any], data_dir: Path, *, also: Iterable[str] = ()) -> Lookup:
    """The school named ``query`` (any language, its domain or entityID), with
    ``also`` its other names (the English one, given by the caller)."""
    given = list(dict.fromkeys(t.strip() for t in (query, *also) if t and t.strip()))
    lookup, found = Lookup(), _Found()
    if not given:
        return lookup
    _from_school_list(given, config, data_dir, found, lookup)
    _from_seamlessaccess(given, config, found, lookup, carsi_listed="CARSI" not in lookup.unavailable)
    if "SeamlessAccess" in lookup.unavailable:
        _from_metadata(given, config, data_dir, found, lookup)
    school, candidates = found.decide()
    if school is not None and school.entity_id not in found.named:
        school = _named_as_given(school, given)
    elif school is not None:
        school = _named_by_its_part(school, given)
    lookup.school = _with_login_hosts(school, config, data_dir) if school else None
    lookup.candidates = candidates[:10]
    return lookup
