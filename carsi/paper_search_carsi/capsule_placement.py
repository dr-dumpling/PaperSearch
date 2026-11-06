"""Screen-independent capsule geometry; all coordinates use top-left logical pixels."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path


EDGE, TOP_GAP, BOTTOM_GAP = 20, 44, 56
SNAP_DISTANCE = 24


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains_center(self, other: Rect) -> bool:
        return self.contains(other.x + other.width / 2, other.y + other.height / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom


@dataclass(frozen=True)
class ScreenArea:
    name: str
    bounds: Rect
    work: Rect


def screen_for(rect: Rect, screens: list[ScreenArea]) -> ScreenArea:
    """Prefer the centre's screen, otherwise the nearest screen (unplugged display)."""
    for screen in screens:
        if screen.bounds.contains_center(rect):
            return screen
    x, y = rect.x + rect.width / 2, rect.y + rect.height / 2
    return min(screens, key=lambda s: max(s.bounds.x - x, 0, x - s.bounds.right) ** 2
               + max(s.bounds.y - y, 0, y - s.bounds.bottom) ** 2)


def fit_rect(rect: Rect, work: Rect) -> Rect:
    """Keep a rectangle in the work area; oversized content starts at its top/left."""
    return Rect(max(work.x, min(rect.x, work.right - rect.width)),
                max(work.y, min(rect.y, work.bottom - rect.height)), rect.width, rect.height)


def direction_for(rect: Rect, work: Rect) -> tuple[str, str]:
    return ("down" if rect.y + rect.height / 2 < work.y + work.height / 2 else "up",
            "right" if rect.x + rect.width / 2 < work.x + work.width / 2 else "left")


def _edge(start: float, end: float, low: float, high: float) -> int:
    """Return -1/1 for the nearby edge, or 0 for free placement on this axis."""
    left, right = start - low, high - end
    if min(left, right) > SNAP_DISTANCE:
        return 0
    return -1 if left <= right else 1


