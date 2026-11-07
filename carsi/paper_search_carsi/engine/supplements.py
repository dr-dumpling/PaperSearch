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
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

from ..adapters.base import SupplementLink
from ..browser.watchdog import BrowserUnresponsive, BrowserOperationTimeout
from ..browser import watchdog
from ..entitlements import UserMarkedNoEntitlement, UserSkippedArticle, UserStoppedBatch

MAX_FILES = 50
MAX_FILE_BYTES = 200 * 1024 * 1024
# No progress for this long ends the collection; active transfers refresh it.
TIME_BUDGET_SEC = 180
# Still bounded even when a server trickles bytes forever; below the MCP cap.
MAX_COLLECTION_SEC = 900
REQUEST_TIMEOUT_MS = 60_000
# The connection dropped before any answer: worth one more request.
_DROPPED_CONNECTION = ("socket disconnected", "socket hang up", "ECONNRESET", "EPIPE")


class SupplementTooLarge(ValueError):
    def __init__(self, size: int):
        self.size = size
        super().__init__("attachment exceeds file size limit")


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

    def __init__(self, body: bytes | Path, name: str):
        self._body = body
        self.status = 200
        self.ok = True
        self.headers = {"content-type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                        "content-disposition": f'attachment; filename="{name}"',
                        "content-length": str(body.stat().st_size if isinstance(body, Path) else len(body))}

    def chunks(self):
        if isinstance(self._body, Path):
            with self._body.open("rb") as fh:
                while chunk := fh.read(64 * 1024):
                    yield chunk
        else:
            yield self._body

    def dispose(self):
        if isinstance(self._body, Path):
            self._body.unlink(missing_ok=True)


def _check_interrupted() -> None:
    if watchdog.interrupted is not None:
        raise watchdog.interrupted


def _get(request: Any, url: str, entry: dict[str, Any], sleep) -> Any:
    """GET the file; once more after the connection dropped before any answer
    (a CDN's TLS handshake cut off midway, Oxford Academic 2026-11-01)."""
    _check_interrupted()
    try:
        return request.get(url, timeout=REQUEST_TIMEOUT_MS)
    except (BrowserUnresponsive, UserMarkedNoEntitlement):
        raise
    except Exception as exc:
        if not any(marker in str(exc) for marker in _DROPPED_CONNECTION):
            raise
        entry["retried"] = "socket disconnected before response"
    _check_interrupted()
    sleep(2)
    _check_interrupted()
    return request.get(url, timeout=REQUEST_TIMEOUT_MS)


# Response headers that name what answered instead of the file (a CDN's or a
# firewall's challenge, a login service), kept for the record.
_PAGE_HEADERS = ("server", "x-amzn-waf-action", "cf-mitigated", "location")


def _page_evidence(response: Any) -> dict[str, Any]:
    """What a page received instead of a file was: its status, final address
    (no query), title and telling headers. Figshare's download address answered a
    page and nothing said which (AIP, Royal Society, AACR; 2026-11-08)."""
    evidence: dict[str, Any] = {"http_status": getattr(response, "status", None)}
    url = str(getattr(response, "url", "") or "")
    if url:
        evidence["final_url"] = url.split("?", 1)[0][:300]
    headers = getattr(response, "headers", None) or {}
    named = {key: str(headers.get(key))[:120] for key in _PAGE_HEADERS if headers.get(key)}
    if named:
        evidence["page_headers"] = named
    try:
        text = response.body()[:65536].decode("utf-8", "replace")
    except Exception:
        return evidence
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if title:
        from html import unescape

        evidence["page_title"] = " ".join(unescape(title.group(1)).split())[:160]
    return evidence


