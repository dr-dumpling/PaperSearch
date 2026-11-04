"""Configuration management for the CARSI backend."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("CARSI_DATA_DIR", str(Path.home() / ".local" / "share" / "paper-search-cli" / "carsi")))
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_SCIHUB_DOMAINS = [
    # Direct PDF mirrors (no CAPTCHA, PDF via sci.bban.top iframe) — verified 2026-07
    # vg/al 现为 Turnstile 门/首页壳（2026-08-31 实测），保留用于人工点一次模式
    "https://sci-hub.vg",
    "https://sci-hub.al",
    "https://sci-hub.mk",
    # 2026-08-31 深夜直连实测新增：bz/mksa 稳定出文章页（iframe PDF，无验证墙）
    "https://sci-hub.bz",
    "https://sci-hub.mksa.top",
    # ALTCHA-protected (stable; used as manual-download hint)
    "https://sci-hub.ru",
    "https://sci-hub.ee",
    # Cloudflare-protected (requires Camoufox JS challenge bypass)
    "https://sci-hub.st",
    # Reported intermittent (2026-06); kept but deprioritized
    "https://sci-hub.mksa.top",
    # Legacy (currently down, kept for future recovery)
    "https://sci-hub.se",
    "https://sci-hub.is",
    "https://sci-hub.41610.org",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "email": "paper-search-carsi@example.invalid",
    "output_dir": str(DATA_DIR / "papers"),
    "cache_dir": str(DATA_DIR / "cache"),
    "network_proxy": "",
    "proxy_pool": "",  # 逗号分隔的代理列表；非空时批量下载按代理轮换出口 IP
    "download_strategy": "fastest",  # fastest / grey_only(all 3 grey) / scihub_only(Sci-Hub only) / scihub_first / oa_first / legal_only
    "race_mode": "hedge",  # hedge: score-ordered staggered cascade (fewer requests, less anti-bot heat) / full: flat parallel race
    "hedge_delay_seconds": 1.5,  # hedged cascade: wait this long before widening to the next lane
    "batch_default_lanes": True,  # batch downloads default to pretriage + channel-lane scheduling (fast HTTP -> grey -> institutional)
    "lane_s2_batch_min": 10,  # minimum batch size to enrich OA URLs via the S2 batch endpoint (500 ids/request)
    "lane_mdpi_cdn": True,  # fast lane: construct mdpi-res.com CDN URLs for 10.3390 DOIs (bypasses the bot-walled main site)
    "scihub_enabled": True,
    "scihub_domains": DEFAULT_SCIHUB_DOMAINS,
    "carsi_enabled": False,
    # The user's school. `setup --carsi --institution ...` saves the Chinese and English
    # names and the SAML entityID (https://idp.<school>/idp/shibboleth) from the CARSI
    # member list; pickers select the entry carrying the entityID first, then by name.
    # Empty: the user picks in the window.
    "carsi_idp_name": "",
    "carsi_idp_name_en": "",
    "idp_entity_id": "",
    # 中文源开关（均为合法渠道）：
    #   ncpssd_enabled      国家哲学社会科学文献中心，人文社科免费全文
    #   cn_journal_direct   中文期刊官网直链 PDF（DOI 落地到刊社网站时）
    "ncpssd_enabled": True,
    "cn_journal_direct": True,
    "core_api_key": "",
    "openalex_api_key": "",
    # Sciverse 语义检索（agentic-search）：自然语言问题 → 可引用的证据片段。
    # 需要 https://sciverse.space/tokens 创建的 API Key；未配置时整条链路静默跳过。
    "sciverse_enabled": True,
    "sciverse_api_key": "",
    "sciverse_base_url": "https://api.sciverse.space",
    "sciverse_sub_queries": 0,  # 查询改写数 0-4；调高召回更好但延迟更高
    "sciverse_timeout_seconds": 45,
    # 每次 search 额外跑一路结构化 meta-search（返回 DOI/unique_id，补语义片段的 DOI 缺口）。
    # 每次检索会因此多消耗一次 Sciverse 配额；配额紧张时设为 false。
    "sciverse_meta_search_enabled": True,
    "springer_api_key": "",  # Springer Nature Full Text API (TDM) — entitlement follows the institution (ORCID-affiliated key, needs a Springer subscription with TDM rights)
    "connect_timeout": 15,
    "read_timeout": 30,
    "request_delay_min": 2.0,
    "request_delay_max": 5.0,
    "fixed_request_delay_enabled": False,
    "json_probe_cache_seconds": 3600,
    "cache_ttl_hours": 168,
    "parallel_sources": True,
    "parallel_probes": True,
    "batch_workers": 10,
    "batch_stagger_seconds": 0.3,
    "min_pdf_size_bytes": 10000,
    "browser_headless": False,
    "browser_humanize": True,
    # 浏览器后端，二选一：camoufox（默认，反指纹 Firefox，经 Playwright 自动化）
    # 或 ego（ego-lite 浏览器，经 ego-browser CLI 驱动）。旧值 patchright/cloakbrowser 自动按 camoufox 处理。
    "browser_backend": "camoufox",
    # 批量下载时每 N 篇回收一次浏览器上下文（cookie 内存交接，登录态不丢）。
    # 0 = 关闭。长批次（上千篇）建议 100-200，避免 Chrome 长会话内存漂移。
    "browser_restart_every": 0,
    # 批量下载成功后自动抓取附件/补充材料（SI）。默认关——大多数任务只要主 PDF。
    # 开启后成功论文会尝试抓取出版商补充材料，存为 {DOI}_SI{n}.{ext}，并写 si_manifest.json。
    "fast_retry_wait_sec": 60,
    # 冷却重试期间的逐篇间隔（秒）。实测 15s/篇可 100% 绕开 Elsevier API 限流。
    "fast_retry_delay_sec": 15,
    # 任务启动时自动弹出悬浮进度条（独立进程，已有实例则不重复弹出）。
    "progress_bar_auto": True,
    # 需要登录学校或完成验证时，除了进度胶囊变色，再发一条系统通知；进度窗口的设置里可以关。
    "progress_notify": True,
    # 每篇文章在学校登录页等待用户输入的总时长上限，秒；从第一次等待算起。
    "browser_login_timeout": 180,
    # 不在学校登录页时（出版社页面、选机构页、人机验证、取 PDF 时等待处理）最多等多久，秒；
    # 连续超过就结束这一篇。进度窗口里可以改。
    "browser_page_wait_timeout": 60,
    # 每个出版社每小时最多打开的文章数，防止学校因下载过多被出版社暂停访问；0 = 不限。
    "publisher_hourly_limit": 100,
    # Turnstile 交互门（如 sci-hub.vg）：无头会话下无法点击，默认跳过并冷却。
    # scihub_browser_headless=false 时可开启人工点一次模式（点一次整批复用）。
    "scihub_turnstile_click": True,
    "turnstile_wait_sec": 180,
    # 机构级联并行 fetcher 数（各持独立登录会话）。默认 1 = 串行；2 可省约一半
    # Phase 2 时间，代价是同 IP 双浏览器会话。
    "institutional_workers": 1,
    # 灰色源竞速浏览器的独立无头开关（只影响 sci-hub 竞速，机构登录仍有可见窗口）。
    # true = 竞速全程零窗口、零任务栏闪烁；指纹安全性由 UA 清洗保证。
    "scihub_browser_headless": False,
    "scihub_browser_first": True,  # false = pure-HTTP Sci-Hub lane (use when the PDF CDN challenges headless browsers but serves plain requests)
    "is_campus_network": False,
    "tor_proxy": os.environ.get("TOR_PROXY", ""),
    "tor_binary_path": "",  # Explicit tor binary; empty falls back to the embedded install and then PATH. Pinning it stops lookup order from deciding which binary runs
    "tor_use_bridges": False,
    "use_tor_for_scihub": True,
    "google_scholar_limit": 5,
    "max_browser_workers": 1,
    "scihub_browser_workers": 3,  # Number of Sci-Hub domains to race in parallel via browser
    "host_concurrency": {},
    "auto_rename": True,
    "zotero_api_key": "",
    "zotero_library_type": "user",
    "zotero_library_id": "",
    "flaresolverr_url": "http://127.0.0.1:8191/v1",
    "cookie_path": "",
    "chrome_profile_dir": "",
    "carsi_cookie_dir": "",
}


def load_config() -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                config.update(existing)
        except Exception:
            pass
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    return config


def save_config(config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)


_VALIDATION_RULES: dict[str, tuple[type, Any, Any]] = {
    # key: (type, min_value, max_value)
    "connect_timeout": (int, 1, 60),
    "read_timeout": (int, 1, 120),
    "request_delay_min": (float, 0.0, 30.0),
    "request_delay_max": (float, 0.0, 60.0),
    "json_probe_cache_seconds": (int, 0, 86400),
    "cache_ttl_hours": (int, 1, 8760),
    "batch_workers": (int, 1, 50),
    "batch_stagger_seconds": (float, 0.0, 10.0),
    "min_pdf_size_bytes": (int, 100, 1000000),
    "google_scholar_limit": (int, 1, 50),
    "sciverse_sub_queries": (int, 0, 4),
    "sciverse_timeout_seconds": (int, 5, 300),
}

_VALID_STRATEGIES = frozenset({"fastest", "scihub_first", "scihub_only", "grey_only", "oa_first", "legal_only"})


def update_config(key: str, value: str) -> dict[str, Any]:
    import warnings as _warnings

    config = load_config()

    # Validate: warn on unknown keys
    if key not in DEFAULT_CONFIG:
        _warnings.warn(
            f"Unknown config key '{key}' — it will be stored but may have no effect. "
            f"Valid keys include: {', '.join(sorted(DEFAULT_CONFIG.keys()))}",
            stacklevel=2,
        )

    # Special handling for download_strategy
    if key == "download_strategy":
        value_lower = value.lower().strip()
        if value_lower not in _VALID_STRATEGIES:
            raise ValueError(
                f"Invalid download_strategy '{value}'. Valid options: {', '.join(sorted(_VALID_STRATEGIES))}"
            )
        config[key] = value_lower
        save_config(config)
        return config

    if key in config:
        old_type = type(config[key])
        if old_type == bool:
            config[key] = value.lower() in ("true", "1", "yes")
        elif old_type == int:
            try:
                config[key] = int(value)
            except ValueError:
                raise ValueError(f"Invalid integer value for '{key}': '{value}'")
        elif old_type == float:
            try:
                config[key] = float(value)
            except ValueError:
                raise ValueError(f"Invalid float value for '{key}': '{value}'")
        elif old_type == list:
            # Try JSON parse for list values (e.g. scihub_domains)
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    config[key] = parsed
                else:
                    raise ValueError(f"Expected a JSON list for '{key}', got {type(parsed).__name__}")
            except json.JSONDecodeError:
                raise ValueError(
                    f"Invalid list value for '{key}'. Use JSON format, e.g.: '[\"https://sci-hub.vg\",\"https://sci-hub.al\"]'"
                )
        else:
            config[key] = value
    else:
        config[key] = value

    if key in _VALIDATION_RULES:
        _, min_val, max_val = _VALIDATION_RULES[key]
        if config[key] < min_val or config[key] > max_val:
            config[key] = DEFAULT_CONFIG[key]

    save_config(config)
    return config


SENSITIVE_KEYS = [
    "core_api_key",
    "zotero_api_key",
    "zotero_library_id",
    "elsevier_api_key",
    "elsevier_insttoken",
    "sciverse_api_key",
]

# The list above is for names that do not advertise themselves. Everything else
# is decided by name, because an exact-match list silently leaks every key that
# is added later: springer_api_key, openalex_api_key, cookie_path and
# carsi_cookie_dir all reached MCP clients in cleartext that way (#70).
_SECRET_NAME_RE = re.compile(r"key|token|secret|password|cookie|credential", re.I)

_PROXY_URL_CREDS_RE = re.compile(r"(//[^/@\s]+:)[^@\s]+@")


def mask_config_value(key: str, value: Any) -> Any:
    """Return a display-safe copy of a config value.

    Secrets (API keys, tokens, cookie files) are fully masked; proxy URLs keep
    host/port but hide the password (``http://user:***@host:port``).
    """
    if value is None:
        return value
    if key in SENSITIVE_KEYS or _SECRET_NAME_RE.search(key):
        # Empty means "not configured", not a masked secret — callers use
        # this to decide whether to show a setup prompt.
        return "***" if value != "" else ""
    if "proxy" in key.lower() and isinstance(value, str) and "@" in value:
        return _PROXY_URL_CREDS_RE.sub(r"\1***@", value)
    return value


def get_config_safe() -> dict[str, Any]:
    config = load_config()
    return {key: mask_config_value(key, value) for key, value in config.items()}


def parse_proxy_pool(value: str | None) -> list[str]:
    """Parse a comma-separated proxy list into a deduplicated list.

    Accepts forms like ``"socks5://1.1.1.1:1080, http://2.2.2.2:8080"`` and
    returns ``["socks5://1.1.1.1:1080", "http://2.2.2.2:8080"]``. Empty/blank
    entries are dropped. Order is preserved; duplicates removed.
    """
    if not value:
        return []
    seen: set[str] = set()
    proxies: list[str] = []
    for token in str(value).split(","):
        proxy = token.strip()
        if proxy and proxy not in seen:
            seen.add(proxy)
            proxies.append(proxy)
    return proxies
