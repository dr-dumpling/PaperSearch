"""Shared default download directory, stored in PaperSearch's CLI config."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

KEY = "DEFAULT_DOWNLOAD_PATH"


def config_path() -> Path:
    override = os.environ.get("PAPER_SEARCH_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("PAPER_SEARCH_CONFIG_DIR", str(Path.home() / ".config" / "paper-search-cli"))) / "config.json"


def _read() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("PaperSearch 配置必须是 JSON 对象")
    return data


def configured() -> str:
    value = os.environ.get(KEY) or _read().get(KEY) or ""
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
    data = _read()
    data[KEY] = value
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Preserve unrelated CLI settings; replace atomically, never write a partial config.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as fh:
        temporary = Path(fh.name)
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return value
