"""--fulltext: the article's full-text page, saved while the browser is on it for the PDF.

PaperSearch turns the page into Markdown (src/capabilities/download/content/markdown/); this module only
keeps what it needs, in two steps that never load the article page again:

1. ``read_page``, on the article page before the PDF is captured: once the page has
   stopped changing, and only when it names this DOI and shows the full text (the
   adapter's ``fulltext_shown_js``, waited for up to 15 s: a body may come after), the page's HTML and the figure images it lists
   (the adapter's ``fulltext_images_js``). An adapter's ``fulltext_prepare_js`` runs
   first, in the page's own world (ScienceDirect keeps each formula's MathML), given the
   text of the document its ``fulltext_prepare_source`` names (PLOS's article XML, which the
   page cannot fetch). No figure is fetched yet, so the PDF's time is not spent on figures.
2. ``save_page``, after the PDF, with the same session's cookies (the institution login
   and Cloudflare clearance apply): the HTML and the images into

       <output dir>/<DOI>_fulltext_page/article.html
       <output dir>/<DOI>_fulltext_page/images/<name>

   and the result's ``fulltext_page``: ``{"file", "url", "images": [{"url", "file"}]}``.

Limits as for supplementary files: 50 images, 200 MB, 3 minutes.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from ..identifiers import normalize_doi

MAX_IMAGES = 50
MAX_BYTES = 200 * 1024 * 1024
TIME_BUDGET_SEC = 180
REQUEST_TIMEOUT_MS = 30_000
STABLE_INTERVAL_SEC = 0.75
STABLE_TIMEOUT_SEC = 8.0
SHOWN_WAIT_MS = 15_000
# The document an adapter's preparation is given (fulltext_prepare_source): at most this
# long and this large; without it the script runs with "" and says so.
PREPARE_SOURCE_TIMEOUT_MS = 15_000
PREPARE_SOURCE_MAX_BYTES = 20 * 1024 * 1024
PDF_ONLY = "pdf_only"  # in the reason a page is not read: its text is in the PDF alone

# What changes while a page is still filling in: its text length and its images.
_FINGERPRINT_JS = """() => {
  const body = document.body;
  return body ? `${body.innerText.length}:${document.images.length}:${document.querySelectorAll('math, mjx-container').length}` : "";
}"""

# The DOI the page says it is (citation_doi, Dublin Core, PRISM).
_PAGE_DOI_JS = """() => {
  const names = ["citation_doi", "dc.identifier", "dc.Identifier", "DC.identifier", "prism.doi"];
  for (const name of names) {
    for (const meta of document.querySelectorAll(`meta[name="${name}"]`)) {
      const value = (meta.getAttribute("content") || "").trim();
      if (/10\\.\\d{4,9}\\//.test(value)) return value;
    }
  }
  return "";
}"""


def paragraph_text_js(paragraphs: str, outside: str, threshold: str, *, root: str = "") -> str:
    """A ``fulltext_shown_js`` that counts the article's paragraph text: the elements
    ``paragraphs`` selects (inside the first ``root`` when one is given: no full text without
    it), those inside ``outside`` aside, their text's length compared with ``threshold``
    ("> 500", ">= 200": each adapter's own). The selectors are written in single quotes."""
    if not re.fullmatch(r">=? \d+", threshold):
        raise ValueError(f"threshold is a comparison with a number: {threshold!r}")
    if any("'" in selector or "\\" in selector for selector in (paragraphs, outside, root)):
        raise ValueError("a selector with a quote or a backslash")
    lines = ["() => {"]
    scope = "document"
    if root:
        lines += [f"  const root = document.querySelector('{root}');", "  if (!root) return false;"]
        scope = "root"
    lines.append(f"  const text = [...{scope}.querySelectorAll('{paragraphs}')]")
    if outside:
        lines.append(f"    .filter((p) => !p.closest('{outside}'))")
    lines += ["    .reduce((total, p) => total + (p.textContent || '').length, 0);", f"  return text {threshold};", "}"]
    return "\n".join(lines)


# For an adapter's ``fulltext_prepare_js`` on a MathJax page that keeps no MathML in the
# DOM (ScienceDirect's MathJax 4, Wiley's lazy MathJax 4.1, 2026-11-14): each formula's
# source written onto its element as data-original-mathml, which PaperSearch reads. A
# formula not typeset yet (lazy) keeps it on its source node. MathJax 2 pages too. A TeX
# formula is left as it is: MathJax 4 writes its TeX on the output (data-latex; Optica,
# 2026-11-15).
MATHJAX_SOURCES_JS = r"""async () => {
  const startup = window.MathJax?.startup?.promise;
  if (startup) await Promise.race([startup, new Promise((done) => setTimeout(done, 5000))]);
  let kept = 0;
  const keep = (node, source) => {
    if (node?.setAttribute && typeof source === 'string' && /^\s*<(?:[\w-]+:)?math[\s>]/.test(source)) {
      node.setAttribute('data-original-mathml', source);
      kept += 1;
    }
  };
  const doc = window.MathJax?.startup?.document;
  if (doc?.getMathItemsWithin) {
    for (const item of doc.getMathItemsWithin(document.body)) keep(item.typesetRoot || item.start?.node, item.math);
  }
  if (window.MathJax?.Hub?.getAllJax) {
    for (const jax of window.MathJax.Hub.getAllJax()) {
      const source = jax.SourceElement && jax.SourceElement();
      keep(document.getElementById(jax.inputID + '-Frame') || source?.previousElementSibling, jax.originalText);
    }
  }
  return kept;
}"""


def _names_doi(named: str, doi: str) -> bool:
    """Whether the DOI a page names (``_PAGE_DOI_JS``) is this one, or the page names none. A
    DOI written as the end of a sentence is the same DOI: the AMA Journal of Ethics writes
    "10.1001/amajethics.2025.884." in its citation_doi too, and its pages were taken for another
    article's (other_article, 2026-11-22)."""
    named = normalize_doi(named).lower()
    wanted = (normalize_doi(doi) or "").lower()
    return not named or named == wanted or named.rstrip(".") == wanted.rstrip(".")


def page_dir(output_dir: Path, doi: str) -> Path:
    return Path(output_dir) / (re.sub(r"[^A-Za-z0-9._-]+", "_", doi) + "_fulltext_page")


# MathJax 2 typesets a page's formulas a batch at a time, saying so in its message box
# ("Typesetting math: 37%"), and the page changes until it is done: a Frontiers page with
# 157 formulas took 36 s, read as never settling (page_not_stable, 2026-11-18). What the box
# says while MathJax is at work, else "".
_MATHJAX_BUSY_JS = """() => {
  const box = document.getElementById('MathJax_Message');
  if (!box || getComputedStyle(box).display === 'none' || getComputedStyle(box).visibility === 'hidden') return '';
  const said = (box.textContent || '').replace(/\\s+/g, ' ').trim();
  return /^(?:typesetting|processing|loading)\\b/i.test(said) ? said.slice(0, 60) : '';
}"""
# The longest wait for MathJax 2 while its progress moves; the page read's own time goes on
# with it (``watchdog.extend_operation``).
MATHJAX_WAIT_SEC = 90


def wait_stable(page: Any, *, interval: float = STABLE_INTERVAL_SEC, timeout: float = STABLE_TIMEOUT_SEC,
                clock: Callable[[], float] | None = None) -> bool:
    """Whether the page stopped changing: the same fingerprint twice, ``interval`` apart
    (the browser runs meanwhile), with MathJax 2 not at work. While MathJax 2 typesets and
    its progress moves, the wait goes on, up to ``MATHJAX_WAIT_SEC``."""
    from ..browser import watchdog

    clock = clock or time.monotonic
    started = clock()
    deadline = started + timeout
    last, progress = page.evaluate(_FINGERPRINT_JS), ""
    while clock() < deadline:
        page.wait_for_timeout(int(interval * 1000))
        current = page.evaluate(_FINGERPRINT_JS)
        busy = page.evaluate(_MATHJAX_BUSY_JS)
        if current and current == last and not busy:
            return True
        if busy and busy != progress and clock() - started < MATHJAX_WAIT_SEC:
            deadline = min(max(deadline, clock() + timeout), started + MATHJAX_WAIT_SEC)
            watchdog.extend_operation(timeout + 15)
        last, progress = current, busy
    return False


# The general rules, for a site without page scripts and a maintainer's sample
# (``publisher-check --fulltext``): any article page with a fair amount of text; each figure
# image on it, the largest a link or a lazy loader names, one address per figure (a shared
# placeholder would count many figures as one).
_SAMPLE_SHOWN_JS = """() => ((document.querySelector('main, article, [role="main"]') || document.body)?.innerText.length || 0) > 3000"""
_SAMPLE_IMAGES_JS = """() => [...document.querySelectorAll('figure img, .figure img, .fig img, img[data-open="viewer"]')]
  .filter((img) => !img.closest('nav, header, footer, aside'))
  .map((img) => {
    const link = img.closest('a[href]');
    const large = link && /\\.(jpe?g|png|gif|webp|tiff?)(\\?|$)/i.test(link.getAttribute('href')) ? link.getAttribute('href') : '';
    const named = large || img.getAttribute('data-lg-src') || img.getAttribute('data-src') || img.getAttribute('data-original') || img.currentSrc || img.src;
    try { return new URL(named, location.href).href; } catch (error) { return ''; }
  })
  .filter((url) => /^https?:/.test(url))"""


# What a page that was not taken for the full text had, for the record: its host and the
# text length of the usual body containers.
# A page that is the PDF itself (Chrome's viewer: a retracted article opened as its PDF), or
# whose body is a line or two while the page sends the reader to the PDF for the rest (a
# one-page figure article: "To view this SnapShot, open or download the PDF", 2026-11-18; an
# Atypon page with no HTML of the article: "You can view the full content in the following
# formats: PDF/eReader", ACM 10.1145/3863936, 2026-11-19):
# there is no full text to wait for, and no school login brings one. What it said, or "".
_PDF_ONLY_JS = """() => {
  if (document.contentType === 'application/pdf'
      || document.querySelector('embed[type="application/pdf"], embed[type="application/x-google-chrome-pdf"]')) {
    return 'the page is the PDF';
  }
  const body = ['#body', 'section#bodymatter', '[property="articleBody"]']
    .map((selector) => document.querySelector(selector)).find(Boolean);
  const text = ((document.querySelector('article') || document.body)?.innerText || '').replace(/\\s+/g, ' ');
  const said = text.match(/[^.]*\\bopen or download the pdf\\b[^.]*|[^.]*\\b(?:full[ -]text|this article|the article) is (?:only )?available (?:only )?(?:as|in) (?:a )?pdf\\b[^.]*|[^.]*\\bview the full (?:content|text) in the following formats?:?\\s*pdf\\b[^.]*/i);
  return said && (body ? body.innerText.trim().length : 0) < 600 ? said[0].trim().slice(0, 160) : '';
}"""

_NOT_SHOWN_EVIDENCE_JS = """() => {
  const sizes = ['#body', 'section#bodymatter', '[property="articleBody"]', 'article', 'main']
    .map((selector) => `${selector}=${document.querySelector(selector)?.innerText.length ?? '-'}`);
  return `${location.hostname} ${sizes.join(' ')}`;
}"""


def read_page(page: Any, doi: str, adapter: Any, *, sample: bool = False) -> tuple[dict[str, Any] | None, str]:
    """The page's HTML, address and figure image addresses, or None and why not.
    ``sample``: a maintainer's sample, read with the general rules whatever the site's own
    say (a site without rules, or one whose rules missed the page).

    A site whose adapter has no page scripts (the general flow's ``site:<domain>``, or a
    publisher without them) is read with the general rules too: PaperSearch tries its
    templates on the page and keeps the Markdown only when it is complete (user,
    2026-11-16). Its figures are the ones the general rule finds, a lower bound."""
    own = getattr(adapter, "fulltext_shown_js", None)
    general = sample or not own
    shown_js = _SAMPLE_SHOWN_JS if general else own
    if not wait_stable(page):
        return None, "page_not_stable"
    if not _names_doi(str(page.evaluate(_PAGE_DOI_JS) or ""), doi):
        return None, "other_article"
    if not sample:
        pdf_only = str(page.evaluate(_PDF_ONLY_JS) or "")
        if pdf_only:
            return None, f"fulltext_not_shown: {PDF_ONLY}: {pdf_only}"
    # A site may show the abstract first and fetch the body after it (ScienceDirect: the
    # page stood still with "body":{} in its state, 2026-11-14): wait for the full text.
    from .batch_common import pump_until

    if not pump_until(page, lambda: bool(page.evaluate(shown_js)), SHOWN_WAIT_MS):
        if not sample:
            return None, f"fulltext_not_shown: {page.evaluate(_NOT_SHOWN_EVIDENCE_JS)}"
        # A maintainer's sample is kept whatever the general rule saw: what the page holds
        # is the point (AMS keeps its body outside main and article, 2026-11-15).
    wait_stable(page)  # the body that just arrived settles
    # The general rules keep the formulas' MathML MathJax holds (nothing without MathJax).
    prepare_js = getattr(adapter, "fulltext_prepare_js", None) or (MATHJAX_SOURCES_JS if general and not sample else None)
    prepared = None
    if prepare_js:
        # In the page's own world: it reads the page's globals (MathJax). What it did (a
        # count, or the site's own short report) goes into the record.
        from ..browser.driver import main_world

        source = _prepare_source(page, adapter, doi) if prepare_js is getattr(adapter, "fulltext_prepare_js", None) else None
        if source is None:
            prepared = page.evaluate(prepare_js, **main_world(page))
        else:
            text, missing = source
            prepared = page.evaluate(prepare_js, text, **main_world(page))
            if missing:
                prepared = f"{prepared}; {missing}"
    url = str(page.url)
    html = page.evaluate("() => document.documentElement.outerHTML")
    if str(page.url) != url:
        # The page moved while being read: not one page's HTML.
        return None, "page_moved"
    own_images = getattr(adapter, "fulltext_images_js", None)
    images_js = (own_images or _SAMPLE_IMAGES_JS) if sample else (_SAMPLE_IMAGES_JS if general else own_images)
    images = page.evaluate(images_js) if images_js else []
    addresses = []
    for value in images if isinstance(images, list) else []:
        if isinstance(value, str) and urlparse(value).scheme in ("http", "https") and value not in addresses:
            addresses.append(value)
    read = {"html": "<!DOCTYPE html>\n" + str(html), "url": url, "image_urls": addresses[:MAX_IMAGES],
            **({"general": True} if general and not sample else {})}
    if isinstance(prepared, (int, float, str)) and not isinstance(prepared, bool):
        read["prepared"] = str(prepared)[:300]
    return read, ""


def _prepare_source(page: Any, adapter: Any, doi: str) -> tuple[str, str] | None:
    """The document the adapter's preparation is given, fetched in the browser session (its
    cookies; no CORS): its text and "", or "" and why there is none; None when the adapter
    names no document."""
    named = getattr(adapter, "fulltext_prepare_source", None)
    url = named(doi, str(page.url)) if callable(named) else ""
    if not url:
        return None
    from ..browser import watchdog
    from ..browser.driver import driver_lost, is_driver_error

    # The page read's budget leaves the fetch its time, as it does MathJax's wait.
    watchdog.extend_operation(PREPARE_SOURCE_TIMEOUT_MS / 1000 + 5)
    try:
        response = page.context.request.get(url, timeout=PREPARE_SOURCE_TIMEOUT_MS)
    except Exception as exc:
        if not is_driver_error(exc) or driver_lost(exc):
            raise
        return "", f"source not fetched: {type(exc).__name__}"
    try:
        if not response.ok:
            return "", f"source not fetched: http_{response.status}"
        body = response.body()
        if len(body) > PREPARE_SOURCE_MAX_BYTES:
            return "", "source not fetched: too_large"
        return body.decode("utf-8", errors="replace"), ""
    finally:
        response.dispose()


def _image_name(url: str, content_type: str, taken: set[str]) -> str:
    raw = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "image"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._") or "image"
    if not re.search(r"\.(jpe?g|png|gif|webp|svg|tiff?)$", name, re.I):
        extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
                     "image/svg+xml": ".svg"}.get(content_type.split(";")[0].strip().lower(), "")
        name += extension
    stem, dot, extension = name.rpartition(".")
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f"{stem}-{n}.{extension}" if dot else f"{name}-{n}"
        n += 1
    taken.add(candidate.lower())
    return candidate


def save_page(read: dict[str, Any], output_dir: Path, doi: str, request: Any, *,
              clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Writes the HTML and fetches the images with ``request`` (the browser session's)."""
    folder = page_dir(output_dir, doi)
    (folder / "images").mkdir(parents=True, exist_ok=True)
    html_file = folder / "article.html"
    html_file.write_text(read["html"], encoding="utf-8")
    saved: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    taken: set[str] = set()
    total = 0
    deadline = clock() + TIME_BUDGET_SEC
    for url in read.get("image_urls") or []:
        if clock() > deadline or total >= MAX_BYTES:
            failed.append({"url": url, "reason": "time_limit" if clock() > deadline else "too_large"})
            continue
        try:
            response = request.get(url, timeout=REQUEST_TIMEOUT_MS)
        except Exception as exc:
            # Recorded; PaperSearch reports each figure without a file.
            failed.append({"url": url, "reason": type(exc).__name__})
            continue
        try:
            content_type = str(response.headers.get("content-type") or "")
            if not response.ok:
                failed.append({"url": url, "reason": f"http_{response.status}"})
                continue
            if not content_type.lower().startswith("image/"):
                failed.append({"url": url, "reason": "not_an_image"})
                continue
            body = bytearray()
            try:
                whole = True
                for chunk in response.chunks():
                    body.extend(chunk)
                    if total + len(body) > MAX_BYTES or clock() > deadline:
                        whole = False
                        break
            except Exception as exc:
                # A read that fails part way (PLOS's image host timing out, 2026-11-23) is recorded like
                # one that could not start: this figure is missing, the page and the PDF go on.
                failed.append({"url": url, "reason": type(exc).__name__})
                continue
            if whole:
                if not body:
                    failed.append({"url": url, "reason": "empty"})
                    continue
                target = folder / "images" / _image_name(url, content_type, taken)
                target.write_bytes(bytes(body))
                total += len(body)
                saved.append({"url": url, "file": str(target)})
                continue
            failed.append({"url": url, "reason": "time_limit" if clock() > deadline else "too_large"})
        finally:
            response.dispose()
    return {"file": str(html_file), "url": read["url"], "images": saved, "failed_images": failed}
