"""AWS WAF picture puzzles: capture the grid, apply service answers, and submit."""
from __future__ import annotations

import math
import time
from typing import Any

NAME = "awswaf"
KIND = "awswaf"
GRID_WAIT_SEC = 8.0
POLL_SEC = 0.5
CONFIRM_DELAY_SEC = 1.0
LEFT_WAIT_SEC = 12.0
ATTEMPTS = 3
RETRY_DELAY_SEC = 1.0
#: Its own control before and after the grid.
_BEGIN = "#amzn-captcha-verify-button"
_CONFIRM = "#amzn-btn-verify-internal"

_FIND = r"""() => {
  const shown = el => !!el && el.getClientRects().length > 0;
  const begin = document.querySelector('#amzn-captcha-verify-button');
  const button = [...document.querySelectorAll('button, [role=button]')].find(el => shown(el)
    && /begin|verify you are human|let's confirm/i.test((el.innerText || '').trim()));
  const text = (document.body?.innerText || '').trim();
  return {aws: !!document.querySelector('#amzn-captcha-container, #captcha-container, .amzn-captcha-root')
                || !!begin || !!button || /choose all|select all/i.test(text),
          ready: document.readyState !== 'loading' && text.length > 0,
          title: document.title, text: text.slice(0, 300)};
}"""

_GRID = r"""() => {
  const shown = el => !!el && el.getClientRects().length > 0;
  const box = el => { const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, width: r.width, height: r.height}; };
  // The grid is the largest square-ish visible image or canvas on the page.
  const squares = [...document.querySelectorAll('img, canvas, table')].filter(shown)
    .map(el => ({el, box: box(el)}))
    .filter(row => row.box.width >= 120 && row.box.height >= 120)
    .sort((a, b) => b.box.width * b.box.height - a.box.width * a.box.height);
  if (!squares.length) return {grid: null, question: ''};
  const question = [...document.querySelectorAll('div, p, span, h1, h2, h3, label')]
    .filter(shown).flatMap(el => (el.innerText || '').split('\n').map(line => line.trim()))
    .find(text => text && text.length < 120 && /choose all|select all|choose the|select the|pick all|选择|选出/i.test(text)) || '';
  return {grid: squares[0].box, question};
}"""



def find(page: Any) -> bool:
    """Is this page AWS WAF's picture puzzle (its own button or the question line)?"""
    try:
        state = page.evaluate(_FIND)
    except Exception:  # noqa: BLE001 - a page that cannot be read is not this page
        return False
    return bool(isinstance(state, dict) and state.get("aws"))


