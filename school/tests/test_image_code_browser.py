"""Replay standalone image-code forms on unrelated hosts, without paid requests."""
import os
import time
from unittest.mock import Mock

import pytest
from paper_search_school.browser.challenge.handlers import text_captcha as image_code
from paper_search_school.browser.driver import main_world
from paper_search_school.browser.challenge import continuation
from paper_search_school.browser.challenge.services import solver

pytestmark = pytest.mark.skipif(os.environ.get('SCHOOL_LOCAL_BROWSER_TEST')!='1', reason='local Chrome opt-in')
CONFIG={'captcha_service':'yescaptcha','captcha_key':'fixture'}


@pytest.fixture(scope='module')
def browser():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--disable-background-networking','--no-proxy-server'])
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context=browser.new_context(device_scale_factor=2)
    yield context.new_page()
    context.close()


def form(picture):
    return '''<title>Captcha</title><p>Enter the letters and numbers below</p>
    <form>'''+picture+'''<br><input type=text id=answer><button type=submit>Continue</button></form>
    <script>document.querySelector('form').onsubmit=e=>{e.preventDefault();
    if(document.querySelector('input').value==='aB52'){
      document.title='Article';document.body.innerHTML='<article>Full text</article>';
    }}</script>'''


@pytest.mark.parametrize('picture',[
    '<span class=puzzle style="font-size:48px">encoded text</span>',
    '<canvas width=100 height=40></canvas>',
    '<img style="width:100px;height:40px" src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'100\' height=\'40\'/%3E">',
])
def test_character_answer_is_filled_into_its_form_and_submitted(page,monkeypatch,picture):
    page.set_content(form(picture))
    ask=Mock(return_value='aB52');monkeypatch.setattr(solver,'solve_image',ask)
    assert image_code.find(page)
    assert continuation.resume(page,CONFIG,kind='image_code',limits=continuation.Limits(time.monotonic()+10,solver.Budget(3)),observation=Mock())
    assert page.title()=='Article'
    assert ask.call_args.args[0].startswith(b'\x89PNG')
    ask.assert_called_once()


@pytest.mark.parametrize('extra',[
    '<input type=password>', '<input type=email>', '<input type=text>',
    '<meta name=citation_doi content="10.1000/example">',
])
def test_login_and_ambiguous_forms_are_not_sent_to_a_service(page,extra):
    page.set_content(form('<canvas width=100 height=40></canvas>')+extra)
    assert image_code.find(page) is None


def test_failed_answer_stops_at_the_shared_budget(page,monkeypatch):
    page.set_content(form('<canvas width=100 height=40></canvas>'))
    ask=Mock(return_value='wrong');monkeypatch.setattr(solver,'solve_image',ask)
    notes=[]
    assert not continuation.resume(page,CONFIG,kind='image_code',limits=continuation.Limits(time.monotonic()+10,solver.Budget(1)),observation=notes.append)
    assert page.title()=='Captcha'
    assert 'service budget exhausted' in notes
    assert ask.call_count==1


def submission_page(control, *, wrapper='form', extra=''):
    return '''<title>Captcha</title><p>Enter the letters and numbers below</p>
    <'''+wrapper+''' id=challenge><canvas width=100 height=40></canvas><br>
    <input type=text id=answer>'''+control+'</'+wrapper+'>'+extra+'''
    <script>
    window.clicked=[];
    document.addEventListener('submit',e=>e.preventDefault());
    document.addEventListener('click',e=>{
      const button=e.target.closest('#send, #other');
      if(!button)return;
      window.clicked.push(button.id);
      if(button.id==='send' && document.querySelector('#answer').value==='aB52'){
        document.title='Article';document.body.innerHTML='<article>Full text</article>';
      }
    });
    </script>'''


@pytest.mark.parametrize('control',[
    '<button id=send>Confirm</button>',
    '<button id=send type=button>Verify</button>',
    '<input id=send type=button value="Validate code">',
    '<div id=send role=button tabindex=0>Continue</div>',
    '<a id=send href="#" onclick="return false">Submit</a>',
    '<a id=send href="#">Verify</a>',
    '<span id=send tabindex=0>Confirm</span>',
    '<input id=send type=image alt="送信" width=40 height=20>',
    '<button id=send type=button aria-label="确认">✓</button>',
    '<span id=caption>Vérifier</span><button id=send type=button aria-labelledby=caption>✓</button>',
    '<button id=send type=button><span>Verify CAPTCHA →</span></button>',
])
def test_native_and_named_controls_really_submit_the_answer(page,monkeypatch,control):
    page.set_content(submission_page(control))
    ask=Mock(return_value='aB52');monkeypatch.setattr(solver,'solve_image',ask)
    assert continuation.resume(page,CONFIG,kind='image_code',
                               limits=continuation.Limits(time.monotonic()+10,solver.Budget(1)),
                               observation=Mock())
    assert page.title()=='Article'
    assert page.evaluate('window.clicked', **main_world(page))==['send']
    ask.assert_called_once()


