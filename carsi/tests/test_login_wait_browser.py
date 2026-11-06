"""Trusted interaction detection on local login documents; no system input."""
import os

import pytest

from paper_search_carsi.engine.login_wait import LoginWait


pytestmark = pytest.mark.skipif(os.environ.get("CARSI_LOCAL_BROWSER_TEST") != "1",
                                reason="local Chrome fixture opt-in")
FORM = ('<form onsubmit="event.preventDefault()"><label>Fixture account<input name="account"></label>'
        '<button>Sign in</button></form>')


@pytest.mark.parametrize("target", ["main", "iframe", "popup"])
def test_trusted_login_input_pauses_but_script_updates_and_focus_do_not(target):
    from playwright.sync_api import sync_playwright

    clock = [1000.0]
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True, args=[
            "--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=FORM))
        page = context.new_page()
        try:
            page.goto("https://login.fixture.test/main")
            if target == "iframe":
                page.set_content('<iframe src="https://frame.fixture.test/login"></iframe>')
                frame = page.frame(url="https://frame.fixture.test/login")
                if frame is None:
                    page.wait_for_event("framenavigated")
                    frame = page.frame(url="https://frame.fixture.test/login")
            elif target == "popup":
                with page.expect_popup() as opened:
                    page.evaluate("window.open('https://login.fixture.test/popup')")
                page = opened.value
                page.wait_for_load_state()
                frame = page.main_frame
            else:
                frame = page.main_frame
            wait = LoginWait(1180, lambda: clock[0])
            wait.observe(page, True)
            field = frame.get_by_label("Fixture account")
            field.focus()
            field.evaluate("el => {el.value='script fixture';el.dispatchEvent(new InputEvent('input',{bubbles:true}));}")
            field.evaluate("""el => {
                el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'}));
                el.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,code:'ArrowRight'}));
                el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerType:'mouse'}));
                el.dispatchEvent(new Event('change',{bubbles:true}));
            }""")
            field.evaluate("el => el.form.requestSubmit()")
            wait.observe(page, True)
            assert not wait.paused
            clock[0] += 10
            field.fill("user fixture")  # trusted events in this test page only
            wait.observe(page, True)
            assert wait.paused
            clock[0] += 400
            assert wait.deadline - clock[0] == 170
            page.goto("https://login.fixture.test/second-factor")
            wait.observe(page, True)
            assert wait.paused  # another authentication step keeps takeover
            wait.observe(page, False)
            assert not wait.paused
            assert page.evaluate("!window[Symbol.for('paper-search:login-activity')]")
            wait.close()
            for action in ("click", "keyboard"):
                wait = LoginWait(clock[0] + 180, lambda: clock[0])
                wait.observe(page, True)
                field = page.get_by_label("Fixture account")
                if action == "click":
                    field.click()
                else:
                    field.press("ArrowRight")
                wait.observe(page, True)
                assert wait.paused, action
                wait.close()
        finally:
            context.close()
            browser.close()
