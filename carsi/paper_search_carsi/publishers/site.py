"""A profile built at run time for a site that has no publisher profile.

The article's DOI resolves (doi.org and its redirects) to a site no builtin or
configured profile names. Instead of refusing it, the publisher driver runs
there with the shared rules only: the base adapter, the engine's article-page
rule (an address carrying the DOI, or a page whose ``citation_doi`` is the DOI),
its institution entry, school choice, PDF links and PDF identity check. The
profile lives for one download and is never written to ``builtin/``.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlparse

from ..engine.access_rules import registrable_domain
from .model import PublisherProfile

#: Name prefix of a run-time site profile: ``site:<registrable domain>``.
SITE_PREFIX = "site:"

# Markers most builtin profiles share (counts over the 34 builtin profiles,
# 2026-11-02): the four login markers every one of them has, the most common
# institution-entry words and supplementary-file markers.
GENERIC_AUTH_URL_MARKERS = ("login.openathens.net", "/saml/", "/sso/", "/login")
GENERIC_SSO_TEXT_MARKERS = (
    "access through your institution", "institutional login", "openathens",
    "log in through your institution", "log in via an institution", "sign in through your institution",
)
GENERIC_SUPPLEMENTARY_URL_MARKERS = ("supplementary", "suppl_file", "supporting-information", "suppdata", "/suppl/")

# Where a DOI can land that is no publisher's site: doi.org itself, Crossref's
# multiple-resolution chooser, the Handle resolver.
_NOT_A_SITE = frozenset({"doi.org", "crossref.org", "handle.net"})
# Platforms the engine does not sign in on, whatever DOI leads there: ClinicalKey
# (the Elsevier adapter's unsupported platform) and the databases dropped on
# 2026-11-02 (CNKI, Wanfang, VIP).
_UNSUPPORTED_SITES = re.compile(r"clinicalkey\.[a-z]{2,3}(?:\.[a-z]{2})?|cnki\.net|wanfangdata\.com\.cn|cqvip\.com")
_DOI_PREFIX = re.compile(r"10\.\d{4,9}")


@dataclass(frozen=True)
class SiteProfile(PublisherProfile):
    """A run-time profile for one site (``site_profile``)."""

    generic: ClassVar[bool] = True


def site_profile(doi: str, landing_url: str) -> SiteProfile | None:
    """The run-time profile for the site ``landing_url`` is on (the page the DOI
    resolves to), or None when that is no site to sign in on: not an http(s)
    address, a PDF file, an IP address, doi.org or Crossref's chooser, or a
    platform the engine does not support. ``doi`` gives the profile's prefix."""
    prefix = str(doi or "").strip().lower().split("/", 1)[0]
    if "/" not in str(doi or "") or not _DOI_PREFIX.fullmatch(prefix):
        return None
    try:
        parsed = urlparse(str(landing_url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not host or "." not in host or parsed.username or parsed.password:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if parsed.path.lower().endswith(".pdf"):
        return None
    domain = registrable_domain(host)
    if not domain or domain in _NOT_A_SITE or _UNSUPPORTED_SITES.fullmatch(domain):
        return None
    return SiteProfile(
        name=SITE_PREFIX + domain,
        article_url_template="https://doi.org/{doi}",
        pdf_url_templates=(),
        success_url_markers=(),
        auth_url_markers=GENERIC_AUTH_URL_MARKERS,
        sso_text_markers=GENERIC_SSO_TEXT_MARKERS,
        doi_prefixes=(prefix,),
        base_domains=(domain,),
        supplementary_url_markers=GENERIC_SUPPLEMENTARY_URL_MARKERS,
    )
