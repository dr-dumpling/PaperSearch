"""Problem reports from the progress window, for the agent to review.

The user picks a problem for the current paper in the progress window
("redirected to the wrong page", "the PDF is open but was not saved", ...).
The report is written at once with what the window knows (paper, journal,
publisher, phase, latest live-preview screenshots) and marked
``needs_page_capture``. The running download picks it up within seconds
(``engine/batch_user.py``): it adds the live page (URL, title, text
excerpt, screenshots of every tab, recent events), does what the kind of
report asks and records the outcome under ``handled``. Reports stay "open"
until reviewed: ``paper-search-carsi issues``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ISSUE_KINDS: dict[str, str] = {
    "pdf_not_captured": "PDF 已打开，但没保存",
    "wrong_redirect": "跳到了无关页面",
    "personal_login": "跳到了个人账号登录",
    "no_institution_page": "没出现机构登录或选学校",
    "wrong_school": "选错了学校",
    "stuck_loading": "一直加载或验证过不去",
    "other": "其他问题",
}
CAPTURE_WINDOW_SEC = 30 * 60


def _data_dir() -> Path:
    return Path(os.environ.get("CARSI_DATA_DIR", str(Path.home() / ".local" / "share" / "paper-search-cli" / "carsi")))


def issues_dir() -> Path:
    return _data_dir() / "issues"


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".issue.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _copy_preview_frames(run_id: str, target: Path) -> list[str]:
    """Latest live-preview screenshots of this run (what the user was looking at)."""
    copied: list[str] = []
    try:
        run_dir = _data_dir() / "previews" / run_id
        current = json.loads((run_dir / "current.json").read_text(encoding="utf-8"))
        for row in current.get("pages", []):
            name = row.get("image_name")
            if name and (run_dir / name).exists():
                dest = target / f"preview-page{row.get('page_id', len(copied) + 1)}{Path(name).suffix or '.png'}"
                shutil.copyfile(run_dir / name, dest)
                copied.append(dest.name)
    except Exception:
        pass
    return copied


def report(current: str, kind: str, state: dict[str, Any] | None = None, note: str = "") -> Path:
    """Write a problem report for the current paper; returns its directory."""
    if kind not in ISSUE_KINDS:
        raise ValueError("unknown issue kind")
    state = state or {}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    issue_id = f"{stamp}-{re.sub(r'[^A-Za-z0-9._-]+', '_', current or 'unknown')[:80]}"
    folder = issues_dir() / issue_id
    folder.mkdir(parents=True, exist_ok=True)
    frames = _copy_preview_frames(str(state.get("run_id") or ""), folder)
    data = {
        "id": issue_id,
        "status": "open",
        "kind": kind,
        "label": ISSUE_KINDS[kind],
        "note": note,
        "doi": current,
        "journal": state.get("journal", ""),
        "publisher": state.get("publisher", ""),
        "task": state.get("task", ""),
        "phase": state.get("phase", ""),
        "stage": state.get("stage", ""),
        "run_id": state.get("run_id", ""),
        "batch_id": state.get("batch_id", ""),
        "reported_at": datetime.now().isoformat(timespec="seconds"),
        "reported_ts": time.time(),
        "preview_frames": frames,
        "needs_page_capture": True,
        "page": None,
        "review": None,
    }
    _write(folder / "issue.json", data)
    return folder


def mark_handled(folder: Path, action: str, text: str) -> None:
    """Record what the running download did about a report (never raises)."""
    data = _load(folder)
    if not data:
        return
    data["handled"] = {"at": datetime.now().isoformat(timespec="seconds"), "action": action, "result": text}
    try:
        _write(folder / "issue.json", data)
    except Exception:
        pass


def kind_of(folder: Path) -> str:
    return str((_load(folder) or {}).get("kind") or "other")


def _load(folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads((folder / "issue.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def pending_captures(doi: str) -> list[Path]:
    """Reports for this paper still waiting for the live page."""
    root = issues_dir()
    if not root.exists():
        return []
    found = []
    now = time.time()
    for folder in sorted(root.iterdir()):
        data = _load(folder) if folder.is_dir() else None
        if (data and data.get("needs_page_capture") and str(data.get("doi", "")).lower() == (doi or "").lower()
                and now - float(data.get("reported_ts", 0)) < CAPTURE_WINDOW_SEC):
            found.append(folder)
    return found


def attach_page(folder: Path, page: Any, events: list[dict[str, Any]] | None = None) -> None:
    """Add the download browser's live state to a report (never raises)."""
    data = _load(folder)
    if not data:
        return
    info: dict[str, Any] = {"captured_at": datetime.now().isoformat(timespec="seconds"), "tabs": []}
    try:
        tabs = [p for p in list(page.context.pages) if not p.is_closed()]
    except Exception:
        tabs = [page]
    for index, tab in enumerate(tabs[:6], 1):
        row: dict[str, Any] = {"index": index, "working_tab": tab is page}
        for key, getter in (("url", lambda t: t.url), ("title", lambda t: t.title())):
            try:
                row[key] = getter(tab)
            except Exception:
                row[key] = ""
        try:
            row["text_excerpt"] = tab.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 3000)")
        except Exception:
            row["text_excerpt"] = ""
        try:
            name = f"tab{index}.png"
            tab.screenshot(path=str(folder / name), full_page=False)
            row["screenshot"] = name
        except Exception:
            pass
        info["tabs"].append(row)
    if events is not None:
        info["recent_events"] = events[-40:]
    data["page"] = info
    data["needs_page_capture"] = False
    _write(folder / "issue.json", data)


