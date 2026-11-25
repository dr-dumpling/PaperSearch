"""Which kind of verification a verification page is, for the record only.

The user (2026-11-25): a paper stopped by a site's verification should say which
kind stopped it. This module only names the kind: it never clicks, waits, hands a
page over or decides anything about the wait (``local.interaction.challenge_kind`` is
the handoff's own reading and stays as it is).

``read`` takes one look at the page (its address, title, frames, scripts and a few
elements, in one script call); ``classify`` names the kind from that look, without
the browser. A page whose title or address already says Cloudflare's interstitial
is not read further: reading an active check can disturb it (``detection``).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

#: Each kind and how the record and messages name it (the user's list, 2026-11-25),
#: then the other providers the program knows, then a verification page of no
#: kind told. The keys are a fixed vocabulary (the CLI keeps only these).
LABELS: dict[str, str] = {
    "recaptcha_v2": "reCAPTCHA v2",
    "recaptcha_v3": "reCAPTCHA v3",
    "hcaptcha": "hCaptcha",
    "cloudflare": "Cloudflare 5 秒盾",
    "image_code": "图片英数字识别",
    "recaptcha_v2_image": "reCAPTCHA v2 图像识别",
    "hcaptcha_image": "hCaptcha 图像识别",
    "funcaptcha_image": "FunCaptcha 图像识别",
    "awswaf_image": "AWS WAF / bCaptcha 图像识别",
    "turnstile": "Cloudflare Turnstile",
    "friendly_captcha": "Friendly Captcha",
    "geetest": "GeeTest",
    "datadome": "DataDome",
    "perimeterx": "PerimeterX",
    "aliyun": "阿里云验证码",
    "tencent": "腾讯验证码",
    "other": "其他验证（未分出类型）",
}

_RECAPTCHA_HOSTS = {"www.google.com", "google.com", "www.recaptcha.net", "recaptcha.net"}
_RECAPTCHA_FRAME = re.compile(r"^/recaptcha/(?:api2|enterprise)/(anchor|bframe)")
_RECAPTCHA_SCRIPT = re.compile(r"/recaptcha/(?:api|enterprise)\.js\b")
_CLOUDFLARE_TITLES = ("just a moment", "请稍候", "attention required", "checking your browser",
                      "verifying you are human")
_ARKOSE = re.compile(r"(?:^|\.)(?:arkoselabs\.com|funcaptcha\.com)$")
_DATADOME = re.compile(r"(?:^|\.)captcha-delivery\.com$")
_TENCENT_HOSTS = {"turing.captcha.qcloud.com", "t.captcha.qq.com", "ssl.captcha.qq.com"}

# One look at the page: every iframe's address and whether it is shown, the scripts'
# addresses, and the elements a kind is told by. Shown: on the page, not hidden by
# CSS (reCAPTCHA keeps its picture frame at top -10000 px, hCaptcha behind
# visibility: hidden, until the puzzle is asked).
_READ_JS = r"""() => {
  const shown = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.right <= 0) return false;
    return typeof el.checkVisibility === 'function'
      ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) : true;
  };
  const any = selector => [...document.querySelectorAll(selector)].some(shown);
  const marker = /captcha|verif(?:y|ication)[-_ ]?code|validat(?:e|ion)[-_ ]?code|check[-_ ]?code|验证码/i;
  const provider = /recaptcha|hcaptcha|arkoselabs|funcaptcha|awswaf|geetest|turnstile|cloudflare/i;
  const codeImage = [...document.querySelectorAll('img, canvas')].some(el => shown(el)
    && marker.test([el.id, el.className, el.getAttribute('src'), el.getAttribute('alt'), el.getAttribute('name')].join(' '))
    && !provider.test(el.getAttribute('src') || ''));
  const typing = [...document.querySelectorAll('input')].some(el => shown(el) && !el.disabled
    && (!el.type || ['text', 'tel', 'number', 'search'].includes(el.type)));
  return {
    frames: [...document.querySelectorAll('iframe')].map(f => ({src: f.src || '', shown: shown(f)})),
    scripts: [...document.scripts].map(s => s.src || '').filter(Boolean).slice(0, 200),
    image_code: codeImage && typing,
    awswaf: !!document.querySelector('awswaf-captcha, #amzn-captcha-container, .amzn-captcha-root, #amzn-captcha-verify-button'),
    cloudflare: !!document.querySelector('#challenge-form, #challenge-stage, #challenge-running, #cf-challenge-running, #challenge-body-text'),
    recaptcha_badge: !!document.querySelector('.grecaptcha-badge'),
    friendly_captcha: any('.frc-captcha'),
    geetest: any('.geetest_holder, .geetest_panel, .geetest_box, .geetest_captcha'),
    aliyun: any("[id^='aliyunCaptcha-'], #nc_1_wrapper"),
    tencent: any('#tcaptcha_iframe, #tcaptcha_transform'),
    perimeterx: any('#px-captcha'),
  };
}"""


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _recaptcha_frame(url: str) -> str:
    """"anchor" (the box; "invisible" for v3's), "bframe" (the picture puzzle) or ""."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in _RECAPTCHA_HOSTS:
        return ""
    match = _RECAPTCHA_FRAME.match(parts.path)
    if not match:
        return ""
    if match[1] == "anchor" and re.search(r"(?:^|&)size=invisible(?:&|$)", parts.query):
        return "invisible"
    return match[1]


def _hcaptcha_frame(url: str) -> str:
    """"checkbox", "challenge" (the picture puzzle) or ""."""
    host = _host(url)
    if not (host == "hcaptcha.com" or host.endswith(".hcaptcha.com")) or "/captcha/" not in url:
        return ""
    found = re.search(r"[#&?]frame=(checkbox|challenge)\b", url)
    return found[1] if found else ""


def _turnstile_frame(url: str) -> bool:
    return _host(url) == "challenges.cloudflare.com" and "/turnstile/" in url


def classify(seen: dict[str, Any]) -> str:
    """The kind (a key of ``LABELS``) of the verification page ``seen`` describes:
    ``url``, ``title``, ``frames`` ([{src, shown}] of its iframes), ``page_frames``
    (every frame's address, nested ones too), ``scripts`` and the element flags of
    ``_READ_JS``. A puzzle that is up counts before its box, the box before
    Cloudflare's page, and an invisible check (reCAPTCHA v3) only when nothing
    else is there."""
    url = str(seen.get("url") or "")
    title = str(seen.get("title") or "").strip().lower()
    frames = [f for f in seen.get("frames") or () if isinstance(f, dict)]
    page_frames = [str(u) for u in seen.get("page_frames") or ()]
    scripts = [str(s) for s in seen.get("scripts") or ()]
    shown = [str(f.get("src") or "") for f in frames if f.get("shown") is True]
    every = [str(f.get("src") or "") for f in frames] + page_frames

    if any(_recaptcha_frame(src) == "bframe" for src in shown):
        return "recaptcha_v2_image"
    if any(_hcaptcha_frame(src) == "challenge" for src in shown):
        return "hcaptcha_image"
    if (any(_ARKOSE.search(_host(src)) for src in every)
            or any(_ARKOSE.search(_host(src)) for src in scripts)):
        return "funcaptcha_image"
    if seen.get("awswaf") or any(_host(src).endswith(".captcha.awswaf.com") for src in scripts + every):
        return "awswaf_image"
    if any(_recaptcha_frame(src) == "anchor" for src in shown):
        return "recaptcha_v2"
    if any(_hcaptcha_frame(src) == "checkbox" for src in shown):
        return "hcaptcha"
    if ("__cf_chl" in url or "/cdn-cgi/challenge-platform/" in url or title.startswith(_CLOUDFLARE_TITLES)
            or seen.get("cloudflare") or any("/cdn-cgi/challenge-platform/" in src for src in scripts)):
        return "cloudflare"
    if any(_turnstile_frame(src) for src in shown):
        return "turnstile"
    if seen.get("image_code"):
        return "image_code"
    for key in ("friendly_captcha", "geetest", "aliyun", "tencent", "perimeterx"):
        if seen.get(key):
            return key
    if any("frcapi.com/api/v2/captcha/widget" in src for src in shown):
        return "friendly_captcha"
    if any(_DATADOME.search(_host(src)) for src in every):
        return "datadome"
    if any(_host(src) in _TENCENT_HOSTS for src in every):
        return "tencent"
    if (any(_recaptcha_frame(src) == "invisible" for src in every) or seen.get("recaptcha_badge")
            or any(_RECAPTCHA_SCRIPT.search(src) and re.search(r"[?&]render=(?!explicit\b)[^&]+", src)
                   for src in scripts)):
        return "recaptcha_v3"
    return "other"


def read(page: Any, *, title_and_url_only: bool = False) -> dict[str, Any]:
    """One look at ``page`` for ``classify``. What cannot be read (the page moved on
    or closed meanwhile, or did not answer within the read limit) is left out."""
    from ..driver import Error
    from ..watchdog import CallAbandoned, call_limit
    from .local.interaction import READ_LIMIT_SEC

    seen: dict[str, Any] = {}
    try:
        seen["url"] = str(getattr(page, "url", "") or "")
        with call_limit(READ_LIMIT_SEC):
            seen["title"] = str(page.title() or "")
    except (Error, CallAbandoned):
        pass
    if title_and_url_only:
        return seen
    try:
        with call_limit(READ_LIMIT_SEC):
            found = page.evaluate(_READ_JS)
        if isinstance(found, dict):
            seen.update(found)
    except (Error, CallAbandoned):
        pass
    try:
        seen["page_frames"] = [str(getattr(frame, "url", "") or "") for frame in list(page.frames)[:50]]
    except (Error, CallAbandoned):
        pass
    return seen


def identify(page: Any, *, title_and_url_only: bool = False) -> str:
    """The kind of the verification page ``page`` shows (a key of ``LABELS``)."""
    return classify(read(page, title_and_url_only=title_and_url_only))
