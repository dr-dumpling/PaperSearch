"""A human-shaped pointer approach before one bounded verification press.

Cloudflare's Turnstile scores the pointer history that leads to a press on its
checkbox: a press that arrives with no preceding movement is the shape an
automated click has, which is why the interactive check can start again on the
same box that was already clicked. This module moves the browser's own pointer
along a slightly curved path into the widget and lets it rest there.

The press itself stays with the element's actionability-checked click in
``challenge_interaction``: nothing here reads or writes page state, navigates,
clicks, or decides whether verification passed. The pointer is the driver's own
(CDP ``Input.dispatchMouseEvent`` through Playwright's ``page.mouse``), so every
move is a trusted event, as a person's is.

A page without a pointer, a box without usable geometry, or a move that fails
because the widget went away all end the approach with ``False`` and no harm:
the caller then presses as it did before this module existed.
"""
from __future__ import annotations

import math
import os
import random
import time
import weakref
from typing import Any

#: Longest approach, before the caller's own action budget is considered.
APPROACH_LIMIT_SEC = 0.5
#: The shortest approach still worth doing: a press with a visible path in.
MIN_LIMIT_SEC = 0.12
#: ``PAPER_SEARCH_POINTER_PATH=fast``: a shorter path for a tight retry budget.
FAST_LIMIT_SEC = 0.25
#: Path segments: enough to look moved, few enough for a short action budget.
_STEPS = (8, 14)
#: How far in front of the widget the pointer starts.
_START_DISTANCE = (220, 520)
_STEP_SLEEP = (0.005, 0.012)
_REST_SLEEP = (0.04, 0.10)
#: Where each page's pointer was left, so a repeated press starts from there
#: instead of teleporting to a new random corner: two presses on the same box
#: then look like one hand, not two.
_LAST: "weakref.WeakKeyDictionary[Any, tuple[float, float]]" = weakref.WeakKeyDictionary()
#: Pages that cannot be weakly referenced (test doubles, driver proxies): their
#: last point by identity, bounded so a long run cannot grow it without limit.
_LAST_BY_ID: dict[int, tuple[float, float]] = {}


def _last_point(page: Any) -> tuple[float, float] | None:
    try:
        return _LAST.get(page)
    except TypeError:
        return _LAST_BY_ID.get(id(page))


def _remember_point(page: Any, point: tuple[float, float]) -> None:
    try:
        _LAST[page] = point
    except TypeError:
        if len(_LAST_BY_ID) > 256:
            _LAST_BY_ID.clear()
        _LAST_BY_ID[id(page)] = point


def _bezier(start: tuple[float, float], c1: tuple[float, float],
            c2: tuple[float, float], end: tuple[float, float],
            t: float) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u ** 3 * start[0] + 3 * u ** 2 * t * c1[0] + 3 * u * t ** 2 * c2[0] + t ** 3 * end[0],
        u ** 3 * start[1] + 3 * u ** 2 * t * c1[1] + 3 * u * t ** 2 * c2[1] + t ** 3 * end[1],
    )


def press(page: Any, rect: dict[str, Any], *, point: dict[str, float] | None = None,
          hold_sec: tuple[float, float] = (0.05, 0.12),
          rng: random.Random | None = None) -> bool:
    """Press the point and hold it for as long as a hand does.

    Playwright's own click presses and releases in the same instant; a person
    holds the button for tens of milliseconds. Before pressing, the outer
    document is asked what sits under the point: anything that is not the
    widget's own frame means an overlay would take the press, and the caller
    keeps its checked click instead.

    Nothing here navigates or reads a verification result.
    """
    mouse = getattr(page, "mouse", None)
    if not all(callable(getattr(mouse, name, None)) for name in ("move", "down", "up")):
        return False
    try:
        left, top = float(rect["x"]), float(rect["y"])
        width, height = float(rect.get("width") or 0.0), float(rect.get("height") or 0.0)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (left, top, width, height)) or width <= 0 or height <= 0:
        return False
    landed = point if isinstance(point, dict) else {"x": width / 2, "y": height / 2}
    try:
        target = (left + float(landed["x"]), top + float(landed["y"]))
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in target):
        return False

    from ...driver import Error

    try:
        hit = page.evaluate("""([x, y]) => {
            const el = document.elementFromPoint(x, y);
            return el ? el.tagName : '';
        }""", [target[0], target[1]])
    except Error:
        return False
    if str(hit or "").upper() != "IFRAME":
        return False

    random_source = rng if rng is not None else random.Random()
    try:
        mouse.move(target[0], target[1], steps=1)
        mouse.down()
        time.sleep(max(0.0, random_source.uniform(*hold_sec)))
        mouse.up()
    except Error:
        return False
    return True


