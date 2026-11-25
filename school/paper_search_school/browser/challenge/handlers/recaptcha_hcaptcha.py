"""Known reCAPTCHA/hCaptcha grid controls, with provider-specific image contracts.

Unknown geometry, drag/audio questions and changing images are never guessed.
The enclosing verification wait alone decides whether the publisher passed.
"""
from __future__ import annotations

import struct
from typing import Any
from urllib.parse import urlsplit

from ...driver import Error
from ..local import prompt
from ..services import solver

# Official ReCaptchaV2Classification question IDs. Only exact visible labels;
# unknown languages/categories stay manual instead of being mistranslated.
_QUESTIONS = {
    "taxis": "/m/0pg52", "bus": "/m/01bjv", "buses": "/m/01bjv",
    "motorcycles": "/m/04_sv", "tractors": "/m/013xlm", "chimneys": "/m/01jk_4",
    "crosswalks": "/m/014xcs", "traffic lights": "/m/015qff", "bicycles": "/m/0199g",
    "parking meters": "/m/015qbp", "cars": "/m/0k4j", "bridges": "/m/015kr",
    "boats": "/m/019jd", "palm trees": "/m/0cdl1", "mountains or hills": "/m/09d_r",
    "fire hydrant": "/m/01pns0", "fire hydrants": "/m/01pns0", "stairs": "/m/01lynh",
}
_SELECTORS = {
    "recaptcha": (".rc-imageselect-desc-wrapper", ".rc-imageselect-tile", "#recaptcha-verify-button"),
    "hcaptcha": (".prompt-text", ".task-image", ".button-submit"),
}
_SIGNATURE = """els => els.map(el => [...el.querySelectorAll('img, .image')].map(im =>
    [im.currentSrc || im.getAttribute('src'), getComputedStyle(im).backgroundImage]))"""


def _frame(page: Any, kind: str) -> Any:
    frames = getattr(page, "frames", ())
    for frame in frames if isinstance(frames, (tuple, list)) else ():
        p = urlsplit(str(frame.url or ""))
        host = p.hostname or ""
        matches = (kind == "recaptcha" and host in {"www.google.com", "google.com", "www.recaptcha.net", "recaptcha.net"}
                   and p.path in {"/recaptcha/api2/bframe", "/recaptcha/enterprise/bframe"}) or (
                       kind == "hcaptcha" and (host == "hcaptcha.com" or host.endswith(".hcaptcha.com"))
                       and p.path.startswith("/captcha/"))
        if matches and frame.frame_element().is_visible():
            if frame.locator(_SELECTORS[kind][1]).count():
                return frame
    return None


def has_grid(page: Any) -> bool:
    """Stop checkbox waiting as soon as a supported provider shows a picture grid."""
    try:
        return any(_frame(page, kind) is not None for kind in _SELECTORS)
    except Error:
        return False


