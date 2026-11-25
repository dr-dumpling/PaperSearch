"""Standalone Turnstile tokens delivered to the original widget and its form."""
from __future__ import annotations

import ipaddress
import re
from contextlib import ExitStack
from typing import Any
from urllib.parse import urlsplit

from ...driver import Error, main_world
from ...watchdog import CallAbandoned, call_limit
from ..local import submission
from ..services import solver


_INSPECT = r'''(empty = true) => {
 const shown = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
 if ((document.body?.innerText || '').length > 2500 || window._cf_chl_opt ||
     /__cf_chl|\/cdn-cgi\/challenge-platform\//i.test(location.href) ||
     /^(just a moment|请稍候|attention required|checking your browser)/i.test(document.title) ||
     document.querySelector('#challenge-form,#challenge-stage,meta[name="citation_doi"],meta[name="citation_title"]') ||
     [...document.querySelectorAll('input[type=password],input[type=email]')].some(shown)) return null;
 const widgets = [...document.querySelectorAll('.cf-turnstile[data-sitekey]')].filter(shown);
 if (widgets.length !== 1) return null;
 const widget = widgets[0], sitekey = widget.dataset.sitekey || '', action = widget.dataset.action || '';
 if (!/^0x[A-Za-z0-9_-]{10,100}$/.test(sitekey) || (action && !/^[A-Za-z0-9_-]{1,32}$/.test(action)) ||
     widget.dataset.cdata || widget.dataset.chlPageData) return null;
 const name = widget.dataset.responseFieldName || 'cf-turnstile-response';
 const fields = [...widget.querySelectorAll('input,textarea')].filter(el=>el.name===name);
 if (fields.length > 1) return null;
 const field = fields[0] || null;
 if (field && (field.disabled || (empty && field.value))) return null;
 let callback = null, owner = window;
 const path = widget.dataset.callback || '';
 if (path) {
   if (!/^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$/.test(path)) return null;
   const parts = path.split('.');
   for (const part of parts.slice(0,-1)) { owner=owner?.[part]; if(!owner)return null; }
   callback=owner[parts.at(-1)];
   if (typeof callback !== 'function') return null;
 }
 const form = field?.form || widget.closest('form');
 if (form && [...form.querySelectorAll('input,textarea,select,[contenteditable=true]')]
      .some(el=>el!==field && shown(el) && !['hidden','submit','image','button','reset'].includes(el.type))) return null;
 const buttons = form ? (''' + submission.CANDIDATES + r''')(form,form) : [];
 if (buttons.length > 1 || (!callback && (!field || buttons.length !== 1))) return null;
 const events = window[Symbol.for('papersearch.turnstile.events')] || [];
 return {widget,field,form,submit:buttons[0] || null,callback,owner,
   frames:[...widget.querySelectorAll('iframe')],
   meta:{sitekey,action,name,path,url:location.href,
     frames:[...widget.querySelectorAll('iframe')].map(el=>el.src),
     revision:events.length ? [events.length,events.at(-1).event,events.at(-1).at] : null}};
}'''

_CURRENT = r'''old => {
 const now = (''' + _INSPECT + r''')(false);
 return !!now && ['widget','field','form','submit','callback','owner'].every(k=>now[k]===old[k]) &&
   now.frames.length===old.frames.length && now.frames.every((frame,i)=>frame===old.frames[i]) &&
   JSON.stringify(now.meta)===JSON.stringify(old.meta);
}'''


def public_origin(url: str) -> str:
    """Drop paths and queries, which can contain publisher or school sessions."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username or parsed.password or "." not in host
                or host.endswith((".localhost", ".local", ".internal"))):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass  # a DNS name
        return f"https://{parsed.netloc}/"
    except ValueError:
        return ""


def _user_agent(page: Any, origin: str, agent: str, cleanup: ExitStack, note: Any = None) -> None:
    """Use the service UA on this page's origin requests until the wait ends."""
    pattern = re.compile("^" + re.escape(origin))

    def forward(route: Any) -> None:
        route.fallback(headers={**route.request.headers, "user-agent": agent})

    page.route(pattern, forward)

    def release() -> None:
        try:
            if not page.is_closed():
                page.unroute(pattern, forward)
        except Error:
            if note:
                note('turnstile: browser unavailable during request-route cleanup')

    cleanup.callback(release)


def _apply(page: Any, snapshot: Any, token: str, limits: Any, note: Any) -> bool:
    limits.remaining()
    if not snapshot.evaluate(_CURRENT, **main_world(snapshot)):
        note('turnstile: widget changed; discard answer')
        return False
    applied = snapshot.evaluate(r'''(s,token) => {
      if (s.field?.value) return false;
      if (s.field) {
        const prototype = s.field.tagName==='TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(prototype,'value').set.call(s.field,token);
        s.field.dispatchEvent(new Event('input',{bubbles:true}));
        s.field.dispatchEvent(new Event('change',{bubbles:true}));
      }
      if (s.callback) Reflect.apply(s.callback,s.owner,[token]);
      return true;
    }''', token, **main_world(snapshot))
    if not applied:
        note('turnstile: local answer already present; discard service answer')
        return False
    note('turnstile: response delivered; awaiting page verification')
    limits.remaining()
    if snapshot.evaluate(_CURRENT, **main_world(snapshot)):
        control = snapshot.get_property('submit').as_element()
        if control is not None:
            control.click(timeout=min(3000, int(limits.remaining()*1000)), no_wait_after=True)
            note('turnstile: form submitted; awaiting page verification')
    return True


def solve(page: Any, config: dict, *, limits: Any, observation: Any) -> bool:
    """Delivery requests another outer page check; it never proves access."""
    note = observation
    origin = public_origin(str(page.url or ""))
    if not origin:
        note('turnstile: no public HTTPS origin')
        return False
    snapshot = None
    with ExitStack() as owned:
        cleanup = limits.cleanup if limits.cleanup is not None else owned
        try:
            with call_limit(min(5, limits.remaining())):
                snapshot = page.evaluate_handle(_INSPECT, True, **main_world(page))
                metadata = snapshot.evaluate('s=>s?.meta || null', **main_world(snapshot))
            if not metadata:
                note('turnstile: unsupported or ambiguous widget/continuation')
                return False
            if not limits.budget.take():
                note('service budget exhausted')
                return False
            answer = solver.solve_turnstile(origin, metadata['sitekey'], config,
                                            action=metadata['action'], timeout=limits.remaining(),
                                            checkpoint=limits.remaining)
            limits.remaining()
            if answer is None:
                note('turnstile: service did not return a valid token and User-Agent')
                return False
            _user_agent(page, origin, answer.user_agent, cleanup, note)
            with call_limit(min(5, limits.remaining())):
                delivered = _apply(page, snapshot, answer.token, limits, note)
            if delivered:
                page.wait_for_timeout(min(250, int(limits.remaining()*1000)))
            return delivered
        except CallAbandoned:
            note('turnstile: browser call timed out; recheck page')
            return False
        except Error:
            note('turnstile: page changed or action failed; recheck page')
            return False
        finally:
            if snapshot is not None:
                try:
                    snapshot.dispose()
                except Error:
                    pass  # navigation can destroy the original execution context
