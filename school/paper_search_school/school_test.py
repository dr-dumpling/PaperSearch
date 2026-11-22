"""The sign-in page's 测试登录 (PaperSearch Pro; user, 2026-11-21): one article downloaded with a saved school's
account, the way a download goes (the school chosen, its sign-in filled in, back to the article, the PDF fetched and
checked), to see that the account works; the PDF is deleted after. It starts signed out (the download browser's school
sign-ins and publisher sessions forgotten, cold_start.before_sign_in): a session left by another school, or by this one,
would open the article without the account.

The article: the one the user set for the school (its DOI or its page's address, ``set_article``); none is set for
them (user, 2026-11-21: they fill it in themselves, one their school subscribes to). The test runs as a process of its own
(``python -m paper_search_school.cli school-test``) that reports as a download does (the window's progress file) and
writes its verdict to ``progress/school-test.json``; the window asks ``SchoolTest.state()`` until it ends. It stops the
way the card's 终止任务 stops a download.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .data_home import default_data_dir

#: The task the progress file names while a test runs.
TASK = "学校登录测试"
#: The steps the page shows, by the download's stage (progress_reporter.STAGES).
STEPS = ("打开文章页", "学校登录", "下载全文", "核对 PDF")
STAGE_STEP = {"starting": 0, "opening_article": 0, "checking_access": 1, "waiting_login": 1, "waiting_verification": 1,
              "route_failed": 1, "fetching_pdf": 2, "pdf_captured": 3, "saved_pending_verification": 3}
#: How long a stopped test may take to end before its process is ended.
STOP_GRACE = 30.0
AGENT = {"User-Agent": "Mozilla/5.0 (PaperSearch school test; +https://github.com/dr-dumpling/papersearch)"}


def _articles_path() -> Path:
    return default_data_dir() / "school_test_articles.json"


def result_path() -> Path:
    return default_data_dir() / "progress" / "school-test.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


# -- the article ----------------------------------------------------------------------------------

def article(entity_id: str) -> dict[str, Any]:
    """The article this school's test opens: {doi}, "" while none is set."""
    return {"doi": str((_read(_articles_path()).get(entity_id) or {}).get("doi") or "") if entity_id else ""}


def set_article(entity_id: str, text: str, fetch=None) -> dict[str, Any]:
    """The article the user set for this school's test, by its DOI or its page's address (``doi_of``); empty: none.
    {ok, doi} or {ok: False, error}."""
    text = str(text or "").strip()
    data = _read(_articles_path())
    if not text:
        data.pop(entity_id, None)
    else:
        doi, error = doi_of(text, fetch)
        if not doi:
            return {"ok": False, "error": error}
        data[entity_id] = {"doi": doi, "given": text[:500]}
    _write(_articles_path(), data)
    return {"ok": True, **article(entity_id)}


_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#&]+")
#: What a publisher puts after the DOI in an article's address (/full, .pdf); bioRxiv's version (v2) besides.
_AFTER_DOI = re.compile(r"(?:/(?:full|abstract|pdf|epdf|fulltext|meta|html|references|figures)|\.(?:pdf|full|abstract))$", re.I)


def _get(url: str, fetch=None):
    if fetch is None:
        import requests

        fetch = requests.get
    return fetch(url, timeout=15, headers=AGENT)


def _http_json(url: str, fetch=None) -> dict[str, Any]:
    response = _get(url, fetch)
    response.raise_for_status()
    return response.json()


