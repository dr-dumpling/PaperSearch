"""没权限时换下一所学校 (PaperSearch Pro; user, 2026-11-21).

A paper the school has no access to, failed under 没权限 (signed in and refused, the school's sign-in not enabled for
the publisher, no route for it there, or marked by the user as without access), is tried with the next saved school:
one Pro fills the sign-in of, its account saved and its auto sign-in on; the default school first, then the list's
order. A download on its own switches at once. A batch switches once at its end (download/batch/batch.ts): its papers
all with the default school, then those without access together with the next school, and so on (user, 2026-11-22:
switching to and fro at each paper had a school's login ask for a picture code). Only 没权限 switches: a sign-in that
failed (a wrong password, a code to type, a page that stopped it) is the user's to see, not another account's. Each
switch forgets the sign-in before it (cold_start.before_sign_in), the batch's browser closed first to let go of it.
"""
from __future__ import annotations

from typing import Any

#: The switch on the sign-in page (config), on unless turned off.
SETTING = "school_switch"

#: 没权限 besides a refusal after the sign-in (failureClass.ts): the school's sign-in not enabled for the publisher (IEEE
#: "Your institution may not be enabled", AHA's OpenAthens "restricted by your organization"), the publisher with no route
#: for it, or the user's mark, made with the default school. Another school may have it (user, 2026-11-22: IEEE was not
#: tried with the second school; every paper under 没权限 is).
NOT_THIS_SCHOOL = ("institution_not_registered", "institution_federation_unavailable", "no_entitlement")

#: Set on a download's config when its school is not the default one: the user's 没权限 marks were made with the
#: default school and do not skip another's visit (engine/bridge.py).
MARKS_OFF = "no_access_marks_off"


def enabled(config: dict[str, Any]) -> bool:
    return config.get(SETTING) is not False


def no_access(result: dict[str, Any] | None) -> bool:
    """The school has no access to this article, a 没权限 failure (not a sign-in that failed)."""
    if not result or result.get("success"):
        return False
    if result.get("error_type") in NOT_THIS_SCHOOL:
        return True
    return result.get("error_type") == "paywall" and result.get("reason_code") == "institution_pdf_entitlement_missing"


#: A failure after one of the school's entries by one name, its next entry to be tried (user, 2026-11-22: "同名学校的话，
#: 那就直接选一个……如果这个不行的话，再向下一个"): 没权限, or the login not reached or not finished (JAMA's first
#: entry of a test school was its library proxy, whose sign-in asks for a picture code).
ENTRY_DID_NOT_DO = ("login_not_reached", "login_timeout", "idp_no_return_to_publisher")


def entry_did_not_do(result: dict[str, Any] | None) -> bool:
    """The download failed after one of several entries by the school's name: the next one may do."""
    return bool(result) and not result.get("success") and int(result.get("same_name_entries") or 0) > 1 and (
        no_access(result) or result.get("error_type") in ENTRY_DID_NOT_DO)


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


def name(entry: dict[str, Any]) -> str:
    return str(entry.get("school_name") or entry.get("school_name_en") or entry.get("idp_entity_id") or "")
