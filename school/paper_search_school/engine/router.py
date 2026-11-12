"""Publisher-owned PDF routing helpers.

This module keeps DOI/source-page PDF routes out of individual download
callers. It follows the same shape as provider catalogs: profile templates
first, then source URL derivation, then page-discovered links.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ..publishers.profiles import PublisherProfile

PDF_LINK_TEXT_MARKERS = ("pdf", "download pdf", "full text pdf", "view pdf")
PDF_URL_MARKERS = (".pdf", "/pdf", "/epdf", "/pdfdirect", "/pdfft", "download=true")
PDF_JS_DEFAULT_URL_RE = re.compile(
    r"PDFViewerApplicationOptions\.set\(\s*['\"]defaultUrl['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    flags=re.IGNORECASE,
)
PLOS_JOURNAL_PATHS = {
    "pbio": "plosbiology",
    "pcbi": "ploscompbiol",
    "pclm": "climate",
    "pdig": "digitalhealth",
    "pgen": "plosgenetics",
    "pgph": "globalpublichealth",
    "pmed": "plosmedicine",
    "pntd": "plosntds",
    "pone": "plosone",
    "ppat": "plospathogens",
    "pstr": "sustainabilitytransformation",
    "pwat": "water",
}
PLOS_DOI_JOURNAL_RE = re.compile(r"^10\.1371/journal\.([a-z0-9]+)\.", flags=re.IGNORECASE)
COPERNICUS_DOI_RE = re.compile(
    r"^10\.5194/(?P<journal>[a-z0-9]+)-(?P<volume>\d+)-(?P<page>.+)-(?P<year>\d{4})$",
    flags=re.IGNORECASE,
)
MDPI_ISSN_JOURNAL_CODES = {
    "1424-8220": "s",
    "1660-4601": "ijerph",
    "1996-1073": "en",
    "2071-1050": "su",
    "2072-4292": "rs",
    "2073-4441": "w",
    "2077-0375": "membranes",
    "2227-7390": "math",
    "2304-8158": "foods",
}
MDPI_JOURNAL_CODE_ISSNS = {
    journal_code: issn
    for issn, journal_code in MDPI_ISSN_JOURNAL_CODES.items()
}
MDPI_NUMERIC_PATH_RE = re.compile(r"/[0-9]{4}-[0-9Xx]{3,4}/[0-9]+/[0-9]+/[0-9]+$")


_ELSEVIER_FORMATTED_PII = re.compile(r"(S\d{4}-?\d{3}[\dX])(?:\(|%28)(\d{2})(?:\)|%29)(\d{5})-?([\dX])", re.I)
_PII = r"S\d{4}-?\d{3}[\dX]\(\d{2}\)\d{5}-?[\dX]"
_ELSEVIER_JOURNAL_ARTICLE = re.compile(
    rf"^/(?:journals/[^/]+/|(?:[^/]+/){{1,2}})?(?:article/(?:PII)?(?P<a>{_PII})(?:/(?P<av>fulltext|abstract|pdf|ppt))?"
    rf"|(?P<cv>fulltext|abstract|pdf)/(?P<c>{_PII})(?:\.pdf)?)/?$", re.I)


def elsevier_journal_article(url: str) -> tuple[str, str] | None:
    """``(formatted PII, view)`` for an article page on an Elsevier journal's own site.

    Cell Press, Gastroenterology, Osteoarthritis and Cartilage, The Lancet and
    other Elsevier journals are also served from their own hosts, e.g.
    ``https://www.gastrojournal.org/article/S0016-5085(24)00291-9/fulltext``,
    ``https://www.cell.com/cell-metabolism/fulltext/S1550-4131(25)00486-3``,
    ``https://www.cell.com/molecular-therapy-family/molecular-therapy/fulltext/S1525-0016(26)00767-7`` or
    ``https://www.thelancet.com/journals/lanrhe/article/PIIS2665-9913(25)00091-8/fulltext``.
    """
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host == "sciencedirect.com" or host.endswith(".sciencedirect.com"):
        return None
    match = _ELSEVIER_JOURNAL_ARTICLE.match(unquote(parsed.path))
    if not match:
        return None
    return match["a"] or match["c"], (match["av"] or match["cv"] or "").lower()


def extract_elsevier_pii(url: str) -> str:
    """Extract an Elsevier PII from article, retrieve, query, or signed asset URLs.

    The formatted form used by journal sites (``S1063-4584(22)00770-1``) is
    returned in ScienceDirect's compact form (``S1063458422007701``).
    """
    formatted = _ELSEVIER_FORMATTED_PII.search(url or "")
    if formatted:
        return "".join(formatted.groups()).replace("-", "").upper()
    for pattern in (
        r"/pii/([A-Z0-9]+)",
        r"/retrieve/pii/([A-Z0-9]+)",
        r"[?&]pii=([A-Z0-9]+)",
        r"1-s2\.0-([A-Z0-9]+)",
    ):
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def extract_ieee_article_number(url: str) -> str:
    """Extract an IEEE Xplore article number from document or query URLs."""
    for pattern in (
        r"/document/(\d+)",
        r"[?&]arnumber=(\d+)",
    ):
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def discover_pdf_candidates_from_html(html_text: str, source_url: str) -> list[str]:
    """Extract likely PDF URLs from publisher HTML without committing to a provider."""
    candidates: list[str] = []
    soup = BeautifulSoup(html_text, "lxml")

    for meta in soup.find_all("meta"):
        key = _clean(meta.get("name") or meta.get("property") or meta.get("itemprop")).lower()
        content = _clean(meta.get("content"))
        if content and ("citation_pdf_url" in key or key.endswith("pdf_url") or key == "pdf_url"):
            _append_candidate(candidates, content, source_url=source_url)
            _append_query_pdf_candidates(candidates, content, source_url=source_url)

    for node in soup.find_all(["a", "link", "iframe", "embed", "object"]):
        target = _clean(node.get("href") or node.get("src") or node.get("data"))
        if not target:
            continue
        label = _clean(
            " ".join(
                filter(
                    None,
                    [node.get_text(" ", strip=True), node.get("title"), node.get("aria-label")],
                )
            )
        ).lower()
        content_type = _clean(node.get("type")).lower()
        lower_target = target.lower()
        if (
            any(marker in lower_target for marker in PDF_URL_MARKERS)
            or any(marker in label for marker in PDF_LINK_TEXT_MARKERS)
            or "pdf" in content_type
        ):
            _append_candidate(candidates, target, source_url=source_url)
            _append_query_pdf_candidates(candidates, target, source_url=source_url)

    for script in soup.find_all("script"):
        text = script.string if script.string is not None else script.get_text(" ", strip=False)
        for match in PDF_JS_DEFAULT_URL_RE.finditer(str(text or "")):
            target = html.unescape(match.group(1))
            if any(marker in target.lower() for marker in PDF_URL_MARKERS):
                _append_candidate(candidates, target, source_url=source_url)
                _append_query_pdf_candidates(candidates, target, source_url=source_url)

    return candidates


def build_pdf_candidates(
    profile: PublisherProfile,
    doi: str,
    *,
    source_url: str = "",
    discovered_urls: Sequence[str] = (),
) -> list[str]:
    """Build ordered, de-duplicated official PDF candidates for a publisher profile."""
    adapter = _adapter_class(profile)
    candidates: list[str] = []
    for url in adapter.profile_pdf_candidates(doi, source_url):
        _append_candidate(candidates, url)

    _append_source_path_candidates(candidates, profile, doi, source_url)

    for url in profile.pdf_urls(doi):
        _append_candidate(candidates, url)

    for url in discovered_urls:
        if not _clean(url):
            continue
        if is_supplementary_url(profile, url):
            continue
        if not is_pdf_candidate_url(profile, url):
            continue
        if not belongs_to_current_article(profile, url, doi=doi, source_url=source_url):
            continue
        _append_candidate(candidates, url, source_url=source_url)

    return [url for url in candidates if adapter.keeps_pdf_candidate(profile, url, doi)]


def _adapter_class(profile: PublisherProfile):
    """The publisher's adapter class, for its profile-level rules. Imported here:
    adapter modules import this one."""
    from ..adapters.base import adapter_class_for

    return adapter_class_for(profile)


def is_pdf_candidate_url(profile: PublisherProfile, url: str) -> bool:
    verdict = _adapter_class(profile).profile_pdf_candidate_url(url)
    if verdict is not None:
        return verdict
    lower = url.lower()
    return lower.endswith(".pdf") or any(marker.lower() in lower for marker in profile.pdf_url_markers)


def is_thieme_article_pdf_url(url: str, doi: str = "") -> bool:
    """Exclude account/reset URLs that merely carry a PDF return address."""
    parsed = urlparse(url.strip())
    match = re.fullmatch(r"/products/ejournals/pdf/(10\.1055/[^/]+)\.pdf",
                         unquote(parsed.path).lower())
    return (parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.netloc.lower() in {"www.thieme-connect.de", "thieme-connect.de",
                                          "www.thieme-connect.com", "thieme-connect.com"}
            and match is not None and (not doi or match[1] == doi.strip().lower()))


# Supplementary-file paths used the same way across publishers (ACS, SAGE,
# T&F, JAMA, LWW "/suppl/", Wiley "/supinfo/" and "downloadSupplement"),
# plus site CMS uploads (user guides, brochures).
_UNIVERSAL_SUPPLEMENT_MARKERS = ("/suppl/", "/supinfo/", "downloadsupplement", "/wp-content/")
# A supplement issue in the path ("/article-pdf/28/Supplement_11/suag119.023/...",
# a journal's supplement issue on Oxford Academic, 2026-11-01) names the issue,
# not supplementary material: it is left out before the publisher's markers.
_ISSUE_SUPPLEMENT = re.compile(r"/supplement[_-]?\d+/")


def is_supplementary_url(profile: PublisherProfile, url: str) -> bool:
    lower = url.lower()
    if any(marker in unquote(lower) for marker in _UNIVERSAL_SUPPLEMENT_MARKERS):
        return True
    adapter = _adapter_class(profile)
    if adapter.unquotes_supplement_urls:
        lower = unquote(lower)
    if adapter.names_supplement(lower):
        return True
    lower = _ISSUE_SUPPLEMENT.sub("/", lower)
    return any(marker.lower() in lower for marker in profile.supplementary_url_markers)


def is_wiley_article_pdf_url(url: str, doi: str = "") -> bool:
    """Only Wiley's article PDF endpoints, optionally bound to the exact DOI."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    domain = "onlinelibrary.wiley.com"
    if parsed.scheme not in {"http", "https"} or not (host == domain or host.endswith("." + domain)):
        return False
    path = unquote(parsed.path).lower().rstrip("/")
    match = re.fullmatch(r"/doi/(?:pdfdirect|pdf|epdf)/(10\.\d{4,9}/.+)", path)
    return bool(match and (not doi or match.group(1) == doi.strip().lower().rstrip("/")))