def doi_of(text: str, fetch=None) -> tuple[str, str]:
    """(the DOI, "") of an article given by its DOI or its page's address; ("", why not) when it cannot be told.
    In the address itself (doi.org, Springer, Wiley, Taylor & Francis, NEJM ...); Nature's by its article's name;
    PubMed's by its PMID (NCBI); ScienceDirect's, Cell's and the Lancet's by its PII (Crossref); else the page's own
    citation_doi, where the site lets it be read (Oxford's and JAMA's turn such a request away)."""
    from .identifiers import normalize_doi, to_halfwidth

    text = to_halfwidth(str(text or "")).strip()
    plain = urllib.parse.unquote(text)
    found = _DOI.search(normalize_doi(plain)) or _DOI.search(plain)
    if found:
        doi = found.group(0).rstrip(".,;:。，；")
        while doi.endswith(")") and doi.count(")") > doi.count("("):  # a bracket around it, not one of its own
            doi = doi[:-1]
        while _AFTER_DOI.search(doi):
            doi = _AFTER_DOI.sub("", doi)
        if doi.lower().startswith("10.1101/"):
            doi = re.sub(r"v\d+$", "", doi)
        return doi, ""
    if not re.match(r"https?://", plain, re.I):
        return "", "认不出这篇文章：请填 DOI 或文章网址"
    host = (urllib.parse.urlparse(plain).hostname or "").lower()
    path = urllib.parse.urlparse(plain).path
    try:
        nature = re.match(r"/articles/([a-z0-9.\-]+)", path, re.I) if host.endswith("nature.com") else None
        if nature:
            return "10.1038/" + nature.group(1), ""
        pubmed = re.match(r"/(\d{5,9})", path) if host == "pubmed.ncbi.nlm.nih.gov" else None
        if pubmed:
            pmid = pubmed.group(1)
            result = _http_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json",
                                fetch).get("result", {}).get(pmid, {})
            doi = next((a.get("value") for a in result.get("articleids") or [] if a.get("idtype") == "doi"), "")
            return (doi, "") if doi else ("", "PubMed 没有这篇的 DOI，请改填 DOI")
        pii = re.search(r"(?:/pii/|/fulltext/|/abstract/|/PII)(S[0-9X()\-]{15,})", path, re.I)
        if pii:
            key = re.sub(r"[^0-9X]", "", pii.group(1).upper()[1:])
            items = _http_json(f"https://api.crossref.org/works?filter=alternative-id:S{key}&rows=1&select=DOI",
                               fetch).get("message", {}).get("items") or []
            if items:
                return str(items[0]["DOI"]), ""
        page = _get(plain, fetch)
        meta = re.search(r"<meta[^>]+name=[\"'](?:citation_doi|dc\.identifier|prism\.doi)[\"'][^>]+content=[\"']([^\"']+)",
                         page.text if page.status_code == 200 else "", re.I)
        doi = _DOI.search(html.unescape(meta.group(1))) if meta else None
        if doi:
            return doi.group(0), ""
    except Exception:
        return "", "没能查到这个网址的 DOI，请改填 DOI"
    return "", "这个网址读不出 DOI，请改填 DOI（文章页上 doi.org/10. 开头的那串）"


# -- the verdict ----------------------------------------------------------------------------------

_LOGIN_UNFINISHED = {"login_timeout", "login_not_reached", "login_retries_exhausted", "login_page_closed",
                     "idp_login_error", "idp_no_return_to_publisher", "institution_federation_unavailable",
                     "institution_not_registered"}


def judge(result: dict[str, Any], *, filled: bool, refused: bool) -> dict[str, Any]:
    """What the page says of a test: ok, a title and a line under it. ``filled``: Pro typed the account in during
    the test; ``refused``: the school turned the password down (Pro turned the account off)."""
    kind = str(result.get("error_type") or "")
    if result.get("success"):
        return {"ok": True, "title": "登录和下载都正常",
                "detail": "自动填写了账号密码，全文已下载并核对" if filled
                else "这次没有用到账号密码：浏览器里还是登录状态，或学校网络直接有权限"}
    if refused or kind == "login_credentials_rejected":
        return {"ok": False, "title": "学校说密码不对", "detail": "自动登录已关闭；改好密码后保存，再测一次"}
    if kind == "idp_account_locked":
        return {"ok": False, "title": "学校说账号被锁定", "detail": "先到学校网站解锁账号，再测一次"}
    if kind == "idp_password_expired":
        return {"ok": False, "title": "学校说密码已过期", "detail": "先到学校网站改密码，改好后保存，再测一次"}
    if kind == "batch_stopped":
        return {"ok": False, "title": "已停止测试", "detail": ""}
    if kind == "paywall" and result.get("reason_code") == "institution_pdf_entitlement_missing" or kind == "no_entitlement":
        return {"ok": False, "title": "登录成功，但这篇没有访问权限", "detail": "学校可能没订这本刊，换一篇再测"}
    if kind in _LOGIN_UNFINISHED or kind == "paywall":
        return {"ok": False, "title": "没有完成学校登录",
                "detail": "自动填写了账号密码，但没有回到文章；学校可能还要验证码或二次验证" if filled
                else "卡在学校登录这一步；学校的登录页要你自己操作时，在下载浏览器里完成"}
    if kind == "access_blocked":
        return {"ok": False, "title": "出版社网站拦住了访问", "detail": "稍后再测，或换一篇"}
    if kind == "download_timeout":
        return {"ok": False, "title": "没有拿到全文", "detail": "页面或安全验证一直没有完成，换一篇或稍后再测"}
    if kind == "network_unavailable":
        return {"ok": False, "title": "网络不通", "detail": "检查网络后再测"}
    if kind in ("browser_closed", "browser_connection_lost"):
        return {"ok": False, "title": "下载浏览器关掉了", "detail": "再测一次"}
    if kind == "browser_busy":
        return {"ok": False, "title": "下载浏览器还开着", "detail": "等下载结束、关掉下载浏览器后再测"}
    if kind in ("school_not_saved", "school_ambiguous"):
        return {"ok": False, "title": "没有找到这所学校", "detail": "回到学校列表，重新添加后再测"}
    return {"ok": False, "title": "没有下载成功", "detail": f"原因代码：{kind or 'unknown'}"}


# -- the test's own process -----------------------------------------------------------------------

def _signed_in_since(entity_id: str, since: float) -> bool:
    """Whether Pro typed this school's account in since ``since`` (school_login.take_turn counts each)."""
    from .school_login import _turns_file

    times = _read(_turns_file()).get(entity_id) or []
    return any(isinstance(t, (int, float)) and t >= since for t in times)