def _snapshot(frame: Any, kind: str, limits: Any) -> dict | None:
    question_sel, cell_sel, _ = _SELECTORS[kind]
    cells = frame.locator(cell_sel)
    count = cells.count()
    if count not in ((9, 16) if kind == "recaptcha" else (9,)):
        return None
    limits.remaining()
    question = frame.locator(question_sel).inner_text(timeout=1000).strip()
    signature = cells.evaluate_all(_SIGNATURE)
    anchors = []
    if kind == "recaptcha":
        label = frame.locator(question_sel + " strong").inner_text(timeout=1000).strip().lower()
        question = _QUESTIONS.get(label, "")
        if not question:
            return None
        picture = frame.locator(".rc-imageselect-table-33, .rc-imageselect-table-44")
        if picture.count() != 1:
            return None
        images = [picture.screenshot(scale="css", timeout=min(2000, int(limits.remaining()*1000)))]
        expected = 300 if count == 9 else 450
        if images[0][:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', images[0][16:24]) != (expected, expected):
            return None
    else:
        if not question or question.lower().startswith(('drag', 'please drag')):
            return None
        images = []
        for i in range(count):
            images.append(cells.nth(i).locator('.image').screenshot(
                scale="css", timeout=min(2000, int(limits.remaining()*1000))))
        # Examples can be an image or a background on the example container
        # itself. Select visible picture surfaces above the tiles, outside them;
        # selectors for one particular prompt wrapper miss other hCaptcha builds.
        for anchor in frame.locator('img, canvas, .image, [style*="background-image"]').all():
            if anchor.evaluate('''el => {
                if(el.closest('.task-image') || !el.getClientRects().length) return false;
                const r=el.getBoundingClientRect(), first=document.querySelector('.task-image');
                if(!first || r.bottom>first.getBoundingClientRect().top+2 ||
                   r.width<30 || r.height<30 || r.width>300 || r.height>300) return false;
                return /^(IMG|CANVAS)$/.test(el.tagName) || getComputedStyle(el).backgroundImage!=='none';
            }''', timeout=min(1000, max(1, int(limits.remaining()*1000)))):
                anchors.append(anchor.screenshot(scale="css", timeout=min(2000, int(limits.remaining()*1000))))
    if signature != cells.evaluate_all(_SIGNATURE):
        return None
    return dict(question=question, signature=signature, images=images, anchors=anchors, count=count)


def solve(page: Any, config: dict, *, kind: str, limits: Any, observation: Any) -> bool:
    note = observation
    try:
        for round_number in range(1, 4):
            limits.remaining()
            if prompt.confirm_checked(page):
                return True  # engine owns the common outer-form submission
            frame = _frame(page, kind)
            if frame is None:
                note(f"{kind}: no visible grid")
                return False
            grid = _snapshot(frame, kind, limits)
            if grid is None:
                note(f"{kind}: unsupported or unstable grid/question")
                return False
            if not limits.budget.take():
                note("service budget exhausted")
                return False
            note(f"{kind}: service request images={len(grid['images'])} examples={len(grid['anchors'])}")
            answer = solver.solve_tiles(grid['images'], grid['question'], config, kind=kind,
                                        count=grid['count'], anchors=grid['anchors'],
                                        timeout=min(limits.remaining(), float(config.get('captcha_timeout', 90))),
                                        checkpoint=limits.remaining)
            limits.remaining()
            if answer is None:
                note(f"{kind}: service failed or invalid answer")
                return False
            cells = frame.locator(_SELECTORS[kind][1])
            # Do not apply an answer to images replaced while the service worked.
            if cells.evaluate_all(_SIGNATURE) != grid['signature']:
                note(f"{kind}: images changed; discard answer")
                continue
            changed = False
            for index in range(grid['count']):
                limits.remaining()
                if cells.evaluate_all(_SIGNATURE) != grid['signature']:
                    changed = True
                    break
                cell = cells.nth(index)
                selected = cell.get_attribute('aria-pressed', timeout=min(1000, max(1, int(limits.remaining()*1000)))) == 'true' or cell.get_attribute('aria-checked', timeout=min(1000, max(1, int(limits.remaining()*1000)))) == 'true'
                selected = selected or 'rc-imageselect-tileselected' in (cell.get_attribute('class', timeout=min(1000, max(1, int(limits.remaining()*1000)))) or '')
                if selected != (index in answer):
                    cell.click(timeout=min(2000, int(limits.remaining()*1000)), no_wait_after=True)
            limits.sleep(1)
            if changed or cells.evaluate_all(_SIGNATURE) != grid['signature']:
                note(f"{kind}: replacement images; read next round")
                continue
            frame.locator(_SELECTORS[kind][2]).click(
                timeout=min(2000, int(limits.remaining()*1000)), no_wait_after=True)
            note(f"{kind}: answer submitted; round {round_number}/3")
            # The provider may acknowledge asynchronously after hiding the grid.
            # Observe before taking another snapshot or paying for another answer.
            for _ in range(10):
                limits.sleep(0.5)
                if prompt.confirm_checked(page) or _frame(page, kind) is None:
                    return True  # outer loop owns form submission and access checks
        note(f"{kind}: three image rounds exhausted")
        return False
    except Error as exc:
        if any(marker in str(exc).lower() for marker in (
                "frame was detached", "frame has been detached", "execution context was destroyed")):
            note(f"{kind}: document changed; outer verification must recheck")
            return True
        note(f"{kind}: browser interaction failed ({type(exc).__name__})")
        return False
