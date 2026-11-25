"""PaperSearch's CLI config file (``config.json``), shared with ``paper-search setup``.

The progress window writes the download directory and API keys here, so the
CLI and the window always show the same values."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def config_path() -> Path:
    override = os.environ.get("PAPER_SEARCH_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("PAPER_SEARCH_CONFIG_DIR", str(Path.home() / ".config" / "paper-search-cli"))) / "config.json"


def read() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("PaperSearch 配置必须是 JSON 对象")
    return data


def update(changes: dict[str, str | None]) -> None:
    """Set (or, for None, remove) these keys and keep every other setting.

    The file is replaced atomically, never left half written; like the CLI's
    own writes it is readable by the user only."""
    data = read()
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    write_private_json(config_path(), data)


def write_private_json(target: Path, data: dict) -> None:
    """Atomically replace a local JSON file that can contain credentials."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fh = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False)
    temporary = Path(fh.name)
    try:
        with fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
