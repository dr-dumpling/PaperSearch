"""Configuration management for the school subscription download backend."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from .data_home import LEGACY_NAME, default_data_dir

DATA_DIR = default_data_dir()
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "email": "paper-search-school@example.invalid",
    "output_dir": str(DATA_DIR / "papers"),
    "cache_dir": str(DATA_DIR / "cache"),
    "network_proxy": "",
    "proxy_pool": "",  # 逗号分隔的代理列表；非空时批量下载按代理轮换出口 IP
    # CARSI chosen without a school (the switch from before federations were named).
    "carsi_enabled": False,
    # The user's school, of any federation (``carsi_idp_name``, ``carsi_idp_name_en`` before 0.6.1).
    # `setup --institution ...` finds it in the federations' member lists and saves its
    # names (CARSI: Chinese and English), its SAML entityID, the hosts of its login
    # pages and its federation (publisher_institution_federation: carsi, hkaf, ...);
    # pickers select the entry carrying the entityID first, then by name.
    # Empty: the user picks in the window.
    "school_name": "",
    "school_name_en": "",
    "idp_entity_id": "",
    "idp_login_hosts": [],
    # The school's own login pages on a service shared by many schools (OpenAthens).
    "idp_login_pages": [],
    # The school's own domains: every page under them is the school's side of the login.
    "idp_domains": [],
    "connect_timeout": 15,
    "read_timeout": 30,
    "request_delay_min": 2.0,
    "request_delay_max": 5.0,
    "fixed_request_delay_enabled": False,
    "json_probe_cache_seconds": 3600,
    "cache_ttl_hours": 168,
    "browser_headless": False,
    "browser_humanize": True,
    # 浏览器后端，二选一：chrome（默认，本机安装的 Google Chrome，经 Patchright 驱动）
    # 或 ego（正在运行的 ego-lite 浏览器，经远程调试连接）。旧值 camoufox/patchright/cloakbrowser 自动按 chrome 处理。
    "browser_backend": "chrome",
    # 装在别处的 Google Chrome 的程序路径；留空时在默认安装位置找。
    "chrome_executable": "",
    # 批量下载时每 N 篇回收一次浏览器上下文（cookie 内存交接，登录态不丢）。
    # 0 = 关闭。长批次（上千篇）建议 100-200，避免 Chrome 长会话内存漂移。
    "browser_restart_every": 0,
    # 任务启动时自动弹出悬浮进度条（独立进程，已有实例则不重复弹出）。
    "progress_bar_auto": True,
    # 需要登录学校或完成验证时，除了进度胶囊变色，再发一条系统通知；进度窗口的设置里可以关。
    "progress_notify": False,
    # The progress window's language: "zh" or "en" (user_settings.language).
    "progress_language": "zh",
    # 每篇文章在学校登录页等待用户输入的总时长上限，秒；从第一次等待算起。
    "browser_login_timeout": 180,
    # 不在学校登录页时（出版社页面、选机构页、人机验证、取 PDF 时等待处理）最多等多久，秒；
    # 连续超过就结束这一篇。进度窗口里可以改。
    "browser_page_wait_timeout": 60,
    # 页面没有实际进展多久后提醒人工查看；仅控制提醒，不延长页面等待上限。
    "browser_stall_notify_after": 30,
    # 每个出版社每小时最多打开的文章数，防止学校因下载过多被出版社暂停访问；0 = 不限。
    "publisher_hourly_limit": 100,
    # 灰色源竞速浏览器的独立无头开关（只影响 sci-hub 竞速，机构登录仍有可见窗口）。
    # true = 竞速全程零窗口、零任务栏闪烁；指纹安全性由 UA 清洗保证。
    "scihub_browser_headless": False,
    "host_concurrency": {},
    "chrome_profile_dir": "",
}


# Settings of the project this backend grew out of (Sci-Hub, Sciverse, Zotero, Tor,
# parallel lanes, VPN and EZproxy routes, the old browser's) that no code reads any
# more: dropped from saved configs when they load, refused by `config set` (2026-11-09).
_RETIRED_KEYS = frozenset("""
download_strategy race_mode hedge_delay_seconds batch_default_lanes lane_s2_batch_min lane_mdpi_cdn
scihub_enabled scihub_domains ncpssd_enabled cn_journal_direct core_api_key openalex_api_key
sciverse_enabled sciverse_api_key sciverse_base_url sciverse_sub_queries sciverse_timeout_seconds sciverse_meta_search_enabled
springer_api_key parallel_sources parallel_probes batch_workers batch_stagger_seconds min_pdf_size_bytes
fast_retry_wait_sec fast_retry_delay_sec scihub_turnstile_click turnstile_wait_sec institutional_workers scihub_browser_first
is_campus_network tor_proxy tor_binary_path tor_use_bridges use_tor_for_scihub google_scholar_limit
max_browser_workers scihub_browser_workers auto_rename zotero_api_key zotero_library_type zotero_library_id
flaresolverr_url cookie_path cookie_dir
auto_relogin browser_auto_upgrade browser_executable cn_auto_login cn_databases_enabled cn_vip_fallback
ezproxy_enabled ezproxy_login_url institutional_allow_self_signed vpnsci_base_url vpnsci_cookie_file vpnsci_enabled
vpnsci_school
""".split())


#: Keys renamed in 0.6.1 (school subscription downloads were named for CARSI before).
_RENAMED_KEYS = {"carsi_idp_name": "school_name", "carsi_idp_name_en": "school_name_en"}


def _from_before_rename(existing: dict[str, Any]) -> dict[str, Any]:
    """A config saved before 0.6.1: its school under the new keys, and its paths under
    the old data directory moved with it (the config holds every default, paths too)."""
    for old, new in _RENAMED_KEYS.items():
        if old in existing:
            value = existing.pop(old)
            existing.setdefault(new, value)
    legacy = str(DATA_DIR.parent / LEGACY_NAME)
    if DATA_DIR.name != LEGACY_NAME:
        for key, value in existing.items():
            if isinstance(value, str) and (value == legacy or value.startswith((legacy + "/", legacy + "\\"))):
                existing[key] = str(DATA_DIR) + value[len(legacy):]
    return existing


def load_config() -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                config.update(_from_before_rename(existing))
        except Exception:
            pass
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    for key in _RETIRED_KEYS:
        config.pop(key, None)
    return config


def save_config(config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)


_VALIDATION_RULES: dict[str, tuple[type, Any, Any]] = {
    # key: (type, min_value, max_value)
    "browser_stall_notify_after": (int, 1, 600),
    "connect_timeout": (int, 1, 60),
    "read_timeout": (int, 1, 120),
    "request_delay_min": (float, 0.0, 30.0),
    "request_delay_max": (float, 0.0, 60.0),
    "json_probe_cache_seconds": (int, 0, 86400),
    "cache_ttl_hours": (int, 1, 8760),
}


def update_config(key: str, value: str) -> dict[str, Any]:
    import warnings as _warnings

    if key in _RETIRED_KEYS:
        raise ValueError(f"'{key}' is no longer used by this backend")
    config = load_config()

    # Validate: warn on unknown keys
    if key not in DEFAULT_CONFIG:
        _warnings.warn(
            f"Unknown config key '{key}' — it will be stored but may have no effect. "
            f"Valid keys include: {', '.join(sorted(DEFAULT_CONFIG.keys()))}",
            stacklevel=2,
        )

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
            # Try JSON parse for list values
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    config[key] = parsed
                else:
                    raise ValueError(f"Expected a JSON list for '{key}', got {type(parsed).__name__}")
            except json.JSONDecodeError:
                raise ValueError(
                    f"Invalid list value for '{key}'. Use JSON format, e.g.: '[\"a\",\"b\"]'"
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
    "elsevier_api_key",
    "elsevier_insttoken",
]

# The list above is for names that do not advertise themselves. Everything else
# is decided by name, because an exact-match list silently leaks every key that
# is added later: springer_api_key, openalex_api_key, cookie_path and
# cookie_dir all reached MCP clients in cleartext that way (#70).
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
