"""Publisher checkbox and outer-form controls shared by verification handlers.

Only native controls are clicked; no response tokens are read or replayed.
A checked provider widget permits submitting its enclosing verification form.
The engine alone decides whether the publisher has actually allowed access.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Literal

from . import pointer

#: Provider frames and the one control each shows before any puzzle.
_FRAMES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("reCAPTCHA", re.compile(r"^https://(?:www\.)?(?:google\.com|recaptcha\.net)/recaptcha/"
                             r"(?:api2|enterprise)/anchor"), "#recaptcha-anchor, .recaptcha-checkbox"),
    ("hCaptcha", re.compile(r"^https://(?:[a-z0-9-]+\.)*hcaptcha\.com/captcha/"), "#checkbox"),
    # Friendly Captcha's box is in its own widget frame: one press starts its
    # proof-of-work, and the page goes on by itself once that is done.
    ("Friendly Captcha", re.compile(r"^https://(?:[a-z0-9-]+\.)*frcapi\.com/api/v2/captcha/widget"),
     "[role=checkbox], .frc-checkbox"),
)
#: The longest one press may take, including its approach.
PRESS_LIMIT_SEC = 3.0
#: How long to keep looking for the control after a page turns out to be a
#: verification. Some providers arm their widget a few seconds after the article
#: page opens, so a single early look can find no button and hand the page out.
AWAIT_LIMIT_SEC = 12.0
#: How often to look again while its widget is shown but no control is there.
AWAIT_STEP_SEC = 1.0


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
    from ...driver import Error, TimeoutError

    def note(reason: str) -> None:
        if observation is not None:
            observation(reason)

    until = time.monotonic() + max(0.0, timeout_ms) / 1000
    unavailable = False
    # Friendly Captcha's box sits in a frame of its own widget, which the frame
    # list below does not carry: it is reached through the widget element.
    widget_frame = getattr(page, "frame_locator", None)
    try:
        widget = widget_frame(".frc-captcha iframe") if widget_frame is not None else None
        control = widget.locator("[role=checkbox], .frc-checkbox").first if widget is not None else None
        if (control is not None and control.count() and control.is_visible()
                and control.is_enabled() and _unchecked(control)):
            remaining_ms = int((until - time.monotonic()) * 1000)
            if remaining_ms > 500:
                _press(page, control, box=control.bounding_box(), remaining_ms=remaining_ms)
                note("Friendly Captcha: control pressed")
                return "clicked"
    except TimeoutError:
        unavailable = True
    except Error as exc:
        if not any(text in str(exc).lower() for text in (
                "frame was detached", "element is not attached", "execution context was destroyed")):
            raise
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

    return "unavailable" if unavailable else "absent"


#: The interstitial's own forward control, pressed once the provider's box is checked.
#: JAMA's crawl-prevention page needs "Take me to my Content" within one minute of the
#: box being checked; without it the token expires while the wait goes on.
_FORWARD_TEXTS: tuple[str, ...] = ("Take me to my Content", "Continue", "Proceed", "Submit", "Verify", "Confirm", "I agree")
FORWARD_LIMIT_SEC = 3.0
#: Measured on JAMA 2026-11-23: the box read checked 22s after the press.
CHECKED_LIMIT_SEC = 30.0
#: The page opens already "expired" more often than not; its own refresh brings the box back.
REFRESH_LIMIT = 2


def confirm_checked(page: Any) -> bool:
    """Whether a known provider's confirmation control reads checked.

    Reads ``aria-checked`` only: the response token is never read, stored or replayed.
    """
    frames = getattr(page, "frames", ())
    if not isinstance(frames, (list, tuple)):
        return False
    for _name, pattern, selector in _FRAMES:
        for frame in frames:
            try:
                if not pattern.search(str(getattr(frame, "url", "") or "")):
                    continue
                locator = frame.locator(selector)
                if locator.count() != 1:
                    continue
                state = (locator.first.get_attribute("aria-checked", timeout=500) or "").strip().lower()
                if state == "true":
                    return True
            except Exception:  # noqa: BLE001 - a frame that cannot be read is not checked
                continue
    return False


def _checked_form_submit(page: Any) -> tuple[bool, Any]:
    """Find one native submit associated with a checked widget, independent of text.

    A form with visible editable fields or multiple submit controls is ambiguous.
    Do not fall back to page-wide labels when such a form exists.
    """
    frames = getattr(page, "frames", ())
    if not isinstance(frames, (list, tuple)):
        return False, None
    for frame in frames:
        for _name, pattern, selector in _FRAMES:
            if not pattern.search(str(frame.url or "")):
                continue
            controls = frame.locator(selector)
            if controls.count() != 1 or controls.first.get_attribute("aria-checked", timeout=500) != "true":
                continue
            form = frame.frame_element().query_selector("xpath=ancestor::form[1]")
            if form is None:
                continue
            if form.evaluate('''el => [...el.querySelectorAll(
                    'input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select, [contenteditable=true]'
                    )].some(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')'''):
                return True, None
            candidates = [el for el in form.query_selector_all('button, input[type=submit], input[type=image]')
                          if el.is_visible() and el.evaluate("el => el.form !== null && ['submit','image'].includes(el.type)")]
            return True, candidates[0] if len(candidates) == 1 else None
    return False, None


def press_forward(page: Any, *, timeout_ms: int,
                  observation: Any = None) -> Literal["absent", "pressed", "unavailable"]:
    """One press on the interstitial's own forward button, when it is there to press.

    Prefer the unique native submit of the checked widget's form, regardless of
    its label. Legacy non-form interstitials use known forward labels. Ambiguous
    or disabled form controls stay untouched; a click is never proof of access.
    """
    note = observation or (lambda _reason: None)
    from ...driver import Error
    try:
        found_form, submit = _checked_form_submit(page)
        if found_form:
            if submit is None or not submit.is_enabled():
                note("forward form: ambiguous or not actionable")
                return "unavailable"
            _press(page, submit, box=submit.bounding_box(), remaining_ms=timeout_ms)
            note("forward pressed: checked widget form submit")
            return "pressed"
    except Error as exc:
        note(f"forward form: {type(exc).__name__}")
        return "unavailable"
    seen = False
    for text in _FORWARD_TEXTS:
        button = None
        try:
            role = page.get_by_role("button", name=text, exact=True)
            if role.count():
                seen = True
                button = role.first
        except Exception as exc:  # noqa: BLE001
            note(f"forward role {text}: {type(exc).__name__}")
        if button is None:
            try:
                locator = page.get_by_text(text, exact=True)
                if locator.count():
                    seen = True
                    button = locator.first
            except Exception as exc:  # noqa: BLE001
                note(f"forward text {text}: {type(exc).__name__}")
        if button is None:
            continue
        try:
            if not (button.is_visible() and button.is_enabled()):
                note(f"forward {text}: not actionable")
                continue
            box = button.bounding_box()
            if box:
                pointer.approach(page, box, limit_sec=pointer.budget_for(timeout_ms))
            button.click(timeout=timeout_ms, no_wait_after=True)
            note(f"forward pressed: {text}")
            return "pressed"
        except Exception as exc:  # noqa: BLE001
            note(f"forward {text}: {type(exc).__name__}")
    return "unavailable" if seen else "absent"


def expired(page: Any) -> bool:
    """The interstitial says the verification expired and offers its own refresh."""
    try:
        return bool(page.get_by_text("verification has expired", exact=False).count())
    except Exception:  # noqa: BLE001
        return False


def press_refresh(page: Any, *, timeout_ms: int, observation: Any = None) -> bool:
    """Press the interstitial's own "Refresh verification" once, before pressing again."""
    note = observation or (lambda _reason: None)
    try:
        locator = page.get_by_role("button", name="Refresh verification", exact=True)
        if not locator.count():
            locator = page.get_by_text("Refresh verification", exact=True)
        if not locator.count():
            return False
        button = locator.first
        if not (button.is_visible() and button.is_enabled()):
            return False
        button.click(timeout=timeout_ms, no_wait_after=True)
        note("refresh pressed")
        return True
    except Exception as exc:  # noqa: BLE001
        note(f"refresh: {type(exc).__name__}")
        return False
