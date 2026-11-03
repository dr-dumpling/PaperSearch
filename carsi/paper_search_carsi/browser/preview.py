"""Live previews of the download browser, written by the owning thread (no debug port).

On by default for institutional downloads: every page of the download context
is screenshotted on navigation and whenever the workflow reads the page (login
and verification waits included, at most every 4 s). Frames go to
``<data dir>/previews/<run_id>/`` (or ``browser_preview_dir``) as JPEG. A page
that has not changed (same URL and title) keeps only its newest frame, earlier
page states are kept up to ``MAX_KEPT_FRAMES`` per download, a successful
download's frames are removed, and only the most recent runs are kept. ``browser_preview: false`` turns it off. Readers
(``paper-search-carsi preview``) inspect artifacts only and report the
frame age explicitly. Screenshots are unmasked and stay on this machine.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

_OBSERVERS = WeakKeyDictionary()
_ACTIVE = {}
_KINDS = {'blank', 'article', 'pdf', 'login', 'other'}
OBSERVE_INTERVAL_SEC = 4  # between unforced frames (waits refresh at most this often)
MAX_KEPT_FRAMES = 5  # earlier page states kept per download, besides each tab's newest frame
JPEG_QUALITY = 60


def _atomic(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(data)
    temporary.chmod(0o600)
    temporary.replace(path)


class BrowserPreview:
    def __init__(self, context, directory: Path, identity: dict):
        self.context = context
        self.run_id = str(UUID(identity['run_id']))
        self.identifier = identity['current'].lower()
        self.directory = Path(directory) / self.run_id
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.context_id = str(uuid4())
        _ACTIVE[str(self.directory.resolve())] = self.context_id
        self.revision = 0
        self.last_observed = 0.0
        self.page_ids = {}
        self.last_frame = {}  # page_id -> ((url, title), image name)
        self.kept = []  # frames of earlier page states, oldest first
        self.pages = []
        self.observed_at = time.time()
        self.closed = False
        self.observing = False
        self._cdp = WeakKeyDictionary()
        context.on('close', self.close)
        self._write([])
        context.on('page', self._attach_page)
        for page in list(context.pages):
            self._attach_page(page)

    def _attach_page(self, page):
        page.on('domcontentloaded', lambda *_args: self._refresh())

    def _refresh(self):
        try:
            self.observe()
        except Exception:
            logging.getLogger(__name__).warning('browser_preview_unavailable')

    def close(self, *_args):
        self.closed = True
        try:
            if self._is_current():
                self._write(self.pages)
        except OSError:
            logging.getLogger(__name__).warning('browser_preview_unavailable')
        finally:
            _OBSERVERS.pop(self.context, None)

    def _is_current(self):
        return _ACTIVE.get(str(self.directory.resolve())) == self.context_id

    def _write(self, pages):
        # screenshot() can yield to another context's navigation callback.
        # Recheck at publication, not only when the observation starts.
        if not self._is_current():
            return
        self.revision += 1
        self.pages = pages
        packet = {'schema_version': 1, 'run_id': self.run_id, 'identifier': self.identifier,
                  'context_id': self.context_id,
                  'owner_pid': os.getpid(), 'revision': self.revision,
                  'observed_at': self.observed_at, 'browser_closed': self.closed, 'pages': pages}
        _atomic(self.directory / 'current.json', json.dumps(packet).encode())

    def observe(self, *, force=False):
        if force and self.observing and not self.closed:
            # A navigation callback can still be finishing its screenshot when
            # goto() returns. Pump the owning loop for that bounded operation.
            deadline = time.monotonic() + 2
            pages = list(self.context.pages)
            while self.observing and pages and not self.closed and time.monotonic() < deadline:
                pages[0].wait_for_timeout(50)
        if self.closed or not self._is_current() or self.observing or (not force and time.monotonic() - self.last_observed < OBSERVE_INTERVAL_SEC):
            return
        self.observing = True
        try:
            self._observe()
        finally:
            self.observing = False

    def _capture(self, page) -> bytes:
        """Screenshot without Playwright's viewport emulation.

        page.screenshot() briefly overrides device metrics on a window opened
        without a fixed viewport, which makes the visible browser flicker on
        every frame. CDP Page.captureScreenshot reads the compositor surface
        as-is; non-Chromium backends fall back to page.screenshot().
        """
        import base64
        session = self._cdp.get(page)
        if session is None:
            try:
                session = page.context.new_cdp_session(page)
                self._cdp[page] = session
            except Exception:
                session = False
                self._cdp[page] = session
        if session:
            data = session.send("Page.captureScreenshot",
                                {"format": "jpeg", "quality": JPEG_QUALITY, "fromSurface": True})
            return base64.b64decode(data["data"])
        return page.screenshot(timeout=1500, full_page=False, type="jpeg", quality=JPEG_QUALITY)

    def _observe(self):
        self.last_observed = time.monotonic()
        pages = []
        superseded = []
        for page in list(self.context.pages)[:8]:
            if page.is_closed():
                continue
            page_id = self.page_ids.setdefault(page, len(self.page_ids) + 1)
            captured_url = page.url
            parsed = urlsplit(captured_url)
            host = parsed.hostname or ''
            kind = ('blank' if page.url == 'about:blank' else
                    'pdf' if '/pdf/' in parsed.path.lower() or parsed.path.lower().endswith('.pdf') else
                    'article' if re.search(r'/(?:abstract|fulltext|article|doi)/', parsed.path, re.I) else 'other')
            row = {'page_id': page_id, 'host': host, 'kind': kind, 'screenshot_status': 'unavailable'}
            captured_at = time.time()
            try:
                if page.locator('input[type="password"]:visible').count():
                    row['kind'] = 'login'
                # The user requested the actual rendered page without preview
                # masks. Field values are never extracted into JSON or logs.
                frame = self._capture(page)
                if page.url != captured_url:
                    # Navigation raced the screenshot. Publish no pixels for
                    # the old host; a later observation captures the new page.
                    pages.append(row)
                    continue
                # Immutable filenames keep a reader's metadata and pixels in
                # the same revision, even while a newer frame is published.
                image_name = f'{self.context_id}-{self.revision + 1}-page-{page_id}.jpg'
                _atomic(self.directory / image_name, frame)
                row.update(image_name=image_name, captured_at=captured_at)
                row['screenshot_status'] = 'available'
                key = (captured_url, self._page_title(page))
                previous = self.last_frame.get(page_id)
                if previous:
                    # The same page again replaces its frame; a changed page keeps the old one.
                    (superseded if previous[0] == key else self.kept).append(previous[1])
                self.last_frame[page_id] = (key, image_name)
            except Exception:
                # Preview failure is explicit and cannot change download success.
                pass
            pages.append(row)
        self.observed_at = min((row['captured_at'] for row in pages if 'captured_at' in row), default=time.time())
        self._write(pages)
        # Old frames go only after current.json names the new ones.
        while len(self.kept) > MAX_KEPT_FRAMES:
            superseded.append(self.kept.pop(0))
        for name in superseded:
            (self.directory / name).unlink(missing_ok=True)

    @staticmethod
    def _page_title(page) -> str:
        try:
            return str(page.title() or "")
        except Exception:
            return ""

    def discard_frames(self):
        """Remove this download's frames; a successful download needs no record."""
        for name in [*self.kept, *(frame for _key, frame in self.last_frame.values())]:
            (self.directory / name).unlink(missing_ok=True)
        self.kept, self.last_frame = [], {}
        self.pages = [{k: v for k, v in row.items() if k not in ('image_name', 'captured_at')}
                      | {'screenshot_status': 'unavailable'} for row in self.pages]
        if self._is_current():
            self._write(self.pages)


