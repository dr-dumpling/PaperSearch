"""Atypon (Literatum) journal sites: the institution login at ``/action/ssostart``.

A site type shared by publishers on the platform (Taylor & Francis, AHA
journals, Neurology); each publisher's adapter names its hosts. The article's
access box links to ``/action/ssostart`` with this article as ``redirectUri``
(or ``uri``); a site whose article page has no such link (NEJM: only its own
"SIGN IN", whose page leads to the chooser, 2026-11-03) gets the chooser's
address with this article as ``redirectUri``. A link with an ``idp`` parameter
goes straight to one identity provider (AHA's member login on ahajournals.org)
and is never used. The
chooser is either a federation dropdown (``#shib-search--fed``, Taylor &
Francis: CARSI is selected here, then the school) or only a search box
("Type the name of your institution", ahajournals.org and neurology.org,
2026-11-01), where the engine types and chooses the configured school.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from ....engine.fulltext_page import MATHJAX_SOURCES_JS
from ....engine.batch_common import _is_browser_error, open_page
from ...base import PublisherAdapter, SupplementLink, register

_ARTICLE = re.compile(r"/doi/(?:(?:abs|full|pdf|epdf|pdfdirect|reader)/)?(10\.\d{4,9}/[^?#]+)", re.I)
# Supplement files: /doi/suppl/<DOI>/suppl_file/<name>, with the link text.
_SUPPLEMENT_ROWS_JS = """() => [...document.querySelectorAll('a[href*="/doi/suppl/"]')].map(a => ({
    href: a.href, label: ((a.textContent || '').trim() || a.getAttribute('title') || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""
# The page's institution-login links, read at once: a link-by-link lookup waited
# 30 s on a page still navigating after a silent IdP return (ASCE, 2026-11-02).
_SSOSTART_LINKS_JS = """() => [...document.querySelectorAll('a[href*="/action/ssostart"]')].map(a => ({
    href: a.href, visible: a.getClientRects().length > 0 && getComputedStyle(a).visibility !== 'hidden'}))"""


# --fulltext on Atypon's current template: the body is section#bodymatter, a page without
# access shows .denial-block; each figure's image is the large one under /assets/images/
# (Science, NEJM and PNAS, pages saved after a school login, 2026-11-14). A publisher on
# this template names these once one of its pages is verified; Atypon's older template
# (Taylor & Francis: hlFld-Fulltext) has neither: its rules are CLASSIC_TEMPLATE_* below.
# A table's figure that holds the table itself gives no image: NEJM's figure.table has the
# table and a picture of it, the Markdown writes the table, and the picture was counted as
# a figure left out ("图片可能不全" on 6 NEJM pages, 2026-11-25).
CURRENT_TEMPLATE_FULLTEXT_SHOWN_JS = """() => (document.querySelector('section#bodymatter')?.innerText.length || 0) > 500
  && !document.querySelector('.denial-block')"""
CURRENT_TEMPLATE_FULLTEXT_IMAGES_JS = r"""() => [...document.querySelectorAll('figure img[data-open="viewer"], section#bodymatter figure img')]
  .filter((img) => !img.closest('figure')?.querySelector('table'))
  .map((img) => img.currentSrc || img.src)
  .filter((url) => /\/assets\/images\//.test(url))
  .map((url) => url.replace(/\/assets\/images\/(?:small|medium)\//, '/assets/images/large/'))"""


# --fulltext on Atypon's older template (Taylor & Francis, pages saved after a school login,
# 2026-11-14): the article is .hlFld-Fulltext, sent with the page (abstracts in
# .hlFld-Abstract; a page without access, or one whose full text is only the PDF, has
# none). A figure is div.figureView showing a small image (500 px); its full-size one
# (1500 px, another asset) is only in the figure viewer's data, an inline script
# "tandf.tfviewerdata={…}" read here as text (page globals are not seen from here), by the
# figure's data-id; the image shown when the data has none. The general sample rules
# found no image: there is no <figure> and no .figure. Tables are in that data too, and
# the references are in the page, so nothing is opened before saving. World Scientific
# (2026-11-15) has the same .hlFld-Fulltext with <figure> inside, the full-size image in
# the img's data-lg-src (the page shows a medium one); MathJax 2 keeps each formula's
# MathML source script, which the shared script also writes onto the formula.
CLASSIC_TEMPLATE_FULLTEXT_SHOWN_JS = """() => {
  const body = document.querySelector('.hlFld-Fulltext');
  if (!body) return false;
  const abstracts = [...body.querySelectorAll('.hlFld-Abstract')].reduce((sum, node) => sum + node.innerText.length, 0);
  return body.innerText.length - abstracts > 500;
}"""
CLASSIC_TEMPLATE_FULLTEXT_IMAGES_JS = r"""() => {
  const large = new Map();
  for (const script of document.querySelectorAll('script:not([src])')) {
    const text = script.textContent || '';
    const at = text.indexOf('tfviewerdata=');
    if (at < 0) continue;
    const start = text.indexOf('{', at);
    let depth = 0, inString = false, end = -1;
    for (let i = start; start >= 0 && i < text.length; i += 1) {
      const c = text[i];
      if (inString) {
        if (c === '\\') i += 1;
        else if (c === '"') inString = false;
      } else if (c === '"') inString = true;
      else if (c === '{') depth += 1;
      else if (c === '}' && --depth === 0) { end = i; break; }
    }
    let data = null;
    try {
      data = end > start ? JSON.parse(text.slice(start, end + 1)) : null;
    } catch (error) {
      data = null;  // not the data: each figure keeps the image it shows
    }
    for (const figure of data?.figures || []) {
      const img = new DOMParser().parseFromString(String(figure?.content || ''), 'text/html').querySelector('img[src]');
      if (figure?.id && img) large.set(figure.id, new URL(img.getAttribute('src'), location.href).href);
    }
    break;
  }
  const views = [...document.querySelectorAll('.hlFld-Fulltext .figureView')].map((view) => {
    const shown = view.querySelector('img.figure-image, img');
    return large.get(view.querySelector('[data-id]')?.getAttribute('data-id')) || (shown ? shown.currentSrc || shown.src : '');
  });
  const figures = [...document.querySelectorAll('.hlFld-Abstract figure img, .hlFld-Fulltext figure img')]
    .filter((img) => !img.closest('figcaption'))
    .map((img) => {
      const full = img.getAttribute('data-lg-src');
      return full ? new URL(full, location.href).href : img.currentSrc || img.src;
    });
  return [...views, ...figures].filter(Boolean);
}"""
# MathJax 4 keeps no MathML in the page (a Taylor & Francis page rendered in a browser had
# only mjx-container): the shared script writes each formula's source onto its element.
CLASSIC_TEMPLATE_FULLTEXT_PREPARE_JS = MATHJAX_SOURCES_JS


class AtyponAdapter(PublisherAdapter):
    """Shared rules of Atypon sites; subclasses set ``site_hosts`` (not ``hosts``: that selects a journal-level adapter)."""

    site_hosts: frozenset[str] = frozenset()
    entry_event = "atypon-institution-link"
    # Without access the PDF address (/doi/pdf/<DOI>) answers with the article's own page there: Taylor & Francis
    # (Scand J Rheumatol 2013, 10.3109, signed in, "Purchase options" on it) and NEJM Catalyst (10.1056/cat.24.0478,
    # "Welcome: <school>" and "Get Access" on it), each ended as pdf_not_captured (Windows, 2026-11-22 and -23).
    pdf_address_shows_article_page = True

    def _on_site(self, url: str) -> bool:
        parsed = urlparse(url or "")
        return parsed.scheme == "https" and (parsed.hostname or "").lower() in self.site_hosts

    def _chooser(self, url: str) -> bool:
        return self._on_site(url) and urlparse(url).path == "/action/ssostart"

    def is_article_page_url(self, url: str) -> bool | None:
        return self._on_site(url) and bool(_ARTICLE.match(urlparse(url).path))

    def is_institution_chooser(self, url: str) -> bool:
        return self._chooser(url)

    def is_login_landing(self, url: str) -> bool:
        """``/action/authenticateSharedSP``: Science's login came back here, a
        "LOG IN" page with the institution search, after the school was chosen
        with its sign-in still valid, and stayed; the article opened by itself
        then had its full text (Windows, 2026-11-16, the first paper of two batches).
        The site's home page too: PNAS's institution search sends the login back there
        (its entries carry ``redirectUri=/``), the school's sign-in still valid
        (2026-11-17)."""
        return self._on_site(url) and urlparse(url).path.lower() in ("/action/authenticatesharedsp", "/", "")

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        """Files under ``/doi/suppl/<this DOI>/suppl_file/``; a supplement link of
        another article on the page is not this article's. Follow the observed
        supplement landing page once when the article only links to that page.
        """
        landing_path = f"/doi/suppl/{doi.lower()}"
        for attempt in range(2):
            links, landing = self._listed_supplements(page, doi)
            if links or not landing or attempt:
                return links
            if unquote(urlparse(str(page.url)).path).lower().rstrip("/") == landing_path:
                return []
            open_page(page, landing, timeout_ms=30_000)
        return []

    def listed_supplement_links(self, page: Any, doi: str) -> list[SupplementLink]:
        """The files this page lists itself, read without leaving it."""
        return self._listed_supplements(page, doi)[0]

    def _listed_supplements(self, page: Any, doi: str) -> tuple[list[SupplementLink], str]:
        """``(files, landing page)`` linked from this page for this article."""
        landing_path = f"/doi/suppl/{doi.lower()}"
        links: list[SupplementLink] = []
        landing = ""
        rows = page.evaluate(_SUPPLEMENT_ROWS_JS)
        for row in rows if isinstance(rows, list) and doi else []:
            target = urlparse(str(row.get("href") or "") if isinstance(row, dict) else "")
            url = target._replace(fragment="").geturl()
            if not self._on_site(url):
                continue
            path = unquote(target.path).lower()
            if path.startswith(landing_path + "/suppl_file/"):
                if url not in {link.url for link in links}:
                    links.append(SupplementLink(url, str(row.get("label") or "")))
            elif path.rstrip("/") == landing_path:
                landing = landing or url
        return links, landing

    def institution_chooser_open(self, page: Any) -> bool:
        return self._chooser(str(getattr(page, "url", "") or "")) and page.locator("select#shib-search--fed").is_visible()

    def institution_link(self, page: Any, doi: str) -> str:
        """The access box's institution login: the chooser with this article as
        its redirect, shown to a reader without access; never a link to one IdP."""
        try:
            links = page.evaluate(_SSOSTART_LINKS_JS)
        except Exception as exc:
            if not _is_browser_error(exc):
                raise
            return ""
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict):
                continue
            target = urlparse(urljoin(str(page.url), str(link.get("href") or "")))
            query = parse_qs(target.query)
            redirect = unquote((query.get("redirectUri") or query.get("uri") or [""])[0]).lower()
            if (doi and self._chooser(target.geturl()) and "idp" not in query
                    and doi.lower() in redirect and link.get("visible")):
                return target.geturl()
        return ""

    def chooser_url(self, url: str) -> str:
        """The platform's institution chooser for the article at ``url``, with it
        as ``redirectUri``; "" off an article page of this site."""
        if not self.is_article_page_url(url):
            return ""
        parsed = urlparse(url)
        return f"https://{parsed.hostname}/action/ssostart?redirectUri={quote(parsed.path, safe='')}"

    def looks_logged_out(self, page: Any, url: str, text: str) -> bool | None:
        """The access box's institution login for this article: Atypon shows it
        only to readers without access, with no offer text the shared rule knows
        (Medical Teacher, 2026-11-01). An open article shows it too (NXI,
        2026-11-01), but its open-access icon has answered before this is asked."""
        match = _ARTICLE.match(urlparse(url or "").path) if self.is_article_page_url(url) else None
        if not match:
            return None
        return True if self.institution_link(page, unquote(match.group(1))) else None

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        # On the chooser the school is chosen there; no other entry is clicked.
        if self._chooser(str(getattr(page, "url", "") or "")):
            return False
        d = self.d
        # The access box's link, else the chooser's address: the same page (NEJM).
        target = ((self.institution_link(page, result.doi) or self.chooser_url(str(getattr(page, "url", "") or "")))
                  if result is not None else "")
        if not target or (d.federation is not None and not d._manual_institution_target_allowed(target)):
            return None
        # Opened, not clicked: a click soon after the article loaded left the
        # page on the article (Neurological Research, cold start 2026-11-01, twice).
        open_page(page, target, timeout_ms=30_000)
        d._event(result, "sso_entry_clicked", self.entry_event)
        return True

    def choose_institution(self, page: Any, result: Any) -> bool | None:
        d = self.d
        if not self._chooser(str(getattr(page, "url", "") or "")):
            return False
        ours = d.federation
        chooser = page.locator("select#shib-search--fed")
        if ours is None or not chooser.is_visible():
            return None  # a search box only: the engine chooses the school there
        # The school's federation as this list names it (the federation layer).
        label = ours.option_among(" ".join(text.split()) for text in chooser.locator("option").all_text_contents())
        if label is None:
            return None  # not listed: the engine's federation-list rule reports it
        changed = " ".join(chooser.locator("option:checked").inner_text().split()) != label
        if changed:
            # Changed by the user only on the very page where the federation was chosen; a
            # chooser reloaded with its first federation is chosen again (the
            # engine's one rule, review 2026-11-02).
            here = d._federation_choice_page(page, result)
            if here is None:
                return False
            chooser.select_option(label=label, timeout=5_000)
            d._federation_chosen(result, here, ours.code)
        # The federation is set here; the configured school is then chosen in
        # the school list by the engine's assistance (2026-11-01: the configured
        # school was chosen automatically), else by the user.
        if not any(event["state"] == "institution_selection_required" for event in result.events):
            d._event(result, "institution_selection_required", ours.code)
        return changed
