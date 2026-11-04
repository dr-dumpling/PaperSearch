"""Serialize download artifacts.

Result manifests / CSV / attempts stay allowlisted (they feed other tools).
Diagnostic files (``diagnostic=True``) are written for local debugging and are
NOT masked at all: full event details, URLs (query strings included), raw
reasons. They can contain live session tokens; keep them on this machine.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from urllib.parse import urlsplit

_DOI = re.compile(r"10\.\d{4,9}/[A-Za-z0-9._;()/:+-]{1,480}\Z")
_STATUSES = frozenset("success failed partial missing unverified cancelled interrupted".split())
_FAILURES = frozenset("""
request_failed download_failed download_timeout source_exception unexpected_error
login_timeout login_page_closed login_credentials_rejected login_retries_exhausted
login_required verification_required institution_not_registered idp_login_error sso_required
idp_account_locked idp_password_expired
sso_redirect_stalled institution_pdf_entitlement_missing publisher_content_error publisher_unreachable
publisher_access_blocked
publisher_institution_entry_missing institution_entry_unresolved
publisher_temporarily_unavailable
challenge_or_viewer_timeout ip_blocked access_blocked pdf_not_captured
pdf_identity_mismatch pdf_identity_unverified invalid_pdf
profile_busy cancelled interrupted skipped_cached_attempt target_verified_reached navigation_error
unsupported_platform unsupported_publisher user_skipped user_marked_no_entitlement pdf_wrong_article
institution_federation_unavailable browser_unresponsive browser_operation_timeout login_not_reached idp_no_return_to_publisher
generic_institution_entry_missing
""".split())
_STATES = _FAILURES | _STATUSES | frozenset("""
started article_loaded article_loaded_after_sso pdf_response_captured
opening_article waiting_login waiting_verification checking_access fetching_pdf
pdf_captured saved_pending_verification route_failed
""".split())
_EVENTS = frozenset("""
aps_institution_entry_missing article_access_ready article_open
auth_wall_after_article_load auth_wall_after_pdf_attempt browser_capture_detach_error
browser_capture_disable_error browser_pdf_response_captured browser_pdf_response_error
browser_response_continue_error browser_response_discard_error challenge_manual_wait
challenge_or_viewer_timeout challenge_resolved challenge_wait cookie_banner_dismissed cookie_banner_left
advertisement_closed pdf_step_article_page institution_choice_returned_article institution_choice_stopped
cookie_inject_failed download_capture_error elsevier_institution_entry_error
institution_continue institution_continue_error institution_entry_unresolved institution_federation_selected
institution_search_error institution_search_retyped institution_session_other idp_confirmation_required
institution_required institution_search institution_search_submitted
institution_select_error institution_selected institution_selection_required
institution_session_return_article institution_session_return_error
ip_blocked_body ip_blocked_response karger_institution_chooser_opened
login_attempt_started login_completed_after_timeout login_navigation_interrupted login_wait_ended
login_observed login_phase_start login_retry_wait login_state login_stopped login_waiting
openathens_entry openathens_entry_error partial_pdf_response pdf_async_navigation
pdf_async_navigation_error pdf_button_clicked pdf_button_error pdf_candidate
pdf_capture_started pdf_navigation_error pdf_saved pdf_state_candidate post_login_hold
post_login_hold_article_access post_login_hold_auth_wall post_login_hold_login_page
post_run_hold publisher_access_blocked publisher_content_error publisher_unreachable publisher_login_menu_opened
publisher_pdf_link_unverified publisher_session_save_failed publisher_session_saved
record_article_return record_article_return_error seamlessaccess_chooser_opened
shared_cookies_exported shared_cookies_loaded sso_entry_clicked sso_entry_error sso_start
access_unknown_pdf_first access_unknown_pdf_failed pdf_step_login_required login_round_trip_returned
pdf_probe pdf_probe_captured pdf_probe_refused no_access_after_login pdf_found_while_waiting
login_entry_missing login_entry_controls access_menu_opened access_menu_entry_refused access_menu_error
article_reopen_error supplements_skipped browser_start
""".split()) | _FAILURES
_DETAIL_CATEGORIES = {
    "login_observed": frozenset("""