def collect(request: Any, links: Iterable[SupplementLink], output_dir: Path, doi: str, *,
            clock=time.monotonic, sleep=time.sleep,
            manifest_dir: Path | None = None,
            target_dir: Path | None = None,
            download: Callable[[str], tuple[bytes | Path, str]] | None = None,
            progress: Callable[[int], None] | None = None,
            activity: Callable[[], None] | None = None) -> list[dict[str, Any]]:
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
    target = target_dir or supplements_dir(output_dir, doi)
    target.mkdir(parents=True, exist_ok=True)
    started = last_progress = clock()
    taken: set[str] = set()
    files: list[dict[str, Any]] = []
    stopped_reason = ""
    for index, link in enumerate(unique):
        entry: dict[str, Any] = {"url": link.url, "label": link.label}
        if stopped_reason:
            entry.update(status="skipped", reason=stopped_reason)
        elif link.error:
            entry.update(status="failed", reason=link.error)
        elif index >= MAX_FILES:
            entry.update(status="skipped", reason="file_limit")
        elif clock() - started > MAX_COLLECTION_SEC or clock() - last_progress > TIME_BUDGET_SEC:
            entry.update(status="skipped", reason="time_budget")
        else:
            try:
                response = None
                response = _get(request, link.url, entry, sleep)
                _check_interrupted()
                if response.status == 403 and download is not None:
                    if callable(getattr(response, "dispose", None)):
                        response.dispose()
                    response = None
                    response = _Downloaded(*download(link.url))
                    entry["via"] = "browser_download"
                    _check_interrupted()
                content_type = str(response.headers.get("content-type", "") or "")
                length = int(response.headers.get("content-length") or 0)
                if not response.ok:
                    entry.update(status="failed", reason=f"http_{response.status}")
                elif length > MAX_FILE_BYTES:
                    entry.update(status="skipped", reason="too_large", size=length)
                elif "text/html" in content_type.lower():
                    # A login wall or landing page instead of the file: which one, for the record.
                    # A firewall's human verification page is told apart (Figshare's AWS WAF,
                    # 2026-11-08): the site stopped the request, the file may well exist.
                    evidence = _page_evidence(response)
                    headers = evidence.get("page_headers") or {}
                    challenged = "challenge" in (headers.get("x-amzn-waf-action"), headers.get("cf-mitigated"))
                    entry.update(status="failed", reason="verification_page" if challenged else "html_page", **evidence)
                else:
                    name = _file_name(link.url, str(response.headers.get("content-disposition", "") or ""), taken,
                                      link.label, content_type)
                    path = target / name
                    temporary = None
                    size = 0
                    try:
                        chunks = response.chunks() if callable(getattr(response, "chunks", None)) else [response.body()]
                        with tempfile.NamedTemporaryFile(dir=target, prefix=".supplement-", suffix=".part", delete=False) as fh:
                            temporary = Path(fh.name)
                            for chunk in chunks:
                                _check_interrupted()
                                now = clock()
                                if now - started > MAX_COLLECTION_SEC:
                                    raise TimeoutError("attachment collection time budget exhausted")
                                if not chunk:
                                    continue
                                size += len(chunk)
                                if size > MAX_FILE_BYTES:
                                    break
                                fh.write(chunk)
                                last_progress = now
                                if activity is not None:
                                    activity()
                        _check_interrupted()
                        if size > MAX_FILE_BYTES:
                            entry.update(status="skipped", reason="too_large", size=size)
                        elif not size or (length and not response.headers.get("content-encoding") and size != length):
                            entry.update(status="failed", reason="incomplete_body", size=size)
                        else:
                            temporary.replace(path)
                            entry.update(status="saved", file=str(path), size=size,
                                         content_type=content_type.split(";")[0].strip())
                    finally:
                        if temporary is not None:
                            temporary.unlink(missing_ok=True)
            except SupplementTooLarge as exc:
                entry.update(status="skipped", reason="too_large", size=exc.size)
            except (BrowserUnresponsive, UserMarkedNoEntitlement) as exc:
                stopped_reason = ("batch_stopped" if isinstance(exc, UserStoppedBatch) else
                                  "user_skipped" if isinstance(exc, UserSkippedArticle) else
                                  "user_marked_no_entitlement" if isinstance(exc, UserMarkedNoEntitlement) else
                                  "browser_operation_timeout" if isinstance(exc, BrowserOperationTimeout) else
                                  "browser_unresponsive")
                entry.update(status="skipped" if isinstance(exc, UserMarkedNoEntitlement) else "failed",
                             reason=stopped_reason)
            except Exception as exc:
                # Network exception messages may carry signed URLs or credentials.
                entry.update(status="failed", reason=f"{type(exc).__name__}: attachment transfer failed")
            finally:
                if response is not None and callable(getattr(response, "dispose", None)):
                    response.dispose()
        files.append(entry)
        if entry.get("status") == "saved":
            last_progress = clock()
        manifest_target = manifest_dir or target
        manifest_target.mkdir(parents=True, exist_ok=True)
        manifest = manifest_target / "manifest.json"
        temporary_manifest = manifest.with_suffix(".json.tmp")
        temporary_manifest.write_text(json.dumps({"doi": doi, "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_manifest.replace(manifest)
        if progress is not None:
            progress(sum(1 for f in files if f.get("status") == "saved"))
    return files
