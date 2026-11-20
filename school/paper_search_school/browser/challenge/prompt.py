"""One bounded press on another provider's own confirmation control.

Turnstile's checkbox has its own module (``challenge_interaction``). The same
kind of control on the other providers' interstitials — reCAPTCHA v2's "I'm not
a robot", hCaptcha's checkbox, AWS WAF's "Verify you are human" button — is a
press the program can make as well: it starts the provider's own check and
answers no puzzle. A puzzle that follows is the user's, and
``needs_manual_verification`` hands the page over as before.

Off unless ``PAPER_SEARCH_AUTO_CONFIRM`` is ``0`` (user, 2026-11-18: the
control is pressed as well; only the puzzle behind it stays the user's). On a
page the user is watching, a press can still turn a short wait into an image
challenge, so the switch exists to turn it off per run. Turnstile is unaffected:
the program clicks its box either way.

Nothing here solves a puzzle, reads a response token, navigates, or decides
that verification passed.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Literal
from urllib.parse import urlsplit

from . import pointer

#: Provider frames and the one control each shows before any puzzle.
_FRAMES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("reCAPTCHA", re.compile(r"^https://(?:www\.)?(?:google\.com|recaptcha\.net)/recaptcha/"
                             r"(?:api2|enterprise)/anchor"), "#recaptcha-anchor, .recaptcha-checkbox"),
    ("hCaptcha", re.compile(r"^https://(?:[a-z0-9-]+\.)*hcaptcha\.com/captcha/"), "#checkbox"),
)
#: AWS WAF's own button: the only control on its interstitial, and its puzzle
#: follows a press on it.
_AWS_WAF = re.compile(r"^https://[^/]*\.captcha\.awswaf\.com/")
_AWS_BUTTONS = ("button:has-text('Verify you are human')",
                "button:has-text('Verify you are a human')",
                "button:has-text('verify you are human')")
#: The longest one press may take, including its approach.
PRESS_LIMIT_SEC = 3.0


def enabled() -> bool:
    """Whether pressing another provider's own confirmation control is allowed.

    On unless ``PAPER_SEARCH_AUTO_CONFIRM`` is 0 (user, 2026-11-18: these
    controls are pressed as well). Only the confirmation control is pressed —
    the puzzle behind it stays the user's, and ``needs_manual_verification``
    hands that over as before.
    """
    value = os.environ.get("PAPER_SEARCH_AUTO_CONFIRM", "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _unchecked(control: Any) -> bool:
    """Not already pressed: ``aria-checked`` false, or no such attribute."""
    try:
        state = (control.get_attribute("aria-checked") or "").strip().lower()
    except Exception:  # noqa: BLE001 - a read that fails leaves the control alone
        state = "true"
    return state in {"false", ""}


def _press(page: Any, control: Any, *, box: dict[str, Any] | None,
           remaining_ms: int) -> bool:
    """Approach the control, then let its own actionable click press it."""
    if box:
        pointer.approach(page, box, limit_sec=pointer.budget_for(remaining_ms))
    control.click(timeout=remaining_ms, no_wait_after=True)
    return True


def click_confirm_control(page: Any, *, timeout_ms: int, checkpoint: Any = None,
                          observation: Any = None) -> Literal["absent", "clicked", "unavailable"]:
    """One press on the first visible confirmation control of a known provider."""
    from ..driver import Error, TimeoutError

    def note(reason: str) -> None:
        if observation is not None:
            observation(reason)

    until = time.monotonic() + max(0.0, timeout_ms) / 1000
    unavailable = False
    frames = getattr(page, "frames", ())
    frames = frames if isinstance(frames, (list, tuple)) else ()
    for frame in frames:
        if checkpoint is not None:
            checkpoint()
        if time.monotonic() >= until:
            return "unavailable" if unavailable else "absent"
        url = str(getattr(frame, "url", "") or "")
        for name, pattern, selector in _FRAMES:
            if not pattern.search(url):
                continue
            try:
                controls = frame.locator(selector)
                count = controls.count()
                if not count:
                    continue
                control = controls.first
                if not control.is_visible() or not control.is_enabled() or not _unchecked(control):
                    note(f"{name}: not actionable")
                    unavailable = True
                    continue
                remaining_ms = int((until - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    return "unavailable"
                _press(page, control, box=control.bounding_box(), remaining_ms=remaining_ms)
                note(f"{name}: control pressed")
                return "clicked"
            except TimeoutError:
                note(f"{name}: actionability timeout")
                unavailable = True
            except Error as exc:
                if any(text in str(exc).lower() for text in (
                        "frame was detached", "frame has been detached", "element is not attached",
                        "execution context was destroyed")):
                    unavailable = True
                    continue
                raise

    # AWS WAF puts its button on the outer page, not in a provider frame.
    try:
        on_aws = any(_AWS_WAF.match(str(script.get_attribute("src") or ""))
                     for script in page.locator("script[src]").all())
    except (Error, AttributeError, TypeError):
        on_aws = False
    if not on_aws:
        return "unavailable" if unavailable else "absent"
    for selector in _AWS_BUTTONS:
        if time.monotonic() >= until:
            return "unavailable"
        try:
            buttons = page.locator(selector)
            if not buttons.count():
                continue
            button = buttons.first
            if not button.is_visible() or not button.is_enabled():
                continue
            remaining_ms = int((until - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return "unavailable"
            _press(page, button, box=button.bounding_box(), remaining_ms=remaining_ms)
            note("AWS WAF: control pressed")
            return "clicked"
        except TimeoutError:
            unavailable = True
        except Error as exc:
            if not any(text in str(exc).lower() for text in ("element is not attached",)):
                raise
            unavailable = True
    return "unavailable" if unavailable else "absent"
