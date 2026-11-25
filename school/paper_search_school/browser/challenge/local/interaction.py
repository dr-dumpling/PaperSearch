"""One bounded interaction with an observed Turnstile widget.

No navigation, token injection, session transfer or success judgement. The
engine owns waiting and decides whether verification has actually ended.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlsplit


_OBSERVE_SCRIPT = """() => {
    const key = Symbol.for('papersearch.turnstile.ready');
    if (window[key]) return;
    const ready = window[key] = new WeakMap();
    const seen = window[Symbol.for('papersearch.turnstile.events')] = [];
    let revision = 0;
    addEventListener('message', event => {
        if (event.origin !== 'https://challenges.cloudflare.com' || !event.source
            || event.data?.source !== 'cloudflare-challenge') return;
        const name = String(event.data.event || '');
        if (name && seen.length < 64) seen.push({event: name, at: Date.now()});
        if (name === 'interactiveBegin') ready.set(event.source, ++revision);
        else if (['interactiveEnd', 'complete', 'fail', 'tokenExpired']
                 .includes(name)) ready.delete(event.source);
    });
}"""


def observe_checkbox(page: Any) -> None:
    """Observe readiness only; never read or write the verification response."""
    from ...driver import main_world

    page.evaluate(_OBSERVE_SCRIPT, **main_world(page))  # where the init script observes


def interaction_events(page: Any) -> list[dict[str, Any]]:
    """What the widget reported on this page, for the article's record.

    The event names and their times, never the response token: this reads what
    the observer already saw and changes nothing. A page that was never
    observed, or one that navigated away while it was read, reports nothing.
    For diagnosis only — no caller may treat an event as proof of a pass.
    """
    from ...driver import Error, main_world
    from ...watchdog import CallAbandoned, call_limit

    try:
        with call_limit(READ_LIMIT_SEC):
            seen = page.evaluate("""() => {
                const key = Symbol.for('papersearch.turnstile.events');
                return (window[key] || []).slice(-64);
            }""", **main_world(page))
    except CallAbandoned:
        return []
    except Error as exc:
        if any(text in str(exc).lower() for text in _NAVIGATED):
            return []
        raise
    if not isinstance(seen, list):
        return []
    return [item for item in seen if isinstance(item, dict)]


def prepare_context(context: Any) -> None:
    """Observe each owned page before navigation, including its PDF popups.

    The ego context filters its pages/events to the backend's own tabs. Install per
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


# The longest one read of a verification page may take. After its checkbox the page
# can hang between two documents: one read waited 48 s and the article's page budget
# ran out before the page it led to opened (BMJ on Windows, 2026-11-11).
READ_LIMIT_SEC = 5
FRIENDLY_CAPTCHA = "Friendly Captcha"


def is_image_verification(page: Any) -> bool:
    """Image puzzles expose controls but may have no readable instructions."""
    from ...driver import Error
    from ...watchdog import CallAbandoned, call_limit

    try:
        with call_limit(READ_LIMIT_SEC):
            return page.evaluate("""() => document.title.trim().toLowerCase() === 'human verification'
                && !document.querySelector('meta[name="citation_doi"]')
                && [...document.querySelectorAll('button, [role="button"], canvas, iframe')].some(el =>
                    el.getClientRects().length > 0)""") is True
    except CallAbandoned:
        return False  # between two documents: the next check reads the one that opens
    except Error as exc:
        # A passed verification navigates while it is being read (Wiley and
        # ScienceDirect on Chrome, 2026-11-07): no puzzle on a page that is gone.
        if any(text in str(exc).lower() for text in _NAVIGATED):
            return False
        raise


def needs_manual_verification(page: Any) -> bool:
    """A puzzle, reCAPTCHA or another provider's widget on an already recognised
    verification page.

    Reading a checked box or a response token cannot prove that the enclosing
    page's confirmation was submitted. Leave these actions to the user.
    """
    return (is_image_verification(page) or has_visible_recaptcha(page)
            or bool(verification_widget(page, manual_only=True)))