def is_springer_article_pdf_url(url: str, doi: str = "") -> bool:
    """Match Springer/Nature article endpoints, excluding their media attachments."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path).lower()
    expected = doi.strip().lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    # Open-access articles offer "<doi>_reference.pdf" (data-article-pdf="true")
    # as their Download PDF; the plain "<doi>.pdf" is refused there.
    if host == "link.springer.com":
        match = re.fullmatch(r"/content/pdf/(10\.\d{4,9}/.+?)(?:_reference)?\.pdf", path)
        return bool(match and (not expected or match.group(1) == expected))
    if host == "nature.com" or host.endswith(".nature.com"):
        match = re.fullmatch(r"/articles/([^/]+?)(?:_reference)?\.pdf", path)
        return bool(match and (not expected or (expected.startswith("10.1038/")
                    and match.group(1) == expected.split("/", 1)[1])))
    return False


def belongs_to_current_article(profile: PublisherProfile, url: str, *, doi: str, source_url: str = "") -> bool:
    verdict = _adapter_class(profile).belongs_to_article(url, doi, source_url)
    return True if verdict is None else verdict


def _append_source_path_candidates(
    candidates: list[str],
    profile: PublisherProfile,
    doi: str,
    source_url: str,
) -> None:
    normalized = _clean(source_url)
    if not normalized:
        return
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    source_path = parsed.path.rstrip("/")
    if parsed.scheme not in {"http", "https"} or not host or not source_path:
        return
    for template in profile.pdf_source_path_templates:
        domain = template.domain.lower()
        if host != domain and not host.endswith(f".{domain}"):
            continue
        path_prefix = _clean(template.path_prefix)
        if path_prefix and not source_path.startswith(path_prefix):
            continue
        candidate_path = _format_template(
            template.path_template,
            doi=doi,
            source_path=source_path,
            source_path_after_prefix=source_path[len(path_prefix):].lstrip("/") if path_prefix else source_path.lstrip("/"),
        )
        if not candidate_path:
            continue
        parsed_candidate = urlparse(candidate_path)
        if parsed_candidate.scheme in {"http", "https"}:
            _append_candidate(candidates, candidate_path)
            continue
        if not candidate_path.startswith("/"):
            candidate_path = f"/{candidate_path}"
        _append_candidate(candidates, urlunparse((parsed.scheme, parsed.netloc, candidate_path, "", "", "")))


def _append_aps_candidates(candidates: list[str], source_url: str) -> None:
    normalized = _clean(source_url)
    if not normalized:
        return
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    source_path = parsed.path.rstrip("/")
    if parsed.scheme not in {"http", "https"} or not host or not source_path:
        return
    if host.endswith("link.aps.org") and source_path.startswith("/doi/"):
        pdf_path = source_path.replace("/doi/", "/pdf/", 1)
        _append_candidate(candidates, urlunparse((parsed.scheme, parsed.netloc, pdf_path, "", "", "")))
        return
    if not host.endswith("journals.aps.org"):
        return
    if "/abstract/" in source_path:
        pdf_path = source_path.replace("/abstract/", "/pdf/", 1)
    elif source_path.endswith("/pdf"):
        pdf_path = source_path
    else:
        return
    _append_candidate(candidates, urlunparse((parsed.scheme, parsed.netloc, pdf_path, "", "", "")))


def _append_ams_candidates(candidates: list[str], source_url: str) -> None:
    normalized = _clean(source_url)
    if not normalized:
        return
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    source_path = parsed.path.rstrip("/")
    if parsed.scheme not in {"http", "https"} or not host.endswith("journals.ametsoc.org"):
        return
    if not source_path.startswith("/view/") or not source_path.lower().endswith(".xml"):
        return
    pdf_path = f"/downloadpdf{source_path[:-4]}.pdf"
    _append_candidate(candidates, urlunparse((parsed.scheme, parsed.netloc, pdf_path, "", "", "")))


def _append_plos_candidates(candidates: list[str], doi: str, source_url: str) -> None:
    journal_path = _plos_journal_path_from_source(source_url) or _plos_journal_path_from_doi(doi)
    if not journal_path:
        return
    _append_candidate(
        candidates,
        f"https://journals.plos.org/{journal_path}/article/file?id={doi}&type=printable",
    )


def _plos_journal_path_from_source(source_url: str) -> str:
    parsed = urlparse(_clean(source_url))
    host = (parsed.hostname or "").lower()
    if host != "journals.plos.org":
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or parts[0] == "article":
        return ""
    return parts[0]


def _plos_journal_path_from_doi(doi: str) -> str:
    match = PLOS_DOI_JOURNAL_RE.match(doi.strip())
    if not match:
        return ""
    return PLOS_JOURNAL_PATHS.get(match.group(1).lower(), "")


def _append_copernicus_candidates(candidates: list[str], doi: str, source_url: str) -> None:
    match = COPERNICUS_DOI_RE.match(doi.strip().lower())
    if not match:
        return
    parsed = urlparse(_clean(source_url))
    host = (parsed.hostname or "").lower()
    if not host.endswith("copernicus.org"):
        host = f"{match.group('journal').lower()}.copernicus.org"
    suffix = doi.split("/", 1)[-1].lower()
    path = f"/articles/{match.group('volume')}/{match.group('page')}/{match.group('year')}/{suffix}.pdf"
    _append_candidate(candidates, f"https://{host}{path}")


def _append_mdpi_candidates(candidates: list[str], doi: str, source_url: str) -> None:
    source_pdf = _mdpi_pdf_url_from_landing_url(source_url)
    if source_pdf:
        _append_candidate(candidates, source_pdf)
    derived_landing = _mdpi_landing_url_from_doi(doi)
    derived_pdf = _mdpi_pdf_url_from_landing_url(derived_landing)
    if derived_pdf:
        _append_candidate(candidates, derived_pdf)


def _mdpi_pdf_url_from_landing_url(url: str | None) -> str:
    candidate = _clean(url)
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host not in {"www.mdpi.com", "mdpi.com"}:
        return ""
    path = parsed.path.rstrip("/")
    if not path:
        return ""
    if path.endswith("/pdf") or "/pdf/" in path:
        return urlunparse(parsed._replace(path=path, query=""))
    if not MDPI_NUMERIC_PATH_RE.fullmatch(path):
        return ""
    return urlunparse(parsed._replace(path=f"{path}/pdf", query=""))


def _mdpi_landing_url_from_doi(doi: str) -> str:
    normalized = doi.strip().lower()
    if not normalized.startswith("10.3390/") or "/" not in normalized:
        return ""
    suffix = normalized.split("/", 1)[1]
    for journal_code in sorted(MDPI_JOURNAL_CODE_ISSNS, key=len, reverse=True):
        if not suffix.startswith(journal_code):
            continue
        encoded = suffix[len(journal_code):]
        if len(encoded) < 7 or not encoded.isdigit():
            continue
        volume = encoded[:-6]
        issue = encoded[-6:-4]
        article_number = encoded[-4:]
        if not volume:
            continue
        return (
            f"https://www.mdpi.com/{MDPI_JOURNAL_CODE_ISSNS[journal_code]}/"
            f"{int(volume)}/{int(issue)}/{int(article_number)}"
        )
    return ""


def _append_oxford_candidates(candidates: list[str], doi: str, source_url: str) -> None:
    parsed = urlparse(_clean(source_url))
    host = (parsed.hostname or "").lower()
    source_path = parsed.path.rstrip("/")
    if parsed.scheme not in {"http", "https"} or not host.endswith("academic.oup.com"):
        return
    match = re.match(r"^/(?P<journal>[^/]+)/article/(?P<rest>.+)$", source_path, flags=re.IGNORECASE)
    if not match:
        return
    suffix = doi.rsplit("/", 1)[-1] if "/" in doi else doi
    pdf_path = f"/{match.group('journal')}/article-pdf/{match.group('rest')}/{suffix}.pdf"
    _append_candidate(candidates, urlunparse((parsed.scheme, parsed.netloc, pdf_path, "", "", "")))


def _format_template(
    template: str,
    *,
    doi: str,
    source_path: str = "",
    source_path_after_prefix: str = "",
) -> str:
    doi_suffix = doi.split("/", 1)[-1] if "/" in doi else doi
    return template.format(
        doi=doi,
        doi_quoted=quote(doi, safe=""),
        doi_suffix=doi_suffix,
        doi_suffix_quoted=quote(doi_suffix, safe=""),
        source_path=source_path,
        source_path_quoted=quote(source_path, safe="/"),
        source_path_after_prefix=source_path_after_prefix,
        source_path_after_prefix_quoted=quote(source_path_after_prefix, safe="/"),
    )


def _append_candidate(candidates: list[str], candidate: str | None, *, source_url: str = "") -> None:
    normalized = _clean(candidate)
    if not normalized:
        return
    if source_url:
        normalized = urljoin(source_url, normalized)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return
    if normalized not in candidates:
        candidates.append(normalized)


def _append_query_pdf_candidates(candidates: list[str], candidate: str, *, source_url: str) -> None:
    absolute = urljoin(source_url, _clean(candidate))
    parsed = urlparse(absolute)
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if _clean(key).lower() not in {"file", "pdf", "src", "url"}:
            continue
        for value in values:
            if any(marker in value.lower() for marker in PDF_URL_MARKERS):
                _append_candidate(candidates, value, source_url=absolute)


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
