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

from market_data_store import (
    ensure_database,
    load_sector_daily_history,
    load_sector_memberships,
    persist_tushare_collection,
)
import market_data_migrations as migrations
from market_data_migrations import MIGRATION_TABLE, Migration
from tushare_sector_data import main, select_performance_universe, summarize_sector_performance


class SectorDataTests(unittest.TestCase):
    def test_sector_migration_is_recorded_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"

            ensure_database(db_path)
            ensure_database(db_path)

            with closing(sqlite3.connect(db_path)) as connection:
                rows = connection.execute(
                    f"SELECT version, name FROM {MIGRATION_TABLE} ORDER BY version"
                ).fetchall()

            self.assertEqual(rows, [(1, "sector_data_tables")])

    def test_existing_database_is_backed_up_before_a_pending_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            ensure_database(db_path)
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("CREATE TABLE preserved_data (value TEXT NOT NULL)")
                connection.execute("INSERT INTO preserved_data (value) VALUES ('keep')")
                connection.execute(f"DROP TABLE {MIGRATION_TABLE}")
                connection.commit()

            ensure_database(db_path)

            backups = list(Path(directory).glob("research.pre-migration-*.sqlite"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(
                    backup.execute("SELECT value FROM preserved_data").fetchone(),
                    ("keep",),
                )
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            with closing(sqlite3.connect(db_path)) as connection:
                self.assertEqual(
                    connection.execute(
                        f"SELECT version, name FROM {MIGRATION_TABLE} ORDER BY version"
                    ).fetchall(),
                    [(1, "sector_data_tables")],
                )

    def test_failed_pending_migration_reports_a_recoverable_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            ensure_database(db_path)

            def fail_migration(connection: sqlite3.Connection, tables: object) -> None:
                raise RuntimeError("intentional migration failure")

            failing_migration = Migration(2, "intentional_failure", fail_migration)
            with patch.object(migrations, "MIGRATIONS", (*migrations.MIGRATIONS, failing_migration)):
                with self.assertRaisesRegex(RuntimeError, "备份保留在"):
                    ensure_database(db_path)

            backups = list(Path(directory).glob("research.pre-migration-*.sqlite"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(
                    backup.execute(
                        f"SELECT version, name FROM {MIGRATION_TABLE} ORDER BY version"
                    ).fetchall(),
                    [(1, "sector_data_tables")],
                )

    def test_default_plan_uses_ths_cross_section_endpoints(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["plan", "--as-of", "20260717"])

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["provider"], "ths")
        self.assertEqual(
            [request["endpoint"] for request in payload["requests"]],
            ["ths_index", "ths_daily", "moneyflow_ind_ths"],
        )
        self.assertEqual(payload["requests"][1]["params"], {"trade_date": "20260717"})
        self.assertEqual(payload["taxonomy_policy"]["fundamental_industry_reference"], "SW2021")

    def test_provider_rejects_an_unsupported_dataset(self) -> None:
        with self.assertRaises(SystemExit):
            main(["plan", "--provider", "dc", "--as-of", "20260717", "--datasets", "flow"])

    def test_cross_section_history_is_split_by_business_day(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "plan",
                    "--as-of",
                    "20260717",
                    "--start-date",
                    "20260715",
                    "--datasets",
                    "daily",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["request_count"], 3)
        self.assertEqual(
            [request["params"] for request in payload["requests"]],
            [
                {"trade_date": "20260715"},
                {"trade_date": "20260716"},
                {"trade_date": "20260717"},
            ],
        )

    def test_members_can_be_planned_directly_from_a_stock_code(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "plan",
                    "--as-of",
                    "20260717",
                    "--stock-code",
                    "000001.SZ",
                    "--datasets",
                    "members",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["requests"][0]["params"], {"con_code": "000001.SZ"})

    def test_sector_endpoints_materialize_normalized_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            master = pd.DataFrame(
                [{"ts_code": "885001.TI", "name": "人工智能", "type": "concept", "exchange": "A"}]
            )
            daily = pd.DataFrame(
                [{
                    "ts_code": "885001.TI",
                    "trade_date": "20260717",
                    "name": "人工智能",
                    "close": 1200.0,
                    "pct_change": 2.5,
                    "amount": 100.0,
                }]
            )
            flow = pd.DataFrame(
                [{
                    "ts_code": "885001.TI",
                    "trade_date": "20260717",
                    "name": "人工智能",
                    "net_amount": 12.5,
                }]
            )

            persist_tushare_collection("sector_ths_master", "ths_index", master, db_path=db_path)
            persist_tushare_collection("sector_ths_daily", "ths_daily", daily, db_path=db_path)
            persist_tushare_collection(
                "sector_ths_flow",
                "moneyflow_ind_ths",
                flow,
                db_path=db_path,
            )

            with closing(sqlite3.connect(db_path)) as connection:
                master_row = connection.execute(
                    "SELECT provider, sector_code, sector_name, sector_type FROM market_sector_master"
                ).fetchone()
                daily_row = connection.execute(
                    "SELECT provider, sector_code, trade_date, pct_chg FROM market_sector_daily"
                ).fetchone()
                flow_row = connection.execute(
                    "SELECT provider, sector_code, trade_date, sector_name, net_amount FROM market_sector_flow_daily"
                ).fetchone()

            self.assertEqual(master_row, ("ths", "885001.TI", "人工智能", "concept"))
            self.assertEqual(daily_row, ("ths", "885001.TI", "2026-07-17", 2.5))
            self.assertEqual(flow_row, ("ths", "885001.TI", "2026-07-17", "人工智能", 12.5))

    def test_performance_adds_strength_breadth_and_moneyflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            master = pd.DataFrame(
                [
                    {"ts_code": "885001.TI", "name": "板块甲", "type": "industry"},
                    {"ts_code": "885002.TI", "name": "板块乙", "type": "industry"},
                ]
            )
            dates = pd.bdate_range(end="2026-07-17", periods=21)
            daily_records = []
            for offset, trade_date in enumerate(dates):
                compact_date = trade_date.strftime("%Y%m%d")
                daily_records.extend(
                    [
                        {
                            "ts_code": "885001.TI",
                            "trade_date": compact_date,
                            "close": 100.0 + offset,
                            "pct_change": 1.0 if offset == 20 else 0.1,
                            "amount": 1000.0 + offset,
                        },
                        {
                            "ts_code": "885002.TI",
                            "trade_date": compact_date,
                            "close": 100.0 - offset,
                            "pct_change": -1.0 if offset == 20 else -0.1,
                            "amount": 900.0 + offset,
                        },
                    ]
                )
            flow = pd.DataFrame(
                [
                    {"ts_code": "885001.TI", "trade_date": "20260717", "net_amount": 10.0},
                    {"ts_code": "885002.TI", "trade_date": "20260717", "net_amount": -8.0},
                ]
            )
            persist_tushare_collection("sector_ths_master", "ths_index", master, db_path=db_path)
            persist_tushare_collection(
                "sector_ths_daily",
                "ths_daily",
                pd.DataFrame(daily_records),
                db_path=db_path,
            )
            persist_tushare_collection(
                "sector_ths_flow",
                "moneyflow_ind_ths",
                flow,
                db_path=db_path,
            )

            history = load_sector_daily_history(
                db_path=db_path,
                provider="ths",
                end_date="20260717",
                sector_type="industry",
            )
            payload = summarize_sector_performance(
                history,
                as_of="20260717",
                provider="ths",
                limit=2,
            )

            self.assertEqual(payload["effective_trade_date"], "2026-07-17")
            self.assertEqual(payload["breadth"]["advancers"], 1)
            self.assertEqual(payload["breadth"]["decliners"], 1)
            self.assertEqual(payload["coverage"]["with_20d_return"], 2)
            self.assertEqual(payload["coverage"]["with_moneyflow"], 2)
            self.assertEqual(payload["ranking"][0]["sector_code"], "885001.TI")
            self.assertAlmostEqual(payload["ranking"][0]["return_20d"], 20.0)
            self.assertEqual(payload["ranking"][0]["net_amount"], 10.0)

    def test_industry_flow_universe_excludes_unmatched_nested_industries(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "provider": "ths",
                    "sector_code": "881001.TI",
                    "trade_date": "2026-07-17",
                    "net_amount": 1.0,
                },
                {
                    "provider": "ths",
                    "sector_code": "700001.TI",
                    "trade_date": "2026-07-17",
                    "net_amount": None,
                },
                {
                    "provider": "ths",
                    "sector_code": "881001.TI",
                    "trade_date": "2026-07-16",
                    "net_amount": None,
                },
            ]
        )

        selected = select_performance_universe(frame, "industry-flow")

        self.assertEqual(selected["sector_code"].unique().tolist(), ["881001.TI"])
        self.assertEqual(len(selected), 2)

    def test_membership_lookup_uses_latest_snapshot_per_sector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            master = pd.DataFrame(
                [{"ts_code": "885001.TI", "name": "人工智能", "type": "concept"}]
            )
            persist_tushare_collection("sector_ths_master", "ths_index", master, db_path=db_path)
            persist_tushare_collection(
                "sector_ths_members",
                "ths_member",
                pd.DataFrame([{"ts_code": "885001.TI", "con_code": "000001.SZ", "con_name": "平安银行"}]),
                db_path=db_path,
                retrieved_at="2026-07-17T03:00:00+00:00",
            )

            memberships = load_sector_memberships(
                db_path=db_path,
                provider="ths",
                stock_code="000001.SZ",
                as_of="20260717",
            )

            self.assertEqual(len(memberships), 1)
            self.assertEqual(memberships.iloc[0]["sector_code"], "885001.TI")
            self.assertEqual(memberships.iloc[0]["sector_name"], "人工智能")
            self.assertEqual(memberships.iloc[0]["stock_name"], "平安银行")

    def test_fetch_reuses_complete_cached_sector_snapshots_without_creating_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            daily = pd.DataFrame(
                [
                    {"ts_code": "885001.TI", "trade_date": "20260716", "close": 100.0},
                    {"ts_code": "885001.TI", "trade_date": "20260717", "close": 101.0},
                ]
            )
            persist_tushare_collection("sector_ths_daily", "ths_daily", daily, db_path=db_path)

            output = io.StringIO()
            with patch("tushare_sector_data.create_tushare_client") as create_client, redirect_stdout(output):
                code = main(
                    [
                        "fetch",
                        "--provider",
                        "ths",
                        "--start-date",
                        "20260716",
                        "--as-of",
                        "20260717",
                        "--datasets",
                        "daily",
                        "--db-path",
                        str(db_path),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["network_requests"], 0)
            self.assertEqual([item["status"] for item in payload["results"]], ["cached", "cached"])
            self.assertTrue(all(not item["network_requested"] for item in payload["results"]))

    def test_fetch_requests_only_missing_sector_snapshot_dates_and_refresh_bypasses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            cached_daily = pd.DataFrame(
                [{"ts_code": "885001.TI", "trade_date": "20260716", "close": 100.0}]
            )
            persist_tushare_collection("sector_ths_daily", "ths_daily", cached_daily, db_path=db_path)
            requests: list[dict[str, str]] = []

            def fetch_missing(_, endpoint: str, params: dict[str, str], **__) -> pd.DataFrame:
                self.assertEqual(endpoint, "ths_daily")
                requests.append(params)
                return pd.DataFrame(
                    [{"ts_code": "885001.TI", "trade_date": params["trade_date"], "close": 101.0}]
                )

            output = io.StringIO()
            with (
                patch("tushare_sector_data.create_tushare_client", return_value=object()) as create_client,
                patch("tushare_sector_data.request_endpoint", side_effect=fetch_missing),
                redirect_stdout(output),
            ):
                code = main(
                    [
                        "fetch",
                        "--provider",
                        "ths",
                        "--start-date",
                        "20260716",
                        "--as-of",
                        "20260717",
                        "--datasets",
                        "daily",
                        "--db-path",
                        str(db_path),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_called_once()
            self.assertEqual(requests, [{"trade_date": "20260717"}])
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["network_requests"], 1)
            self.assertEqual([item["status"] for item in payload["results"]], ["cached", "available"])

            output = io.StringIO()
            with (
                patch("tushare_sector_data.create_tushare_client", return_value=object()) as create_client,
                patch("tushare_sector_data.request_endpoint", side_effect=fetch_missing),
                redirect_stdout(output),
            ):
                code = main(
                    [
                        "fetch",
                        "--provider",
                        "ths",
                        "--as-of",
                        "20260717",
                        "--datasets",
                        "daily",
                        "--refresh",
                        "--db-path",
                        str(db_path),
                    ]
                )

            self.assertEqual(code, 0)
            create_client.assert_called_once()
            self.assertEqual(requests[-1], {"trade_date": "20260717"})
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["network_requests"], 1)
            self.assertEqual(payload["results"][0]["status"], "available")


if __name__ == "__main__":
    unittest.main()
