"""Single-paper institutional download orchestration.

This package serves one case: PaperSearch has already exhausted
public/OA sources and asks for the institutional phase only. There is no free-source race, no grey
sources and no renaming; the caller names and verifies the file.
"""
from __future__ import annotations

import html
import re
import threading
from pathlib import Path
from typing import Any

from .cache import cache_get, cache_set
from .config import load_config
from .identifiers import is_arxiv_identifier, normalize_doi, normalize_doi_unicode, safe_filename
from .engine.bridge import try_institutional
from .log import get_logger
from .pdf_utils import fail, is_pdf_file

log = get_logger()

ACCEPTED_STRATEGIES = ("legal_only", "institutional_only")

_INFLIGHT: set[str] = set()
_INFLIGHT_LOCK = threading.Lock()


def plain_title(title: str) -> str:
    """A metadata title as plain text: no markup or entities (Crossref gives <i>…</i> and &amp;)."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(title))).split())[:500]


def download_institutional(
    identifier: str,
    output_dir: str | Path | None = None,
    *,
    strategy: str | None = None,
    supplements: str | None = None,
    user_wait: str | None = None,
    diagnostics_dir: str | None = None,
    title: str | None = None,
    login_only: bool = False,
    login_wait: int | None = None,
    fulltext: bool | str | None = None,
    school: str | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    """Download one DOI through institutional access only.

    ``fresh`` (the settings' 测试登录, school_test.py): neither from the cache nor into it: the download itself is
    what is tested.

    ``login_only`` (``login``): the download's own steps up to the article's
    access, then stop: no PDF, nothing cached. ``login_wait``: seconds to wait
    on the school's login page instead of the setting.

    ``user_wait="short"``: the user seems away (an earlier article of the batch
    waited on them until its time was up); each wait on the user is short.

    Returns the result dict that PaperSearch reads:
    ``{"success": true, "identifier", "doi", "file", "source", "size_kb"}`` or
    ``{"success": false, "identifier", "doi", "reason", "error_type"?, "action"?, "reason_code"?}``.
    """
    key = identifier.strip()
    if strategy not in (None, "") and strategy not in ACCEPTED_STRATEGIES:
        return fail(key, f"unsupported strategy: {strategy}", error_type="source_exception", action="review_strategy")
    if is_arxiv_identifier(key):
        return fail(key, "arXiv identifiers have no institutional route", error_type="not_found")
    doi = normalize_doi(key)
    if not doi or normalize_doi_unicode(doi) is None:
        # Only DOI-shaped identifiers reach a route; the browser must not be
        # opened for arbitrary text.
        return fail(key, "invalid identifier", error_type="not_found")

    with _INFLIGHT_LOCK:
        if doi in _INFLIGHT:
            return fail(
                doi,
                reason="download already in progress for this identifier",
                error_type="in_progress",
                action="wait for the in-flight attempt to finish",
            )
        _INFLIGHT.add(doi)
    try:
        extra = {"supplements": supplements} if supplements in ("with", "only") else {}
        if user_wait == "short":
            extra["user_wait"] = user_wait
        if diagnostics_dir:
            extra["diagnostics_dir"] = diagnostics_dir
        if title:
            extra["title"] = title
        if login_only:
            extra["login_only"] = True
        if fulltext:
            # "with" (or True): the page beside the PDF; "only": the page alone, no PDF;
            # "sample": a maintainer's sample of a site without page rules (publisher-check).
            extra["fulltext"] = fulltext if fulltext in ("only", "sample") else "with"
        if login_wait:
            extra["login_wait"] = login_wait
        if school and school.strip():
            extra["school"] = school.strip()
        if fresh:
            extra["fresh"] = True
        return _download_impl(doi, output_dir, **extra)
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.discard(doi)


def _download_impl(doi: str, output_dir: str | Path | None, *,
                   supplements: str | None = None, user_wait: str | None = None,
                   diagnostics_dir: str | None = None, title: str | None = None,
                   login_only: bool = False, login_wait: int | None = None,
                   fulltext: str | None = None, school: str | None = None, fresh: bool = False) -> dict[str, Any]:
    config = load_config()
    if school:
        # Another saved school for this download alone, as the user asked; the config's own
        # school is not changed (user, 2026-11-17).
        from .schools.saved import use_for_download

        problem = use_for_download(config, school)
        if problem:
            return fail(doi, problem, error_type=problem, action="review_school")
    if fulltext:
        # The article's full-text page is saved while on it (engine/fulltext_page.py).
        # A main text already cached is not fetched again, so neither is its page.
        config["fulltext"] = "sample" if fulltext == "sample" else True
    if fulltext == "only":
        # The page alone: the article's access as for `login`, then its page, no PDF.
        login_only = True
    if login_only:
        config["login_only"] = True
    if login_wait:
        config["browser_login_timeout"] = int(login_wait)
    if title:
        # The caller's title for the PDF identity check (bridge's PaperRecord).
        config["record_title"] = plain_title(title)
    if user_wait == "short":
        config["user_wait"] = "short"
    if supplements in ("with", "only"):
        config["supplements"] = supplements

    from .download_directory import configured as configured_download_directory

    target_dir = Path(output_dir) if output_dir else Path(configured_download_directory() or config["output_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)
    from .progress_reporter import set_output_dir
    set_output_dir(target_dir)
    if diagnostics_dir:
        config["diagnostics_dir"] = str(Path(diagnostics_dir).resolve())
    output_path = target_dir / f"{safe_filename(doi)}.pdf"

    cached = None if login_only or fresh else cache_get(doi, config)
    if cached and cached.get("success"):
        cached_file = Path(str(cached.get("file") or ""))
        if cached_file.exists() and is_pdf_file(cached_file):
            cached["cached"] = True
            if supplements not in ("with", "only"):
                return cached
            # The main text is cached; only the supplementary files are fetched.
            config["supplements"] = "only"
            extra = try_institutional(doi, output_path, config) or {}
            if isinstance(extra.get("supplements"), list):
                cached = {**cached, "supplements": extra["supplements"]}
            return cached

    log.info(f"paper-search-school - {doi}")
    # Another school than the one the browser last signed in with: that sign-in forgotten first; a test
    # (``fresh``) always starts signed out, so that the account is what it tries (user, 2026-11-21).
    from .cold_start import before_sign_in
    from . import school_switch
    from .schools import saved as saved_schools

    # 没权限时换下一所学校 (school_switch.py): the schools to try in turn, its journal's school of this task first.
    # One alone: the switch off, a school named for this download, the test of one, a sign-in only.
    turns = (school_switch.order_for(config, doi) if school_switch.enabled(config) and not school and not fresh
             and not login_only else [])
    if turns and not saved_schools.is_current(config, turns[0]):
        saved_schools.apply(config, turns[0])
    turn = 0
    while True:
        signed = before_sign_in(config, always=fresh)
        if signed == "cleared":
            log.info("   [Institutional] the browser's sign-in with another school forgotten")
        elif signed == "busy" and fresh:
            return fail(doi, "the download browser is open", error_type="browser_busy", action="close_browser")

        try:
            result = try_institutional(doi, output_path, config)
        except Exception as exc:
            log.info(f"   [Institutional] route exception: {type(exc).__name__}")
            return fail(doi, "institutional route raised", error_type="source_exception", action="review_logs")
        if turn + 1 >= len(turns) or not school_switch.no_access(result):
            break
        # Signed in, no access: the next school, its sign-in after this one's is forgotten (the batch's browser closed
        # first to let go of it; one that will not let go ends the turns: the next would try this school's session).
        turn += 1
        following = turns[turn]
        log.info(f"   [Institutional] no access with {school_switch.name(turns[turn - 1])}; next: {school_switch.name(following)}")
        from . import progress_reporter
        from .browser.batch_session import active_batch

        progress_reporter.update(stage="switching_school", phase=f"没权限，换{school_switch.name(following)}")
        batch = active_batch.get()
        if batch is not None:
            batch.close()
        saved_schools.apply(config, following)
        if before_sign_in(config) == "busy":
            log.info("   [Institutional] the browser kept the last school's sign-in; no other school tried")
            turn -= 1
            break
    if len(turns) > 1 and result and result.get("success"):
        school_switch.remember(doi, str(config.get("idp_entity_id") or "").strip())
        if turn or not saved_schools.is_current(load_config(), turns[turn]):
            result["school"] = school_switch.name(turns[turn])  # not the default school's: the results say whose
    elif turns and turn and school_switch.no_access(result):
        result["schools_tried"] = turn + 1  # the lists say "N 所学校都没有权限"
    # An article that re-checked a blocked journal's site: open again unless blocked again.
    from . import blocked_journals
    blocked_journals.recheck_ended(doi, blocked=bool(result) and result.get("error_type") == "access_blocked")

    if result is None:
        return fail(
            doi,
            "paywall — requires institutional access",
            error_type="paywall",
            action="login_required",
        )
    if not result.get("success"):
        result.setdefault("identifier", doi)
        result.setdefault("doi", doi)
        result.setdefault("reason", "institutional download failed")
        return result
    if login_only:
        return result  # the article's access, no PDF (bridge: access_ready)

    file_path = Path(str(result.get("file") or output_path))
    if not file_path.exists() or not is_pdf_file(file_path):
        return fail(doi, "institutional route reported success without a readable PDF", error_type="source_exception", action="review_logs")
    result["identifier"] = doi
    result.setdefault("doi", doi)
    result["file"] = str(file_path)
    result.setdefault("size_kb", round(file_path.stat().st_size / 1024, 1))
    if fresh:
        return result
    cache_set(doi, result, config)
    return result
