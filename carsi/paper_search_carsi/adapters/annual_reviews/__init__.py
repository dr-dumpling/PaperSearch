"""Annual Reviews: journals on annualreviews.org.

Outside CARSI its institution login is on its own pages: ``/session/ext/shib``
(Shibboleth) and ``/session/ext/athens`` ("Option 2: Sign-in with OpenAthens").
The OpenAthens page is taken: from the Shibboleth page its address is opened
with the configured school as the search (``openathens_entry``), and there the
school is typed into the organisation search and chosen
(``fill_institution_search``). Moved from the engine (review 2026-11-02); the
steps are as before, and a browser error on them is recorded instead of passed
over in silence.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from ...engine.batch_common import _is_browser_error, open_page, pump_until
from ..base import PublisherAdapter, register

_OPENATHENS_BOX = ("xpath=(//*[contains(normalize-space(.), 'Option 2: Sign-in with OpenAthens')]"
                   "/following::input[contains(@placeholder, 'organization')])[1]")
# The page's own controls, by their words: the school's result, "Go To Sign-in",
# else the organisation search and "Find Your Organization".
_OPENATHENS_STEP_JS = """
                (query) => {
                  const needle = (query || '').toLowerCase();
                  if (!needle) return null;
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const textOf = (el) => [
                    el.innerText || '',
                    el.textContent || '',
                    el.value || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || ''
                  ].join(' ').trim();
                  const controls = [...document.querySelectorAll('a,button,input[type="button"],input[type="submit"]')].filter(visible);
                  const goButtons = controls.filter((el) => textOf(el).toLowerCase().includes('go to sign-in'));
                  const resultEls = [...document.querySelectorAll('a,button,li,div,span,option')]
                    .filter(visible)
                    .filter((el) => textOf(el).toLowerCase().includes(needle));
                  if (resultEls.length) {
                    resultEls[resultEls.length - 1].click();
                    if (goButtons.length) {
                      goButtons[goButtons.length - 1].click();
                      return {action: 'openathens_go', result: textOf(resultEls[resultEls.length - 1]).slice(0, 160)};
                    }
                    return {action: 'openathens_result', result: textOf(resultEls[resultEls.length - 1]).slice(0, 160)};
                  }
                  const inputs = [...document.querySelectorAll('input')]
                    .filter(visible)
                    .filter((el) => {
                      const haystack = [el.placeholder || '', el.name || '', el.id || '', el.getAttribute('aria-label') || ''].join(' ').toLowerCase();
                      return haystack.includes('organization') || haystack.includes('institution');
                    });
                  if (inputs.length) {
                    const input = inputs[inputs.length - 1];
                    input.focus();
                    input.value = query;
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    const findButtons = controls.filter((el) => textOf(el).toLowerCase().includes('find your organization'));
                    if (findButtons.length) {
                      findButtons[findButtons.length - 1].click();
                    }
                    return {action: 'openathens_search', query};
                  }
                  if (goButtons.length) {
                    goButtons[goButtons.length - 1].click();
                    return {action: 'openathens_go'};
                  }
                  return null;
                }
                """


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"


@register
class AnnualReviewsAdapter(PublisherAdapter):
    publisher = "annual reviews"

    def openathens_entry(self, page: Any, result: Any) -> bool | None:
        """From the Shibboleth page, its OpenAthens page with the school as the
        search; on the OpenAthens page nothing more (the school is chosen there)."""
        d = self.d
        parsed = urlparse(str(getattr(page, "url", "") or ""))
        if not parsed.netloc.endswith("annualreviews.org"):
            return None
        path = parsed.path.lower()
        if path.startswith("/session/ext/athens"):
            return False
        if not path.startswith("/session/ext/shib"):
            return None
        target_url = parse_qs(parsed.query).get("url", ["/"])[0] or "/"
        openathens_url = (f"{parsed.scheme or 'https'}://{parsed.netloc}/session/ext/athens?"
                          f"{urlencode({'url': target_url, 'athensWayfSearch': d.institution_query})}")
        try:
            open_page(page, openathens_url, timeout_ms=30_000)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            d._event(result, "openathens_entry_error", _error(exc))
            return False
        d._event(result, "openathens_entry", openathens_url)
        return True

    def fill_institution_search(self, page: Any, result: Any) -> bool:
        """On the OpenAthens page: the school in "Option 2"'s organisation search,
        its result, then "Go To Sign-in"; else the page's own controls by their words."""
        d = self.d
        if "annualreviews.org/session/ext/athens" not in str(getattr(page, "url", "") or "").lower():
            return False
        try:
            input_box = page.locator(_OPENATHENS_BOX).first
            if input_box.is_visible(timeout=1_500):
                input_box.fill(d.institution_query)
                page.locator("text=Find Your Organization").last.click(timeout=5_000, no_wait_after=True)
                d._event(result, "institution_search", f"OpenAthens: {d.institution_query}")
                pump_until(page, lambda: d._any_visible(page, d._institution_result_selectors()), 2_000)
                for selector in d._institution_result_selectors():
                    try:
                        option = page.locator(selector).last
                        if option.is_visible(timeout=1_500):
                            option.click(timeout=5_000, no_wait_after=True)
                            page.locator("text=Go To Sign-in").last.click(timeout=5_000, no_wait_after=True)
                            d._event(result, "institution_selected", selector)
                            break
                    except Exception as exc:
                        if not _is_browser_error(exc):
                            raise
                        continue  # the next result selector
                return True
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            d._event(result, "institution_search_error", f"OpenAthens organisation search: {_error(exc)}")
        try:
            action = page.evaluate(_OPENATHENS_STEP_JS, d.institution_query)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            d._event(result, "institution_select_error", _error(exc))
            return False
        if action:
            d._event(result, "institution_selected", json.dumps(action, ensure_ascii=False))
            return True
        return False