def _account_off(entity_id: str) -> str:
    from . import school_login
    from .config import load_config

    return str((school_login.saved(load_config(), entity_id) or {}).get("off") or "")


def run(entity_id: str, doi: str) -> int:
    """``school-test``: the download, reported as one; its verdict in ``result_path()``."""
    from . import progress_reporter
    from .orchestrator import download_institutional

    since, started = time.time(), time.monotonic()
    off_before = _account_off(entity_id)
    scratch = Path(tempfile.mkdtemp(prefix="paper-search-school-test-"))
    progress_reporter.start_task(TASK, total=1, current=doi, phase="打开文章页")
    result: dict[str, Any] = {}
    try:
        # Not from the cache, not into it: the test is the download itself.
        result = download_institutional(doi, scratch, strategy="institutional_only", school=entity_id, fresh=True)
    finally:
        ok = bool(result.get("success"))
        progress_reporter.advance(ok, current=doi, phase="测试通过" if ok else "测试没有通过")
        progress_reporter.finish()
        shutil.rmtree(scratch, ignore_errors=True)  # the PDF goes with it
    verdict = judge(result, filled=_signed_in_since(entity_id, since),
                    refused=_account_off(entity_id) == "rejected" and off_before != "rejected")
    _write(result_path(), {"key": entity_id, "doi": doi, "seconds": round(time.monotonic() - started), **verdict})
    return 0 if verdict["ok"] else 1


# -- the window's side ----------------------------------------------------------------------------

def _live(doi: str) -> dict[str, Any]:
    """Where the running test is: its step and what the download says (a reminder first)."""
    from .progress_reporter import read_state

    state = read_state() or {}
    if state.get("task") != TASK or str(state.get("current") or "") != doi:
        return {"step": 0, "phase": ""}
    attention = [value for value in (state.get("attention") or {}).values() if isinstance(value, dict)]
    phase = str(attention[-1].get("message") or "") if attention else str(state.get("phase") or "")
    return {"step": STAGE_STEP.get(str(state.get("stage") or ""), 0), "phase": phase, "run_id": str(state.get("run_id") or "")}


class SchoolTest:
    """The settings window's 测试登录: one test at a time, its process watched in the background."""

    def __init__(self, popen=None) -> None:
        self._popen = popen or subprocess.Popen
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"state": "idle"}
        self._process: Any = None

    def state(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        if state.get("state") == "running":
            live = _live(str(state.get("doi") or ""))
            live.pop("run_id", None)
            state.update(live)
        return state

    def start(self, entity_id: str, doi: str) -> dict[str, Any]:
        from .progress_reporter import read_state

        with self._lock:
            if self._state.get("state") == "running":
                return dict(self._state)
        if (read_state() or {}).get("status") == "running":
            return {"state": "idle", "error": "正在下载，等这次下载结束再测试"}
        result_path().unlink(missing_ok=True)
        command = [sys.executable, "-m", "paper_search_school.cli", "school-test", "--school", entity_id, "--doi", doi]
        extra = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
        process = self._popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
        with self._lock:
            self._process = process
            self._state = {"state": "running", "key": entity_id, "doi": doi, "started": time.time(), "step": 0, "phase": ""}
        threading.Thread(target=self._wait, args=(process, entity_id, doi), name="school-test", daemon=True).start()
        return self.state()

    def _wait(self, process: Any, entity_id: str, doi: str) -> None:
        process.wait()
        verdict = _read(result_path())
        if verdict.get("key") != entity_id or verdict.get("doi") != doi:
            with self._lock:
                stopped = bool(self._state.get("stopping"))
            verdict = ({"ok": False, "title": "已停止测试", "detail": ""} if stopped
                       else {"ok": False, "title": "测试没有完成", "detail": "测试进程意外结束，可以再测一次"})
        with self._lock:
            self._process = None
            self._state = {"state": "done", "key": entity_id, "doi": doi, "ok": bool(verdict.get("ok")),
                           "title": str(verdict.get("title") or ""), "detail": str(verdict.get("detail") or ""),
                           "seconds": int(verdict.get("seconds") or 0)}

    def stop(self) -> dict[str, Any]:
        """Asked to stop as the card's 终止任务 asks a download; ended after STOP_GRACE if it goes on."""
        from .entitlements import STOP_BATCH, request_action

        with self._lock:
            process, doi = self._process, str(self._state.get("doi") or "")
            if process is None:
                return dict(self._state)
            self._state = {**self._state, "stopping": True}
        run_id = _live(doi).get("run_id")
        if run_id:
            request_action(doi, STOP_BATCH, run_id)

        def end_later() -> None:
            try:
                process.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                process.terminate()

        threading.Thread(target=end_later, name="school-test-stop", daemon=True).start()
        return self.state()

    def forget(self) -> None:
        """A finished test's verdict no longer shown (another school opened, the page left)."""
        with self._lock:
            if self._state.get("state") == "done":
                self._state = {"state": "idle"}
