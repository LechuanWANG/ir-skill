from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tushare_mode_data
from market_data_store import load_daily_price_history, write_daily_market_data
from technical_indicators import (
    TechnicalIndicatorSettings,
    calculate_technical_indicators,
    summarize_technical_indicators,
)


class TechnicalIndicatorSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = TechnicalIndicatorSettings()
        index = pd.date_range("2026-06-01", periods=12, freq="B", name="trade_date")
        self.indicators = pd.DataFrame(
            {
                "close_qfq": range(100, 112),
                "sma_20": [95.0] * 12,
                "sma_60": [90.0] * 12,
                "price_vs_sma_20": [0.05] * 12,
                "price_vs_sma_60": [0.10] * 12,
                "return_20d": [0.08] * 12,
                "volatility_20d_annualized": [0.24] * 12,
                "macd_12_26": [-0.2] * 8 + [-0.1, 0.1, 0.2, 0.3],
                "macd_signal_9": [0.0] * 12,
                "macd_histogram": [-0.2] * 8 + [-0.1, 0.1, 0.2, 0.3],
                "rsi_14": [55.0] * 6 + [62.0, 64.0, 66.0, 69.0, 72.0, 75.0],
                "bollinger_percent_b_20": [0.75] * 12,
                "bollinger_bandwidth_20": [0.18] * 12,
                "volume_ratio_20d": [1.3] * 12,
                "price_volume_correlation_20d": [0.4] * 12,
                "up_volume_share_20d": [0.65] * 12,
            },
            index=index,
        )

    def test_groups_current_state_changes_and_recent_cross(self) -> None:
        snapshot = summarize_technical_indicators(self.indicators, settings=self.settings)

        self.assertEqual(snapshot["available_dimensions"], ["trend", "momentum", "risk_and_location", "participation"])
        self.assertEqual(snapshot["dimensions"]["trend"]["sma_alignment"], "short_above_long")
        momentum = snapshot["dimensions"]["momentum"]
        self.assertEqual(momentum["macd_position"], "above_signal")
        self.assertEqual(momentum["last_macd_cross_within_10d"]["direction"], "crossed_above_signal")
        self.assertEqual(momentum["last_macd_cross_within_10d"]["sessions_ago"], 2)
        self.assertEqual(momentum["rsi_zone"], "at_or_above_70")
        self.assertEqual(snapshot["dimensions"]["participation"]["volume_regime"], "above_recent_average")

    def test_marks_participation_missing_when_volume_indicators_are_absent(self) -> None:
        snapshot = summarize_technical_indicators(
            self.indicators.drop(
                columns=["volume_ratio_20d", "price_volume_correlation_20d", "up_volume_share_20d"]
            ),
            settings=self.settings,
        )

        self.assertIn("participation", snapshot["missing_dimensions"])
        self.assertNotIn("participation", snapshot["available_dimensions"])

    def test_rejects_empty_history(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty technical-indicator history"):
            summarize_technical_indicators(pd.DataFrame(), settings=self.settings)

    def test_exposes_historical_highs_and_persistent_uptrend(self) -> None:
        index = pd.date_range("2023-01-02", periods=800, freq="B", name="trade_date")
        close = pd.Series([100 * (1.0008**position) for position in range(len(index))], index=index)
        indicators = calculate_technical_indicators(
            close,
            high_prices=close * 1.02,
            low_prices=close * 0.98,
            settings=self.settings,
        )

        structure = summarize_technical_indicators(indicators, settings=self.settings)["historical_price_structure"]
        full_history = structure["periods"]["full_available_history"]

        self.assertEqual(full_history["historical_high_basis"], "forward_adjusted_intraday_high")
        self.assertEqual(full_history["historical_high_trade_date"], index[-1].strftime("%Y-%m-%d"))
        self.assertEqual(full_history["price_path_label"], "persistent_uptrend")
        self.assertTrue(structure["periods"]["trailing_1y"]["available"])
        self.assertTrue(structure["periods"]["trailing_3y"]["available"])

    def test_identifies_a_sideways_or_oscillating_price_path(self) -> None:
        index = pd.date_range("2025-01-02", periods=260, freq="B", name="trade_date")
        close = pd.Series([100 + ((position % 20) - 10) for position in range(len(index))], index=index)
        indicators = calculate_technical_indicators(close, settings=self.settings)

        full_history = summarize_technical_indicators(indicators, settings=self.settings)["historical_price_structure"][
            "periods"
        ]["full_available_history"]

        self.assertEqual(full_history["historical_high_basis"], "forward_adjusted_close_fallback")
        self.assertEqual(full_history["price_path_label"], "sideways_or_oscillating")
        self.assertLess(full_history["trend_r_squared"], 0.25)

    def test_legacy_daily_table_is_migrated_and_loads_price_extremes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market.sqlite"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE a_share_daily (
                        trade_date TEXT NOT NULL,
                        ts_code TEXT NOT NULL,
                        close_qfq REAL,
                        volume REAL,
                        source TEXT NOT NULL,
                        retrieved_at TEXT NOT NULL,
                        PRIMARY KEY (trade_date, ts_code)
                    )
                    """
                )
                connection.commit()

            index = pd.DatetimeIndex([pd.Timestamp("2026-06-01")], name="trade_date")
            prices = pd.DataFrame({"000001.SZ": [10.0]}, index=index)
            volumes = pd.DataFrame({"000001.SZ": [1_000_000]}, index=index)
            write_daily_market_data(
                prices,
                volumes,
                high_prices=pd.DataFrame({"000001.SZ": [10.5]}, index=index),
                low_prices=pd.DataFrame({"000001.SZ": [9.5]}, index=index),
                db_path=db_path,
                source="test",
            )

            history = load_daily_price_history(db_path=db_path, symbols=["000001.SZ"])
            self.assertEqual(history.loc[0, "high_qfq"], 10.5)
            self.assertEqual(history.loc[0, "low_qfq"], 9.5)

    def test_indicators_command_reads_sqlite_and_emits_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market.sqlite"
            index = pd.date_range("2026-01-02", periods=100, freq="B", name="trade_date")
            prices = pd.DataFrame(
                {"000001.SZ": [100 + (position * 0.2) for position in range(len(index))]},
                index=index,
            )
            volumes = pd.DataFrame(
                {"000001.SZ": [1_000_000 + (position * 1_000) for position in range(len(index))]},
                index=index,
            )
            write_daily_market_data(
                prices,
                volumes,
                high_prices=prices * 1.01,
                low_prices=prices * 0.99,
                db_path=db_path,
                source="test",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                result = tushare_mode_data.main(
                    [
                        "indicators",
                        "--symbol",
                        "000001.SZ",
                        "--end-date",
                        index[-1].strftime("%Y%m%d"),
                        "--db-path",
                        str(db_path),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(payload["operation"], "indicators")
            self.assertTrue(payload["sufficient_history_for_standard_set"])
            self.assertEqual(
                payload["technical_snapshot"]["as_of_trade_date"],
                index[-1].strftime("%Y-%m-%d"),
            )
            self.assertIn("momentum", payload["technical_snapshot"]["available_dimensions"])
            full_history = payload["technical_snapshot"]["historical_price_structure"]["periods"][
                "full_available_history"
            ]
            self.assertEqual(full_history["historical_high_basis"], "forward_adjusted_intraday_high")
            self.assertEqual(full_history["historical_high_trade_date"], index[-1].strftime("%Y-%m-%d"))


if __name__ == "__main__":
    unittest.main()
