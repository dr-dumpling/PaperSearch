"""Shared default download directory, stored in PaperSearch's CLI config."""
from __future__ import annotations

import os
from pathlib import Path

from . import cli_config
from .cli_config import config_path  # noqa: F401  (kept for callers of this module)

KEY = "DEFAULT_DOWNLOAD_PATH"


def configured() -> str:
    value = os.environ.get(KEY) or cli_config.read().get(KEY) or ""
    return str(Path(str(value)).expanduser()) if value else ""


def current() -> str:
    from .config import load_config

    return configured() or str(load_config()["output_dir"])


def validate(value: str) -> str:
    value = str(value).strip()
    if not value or "\0" in value:
        raise ValueError("请选择下载文件夹或输入完整路径")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("请输入完整的绝对路径")
    if path.exists() and not path.is_dir():
        raise ValueError("此路径是文件，请选择文件夹")
    return str(path)


def save(value: str) -> str:
    value = validate(value)
    Path(value).mkdir(parents=True, exist_ok=True)
    cli_config.update({KEY: value})
    return value