def list_issues(status: str | None = "open") -> list[dict[str, Any]]:
    root = issues_dir()
    if not root.exists():
        return []
    rows = []
    for folder in sorted(root.iterdir()):
        data = _load(folder) if folder.is_dir() else None
        if data and (status is None or data.get("status") == status):
            rows.append({**data, "folder": str(folder)})
    return rows


def wait_for_new(since: float, timeout: float, *, settle: float = 30.0, poll: float = 1.0) -> dict[str, Any] | None:
    """The first report filed after ``since`` (epoch seconds), once the download
    has captured its page and acted on it (or ``settle`` seconds passed); None
    after ``timeout``. An agent running a batch keeps this waiting, so a click
    reaches it at once, with what the download did about it."""
    deadline = time.time() + timeout
    while True:
        for row in list_issues(None):
            filed = float(row.get("reported_ts") or 0)
            ready = not row.get("needs_page_capture") and row.get("handled")
            if filed > since and (ready or time.time() - filed > settle):
                return row
        if time.time() >= deadline:
            return None
        time.sleep(poll)


def summary(row: dict[str, Any]) -> dict[str, Any]:
    """What an agent reads first: the report, its handling and each captured tab."""
    folder = Path(str(row.get("folder") or ""))
    tabs = [{**{k: tab.get(k) for k in ("index", "working_tab", "url", "title")},
             "text_excerpt": str(tab.get("text_excerpt") or "")[:600],
             **({"screenshot": str(folder / tab["screenshot"])} if tab.get("screenshot") else {})}
            for tab in ((row.get("page") or {}).get("tabs") or [])]
    keys = ("id", "kind", "label", "doi", "journal", "publisher", "phase", "stage",
            "reported_at", "reported_ts", "handled", "folder")
    return {**{k: row.get(k) for k in keys}, "tabs": tabs}


def resolve(issue_id: str, note: str, status: str = "resolved") -> bool:
    folder = issues_dir() / issue_id
    data = _load(folder)
    if not data:
        return False
    data["status"] = status
    data["review"] = {"note": note, "reviewed_at": datetime.now().isoformat(timespec="seconds")}
    _write(folder / "issue.json", data)
    return True
