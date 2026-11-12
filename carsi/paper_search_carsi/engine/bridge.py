"""Institutional access bridge — connects the download orchestrator to institutional download.

Two modes:
1. If external `instsci` package is installed: delegates to PaperFetcher for full cascade
2. Otherwise: uses the ported institutional modules directly (the publisher driver)

Built-in mode runs the publisher driver: session broker (persistent sessions
across downloads) when one is running, else PublisherBatchDownloader (browser
state machine for the publisher's institution login, CARSI school choice
included, and PDF capture).
"""

from __future__ import annotations

import html
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import federations
from ..federations import schools
from ..log import get_logger

log = get_logger()

_MIN_FULLTEXT_LEN = 1000
_LOGIN_FAILURE_CODES = (
    "login_credentials_rejected", "institution_not_registered", "login_page_closed",
    "login_retries_exhausted", "login_timeout", "login_not_reached", "idp_login_error",
    "idp_account_locked", "idp_password_expired",
    "institution_federation_unavailable", "idp_no_return_to_publisher",
)
# Report a fixed category rather than losing the browser reason in a None.
_FAILURE_KINDS = {
    "publisher_content_error": ("publisher_content_error", "review_publisher_error"),
    "unsupported_platform": ("unsupported_platform", "review_publisher_error"),
    "article_not_yet_published": ("article_not_yet_published", "review_publisher_error"),
    "browser_unresponsive": ("browser_unresponsive", "review_browser"),
    "browser_operation_timeout": ("browser_operation_timeout", "review_browser"),
    "publisher_access_blocked": ("access_blocked", "review_access"),
    "publisher_unreachable": ("publisher_unreachable", "review_publisher_error"),
    "sso_required": ("paywall", "login_required"),
    "institution_pdf_entitlement_missing": ("paywall", "review_entitlement"),
    "challenge_or_viewer_timeout": ("download_timeout", "review_browser"),
    "ip_blocked": ("access_blocked", "review_access"),
    "unexpected_error": ("source_exception", ""),
    # The user closed the download browser (or it quit) before the article was done.
    "browser_closed": ("browser_closed", ""),
    "user_marked_no_entitlement": ("no_entitlement", "skipped_by_user"),
    "user_skipped": ("user_skipped", "skipped_by_user"),
    "batch_stopped": ("batch_stopped", "stopped_by_user"),
    "pdf_wrong_article": ("pdf_wrong_article", "review_browser"),
    "supplements_only": ("supplements_only", "supplements_only"),
    # The DOI resolves to no site to sign in on (publishers/site.py): no driver can run.
    "unsupported_publisher": ("unsupported_publisher", "review_publisher_profiles"),
    # A site without a publisher profile: the shared rules found no institution entry.
    "generic_institution_entry_missing": ("generic_institution_entry_missing", "review_publisher_profiles"),
    **{code: (code, "review_browser") for code in _LOGIN_FAILURE_CODES},
}


