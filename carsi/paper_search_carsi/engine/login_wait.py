"""A login deadline that stops while the user owns the authentication step.

Only events inside the dedicated login document are counted. No field values,
key contents, system input hooks or foreground-window observations are used.
"""
from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from ..browser import watchdog
from .batch_common import _is_browser_error


_READ_ACTIVITY = """token => {
    const key = Symbol.for('paper-search:login-activity');
    let state = window[key];
    if (!state || state.token !== token) {
        if (state) state.dispose();
        state = {token, count: 0};
        // Some automation marks script events trusted. Require native input
        // metadata as well; submit/change alone cannot establish takeover.
        const events = ['input', 'keydown', 'pointerdown'];
        const record = event => {
            if (!event.isTrusted || !(event.target instanceof Element)) return;
            if (!event.composed) return;
            const input = event.type === 'input' && event instanceof InputEvent && !!event.inputType;
            const keyboard = event.type === 'keydown' && event instanceof KeyboardEvent
                && !!event.code && event.keyCode > 0;
            const pointer = event.type === 'pointerdown' && event instanceof PointerEvent
                && ['mouse', 'touch', 'pen'].includes(event.pointerType);
            if (!input && !keyboard && !pointer) return;
            const control = event.target.closest(
                'input:not([type=hidden]),textarea,select,button,label,a[href],[role=button],[contenteditable=true],form');
            if (control) state.count++;
        };
        state.dispose = () => {
            events.forEach(name => document.removeEventListener(name, record, true));
            delete window[key];
        };
        events.forEach(name => document.addEventListener(name, record, true));
        window[key] = state;
    }
    return state.count;
}"""
_REMOVE_ACTIVITY = """token => {
    const state = window[Symbol.for('paper-search:login-activity')];
    if (state && state.token === token) state.dispose();
}"""


class LoginWait:
    def __init__(self, deadline: float, clock: Callable[[], float], *, attribute: str = ""):
        self._deadline = deadline
        self._clock = clock
        self._paused_at: float | None = None
        self._token = uuid4().hex
        self._frames: dict[Any, int] = {}
        self.user_step = False
        self.attribute = attribute

    def _account(self) -> None:
        if self._paused_at is not None:
            now = self._clock()
            self._deadline += max(0, now - self._paused_at)
            self._paused_at = now

    @property
    def deadline(self) -> float:
        self._account()
        return self._deadline

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def take_over(self) -> None:
        """An explicit capsule request counts only during a human login step."""
        if self.user_step and not self.paused:
            self._paused_at = self._clock()

    def exclude_elapsed(self, seconds: float) -> None:
        """A nested manual verification already accounted for this time."""
        self._deadline += max(0, seconds)

    def observe(self, page: Any, user_step: bool) -> None:
        self._account()
        self.user_step = user_step
        if not user_step:
            self._paused_at = None
            self._remove_listeners()
            return
        for frame in page.frames:
            try:
                count = frame.evaluate(_READ_ACTIVITY, self._token)
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise
                continue  # navigation replaced this document; retry on the next pass
            if type(count) is not int:
                continue
            previous = self._frames.get(frame, 0)
            self._frames[frame] = count
            if count > 0 and count != previous:
                self.take_over()

    def _remove_listeners(self) -> None:
        frames, self._frames = self._frames, {}
        # An interrupted browser cannot accept further calls. The document's
        # small counter dies on navigation, or is replaced by the next token.
        if watchdog.fired is not None or watchdog.interrupted is not None:
            return
        for frame in frames:
            try:
                frame.evaluate(_REMOVE_ACTIVITY, self._token)
            except Exception as exc:
                if not _is_browser_error(exc):
                    raise

    def close(self) -> float:
        self._account()
        self._paused_at = None
        self.user_step = False
        self._remove_listeners()
        return self._deadline
