"""The CARSI member list, for choosing the user's school at setup.

CARSI's discovery page loads every member school from ``idpselect.js``:
entityID, Chinese and English name, domain and pinyin. ``setup`` looks the
user's school up there and saves its names and entityID; the package ships
no copy of the list and names no school itself (ADR 0009).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHOOL_LIST_URL = "https://ds.carsi.edu.cn/login/js/idpselect.js"
CACHE_FILE = "carsi_school_list.js"
CACHE_MAX_AGE_SEC = 7 * 24 * 3600

_GROUP = re.compile(r"IdPList\[\d+\]\s*=\s*")


@dataclass(frozen=True)
class CarsiSchool:
    entity_id: str
    name: str
    name_en: str
    domain: str
    pinyin: str = ""

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "name_en": self.name_en, "domain": self.domain, "entity_id": self.entity_id}


def parse_school_list(text: str) -> list[CarsiSchool]:
    """Schools in ``idpselect.js`` (``IdPList[n]=[{...}, ...];`` groups)."""
    decoder = json.JSONDecoder()
    schools: list[CarsiSchool] = []
    for match in _GROUP.finditer(text):
        rows, _ = decoder.raw_decode(text, match.end())
        for row in rows:
            entity_id = str(row.get("entityID") or "").strip()
            name = str(row.get("IdP_CN") or "").strip()
            if entity_id and name:
                schools.append(CarsiSchool(entity_id, name, str(row.get("IdP_EN") or "").strip(),
                                           str(row.get("dns") or "").strip().lower(),
                                           str(row.get("IdP_CN_PY") or "").strip()))
    if not schools:
        raise ValueError("no schools found in the CARSI list; its format may have changed")
    return schools


def load_school_list(config: dict[str, Any], data_dir: Path) -> list[CarsiSchool]:
    """The member list, from the data directory's copy while it is under a week old."""
    cache = Path(data_dir) / CACHE_FILE
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_MAX_AGE_SEC:
        return parse_school_list(cache.read_text(encoding="utf-8"))
    from .network import fetch

    response = fetch(SCHOOL_LIST_URL, config)
    response.raise_for_status()
    schools = parse_school_list(response.text)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(response.text, encoding="utf-8")
    return schools


def _key(text: str) -> str:
    """Case, spaces, hyphens and punctuation do not count ("Example-Normal University" = "example normal university")."""
    return re.sub(r"[\W_]+", "", text.casefold())


def find_schools(schools: list[CarsiSchool], query: str) -> tuple[list[CarsiSchool], list[CarsiSchool]]:
    """(exact, partial) matches for what the user typed.

    Exact: the entityID, the Chinese or English name, the pinyin, or the
    domain (``example.edu.cn`` or ``example``). Partial: the query appears in
    one of the names, the pinyin or the domain; shortest names first.
    """
    text = query.strip()
    if not text:
        return [], []
    exact = [s for s in schools if s.entity_id == text]
    if exact:
        return exact, []
    key = _key(text)
    host = text.lower().removeprefix("www.")
    if not key:
        return [], []
    exact = [s for s in schools
             if key in {_key(s.name), _key(s.name_en), _key(s.pinyin)} or host in {s.domain, s.domain.split(".")[0]}]
    partial = [s for s in schools if s not in exact and (
        key in _key(s.name) or key in _key(s.name_en) or key in _key(s.pinyin) or host in s.domain)]
    partial.sort(key=lambda s: (len(s.name), s.name))
    return exact, partial


def choose_school(schools: list[CarsiSchool], query: str) -> tuple[CarsiSchool | None, list[CarsiSchool]]:
    """(the school, candidates): one exact match, else the only partial match; otherwise no school and the candidates."""
    exact, partial = find_schools(schools, query)
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, exact
    if len(partial) == 1:
        return partial[0], []
    return None, partial
