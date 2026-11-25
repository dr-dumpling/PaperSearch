"""Verification requests and decoded answers; browser actions live in handlers."""
from __future__ import annotations

import base64
import logging
import re
import os
import time
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://cn.yescaptcha.com"
DEFAULT_TIMEOUT = 90
DEFAULT_MAX_PER_RUN = 20
KEY_FILE = Path.home() / ".config" / "paper-search-cli" / "yescaptcha.key"
SOFT_ID = 149362
IMAGE_TASK = "ImageToTextTaskOcrBase"
GRID_TASK = "AwsClassification"
TASKS = {
    "image_code": IMAGE_TASK,
    "awswaf": GRID_TASK,
    "bcaptcha": "bCaptchaClassification",
    "recaptcha": "ReCaptchaV2Classification",
    "hcaptcha": "HCaptchaClassification",
}


def service(config: dict[str, Any] | None) -> str:
    return str((config or {}).get("captcha_service") or "none").strip().lower()


def endpoint(config: dict[str, Any] | None) -> str:
    return str((config or {}).get("captcha_service_url") or DEFAULT_ENDPOINT).strip().rstrip("/")


def key(config: dict[str, Any] | None) -> str:
    """Read the key from config, environment, then the local key file."""
    value = str((config or {}).get("captcha_key") or "").strip()
    if value:
        return value
    value = os.environ.get("YESCAPTCHA_KEY", "").strip()
    if value:
        return value
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def configured(config: dict[str, Any] | None) -> bool:
    return service(config) == "yescaptcha" and bool(key(config))


def _mask(value: str) -> str:
    return "***" if value else ""


