"""Local CLI for paper-search-school.

Commands:
  run                          start the MCP stdio server (what PaperSearch spawns)
  setup [...]                  show or change institutional access settings; --check for an environment check
  login --doi DOI              sign in to the school as a download does (no PDF); success only once confirmed
  school-test --school ENTITY --doi DOI   the settings' 测试登录: one download with a saved school, its PDF deleted,
                               the verdict in progress/school-test.json (school_test.py)
  config get|set|list          read or write the backend config in SCHOOL_DATA_DIR
  list-publishers              print publisher profiles and their platform labels
  publisher-check --doi DOI    run one institutional download and print a sanitized report
  progress                     open the floating progress window
  progress --json [--watch]    read-only snapshot of the current task progress file
  settings [PAGE|KEY]          show the progress window's settings: download, wait, keys, or one API key (e.g. EASYSCHOLAR_KEY)
  preview [--run-id ID --doi DOI]  latest screenshots of the download browser (JSON)
  entitlements [list|set|clear]   remembered "has access / no access" decisions per journal or publisher
  issues [list|show ID|resolve ID --note TEXT]  problem reports filed from the progress window (agent review)
  cold-start [--yes]           forget school sessions in the download browser (lists first; deletes on confirmation)

Credentials are never passed through this CLI: logins happen in the browser window it opens.
"""
from __future__ import annotations

import argparse
import codecs
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

MASK = "***configured***"


def _data_dir() -> Path:
    from .config import DATA_DIR

    return DATA_DIR


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def _federation_code(cfg: dict[str, Any]) -> str:
    """The configured federation's code; "carsi" for the old switch alone."""
    from .federations import configured

    federation = configured(cfg)
    return federation.code if federation else ("carsi" if cfg.get("carsi_enabled") else "")