def enable(context, directory: str | Path) -> BrowserPreview:
    from .. import progress_reporter
    from ..progress_status import normalize_identifier
    identity = progress_reporter.read_state()
    if (identity.get('owner_pid') != os.getpid()
            or normalize_identifier(identity.get('current')) is None):
        raise ValueError('browser preview requires an owned DOI task')
    observer = BrowserPreview(context, Path(directory), identity)
    _OBSERVERS[context] = observer
    return observer


def discard_frames(context) -> None:
    """Drop the preview frames of ``context``'s download (it succeeded); never raises."""
    try:
        observer = _OBSERVERS.get(context) if context is not None else None
    except TypeError:
        return
    if observer is not None:
        try:
            observer.discard_frames()
        except Exception:
            logging.getLogger(__name__).warning('browser_preview_unavailable')


def observe_page(page, *, force=False) -> None:
    try:
        observer = _OBSERVERS.get(getattr(page, 'context', None))
    except TypeError:
        return
    if observer is not None:
        try:
            observer.observe(force=force)
        except Exception:
            logging.getLogger(__name__).warning('browser_preview_unavailable')


def snapshot(directory: str | Path, run_id: str, identifier: str) -> dict:
    """A requested run can return a clearly labelled retained or stale view."""
    from ..progress_status import normalize_identifier, snapshot as progress_snapshot
    from ..progress_reporter import read_snapshot
    run_id = str(UUID(run_id))
    identifier = normalize_identifier(identifier)
    if identifier is None:
        raise ValueError('identifier must be a DOI')
    output = {'schema_version': 1, 'run_id': run_id, 'identifier': identifier, 'status': 'unavailable'}
    progress = progress_snapshot(run_id=run_id, identifier=identifier)
    if progress['status'] == 'task_mismatch':
        return {**output, 'status': 'task_mismatch'}
    folder = Path(directory).resolve() / run_id
    try:
        path = folder / 'current.json'
        if path.stat().st_size > 65536:
            return output
        packet = json.loads(path.read_text())
        state, _ = read_snapshot()
        if (not isinstance(packet, dict) or packet.get('run_id') != run_id
                or packet.get('identifier') != identifier or packet.get('schema_version') != 1
                or type(packet.get('owner_pid')) is not int or not state
                or state.get('run_id') != run_id or state.get('owner_pid') != packet['owner_pid']
                or type(packet.get('observed_at')) not in (float, int)
                or type(packet.get('revision')) is not int
                or not isinstance(packet.get('pages'), list)):
            return output
        context_id = str(UUID(packet['context_id']))
        age = time.time() - packet['observed_at']
        if not 0 <= age < 86400:
            return output
        status = 'browser_closed' if packet.get('browser_closed') is True else 'stale'
        if status != 'browser_closed' and progress['status'] == 'running' and age <= 10:
            os.kill(packet['owner_pid'], 0)
            status = 'available'
        output.update(status=status, age_seconds=round(age, 1), observed_at=packet['observed_at'])
        pages = []
        for row in packet['pages'][:8]:
            page_id = row.get('page_id')
            if (type(page_id) is not int or not 1 <= page_id <= 1000
                    or row.get('kind') not in _KINDS or not isinstance(row.get('host'), str)
                    or not re.fullmatch(r'[a-zA-Z0-9.-]{0,253}', row['host'])):
                return {**output, 'status': 'unavailable'}
            safe = {'page_id': page_id, 'host': row['host'], 'kind': row['kind'],
                    'screenshot_status': 'unavailable',
                    'identity_marker_visible': row.get('identity_marker_visible') is True}
            image_name = row.get('image_name', '')
            valid_name = re.fullmatch(re.escape(context_id) + r'-[1-9][0-9]*-page-' + str(page_id) + r'\.(?:jpg|png)', image_name)
            captured_at = row.get('captured_at')
            image_path = folder / image_name
            if (row.get('screenshot_status') == 'available' and image_path.is_file()
                    and image_path.resolve().parent == folder and valid_name
                    and type(captured_at) in (int, float) and 0 <= time.time()-captured_at < 86400):
                safe.update(screenshot_status='available', screenshot=str(image_path),
                            captured_at=captured_at, age_seconds=round(time.time()-captured_at, 1))
            pages.append(safe)
        return {**output, 'pages': pages, 'revision': packet['revision'], 'owner_pid': packet['owner_pid'],
                'context_id': context_id}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {**output, 'status': 'unavailable'}


