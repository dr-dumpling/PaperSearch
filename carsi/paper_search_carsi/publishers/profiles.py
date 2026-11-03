"""Tier-1 publisher profile registry.

The profiles themselves live in ``builtin/*.json`` (one file per publisher,
file stem = registry key) and are loaded by :mod:`.loader` at import time.
This module keeps the lookup API and the legacy ``*_PROFILE`` constants.

Profiles carry GENERIC markers that work for any institution. The
``institution_result_selectors`` field holds optional picker locators where
``{institution}`` stands for the user's configured institution name
(see ``engine/batch.py``); no profile may name a specific school.
"""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from .loader import BuiltinProfileError, load_builtin_profiles
from .model import PdfSourcePathTemplate, PublisherProfile

__all__ = [
    "BuiltinProfileError",
    "PUBLISHER_PROFILES",
    "PdfSourcePathTemplate",
    "PublisherProfile",
    "get_publisher_profile",
    "infer_publisher_profile",
    "infer_publisher_profile_from_url",
    "list_publisher_profiles",
]

PUBLISHER_PROFILES: dict[str, PublisherProfile] = load_builtin_profiles()

_PROFILE_ALIASES = {
    alias.lower(): profile
    for profile in PUBLISHER_PROFILES.values()
    for alias in (profile.name, *profile.aliases)
}

# Legacy constants kept for code that still imports them; new code should use
# get_publisher_profile("elsevier") so adding a JSON file needs no Python edit.
ACS_PROFILE = PUBLISHER_PROFILES["acs"]
ACM_PROFILE = PUBLISHER_PROFILES["acm"]
AIP_PROFILE = PUBLISHER_PROFILES["aip"]
AMS_PROFILE = PUBLISHER_PROFILES["ams"]
ANNUAL_REVIEWS_PROFILE = PUBLISHER_PROFILES["annual-reviews"]
APS_PROFILE = PUBLISHER_PROFILES["aps"]
COPERNICUS_PROFILE = PUBLISHER_PROFILES["copernicus"]
ELSEVIER_PROFILE = PUBLISHER_PROFILES["elsevier"]
FRONTIERS_PROFILE = PUBLISHER_PROFILES["frontiers"]
IEEE_PROFILE = PUBLISHER_PROFILES["ieee"]
IOP_PROFILE = PUBLISHER_PROFILES["iop"]
MDPI_PROFILE = PUBLISHER_PROFILES["mdpi"]
OPTICA_PROFILE = PUBLISHER_PROFILES["optica"]
OXFORD_ACADEMIC_PROFILE = PUBLISHER_PROFILES["oxfordacademic"]
PLOS_PROFILE = PUBLISHER_PROFILES["plos"]
PNAS_PROFILE = PUBLISHER_PROFILES["pnas"]
ROYAL_SOCIETY_PUBLISHING_PROFILE = PUBLISHER_PROFILES["royalsocietypublishing"]
RSC_PROFILE = PUBLISHER_PROFILES["rsc"]
SCIENCE_PROFILE = PUBLISHER_PROFILES["science"]
SPRINGER_PROFILE = PUBLISHER_PROFILES["springer"]
WILEY_PROFILE = PUBLISHER_PROFILES["wiley"]
WORLD_SCIENTIFIC_PROFILE = PUBLISHER_PROFILES["world-scientific"]


def list_publisher_profiles(*, profiles: Mapping[str, PublisherProfile] | None = None) -> list[str]:
    """Return stable publisher profile keys available to deterministic workflows."""
    return sorted(PUBLISHER_PROFILES if profiles is None else profiles)


def get_publisher_profile(name: str, *, profiles: Mapping[str, PublisherProfile] | None = None) -> PublisherProfile:
    """Resolve a publisher profile by key, display name, or alias."""
    key = name.strip().lower()
    catalog = PUBLISHER_PROFILES if profiles is None else profiles
    profile = catalog.get(key)
    if profile is None:
        profile = next((value for value in catalog.values()
                        if key in (alias.lower() for alias in (value.name, *value.aliases))), None)
    if profile is None:
        available = ", ".join(list_publisher_profiles(profiles=catalog))
        raise ValueError(f"Unknown publisher profile '{name}'. Available: {available}")
    return profile


# Journals whose DOIs keep a former publisher's registrant prefix.
_MOVED_JOURNALS = {
    "10.1136/ard-": "elsevier",  # Annals of the Rheumatic Diseases: BMJ -> Elsevier (2025)
}


def infer_publisher_profile(doi: str, *, profiles: Mapping[str, PublisherProfile] | None = None) -> PublisherProfile | None:
    """Infer a likely publisher profile from stable DOI prefixes."""
    normalized = doi.strip().lower()
    catalog = PUBLISHER_PROFILES if profiles is None else profiles
    for prefix, key in _MOVED_JOURNALS.items():
        if normalized.startswith(prefix) and key in catalog:
            return catalog[key]
    for profile in catalog.values():
        if any(normalized == prefix.lower() or normalized.startswith(prefix.lower() + "/")
               for prefix in profile.doi_prefixes):
            return profile
    return None


def infer_publisher_profile_from_url(url: str, *, profiles: Mapping[str, PublisherProfile] | None = None) -> PublisherProfile | None:
    """Infer a publisher profile from a resolved landing or publisher URL."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return None
    catalog = PUBLISHER_PROFILES if profiles is None else profiles
    for profile in catalog.values():
        domains = profile.base_domains or ()
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return profile
        # Some builtins have additional hosts only in their success markers
        # (e.g. elsevier.com). Preserve those routes, but bind the marker's
        # host to the actual authority, never to a query/path substring.
        for marker in profile.success_url_markers:
            marker_url = urlparse(marker if "://" in marker else "//" + marker)
            domain = (marker_url.hostname or "").lower()
            if (domain and (host == domain or host.endswith("." + domain))
                    and parsed.path.lower().startswith(marker_url.path.lower())):
                return profile
    return None
