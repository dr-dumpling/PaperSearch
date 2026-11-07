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
    const ready = window[key] = new WeakMap();
    let revision = 0;
    addEventListener('message', event => {
        if (event.origin !== 'https://challenges.cloudflare.com' || !event.source
            || event.data?.source !== 'cloudflare-challenge') return;
        if (event.data.event === 'interactiveBegin') ready.set(event.source, ++revision);
        else if (['interactiveEnd', 'complete', 'fail', 'tokenExpired']
                 .includes(event.data.event)) ready.delete(event.source);
    });
}"""


def observe_checkbox(page: Any) -> None:
    """Observe readiness only; never read or write the verification response."""
    from .driver import main_world

    page.evaluate(_OBSERVE_SCRIPT, **main_world(page))  # where the init script observes


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


# A page that navigated away while it was read: the next check reads the new page.
_NAVIGATED = ("frame was detached", "frame has been detached", "element is not attached",
              "execution context was destroyed")


def is_image_verification(page: Any) -> bool:
    """Image puzzles expose controls but may have no readable instructions."""
    from .driver import Error

    try:
        return page.evaluate("""() => document.title.trim().toLowerCase() === 'human verification'
            && !document.querySelector('meta[name="citation_doi"]')
            && [...document.querySelectorAll('button, [role="button"], canvas, iframe')].some(el =>
                el.getClientRects().length > 0)""") is True
    except Error as exc:
        # A passed verification navigates while it is being read (Wiley and
        # ScienceDirect on Chrome, 2026-11-07): no puzzle on a page that is gone.
        if any(text in str(exc).lower() for text in _NAVIGATED):
            return False
        raise


def needs_manual_verification(page: Any) -> bool:
    """A puzzle or reCAPTCHA on an already recognised verification page.

    Reading a checked box or a response token cannot prove that the enclosing
    page's confirmation was submitted. Leave both actions to the user.
    """
    return is_image_verification(page) or has_visible_recaptcha(page)


def has_visible_recaptcha(page: Any) -> bool:
    """Detect a reCAPTCHA prompt that remains after the outer page changes."""
    from .driver import Error

    for frame in page.frames:
        parsed = urlsplit(str(frame.url or ""))
        if (parsed.scheme != "https" or parsed.hostname not in {
                "www.google.com", "www.recaptcha.net", "recaptcha.net"}
                or not parsed.path.startswith(("/recaptcha/api2/", "/recaptcha/enterprise/"))):
            continue
        try:
            if frame.frame_element().is_visible():
                return True
        except Error as exc:
            if not any(text in str(exc).lower() for text in (
                    "frame was detached", "frame has been detached", "element is not attached",
                    "execution context was destroyed")):
                raise
    return False


def click_checkbox(page: Any, *, timeout_ms: int, checkpoint: Callable[[], None],
                   observation: Callable[[str], None] | None = None) -> Literal[
    "absent", "clicked", "unavailable"
]:
    """Try one visible checkbox; never force a click through an overlay.

    A closed shadow root hides the checkbox from locators. Only the normal,
    compact-height Cloudflare widget with its identifying iframe title can
    use its standard checkbox position. Expanded puzzles are left alone.
    """
    from .driver import Error, TimeoutError, main_world

    def note(reason: str) -> None:
        if observation is not None:
            observation(reason)

    until = time.monotonic() + max(0, timeout_ms) / 1000
    unavailable = False
    for frame in page.frames:
        checkpoint()
        if time.monotonic() >= until:
            return "unavailable" if unavailable else "absent"
        if not is_turnstile_frame(str(frame.url or "")):
            continue
        try:
            # An iframe can be present for seconds while only a spinner is up.
            # Start observing before inspecting it, so a later call can act.
            observe_checkbox(page)
            element = frame.frame_element()
            if not element.is_visible():
                note("hidden_frame")
                continue
            controls = frame.locator('input[type="checkbox"], [role="checkbox"]')
            count = controls.count()
            position = None
            if count:
                if count != 1:
                    note("multiple_controls")
                    unavailable = True
                    continue
                target = controls.first
                if not target.is_visible():
                    note("hidden_control")
                    continue
                if not target.is_enabled() or target.is_checked():
                    note("disabled_or_checked")
                    unavailable = True
                    continue
            else:
                title = (element.get_attribute("title") or "").lower()
                box = element.bounding_box()
                if ("cloudflare" not in title or "challenge" not in title or not box
                        or not 250 <= box["width"] <= 350 or not 60 <= box["height"] <= 80):
                    geometry = f" width={box['width']:.0f} height={box['height']:.0f}" if box else ""
                    note("unsupported_geometry_or_title" + geometry)
                    unavailable = True
                    continue
                readiness = element.evaluate("""iframe =>
                    window[Symbol.for('papersearch.turnstile.ready')]?.get(iframe.contentWindow) || 0
                """, **main_world(element))
                if not readiness:
                    note("waiting_ready_signal")
                    continue  # loading/automatic check; no click has been attempted
                target = element
                position = {"x": 28, "y": box["height"] / 2}
            checkpoint()
            remaining_ms = int((until - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return "unavailable"
            # click performs visibility, stability and hit-target checks itself.
            # A separate humanized hover uses the same short action budget twice.
            # Keep readiness on actionability timeout so an overlay can clear.
            # The engine observes the navigation separately. A dispatched click
            # must not be reported as unavailable while waiting for that load.
            target.click(timeout=remaining_ms, no_wait_after=True,
                         **({"position": position} if position else {}))
            if position:
                try:
                    element.evaluate("""(iframe, revision) => {
                        const ready = window[Symbol.for('papersearch.turnstile.ready')];
                        if (ready?.get(iframe.contentWindow) === revision) ready.delete(iframe.contentWindow);
                    }""", readiness, **main_world(element))
                except Error as exc:
                    if not any(text in str(exc).lower() for text in (
                            "frame was detached", "frame has been detached", "element is not attached",
                            "execution context was destroyed")):
                        raise
            note("click_dispatched")
            return "clicked"
        except TimeoutError:
            note("actionability_timeout")
            unavailable = True
        except Error as exc:
            # Navigation can remove the widget before its action. Browser close,
            # crash, watchdog and cancellation errors must still reach the caller.
            if any(text in str(exc).lower() for text in (
                "frame was detached", "frame has been detached", "element is not attached",
                "execution context was destroyed",
            )):
                note("frame_detached")
                unavailable = True
                continue
            raise
    return "unavailable" if unavailable else "absent"
