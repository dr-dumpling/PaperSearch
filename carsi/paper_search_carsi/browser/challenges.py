"""Browser-independent verification-page recognition from observed page data.

These predicates do not read the browser, wait, report progress or decide
article access. The caller checks explicit publisher blocks before the broader
path/text predicates. No match means no recognised challenge, not verified
access or a successfully completed check.
"""
from __future__ import annotations

from urllib.parse import urlparse


CHALLENGE_TITLES = ("just a moment", "请稍候")
_TEXT_MARKERS = (
    "just a moment",
    "attention required",
    "verify you are human",
    "checking your browser",
    "verifying your request",
    "automated-traffic protection",
    "are you a robot",
    "please confirm you are a human",
    "confirm that you are not a robot",
)
_CLOUDFLARE_MARKERS = (
    "ray id:",
    "security verification",
    "security service",
    "not a robot",
    "瀹夊叏楠岃瘉",
)


def looks_like_challenge(url: str, title: str) -> bool:
    """Recognise an interstitial without requiring a DOM/body read.

    Reading the body of an active check can interfere with it. In particular,
    'Attention Required! | Cloudflare' is not this lightweight shell: the engine
    must first check whether it is an explicit block.
    """
    url = str(url or "").lower()
    return ("__cf_chl" in url or "/cdn-cgi/challenge-platform/" in url
            or str(title or "").strip().lower().startswith(CHALLENGE_TITLES))


def is_challenge_path(url: str) -> bool:
    """Verification routes, excluding links in queries and article topic paths."""
    path = urlparse(url).path.lower()
    return "/crawlprevention/" in path or path == "/captcha" or path.startswith("/captcha/")


def has_challenge_text(title: str, text: str) -> bool:
    """Recognise verification wording after explicit access blocks are excluded."""
    haystack = f"{title} {text}".lower()
    return (any(marker in haystack for marker in _TEXT_MARKERS)
            or ("cloudflare" in haystack
                and any(marker in haystack for marker in _CLOUDFLARE_MARKERS)))
