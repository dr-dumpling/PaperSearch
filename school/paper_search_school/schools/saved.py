"""Several schools saved, one of them the current one (user, 2026-11-17: "以后我可以有几个学校的话，
可以随时进行一个切换"). The current school stays in the config's own fields, which all the code
reads (``SCHOOL_FIELDS``); ``saved_schools`` keeps each saved school's copy of them. Switching
writes the chosen copy back into those fields. A download may use another saved school for
itself alone (``apply`` on that download's config, not saved). Nothing switches on its own: only
when the user says so (user, 2026-11-17)."""
from __future__ import annotations

from typing import Any

# What `setup --institution` saves of a school (schools/lookup.py `save`).
SCHOOL_FIELDS = ("school_name", "school_name_en", "school_entry_name", "idp_entity_id", "idp_login_hosts",
                 "idp_login_pages", "idp_domains", "publisher_institution_federation", "carsi_enabled")
SAVED_KEY = "saved_schools"
MAX_SAVED = 20


def current(config: dict[str, Any]) -> dict[str, Any] | None:
    """The current school's fields; None when no school is set."""
    if not str(config.get("school_name") or config.get("idp_entity_id") or "").strip():
        return None
    return {key: config.get(key) for key in SCHOOL_FIELDS}


def saved(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The saved schools, each with at least its name; anything else in the list is left out."""
    raw = config.get(SAVED_KEY)
    if not isinstance(raw, list):
        return []
    return [{key: entry.get(key) for key in SCHOOL_FIELDS} for entry in raw
            if isinstance(entry, dict) and str(entry.get("school_name") or "").strip()][:MAX_SAVED]


def _same(one: dict[str, Any], other: dict[str, Any]) -> bool:
    """One school: the same entityID, else the same name."""
    ids = [str(entry.get("idp_entity_id") or "").strip().lower() for entry in (one, other)]
    if ids[0] and ids[1]:
        return ids[0] == ids[1]
    return str(one.get("school_name") or "").strip().casefold() == str(other.get("school_name") or "").strip().casefold()


def remember(config: dict[str, Any]) -> None:
    """The current school in the saved list (its copy brought up to date when already there)."""
    school = current(config)
    if school is None:
        return
    schools = saved(config)
    for index, entry in enumerate(schools):
        if _same(entry, school):
            schools[index] = school
            break
    else:
        schools.append(school)
    config[SAVED_KEY] = schools[:MAX_SAVED]


def _names(entry: dict[str, Any]) -> list[str]:
    domains = entry.get("idp_domains") if isinstance(entry.get("idp_domains"), list) else []
    return [str(value).strip() for value in (entry.get("school_name"), entry.get("school_name_en"),
                                            entry.get("school_entry_name"), entry.get("idp_entity_id"), *domains)
            if str(value or "").strip()]


def find(config: dict[str, Any], query: str) -> list[dict[str, Any]]:
    """The saved schools ``query`` names: by a whole name, English name, entityID or domain;
    else those whose names contain it. The current school is among them."""
    wanted = query.strip().casefold()
    if not wanted:
        return []
    remember(config)
    schools = saved(config)
    exact = [entry for entry in schools if any(name.casefold() == wanted for name in _names(entry))]
    return exact or [entry for entry in schools if any(wanted in name.casefold() for name in _names(entry))]


def apply(config: dict[str, Any], entry: dict[str, Any]) -> None:
    """``entry`` as the school of ``config`` (the current one once the config is saved)."""
    for key in SCHOOL_FIELDS:
        config[key] = entry.get(key)


def is_current(config: dict[str, Any], entry: dict[str, Any]) -> bool:
    school = current(config)
    return school is not None and _same(school, entry)


def summary(entry: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a listing says of a school: names, federation, entityID, whether current."""
    out = {"name": entry.get("school_name") or "", "name_en": entry.get("school_name_en") or "",
           "federation": entry.get("publisher_institution_federation") or "", "entity_id": entry.get("idp_entity_id") or ""}
    if config is not None:
        out["current"] = is_current(config, entry)
    return out


def use_for_download(config: dict[str, Any], query: str) -> str:
    """The saved school ``query`` names as ``config``'s school, for one download (the config is
    not saved); "" when done, else why not: school_not_saved, school_ambiguous."""
    matches = find(config, query)
    if len(matches) != 1:
        return "school_not_saved" if not matches else "school_ambiguous"
    apply(config, matches[0])
    return ""


def forget(config: dict[str, Any], entry: dict[str, Any]) -> bool:
    """``entry`` out of the saved list; the current school stays (False)."""
    if is_current(config, entry):
        return False
    config[SAVED_KEY] = [other for other in saved(config) if not _same(other, entry)]
    return True
