from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tushare_sync import fetch_fina_indicator
from tushare_transport import TushareEndpointError, TushareRequestPolicy, request_endpoint


class FlakyClient:
    def __init__(self) -> None:
        self.calls = 0

    def income(self, **_params: object) -> pd.DataFrame:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("HTTP 429 too many requests")
        return pd.DataFrame([{"ts_code": "000001.SZ"}])


class PermissionDeniedClient:
    def __init__(self) -> None:
        self.calls = 0

    def income(self, **_params: object) -> pd.DataFrame:
        self.calls += 1
        raise RuntimeError("权限不足")


class FinancialIndicatorClient:
    def fina_indicator(self, **params: object) -> pd.DataFrame:
        if params["ts_code"] == "000002.SZ":
            raise RuntimeError("权限不足")
        return pd.DataFrame([{"ts_code": params["ts_code"], "end_date": "20260331"}])


class TushareTransportTests(unittest.TestCase):
    def test_retries_rate_limit_with_bounded_backoff(self) -> None:
        client = FlakyClient()
        delays: list[float] = []
        policy = TushareRequestPolicy(
            min_interval_seconds=0,
            max_attempts=3,
            base_backoff_seconds=1,
            sleep=delays.append,
            random_value=lambda: 0.5,
        )

        frame = request_endpoint(client, "income", {}, policy=policy)

        self.assertEqual(client.calls, 2)
        self.assertEqual(len(frame), 1)
        self.assertEqual(delays, [1.0])

    def test_does_not_retry_permission_error(self) -> None:
        client = PermissionDeniedClient()
        policy = TushareRequestPolicy(min_interval_seconds=0, max_attempts=3, sleep=lambda _seconds: None)

        with self.assertRaises(TushareEndpointError) as caught:
            request_endpoint(client, "income", {}, policy=policy)

        self.assertEqual(caught.exception.category, "permission_denied")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.attempts, 1)
        self.assertEqual(client.calls, 1)

    def test_financial_indicator_keeps_other_symbols_when_one_fails(self) -> None:
        failures: list[dict[str, object]] = []
        frame = fetch_fina_indicator(
            FinancialIndicatorClient(),
            ["000001.SZ", "000002.SZ"],
            "20260101",
            "20260718",
            sleep_seconds=0,
            request_policy=TushareRequestPolicy(min_interval_seconds=0, max_attempts=1, sleep=lambda _seconds: None),
            failures=failures,
        )

        self.assertEqual(frame["ts_code"].tolist(), ["000001.SZ"])
        self.assertEqual(failures[0]["symbol"], "000002.SZ")
        self.assertEqual(failures[0]["error_type"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
