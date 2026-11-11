"""Resolve DOI-bound Figshare supplementary articles/collections via the public API.

Works across publishers; never searches Figshare by title or accepts a reference
as proof that an unrelated dataset belongs to the paper.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

from ...base import SupplementLink
from ....browser.watchdog import BrowserUnresponsive
from ....entitlements import UserMarkedNoEntitlement

_API = "https://api.figshare.com/v2"
_MAX_RESOURCES = 5
_MAX_ARTICLES = 50
_MAX_BYTES = 200 * 1024 * 1024
_BUDGET_SEC = 30
_PAGE_LINKS = """() => {
 // A cited dataset is not a supplement of the article citing it.
 const links = [...document.querySelectorAll('a[href], iframe[src]')]
   .filter(a => !a.closest('[role="doc-bibliography"], [role="doc-biblioentry"], '
     + '#references, #bibliography, #articleReferences, .ref-list, .article-section__references'));
 return {
   doi: document.querySelector('meta[name="citation_doi"]')?.content || '',
   links: links.map(a => a.href || a.src),
   labelled: links.filter(a => a.tagName === 'A' &&
     /^(?:supplement(?:ary)?(?: (?:material|information|data|file|document))?|supporting information)\\s*\\d*$/i
       .test((a.textContent || '').replace(/\\s+/g,' ').trim())).map(a => a.href)
 };
}"""


def _doi(value: Any) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I).lower()


def resource(url: str) -> tuple[str, str, str] | None:
    """Return kind/id/version only for official Figshare URLs and DOI links."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    host, path = (parsed.hostname or "").lower(), unquote(parsed.path)
    if host in {"doi.org", "dx.doi.org"}:
        # Publishers can mint their own Figshare DOI prefixes, e.g.
        # 10.60893/figshare.adv.c.8713366 (AIP). Check the returned resource
        # DOI below as well as the parent paper DOI; the numeric ID alone
        # is never evidence that this landing link denotes that resource.
        stem = r"/10\.\d{4,9}/(?:m9\.)?figshare(?:\.[a-z][a-z0-9_-]*)*"
        for kind, suffix in (("collections", r"\.c\."), ("articles", r"\.")):
            m = re.fullmatch(stem + suffix + r"(\d+)(?:\.v(\d+))?/?", path, re.I)
            if m:
                return kind, m[1], m[2] or ""
        return None
    if host != "figshare.com" and not host.endswith(".figshare.com"):
        return None
    if host == "widgets.figshare.com":
        widget = re.fullmatch(r"/articles/(\d+)/embed/?", path)
        if widget:
            return "articles", widget[1], ""
    m = re.fullmatch(r"/(articles|collections)/(?:[^/]+/)*(\d+)(?:/(\d+))?/?", path)
    if not m:
        return None
    # A numeric last segment after the resource ID denotes a pinned version.
    parts = path.strip('/').split('/')
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
        return parts[0], parts[-2], parts[-1]
    return m[1], m[2], m[3] or ""


def _belongs(data: dict, doi: str, *, labelled: bool = False) -> bool:
    resource_doi = _doi(data.get("resource_doi"))
    if resource_doi:
        return resource_doi == doi
    parents = [_doi(item.get("identifier")) for item in data.get("related_materials") or []
               if isinstance(item, dict) and item.get("relation") == "IsSupplementTo"]
    if parents:
        return doi in parents
    # Some publisher deposits omit the backlink. An explicit Supplement link
    # on the DOI-verified article is then sufficient; a plain citation is not.
    return labelled