DEFAULT_KEEP_RUNS = 5


def default_directory(config: dict | None = None) -> Path:
    configured = (config or {}).get("browser_preview_dir")
    if configured:
        return Path(configured)
    from ..config import DATA_DIR
    return DATA_DIR / "previews"


def prune(directory: str | Path, keep: int = DEFAULT_KEEP_RUNS) -> list[str]:
    """Delete preview folders beyond the newest ``keep`` runs; never an active one."""
    import shutil
    root = Path(directory)
    if not root.is_dir():
        return []
    runs = []
    for child in root.iterdir():
        try:
            UUID(child.name)
        except ValueError:
            continue
        if child.is_dir():
            runs.append(child)
    runs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    active = set(_ACTIVE)
    removed = []
    for old in runs[max(0, keep):]:
        if str(old.resolve()) in active:
            continue
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    return removed


def ensure_enabled(context, config: dict | None = None):
    """Enable the preview for this download context unless turned off; never raises."""
    config = config or {}
    if config.get("browser_preview") is False:
        return None
    existing = _OBSERVERS.get(context) if context is not None else None
    if existing is not None:
        return existing
    directory = default_directory(config)
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            keep = int(config.get("browser_preview_keep_runs", DEFAULT_KEEP_RUNS))
        except (TypeError, ValueError):
            keep = DEFAULT_KEEP_RUNS
        prune(directory, keep=max(1, keep))
        return enable(context, directory)
    except Exception as exc:  # no owned DOI task (batch runs) or an I/O problem
        logging.getLogger(__name__).info("browser_preview_disabled: %s", type(exc).__name__)
        return None


def latest_snapshot(config: dict | None = None, run_id: str | None = None,
                    identifier: str | None = None) -> dict:
    """Snapshot for the given run, or for the current/most recent task."""
    from ..progress_reporter import read_snapshot
    if not run_id or not identifier:
        state, _reason = read_snapshot()
        state = state or {}
        run_id = run_id or state.get("run_id")
        identifier = identifier or state.get("current")
    if not run_id or not identifier:
        return {"schema_version": 1, "status": "unavailable", "reason": "no_task"}
    try:
        return snapshot(default_directory(config), run_id, identifier)
    except ValueError as exc:
        return {"schema_version": 1, "status": "unavailable", "reason": str(exc)}