def _saved(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from .schools import saved as saved_schools

    return saved_schools.saved(cfg)


def _institutional_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    from .federations import by_code

    federation = by_code(_federation_code(cfg))
    return {
        "data_dir": str(_data_dir()),
        "federation": federation.code if federation else "",
        "federation_name": federation.name if federation else "",
        "federation_country": federation.country if federation else "",
        "carsi_enabled": bool(cfg.get("carsi_enabled")),
        "school_name": cfg.get("school_name") or "",
        "school_name_en": cfg.get("school_name_en") or "",
        "idp_entity_id": cfg.get("idp_entity_id") or "",
        # The other saved schools, switched to with `use` (user, 2026-11-17).
        "saved_schools": [entry.get("school_name") or "" for entry in _saved(cfg)],
        "browser_backend": cfg.get("browser_backend") or "",
        "chrome_profile_dir": cfg.get("chrome_profile_dir") or "",
        "output_dir": cfg.get("output_dir") or "",
    }


def _environment_check(cfg: dict[str, Any]) -> tuple[bool, list[dict[str, str]], dict[str, Any]]:
    """(ready, checks, browser): ``browser`` is the chrome backend's browser
    (backend.browser_check) when that backend is configured, else {}."""
    checks: list[dict[str, str]] = []
    browser: dict[str, Any] = {}

    def add(item: str, ok: bool, detail: str) -> None:
        checks.append({"item": item, "status": "ok" if ok else "missing", "detail": detail})

    data_dir = _data_dir()
    add("data_dir", data_dir.exists() and os.access(data_dir, os.W_OK), str(data_dir))
    add("config_file", (data_dir / "config.json").exists(), str(data_dir / "config.json"))

    try:
        from .browser.backend import BACKEND_CHROME, CHROME_MISSING, browser_check, is_available, resolve_backend

        backend = resolve_backend(cfg)
        if backend == BACKEND_CHROME:
            browser = browser_check(cfg)
            found = f"{browser['browser']} {browser['version']} ({browser['path']}), {browser['driver']}"
            add("browser_backend", bool(is_available(backend, cfg)),
                f"chrome: {found}" if browser["browser"] else f"chrome: {CHROME_MISSING}")
        else:
            add("browser_backend", bool(is_available(backend, cfg)), backend)
    except Exception as exc:  # pragma: no cover - import problems are themselves a finding
        add("browser_backend", False, f"{type(exc).__name__}")

    federation = _federation_code(cfg)
    add("institutional_route", bool(federation), federation or 'none; run: setup --institution "<your school>"')
    school = str(cfg.get("school_name") or "").strip()
    if federation and school:
        # A name alone (saved before setup used the member lists) is not found in English-only pickers.
        complete = bool(cfg.get("idp_entity_id") and cfg.get("school_name_en"))
        add("school", complete,
            school if complete else f'only the name is saved; run: setup --institution "{school}"')
    for item in ("output_dir", "cache_dir"):
        value = cfg.get(item) or ""
        add(item, bool(value), value)
    return all(c["status"] == "ok" for c in checks), checks, browser


def _carsi_school_list(cfg: dict[str, Any]) -> tuple[list[Any], dict[str, Any] | None]:
    import requests

    from .federations.carsi import SCHOOL_LIST_URL, load_school_list

    try:
        return load_school_list(cfg, _data_dir()), None
    except (requests.RequestException, ValueError) as exc:
        return [], {"error": "carsi_school_list_unavailable", "url": SCHOOL_LIST_URL,
                    "detail": f"{type(exc).__name__}: {exc}"[:300],
                    "hint": "retry later; `setup --carsi` without --institution leaves the school to the login window"}


def _set_carsi_school(cfg: dict[str, Any], query: str) -> dict[str, Any] | None:
    """Save the CARSI member school the user named; the problem to report when there is not exactly one."""
    from .federations.carsi import choose_school

    schools, problem = _carsi_school_list(cfg)
    if problem:
        return problem
    school, candidates = choose_school(schools, query)
    if school is None:
        if not candidates:
            return {"error": "carsi_school_not_found", "query": query,
                    "hint": "type the Chinese or English name, the domain or the entityID; `setup --list-carsi-schools <keyword>`"}
        return {"error": "carsi_school_ambiguous", "query": query, "count": len(candidates),
                "candidates": [s.summary() for s in candidates[:10]],
                "hint": "run again with the full name, the domain or the entityID of one candidate"}
    cfg.update(school_name=school.name, school_name_en=school.name_en, school_entry_name="", idp_entity_id=school.entity_id,
               idp_login_hosts=[], idp_login_pages=[], idp_domains=[school.domain] if school.domain else [])
    return None


def _find_school(cfg: dict[str, Any], query: str, also: list[str]) -> dict[str, Any] | None:
    """Save the school the user named, any federation (``schools.lookup``);
    the problem to report when there is not exactly one."""
    from .schools import lookup as schools

    found = schools.find(query, cfg, _data_dir(), also=also)
    if found.school is not None:
        schools.save(cfg, found.school)
        return None
    if found.candidates:
        return {"error": "school_ambiguous", "query": query, "count": len(found.candidates),
                "candidates": [s.summary() for s in found.candidates],
                "hint": "ask the user which one, then run again with its entity_id as --institution"}
    if found.unsupported:
        return {"error": "federation_not_supported", "query": query,
                "found": [{"name": n, "registration_authority": ra} for n, ra in found.unsupported[:10]],
                "hint": "the school signs in through a federation not supported yet"}
    if found.unavailable:
        return {"error": "school_list_unavailable", "query": query, "sources": found.unavailable,
                "hint": "retry later; `setup --carsi` without --institution leaves the school to the login window"}
    return {"error": "school_not_found", "query": query,
            "reasons": ["the name is written differently from the federations' lists",
                        "the school has not joined an identity federation or OpenAthens: it gives access by campus "
                        "network, VPN or a library proxy only, and school subscription download cannot sign in for it"],
            "hint": "try the school's official name in its own language or in English (--also-name for another name), "
                    "its web domain or its entityID; if it is still not found, tell the user the second reason"}


def _cmd_setup(args: argparse.Namespace) -> int:
    from .config import load_config, save_config

    cfg = load_config()
    changed = False

    if args.list_carsi_schools is not None:
        schools, problem = _carsi_school_list(cfg)
        if problem:
            print(json.dumps(problem, ensure_ascii=False))
            return 1
        from .federations.carsi import find_schools

        if args.list_carsi_schools.strip():
            exact, partial = find_schools(schools, args.list_carsi_schools)
            schools = exact + partial
        print(json.dumps({"count": len(schools), "schools": [s.summary() for s in schools]}, ensure_ascii=False, indent=2))
        return 0

    if args.carsi:
        cfg["publisher_institution_federation"] = "carsi"
        cfg["carsi_enabled"] = True
        changed = True
    if args.no_school:
        cfg["publisher_institution_federation"] = ""
        cfg["carsi_enabled"] = False
        changed = True
    if args.institution:
        from .schools import saved as saved_schools

        # The school before it stays saved, to switch back to with `use` (2026-11-17).
        saved_schools.remember(cfg)
        # With --carsi only CARSI's member list is asked; otherwise every
        # supported federation, and the school's federation is saved with it.
        problem = (_set_carsi_school(cfg, args.institution) if args.carsi
                   else _find_school(cfg, args.institution, list(args.also_name or ())))
        if problem:
            print(json.dumps(problem, ensure_ascii=False, indent=2))
            return 1
        saved_schools.remember(cfg)
        changed = True

    if args.output_dir:
        cfg["output_dir"] = str(Path(args.output_dir).expanduser())
        changed = True

    if changed:
        for key in ("output_dir", "cache_dir"):
            if cfg.get(key):
                Path(cfg[key]).mkdir(parents=True, exist_ok=True)
        save_config(cfg)

    if args.check:
        ready, checks, browser = _environment_check(cfg)
        report: dict[str, Any] = {"ready": ready, "checks": checks, "settings": _institutional_summary(cfg)}
        if browser:
            report["browser"] = browser
        if browser.get("outdated"):
            report["warnings"] = [f"Google Chrome {browser['version']} 低于测试过的 {browser['tested']}："
                                  "请先更新 Chrome（菜单 → 帮助 → 关于 Google Chrome）"]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ready else 2

    print(json.dumps({"updated": changed, "settings": _institutional_summary(cfg)}, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# several schools (user, 2026-11-17): list, switch, forget; nothing switches on its own
# ---------------------------------------------------------------------------

def _cmd_schools(_args: argparse.Namespace) -> int:
    from .schools import saved as saved_schools
    from .config import load_config

    cfg = load_config()
    saved_schools.remember(cfg)
    school = saved_schools.current(cfg)
    print(json.dumps({"current": saved_schools.summary(school) if school else None,
                      "schools": [saved_schools.summary(entry, cfg) for entry in saved_schools.saved(cfg)]},
                     ensure_ascii=False, indent=2))
    return 0


def _cmd_use(args: argparse.Namespace) -> int:
    """The named school as the current one: a saved one, else looked up as `setup
    --institution` does and saved too. The one before stays saved."""
    from .schools import saved as saved_schools
    from .config import load_config, save_config

    cfg = load_config()
    saved_schools.remember(cfg)
    matches = saved_schools.find(cfg, args.school)
    if len(matches) > 1:
        print(json.dumps({"error": "school_ambiguous", "query": args.school,
                          "candidates": [saved_schools.summary(entry, cfg) for entry in matches],
                          "hint": "run again with the full name or the entityID of one of them"}, ensure_ascii=False, indent=2))
        return 1
    added = not matches
    if matches:
        saved_schools.apply(cfg, matches[0])
    else:
        problem = _find_school(cfg, args.school, list(args.also_name or ()))
        if problem:
            print(json.dumps(problem, ensure_ascii=False, indent=2))
            return 1
    saved_schools.remember(cfg)
    save_config(cfg)
    print(json.dumps({"switched": True, "added": added, "school": saved_schools.summary(saved_schools.current(cfg) or {}),
                      "settings": _institutional_summary(cfg)}, ensure_ascii=False, indent=2))
    return 0


def _cmd_forget(args: argparse.Namespace) -> int:
    from .schools import saved as saved_schools
    from .config import load_config, save_config

    cfg = load_config()
    saved_schools.remember(cfg)
    matches = saved_schools.find(cfg, args.school)
    if len(matches) != 1:
        print(json.dumps({"error": "school_not_saved" if not matches else "school_ambiguous", "query": args.school,
                          "candidates": [saved_schools.summary(entry, cfg) for entry in matches]}, ensure_ascii=False, indent=2))
        return 1
    if not saved_schools.forget(cfg, matches[0]):
        print(json.dumps({"error": "school_is_current", "query": args.school,
                          "hint": "switch to another school with `use` first"}, ensure_ascii=False, indent=2))
        return 1
    save_config(cfg)
    print(json.dumps({"forgotten": saved_schools.summary(matches[0]),
                      "schools": [saved_schools.summary(entry, cfg) for entry in saved_schools.saved(cfg)]}, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

_LOGIN_MESSAGES = {
    "login_timeout": "等你登录超时了；再运行一次，在弹出的学校登录页里登录即可",
    "login_page_closed": "学校登录页被关闭了，没有完成登录",
    "browser_closed": "下载浏览器被关闭了，没有完成登录",
    "institution_pdf_entitlement_missing": "已登录学校，但学校没有这篇文章的全文权限；换一篇学校订阅的文章再试",
    "login_credentials_rejected": "学校登录页没有接受账号或密码",
    "institution_not_registered": "学校的这个登录入口和这家出版社之间没有开通，经这个入口没有权限",
    "login_not_reached": "程序没能进入学校登录页的输入步骤（停在出版社页面或跳转途中）；详情见诊断文件",
}


def _login_reply(result: dict[str, Any]) -> dict[str, Any]:
    """What ``login`` says: success only when the school's login is confirmed
    and the article opens in full (a window closed by hand is no login)."""
    login = result.get("login") or {}
    artifacts = result.get("artifacts") or {}
    if result.get("success") and login.get("signed_in"):
        return {"success": True, "state": "signed_in",
                "message": "已登录学校，这篇文章能看全文；之后下载沿用这个登录"}
    if result.get("success"):
        return {"success": False, "state": "access_without_login",
                "message": "这篇文章不用登录就能看全文（开放获取或校园网），这次没有验证到学校登录；要测试登录，换一篇需要订阅的文章"}
    # The bridge's reported reason (a wait run out on the school's page is login_timeout);
    # the raw state only behind a general one.
    state = str(result.get("reason_code") or result.get("error_type") or "")
    if state in ("", "paywall", "download_failed"):
        state = str(artifacts.get("state") or state or "login_failed")
    reply: dict[str, Any] = {"success": False, "state": state,
                             "message": _LOGIN_MESSAGES.get(state, f"没有完成登录（{state}）；详情见诊断文件")}
    if artifacts.get("diagnostic"):
        reply["diagnostic"] = artifacts["diagnostic"]
    return reply


def _cmd_login(args: argparse.Namespace) -> int:
    """Sign in to the school the way a download does, without its PDF: the
    download browser (its own Chrome profile) opens the article's page, gets
    past the site's verification, picks the school (CARSI) and waits on the
    school's login page for the user; then the article's access is checked.
    The session stays in that profile for the downloads that follow."""
    from .config import load_config
    from .engine.bridge import _any_institutional_configured

    if not args.doi:
        print(json.dumps({"success": False, "error": "doi_required",
                          "hint": "pass --doi with an article the school subscribes to; its page leads to the school's login"},
                         ensure_ascii=False))
        return 2
    if not _any_institutional_configured(load_config()):
        print(json.dumps({"success": False, "error": "school_not_configured",
                          "hint": 'run: setup --institution "<your school>"'}, ensure_ascii=False))
        return 2
    import shutil
    import tempfile

    from . import progress_reporter
    from .orchestrator import download_institutional

    scratch = Path(tempfile.mkdtemp(prefix="paper-search-login-"))
    progress_reporter.start_task("学校登录", total=1, current=args.doi, phase="打开文章页")
    reply: dict[str, Any] = {"success": False, "state": "login_failed", "message": "没有完成登录"}
    try:
        result = download_institutional(args.doi, scratch, strategy="institutional_only",
                                        login_only=True, login_wait=args.max_wait,
                                        diagnostics_dir=str(_data_dir() / "diagnostics" / "login"))
        reply = _login_reply(result)
    finally:
        progress_reporter.advance(reply["success"], current=args.doi,
                                  phase="已登录学校" if reply["success"] else "没有完成登录")
        progress_reporter.finish()
        shutil.rmtree(scratch, ignore_errors=True)
    print(json.dumps(reply, ensure_ascii=False))
    return 0 if reply["success"] else 1


def _cmd_school_test(args: argparse.Namespace) -> int:
    from .school_test import run

    return run(args.school, args.doi)


# ---------------------------------------------------------------------------
# other commands
# ---------------------------------------------------------------------------

def _cmd_report_export(args: argparse.Namespace) -> int:
    from .config import load_config
    from .failure_export import ExportError, MAX_REQUEST_BYTES, export_report

    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ExportError("export_request_too_large")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ExportError("invalid_export_request")
        result = export_report(request, Path(args.output), load_config())
    except (OSError, ValueError) as exc:
        # Never print original JSON, paths, secrets or exception payloads.
        code = (str(exc) if isinstance(exc, ExportError) else
                "export_target_exists" if isinstance(exc, FileExistsError) else
                "export_permission_denied" if isinstance(exc, PermissionError) else "export_io_or_input_error")
        print(json.dumps({"ok": False, "error": code}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_markdown_report(args: argparse.Namespace) -> int:
    """The Markdown report (markdown_report.py) from the run records PaperSearch names on
    stdin: ``{"schemaVersion": 1, "version", "reports": [{"report", "doi", "title"}]}``."""
    from .config import load_config
    from .markdown_report import ReportError, export

    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ReportError("export_request_too_large")
        request = json.loads(raw)
        if not isinstance(request, dict) or request.get("schemaVersion") != 1 or not isinstance(request.get("reports"), list):
            raise ReportError("invalid_export_request")
        result = export(request["reports"], Path(args.folder or "."), load_config(), str(request.get("version") or ""),
                        output=Path(args.output) if args.output else None)
    except (OSError, ValueError) as exc:
        # Never print original JSON, paths, secrets or exception payloads.
        code = (str(exc) if isinstance(exc, ReportError) else
                "export_permission_denied" if isinstance(exc, PermissionError) else "export_io_or_input_error")
        print(json.dumps({"ok": False, "error": code}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_run(_args: argparse.Namespace) -> int:
    from .server import main as serve

    serve()
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    from .config import SENSITIVE_KEYS, get_config_safe, load_config, update_config

    if args.action == "list":
        print(json.dumps(get_config_safe(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "get":
        value = load_config().get(args.key)
        if args.key in SENSITIVE_KEYS and value:
            value = MASK
        print(json.dumps({args.key: value}, ensure_ascii=False))
        return 0
    if args.action == "set":
        if args.value is None:
            print("config set needs KEY VALUE", file=sys.stderr)
            return 2
        update_config(args.key, args.value)
        print(json.dumps({"updated": args.key}, ensure_ascii=False))
        return 0
    return 2


def _cmd_list_publishers(_args: argparse.Namespace) -> int:
    from .server import school_list_publishers

    print(school_list_publishers())
    return 0


def _cmd_publisher_check(args: argparse.Namespace) -> int:
    """Run one real institutional download and print a report safe to paste into a PR."""
    from . import progress_reporter
    from .orchestrator import download_institutional

    with progress_reporter.tracked_download(args.doi, args.output_dir) as outcome:
        extra = {"fulltext": "sample"} if getattr(args, "fulltext", False) else {}
        if extra:
            # A cached main text would skip the article page, and with it the page's sample.
            from .cache import cache_clear
            from .config import load_config

            cache_clear(args.doi, load_config())
        result = download_institutional(args.doi, args.output_dir, strategy="institutional_only", **extra)
        outcome["result"] = result
    report = {
        "doi": result.get("doi"),
        "success": result.get("success"),
        "source": result.get("source"),
        "error_type": result.get("error_type"),
        "action": result.get("action"),
        "reason_code": result.get("reason_code"),
    }
    if result.get("success") and result.get("file"):
        path = Path(result["file"])
        report["file"] = path.name
        report["size_kb"] = result.get("size_kb")
        try:
            from . import pdf_text

            report["pages"] = pdf_text.page_count(path)
            first = pdf_text.text(path, 1) if report["pages"] else ""
            report["first_page_has_doi"] = (result.get("doi") or "").lower() in first.lower()
        except Exception:
            report["pages"] = None
    page = result.get("fulltext_page")
    if isinstance(page, dict):
        report["fulltext_page"] = {"file": page.get("file"), "url": page.get("url"),
                                   "images": len(page.get("images") or []),
                                   "failed_images": len(page.get("failed_images") or [])}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


def _cmd_preview(args: argparse.Namespace) -> int:
    """Print the live preview of the download browser for the current (or given) run."""
    from .browser.preview import latest_snapshot
    from .config import load_config

    snap = latest_snapshot(load_config(), args.run_id, args.doi)
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    return 0 if snap.get("status") in ("available", "stale", "browser_closed") else 1


def _cmd_entitlements(args: argparse.Namespace) -> int:
    """List, set or clear remembered entitlement decisions."""
    from . import entitlements

    if args.action == "clear":
        if not args.key:
            print(json.dumps({"error": "clear needs a KEY from `entitlements list`"}))
            return 2
        print(json.dumps({"cleared": entitlements.clear(args.key), "key": args.key}, ensure_ascii=False))
        return 0
    if args.action == "set":
        if not args.doi or not args.decision:
            print(json.dumps({"error": "set needs --doi and --decision (allow_journal|skip_journal|skip_publisher)"}))
            return 2
        publisher = args.publisher or ""
        if not publisher:
            from .publishers.profiles import infer_publisher_profile
            profile = infer_publisher_profile(args.doi)
            publisher = getattr(profile, "name", "") if profile else ""
        entry = entitlements.record(args.doi, publisher, args.decision)
        print(json.dumps({"recorded": entry}, ensure_ascii=False, indent=2))
        return 0 if entry else 1
    print(json.dumps(entitlements.load(), ensure_ascii=False, indent=2))
    return 0


def _cmd_cold_start(args: argparse.Namespace) -> int:
    """List, then on confirmation delete, the school sessions of the download browser."""
    from . import cold_start
    from .config import load_config

    run = cold_start.for_config(load_config(), args.profile, args.cache_dir)
    plan = run.plan()
    if plan["browser_running"]:
        print(json.dumps({**plan, "applied": False, "error": "the download browser is using this profile; close it first"},
                         ensure_ascii=False, indent=2))
        return 1
    if not args.yes:
        if not sys.stdin.isatty():
            print(json.dumps({**plan, "applied": False,
                              "hint": "nothing deleted; rerun with --yes to delete what is listed"},
                             ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        sys.stderr.write("Delete the cookies, site data and files listed under delete, site_data and files? [y/N] ")
        sys.stderr.flush()
        if input().strip().lower() not in ("y", "yes"):
            print(json.dumps({"applied": False}))
            return 0
    try:
        done = run.apply()
    except RuntimeError as exc:
        print(json.dumps({"applied": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({**({"plan": plan} if args.yes else {}), "applied": True, "done": done}, ensure_ascii=False, indent=2))
    return 0


def _cmd_issues(args: argparse.Namespace) -> int:
    """Problem reports from the progress window, for review."""
    from . import issues

    if args.action == "resolve":
        if not args.id:
            print(json.dumps({"error": "resolve needs an issue ID"}))
            return 2
        ok = issues.resolve(args.id, args.note or "", status=args.status)
        print(json.dumps({"updated": ok, "id": args.id}, ensure_ascii=False))
        return 0 if ok else 1
    if args.action == "watch":
        # Wait for the user's next report; an agent runs this beside a batch.
        row = issues.wait_for_new(args.since if args.since is not None else time.time(), args.timeout)
        print(json.dumps(issues.summary(row) if row else {"timeout": True}, ensure_ascii=False, indent=2))
        return 0 if row else 3
    if args.action == "show":
        rows = [r for r in issues.list_issues(None) if r["id"] == args.id]
        print(json.dumps(rows[0] if rows else {"error": "not found"}, ensure_ascii=False, indent=2))
        return 0 if rows else 1
    status = None if args.all else "open"
    rows = [{k: r.get(k) for k in ("id", "status", "label", "doi", "journal", "publisher", "phase",
                                     "reported_at", "folder")} for r in issues.list_issues(status)]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


# about: PaperSearch's version and its update, Pro's with it (user, 2026-11-21); pro opens it too, by its old name.
SETTINGS_PAGES = ("home", "about", "download", "wait", "keys", "pro", "markdown", "login")
# PaperSearch Pro's pages (edition.py): Pro itself, its Markdown, the school's sign-in (school_login.py).
PRO_PAGES = ("pro", "markdown", "login")


def _cmd_settings(args: argparse.Namespace) -> int:
    """Open the settings in the progress window, at a page or at one service's key."""
    from . import api_keys, progress_reporter
    from .edition import pro_features

    # Pro's pages are there with PaperSearch Pro's features only (edition.py).
    pages = SETTINGS_PAGES if pro_features() else tuple(p for p in SETTINGS_PAGES if p not in PRO_PAGES)
    target = (args.target or "home").strip()
    page = target if target in pages else "keys"
    found = None if target in pages else api_keys.find(target)
    if page == "keys" and target != "keys" and found is None:
        print(json.dumps({"ok": False, "error": f"没有这一项设置：{target}"}, ensure_ascii=False))
        return 2
    service = found["id"] if found else ""
    # Servers and other machines without a screen keep the terminal: `paper-search setup`.
    terminal = "paper-search setup " + (found["keys"][0]["key"] if found else "<KEY>")
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print(json.dumps({"ok": False, "error": f"这台电脑没有图形界面，打不开设置窗口；请在终端运行 {terminal}"},
                         ensure_ascii=False))
        return 1
    try:
        import webview  # noqa: F401  (the settings are a page of the capsule's web view)
    except Exception:
        print(json.dumps({"ok": False, "error": f"设置窗口需要 pywebview，当前环境里没有；请运行 paper-search school update，或在终端运行 {terminal}"},
                         ensure_ascii=False))
        return 1
    try:
        window = progress_reporter.open_settings(page, service)
    except (OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": f"设置窗口没能打开：{exc}；也可以在终端运行 {terminal}"}, ensure_ascii=False))
        return 1
    reply = {"ok": True, "window": window, "page": page, **({"service": service} if service else {})}
    if os.environ.get("SSH_CONNECTION"):
        reply["note"] = f"窗口开在这台电脑自己的屏幕上；远程连接、看不到这块屏幕时，请在终端运行 {terminal}"
    print(json.dumps(reply, ensure_ascii=False))
    return 0


def _utf8_stdio() -> None:
    """Read and write the standard streams in UTF-8, as PaperSearch does at the
    other end of the pipes. Piped, Python otherwise uses the system code page
    (cp1252, GBK on Windows): a reply with a character it cannot encode stops
    the command with UnicodeEncodeError, and Chinese it can encode reaches
    PaperSearch garbled. Each stream keeps its error handler; a missing stream
    (pythonw) or a replaced one is left alone."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and codecs.lookup(stream.encoding).name != "utf-8":
            stream.reconfigure(encoding="utf-8", errors=stream.errors)


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    # Fingerprint generation needs no parallel linear algebra. On Windows its
    # default OpenBLAS worker pool reserves hundreds of MiB in each backend.
    # Limit only this owned CLI process; keep an explicit caller override.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["progress"]:
        if len(argv) == 1:
            # Bare `progress` opens the floating progress window.
            from .progress_capsule import main as progress_window

            progress_window()
            return 0
        # With options it is the read-only snapshot / watch; progress_status
        # owns its own argument parsing and exit codes.
        from .progress_status import main as progress_main

        return progress_main(argv[1:])
    # progress stays read-only; every other command can be asked for its stacks.
    from .log import enable_stack_dump

    enable_stack_dump()
    parser = argparse.ArgumentParser(prog="paper-search-school")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="start the MCP stdio server").set_defaults(func=_cmd_run)

    st = sub.add_parser("setup", help="show or change institutional access settings")
    st.add_argument("--carsi", action="store_true", help="use the CARSI federation; with --institution only CARSI's member list is asked; without it the school is chosen in the login window")
    st.add_argument("--no-school", action="store_true", help="no federation: the institution is chosen by hand")
    st.add_argument("--institution", help="your school: its name in its own language or English, its domain or its entityID. "
                    "It is looked up in the supported federations' member lists; its federation, names, entityID and "
                    "login hosts are saved and publisher pickers then select only that school")
    st.add_argument("--also-name", action="append", metavar="NAME",
                    help="another name of the same school (its official English name when --institution is in another language); repeatable")
    st.add_argument("--list-carsi-schools", nargs="?", const="", metavar="KEYWORD", help="print CARSI member schools, optionally only those matching KEYWORD")
    st.add_argument("--output-dir")
    st.add_argument("--check", action="store_true", help="environment check; exit 2 when something is missing")
    st.set_defaults(func=_cmd_setup)

    sub.add_parser("schools", help="the saved schools, the current one marked").set_defaults(func=_cmd_schools)
    us = sub.add_parser("use", help="switch the current school: a saved one, else looked up and saved (only when the user asks)")
    us.add_argument("school", help="its name, English name, domain or entityID")
    us.add_argument("--also-name", action="append", metavar="NAME", help="another name of the same school, as for setup")
    us.set_defaults(func=_cmd_use)
    fg = sub.add_parser("forget", help="remove a saved school (not the current one)")
    fg.add_argument("school")
    fg.set_defaults(func=_cmd_forget)

    lg = sub.add_parser("login", help="sign in to the school as a download does, without the PDF")
    lg.add_argument("--doi", default="", help="an article the school subscribes to; its page leads to the school's login")
    lg.add_argument("--max-wait", type=int, default=None,
                    help="seconds to wait on the school's login page (default: the setting browser_login_timeout)")
    lg.set_defaults(func=_cmd_login)

    stt = sub.add_parser("school-test", help="the settings' 测试登录: one download with a saved school, its PDF deleted")
    stt.add_argument("--school", required=True, help="the saved school's entityID")
    stt.add_argument("--doi", required=True)
    stt.set_defaults(func=_cmd_school_test)

    cfg = sub.add_parser("config", help="read or write backend config")
    cfg.add_argument("action", choices=["get", "set", "list"])
    cfg.add_argument("key", nargs="?")
    cfg.add_argument("value", nargs="?")
    cfg.set_defaults(func=_cmd_config)

    sub.add_parser("list-publishers", help="print publisher profiles and their platform labels").set_defaults(func=_cmd_list_publishers)

    exp = sub.add_parser("report-export", help="export a sanitized local failure ZIP from a JSON request on stdin")
    exp.add_argument("--output", required=True)
    exp.set_defaults(func=_cmd_report_export)

    mdr = sub.add_parser("markdown-report-export",
                         help="export the pages of sites not yet supported for Markdown into a sanitized ZIP (JSON request on stdin)")
    mdr.add_argument("--folder", help="folder for PaperSearch-Markdown报告-<date>.zip")
    mdr.add_argument("--output", help="a new .zip path instead")
    mdr.set_defaults(func=_cmd_markdown_report)

    chk = sub.add_parser("publisher-check", help="run one institutional download and print a sanitized report")
    chk.add_argument("--doi", required=True)
    chk.add_argument("--output-dir")
    chk.add_argument("--fulltext", action="store_true",
                     help="also save the article's full-text page and figures in <output-dir>/<DOI>_fulltext_page/, "
                          "with general rules on a site without its own (samples for a new converter)")
    chk.set_defaults(func=_cmd_publisher_check)

    en = sub.add_parser("entitlements", help="remembered has-access / no-access decisions per journal or publisher")
    en.add_argument("action", nargs="?", default="list", choices=["list", "set", "clear"])
    en.add_argument("key", nargs="?", help="entry key for clear (from `entitlements list`)")
    en.add_argument("--doi", help="a paper of the journal/publisher to mark (set)")
    en.add_argument("--decision", choices=["allow_journal", "skip_journal", "skip_publisher"])
    en.add_argument("--publisher", help="publisher profile name; inferred from the DOI when omitted")
    en.set_defaults(func=_cmd_entitlements)

    cs = sub.add_parser("cold-start", help="forget school sessions in the download browser (lists first)")
    cs.add_argument("--yes", action="store_true", help="delete without asking")
    cs.add_argument("--profile", help="another Chrome profile directory (default: the download profile)")
    cs.add_argument("--cache-dir", help="the cache whose saved cookie files to filter "
                    "(default: the configured one; none with --profile)")
    cs.set_defaults(func=_cmd_cold_start)

    iss = sub.add_parser("issues", help="problem reports filed from the progress window")
    iss.add_argument("action", nargs="?", default="list", choices=["list", "show", "resolve", "watch"])
    iss.add_argument("id", nargs="?")
    iss.add_argument("--note", help="review conclusion (resolve)")
    iss.add_argument("--status", default="resolved", choices=["resolved", "wont_fix", "open"])
    iss.add_argument("--all", action="store_true", help="list reviewed reports too")
    iss.add_argument("--since", type=float, help="watch: reports filed after this time (epoch seconds; default now)")
    iss.add_argument("--timeout", type=float, default=3600, help="watch: give up after this many seconds")
    iss.set_defaults(func=_cmd_issues)

    pv = sub.add_parser("preview", help="latest screenshots of the download browser (JSON)")
    pv.add_argument("--run-id", default=None)
    pv.add_argument("--doi", default=None)
    pv.set_defaults(func=_cmd_preview)

    sub.add_parser("progress", help="open the progress window; `progress --json` for a read-only snapshot", add_help=False)

    stg = sub.add_parser("settings", help="show the progress window's settings")
    stg.add_argument("target", nargs="?", help="download, wait, keys, or an API key name such as EASYSCHOLAR_KEY")
    stg.set_defaults(func=_cmd_settings)

    args = parser.parse_args(argv)
    if args.command == "config" and args.action != "list" and not args.key:
        parser.error("config get/set needs KEY")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
