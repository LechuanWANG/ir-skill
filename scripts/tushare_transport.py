#!/usr/bin/env python3
"""Bounded, classified TuShare endpoint calls shared by sync and gateway tools."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd


DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.6
DEFAULT_MAX_ATTEMPTS = 3


def classify_tushare_exception(error: Exception) -> tuple[str, bool]:
    """Classify only well-known transient failures as retryable.

    TuShare commonly surfaces API failures as generic exceptions, so unknown
    messages deliberately remain terminal instead of risking an uncontrolled
    retry loop.
    """

    message = str(error).lower()
    if any(token in message for token in ("permission", "权限", "积分", "积分不足", "积分不够")):
        return "permission_denied", False
    if any(token in message for token in ("token", "auth", "认证", "鉴权", "unauthorized", "401")):
        return "invalid_token", False
    if any(token in message for token in ("429", "rate limit", "too many", "频率", "访问过于频繁", "每分钟")):
        return "rate_limited", True
    if any(
        token in message
        for token in (
            "timeout",
            "timed out",
            "connection",
            "network",
            "temporar",
            "urlopen error",
            "nodename nor servname",
            "name or service not known",
            "dns",
            "502",
            "503",
            "504",
        )
    ):
        return "transient_network", True
    return "endpoint_error", False


class TushareEndpointError(RuntimeError):
    """Expose endpoint failure metadata without leaking credentials or request bodies."""

    def __init__(self, *, endpoint: str, category: str, retryable: bool, attempts: int, message: str) -> None:
        self.endpoint = endpoint
        self.category = category
        self.retryable = retryable
        self.attempts = attempts
        self.detail = message
        super().__init__(
            f"TuShare endpoint '{endpoint}' failed ({category}, attempts={attempts}): {message}"
        )

    def as_record(self, **extra: object) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "category": "tushare_request",
            "status": "retryable_failed" if self.retryable else "terminal_failed",
            "error_type": self.category,
            "attempts": self.attempts,
            **extra,
        }


@dataclass
class TushareRequestPolicy:
    """Serialize calls from one workflow and retry only explicitly transient outcomes."""

    min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 8.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    random_value: Callable[[], float] = random.random
    _last_attempt_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be zero or greater")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")
        if self.base_backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise ValueError("backoff seconds must be zero or greater")

    def _wait_for_next_attempt(self) -> None:
        now = self.clock()
        if self._last_attempt_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_attempt_at)
            if remaining > 0:
                self.sleep(remaining)
        self._last_attempt_at = self.clock()

    def _backoff_seconds(self, attempt: int) -> float:
        base = min(self.max_backoff_seconds, self.base_backoff_seconds * (2 ** (attempt - 1)))
        return base * (0.75 + (0.5 * self.random_value()))

    def request(self, client: Any, endpoint: str, params: dict[str, Any]) -> pd.DataFrame:
        method = getattr(client, endpoint, None)
        if not callable(method):
            raise ValueError(f"TuShare client does not expose endpoint '{endpoint}'")

        for attempt in range(1, self.max_attempts + 1):
            self._wait_for_next_attempt()
            try:
                frame = method(**params)
            except Exception as error:
                category, retryable = classify_tushare_exception(error)
                if retryable and attempt < self.max_attempts:
                    self.sleep(self._backoff_seconds(attempt))
                    continue
                raise TushareEndpointError(
                    endpoint=endpoint,
                    category=category,
                    retryable=retryable,
                    attempts=attempt,
                    message=str(error),
                ) from error
            if not isinstance(frame, pd.DataFrame):
                raise TushareEndpointError(
                    endpoint=endpoint,
                    category="unexpected_response",
                    retryable=False,
                    attempts=attempt,
                    message=f"returned {type(frame).__name__}, not a DataFrame",
                )
            return frame

        raise AssertionError("request loop must return or raise")


def request_endpoint(
    client: Any,
    endpoint: str,
    params: dict[str, Any],
    *,
    policy: TushareRequestPolicy | None = None,
) -> pd.DataFrame:
    return (policy or TushareRequestPolicy()).request(client, endpoint, params)
