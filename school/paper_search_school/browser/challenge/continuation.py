"""Continue a publisher verification in the same browser with a typed service task."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .services import solver


class Expired(Exception):
    """The existing verification deadline has elapsed."""


@dataclass
class Limits:
    deadline: float
    budget: solver.Budget
    checkpoint: Any = None
    cleanup: Any = None

    def remaining(self) -> float:
        if self.checkpoint:
            self.checkpoint()
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Expired
        return left

    def sleep(self, seconds: float) -> None:
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            time.sleep(min(0.2, self.remaining(), max(0, until - time.monotonic())))
        self.remaining()


def resume(page: Any, config: dict, *, kind: str, limits: Limits, observation: Any) -> bool:
    """True means return to the outer page check, never that the site passed.

    This dispatcher is entered only for publisher pages. The engine checks the
    IdP boundary before local actions and before every service continuation.
    """
    note = observation
    if kind not in {"awswaf", "recaptcha", "hcaptcha", "image_code", "turnstile"}:
        note(f"service unsupported: {kind}; no handler")
        return False
    if not solver.configured(config):
        note("service not configured")
        return False
    try:
        limits.remaining()
        if kind == "turnstile":
            from .handlers import turnstile
            return turnstile.solve(page, config, limits=limits, observation=note)
        if kind == "awswaf":
            from .handlers import aws_waf
            return aws_waf.solve(page, config, observation=note, limits=limits)
        if kind == "image_code":
            from .handlers import text_captcha
            return text_captcha.solve(page, config, limits=limits, observation=note)
        from .handlers import recaptcha_hcaptcha
        return recaptcha_hcaptcha.solve(page, config, kind=kind, limits=limits, observation=note)
    except Expired:
        note("service deadline exhausted")
        return False
