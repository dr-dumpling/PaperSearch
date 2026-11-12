"""Identity federations: which one the user's school belongs to, how publishers'
choosers name it, and its own school-choosing pages.

The federation layer stands beside the publisher layers (engine, platforms,
publishers, journals; ADR 0014). Publisher rules never name a federation: they
ask the configured one whether a chooser's entry is it (``Federation.matches``).
Each federation is one data file in ``builtin/`` (``schema`` below); one whose
own pages need code gets a module of its own. No school is named here (ADR
0009): the school is the user's setting (``schools``).

``builtin/<code>.json``:

- ``code``: the value of ``publisher_institution_federation`` ("carsi").
- ``name``: its short name, as users and the records call it.
- ``country``: ISO 3166 code of the country it serves.
- ``registration_authorities``: its registrationAuthority in SAML metadata,
  which tells a school's federation in SeamlessAccess and eduGAIN.
- ``chooser_labels``: its entry on publishers' federation choosers, as seen;
  ``chooser_pattern`` (a regular expression) matches any of them.
- ``discovery_hosts``: its own school-choosing pages (none for most).
- ``service_domains``: the domains of its own services, which remember a
  chosen school (forgotten by a cold start).
- ``metadata_url``: its published member list (SAML metadata), for the
  schools' login hosts; empty when its own list is read instead
  (``member_list``: "carsi").
- ``kind``: "federation" (a national identity federation, the default) or
  "service" (OpenAthens: an identity service across countries, which the
  publisher layers know on their own and may name).
- ``secondary``: a school's entry here is used only when it has none in a
  federation (a school in both GakuNin and OpenAthens signs in through GakuNin).
- ``openathens_entries``: the publishers' "OpenAthens" sign-in entries and the
  OpenAthens wayfinder lead to the schools of this route.
- ``school_login_pages``: where its schools' own login pages begin on a service
  shared by all of them: ``{scope}`` stands for the school's domain, ``*`` for any
  one path segment (OpenAthens: ``https://login.openathens.net/auth/*/o/``, an
  organization's own sign-in page; its search page has no ``/o/``, and the
  segment is the organization's OpenAthens name, not always the school's domain).
- ``without_school``: it may be switched on with no school saved, the user
  choosing in the window (``setup --carsi``); any other route counts only once
  setup saved the school for it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

_BUILTIN = Path(__file__).with_name("builtin")


@dataclass(frozen=True)
class Federation:
    code: str
    name: str
    country: str
    registration_authorities: tuple[str, ...]
    chooser_labels: tuple[str, ...]
    chooser_pattern: re.Pattern[str]
    discovery_hosts: tuple[str, ...] = ()
    service_domains: tuple[str, ...] = ()
    metadata_url: str = ""
    member_list: str = ""
    kind: str = "federation"
    secondary: bool = False
    openathens_entries: bool = False
    without_school: bool = False
    school_login_pages: tuple[str, ...] = ()

    def matches(self, label: str) -> bool:
        """This federation's entry on a publisher's federation chooser."""
        return bool(self.chooser_pattern.search(" ".join(str(label or "").split())))

    def option_among(self, labels: Iterable[str]) -> str | None:
        """The one entry among ``labels`` that is this federation, else None."""
        hits = [label for label in labels if self.matches(label)]
        return hits[0] if len(hits) == 1 else None

    def on_discovery_page(self, url: str) -> bool:
        """``url`` is one of this federation's own school-choosing pages."""
        host = (urlparse(url or "").hostname or "").lower()
        return any(host == h or host.endswith("." + h) for h in self.discovery_hosts)


def _load(path: Path) -> Federation:
    data = json.loads(path.read_text(encoding="utf-8"))
    code = str(data["code"]).strip().lower()
    if code != path.stem:
        raise ValueError(f"{path.name}: code {code!r} differs from the file name")
    labels = tuple(str(label) for label in data.get("chooser_labels") or ())
    pattern = re.compile(str(data["chooser_pattern"]), re.I)
    for label in labels:
        if not pattern.search(label):
            raise ValueError(f"{path.name}: chooser_pattern does not match {label!r}")
    for template in data.get("school_login_pages") or ():
        if not ("{scope}" in str(template) or "*" in str(template)) or not str(template).startswith("https://"):
            raise ValueError(f"{path.name}: school_login_pages needs https:// and {{scope}} or *: {template!r}")
    return Federation(
        code=code,
        name=str(data["name"]),
        country=str(data["country"]).upper(),
        registration_authorities=tuple(str(ra).rstrip("/").lower() for ra in data["registration_authorities"]),
        chooser_labels=labels,
        chooser_pattern=pattern,
        discovery_hosts=tuple(str(h).lower() for h in data.get("discovery_hosts") or ()),
        service_domains=tuple(str(h).lower() for h in data.get("service_domains") or ()),
        metadata_url=str(data.get("metadata_url") or ""),
        member_list=str(data.get("member_list") or ""),
        kind=str(data.get("kind") or "federation"),
        secondary=bool(data.get("secondary")),
        openathens_entries=bool(data.get("openathens_entries")),
        without_school=bool(data.get("without_school")),
        school_login_pages=tuple(str(t) for t in data.get("school_login_pages") or ()),
    )


@lru_cache(maxsize=1)
def all_federations() -> tuple[Federation, ...]:
    """Every built-in federation, CARSI first (the default)."""
    found = [_load(path) for path in sorted(_BUILTIN.glob("*.json"))]
    return tuple(sorted(found, key=lambda f: (f.code != "carsi", f.code)))


def by_code(code: str | None) -> Federation | None:
    code = str(code or "").strip().lower()
    return next((f for f in all_federations() if f.code == code), None)


def by_registration_authority(authority: str) -> Federation | None:
    """The built-in federation that registered a school ("https://hkaf.edu.hk")."""
    key = str(authority or "").strip().rstrip("/").lower()
    return next((f for f in all_federations() if key in f.registration_authorities), None)


def configured(config: dict[str, Any]) -> Federation | None:
    """The federation the user's school belongs to (``publisher_institution_federation``);
    None when none is set, or a route other than one switched on ``without_school``
    has no school saved (a value an old config file may hold)."""
    federation = by_code(config.get("publisher_institution_federation"))
    if federation is None or federation.without_school or str(config.get("school_name") or "").strip():
        return federation
    return None


def on_discovery_page(url: str) -> bool:
    """``url`` is a built-in federation's own school-choosing page."""
    return any(federation.on_discovery_page(url) for federation in all_federations())


def service_domains() -> tuple[str, ...]:
    """Every built-in federation's own service domains."""
    return tuple(domain for federation in all_federations() for domain in federation.service_domains)