def _post(url: str, payload: dict[str, Any], timeout: int,
          post: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """Post JSON; return None on transport or response errors."""
    sender = post
    if sender is None:
        import requests

        sender = requests.post
    try:
        response = sender(url, json=payload, timeout=timeout)
        data = response.json()
    except Exception:  # noqa: BLE001 - the caller records transport or response errors
        return None
    return data if isinstance(data, dict) else None


class Budget:
    """Thread-safe request budget shared by a downloader."""

    def __init__(self, limit: int | None = None, config: dict[str, Any] | None = None) -> None:
        raw = limit if limit is not None else int((config or {}).get("captcha_max_per_run", DEFAULT_MAX_PER_RUN) or 0)
        self.limit = max(0, int(raw))
        self.used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


def get_balance(config: dict[str, Any] | None, *, post: Callable[..., Any] | None = None,
                timeout: int | None = None) -> float | None:
    """Read the balance without creating a task."""
    token = key(config)
    if service(config) != "yescaptcha" or not token:
        return None
    seconds = int(timeout or (config or {}).get("captcha_timeout") or DEFAULT_TIMEOUT)
    data = _post(f"{endpoint(config)}/getBalance", {"clientKey": token, "softID": SOFT_ID}, seconds, post)
    if not data or data.get("errorId"):
        return None
    try:
        return float(data.get("balance"))
    except (TypeError, ValueError):
        return None


def solve_image(image: bytes, config: dict[str, Any] | None, *,
                post: Callable[..., Any] | None = None,
                timeout: float | None = None, checkpoint: Any = None) -> str | None:
    """Return recognized characters, or None on failure."""
    if not image:
        return None
    solution = _solve_task({"type": IMAGE_TASK, "body": base64.b64encode(image).decode("ascii")},
                           config, timeout=timeout, post=post, checkpoint=checkpoint)
    if not solution or not isinstance(solution.get("text"), str):
        return None
    return solution["text"].strip() or None


@dataclass(frozen=True, repr=False)
class TurnstileAnswer:
    token: str
    user_agent: str


def solve_turnstile(origin: str, sitekey: str, config: dict | None, *,
                    action: str = "", timeout: float | None = None,
                    checkpoint: Any = None, post: Callable[..., Any] | None = None) -> TurnstileAnswer | None:
    """Send only the public origin and widget settings, never a session URL."""
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or not re.fullmatch(r"0x[A-Za-z0-9_-]{10,100}", sitekey)
            or (action and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", action))):
        return None
    task = {"type": "TurnstileTaskProxyless", "websiteURL": origin, "websiteKey": sitekey}
    if action:
        task["pageAction"] = action
    solution = _solve_task(task, config, timeout=timeout, checkpoint=checkpoint, post=post)
    if not solution:
        return None
    token, agent = solution.get("token"), solution.get("userAgent")
    if (not isinstance(token, str) or not 1 <= len(token) <= 4096 or re.search(r"\s", token)
            or not isinstance(agent, str) or not 1 <= len(agent) <= 1024
            or any(ord(c) < 32 or ord(c) > 126 for c in agent)):
        return None
    return TurnstileAnswer(token, agent)


def solve_grid(image: bytes, question: str, config: dict[str, Any] | None, *,
               post: Callable[..., Any] | None = None,
               timeout: int | None = None, kind: str = "awswaf") -> list[tuple[float, float]]:
    """Return click coordinates for a supported whole-grid image task."""
    # Each provider has a different wire format. Never default an unknown kind
    # (or a non-grid provider) to an AWS task.
    if not image or kind not in {"awswaf", "bcaptcha"}:
        return []
    task = {"type": TASKS[kind], "queries": base64.b64encode(image).decode("ascii"),
            "question": str(question).strip()}
    return _points(_solve_task(task, config, timeout=timeout, post=post))


def _solve_task(task: dict, config: dict | None, *, timeout: float | None = None,
                post: Callable[..., Any] | None = None, checkpoint: Any = None) -> dict | None:
    """One deadline includes creation and all result polls; late answers are ignored."""
    if not configured(config):
        return None
    seconds = float(timeout if timeout is not None else (config or {}).get("captcha_timeout", DEFAULT_TIMEOUT))
    deadline = time.monotonic() + max(0, seconds)
    def request(path: str, body: dict) -> dict | None:
        if checkpoint:
            checkpoint()
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        data = _post(f"{endpoint(config)}/{path}",
                     {"clientKey": key(config), "softID": SOFT_ID, **body}, left, post)
        if checkpoint:
            checkpoint()
        return data if time.monotonic() < deadline else None
    queries = task.get("queries")
    image_count = len(queries) if isinstance(queries, list) else int(any(k in task for k in ('queries', 'body', 'image')))
    log.info("captcha service request: task=%s images=%d examples=%d", task["type"], image_count, len(task.get("anchors", [])))
    data = request("createTask", {"task": task})
    while data and not data.get("errorId"):
        if str(data.get("status", "")).lower() == "ready" or not data.get("taskId"):
            value = data.get("solution")
            log.info("captcha service result: task=%s status=%s", task["type"],
                     "ready" if isinstance(value, dict) else "invalid_solution")
            return value if isinstance(value, dict) else None
        task_id = data["taskId"]
        left = deadline - time.monotonic()
        if left <= 5:
            return None
        # Short sleeps allow cancellation while waiting for the next poll.
        for _ in range(10):
            if checkpoint:
                checkpoint()
            time.sleep(0.5)
        data = request("getTaskResult", {"taskId": task_id})
        if data and not data.get("taskId") and data.get("status") == "processing":
            data["taskId"] = task_id
    error = str((data or {}).get("errorCode") or "network_or_format")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,80}", error):
        error = "service_error"
    log.info("captcha service result: task=%s failure=%s", task["type"], error)
    return None


def solve_tiles(images: list[bytes], question: str, config: dict | None, *,
                kind: str, count: int, timeout: float, anchors: list[bytes] = (),
                post: Callable[..., Any] | None = None, checkpoint: Any = None) -> list[int] | None:
    """Provider-specific image tasks; None is failure, [] is a valid empty answer."""
    if not images or not all(images) or not question:
        return None
    encode = lambda image: base64.b64encode(image).decode("ascii")
    if kind == "hcaptcha" and len(images) == count == 9:
        task = {"type": TASKS[kind], "queries": [encode(im) for im in images], "question": question}
        if anchors:
            task["anchors"] = [encode(im) for im in anchors]
    elif kind == "recaptcha" and len(images) == 1 and count in (9, 16) and question.startswith("/m/"):
        task = {"type": TASKS[kind], "image": encode(images[0]), "question": question, "confidence": 0.5}
    else:
        return None
    solution = _solve_task(task, config, timeout=timeout, post=post, checkpoint=checkpoint)
    if not solution or solution.get("type") in {"drag", "single"}:
        return None
    objects = solution.get("objects")
    if not isinstance(objects, list):
        return None
    if kind == "hcaptcha":
        if len(objects) != count or any(type(v) is not bool for v in objects):
            return None
        return [i for i, hit in enumerate(objects) if hit]
    if any(type(i) is not int or not 0 <= i < count for i in objects):
        return None
    return sorted(set(objects))


def _points(solution: Any) -> list[tuple[float, float]]:
    """The answer's points: ``clicks`` (pixels of the picture), ``objects`` (nine
    tile booleans, in reading order) or ``box`` (pixel pairs), whichever it gives."""
    if not isinstance(solution, dict):
        return []
    clicks = solution.get("clicks")
    if isinstance(clicks, list):
        points: list[tuple[float, float]] = []
        for item in clicks:
            try:
                points.append((float(item["x"]), float(item["y"])))
            except (KeyError, TypeError, ValueError):
                continue
        if points:
            return points
    objects = solution.get("objects")
    if isinstance(objects, list) and len(objects) == 9 and all(isinstance(flag, bool) for flag in objects):
        return [(float(index % 3), float(index // 3)) for index, flag in enumerate(objects) if flag]
    box = solution.get("box")
    if isinstance(box, list):
        numbers: list[float] = []
        for value in box:
            try:
                numbers.append(float(value))
            except (TypeError, ValueError):
                continue
        return list(zip(numbers[::2], numbers[1::2]))
    return []