# Verification widgets the program never operates (the user, 2026-11-11): a page
# showing one is a verification for the user. Frames by their address, read without
# a browser call; elements by the providers' fixed names; AWS WAF, whose puzzle has
# no fixed element, by its script. Turnstile is Cloudflare's own check, whose box the
# program clicks (``click_checkbox``). Not a verification page: an article (citation
# metadata), whose comment or newsletter form may carry a widget, and a long page,
# where a widget is one form among others (a publisher's personal sign-in).
_WIDGET_FRAMES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("reCAPTCHA", re.compile(r"^https://(?:www\.)?(?:google\.com|recaptcha\.net)/recaptcha/"
                             r"(?:api2|enterprise)/(?:anchor|bframe)").search),
    ("hCaptcha", re.compile(r"^https://(?:[a-z0-9-]+\.)*hcaptcha\.com/captcha/").search),
    ("DataDome", re.compile(r"^https://(?:[a-z0-9-]+\.)*captcha-delivery\.com/").search),
    ("Arkose", re.compile(r"^https://(?:[a-z0-9-]+\.)*(?:arkoselabs\.com|funcaptcha\.com)/").search),
    ("Tencent", re.compile(r"^https://(?:turing\.captcha\.qcloud\.com|t\.captcha\.qq\.com|"
                           r"ssl\.captcha\.qq\.com)/").search),
    ("Turnstile", lambda url: is_turnstile_frame(url)),
    (FRIENDLY_CAPTCHA, lambda url: "frcapi.com/api/v2/captcha/widget" in url),
)
_WIDGET_ELEMENTS = (
    ("Turnstile", ".cf-turnstile[data-sitekey]"),
    (FRIENDLY_CAPTCHA, ".frc-captcha"),
    ("GeeTest", ".geetest_holder, .geetest_panel, .geetest_box, .geetest_captcha"),
    ("Aliyun", "[id^='aliyunCaptcha-'], #nc_1_wrapper"),
    ("Tencent", "#tcaptcha_iframe, #tcaptcha_transform"),
    ("PerimeterX", "#px-captcha"),
)
# Longer than this, the page is more than a verification interstitial.
_WIDGET_PAGE_TEXT = 2500
_WIDGET_PAGE_JS = r"""([groups, longest, friendlyCaptcha]) => {
    if (document.querySelector('meta[name="citation_doi"], meta[name="citation_title"]')) return '#page';
    const text = (document.body?.innerText || '').trim();
    if (text.length > longest) return '#page';
    const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
    if (/^verification required!?$/im.test(text) && /\bfriendly captcha\b/i.test(text)) return friendlyCaptcha;
    for (const [name, selector] of groups)
        if ([...document.querySelectorAll(selector)].some(shown)) return name;
    if ([...document.scripts].some(s => /^https:\/\/[^/]*\.captcha\.awswaf\.com\//.test(s.src || ''))) return 'AWS WAF';
    return '';
}"""


def verification_widget(page: Any, *, manual_only: bool = False) -> str:
    """The provider of a visible verification widget making up ``page``, or "".
    ``manual_only``: leave out Turnstile, which the program may click itself."""
    from ...driver import Error
    from ...watchdog import CallAbandoned, call_limit

    try:
        with call_limit(READ_LIMIT_SEC):
            found = page.evaluate(_WIDGET_PAGE_JS, [list(_WIDGET_ELEMENTS), _WIDGET_PAGE_TEXT, FRIENDLY_CAPTCHA])
    except CallAbandoned:
        return ""
    except Error as exc:
        if any(text in str(exc).lower() for text in _NAVIGATED):
            return ""  # the page went on: the next check reads the new one
        raise
    found = found if isinstance(found, str) else ""
    if found == "#page":
        return ""
    if found == "Turnstile" and manual_only:
        found = ""
    if found:
        return found
    frames = getattr(page, "frames", ())
    frames = frames if isinstance(frames, (list, tuple)) else ()
    for name, matches in _WIDGET_FRAMES:
        if manual_only and name == "Turnstile":
            continue
        for frame in frames:
            url = str(getattr(frame, "url", "") or "")
            # reCAPTCHA v3's badge is a frame too, on ordinary pages.
            if not matches(url) or "size=invisible" in url:
                continue
            try:
                with call_limit(READ_LIMIT_SEC):
                    if frame.frame_element().is_visible() is True:
                        return name
            except CallAbandoned:
                continue
            except Error as exc:
                if not any(text in str(exc).lower() for text in _NAVIGATED):
                    raise
    return ""


def has_visible_recaptcha(page: Any) -> bool:
    """Detect a reCAPTCHA prompt that remains after the outer page changes."""
    from ...driver import Error
    from ...watchdog import CallAbandoned, call_limit

    for frame in page.frames:
        parsed = urlsplit(str(frame.url or ""))
        if (parsed.scheme != "https" or parsed.hostname not in {
                "www.google.com", "www.recaptcha.net", "recaptcha.net"}
                or not parsed.path.startswith(("/recaptcha/api2/", "/recaptcha/enterprise/"))):
            continue
        try:
            with call_limit(READ_LIMIT_SEC):
                if frame.frame_element().is_visible():
                    return True
        except CallAbandoned:
            continue  # the frame is going away with its page (``READ_LIMIT_SEC``)
        except Error as exc:
            if not any(text in str(exc).lower() for text in (
                    "frame was detached", "frame has been detached", "element is not attached",
                    "execution context was destroyed")):
                raise
    return False


def _retry_offset(attempt: int, *, vertical: bool) -> float:
    """A small, deterministic offset for a repeated press.

    The same pixel pressed twice is the shape an automated retry has, and a
    widget that re-rendered after the first press may have moved: the second
    and third presses land a couple of pixels away, still inside the box.
    """
    if attempt <= 0:
        return 0.0
    magnitude = 2.0 if attempt % 2 else 1.6
    sign = 1.0 if attempt % 4 in (1, 2) else -1.0
    value = magnitude * sign
    return -value if vertical else value


