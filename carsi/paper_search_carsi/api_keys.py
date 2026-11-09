"""The API keys PaperSearch's searches use, as the progress window's settings show them.

The list (``assets/api_keys.json``) groups the keys by service, the way the
README does; PaperSearch's tests check it against the CLI's own key names and
sign-up pages. Values live in PaperSearch's CLI config, where ``paper-search
setup`` puts them. The list shows whether each key is set and its last four
characters; a row's own values go to the page only when the user opens that
row, into fields that hide them until the user asks to see them."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import cli_config

CATALOG = Path(__file__).resolve().parent / "assets" / "api_keys.json"
MAX_LENGTH = 512
_PRINTABLE = re.compile(r"^[\x21-\x7e]+$")  # visible ASCII: no spaces, line breaks or full-width characters


def groups() -> list[dict[str, Any]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["groups"]


def services() -> list[dict[str, Any]]:
    return [service for group in groups() for service in group["services"]]


def find(target: str) -> dict[str, Any] | None:
    """The service with this id, or the one that uses this config key."""
    target = str(target or "").strip()
    for service in services():
        if target.lower() == service["id"] or any(target.upper() == k["key"] for k in service["keys"]):
            return service
    return None


def mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) > 8 else "••••"


def _status(service: dict[str, Any], config: dict) -> dict[str, Any]:
    keys = []
    for key in service["keys"]:
        value = str(config.get(key["key"]) or "").strip()
        keys.append({"key": key["key"], "label": key["label"], "set": bool(value), "masked": mask(value) if value else ""})
    primary = keys[0]
    return {"id": service["id"], "name": service["name"], "use": service.get("use", ""), "url": service["url"],
            "guide": service.get("guide", ""), "guide_label": service.get("guide_label", ""),
            "keys": keys, "set": primary["set"], "masked": primary["masked"]}


def listing() -> dict[str, Any]:
    """Every service with whether its key is set; ``filled`` of ``total`` services are set."""
    config = cli_config.read()
    shown = [{"title": group["title"], "services": [_status(s, config) for s in group["services"]]} for group in groups()]
    every = [s for group in shown for s in group["services"]]
    return {"groups": shown, "filled": sum(1 for s in every if s["set"]), "total": len(every)}


def check(value: str) -> tuple[str, str]:
    """A pasted value, trimmed, or why it cannot be a key."""
    value = str(value or "").strip()
    if len(value) > MAX_LENGTH:
        return "", "太长了，请确认粘贴的是 key"
    if value and not _PRINTABLE.match(value):
        return "", "key 里不能有空格、换行或中文字符"
    return value, ""


def _service(service_id: str) -> dict[str, Any]:
    service = find(service_id)
    if service is None or service["id"] != service_id:
        raise ValueError("没有这一项")
    return service


def saved(service_id: str) -> dict[str, str]:
    """One service's saved values, for its fields when the user opens it."""
    config = cli_config.read()
    return {key["key"]: str(config.get(key["key"]) or "").strip() for key in _service(service_id)["keys"]}


def save(service_id: str, values: dict[str, str]) -> None:
    """Save one service's fields as shown; each must hold a key (removing one is "清除")."""
    service = _service(service_id)
    changes: dict[str, str | None] = {}
    for key in service["keys"]:
        value, problem = check((values or {}).get(key["key"], ""))
        if problem:
            raise ValueError(problem)
        if not value:
            raise ValueError("请先粘贴 key；要删除请点“清除”")
        changes[key["key"]] = value
    cli_config.update(changes)


def paper_search_command() -> list[str] | None:
    """How to run PaperSearch's CLI: as PaperSearch passed itself (PAPER_SEARCH_CLI,
    a JSON list), else `paper-search` on the PATH."""
    try:
        given = json.loads(os.environ.get("PAPER_SEARCH_CLI") or "null")
    except ValueError:
        given = None
    if isinstance(given, list) and given and all(isinstance(part, str) for part in given):
        return given
    found = shutil.which("paper-search")
    return [found] if found else None


def test(service_id: str, values: dict[str, str]) -> dict[str, str]:
    """Whether the service takes the values in its fields, by `paper-search config test`;
    the values go on its stdin, never on a command line."""
    service = _service(service_id)
    command = paper_search_command()
    if command is None:
        return {"status": "error", "message": f"找不到 paper-search 命令，没法测试；也可以在终端运行 paper-search config test {service['keys'][0]['key']}"}
    typed = {key["key"]: str((values or {}).get(key["key"], "")).strip() for key in service["keys"]}
    # A test must not also update the Skill or check for a new version.
    env = {**os.environ, "PAPER_SEARCH_SKILL_AUTO_UPDATE": "false", "PAPER_SEARCH_UPDATE_NOTIFY": "false"}
    try:
        done = subprocess.run([*command, "config", "test", service["keys"][0]["key"], "--stdin"], input=json.dumps(typed),
                              capture_output=True, text=True, timeout=45, env=env)
        reply = json.loads(done.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"status": "unreachable", "message": "测试超时，没法判断；检查网络或代理后再试"}
    except (OSError, ValueError, IndexError) as exc:
        return {"status": "error", "message": f"测试没有完成：{type(exc).__name__}"}
    return {"status": str(reply.get("status") or "error"), "message": str(reply.get("message") or reply.get("error") or "")}


def clear(service_id: str) -> None:
    cli_config.update({key["key"]: None for key in _service(service_id)["keys"]})