verification human_login article_ready publisher_login redirect_wait transient_error
login_page_closed login_credentials_rejected institution_not_registered
institution_pdf_entitlement_missing publisher_temporarily_unavailable
""".split()),
    "login_stopped": _FAILURES,
    "login_waiting": frozenset({"login", "verification"}),
    "login_attempt_started": frozenset({"1/3", "2/3", "3/3"}),
    "login_phase_start": frozenset({"primary", "retry"}),
    "login_wait_ended": frozenset({"school_login", "school_choice", "institution_chooser",
                                   "publisher", "other", "closed"}),
}
_PUBLISHERS = frozenset("""
sciencedirect.com elsevier.com nature.com springer.com link.springer.com
wiley.com academic.oup.com journals.lww.com ovid.com jamanetwork.com science.org
tandfonline.com sagepub.com pubs.acs.org pubs.rsc.org thieme-connect.com
thieme-connect.de karger.com nejm.org bmj.com
""".split())
_AUTH_HOSTS = frozenset({"openathens.net", "sso.rsc.org", "profile.thieme.de"})
_DELIVERY_HOSTS = frozenset({"watermark02.silverchair.com"})
_AUTH_SEGMENTS = frozenset({"login", "signin", "sso", "saml", "oidc", "authorize",
                            "callback", "wayf", "ssostart", "shibboleth", "logout"})


def _get(record, name):
    return record.get(name) if isinstance(record, Mapping) else getattr(record, name, None)


def _choice(value, allowed, fallback):
    return value if type(value) is str and value in allowed else fallback


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _url_role(value):
    if value is None or value == "":
        return "absent"
    if type(value) is not str or len(value) > 4096:
        return "invalid"
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        parsed.port
        if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password:
            return "invalid"
    except ValueError:
        return "invalid"
    if any(host == h or host.endswith("." + h) for h in _AUTH_HOSTS):
        return "authentication"
    if set(parsed.path.lower().split("/")) & _AUTH_SEGMENTS:
        return "authentication"
    if host in _DELIVERY_HOSTS:
        return "pdf_delivery"
    if any(host == h or host.endswith("." + h) for h in _PUBLISHERS):
        return "publisher"
    return "external"


_DIAGNOSTIC_DETAIL_CAP = 8000


def _raw(value):
    """JSON-safe copy of a scalar, without masking."""
    if value is None or type(value) in (bool, int, float):
        return value
    return str(value)


def serialize_download_result(result, *, phase=None, full_text=None,
                              artifact_name=None, include_events=True, diagnostic=False):
    """Return a new record; never change the source or perform I/O.

    ``diagnostic=True`` keeps everything unmasked (see module docstring).
    """
    raw_doi = _get(result, "doi")
    doi = raw_doi if type(raw_doi) is str and _DOI.fullmatch(raw_doi) else None
    status = _choice(_get(result, "status"), _STATUSES, "unknown")
    state = _choice(_get(result, "state"), _STATES, "unknown")
    raw_reason = _get(result, "reason")
    reason = "" if raw_reason is None or raw_reason == "" else _choice(
        raw_reason, _FAILURES, state if state in _FAILURES else "request_failed")
    verified = _get(result, "verified_match")
    packet = {
        "schema_version": 1, "doi": doi, "status": status, "state": state, "reason": reason,
        "size_bytes": _count(_get(result, "size_bytes")),
        "text_length": _count(_get(result, "text_length")),
        "verified_match": verified if type(verified) is bool else None,
        "article_url_role": _url_role(_get(result, "article_url")),
        "final_url_role": _url_role(_get(result, "final_url")),
        "pdf_url_role": _url_role(_get(result, "pdf_url")),
    }
    if phase is not None:
        packet["phase"] = _choice(phase, {"primary", "retry"}, "unknown")
    if doi and type(artifact_name) is str and artifact_name == re.sub(r"[^\w\-.]", "_", doi) + ".pdf":
        packet["artifact_name"] = artifact_name
    if diagnostic:
        for name in ("doi", "status", "state", "reason", "title", "article_url", "final_url",
                     "pdf_url", "pdf_path", "diagnostic_path"):
            value = _get(result, name)
            if value not in (None, ""):
                packet[f"raw_{name}" if name in packet else name] = _raw(value)
    if include_events:
        raw_events = _get(result, "events")
        events = raw_events if type(raw_events) in {list, tuple} else ()
        packet["events"] = []
        # A diagnostic keeps every step of a long article (verification waits
        # write one event a second); the public record keeps its 256.
        cap = 2000 if diagnostic else 256
        packet["events_truncated"] = len(events) > cap
        for event in events[:cap]:
            if diagnostic:
                item = {"state": _raw(_get(event, "state"))}
                detail = _get(event, "detail")
                if detail not in (None, ""):
                    item["detail"] = _raw(detail)[:_DIAGNOSTIC_DETAIL_CAP]
                for extra in ("at", "time", "ts", "elapsed", "gap", "browser_time"):
                    if _get(event, extra) is not None:
                        item[extra] = _raw(_get(event, extra))
                packet["events"].append(item)
                continue
            kind = _choice(_get(event, "state"), _EVENTS, "unknown")
            item = {"state": kind}
            detail = _get(event, "detail")
            if type(detail) is str and detail in _DETAIL_CATEGORIES.get(kind, ()):
                item["category"] = detail
            packet["events"].append(item)
    if diagnostic:
        start = _get(result, "browser_start")
        if isinstance(start, Mapping) and start:
            packet["browser_start"] = {str(k): _raw(v) for k, v in start.items()}
        for name in ("pdf_attempts", "snapshots"):
            rows = _get(result, name)
            if isinstance(rows, (list, tuple)) and rows:
                packet[name] = [{str(k): (v if isinstance(v, (list, dict)) else _raw(v)) for k, v in row.items()}
                                for row in rows[:50] if isinstance(row, Mapping)]
        phases = _get(result, "phases")
        if isinstance(phases, Mapping) and phases:
            packet["phases"] = {str(k): round(float(v), 1) for k, v in phases.items()
                                if type(v) in (int, float) and v >= 0}
    if type(full_text) is str and status == "success" and verified is True:
        packet["full_text"] = full_text
    return packet


def serialize_download_summary(summary):
    """Keep batch counts while excluding execution paths and proxy credentials."""
    packet = {"schema_version": 1}
    for key in ("count", "success", "missing", "unverified", "verified_match",
                "retry_attempted", "retry_success", "target_verified", "skipped",
                "cached_skipped", "concurrency", "ip_blocked_count"):
        packet[key] = _count(summary.get(key))
    for key in ("target_reached", "auto_stopped"):
        value = summary.get(key)
        packet[key] = value if type(value) is bool else None
    packet["stop_reason"] = _choice(summary.get("stop_reason"), {"", "ip_blocked"}, "unknown")
    for key in ("primary", "final"):
        counts = summary.get(key)
        packet[key] = {name: _count(counts.get(name)) for name in
                       ("count", "success", "failed")} if isinstance(counts, Mapping) else None
    return packet
