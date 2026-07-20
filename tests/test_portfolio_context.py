from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from portfolio_context import clean_holding_items, main, profile_path, read_profile


class PortfolioContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = profile_path(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_main(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(arguments)
        output = stdout.getvalue() if exit_code == 0 else stderr.getvalue()
        return exit_code, json.loads(output)

    def test_agent_upsert_preserves_profile_and_trade_fields(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "horizon": "中期（3–6个月）",
                    "trades": [{"date": "2026-07-18", "side": "buy"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        exit_code, payload = self.run_main(
            [
                "upsert",
                "--project-dir",
                str(self.root),
                "--symbol",
                "600519.sh",
                "--name",
                "贵州茅台",
                "--quantity",
                "100",
                "--average-cost",
                "1500",
                "--latest-price",
                "1600",
                "--as-of",
                "2026-07-19",
            ]
        )

        profile = read_profile(self.path)
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "created")
        self.assertEqual(profile["horizon"], "中期（3–6个月）")
        self.assertEqual(profile["trades"], [{"date": "2026-07-18", "side": "buy"}])
        self.assertEqual(profile["holdings"][0]["symbol"], "600519.SH")
        self.assertEqual(profile["holdings"][0]["source"], "agent")
        self.assertEqual(payload["holding"]["unrealized_pnl"], 10000.0)

    def test_upsert_updates_one_symbol_and_preserves_omitted_fields(self) -> None:
        self.run_main(
            [
                "upsert",
                "--project-dir",
                str(self.root),
                "--symbol",
                "00700.HK",
                "--name",
                "腾讯控股",
                "--quantity",
                "300",
                "--average-cost",
                "420",
                "--notes",
                "核心持仓",
                "--as-of",
                "2026-07-18",
            ]
        )

        exit_code, payload = self.run_main(
            [
                "upsert",
                "--project-dir",
                str(self.root),
                "--symbol",
                "00700.hk",
                "--quantity",
                "250",
                "--as-of",
                "2026-07-19",
            ]
        )

        holding = payload["holding"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "updated")
        self.assertEqual(holding["name"], "腾讯控股")
        self.assertEqual(holding["average_cost"], 420.0)
        self.assertEqual(holding["quantity"], 250.0)
        self.assertEqual(holding["notes"], "核心持仓")
        self.assertEqual(holding["as_of"], "2026-07-19")

    def test_show_filters_symbols_and_reports_lightweight_pnl(self) -> None:
        for symbol, quantity, cost, price in (
            ("600519.SH", "10", "1500", "1550"),
            ("000001.SZ", "20", "12", "11"),
        ):
            self.run_main(
                [
                    "upsert",
                    "--project-dir",
                    str(self.root),
                    "--symbol",
                    symbol,
                    "--quantity",
                    quantity,
                    "--average-cost",
                    cost,
                    "--latest-price",
                    price,
                    "--as-of",
                    "2026-07-19",
                ]
            )

        exit_code, payload = self.run_main(
            [
                "show",
                "--project-dir",
                str(self.root),
                "--symbol",
                "600519.sh",
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["holding_count"], 1)
        self.assertEqual(payload["holdings"][0]["symbol"], "600519.SH")
        self.assertEqual(payload["holdings"][0]["unrealized_pnl"], 500.0)
        self.assertAlmostEqual(payload["holdings"][0]["unrealized_return_pct"], 3.3333333333)

    def test_remove_deletes_only_the_selected_current_holding(self) -> None:
        for symbol in ("600519.SH", "000001.SZ"):
            self.run_main(
                [
                    "upsert",
                    "--project-dir",
                    str(self.root),
                    "--symbol",
                    symbol,
                    "--quantity",
                    "10",
                ]
            )

        exit_code, payload = self.run_main(
            ["remove", "--project-dir", str(self.root), "--symbol", "600519.SH"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "removed")
        self.assertEqual([item["symbol"] for item in read_profile(self.path)["holdings"]], ["000001.SZ"])

    def test_rejects_non_positive_quantity_and_invalid_date(self) -> None:
        for extra_arguments in (
            ["--quantity", "0"],
            ["--quantity", "10", "--as-of", "2026-02-30"],
        ):
            exit_code, payload = self.run_main(
                [
                    "upsert",
                    "--project-dir",
                    str(self.root),
                    "--symbol",
                    "600519.SH",
                    *extra_arguments,
                ]
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")

    def test_ui_sanitizer_skips_an_empty_row_and_adds_context_metadata(self) -> None:
        holdings = clean_holding_items(
            [
                {"symbol": "", "quantity": "", "as_of": "2026-07-19"},
                {"symbol": "000001.sz", "quantity": "100", "average_cost": "12.5"},
            ],
            default_as_of="2026-07-19",
            default_source="ui",
        )

        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["symbol"], "000001.SZ")
        self.assertEqual(holdings[0]["as_of"], "2026-07-19")
        self.assertEqual(holdings[0]["source"], "ui")


if __name__ == "__main__":
    unittest.main()
