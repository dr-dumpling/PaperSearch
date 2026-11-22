"""没权限时换下一所学校 (PaperSearch Pro; user, 2026-11-21).

An article the school signed in to but has no access to (its publisher says so) is tried with the next saved school:
one Pro fills the sign-in of, its account saved and its auto sign-in on; the default school first, then the list's
order. A journal one of them got is remembered for the rest of the download task (a batch; a single download is a task
of its own) and tried with it first; a task starts again from the default school. Only "no access" switches: a sign-in
that failed (a wrong password, a code to type, a page that stopped it) is the user's to see, not another account's.
Each switch forgets the sign-in before it (cold_start.before_sign_in), the batch's browser closed first to let go of it.
"""
from __future__ import annotations

from typing import Any

#: The switch on the sign-in page (config), on unless turned off.
SETTING = "school_switch"

#: (task, journal) -> the entityID of the school that got the journal's article in that task.
_GOT: dict[tuple[str, str], str] = {}


def enabled(config: dict[str, Any]) -> bool:
    return config.get(SETTING) is not False


def no_access(result: dict[str, Any] | None) -> bool:
    """Signed in, and the publisher has no access for the school to this article (not a sign-in that failed)."""
    return bool(result) and not result.get("success") and result.get("error_type") == "paywall" \
        and result.get("reason_code") == "institution_pdf_entitlement_missing"


def schools(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The schools taking part, in order: the default one, then each other saved school Pro fills the sign-in of, its
    account saved and its auto sign-in on. [] without Pro."""
    from . import school_login
    from .schools import saved as saved_schools

    pro = school_login.module()
    if pro is None:
        return []
    saved_schools.remember(config)
    listed = saved_schools.saved(config)
    current = [entry for entry in listed if saved_schools.is_current(config, entry)]
    order: list[dict[str, Any]] = current[:]
    for entry in listed:
        entity = str(entry.get("idp_entity_id") or "").strip()
        if entry in current or not entity:
            continue
        account = school_login.saved(config, entity) or {}
        if account.get("enabled") and school_login.fills_for(entity, pro):
            order.append(entry)
    return order


def grouping(config: dict[str, Any]) -> bool:
    """Whether a batch takes one journal's papers one after another: on, and more than one school taking part."""
    return enabled(config) and len(schools(config)) > 1


def _task() -> str:
    from . import progress_reporter

    return progress_reporter.batch_id()


def journal(doi: str) -> str:
    """The journal's key: its ISSNs (Crossref, kept), else its title; "" when not known."""
    from .entitlements import journal_identity

    try:
        identity = journal_identity(doi)
    except Exception:
        return ""
    issns = identity.get("issn") or []
    return "issn:" + ",".join(sorted(issns)) if issns else str(identity.get("journal") or "").strip().lower()


def remembered(doi: str) -> str:
    """The school (entityID) that got this article's journal earlier in this task; "" when none or not in a task."""
    task = _task()
    key = journal(doi) if task else ""
    return _GOT.get((task, key), "") if key else ""


def remember(doi: str, entity: str) -> None:
    task = _task()
    key = journal(doi) if task and entity else ""
    if key:
        _GOT[(task, key)] = entity


def order_for(config: dict[str, Any], doi: str) -> list[dict[str, Any]]:
    """The schools to try for this article, in turn: its journal's school of this task first, then the default one
    and the rest."""
    listed = schools(config)
    if len(listed) < 2:
        return listed  # nothing to switch to: no journal looked up
    first = remembered(doi)
    return sorted(listed, key=lambda entry: str(entry.get("idp_entity_id") or "").strip() != first) if first else listed


def name(entry: dict[str, Any]) -> str:
    return str(entry.get("school_name") or entry.get("school_name_en") or entry.get("idp_entity_id") or "")
