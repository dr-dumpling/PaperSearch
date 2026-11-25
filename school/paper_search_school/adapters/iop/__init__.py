"""IOP Publishing: journals on iopscience.iop.org.

Without access the article page offers "Access this article" or "Access
through your institution". The institution login starts at myIOPscience's
sign-in (``myiopscience.iop.org/signin``) with the article as its target: with
``origin=deeplink`` it leads to OpenAthens' institution finder (without it, to
the personal account sign-in only).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlencode, urlparse

from ...engine.batch_common import open_page
from ..base import PublisherAdapter, SupplementLink, register

_SUPPLEMENT_ROWS_JS = """() => ({
    status: performance.getEntriesByType('navigation')[0]?.responseStatus || 0,
    doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
    rows: [...document.querySelectorAll('a[href]')].map(a => ({
        href: a.href, label: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240)
    }))
})"""


def supplement_links_from_page(data: dict, page_url: str, doi: str) -> list[SupplementLink] | None:
    """Files declared by this article's dedicated supplementary-data page.

    IOP's current file host uses signed URLs without a full DOI in the path.
    Bind the list to the article page and keep the signature for the transfer.
    An article without supplementary data has no such page (404, "Page Not
    Found") and no "Supplementary data" link on its own page (2026-11-07).
    """
    page = urlparse(page_url)
    citation = str(data.get("doi") or "").lower().removeprefix("https://doi.org/")
    if (page.scheme != "https" or page.netloc != "iopscience.iop.org"
            or unquote(page.path).rstrip("/").lower() != f"/article/{doi.lower()}/data"):
        return None
    if not citation and data.get("status") == 404:
        return []
    if citation != doi.lower():
        return None
    links: list[SupplementLink] = []
    seen: set[str] = set()
    for row in data.get("rows", []):
        target = urlparse(str(row.get("href") or ""))
        label = str(row.get("label") or "")
        if (target.scheme == "https"
                and target.netloc == "cfn-live-content-bucket-iop-org.s3.eu-west-1.amazonaws.com"
                and target.path.startswith("/journals/")
                and "supplement" in label.lower() and target.path not in seen):
            seen.add(target.path)
            links.append(SupplementLink(target._replace(fragment="").geturl(), label))
    return links


# --fulltext (PaperSearch's sites/templates/iop.ts). The full text is
# div.wd-jnl-art-full-text; a page without it shows the abstract (an accepted manuscript)
# or, without access, the "Access this article" panel. A figure (figure.boxout around a
# second <figure>) links its high-resolution image (a.fig-dwnld-hi-img, _hr.jpg) beside the
# standard one it shows (_lr.jpg): the high-resolution link is taken, else the standard
# one, else the <img>, as the converter does. Formulas keep their TeX in MathJax's scripts
# (MathJax is off by default; the page shows GIFs), so MATHJAX_SOURCES_JS is not needed
# (10.1088/1367-2630/aea700, open access, saved by the backend, 2026-11-15).
FULLTEXT_SHOWN_JS = """() => {
  const body = document.querySelector('div.wd-jnl-art-full-text');
  if (!body) return false;
  const text = [...body.querySelectorAll('p')].reduce((total, p) => total + (p.textContent || '').length, 0);
  return text > 500;
}"""
FULLTEXT_IMAGES_JS = """() => {
  const body = document.querySelector('div.wd-jnl-art-full-text');
  if (!body) return [];
  return [...body.querySelectorAll('figure')]
    .filter((figure) => !figure.parentElement?.closest('figure'))
    .flatMap((figure) => {
      const links = (name) => [...figure.querySelectorAll(`a.${name}`)].map((a) => a.getAttribute('href') || '');
      const shown = [...figure.querySelectorAll('img')]
        .filter((img) => !img.closest('figcaption, .texImage, .inline-eqn'))
        .map((img) => img.getAttribute('data-src') || img.getAttribute('src') || '');
      return [links('fig-dwnld-hi-img'), links('fig-dwnld-std-img'), shown]
        .map((list) => list.filter((src) => src && !/^(data|javascript):/i.test(src)))
        .find((list) => list.length) || [];
    })
    .map((src) => new URL(src, location.href).href);
}"""
# The page does not hold the references: its closed "Show References" panel
# (#references-wrapper) fetches them from /references/article/<DOI> when opened (the
# site's article.scripts.min.js, 4.45.0). Before the page is read the same list is fetched
# from the article page (same origin, the session's cookies, 8 s; the page read has 50 s,
# batch_capture.FULLTEXT_READ_SEC) and put into the panel, marked
# data-papersearch-references, when it is the list (its [data-toolbar-content=references]
# or li[data-reference]; not a challenge or an error page). Without it the converter
# writes the references from the page's citation_reference tags.
FULLTEXT_PREPARE_JS = r"""async () => {
  const wrapper = document.getElementById('references-wrapper');
  if (!wrapper || wrapper.querySelector('li')) return 0;
  const path = location.pathname.replace('/meta', '');
  if (!/^\/article\/10\.\d{4,9}\/\S+$/.test(path)) return 0;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`/references${path}`, {credentials: 'include', signal: controller.signal});
    if (!response.ok) return 0;
    const fragment = new DOMParser().parseFromString(await response.text(), 'text/html');
    if (!fragment.querySelector('[data-toolbar-content="references"], li[data-reference]')) return 0;
    fragment.querySelectorAll('script, style, link, button').forEach((node) => node.remove());
    wrapper.replaceChildren(...[...fragment.body.childNodes].map((node) => document.importNode(node, true)));
    wrapper.setAttribute('data-papersearch-references', `/references${path}`);
    return wrapper.querySelectorAll('li').length;
  } catch {
    return 0;
  } finally {
    clearTimeout(timer);
  }
}"""


@register
class IOPAdapter(PublisherAdapter):
    publisher = "iop"
    fulltext_shown_js = FULLTEXT_SHOWN_JS
    fulltext_images_js = FULLTEXT_IMAGES_JS
    fulltext_prepare_js = FULLTEXT_PREPARE_JS

    def server_error_page(self, page: Any) -> str:
        # In place of the article, a page with only the site's header and footer, titled
        # "IOPscience::.. Error!": five subscription articles of a resumed batch, each then went
        # through the PDF and the login to 没取到 PDF; the same pages opened normally later
        # (Windows, 2026-11-25).
        title = self.d._title(page)
        return title if title.lower() == "iopscience::.. error!" else ""

    def supplements_page_urls(self, doi: str) -> list[str]:
        return [f"https://iopscience.iop.org/article/{doi}/data"]

    def supplement_links(self, page: Any, doi: str) -> list[SupplementLink] | None:
        return supplement_links_from_page(page.evaluate(_SUPPLEMENT_ROWS_JS), str(page.url), doi)

    def open_institution_entry(self, page: Any, result: Any) -> bool | None:
        current_url = str(getattr(page, "url", "") or "")
        host = (urlparse(current_url).hostname or "").lower()
        if host == "openathens.net" or host.endswith(".openathens.net"):
            return None  # a federation page: the engine clicks nothing there
        if "iopscience.iop.org/article/" not in current_url.lower():
            return None
        text = self.d._body_text(page, 5_000).lower()
        offered = "access this article" in text or "access through your institution" in text
        # An accepted manuscript's page has no access box, its PDF still needs the
        # institution's login (Physics in Medicine & Biology, 2026-11-08). Once per
        # article: back from the login without access, the page is left as it is.
        manuscript = "accepted manuscript" in text and result is not None and not any(
            e.get("state") == "sso_entry_clicked" and "myiopscience.iop.org/signin" in str(e.get("detail", ""))
            for e in getattr(result, "events", None) or [])
        if not offered and not manuscript:
            return None
        signin_url = "https://myiopscience.iop.org/signin?" + urlencode(
            {"origin": "deeplink", "target": current_url}
        )
        try:
            open_page(page, signin_url, timeout_ms=30_000)
            if result is not None:
                self.d._event(result, "sso_entry_clicked", signin_url)
            return True
        except Exception as exc:
            if result is not None:
                self.d._event(result, "sso_entry_error", f"{type(exc).__name__}: {exc}")
            return None  # the generic entries are tried next
