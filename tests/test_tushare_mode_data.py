from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_data_store import persist_tushare_collection, write_daily_market_data
from tushare_mode_data import _filter_available_as_of, main


class ModeDataTests(unittest.TestCase):
    def _plan(self, mode: str, *datasets: str) -> dict[str, object]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["plan", mode, "--symbol", "000001.SZ", "--end-date", "20260719", "--datasets", *datasets])
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def test_mode_plans_keep_tactical_endpoints_in_short_only(self) -> None:
        short = self._plan("short", "limit_step", "chip_distribution", "minute_price")
        self.assertEqual(
            [item["request"]["endpoint"] for item in short["datasets"]],
            ["limit_step", "cyq_chips", "stk_mins"],
        )
        with self.assertRaises(SystemExit):
            self._plan("long", "limit_step")

    def test_long_and_medium_expose_their_optional_research_data(self) -> None:
        long_plan = self._plan("long", "major_holders", "pledge_detail", "repurchase")
        medium_plan = self._plan(
            "medium",
            "broker_expectation",
            "institutional_research",
            "share_float",
            "holder_trade",
        )

        self.assertEqual(
            [item["request"]["endpoint"] for item in long_plan["datasets"]],
            ["top10_holders", "pledge_detail", "repurchase"],
        )
        self.assertEqual(
            [item["request"]["endpoint"] for item in medium_plan["datasets"]],
            ["report_rc", "stk_surv", "share_float", "stk_holdertrade"],
        )

    def test_availability_filter_excludes_future_disclosures(self) -> None:
        frame = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "ann_date": "20260718", "value": 1},
                {"ts_code": "000001.SZ", "ann_date": "20260720", "value": 2},
            ]
        )
        filtered, verification = _filter_available_as_of(frame, "20260719")
        self.assertEqual(filtered["value"].tolist(), [1])
        self.assertEqual(verification["excluded_rows"], 1)

    def test_availability_filter_excludes_unparseable_dates_and_reports_the_gap(self) -> None:
        frame = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "ann_date": "20260718", "value": 1},
                {"ts_code": "000001.SZ", "ann_date": "bad-date", "value": 2},
            ]
        )

        filtered, verification = _filter_available_as_of(frame, "20260719")

        self.assertEqual(filtered["value"].tolist(), [1])
        self.assertEqual(verification["status"], "partial")
        self.assertEqual(verification["invalid_or_missing_date_rows"], 1)

    def test_extended_tables_are_normalized_and_raw_observation_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            frame = pd.DataFrame(
                [{
                    "ts_code": "000001.SZ",
                    "trade_date": "20260719",
                    "net_mf_amount": 12.5,
                    "buy_elg_amount": 20.0,
                }]
            )
            observed, normalized = persist_tushare_collection("mode_short_moneyflow", "moneyflow_ths", frame, db_path=db_path)
            self.assertEqual((observed, normalized), (1, 1))
            with closing(sqlite3.connect(db_path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM market_flow_daily").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM tushare_research_observation").fetchone()[0], 1)

    def test_member_snapshot_without_trade_date_is_cached_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            frame = pd.DataFrame(
                [{"ts_code": "885001.TI", "con_code": "000001.SZ", "name": "Example"}]
            )

            observed, normalized = persist_tushare_collection(
                "mode_short_concept_members",
                "ths_member",
                frame,
                db_path=db_path,
                retrieved_at="2026-07-19T03:00:00+00:00",
            )

            self.assertEqual((observed, normalized), (1, 1))
            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "SELECT trade_date, index_code, con_code FROM sector_membership_daily"
                ).fetchone()
            self.assertEqual(row, ("2026-07-19", "885001.TI", "000001.SZ"))

    def test_fetch_reuses_complete_cached_core_data_without_creating_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            output_dir = Path(directory) / "export"
            calendar = pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": "20260716", "is_open": 1, "pretrade_date": "20260715"},
                    {"exchange": "SSE", "cal_date": "20260717", "is_open": 1, "pretrade_date": "20260716"},
                ]
            )
            prices = pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260716", "close": 10.0},
                    {"ts_code": "000001.SZ", "trade_date": "20260717", "close": 10.2},
                ]
            )
            persist_tushare_collection("mode_short_market_calendar", "trade_cal", calendar, db_path=db_path)
            persist_tushare_collection("mode_short_market_price", "daily", prices, db_path=db_path)

            output = io.StringIO()
            with patch("tushare_mode_data.create_tushare_client") as create_client, redirect_stdout(output):
                code = main(
                    [
                        "fetch",
                        "short",
                        "--symbol",
                        "000001.SZ",
                        "--start-date",
                        "20260716",
                        "--end-date",
                        "20260717",
                        "--datasets",
                        "market_calendar",
                        "market_price",
                        "--db-path",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["network_requests"], 0)
            by_key = {item["key"]: item for item in payload["results"]}
            self.assertEqual(by_key["market_calendar"]["status"], "cached")
            self.assertEqual(by_key["market_price"]["status"], "cached")
            self.assertEqual(by_key["market_price"]["cache_coverage"]["missing_date_count"], 0)
            exported = pd.read_csv(output_dir / "short_market_price_000001_SZ_20260717.csv")
            self.assertEqual(exported["ts_code"].tolist(), ["000001.SZ", "000001.SZ"])

    def test_fetch_requests_only_missing_cached_core_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            calendar = pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": "20260716", "is_open": 1, "pretrade_date": "20260715"},
                    {"exchange": "SSE", "cal_date": "20260717", "is_open": 1, "pretrade_date": "20260716"},
                ]
            )
            cached_price = pd.DataFrame(
                [{"ts_code": "000001.SZ", "trade_date": "20260716", "close": 10.0}]
            )
            persist_tushare_collection("mode_short_market_calendar", "trade_cal", calendar, db_path=db_path)
            persist_tushare_collection("mode_short_market_price", "daily", cached_price, db_path=db_path)

            requests: list[dict[str, str]] = []

            def request_missing_date(_, endpoint: str, params: dict[str, str], **__) -> pd.DataFrame:
                self.assertEqual(endpoint, "daily")
                requests.append(params)
                return pd.DataFrame(
                    [{"ts_code": "000001.SZ", "trade_date": "20260717", "close": 10.2}]
                )

            output = io.StringIO()
            with (
                patch("tushare_mode_data.create_tushare_client", return_value=object()) as create_client,
                patch("tushare_mode_data.request_endpoint", side_effect=request_missing_date),
                redirect_stdout(output),
            ):
                code = main(
                    [
                        "fetch",
                        "short",
                        "--symbol",
                        "000001.SZ",
                        "--start-date",
                        "20260716",
                        "--end-date",
                        "20260717",
                        "--datasets",
                        "market_price",
                        "--db-path",
                        str(db_path),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_called_once()
            self.assertEqual(requests, [{"ts_code": "000001.SZ", "start_date": "20260717", "end_date": "20260717", "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"}])
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["network_requests"], 1)
            result = payload["results"][0]
            self.assertEqual(result["request_date_range"], {"start_date": "20260717", "end_date": "20260717"})
            self.assertEqual(result["cache_coverage"]["missing_date_count"], 1)

    def test_fetch_reuses_normalized_daily_sync_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            calendar = pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": "20260716", "is_open": 1, "pretrade_date": "20260715"},
                    {"exchange": "SSE", "cal_date": "20260717", "is_open": 1, "pretrade_date": "20260716"},
                ]
            )
            dates = pd.to_datetime(["2026-07-16", "2026-07-17"])
            write_daily_market_data(
                pd.DataFrame({"000001.SZ": [10.0, 10.2]}, index=dates),
                pd.DataFrame({"000001.SZ": [1000.0, 1200.0]}, index=dates),
                db_path=db_path,
            )
            persist_tushare_collection("mode_short_market_calendar", "trade_cal", calendar, db_path=db_path)

            output = io.StringIO()
            with patch("tushare_mode_data.create_tushare_client") as create_client, redirect_stdout(output):
                code = main(
                    [
                        "fetch",
                        "short",
                        "--symbol",
                        "000001.SZ",
                        "--start-date",
                        "20260716",
                        "--end-date",
                        "20260717",
                        "--datasets",
                        "market_price",
                        "--db-path",
                        str(db_path),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["network_requests"], 0)
            self.assertEqual(payload["results"][0]["status"], "cached")

    def test_export_backfills_only_raw_payload_dates_absent_from_normalized_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            output_dir = Path(directory) / "export"
            calendar = pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": "20260716", "is_open": 1, "pretrade_date": "20260715"},
                    {"exchange": "SSE", "cal_date": "20260717", "is_open": 1, "pretrade_date": "20260716"},
                ]
            )
            dates = pd.to_datetime(["2026-07-16", "2026-07-17"])
            write_daily_market_data(
                pd.DataFrame({"000001.SZ": [10.0, 10.2]}, index=dates),
                pd.DataFrame({"000001.SZ": [1000.0, 1200.0]}, index=dates),
                db_path=db_path,
            )
            persist_tushare_collection("mode_short_market_calendar", "trade_cal", calendar, db_path=db_path)
            requests: list[dict[str, str]] = []

            def request_raw_export(_, endpoint: str, params: dict[str, str], **__) -> pd.DataFrame:
                self.assertEqual(endpoint, "daily")
                requests.append(params)
                return pd.DataFrame(
                    [
                        {"ts_code": "000001.SZ", "trade_date": "20260716", "close": 10.0},
                        {"ts_code": "000001.SZ", "trade_date": "20260717", "close": 10.2},
                    ]
                )

            output = io.StringIO()
            with (
                patch("tushare_mode_data.create_tushare_client", return_value=object()) as create_client,
                patch("tushare_mode_data.request_endpoint", side_effect=request_raw_export),
                redirect_stdout(output),
            ):
                code = main(
                    [
                        "fetch",
                        "short",
                        "--symbol",
                        "000001.SZ",
                        "--start-date",
                        "20260716",
                        "--end-date",
                        "20260717",
                        "--datasets",
                        "market_price",
                        "--db-path",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_called_once()
            self.assertEqual(
                requests,
                [{"ts_code": "000001.SZ", "start_date": "20260716", "end_date": "20260717", "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"}],
            )
            payload = json.loads(output.getvalue())
            result = payload["results"][0]
            self.assertEqual(payload["network_requests"], 1)
            self.assertEqual(result["cache_coverage"]["missing_date_count"], 0)
            self.assertEqual(result["cache_coverage"]["missing_raw_date_count"], 2)
            exported = pd.read_csv(output_dir / "short_market_price_000001_SZ_20260717.csv")
            self.assertEqual(exported["trade_date"].tolist(), [20260716, 20260717])


if __name__ == "__main__":
    unittest.main()