def _move_into_place(src: Path, output_path: Path) -> None:
    """Put a captured PDF at ``output_path``. The backend saves it in its run folder
    first, which is in PaperSearch's own data (since 0.5.13) and can sit on another
    drive than the download folder: a rename cannot cross drives (WinError 17, Windows
    with D:\\Downloads, 2026-11-11), so the file is moved, copied when it must."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    shutil.move(str(src), str(output_path))


def _remember_blocked_journal(doi: str, identity: dict[str, Any]) -> None:
    """The journal whose site blocked the current network (``blocked_journals``)."""
    from .. import blocked_journals

    if not blocked_journals.journal_key(identity):
        try:
            from .. import entitlements
            identity = entitlements.journal_identity(doi, lookup=True)
        except Exception:
            return  # unknown journal: nothing to remember, the batch goes on as before
    blocked_journals.remember(doi, identity)


def _remember_missing_route(publisher: str, config: dict[str, Any], doi: str) -> None:
    """The publisher has no login route for the configured school (``login_routes``)."""
    from .. import login_routes

    login_routes.remember(publisher, login_routes.school_key(config), doi)


def _failure_reason_code(result: Any) -> str:
    """The reason a failed browser result is reported under (a key of ``_FAILURE_KINDS``)."""
    # Denial must be the terminal state, not a stale reason left on a
    # spinner, login page, or unexpected-error result.
    reason_code = result.state if result.state in _FAILURE_KINDS else result.reason
    if reason_code == "institution_pdf_entitlement_missing" and result.state != reason_code:
        reason_code = "download_failed"
    wait_page = getattr(result, "login_wait_page", "")
    if reason_code in ("sso_required", "login_timeout") and wait_page:
        # A timeout is the user's only where the user had a step to take
        # (ADR 0012); a wait that ended on the publisher's pages means the
        # program never reached the login.
        reason_code = "login_timeout" if wait_page in ("school_login", "school_choice") else "login_not_reached"
    elif reason_code == "sso_required" and getattr(result, "_user_wait_expired", False):
        reason_code = "login_timeout"  # the login waited on the user until its time was up
    return reason_code


def try_institutional(
    doi: str,
    output_path: Path,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Try institutional access. Drop-in source for the tier system.

    Stage B source — skips OA/grey checks, goes straight to institutional paths:
    1. External instsci package (if installed — full cascade)
    2. The publisher driver: the session broker if one is running, else the
       browser state machine (the publisher's institution login, where the
       CARSI school is chosen). It runs with the publisher's profile, or, for a
       site no profile names, with a profile built for the site the DOI
       resolves to (publishers/site.py: the shared rules only).

    A DOI without a profile that resolves to no site to sign in on (doi.org
    failed, a PDF file, an unsupported platform) ends as ``unsupported_publisher``.
    """
    if not _any_institutional_configured(config):
        log.info("   [Institutional] No institutional access configured, skipping")
        return None

    from ..publishers.profiles import infer_publisher_profile
    profiles = None
    if "publisher_profiles_file" in config:
        from ..publishers.extensions import load_publisher_profiles, PublisherProfileConfigError
        try:
            profiles = load_publisher_profiles(config)
        except PublisherProfileConfigError:
            return {"success": False, "identifier": doi, "source": "institutional:profiles",
                    "error_type": "source_exception", "reason": "publisher_profile_config_invalid",
                    "action": "review_publisher_profiles"}
    profile = infer_publisher_profile(doi, profiles=profiles) if profiles is not None else infer_publisher_profile(doi)
    if profile:
        log.info(f"   [Institutional] Publisher: {profile.name}")

    # Mode 1: External instsci package — full cascade
    # The external adapter does not carry the explicit federation choice.
    if federations.configured(config) is None:
        result = _try_external_instsci(doi, output_path, config)
        if result:
            return result

    # Mode 2: Built-in institutional access using ported modules
    if profiles is not None:
        return _try_builtin_institutional(doi, output_path, config, profile, profiles=profiles)
    return _try_builtin_institutional(doi, output_path, config, profile)


def _any_institutional_configured(config: dict[str, Any]) -> bool:
    return schools.institutional_configured(config)


# ---------------------------------------------------------------------------
# Mode 1: External instsci package
# ---------------------------------------------------------------------------

