"""The API keys PaperSearch's searches use, as the progress window's settings show them.

The list (``assets/api_keys.json``) groups the keys by service, the way the
README does; PaperSearch's tests check it against the CLI's own key names and
sign-up pages. Most values live in the CLI config; YesCaptcha's ClientKey lives
in the school backend's config. The list shows whether each key is set and its last four
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

from . import cli_config, config as school_config
from .browser.challenge.services import solver

CATALOG = Path(__file__).resolve().parent / "assets" / "api_keys.json"
YESCAPTCHA_KEY = "YESCAPTCHA_KEY"
_BACKEND_TOKEN = "captcha_key"
_BACKEND_URL = "captcha_service_url"
MAX_LENGTH = 512
_PRINTABLE = re.compile(r"^[\x21-\x7e]+$")  # visible ASCII: no spaces, line breaks or full-width characters
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def groups() -> list[dict[str, Any]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["groups"]


def services() -> list[dict[str, Any]]:
    return [service for group in groups() for service in group["services"]]


def find(target: str) -> dict[str, Any] | None:
    """The service with this id, or the one that uses this config key."""
    target = str(target or "").strip()
    for service in services():
        if target.lower() == service["id"] or any(target.lower() == k["key"].lower() for k in service["keys"]):
            return service
    return None


def mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) > 8 else "••••"


def _stored(service: dict[str, Any], config: dict) -> dict:
    if service["id"] != "yescaptcha":
        return config
    backend = school_config.load_config(strict=True)
    return {YESCAPTCHA_KEY: str(backend.get(_BACKEND_TOKEN) or "").strip() or config.get(YESCAPTCHA_KEY)}


def _status(service: dict[str, Any], config: dict) -> dict[str, Any]:
    config = _stored(service, config)
    keys = []
    for key in service["keys"]:
        value = str(config.get(key["key"]) or "").strip()
        kind = key.get("kind", "key")
        keys.append({"key": key["key"], "label": key["label"], "kind": kind,
                     "set": bool(value), "masked": mask(value) if value and kind != "zone" else ""})
    return {"id": service["id"], "name": service["name"], "use": service.get("use", ""), "url": service["url"],
            "guide": service.get("guide", ""), "guide_label": service.get("guide_label", ""),
            "signup_label": service.get("signup_label", ""), "note": service.get("note", ""),
            "keys": keys, "set": all(k["set"] for k in keys), "masked": keys[0]["masked"]}


def listing() -> dict[str, Any]:
    """Every service with whether its key is set; ``filled`` of ``total`` services are set."""
    config = cli_config.read()
    shown = [{"title": group["title"], "services": [_status(s, config) for s in group["services"]]} for group in groups()]
    every = [s for group in shown for s in group["services"]]
    return {"groups": shown, "filled": sum(1 for s in every if s["set"]), "total": len(every)}


def check(value: str, kind: str = "key") -> tuple[str, str]:
    """A pasted value, trimmed, or why it cannot be a key (an email for an email field)."""
    value = str(value or "").strip()
    if kind == "email":
        return (value, "") if not value or (len(value) <= 254 and _EMAIL.match(value)) else ("", "邮箱格式不对")
    if kind == "zone":
        return (value, "") if not value or (len(value) <= MAX_LENGTH and _PRINTABLE.match(value)) else ("", "Zone 名称格式不正确")
    if kind == "url":
        ok = re.match(r"^https?://[\w.-]+(?::\d+)?(?:/\S*)?$", value) if value else True
        return (value, "") if ok else ("", "服务地址要写成 https://…")
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
    service = _service(service_id)
    config = _stored(service, cli_config.read())
    return {key["key"]: str(config.get(key["key"]) or "").strip() for key in service["keys"]}


def save(service_id: str, values: dict[str, str]) -> None:
    """Save one service's fields as shown; each must hold a key (removing one is "清除")."""
    service = _service(service_id)
    changes: dict[str, str | None] = {}
    for key in service["keys"]:
        value, problem = check((values or {}).get(key["key"], ""), key.get("kind", "key"))
        if problem:
            raise ValueError(problem)
        if not value:
            if key.get("kind") == "zone":
                raise ValueError("请先填写 Zone 名称")
            if key.get("kind") == "url":
                raise ValueError("请先填写服务地址")
            raise ValueError("请先填写邮箱；要删除请点“清除”" if key.get("kind") == "email" else "请先粘贴 key；要删除请点“清除”")
        changes[key["key"]] = value
    if service_id == "yescaptcha":
        config = school_config.load_config(strict=True)
        config.update({"captcha_service": "yescaptcha", _BACKEND_TOKEN: changes[YESCAPTCHA_KEY],
                       _BACKEND_URL: solver.DEFAULT_ENDPOINT})
        school_config.save_config(config)
        return
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


def _test_yescaptcha(value: str) -> dict[str, str]:
    """Ask YesCaptcha for the balance: no task is created and no point is spent."""
    token, problem = check(value)
    if problem:
        return {"status": "invalid", "message": problem}
    if not token:
        return {"status": "missing", "message": "请先填写 ClientKey"}
    balance = solver.get_balance({"captcha_service": "yescaptcha",
                                  "captcha_service_url": solver.DEFAULT_ENDPOINT, "captcha_key": token})
    if balance is None:
        return {"status": "invalid", "message": "YesCaptcha 拒绝了 ClientKey，或连不上它的服务"}
    # 1,110, not 1110 or 1.23457e+06 (user, 2026-11-25: the number alone was not understood).
    shown = f"{balance:,.0f}" if balance.is_integer() else f"{balance:,.2f}".rstrip("0").rstrip(".")
    return {"status": "valid", "message": f"ClientKey 有效，余额 {shown} 点"}


def test(service_id: str, values: dict[str, str]) -> dict[str, str]:
    """Check typed values, passing CLI-managed keys on stdin, never on a command line."""
    service = _service(service_id)
    typed = {key["key"]: str((values or {}).get(key["key"], "")).strip() for key in service["keys"]}
    if service_id == "yescaptcha":
        return _test_yescaptcha(typed[YESCAPTCHA_KEY])
    command = paper_search_command()
    if command is None:
        return {"status": "error", "message": f"找不到 paper-search 命令，没法测试；也可以在终端运行 paper-search config test {service['keys'][0]['key']}"}
    # A test must not also update the Skill or check for a new version.
    env = {**os.environ, "PAPER_SEARCH_SKILL_AUTO_UPDATE": "false", "PAPER_SEARCH_UPDATE_NOTIFY": "false"}
    try:
        # PaperSearch answers in UTF-8; left to the system encoding, Chinese Windows reads it as GBK and loses it all.
        done = subprocess.run([*command, "config", "test", service["keys"][0]["key"], "--stdin"], input=json.dumps(typed),
                              capture_output=True, encoding="utf-8", errors="replace", timeout=45, env=env)
        reply = json.loads((done.stdout or "").strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"status": "unreachable", "message": "测试超时，没法判断；检查网络或代理后再试"}
    except (OSError, ValueError, IndexError) as exc:
        return {"status": "error", "message": f"测试没有完成：{type(exc).__name__}"}
    return {"status": str(reply.get("status") or "error"), "message": str(reply.get("message") or reply.get("error") or "")}


def clear(service_id: str) -> None:
    if service_id == "yescaptcha":
        config = school_config.load_config(strict=True)
        config.update({"captcha_service": "none", _BACKEND_TOKEN: "", _BACKEND_URL: solver.DEFAULT_ENDPOINT})
        school_config.save_config(config)
        return
    cli_config.update({key["key"]: None for key in _service(service_id)["keys"]})