def supplement_links(page: Any, doi: str, *, clock=time.monotonic, pause=time.sleep) -> list[SupplementLink] | None:
    """None means no Figshare route on this article; failures stay in the manifest.
    A resource not shown to be this article's is set aside (``set_aside``)."""
    data = page.evaluate(_PAGE_LINKS)
    if not isinstance(data, dict) or _doi(data.get("doi")) != _doi(doi):
        return None
    roots: dict[tuple[str, str, str], str] = {}
    for url in data.get("links", []):
        if isinstance(url, str) and (key := resource(url)):
            roots.setdefault(key, url)
    if not roots:
        return None
    started = clock()
    links: list[SupplementLink] = []
    fetched: dict[str, Any] = {}
    last_request: float | None = None
    doi = _doi(doi)

    def get(path: str) -> Any:
        nonlocal last_request
        if path in fetched:
            return fetched[path]
        if last_request is not None:
            pause(max(0, 1 - (clock() - last_request)))
        remaining = _BUDGET_SEC - (clock() - started)
        if remaining <= 0:
            raise ValueError("figshare_time_budget")
        last_request = clock()
        response = page.context.request.get(_API + path, timeout=min(10_000, max(1, int(remaining * 1000))))
        if not response.ok:
            raise ValueError(f"figshare_http_{response.status}")
        value = response.json()
        fetched[path] = value
        return value

    for index, ((kind, ident, version), root) in enumerate(roots.items()):
        if index >= _MAX_RESOURCES:
            links.append(SupplementLink(root, "Figshare resources", error="figshare_resource_limit"))
            break
        try:
            base = f"/{kind}/{ident}" + (f"/versions/{version}" if version else "")
            detail = get(base)
            if not isinstance(detail, dict) or str(detail.get("id")) != ident:
                raise ValueError("figshare_invalid_metadata")
            if urlparse(root).hostname in {"doi.org", "dx.doi.org"}:
                requested = unquote(urlparse(root).path).strip("/").lower()
                actual = _doi(detail.get("doi"))
                if (requested != actual if version else
                        re.sub(r"\.v\d+$", "", requested) != re.sub(r"\.v\d+$", "", actual)):
                    raise ValueError("figshare_resource_doi_mismatch")
            if not _belongs(detail, doi, labelled=root in data.get("labelled", [])):
                raise ValueError("figshare_article_mismatch")
            articles = [detail]
            if kind == "collections":
                # Fetch one more than the collector limit to report truncation.
                members = get(base + f"/articles?page_size={_MAX_ARTICLES + 1}&page=1")
                if not isinstance(members, list):
                    raise ValueError("figshare_invalid_metadata")
                articles = []
                for member in members[:_MAX_ARTICLES]:
                    article_id = member.get("id") if isinstance(member, dict) else None
                    if not isinstance(article_id, int) or article_id <= 0:
                        raise ValueError("figshare_invalid_metadata")
                    member_version = member.get("version")
                    suffix = f"/versions/{member_version}" if isinstance(member_version, int) and member_version > 0 else ""
                    item = get(f"/articles/{article_id}{suffix}")
                    if not isinstance(item, dict) or item.get("id") != article_id:
                        raise ValueError("figshare_invalid_metadata")
                    # Collection association is sufficient only if the member does
                    # not explicitly contradict it; its resource DOI takes precedence.
                    if item.get("resource_doi") and _doi(item["resource_doi"]) != doi:
                        raise ValueError("figshare_article_mismatch")
                    if any(isinstance(rel, dict) and rel.get("relation") == "IsSupplementTo"
                           and _doi(rel.get("identifier")) != doi
                           for rel in item.get("related_materials") or []):
                        raise ValueError("figshare_article_mismatch")
                    articles.append(item)
                if len(members) > _MAX_ARTICLES:
                    links.append(SupplementLink(root, "Figshare collection", error="figshare_article_limit"))
            count = 0
            for article in articles:
                files = article.get("files")
                if not isinstance(files, list):
                    raise ValueError("figshare_invalid_metadata")
                for file in files:
                    if not isinstance(file, dict) or not isinstance(file.get("id"), int) or file["id"] <= 0:
                        raise ValueError("figshare_invalid_file")
                    file_id = file["id"]
                    # Construct the documented public download endpoint; never
                    # follow arbitrary external URLs supplied by link-only datasets.
                    url = f"https://api.figshare.com/v2/file/download/{file_id}"
                    name = str(file.get("name") or f"Figshare file {file_id}")
                    error = ""
                    if file.get("is_link_only"):
                        error = "figshare_link_only"
                    elif not isinstance(file.get("size"), int) or file["size"] < 0:
                        error = "figshare_invalid_file"
                    elif file["size"] > _MAX_BYTES:
                        error = "too_large"
                    links.append(SupplementLink(url, name, error=error))
                    count += 1
            if count == 0:
                raise ValueError("figshare_no_files")
        except (BrowserUnresponsive, UserMarkedNoEntitlement):
            raise
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("figshare_") else "figshare_request_failed"
            if reason == "figshare_article_mismatch":
                # A dataset the article names (its data availability statement) is
                # not its supplement unless one of them says so (JEM, 2026-11-11).
                links.append(SupplementLink(root, "Figshare resource", set_aside=reason))
            else:
                links.append(SupplementLink(root, "Figshare supplementary material", error=reason))
    return list(dict.fromkeys(links))
