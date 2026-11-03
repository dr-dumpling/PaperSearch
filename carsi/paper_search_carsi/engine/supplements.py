"""Download an article's supplementary files with the browser session.

The adapter lists the links (``supplement_links``); this module fetches them
through the page's own request context, so the institution login and
Cloudflare clearance apply, and saves them next to the main text:

    <output dir>/<DOI>_supplements/<original file name>
    <output dir>/<DOI>_supplements/manifest.json

Every file is recorded, including the ones that failed or were skipped, with
the reason. Limits keep one article from stalling a batch.
"""
from __future__ import annotations

import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

from ..adapters.base import SupplementLink

MAX_FILES = 50
MAX_FILE_BYTES = 200 * 1024 * 1024
TIME_BUDGET_SEC = 180
REQUEST_TIMEOUT_MS = 60_000
# The connection dropped before any answer: worth one more request.
_DROPPED_CONNECTION = ("socket disconnected", "socket hang up", "ECONNRESET", "EPIPE")


def supplements_dir(output_dir: Path, doi: str) -> Path:
    return Path(output_dir) / (re.sub(r"[^A-Za-z0-9._-]+", "_", doi) + "_supplements")


def _file_name(url: str, disposition: str, taken: set[str], label: str = "", content_type: str = "") -> str:
    match = re.search(r"filename\*=(?:UTF-8'')?([^;]+)|filename=\"?([^\";]+)\"?", disposition or "", re.I)
    raw = unquote((match.group(1) or match.group(2)).strip()) if match else ""
    if not raw:
        parsed = urlparse(url)
        file_param = re.search(r"(?:^|&)file=([^&]+)", parsed.query)
        raw = unquote(file_param.group(1)) if file_param else unquote(parsed.path.rsplit("/", 1)[-1])
    if not re.search(r"\.[A-Za-z0-9]{1,5}$", raw):
        # A short link without the file's name (links.lww.com/CORR/B539): the
        # name in the link's text ("..._SDC1.docx (46.34 KB)"), else the type's extension.
        named = re.search(r"[\w\-()+.]+\.[A-Za-z0-9]{2,5}(?=\s|$|\()", label or "")
        extension = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
        raw = named.group(0) if named else f"{raw or 'supplement'}{extension}"
    name = re.sub(r"[^\w.\-()+ ]+", "_", raw).strip(" ._") or "supplement"
    stem, dot, ext = name.rpartition(".")
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f"{stem or name}_{n}{dot}{ext}" if dot else f"{name}_{n}"
        n += 1
    taken.add(candidate.lower())
    return candidate


class _Downloaded:
    """A file the browser downloaded itself, shaped like Playwright's APIResponse."""

    def __init__(self, body: bytes, name: str):
        self._body = body
        self.status = 200
        self.ok = True
        self.headers = {"content-type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                        "content-disposition": f'attachment; filename="{name}"',
                        "content-length": str(len(body))}

    def body(self) -> bytes:
        return self._body


def _get(request: Any, url: str, entry: dict[str, Any], sleep) -> Any:
    """GET the file; once more after the connection dropped before any answer
    (a CDN's TLS handshake cut off midway, Oxford Academic 2026-11-01)."""
    try:
        return request.get(url, timeout=REQUEST_TIMEOUT_MS)
    except Exception as exc:
        if not any(marker in str(exc) for marker in _DROPPED_CONNECTION):
            raise
        entry["retried"] = str(exc).splitlines()[0][:120]
    sleep(2)
    return request.get(url, timeout=REQUEST_TIMEOUT_MS)


def collect(request: Any, links: Iterable[SupplementLink], output_dir: Path, doi: str, *,
            clock=time.monotonic, sleep=time.sleep,
            download: Callable[[str], tuple[bytes, str]] | None = None,
            progress: Callable[[int], None] | None = None) -> list[dict[str, Any]]:
    """Fetch ``links`` with ``request`` (a Playwright APIRequestContext). A file
    refused with 403 is taken through ``download`` when given: the browser
    opens it and downloads it itself (Taylor & Francis behind Cloudflare
    refused every scripted request with ego, the page's own fetch included,
    and let the browser's own navigation through, 2026-11-01). ``progress`` is
    told how many files are saved after each one (the progress window)."""
    unique: list[SupplementLink] = []
    for link in links:
        if link.url and link.url not in {u.url for u in unique}:
            unique.append(link)
    if not unique:
        return []
    target = supplements_dir(output_dir, doi)
    target.mkdir(parents=True, exist_ok=True)
    started = clock()
    taken: set[str] = set()
    files: list[dict[str, Any]] = []
    for index, link in enumerate(unique):
        entry: dict[str, Any] = {"url": link.url, "label": link.label}
        if index >= MAX_FILES:
            entry.update(status="skipped", reason="file_limit")
        elif clock() - started > TIME_BUDGET_SEC:
            entry.update(status="skipped", reason="time_budget")
        else:
            try:
                response = _get(request, link.url, entry, sleep)
                if response.status == 403 and download is not None:
                    response = _Downloaded(*download(link.url))
                    entry["via"] = "browser_download"
                content_type = str(response.headers.get("content-type", "") or "")
                length = int(response.headers.get("content-length") or 0)
                if not response.ok:
                    entry.update(status="failed", reason=f"http_{response.status}")
                elif length > MAX_FILE_BYTES:
                    entry.update(status="skipped", reason="too_large", size=length)
                elif "text/html" in content_type.lower():
                    # A login wall or landing page instead of the file.
                    entry.update(status="failed", reason="html_page")
                else:
                    body = response.body()
                    if len(body) > MAX_FILE_BYTES:
                        entry.update(status="skipped", reason="too_large", size=len(body))
                    else:
                        name = _file_name(link.url, str(response.headers.get("content-disposition", "") or ""), taken,
                                          link.label, content_type)
                        path = target / name
                        path.write_bytes(body)
                        entry.update(status="saved", file=str(path), size=len(body),
                                     content_type=content_type.split(";")[0].strip())
            except Exception as exc:
                entry.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:160]}")
        files.append(entry)
        if progress is not None:
            progress(sum(1 for f in files if f.get("status") == "saved"))
    (target / "manifest.json").write_text(
        json.dumps({"doi": doi, "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
    return files