def budget_for(timeout_ms: int) -> float:
    """The approach's share of one click's action budget.

    Two fifths of the caller's budget leaves the hover, the stability check and
    the press itself their room, which matters for the short retry budgets the
    engine hands the third attempt.

    ``PAPER_SEARCH_POINTER_PATH`` picks the cost: ``off`` presses as before this
    module existed, ``fast`` caps the path at ``FAST_LIMIT_SEC``, and the default
    takes the fuller path.
    """
    mode = os.environ.get("PAPER_SEARCH_POINTER_PATH", "").strip().lower()
    if mode in {"off", "0", "false", "no"}:
        return 0.0
    cap = FAST_LIMIT_SEC if mode in {"fast", "1", "on"} else APPROACH_LIMIT_SEC
    return max(MIN_LIMIT_SEC, min(cap, max(0, timeout_ms) / 1000 * 0.4))


def approach(page: Any, rect: dict[str, Any], *, point: dict[str, float] | None = None,
             limit_sec: float = APPROACH_LIMIT_SEC,
             rng: random.Random | None = None) -> bool:
    """Move the pointer into ``rect`` (a viewport box) and leave it on ``point``.

    ``point`` is the box-relative press point (``{"x": 28, "y": 32.5}``); it
    defaults to the box's centre. Returns whether the pointer was moved at all.
    """
    mouse = getattr(page, "mouse", None)
    move = getattr(mouse, "move", None)
    if not callable(move) or limit_sec <= 0:
        return False
    try:
        left, top = float(rect["x"]), float(rect["y"])
        width, height = float(rect.get("width") or 0.0), float(rect.get("height") or 0.0)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (left, top, width, height)):
        return False
    if width <= 0 or height <= 0:
        return False
    landed = point if isinstance(point, dict) else {"x": width / 2, "y": height / 2}
    try:
        target = (left + float(landed["x"]), top + float(landed["y"]))
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in target):
        return False

    random_source = rng if rng is not None else random.Random()
    until = time.monotonic() + max(0.0, limit_sec)
    try:
        previous = _last_point(page)
    except TypeError:  # a page object that keeps no identity
        previous = None
    if previous is not None and math.dist(previous, target) <= _START_DISTANCE[1] * 2:
        # The hand is still where the last press left it: move from there, so
        # two presses on the same box read as one hand and not two.
        start = (previous[0] + random_source.uniform(-2.0, 2.0),
                 previous[1] + random_source.uniform(-2.0, 2.0))
        steps = max(4, min(_STEPS[1], int(math.dist(start, target) / 10) + 4))
        bend_share = 0.08
    else:
        angle = random_source.uniform(0.0, math.tau)
        distance = random_source.uniform(*_START_DISTANCE)
        start = (target[0] + math.cos(angle) * distance, target[1] + math.sin(angle) * distance)
        steps = random_source.randint(*_STEPS)
        bend_share = 0.26
    # The hand does not travel straight: control points sit off the line by a
    # share of the distance, then close in on the box.
    dx, dy = target[0] - start[0], target[1] - start[1]
    span = math.hypot(dx, dy) or 1.0
    normal = (-dy / span, dx / span)
    bend = random_source.uniform(-bend_share, bend_share) * span
    c1 = (start[0] + dx * random_source.uniform(0.25, 0.45) + normal[0] * bend,
          start[1] + dy * random_source.uniform(0.25, 0.45) + normal[1] * bend)
    c2 = (start[0] + dx * random_source.uniform(0.60, 0.80) + normal[0] * bend * 0.4,
          start[1] + dy * random_source.uniform(0.60, 0.80) + normal[1] * bend * 0.4)

    from ...driver import Error  # late: the module imports the driver's error classes

    try:
        move(start[0], start[1], steps=1)
        for index in range(1, steps + 1):
            now = time.monotonic()
            if now >= until:
                break
            x, y = _bezier(start, c1, c2, target, index / steps)
            move(x + random_source.uniform(-1.0, 1.0), y + random_source.uniform(-1.0, 1.0), steps=1)
            time.sleep(min(random_source.uniform(*_STEP_SLEEP), max(0.0, until - time.monotonic())))
        # A path cut short still ends on the box, and the final move lands on the
        # press point itself rather than near it: the press follows this.
        move(target[0], target[1], steps=1)
        time.sleep(min(random_source.uniform(*_REST_SLEEP), max(0.0, until - time.monotonic())))
    except Error:
        # The widget or its page went away mid-approach; the press decides.
        return False
    try:
        _remember_point(page, target)
    except TypeError:
        pass
    return True