def solve(page: Any, config: dict[str, Any] | None, *, observation: Any = None, limits: Any = None) -> bool:
    """Try bounded image rounds; accept only a readable page without the puzzle."""
    from ..services import solver as solver_module

    note = observation or (lambda _reason: None)

    def trace(message: str) -> None:
        note(message)
        try:
            from ....config import DATA_DIR
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with (DATA_DIR / "awswaf.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
        except OSError:
            pass

    trace(f"enter configured={solver_module.configured(config)} url={str(getattr(page, 'url', ''))[:80]}")
    if not solver_module.configured(config):
        trace("solver not configured")
        return False
    if limits is None:
        from ..continuation import Limits
        budget = getattr(page, "_papersearch_grid_budget", None)
        if budget is None:
            budget = solver_module.Budget(config=config)
            page._papersearch_grid_budget = budget
        limits = Limits(time.monotonic() + 180, budget)
    budget = limits.budget
    for attempt in range(1, ATTEMPTS + 1):
        limits.remaining()
        if not budget.take():
            trace("solver budget spent")
            return False
        trace(f"attempt {attempt}")
        if _attempt(page, config, trace, limits):
            return True
        trace(f"attempt {attempt} not completed")
        limits.sleep(RETRY_DELAY_SEC)
    return False


def _attempt(page: Any, config: dict[str, Any] | None, trace: Any, limits: Any) -> bool:
    """One whole answer: Begin, the grid, the service, the clicks, Confirm, passed?"""
    from ..services import solver as solver_module

    limits.remaining()
    if not _grid(page):
        trace(f"begin pressed={_press(page, _BEGIN, trace)}")
    grid = None
    deadline = time.monotonic() + GRID_WAIT_SEC
    while time.monotonic() < deadline:
        limits.remaining()
        state = _grid(page)
        if state.get("grid"):
            grid = state
            break
        limits.sleep(POLL_SEC)
    if not grid:
        trace("no grid")
        return False
    image = _screenshot(page, grid["grid"])
    if not image:
        trace("no screenshot")
        return False
    points = solver_module.solve_grid(image, grid.get("question") or "", config, kind=KIND,
                                      timeout=min(limits.remaining(), float((config or {}).get("captcha_timeout", 90))))
    limits.remaining()
    if not points:
        trace("no points")
        return False
    trace(f"points={len(points)} grid={grid['grid']} question={(grid.get('question') or '')[:40]}")
    if not _click_points(page, grid["grid"], points, limits=limits):
        trace("click failed")
        return False
    trace("points clicked")
    # Let selection settle, then click the widget's Confirm control by its ID.
    limits.sleep(CONFIRM_DELAY_SEC)
    pressed = _press(page, _CONFIRM, trace, wait_sec=5.0)
    trace(f"confirm pressed={pressed}")
    if not pressed:
        return False
    # Pressing is not passing: the page says it left the puzzle, or the answer was
    # not taken (the next attempt, or the user's wait as before).
    deadline = time.monotonic() + LEFT_WAIT_SEC
    while time.monotonic() < deadline:
        limits.remaining()
        try:
            state = page.evaluate(_FIND)
        except Exception:  # noqa: BLE001 - navigation or a closed page is not acceptance
            state = None
        if isinstance(state, dict) and state.get("ready") and state.get("aws") is False:
            trace("page passed")
            return True
        limits.sleep(POLL_SEC)
    trace("still on the puzzle")
    return False


def _press(page: Any, selector: str, note: Any, *, wait_sec: float = 0.0) -> bool:
    """One press on the page's own control, when it is there and actionable.

    ``wait_sec``: the control may still be disabled while the tiles are being
    clicked (AWS WAF's "Confirm" enables once a tile is chosen), so it is looked
    for again a few times before the press is given up.
    """
    deadline = time.monotonic() + max(0.0, wait_sec)
    while True:
        try:
            control = page.locator(selector).first
            if control.count() and control.is_visible():
                if control.is_enabled():
                    control.click(timeout=3000, no_wait_after=True)
                    return True
        except Exception as exc:  # noqa: BLE001 - a control that cannot be pressed is the user's
            note(f"press {selector}: {type(exc).__name__}")
            return False
        if time.monotonic() >= deadline:
            note(f"press {selector}: not actionable")
            return False
        time.sleep(0.3)


def _grid(page: Any) -> dict:
    """The grid's box and its question line, or {} while it is not up yet."""
    try:
        state = page.evaluate(_GRID)
    except Exception:  # noqa: BLE001 - a page that cannot be read has no grid
        return {}
    return state if isinstance(state, dict) and state.get("grid") else {}


def _screenshot(page: Any, box: dict) -> bytes:
    """The whole grid as one picture: the service is given one image, not nine."""
    try:
        clip = {key: float(box[key]) for key in ("x", "y", "width", "height")}
        # Answers are in image pixels; use one pixel per CSS pixel on Retina too.
        return page.screenshot(clip=clip, scale="css") or b""
    except Exception:  # noqa: BLE001 - a picture that cannot be taken answers nothing
        return b""


def _click_points(page: Any, box: dict, points: list, *, limits: Any = None) -> bool:
    """Click the answer: the tiles' own buttons, or the picture's pixels.

    The service answers with points of the picture; the page's nine
    ``button.amzn-grid-cell`` tiles take a press, so a point names its tile
    (a third of the picture each way) and that tile's button is pressed.
    """
    if not points:
        return False
    tiles = all(isinstance(value, (int, float)) and value in (0, 1, 2)
                for point in points for value in point)
    cells = []
    try:
        cells = page.locator("button.amzn-grid-cell").all()
    except Exception:  # noqa: BLE001 - no cell buttons: the picture is clicked instead
        cells = []
    targets = []
    for x, y in points:
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
            return False
        if not tiles and not (0 <= x < box["width"] and 0 <= y < box["height"]):
            return False
        index = None
        if tiles:
            index = int(y) * 3 + int(x)
        elif len(cells) == 9:
            index = int(y / (box["height"] / 3)) * 3 + int(x / (box["width"] / 3))
        target = index if index is not None else (x, y)
        if target not in targets:
            targets.append(target)
    # A rejected answer can leave tiles selected on the same question. Apply
    # the whole new selection, including clearing obsolete choices.
    if len(cells) == 9 and all(isinstance(target, int) for target in targets):
        for index, cell in enumerate(cells):
            if limits is not None:
                limits.remaining()
            try:
                if index not in targets and cell.get_attribute("aria-checked") == "true":
                    cell.click(timeout=2000, no_wait_after=True)
                    if cell.get_attribute("aria-checked") != "false":
                        return False
            except Exception:  # noqa: BLE001 - do not submit a partially updated answer
                return False
    for target in targets:
        if limits is not None:
            limits.remaining()
        try:
            if isinstance(target, int):
                if len(cells) != 9:
                    return False
                cell = cells[target]
                if cell.get_attribute("aria-checked") != "true":
                    cell.click(timeout=2000, no_wait_after=True)
                if cell.get_attribute("aria-checked") != "true":
                    return False
            else:
                page.mouse.click(box["x"] + target[0], box["y"] + target[1])
            time.sleep(0.2)
        except Exception:  # noqa: BLE001 - an incomplete answer must not be submitted
            return False
    return True
