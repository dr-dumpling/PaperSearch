"""A standalone character challenge: capture only the code, fill one field.

Geometry and form structure, not publisher domains, identify the code. Visible
password/email fields and article metadata exclude login/article pages. No
hidden fields, cookies, DOM text answers or full-page images leave the browser.
"""
from __future__ import annotations

from typing import Any

from ...driver import Error
from ..services import solver
from ..local import submission

_FIND = r'''() => {
 const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
 const text = (document.body?.innerText || '').trim();
 if (text.length > 2500 || document.querySelector('meta[name="citation_doi"]') ||
     [...document.querySelectorAll('input[type=password],input[type=email]')].some(shown)) return null;
 if (!/captcha|not a robot|letters.{0,20}numbers|验证码/i.test(document.title+' '+text)) return null;
 const fields = [...document.querySelectorAll('input[type=text],input:not([type])')].filter(el=>shown(el)&&!el.disabled);
 if(fields.length!==1) return null;
 const field=fields[0], f=field.getBoundingClientRect();
 const pictures=[...document.querySelectorAll('img,canvas,.puzzle,[class*=captcha-image],[id*=captchaImage]')]
  .filter(shown).map(el=>({el,r:el.getBoundingClientRect()}))
  .filter(({r})=>r.width>=25 && r.width<=600 && r.height>=15 && r.height<=200 &&
      r.bottom<=f.top+5 && f.top-r.bottom<=160 && r.left<f.right && r.right>f.left)
  .sort((a,b)=>(f.top-a.r.bottom)-(f.top-b.r.bottom));
 if(!pictures.length || (pictures.length>1 && Math.abs(pictures[0].r.bottom-pictures[1].r.bottom)<5))return null;
 const picture=pictures[0].el;
 let scope=field.form;
 if(!scope){
   scope=field.parentElement;
   while(scope && !scope.contains(picture))scope=scope.parentElement;
   if(!scope || scope===document.body || scope===document.documentElement)return null;
 }
 const submits = (''' + submission.CANDIDATES + r''')(field.form, scope);
 // Disabled controls still count: filling the answer may enable them. Click waits
 // for actionability; multiple possible submits never become a guessed action.
 if(submits.length!==1)return null;
 const selector=el=>el.id ? '#'+CSS.escape(el.id) : (()=>{
   const parts=[];while(el && el!==document.documentElement){
    const tag=el.tagName.toLowerCase();const siblings=[...el.parentElement.children].filter(e=>e.tagName===el.tagName);
    parts.unshift(tag+':nth-of-type('+(siblings.indexOf(el)+1)+')');el=el.parentElement;
   }return 'html > '+parts.join(' > ');
 })();
 return {picture:selector(picture),field:selector(field),submit:selector(submits[0])};
}'''


def find(page: Any) -> dict | None:
    try:
        value = page.evaluate(_FIND)
        if isinstance(value, dict) and all(isinstance(value.get(k), str) for k in ('picture', 'field', 'submit')):
            return value
    except Error:
        pass  # the outer verification loop rechecks navigation
    return None


def solve(page: Any, config: dict, *, limits: Any, observation: Any) -> bool:
    note = observation
    try:
        for attempt in range(1, 4):
            limits.remaining()
            controls = find(page)
            if not controls:
                note('image_code: no unambiguous standalone code form')
                return False
            picture = page.locator(controls['picture'])
            image = picture.screenshot(scale='css', timeout=min(2000, int(limits.remaining()*1000)))
            if not limits.budget.take():
                note('service budget exhausted')
                return False
            answer = solver.solve_image(image, config, timeout=min(limits.remaining(), float(config.get('captcha_timeout', 90))),
                                        checkpoint=limits.remaining)
            limits.remaining()
            if not answer or len(answer)>64 or not answer.isalnum():
                note('image_code: service failed or invalid text')
                return False
            if controls != find(page) or image != picture.screenshot(scale='css', timeout=min(2000, int(limits.remaining()*1000))):
                note('image_code: code changed; discard answer')
                continue
            page.locator(controls['field']).fill(answer, timeout=min(2000, int(limits.remaining()*1000)))
            limits.remaining()
            if controls != find(page):
                note('image_code: form changed after filling; stop')
                return False
            page.locator(controls['submit']).click(timeout=min(2000, int(limits.remaining()*1000)), no_wait_after=True)
            note(f'image_code: submitted; attempt {attempt}/3')
            limits.sleep(2)
            if not find(page):
                return True  # outer loop checks the resulting page, never assume pass here
        note('image_code: three attempts exhausted')
        return False
    except Error as exc:
        if any(text in str(exc).lower() for text in ('frame was detached','execution context was destroyed')):
            return True
        note(f'image_code: browser interaction failed ({type(exc).__name__})')
        return False
