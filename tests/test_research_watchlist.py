from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from research_watchlist import (
    main,
    read_watchlist,
    replace_watchlist,
    upsert_watch_item,
    watchlist_path,
)


class ResearchWatchlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = watchlist_path(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_main(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(arguments)
        output = stdout.getvalue() if exit_code == 0 else stderr.getvalue()
        return exit_code, json.loads(output)

    def test_agent_upsert_preserves_research_path_and_appends_report_links(self) -> None:
        first_report = "report/company/2026-07-18/腾讯控股中期研究.md"
        second_report = "report/company/2026-07-19/腾讯控股复核.md"
        self.run_main(
            [
                "upsert", "--project-dir", str(self.root), "--symbol", "00700.hk",
                "--name", "腾讯控股", "--research-path", "medium-term",
                "--action-label", "等待价格", "--thesis", "利润兑现但价格条件不足",
                "--source-report", first_report,
            ]
        )

        exit_code, payload = self.run_main(
            [
                "upsert", "--project-dir", str(self.root), "--symbol", "00700.HK",
                "--status", "tracking", "--last-researched-on", "2026-07-19",
                "--source-report", first_report, "--source-report", second_report,
            ]
        )

        item = payload["item"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "updated")
        self.assertEqual(item["research_path"], "medium-term")
        self.assertEqual(item["thesis"], "利润兑现但价格条件不足")
        self.assertEqual(item["source_reports"], [first_report, second_report])

    def test_upsert_accepts_one_report_path_and_round_trips_review_date(self) -> None:
        report = "report/company/2026-07-19/苹果公司长期研究.md"

        _, item = upsert_watch_item(
            self.path,
            {
                "symbol": "AAPL",
                "research_path": "long-term",
                "next_review_on": "2026-08-19",
                "source_reports": report,
            },
        )

        self.assertEqual(item["next_review_on"], "2026-08-19")
        self.assertEqual(item["source_reports"], [report])
        self.assertEqual(read_watchlist(self.path)["items"][0], item)

    def test_show_excludes_archived_items_unless_requested(self) -> None:
        self.run_main(
            [
                "upsert", "--project-dir", str(self.root), "--symbol", "600519.SH",
                "--research-path", "long-term", "--status", "archived",
            ]
        )

        exit_code, current = self.run_main(["show", "--project-dir", str(self.root)])
        _, complete = self.run_main(
            ["show", "--project-dir", str(self.root), "--include-archived"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(current["status"], "empty")
        self.assertEqual(complete["item_count"], 1)
        self.assertEqual(complete["items"][0]["status"], "archived")

    def test_show_reports_missing_linked_research(self) -> None:
        missing_report = "report/company/2026-07-19/不存在的研究.md"
        self.run_main(
            [
                "upsert", "--project-dir", str(self.root), "--symbol", "000001.SZ",
                "--research-path", "short-term", "--source-report", missing_report,
            ]
        )

        _, payload = self.run_main(
            ["show", "--project-dir", str(self.root), "--symbol", "000001.sz"]
        )

        self.assertEqual(payload["item_count"], 1)
        self.assertIn(missing_report, payload["warnings"][0])

    def test_ui_replace_skips_blank_rows_and_adds_metadata(self) -> None:
        payload = replace_watchlist(
            self.path,
            {
                "items": [
                    {"symbol": "", "recommended_on": "2026-07-19"},
                    {
                        "symbol": "aapl",
                        "name": "Apple",
                        "status": "waiting-evidence",
                        "research_path": "long-term",
                        "thesis": "等待下一期服务收入验证",
                    },
                ]
            },
        )

        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["symbol"], "AAPL")
        self.assertEqual(payload["items"][0]["source"], "ui")
        self.assertTrue(payload["items"][0]["created_at"])
        self.assertEqual(read_watchlist(self.path)["items"][0]["research_path"], "long-term")

    def test_rejects_duplicate_symbols_invalid_dates_and_unsafe_report_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate tracked symbol"):
            replace_watchlist(
                self.path,
                {
                    "items": [
                        {"symbol": "AAPL", "research_path": "long-term"},
                        {"symbol": "aapl", "research_path": "short-term"},
                    ]
                },
            )

        for extra_arguments in (
            ["--recommended-on", "2026-02-30"],
            ["--source-report", "../outside.md"],
            ["--source-report", "/tmp/report.md"],
        ):
            exit_code, payload = self.run_main(
                [
                    "upsert", "--project-dir", str(self.root), "--symbol", "AAPL",
                    "--research-path", "long-term", *extra_arguments,
                ]
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")

    def test_remove_deletes_only_selected_symbol(self) -> None:
        for symbol in ("600519.SH", "000001.SZ"):
            self.run_main(
                [
                    "upsert", "--project-dir", str(self.root), "--symbol", symbol,
                    "--research-path", "medium-term",
                ]
            )

        exit_code, payload = self.run_main(
            ["remove", "--project-dir", str(self.root), "--symbol", "600519.sh"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "removed")
        self.assertEqual(
            [item["symbol"] for item in read_watchlist(self.path)["items"]],
            ["000001.SZ"],
        )


if __name__ == "__main__":
    unittest.main()