def _try_external_instsci(
    doi: str,
    output_path: Path,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Try using the installed instsci package's PaperFetcher."""
    try:
        from instsci.config import Config as InstSciConfig
        from instsci.fetcher import PaperFetcher
    except ImportError:
        return None

    log.info("   [Institutional] Using external instsci PaperFetcher")
    inst_config = _map_to_instsci_config(config, output_path)
    inst_config.ensure_dirs()

    fetcher = PaperFetcher(config=inst_config)
    try:
        result = fetcher.fetch_with_result(doi, use_cache=False)
    except Exception as e:
        log.info(f"   [Institutional] PaperFetcher error: {e}")
        return None
    finally:
        try:
            fetcher.close()
        except Exception:
            pass

    return _instsci_result_to_dict(result, doi, output_path)


def _map_to_instsci_config(backend_config: dict[str, Any], output_path: Path):
    from instsci.config import Config as InstSciConfig
    # This backend has no WebVPN or EZProxy route: the package gets none either.
    return InstSciConfig(
        school="",
        webvpn_base_url="",
        ezproxy_base_url="",
        email=backend_config.get("email", ""),
        elsevier_api_key=backend_config.get("elsevier_api_key", ""),
        elsevier_inst_token=backend_config.get("elsevier_insttoken", ""),
        carsi_enabled=backend_config.get("carsi_enabled", False),
        carsi_idp_name=backend_config.get("carsi_idp_name", ""),
        output_dir=str(output_path.parent),
        cache_dir=backend_config.get("cache_dir", ""),
    )


def _instsci_result_to_dict(result, doi: str, output_path: Path) -> dict[str, Any] | None:
    if result.status != "success":
        log.info(f"   [Institutional] instsci: {result.status}/{result.quality} — {result.reason}")
        return None

    paper = result.paper
    if paper.pdf_path:
        src = Path(paper.pdf_path)
        if src.exists():
            if src != output_path:
                _move_into_place(src, output_path)
            return {
                "success": True, "identifier": doi, "doi": doi,
                "file": str(output_path),
                "source": f"institutional:{paper.source}",
                "full_text_length": len(paper.full_text or ""),
            }

    if paper.full_text and len(paper.full_text) >= _MIN_FULLTEXT_LEN:
        return {
            "success": False, "identifier": doi, "doi": doi,
            "source": f"institutional:{paper.source}",
            "error": "full_text_extracted_but_no_pdf",
        }
    return None


# ---------------------------------------------------------------------------
# Mode 2: Built-in institutional access (ported modules)
# ---------------------------------------------------------------------------

def _try_builtin_institutional(
    doi: str,
    output_path: Path,
    config: dict[str, Any],
    profile: Any | None,
    *, profiles=None,
) -> dict[str, Any] | None:
    """Try institutional download using ported modules directly."""
    log.info("   [Institutional] Using built-in institutional layer")

    # Step 1: Resolve DOI to publisher URL
    resolved_url = _resolve_doi(doi)
    if not resolved_url:
        log.info("   [Institutional] Could not resolve DOI")
        # Without a profile there is no site to build one for.
        return None if profile else _unsupported_publisher(doi)

    if not profile:
        from ..publishers.profiles import infer_publisher_profile_from_url
        profile = (infer_publisher_profile_from_url(resolved_url, profiles=profiles)
                   if profiles is not None else infer_publisher_profile_from_url(resolved_url))
    if not profile:
        # No profile names the site: the publisher driver with the shared rules
        # only, on the site the DOI resolves to.
        from ..publishers.site import site_profile
        profile = site_profile(doi, resolved_url)
        if profile:
            log.info("   [Institutional] No publisher profile for this site: general rules (%s)",
                     getattr(profile, "name", ""))

    failures: list[dict[str, str]] = []
    manual_school = federations.configured(config) is not None

    # Remembered entitlement decisions (progress-window buttons): a journal or
    # publisher the user marked as "no access" is skipped before any browser.
    publisher_name = getattr(profile, "name", "") if profile else ""
    identity: dict[str, Any] = {}
    try:
        from .. import entitlements, progress_reporter
        from .. import blocked_journals
        identity = entitlements.journal_identity(doi, lookup=bool(entitlements.load()) or blocked_journals.any_recent())
        # Older cache entries kept Crossref's HTML entities.
        progress_reporter.update(publisher=publisher_name, journal=html.unescape(identity.get("journal", "")))
        remembered = entitlements.decision_for(doi, publisher_name, identity=identity)
    except Exception:
        remembered = None
    if remembered and remembered.get("decision") == "skip":
        log.info("   [Institutional] Skipped: %s marked as no access", remembered.get("key"))
        return {"success": False, "identifier": doi, "doi": doi, "source": "institutional:entitlement_memory",
                "error_type": "no_entitlement", "reason": "user_marked_no_entitlement",
                "action": "skipped_by_user", "entitlement": remembered}
    from .. import blocked_journals
    blocked_by = blocked_journals.blocked_by(identity)
    if blocked_by:
        log.info("   [Institutional] Skipped: this journal's site blocked the current network (%s)", blocked_by)
        return {"success": False, "identifier": doi, "doi": doi, "source": "institutional:blocked_journal",
                "error_type": "access_blocked", "reason": "journal_blocked_earlier", "action": "review_access",
                "blocked_by": blocked_by}

    # At most ``publisher_hourly_limit`` articles per publisher in any hour
    # (state L): psc's batch waits the given seconds and tries this one again.
    from .. import rate_limit
    rate_key = publisher_name or (urlparse(resolved_url).hostname or "")
    limit = int(config.get("publisher_hourly_limit", rate_limit.DEFAULT_LIMIT) or 0)
    wait = rate_limit.wait_seconds(rate_key, limit)
    if wait:
        log.info("   [Institutional] %s: %d articles in the last hour, next in %d s", rate_key, limit, wait)
        return {"success": False, "identifier": doi, "doi": doi, "source": "institutional:rate_limit",
                "error_type": "rate_limited", "reason": "publisher_hourly_limit", "action": "wait",
                "retry_after_sec": wait, "publisher": rate_key, "limit": limit}
    rate_limit.record(rate_key)

    def accept(result: dict[str, Any] | None, source: str) -> bool:
        if not result:
            return False
        if result.get("success"):
            if failures:
                result["source_failures"] = failures + list(result.get("source_failures", []))
            return True
        failure = {
            "source": source,
            "error_type": str(result.get("error_type") or "download_failed"),
            "reason": str(result.get("reason") or "download_failed"),
            "action": str(result.get("action") or ""),
        }
        if isinstance(result.get("artifacts"), dict):
            failure["artifacts"] = result["artifacts"]
        if isinstance(result.get("supplements"), list):
            failure["supplements"] = result["supplements"]
        if failure["error_type"] in _LOGIN_FAILURE_CODES:
            failure.update(reason=failure["error_type"], action="review_browser")
        if (result.get("error_type") == "paywall"
                and result.get("reason_code") == "institution_pdf_entitlement_missing"
                and result.get("action") == "review_entitlement"):
            failure["reason_code"] = "institution_pdf_entitlement_missing"
        failures.append(failure)
        return False

    # Step 2: the publisher driver: session broker (persistent session) when
    # one is running, else the profile-driven browser state machine. Broker
    # jobs cannot propagate the federation/manual-selection policy.
    if profile:
        log.info("   [Institutional] Publisher driver (%s)", getattr(profile, "name", ""))
        if not manual_school:
            result = _try_session_broker(doi, output_path, config, profile)
            if accept(result, "institutional:session_broker"):
                return result
        result = _try_browser_batch_download(doi, output_path, config, profile)
        if accept(result, "institutional:browser"):
            return result
    else:
        log.info("   [Institutional] The DOI resolves to no site to sign in on, publisher driver skipped")

    if failures:
        # A route error takes precedence over denial evidence, which still
        # survives in source_failures. Neither is hidden by a later plain miss.
        denial = next((f for f in failures if f.get("reason_code") ==
                       "institution_pdf_entitlement_missing"), None)
        primary = next((f for code in ("source_exception", "unsupported_platform", "article_not_yet_published",
                                      "generic_institution_entry_missing",
                                      "publisher_content_error", "access_blocked", *_LOGIN_FAILURE_CODES,
                                      "download_timeout")
                        for f in failures if f["error_type"] == code), denial or failures[-1])
        result = {"success": False, "identifier": doi, "doi": doi, "source": "institutional",
                  "error_type": primary["error_type"], "reason": primary["reason"],
                  "action": primary["action"], "source_failures": failures}
        if primary["error_type"] == "access_blocked":
            _remember_blocked_journal(doi, identity)
        if primary["error_type"] == "institution_federation_unavailable" and manual_school:
            _remember_missing_route(publisher_name, config, doi)
        if "reason_code" in primary:
            result["reason_code"] = primary["reason_code"]
        artifacts = primary.get("artifacts") or next(
            (f["artifacts"] for f in reversed(failures) if f.get("artifacts")), None)
        if artifacts:
            result["artifacts"] = artifacts
        supplements = next((f["supplements"] for f in reversed(failures)
                            if isinstance(f.get("supplements"), list)), None)
        if supplements is not None:
            result["supplements"] = supplements
        return result
    if not profile:
        # Nothing could run. Said as such, not as a login that is needed.
        return _unsupported_publisher(doi)
    return None


def _unsupported_publisher(doi: str) -> dict[str, Any]:
    error_type, action = _FAILURE_KINDS["unsupported_publisher"]
    return {"success": False, "identifier": doi, "doi": doi, "source": "institutional",
            "error_type": error_type, "reason": error_type, "action": action}


def _resolve_doi(doi: str) -> str | None:
    """Resolve a DOI to the publisher landing URL that doi.org redirects to.

    Only doi.org is asked: following the redirect on to the publisher made the
    lookup fail whenever the publisher refused a plain request (Springer), and
    an unknown publisher then ended the institutional route.
    """
    import requests
    url = f"https://doi.org/{doi}"
    for attempt in range(2):
        try:
            current = url
            for _hop in range(3):
                resp = requests.head(current, allow_redirects=False, timeout=15,
                                     headers={"User-Agent": "scansci-pdf/1.5"})
                location = resp.headers.get("Location", "")
                if not location:
                    break
                current = requests.compat.urljoin(current, location)
                if "doi.org" not in (requests.utils.urlparse(current).hostname or ""):
                    return current
        except requests.RequestException:
            pass
        if attempt == 0:
            time.sleep(1)
    return None


def _try_session_broker(
    doi: str,
    output_path: Path,
    config: dict[str, Any],
    profile: Any | None,
) -> dict[str, Any] | None:
    """Try submitting DOI to a running session broker for the publisher."""
    if not profile:
        return None
    try:
        from ..session_broker import broker_is_running, submit_broker_job
    except ImportError:
        return None

    publisher_name = getattr(profile, "name", "")
    if not publisher_name or not broker_is_running(publisher_name):
        return None

    log.info(f"   [Institutional] Session broker active for {publisher_name}, submitting job")
    try:
        result = submit_broker_job(
            publisher=publisher_name,
            records=[{"doi": doi}],
            output_dir=str(output_path.parent),
            institution="",
            login_timeout=300,
            pdf_timeout=60,
            post_login_hold=0,
            post_run_hold=0,
            timeout_seconds=120,
        )
        if result and result.get("status") == "success":
            pdf_path = result.get("pdf_path", "")
            if pdf_path and Path(pdf_path).exists():
                src = Path(pdf_path)
                if src != output_path:
                    _move_into_place(src, output_path)
                log.info(f"   [Institutional] Session broker download succeeded")
                return {
                    "success": True, "identifier": doi, "doi": doi,
                    "file": str(output_path),
                    "source": f"institutional:broker:{publisher_name}",
                }
    except Exception as e:
        log.info(f"   [Institutional] Session broker failed: {e}")
    return None


def _try_browser_batch_download(
    doi: str,
    output_path: Path,
    config: dict[str, Any],
    profile: Any | None,
) -> dict[str, Any] | None:
    """Try single-DOI download via PublisherBatchDownloader in the download browser.

    Uses the browser state machine: navigate → SSO login → capture PDF → verify.
    This is the most capable built-in path — handles Cloudflare, SSO redirects,
    and publisher-specific PDF extraction.
    """
    if not profile:
        return None

    try:
        from .batch import DownloadResult, PaperRecord, PublisherBatchDownloader
    except ImportError:
        log.info("   [Institutional] publisher_batch not available")
        return None

    try:
        from ..browser.backend import launch_persistent_context  # noqa: F401
        # The configured browser, not the default one (2026-11-01: the
        # default-backend check skipped every ego download).
        from ..browser.engine import is_available as _browser_backend_available
        if not _browser_backend_available(config):
            log.info("   [Institutional] no browser backend available, skipping browser download")
            return None
    except ImportError:
        log.info("   [Institutional] no browser backend available, skipping browser download")
        return None

    # The caller's title checks the PDF when the article page names none (orchestrator).
    record = PaperRecord(doi=doi, title=str(config.get("record_title") or ""))
    # The institution name is the user's own setting (with its federation); empty means "choose by hand".
    institution_query = schools.name(config) if federations.configured(config) else ""
    login_timeout = config.get("browser_login_timeout", 180)

    downloader = PublisherBatchDownloader(
        config=config,
        profile=profile,
        institution_query=institution_query,
        login_timeout_sec=login_timeout,
        pdf_timeout_sec=60,
        post_login_hold_sec=config.get("post_login_hold", 0),
        post_run_hold_sec=0,
        # The institutional bridge logs in by hand (SSO/2FA), so the browser
        # must stay visible whatever browser_headless says.
        require_interactive_browser=True,
    )

    from uuid import uuid4
    run_dir = Path(config.get("diagnostics_dir") or output_path.parent / "diagnostics") / uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"   [Institutional] Browser batch download: {doi} via {profile.name}")

    from ..browser import watchdog

    from ..browser.backend import supports
    from ..browser.batch_session import active_batch

    supplements_mode = str(config.get("supplements") or "")
    batch = active_batch.get() if supports("batch_window", config) else None
    try:
        context = batch.open(downloader) if batch is not None else downloader._launch_context()
        try:
            if supplements_mode == "only":
                result = DownloadResult(doi=doi, status="failed", state="supplements_only",
                                        reason="supplements_only", article_url=downloader._article_url(doi))
            else:
                result = downloader.fetch_one(batch.page if batch is not None else context, record, run_dir)
                if _browser_closed_at_start(result):
                    # The browser closed under the item's first page: the previous
                    # item's browser was still releasing the profile. Once more.
                    try:
                        (batch.close if batch is not None else context.close)()
                    except Exception:
                        pass
                    relaunch = "the browser closed at the first page"
                    context = (batch.open(downloader, relaunch=relaunch) if batch is not None
                               else downloader._launch_context(relaunch=relaunch))
                    result = downloader.fetch_one(batch.page if batch is not None else context, record, run_dir)
            if watchdog.fired and not result.ok:
                # The browser call never returned and the driver was stopped:
                # whatever the engine reported after that is a consequence.
                result.reason = result.state = watchdog.failure_code()
            if supplements_mode in ("with", "only"):
                if result.state in ("browser_unresponsive", "browser_operation_timeout"):
                    result.supplements = [{"status": "skipped", "reason": result.state,
                                           "url": "", "label": ""}]
                elif result.state == "challenge_or_viewer_timeout":
                    # The verification page was never completed: the article
                    # page is unreachable, so do not wait on it a second time.
                    result.supplements = [{"status": "skipped", "reason": "challenge_timeout",
                                           "url": "", "label": ""}]
                elif result.state in ("unsupported_platform", "article_not_yet_published",
                                      "publisher_access_blocked", "publisher_unreachable",
                                      "login_page_closed", "user_skipped", "batch_stopped",
                                      "user_marked_no_entitlement"):
                    # Nothing more to fetch there now.
                    result.supplements = [{"status": "skipped", "reason": result.state,
                                           "url": "", "label": ""}]
                else:
                    written = len(result.events)
                    result.supplements = downloader.collect_supplements(context, doi, output_path.parent, result, manifest_dir=run_dir)
                    if supplements_mode == "only":
                        manifest = run_dir / "manifest.json"
                        if not manifest.is_file():
                            manifest.write_text(json.dumps({"doi": doi, "files": result.supplements},
                                                           ensure_ascii=False, indent=2), encoding="utf-8")
                        result.record_path = str(manifest)
                    if ((result.ok and result.verified_match) or supplements_mode == "only") and all(
                        f.get("status") == "saved" for f in result.supplements
                    ):
                        downloader._drop_snapshot_pictures(result)
                    _note_supplements(result, written)
        finally:
            if batch is not None:
                if not watchdog.fired:
                    batch.finish_item()
            else:
                try:
                    context.close()
                except Exception:
                    pass
    except Exception as e:
        log.info("   [Institutional] Browser batch download error: %s", type(e).__name__)
        from .batch_common import browser_closed

        if isinstance(e, watchdog.BrowserOperationTimeout):
            state = "browser_operation_timeout"
        elif isinstance(e, watchdog.BrowserUnresponsive):
            state = "browser_unresponsive"
        elif browser_closed(e):
            state = "browser_closed"
        else:
            state = "unexpected_error"
        error_type, action = _FAILURE_KINDS[state]
        return {"success": False, "identifier": doi, "source": "institutional:browser",
                "error_type": error_type, "reason": error_type, "action": action,
                "artifacts": {"driver": "publisher", "publisher": str(getattr(profile, "name", "") or ""), "record": "",
                              "diagnostic": _write_exception_diagnostic(run_dir, doi, e, state=state, reason=error_type),
                              "state": state}}

    if getattr(result, "state", "") == "access_ready":
        # `login`: the article opens in full; whether the school's login was part of it.
        return {"success": True, "identifier": doi, "doi": doi,
                "source": f"institutional:browser:{profile.name}",
                "login": {"signed_in": bool(getattr(result, "signed_in", False))},
                "artifacts": _browser_artifacts(result, profile)}

    if result.ok and result.pdf_path:
        src = Path(result.pdf_path)
        if src.exists():
            if src != output_path:
                _move_into_place(src, output_path)
            result.pdf_path = str(output_path)
            _note_supplements(result, len(getattr(result, "events", [])))
            log.info(f"   [Institutional] Browser download succeeded: {result.size_bytes:,} bytes")
            return {
                "success": True, "identifier": doi, "doi": doi,
                "file": str(output_path),
                "source": f"institutional:browser:{profile.name}",
                "full_text_length": result.text_length,
                "artifacts": _browser_artifacts(result, profile),
                **({"supplements": result.supplements} if supplements_mode in ("with", "only") else {}),
            }

    reason_code = _failure_reason_code(result)
    error_type, action = _FAILURE_KINDS.get(reason_code, ("download_failed", ""))
    failure = {"success": False, "identifier": doi, "source": "institutional:browser",
               "error_type": error_type, "reason": error_type, "action": action,
               "artifacts": _browser_artifacts(result, profile)}
    if supplements_mode in ("with", "only"):
        failure["supplements"] = result.supplements
    if reason_code == "institution_pdf_entitlement_missing":
        failure["reason"] = reason_code
        failure["reason_code"] = reason_code
    return failure


