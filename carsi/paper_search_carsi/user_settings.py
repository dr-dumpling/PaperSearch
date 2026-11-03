"""The settings the progress window lets the user type in: how long a download
waits on the school's login page and elsewhere, and how many papers each
publisher may open per hour. They apply from the next paper."""

from __future__ import annotations

from dataclasses import dataclass

from . import config as _config


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    key: str  # the backend's config key
    default: int
    low: int
    high: int
    unit: str


FIELDS = (
    Field("login", "学校登录页最多等", "browser_login_timeout", 180, 30, 1800, "秒"),
    Field("page", "其他页面最多等", "browser_page_wait_timeout", 60, 10, 600, "秒"),
    Field("hourly", "每家出版社每小时最多", "publisher_hourly_limit", 100, 0, 1000, "篇"),
)


def current() -> dict[str, int]:
    """The values now set, by field name."""
    config = _config.load_config()
    return {field.name: int(config.get(field.key, field.default)) for field in FIELDS}


def check(field: Field, text: str) -> tuple[int | None, str]:
    """A typed value, or why it cannot be saved."""
    try:
        value = int(str(text).strip())
    except ValueError:
        value = None
    if value is None or not field.low <= value <= field.high:
        return None, f"请输入 {field.low} 到 {field.high} 之间的整数"
    return value, ""


def save(values: dict[str, int]) -> None:
    """Save values by field name; each is checked again first."""
    for field in FIELDS:
        if field.name not in values:
            continue
        value, problem = check(field, str(values[field.name]))
        if problem:
            raise ValueError(f"{field.key}: {problem}")
        _config.update_config(field.key, str(value))
