from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tushare_sync import TushareHttpClient, fetch_daily_basic, fetch_daily_ohlcv_with_adjustment
from tushare_transport import TushareRequestPolicy, classify_tushare_exception


class DailyBasicClient:
    def __init__(self) -> None:
        self.requested_dates: list[str] = []

    def daily_basic(self, **params: object) -> pd.DataFrame:
        trade_date = str(params["trade_date"])
        self.requested_dates.append(trade_date)
        if trade_date == "20240722":
            raise ConnectionError("temporary connection reset")
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "close": 10.0}])


class TushareSyncTests(unittest.TestCase):
    def test_dns_failures_are_classified_as_transient_network_errors(self) -> None:
        category, retryable = classify_tushare_exception(
            OSError("<urlopen error [Errno 8] nodename nor servname provided, or not known>")
        )

        self.assertEqual(category, "transient_network")
        self.assertTrue(retryable)

    def test_http_client_uses_tushare_json_contract_without_sdk(self) -> None:
        requests: list[object] = []

        class Response:
            def read(self) -> bytes:
                return b'{"code": 0, "data": {"fields": ["ts_code", "close"], "items": [["000001.SZ", 10.5]]}}'

            def close(self) -> None:
                return None

        def opener(request, *, timeout: float):
            requests.append(request)
            self.assertEqual(timeout, 30.0)
            return Response()

        client = TushareHttpClient("secret-token", opener=opener)
        frame = client.daily(ts_code="000001.SZ", fields="ts_code,close")

        self.assertEqual(frame.to_dict(orient="records"), [{"ts_code": "000001.SZ", "close": 10.5}])
        self.assertEqual(len(requests), 1)
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(payload["api_name"], "daily")
        self.assertEqual(payload["params"], {"ts_code": "000001.SZ"})
        self.assertEqual(payload["fields"], "ts_code,close")

    def test_daily_basic_skips_weekends_and_keeps_successful_dates(self) -> None:
        client = DailyBasicClient()
        failures: list[dict[str, object]] = []
        frame = fetch_daily_basic(
            client,
            None,
            "20240719",
            "20240722",
            sleep_seconds=0,
            request_policy=TushareRequestPolicy(min_interval_seconds=0, max_attempts=1),
            failures=failures,
        )

        self.assertEqual(client.requested_dates, ["20240719", "20240722"])
        self.assertEqual(frame["trade_date"].tolist(), ["20240719"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["trade_date"], "20240722")
        self.assertEqual(failures[0]["error_type"], "transient_network")

    def test_daily_sync_fetches_and_forward_adjusts_intraday_extremes(self) -> None:
        class DailyClient:
            def daily(self, **params: object) -> pd.DataFrame:
                assert "high" in str(params["fields"])
                assert "low" in str(params["fields"])
                return pd.DataFrame(
                    [
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260102",
                            "close": 10.0,
                            "high": 10.5,
                            "low": 9.5,
                            "vol": 1000.0,
                        },
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260105",
                            "close": 11.0,
                            "high": 11.5,
                            "low": 10.5,
                            "vol": 1200.0,
                        },
                    ]
                )

            def adj_factor(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {"ts_code": "000001.SZ", "trade_date": "20260102", "adj_factor": 1.0},
                        {"ts_code": "000001.SZ", "trade_date": "20260105", "adj_factor": 1.1},
                    ]
                )

        daily = fetch_daily_ohlcv_with_adjustment(
            DailyClient(),
            ["000001.SZ"],
            "20260102",
            "20260105",
            sleep_seconds=0,
            request_policy=TushareRequestPolicy(min_interval_seconds=0, max_attempts=1),
        )

        self.assertAlmostEqual(daily.close.loc[pd.Timestamp("2026-01-02"), "000001.SZ"], 10 / 1.1)
        self.assertAlmostEqual(daily.high.loc[pd.Timestamp("2026-01-02"), "000001.SZ"], 10.5 / 1.1)
        self.assertAlmostEqual(daily.low.loc[pd.Timestamp("2026-01-05"), "000001.SZ"], 10.5)


if __name__ == "__main__":
    unittest.main()