class Placement:
    """Persist only the collapsed home. Temporary expansion/clamping never moves it."""
    def __init__(self, path: Path, corner: str) -> None:
        self.path, self.corner = path, corner
        self.home: Rect | None = None
        self._dragged_card: Rect | None = None
        self.screen: ScreenArea | None = None
        self.direction = ("down" if corner == "top" else "up", "left")
        self.edges = (0, 0)
        self.expanded = False
        self.scale = 1.0
        self._saved: dict = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._saved = data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Cannot read capsule placement: %s", type(exc).__name__)

    def start(self, screens: list[ScreenArea], size: tuple[int, int], scale: float = 1.0) -> tuple[int, int]:
        w, h = size
        self.scale = scale
        saved = self._saved
        restored = None
        saved_screen = None
        self.edges = (0, 0)
        try:
            if saved.get("version") == 2:
                values = [float(saved[k]) for k in ("x", "y", "width", "height")]
                if all(math.isfinite(n) for n in values) and values[2] > 0 and values[3] > 0:
                    old_scale = float(saved.get("scale", 1))
                    if not math.isfinite(old_scale) or old_scale <= 0:
                        raise ValueError("Invalid saved DPI")
                    ratio = old_scale / scale
                    restored = Rect(values[0] * ratio, values[1] * ratio, values[2], values[3])
                    screen = next((s for s in screens if s.name == saved.get("screen")), None)
                    edges = saved.get("edges")
                    if screen and isinstance(edges, list) and len(edges) == 2 and all(
                            type(edge) is int and edge in (-1, 0, 1) for edge in edges):
                        self.edges = (edges[0], edges[1])
                        if any(self.edges):
                            saved_screen = screen
                    if screen and isinstance(saved.get("work"), list) and len(saved["work"]) == 2:
                        old_x, old_y = map(float, saved["work"])
                        if math.isfinite(old_x) and math.isfinite(old_y):
                            restored = Rect(restored.x + screen.work.x - old_x * ratio,
                                            restored.y + screen.work.y - old_y * ratio,
                                            restored.width, restored.height)
            elif saved.get("corner") in ("top", "bottom"):
                right, edge = float(saved["right"]), float(saved["edge"])
                if math.isfinite(right) and math.isfinite(edge):
                    restored = Rect(right - w, edge if saved["corner"] == "top" else edge - h, w, h)
        except (KeyError, TypeError, ValueError, OverflowError):
            restored = None
        if restored is not None and (saved_screen or any(s.bounds.contains_center(restored) for s in screens)):
            self.screen = saved_screen or screen_for(restored, screens)
            restored = Rect(restored.x, restored.y, min(restored.width, self.screen.work.width),
                            min(restored.height, self.screen.work.height))
            self.home = self._fit(restored)
        else:
            self.edges = (0, 0)
            self.screen = screens[0]
            b = self.screen.bounds
            self.home = fit_rect(Rect(b.right - EDGE - w,
                                      b.y + TOP_GAP if self.corner == "top" else b.bottom - BOTTOM_GAP - h,
                                      w, h), self.screen.work)
        self.direction = self._direction(self.home)
        return round(self.home.x), round(self.home.y)

    def rescale(self, scale: float) -> None:
        """Rebase global coordinates when a Windows drag crosses different DPIs."""
        ratio = self.scale / scale
        if ratio != 1:
            if self.home is not None:
                self.home = self._rescaled(self.home, ratio)
            if self._dragged_card is not None:
                self._dragged_card = self._rescaled(self._dragged_card, ratio)
        self.scale = scale

    @staticmethod
    def _rescaled(rect: Rect, ratio: float) -> Rect:
        return Rect(rect.x * ratio, rect.y * ratio, rect.width, rect.height)

    def begin(self, expanded: bool, actual: Rect, screens: list[ScreenArea]) -> None:
        if self.home is None:
            self.home = actual
        if not self.expanded:
            # The first measured pill can differ from START_SIZE.
            self.home = actual
        self.screen = screen_for(self.home, screens)
        if not self.expanded:
            self.direction = self._direction(self.home)
        if expanded:
            self.expanded = True

    def target(self, width: int, height: int, expanded: bool) -> Rect:
        assert self.home is not None and self.screen is not None
        home, work = self.home, self.screen.work
        width, height = min(width, int(work.width)), min(height, int(work.height))
        if expanded or not self.expanded:
            anchor = (self._dragged_card if expanded else None) or home
            vertical, horizontal = self.direction
            x = anchor.right - width if horizontal == "left" else anchor.x
            y = anchor.bottom - height if vertical == "up" else anchor.y
        else:
            # A different status can change the pill's width while it is open.
            x, y = home.x, home.y
        return self._fit(Rect(x, y, width, height))

    def finish(self, expanded: bool, actual: Rect) -> None:
        if not expanded:
            self.home = actual
            self._dragged_card = None
            self.expanded = False
            self.save()

    def _fit(self, rect: Rect) -> Rect:
        work = self.screen.work
        horizontal, vertical = self.edges
        x = work.x if horizontal < 0 else work.right - rect.width if horizontal > 0 else rect.x
        y = work.y if vertical < 0 else work.bottom - rect.height if vertical > 0 else rect.y
        return fit_rect(Rect(x, y, rect.width, rect.height), work)

    def _direction(self, rect: Rect) -> tuple[str, str]:
        vertical, horizontal = direction_for(rect, self.screen.work)
        x, y = self.edges
        return ("down" if y < 0 else "up" if y > 0 else vertical,
                "right" if x < 0 else "left" if x > 0 else horizontal)

    def _drop_edges(self, rect: Rect, work: Rect, pointer: tuple[float, float] | None) -> tuple[int, int]:
        x = _edge(rect.x, rect.right, work.x, work.right)
        y = _edge(rect.y, rect.bottom, work.y, work.bottom)
        if pointer is None:
            return x, y
        px, py = pointer
        mouse_x = _edge(px, px, work.x, work.right)
        mouse_y = _edge(py, py, work.y, work.bottom)
        if not self.expanded:
            return mouse_x or x, mouse_y or y
        # A large card can touch a second edge by size alone. Only a release
        # near the corner docks both axes; otherwise keep the closer edge.
        if mouse_x or mouse_y:
            return mouse_x, mouse_y
        if x and y:
            dx = abs(rect.x - work.x if x < 0 else work.right - rect.right)
            dy = abs(rect.y - work.y if y < 0 else work.bottom - rect.bottom)
            if dx != dy:
                return (x, 0) if dx < dy else (0, y)
            px_gap = abs(px - (work.x if x < 0 else work.right))
            py_gap = abs(py - (work.y if y < 0 else work.bottom))
            return (x, 0) if px_gap <= py_gap else (0, y)
        return x, y

    def dragged(self, after: Rect, screens: list[ScreenArea],
                pointer: tuple[float, float] | None = None) -> Rect:
        # At a display seam the card's centre may still be on the previous
        # display. Prefer the display where the user actually released it.
        self.screen = next((s for s in screens if pointer and s.bounds.contains(*pointer)), None)
        if self.screen is None:
            self.screen = screen_for(after, screens)
        work = self.screen.work
        point = pointer if pointer and self.screen.bounds.contains(*pointer) else None
        self.edges = self._drop_edges(after, work, point)
        after = self._fit(Rect(after.x, after.y, min(after.width, work.width), min(after.height, work.height)))
        self.direction = self._direction(after)
        if self.home is None or not self.expanded:
            self.home = after
        else:
            self._dragged_card = after
            vertical, horizontal = self.direction
            w, h = self.home.width, self.home.height
            if point is not None and any(self.edges):
                # The card's chosen growth corner must not quantize where the
                # much smaller pill lands along the side.
                self.home = Rect(point[0] - w / 2, point[1] - h / 2, w, h)
            else:
                self.home = Rect(after.right - w if horizontal == "left" else after.x,
                                 after.bottom - h if vertical == "up" else after.y, w, h)
        self.home = self._fit(self.home)
        self.save()
        return after

    def save(self) -> None:
        if self.home is None or self.screen is None:
            return
        try:
            self.path.write_text(json.dumps({"version": 2, "x": self.home.x, "y": self.home.y,
                "width": self.home.width, "height": self.home.height, "screen": self.screen.name,
                "work": [self.screen.work.x, self.screen.work.y], "scale": self.scale,
                "edges": self.edges}), encoding="utf-8")
        except OSError as exc:
            logging.getLogger(__name__).warning("Cannot save capsule placement: %s", type(exc).__name__)
