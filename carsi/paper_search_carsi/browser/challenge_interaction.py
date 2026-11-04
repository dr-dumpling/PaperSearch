"""One bounded interaction with an observed Turnstile widget.

No navigation, token injection, session transfer or success judgement. The
engine owns waiting and decides whether verification has actually ended.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlsplit


_OBSERVE_SCRIPT = """() => {
    const key = Symbol.for('papersearch.turnstile.ready');
    if (window[key]) return;
    const ready = window[key] = new WeakSet();
    addEventListener('message', event => {
        if (event.origin !== 'https://challenges.cloudflare.com' || !event.source
            || event.data?.source !== 'cloudflare-challenge') return;
        if (event.data.event === 'interactiveBegin') ready.add(event.source);
        else if (['interactiveEnd', 'complete', 'fail', 'tokenExpired']
                 .includes(event.data.event)) ready.delete(event.source);
    });
}"""


def observe_checkbox(page: Any) -> None:
    """Observe readiness only; never read or write the verification response."""
    page.evaluate(_OBSERVE_SCRIPT)


def prepare_context(context: Any) -> None:
    """Observe each owned page before navigation, including its PDF popups.

    The ego context filters its pages/events to CARSI-owned tabs. Install per
    page, never on the shared context (which would also affect the user's tabs).
    """
    if getattr(context, "_papersearch_challenge_observer", False) is True:
        return

    def prepare(page: Any) -> None:
        if getattr(page, "_papersearch_challenge_observer", False) is not True:
            page.add_init_script("(" + _OBSERVE_SCRIPT + ")()")
            page._papersearch_challenge_observer = True

    open_page = context.new_page
    def new_page(*args: Any, **kwargs: Any) -> Any:
        page = open_page(*args, **kwargs)
        prepare(page)
        return page

    context.new_page = new_page
    context.on("page", prepare)
    for page in context.pages:
        prepare(page)
    context._papersearch_challenge_observer = True


def is_turnstile_frame(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname == "challenges.cloudflare.com"
            and parsed.path.startswith("/cdn-cgi/challenge-platform/")
            and "/turnstile/" in parsed.path)


def click_checkbox(page: Any, *, timeout_ms: int, checkpoint: Callable[[], None]) -> Literal[
    "absent", "clicked", "unavailable"
]:
    """Try one visible checkbox; never force a click through an overlay.

    A closed shadow root hides the checkbox from locators. Only the normal,
    compact-height Cloudflare widget with its identifying iframe title can
    use its standard checkbox position. Expanded puzzles are left alone.
    """
    from playwright.sync_api import Error, TimeoutError

    until = time.monotonic() + max(0, timeout_ms) / 1000
    for frame in page.frames:
        checkpoint()
        if time.monotonic() >= until:
            return "absent"
        if not is_turnstile_frame(str(frame.url or "")):
            continue
        try:
            # An iframe can be present for seconds while only a spinner is up.
            # Start observing before inspecting it, so a later call can act.
            observe_checkbox(page)
            element = frame.frame_element()
            if not element.is_visible():
                continue
            controls = frame.locator('input[type="checkbox"], [role="checkbox"]')
            count = controls.count()
            position = None
            if count:
                if count != 1:
                    return "unavailable"
                target = controls.first
                if not target.is_visible() or not target.is_enabled() or target.is_checked():
                    return "unavailable"
            else:
                title = (element.get_attribute("title") or "").lower()
                box = element.bounding_box()
                if ("cloudflare" not in title or "challenge" not in title or not box
                        or not 250 <= box["width"] <= 350 or not 60 <= box["height"] <= 80):
                    return "unavailable"
                if not element.evaluate("""iframe =>
                    window[Symbol.for('papersearch.turnstile.ready')]?.has(iframe.contentWindow) === true
                """):
                    return "absent"  # loading/automatic check; no click has been attempted
                target = element
                position = {"x": 28, "y": box["height"] / 2}
            checkpoint()
            # One readiness signal permits only one closed-shadow click. Wait
            # for a fresh interactiveBegin before retrying; otherwise a stale
            # signal could toggle an already checked or processing widget.
            if position and not element.evaluate("""iframe =>
                window[Symbol.for('papersearch.turnstile.ready')]?.delete(iframe.contentWindow) === true
            """):
                return "absent"
            remaining_ms = int((until - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return "unavailable"
            target.click(timeout=remaining_ms, **({"position": position} if position else {}))
            return "clicked"
        except TimeoutError:
            return "unavailable"  # hidden/covered/stale; no repeated forced clicks
        except Error as exc:
            # Navigation can remove the widget before its action. Browser close,
            # crash, watchdog and cancellation errors must still reach the caller.
            if any(text in str(exc).lower() for text in (
                "frame was detached", "frame has been detached", "element is not attached",
                "execution context was destroyed",
            )):
                return "unavailable"
            raise
    return "absent"