@pytest.mark.parametrize('name',[
    'submit','VERIFY','Check answer','Confirm the code','Proceed','Next',
    '提交','验证','驗證','確認','继续','繼續','下一步','送信','検証','認証','続行',
    '확인','제출','계속','Valider','Continuer','Envoyer',
])
def test_common_labels_select_the_control(page,name):
    page.set_content(submission_page(f'<button id=send type=button>{name}</button>'))
    assert image_code.find(page)['submit']=='#send'


def test_only_controls_associated_with_the_answer_form_are_candidates(page):
    page.set_content(submission_page('<button id=send>Verify</button>',
                                    extra='<form id=unrelated><button id=other>Verify</button></form>'))
    assert image_code.find(page)['submit']=='#send'
    page.locator('#send').evaluate('el=>el.setAttribute("form","unrelated")')
    assert image_code.find(page) is None


def test_external_native_submit_uses_its_form_attribute(page):
    page.set_content(submission_page('',extra='<button id=send form=challenge>继续</button>'))
    assert image_code.find(page)['submit']=='#send'


def test_formless_widget_uses_its_shared_container(page,monkeypatch):
    page.set_content(submission_page('<div id=send role=button>Verify</div>',wrapper='section',
                                    extra='<button id=other type=button>Verify</button>'))
    monkeypatch.setattr(solver,'solve_image',Mock(return_value='aB52'))
    assert continuation.resume(page,CONFIG,kind='image_code',
                               limits=continuation.Limits(time.monotonic()+10,solver.Budget(1)),
                               observation=Mock())
    assert page.evaluate('window.clicked', **main_world(page))==['send']


@pytest.mark.parametrize('controls',[
    '<button id=send>Submit</button><button id=other type=button>Verify</button>',
    '<button id=send>Submit</button><button id=other disabled>Verify</button>',
    '<button id=other type=reset>Verify</button>',
    '<button id=other type=button>Refresh</button>',
    '<button id=other type=button>Cancel</button>',
    '<button id=other type=button>Verify account and pay</button>',
    '<a id=other href="/help">Verify</a>',
    '<div id=other>Verify</div>',
    '<input id=other type=checkbox tabindex=0 value=Verify>',
    '<div id=other contenteditable=true tabindex=0>Verify</div>',
])
def test_ambiguous_or_unrelated_controls_never_request_an_answer(page,monkeypatch,controls):
    page.set_content(submission_page(controls))
    ask=Mock();monkeypatch.setattr(solver,'solve_image',ask)
    assert not continuation.resume(page,CONFIG,kind='image_code',
                                   limits=continuation.Limits(time.monotonic()+5,solver.Budget(1)),
                                   observation=Mock())
    ask.assert_not_called()
    assert page.evaluate('window.clicked', **main_world(page))==[]


def test_filling_answer_enables_the_button_before_click(page,monkeypatch):
    page.set_content(submission_page('<button id=send disabled>Verify</button>')+'''
    <script>document.querySelector('#answer').oninput=()=>{
      setTimeout(()=>document.querySelector('#send').disabled=false,150);
    };</script>''')
    monkeypatch.setattr(solver,'solve_image',Mock(return_value='aB52'))
    assert continuation.resume(page,CONFIG,kind='image_code',
                               limits=continuation.Limits(time.monotonic()+10,solver.Budget(1)),
                               observation=Mock())
    assert page.evaluate('window.clicked', **main_world(page))==['send']


def test_new_ambiguity_after_filling_does_not_click(page,monkeypatch):
    page.set_content(submission_page('<button id=send>Submit</button>')+'''
    <script>document.querySelector('#answer').oninput=()=>{
      document.querySelector('#challenge').insertAdjacentHTML('beforeend',
        '<button id=other type=button>Verify</button>');
    };</script>''')
    monkeypatch.setattr(solver,'solve_image',Mock(return_value='aB52'))
    notes=[]
    assert not continuation.resume(page,CONFIG,kind='image_code',
                                   limits=continuation.Limits(time.monotonic()+10,solver.Budget(1)),
                                   observation=notes.append)
    assert page.evaluate('window.clicked', **main_world(page))==[]
    assert 'image_code: form changed after filling; stop' in notes
