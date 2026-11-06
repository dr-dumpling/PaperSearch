"""IEEE Xplore (ieeexplore.ieee.org): the institution login is a modal on the article.

"Institutional Sign In" (``a.inst-sign-in``, a ``javascript:`` link the
generic entry rule does not follow) opens it. The modal may first offer
SeamlessAccess's "Access Through Your Institution"; then it shows the
institution search (``input.inst-typeahead-input``), where the engine types
the configured school and picks its single entry (cold start, 2026-11-01).
Ported from the old CARSI route's IEEE assist when IEEE moved to the
publisher route.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from ...engine.batch_common import pump_until, settle
from ...engine.router import extract_ieee_article_number
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENTS_JS = r"""() => {
  let metadata = window.xplGlobal?.document?.metadata;
  // Camoufox's isolated evaluation world may not expose page globals. Read
  // the same JSON declaration from the DOM without executing website code.
  if (!metadata) {
    for (const script of document.scripts) {
      const text = script.textContent || '';
      if (text.length > 1048576) continue;
      const match = text.match(/xplGlobal\.document\.metadata\s*=\s*(\{[\s\S]*?\})\s*;/);
      if (!match) continue;
      try { metadata = JSON.parse(match[1]); }
      catch (error) { if (!(error instanceof SyntaxError)) throw error; }
      break;
    }
  }
  return {
    article: metadata?.articleNumber,
    doi: metadata?.doi,
    multimedia: metadata?.sections?.multimedia,
    tabs: [...document.querySelectorAll('a.document-tab-link[href]')].map(a => a.href),
    dois: [...document.querySelectorAll('a.multimedia-doi[href]')].map(a => a.href),
    rows: [...document.querySelectorAll('.media-item a[href]')].map(a => ({
        href:a.href, label:(a.textContent || '').trim().slice(0,240)
    }))
  };
}"""


def supplement_links_from_page(data: dict, page_url: str, doi: str) -> list[SupplementLink] | None:
    current = urlparse(page_url)
    main_article = re.fullmatch(r"/document/(\d+)/?", current.path)
    if (current.scheme == "https" and current.netloc == "ieeexplore.ieee.org" and main_article
            and str(data.get("article") or "") == main_article[1]
            and str(data.get("doi") or "").casefold() == doi.casefold()
            and (data.get("multimedia") is False or data.get("multimedia") == "false")
            and not data.get("rows") and not data.get("dois")
            and not any(urlparse(urljoin(page_url, str(tab))).path.rstrip("/")
                        == f"/document/{main_article[1]}/media" for tab in data.get("tabs", []))):
        # IEEE explicitly declares the sections of this identified article.
        # Missing tabs or an unfinished app shell alone are not empty evidence.
        return []
    article = re.fullmatch(r"/document/(\d+)/media/?", current.path)
    if (current.scheme != "https" or current.netloc != "ieeexplore.ieee.org" or not article
            or not any(re.fullmatch(r"https://doi\.org/" + re.escape(doi) + r"/mm\d+", url, re.I)
                       for url in data.get("dois", []))):
        return None
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        if (target.scheme != "https" or target.netloc != current.netloc
                or not re.fullmatch(r"/ielx\d+/\d+/\d+/" + article[1] + r"/[^/]+", target.path)):
            continue
        url = target._replace(fragment="").geturl()
        if url not in seen:
            seen.add(url)
            links.append(SupplementLink(url, str(row.get("label") or "")))
    return links

_SEARCH = "input.inst-typeahead-input"
# Text on an article page that offers the institution login.
_ENTRY_MARKERS = (
    "you do not have access to this pdf",
    "sign in to continue reading",
    "institutional sign in",
    "access through your institution",
    "search for your institution",
)
# The first visible control naming one of the institution logins, in this order.
_ENTRY_CONTROL_JS = """
                () => {
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
                  ].join(' ').replace(/\\s+/g, ' ').trim();
                  const controls = [...document.querySelectorAll('button,a,[role="button"],input[type="button"],input[type="submit"]')]
                    .filter(visible);
                  const wanted = [
                    'access through your institution',
                    'institutional sign in',
                    'institutional login'
                  ];
                  for (const marker of wanted) {
                    const target = controls.find((el) => textOf(el).toLowerCase().includes(marker));
                    if (!target) continue;
                    const detail = {
                      text: textOf(target).slice(0, 200),
                      href: (target.href || target.getAttribute('href') || '').slice(0, 300)
                    };
                    target.click();
                    return detail;
                  }
                  return null;
                }
                """
_SEARCH_INPUTS = (
    "input[aria-label='Search for your Institution']",
    "input[aria-label*='Institution']",
    "input.inst-typeahead-input",
    "xpath=(//*[normalize-space()='Search for your Institution']/following::input[1])",
)


@register
class IEEEAdapter(PublisherAdapter):
    publisher = "ieee"

    def is_article_page_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return (parsed.scheme == "https" and parsed.netloc == "ieeexplore.ieee.org"
                and re.fullmatch(r"/document/\d+/?", parsed.path) is not None)

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """Open the article's observed Supplemental Items tab before discovery."""
        current = urlparse(str(page.url))
        article = re.fullmatch(r"/document/(\d+)/?", current.path)
        if current.scheme == "https" and current.netloc == "ieeexplore.ieee.org" and article:
            for control in page.locator('a.document-tab-link[href]').all():
                href = urljoin(str(page.url), control.get_attribute('href') or '')
                target = urlparse(href)
                if (target.scheme == "https" and target.netloc == current.netloc
                        and target.path == f"/document/{article[1]}/media"):
                    # This is a client-side document tab; a fresh navigation can
                    # return a blank shell instead of rendering its media panel.
                    # Native activation reaches the same client-side router
                    # without waiting for animation-frame stability in a
                    # background tab. Never activate a hidden/disabled tab.
                    activated = control.evaluate("""el => {
                        if (!el.getClientRects().length || getComputedStyle(el).visibility !== 'visible'
                                || el.getAttribute('aria-disabled') === 'true') return false;
                        el.click(); return true;
                    }""", timeout=5_000)
                    if not activated:
                        continue
                    pump_until(page, lambda: page.evaluate("""doi =>
                        [...document.querySelectorAll('a[href]')].some(a =>
                            a.href.toLowerCase().startsWith('https://doi.org/' + doi.toLowerCase() + '/mm'))
                        """, doi), 15_000)
                    break
        return supplement_links_from_page(page.evaluate(_SUPPLEMENTS_JS), str(page.url), doi)

    def login_url(self) -> str | None:
        return "https://ieeexplore.ieee.org/"

    @classmethod
    def profile_pdf_candidates(cls, doi: str, source_url: str) -> list[str]:
        arnumber = extract_ieee_article_number(source_url)
        if not arnumber:
            return []
        return [f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&isnumber=&arnumber={arnumber}",
                f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}"]

    def login_block_reason(self, page: Any, text: str) -> str | None:
        """IEEE Xplore's own outage page: the login cannot go on (moved from the engine, review 2026-11-02)."""
        if ("ieee xplore is temporarily unavailable" in text
                or ("temporarily unavailable" in text and "onlinesupport@ieee.org" in text)):
            return "publisher_temporarily_unavailable"
        return None

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        if (urlparse(str(getattr(page, "url", "") or "")).hostname or "") != "ieeexplore.ieee.org":
            return None
        search = page.locator(_SEARCH).first
        if search.is_visible():
            return False  # the modal is open: the school is chosen there
        for dialog in page.get_by_role("dialog").filter(
                has_text=re.compile(r"institutional sign in|access through", re.I)).all():
            if dialog.is_visible():
                # PDF can open this modal before the login flow starts. It may
                # show only a remembered school, with no search input yet.
                return False
        entry = page.locator("a.inst-sign-in").first
        if not entry.is_visible():
            return None
        entry.click(timeout=5_000)
        self.d._event(result, "sso_entry_clicked", "ieee-institutional-sign-in")
        seamless = page.get_by_role("button", name="Access Through Your Institution").first
        pump_until(page, lambda: search.is_visible() or seamless.is_visible(), 5_000)
        if not search.is_visible() and seamless.is_visible():
            seamless.click(timeout=5_000)
            pump_until(page, search.is_visible, 5_000)
        return True

    def click_institution_control(self, page: Any, result: Any) -> bool:
        """A visible control naming the institution login, on an article page
        that offers it (the IEEE login page itself, /servlet/wayf, is not one)."""
        d = self.d
        current_url = str(getattr(page, "url", "") or "")
        if "ieeexplore.ieee.org/servlet/wayf" in current_url.lower():
            return False
        if "ieeexplore.ieee.org" not in current_url.lower():
            return False
        text = d._body_text(page, 5_000).lower()
        if not any(marker in text for marker in _ENTRY_MARKERS):
            return False
        try:
            clicked = page.evaluate(_ENTRY_CONTROL_JS)
            if not clicked:
                return False
            if result is not None:
                d._event(result, "sso_entry_clicked", json.dumps(clicked, ensure_ascii=False))
            return True
        except Exception as exc:
            if result is not None:
                d._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
        return False

    def fill_institution_search(self, page: Any, result: Any) -> bool:
        """Type the configured school into the modal's institution search and
        choose the entry that names it."""
        d = self.d
        input_box = None
        input_selector = ""
        for selector in _SEARCH_INPUTS:
            try:
                candidate = page.locator(selector).first
                if candidate.is_visible(timeout=1_500):
                    input_box = candidate
                    input_selector = selector
                    break
            except Exception:
                continue
        if input_box is None:
            return False
        try:
            input_box.fill("")
            try:
                input_box.type(d.institution_query, timeout=5_000)
            except Exception:
                input_box.fill(d.institution_query)
            d._event(result, "institution_search", input_selector)
            settle(page, 2_000)
        except Exception as exc:
            d._event(result, "institution_select_error", f"{type(exc).__name__}: {exc}")
            return False

        for selector in d._institution_result_selectors():
            try:
                option = page.locator(selector).first
                if option.is_visible(timeout=2_000):
                    option.click(timeout=5_000, no_wait_after=True)
                    d._event(result, "institution_selected", selector)
                    return True
            except Exception:
                continue
        if d.config.get("publisher_institution_federation") == "carsi":
            return False  # no text match: never pick the first suggestion for the user
        try:
            input_box.press("ArrowDown", timeout=2_000)
            input_box.press("Enter", timeout=2_000)
            d._event(result, "institution_selected", "IEEE typeahead ArrowDown+Enter")
            return True
        except Exception as exc:
            d._event(result, "institution_select_error", f"{type(exc).__name__}: {exc}")
            return False