def click_checkbox(page: Any, *, timeout_ms: int, checkpoint: Callable[[], None],
                   observation: Callable[[str], None] | None = None,
                   attempt: int = 0) -> Literal[
    "absent", "clicked", "unavailable"
]:
    """Try one visible checkbox; never force a click through an overlay.

    A closed shadow root hides the checkbox from locators. Only the normal,
    compact-height Cloudflare widget with its identifying iframe title can
    use its standard checkbox position. Expanded puzzles are left alone.
    """
    from . import pointer
    from ...driver import Error, TimeoutError, main_world

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
            box = None
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
                box = target.bounding_box()  # the checkbox itself, not the frame
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
            if position and attempt:
                position = {"x": position["x"] + _retry_offset(attempt, vertical=False),
                            "y": position["y"] + _retry_offset(attempt, vertical=True)}
            # Turnstile reads the pointer history before a press: a click that
            # arrives from nowhere is the shape an automated one has. The
            # approach only moves the pointer; the press below still decides,
            # with its visibility, stability and hit-target checks.
            if box is None:
                box = element.bounding_box()
            pressed = False
            if box:
                # ``position`` is the box-relative point; without one the module
                # centres on the box it was given.
                landed = position
                if pointer.approach(page, box, point=landed,
                                          limit_sec=pointer.budget_for(remaining_ms)):
                    note("pointer_approach")
                # A held press, once the outer document confirms the widget's
                # frame is what sits under the point; an overlay keeps its turn.
                pressed = pointer.press(page, box, point=landed)
                if pressed:
                    note("pointer_press")
            if not pressed:
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
            note("press_dispatched" if pressed else "click_dispatched")
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


_CLOUDFLARE_FRAME = ("challenges.cloudflare.com", "/cdn-cgi/challenge-platform", "turnstile")
_RECAPTCHA_FRAME = ("/recaptcha/api2/", "/recaptcha/enterprise/")
_HCAPTCHA_FRAME = ("hcaptcha.com/captcha/",)
_AWS_FRAME = ("captcha.awswaf.com/",)
_CLOUDFLARE_TITLES = ("just a moment", "attention required", "verifying you are human",
                     "checking your browser", "verification required")


_AWS_WAF_SCRIPT = "/^https:\\/\\/[^/]*\\.captcha\\.awswaf\\.com\\//"


def _aws_waf_armed(page: Any) -> bool:
    """AWS WAF's own script on the outer page. Its button lives there, not in a
    provider frame, so the iframe addresses above never show it; without this a
    page carrying AWS WAF falls through to ``other``."""
    from ...driver import Error
    from ...watchdog import CallAbandoned, call_limit

    js = ("() => [...document.scripts].some(s => "
          + _AWS_WAF_SCRIPT + ".test(s.src || ''))")
    try:
        with call_limit(READ_LIMIT_SEC):
            return page.evaluate(js) is True
    except CallAbandoned:
        return False
    except Error as exc:
        if any(text in str(exc).lower() for text in _NAVIGATED):
            return False  # the page went on: the next check reads the new one
        raise


def challenge_kind(page: Any) -> str:
    """Identify the provider for the verification handoff decision."""

    from .. import detection

    try:
        url = str(getattr(page, "url", "") or "").lower()
    except Exception:  # noqa: BLE001
        url = ""
    try:
        title = str(getattr(page, "title", lambda: "")() or "")
    except Exception:  # noqa: BLE001
        title = ""
    frames: list[str] = []
    try:
        frames = [str(getattr(frame, "url", "") or "").lower() for frame in page.frames]
    except Exception:  # noqa: BLE001
        frames = []
    joined = " ".join(frames)

    if detection.looks_like_challenge(url, title):
        return "cloudflare"
    if any(is_turnstile_frame(frame) for frame in frames) or verification_widget(page) == "Turnstile":
        return "turnstile"
    if any(marker in joined for marker in _CLOUDFLARE_FRAME):
        return "cloudflare"
    if not detection.looks_like_challenge(url, title) and verification_widget(page) == FRIENDLY_CAPTCHA:
        return "friendlycaptcha"
    if any(marker in joined for marker in _RECAPTCHA_FRAME) or has_visible_recaptcha(page):
        return "recaptcha"
    if any(marker in joined for marker in _HCAPTCHA_FRAME):
        return "hcaptcha"
    if any(marker in joined for marker in _AWS_FRAME) or _aws_waf_armed(page):
        return "awswaf"
    lowered = title.lower()
    if any(signal in lowered for signal in _CLOUDFLARE_TITLES):
        return "cloudflare"
    if detection.looks_like_challenge(url, title):
        return "other"   # 认得出是验证页、但不是 Cloudflare（AMS 的 Human Verification 就是这一类）
    return "other" if (url or title) else "unknown"
