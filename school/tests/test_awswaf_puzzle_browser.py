"""AWS controls in local Chrome; fixture answers never call a paid service."""
import os
import struct

import pytest

from paper_search_school.browser.challenge.handlers import aws_waf as awswaf
from paper_search_school.browser.challenge.services import solver

pytestmark = pytest.mark.skipif(os.environ.get("SCHOOL_LOCAL_BROWSER_TEST") != "1",
                                reason="local Chrome fixture opt-in")
CONFIG = {"captcha_service": "yescaptcha", "captcha_key": "fixture", "captcha_max_per_run": 1}
HTML = """<!doctype html><title>Let's confirm you are human</title>
<div id="captcha-container"><button id="amzn-captcha-verify-button">Begin</button></div>
<output id="submitted"></output>
<script>
document.querySelector('button').onclick=()=>{
 const root=document.querySelector('#captcha-container');
 root.innerHTML='<p>Choose all the hats</p><div style="position:relative;width:320px;height:320px">'
  +'<canvas width="320" height="320" style="width:320px;height:320px"></canvas>'
  +Array.from({length:9},(_,i)=>`<button class="amzn-grid-cell" aria-checked="false"
    aria-label="Image ${i+1}" style="position:absolute;left:${i%3*106}px;top:${Math.floor(i/3)*106}px;
    width:104px;height:104px">${i+1}</button>`).join('')+'</div>'
  +'<button id="amzn-btn-verify-internal">Confirm</button>';
 root.querySelectorAll('.amzn-grid-cell').forEach(b=>b.onclick=()=>{
   b.setAttribute('aria-checked',b.getAttribute('aria-checked')==='true'?'false':'true');
 });
 root.querySelector('#amzn-btn-verify-internal').onclick=()=>{
   const chosen=[...root.querySelectorAll('.amzn-grid-cell')]
     .flatMap((b,i)=>b.getAttribute('aria-checked')==='true'?[i]:[]);
   document.querySelector('#submitted').textContent=JSON.stringify(chosen);
   if(JSON.stringify(chosen)==='[1,2,3,7,8]'){
     root.remove();document.title='Research article';
     document.body.insertAdjacentHTML('beforeend','<article>Article text</article>');
   }
 };
};
</script>"""


@pytest.fixture
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True, args=[
            "--disable-background-networking", "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"])
        context = browser.new_context(device_scale_factor=2, service_workers="block")
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=HTML))
        page = context.new_page()
        page.goto("https://journal.example/article")
        yield page
        browser.close()


def test_retina_image_coordinates_and_real_confirm_complete_the_page(page, monkeypatch):
    def answer(image, question, config, **kwargs):
        width, height = struct.unpack(">II", image[16:24])
        assert (width, height) == (320, 320)
        assert question == "Choose all the hats"
        return [(width/2, height/6), (width*5/6, height/6),
                (width/6, height/2), (width/2, height*5/6), (width*5/6, height*5/6)]

    monkeypatch.setattr(solver, "solve_grid", answer)
    notes = []
    assert awswaf.solve(page, CONFIG, observation=notes.append)
    assert page.title() == "Research article"
    assert page.locator('#submitted').text_content() == '[1,2,3,7,8]'
    assert "confirm pressed=True" in notes


def test_a_missing_control_is_not_reported_as_pressed(page):
    assert awswaf._press(page, '#missing', lambda _: None) is False
    assert awswaf._press(page, '#amzn-captcha-verify-button', lambda _: None) is True


def test_multiple_points_in_one_tile_do_not_toggle_it_back_off(page):
    page.locator('#amzn-captcha-verify-button').click()
    box = awswaf._grid(page)['grid']
    assert awswaf._click_points(page, box, [(50, 50), (60, 60), (150, 150)])
    cells = page.locator('.amzn-grid-cell')
    assert [i for i in range(9) if cells.nth(i).get_attribute('aria-checked') == 'true'] == [0, 4]


def test_a_failed_page_read_is_not_verification_success(page, monkeypatch):
    monkeypatch.setattr(awswaf, 'LEFT_WAIT_SEC', 0.05)
    monkeypatch.setattr(awswaf, 'RETRY_DELAY_SEC', 0)
    monkeypatch.setattr(awswaf, 'CONFIRM_DELAY_SEC', 0)
    monkeypatch.setattr(solver, 'solve_grid', lambda *a, **k: [(50, 50)])
    original = awswaf._press

    def press(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1] == '#amzn-btn-verify-internal' and result:
            page.close()
        return result

    monkeypatch.setattr(awswaf, '_press', press)
    assert awswaf.solve(page, CONFIG) is False


def test_new_answer_clears_choices_left_by_the_rejected_answer(page):
    page.locator('#amzn-captcha-verify-button').click()
    box = awswaf._grid(page)['grid']
    assert awswaf._click_points(page, box, [(50, 50), (150, 50)])
    assert awswaf._click_points(page, box, [(50, 50), (250, 50)])
    assert page.locator('button.amzn-grid-cell[aria-checked=true]').count() == 2
    assert page.locator('button.amzn-grid-cell').nth(1).get_attribute('aria-checked') == 'false'