def _browser_closed_at_start(result: Any) -> bool:
    """The item ended at its first navigation because the browser had closed
    (Playwright's TargetClosedError), before any other step: the previous
    item's browser was still letting go of the profile, not the user."""
    events = [e for e in getattr(result, "events", None) or () if e.get("state") != "browser_start"]
    return (getattr(result, "state", "") == "browser_closed" and 2 <= len(events) <= 3
            and events[0].get("state") == "article_open" and events[1].get("state") == "browser_closed")


def _note_supplements(result: Any, written: int) -> None:
    """Add the supplementary-file step to the article's record or diagnostic,
    which were written before it (foodchem and rineng found none on 2026-11-01
    and left no trace of why)."""
    for name in ("record_path", "diagnostic_path"):
        path = Path(str(getattr(result, name, "") or ""))
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["events"] = list(data.get("events") or []) + list(getattr(result, "events", [])[written:])
        data["supplements"] = getattr(result, "supplements", [])
        data["snapshots"] = getattr(result, "snapshots", [])
        data["pdf_path"] = str(getattr(result, "pdf_path", "") or "")
        if getattr(result, "phases", None):
            data["phases"] = {k: round(float(v), 1) for k, v in result.phases.items()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_exception_diagnostic(run_dir: Path, doi: str, exc: Exception, *,
                                state: str = "unexpected_error", reason: str = "source_exception") -> str:
    """A failure outside the article's own steps (starting the browser, the ego
    connection) still leaves what happened, for the failure summary (ADR 0012).
    Records of 2026-10-30 had only "source_exception", nothing to look into."""
    import traceback
    from .batch_common import safe_name

    path = run_dir / "diagnostics" / safe_name(doi) / "diagnostic.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "doi": doi, "status": "failed", "state": state, "reason": reason,
            "events": [{"state": "unexpected_exception", "detail": f"{type(exc).__name__}: {str(exc)[:400]}"}],
            "traceback": traceback.format_exc()[-4000:],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return ""
    return str(path)


def _browser_artifacts(result: Any, profile: Any) -> dict[str, str]:
    """Where the browser run left its record (success) or diagnostic packet (failure).

    Only local file paths and the fixed state code: free-text reasons can carry
    tokens or cookies and stay in the diagnostic file, never in tool results.
    """
    state = str(getattr(result, "state", "") or "")
    artifacts = {
        "driver": "publisher",
        "publisher": str(getattr(profile, "name", "") or ""),
        "record": str(getattr(result, "record_path", "") or ""),
        "diagnostic": str(getattr(result, "diagnostic_path", "") or ""),
        "state": state if re.fullmatch(r"[a-z0-9_]{1,64}", state) else "",
    }
    # The school's site the login stopped on: a host name only, for the message.
    host = str(getattr(result, "_stopped_host", "") or "").lower()
    if state == "idp_no_return_to_publisher" and re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host) and len(host) <= 253:
        artifacts["stopped_host"] = host
    return artifacts
