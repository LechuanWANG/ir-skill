from __future__ import annotations

import json
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from contextlib import redirect_stdout

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_data_store import (
    load_daily_screening_panel,
    load_index_daily_history,
    load_sector_memberships,
    persist_tushare_collection,
    write_daily_basic,
    write_daily_market_data,
    write_index_daily,
    write_limit_events,
    write_stock_basic,
    write_short_screen_run,
)
from short_term_screen import (
    PROFILES,
    _setup_trigger,
    build_data_quality_report,
    build_position_plan,
    build_screen,
    evaluate_screen_history,
    main,
)


class ShortTermScreenTests(unittest.TestCase):
    def _seed_database(self, db_path: Path, *, periods: int = 240) -> pd.DatetimeIndex:
        dates = pd.bdate_range("2025-01-02", periods=periods, name="trade_date")
        growth = {
            "000001.SZ": 0.0040,
            "000002.SZ": 0.0032,
            "000003.SZ": 0.0025,
            "000004.SZ": 0.0006,
            "000005.SZ": 0.0002,
            "000006.SZ": -0.0001,
            "000007.SZ": 0.0050,
            "000008.SZ": 0.0060,
            "000009.SZ": 0.0045,
            "000010.SZ": 0.0042,
        }
        prices = pd.DataFrame(
            {
                symbol: [10.0 * ((1.0 + rate) ** position) for position in range(periods)]
                for symbol, rate in growth.items()
            },
            index=dates,
        )
        volumes = pd.DataFrame(1_000_000.0, index=dates, columns=prices.columns)
        amounts = pd.DataFrame(100_000.0, index=dates, columns=prices.columns)
        amounts["000008.SZ"] = 10_000.0
        write_daily_market_data(
            prices,
            volumes,
            open_prices=prices * 0.999,
            high_prices=prices * 1.01,
            low_prices=prices * 0.99,
            amounts=amounts,
            raw_open_prices=prices * 0.999,
            raw_close_prices=prices,
            raw_high_prices=prices * 1.01,
            raw_low_prices=prices * 0.99,
            adjustment_factors=pd.DataFrame(1.0, index=dates, columns=prices.columns),
            db_path=db_path,
            source="test",
        )
        latest = dates[-1].strftime("%Y%m%d")
        write_daily_basic(
            pd.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "trade_date": latest,
                        "turnover_rate": 2.0,
                        "volume_ratio": 1.2,
                        "circ_mv": 100_000.0 + (position * 10_000.0),
                    }
                    for position, symbol in enumerate(prices.columns)
                ]
            ),
            db_path=db_path,
            source="test",
        )
        write_stock_basic(
            pd.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "name": "ST样本" if symbol == "000007.SZ" else f"样本{position}",
                        "industry": "科技" if position < 5 else "金融",
                        "market": "主板",
                        "list_date": "20260101" if symbol == "000009.SZ" else "20200101",
                        "list_status": "L",
                        "delist_date": None,
                    }
                    for position, symbol in enumerate(prices.columns)
                ]
            ),
            db_path=db_path,
            source="test",
        )
        write_index_daily(
            pd.DataFrame(
                [
                    {
                        "ts_code": "000300.SH",
                        "trade_date": trade_date.strftime("%Y%m%d"),
                        "open": 4000.0 * (1.0005**position),
                        "close": 4002.0 * (1.0005**position),
                    }
                    for position, trade_date in enumerate(dates)
                ]
            ),
            db_path=db_path,
            source="test",
        )
        write_limit_events(
            pd.DataFrame(
                [{"ts_code": "000010.SZ", "trade_date": latest, "limit_type": "U"}]
            ),
            db_path=db_path,
            source="test",
        )
        persist_tushare_collection(
            "sector_ths_master",
            "ths_index",
            pd.DataFrame(
                [
                    {"ts_code": "881001.TI", "name": "科技", "type": "industry"},
                    {"ts_code": "881002.TI", "name": "金融", "type": "industry"},
                ]
            ),
            db_path=db_path,
            source="test",
        )
        members = []
        for position, symbol in enumerate(prices.columns):
            members.append(
                {
                    "ts_code": "881001.TI" if position < 5 else "881002.TI",
                    "con_code": symbol,
                    "con_name": f"样本{position}",
                }
            )
        persist_tushare_collection(
            "sector_ths_members",
            "ths_member",
            pd.DataFrame(members),
            db_path=db_path,
            source="test",
            retrieved_at=f"{dates[-1].date().isoformat()}T08:00:00+00:00",
        )
        return dates

    def test_screen_builds_investable_universe_and_relative_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "market.sqlite"
            dates = self._seed_database(db_path)
            panel = load_daily_screening_panel(db_path=db_path, end_date=dates[-1].strftime("%Y%m%d"))
            benchmark = load_index_daily_history(
                db_path=db_path,
                benchmark="000300.SH",
                end_date=dates[-1].strftime("%Y%m%d"),
            )
            memberships = load_sector_memberships(
                db_path=db_path,
                provider="ths",
                as_of=dates[-1].strftime("%Y%m%d"),
            )

            payload = build_screen(
                panel,
                benchmark,
                as_of=dates[-1].strftime("%Y%m%d"),
                profile=PROFILES["trade"],
                limit=5,
                memberships=memberships,
            )

            exclusions = payload["universe"]["exclusions"]
            self.assertEqual(exclusions["special_treatment_or_delisting"], 1)
            self.assertEqual(exclusions["insufficient_liquidity"], 1)
            self.assertEqual(exclusions["insufficient_listing_age"], 1)
            self.assertEqual(exclusions["entry_blocked_by_limit_up"], 1)
            self.assertEqual(payload["ranking_basis"]["primary"], "buyability_score")
            self.assertEqual(payload["candidates"][0]["ts_code"], "000002.SZ")
            self.assertEqual(payload["candidates"][0]["technical_pattern"], "动量突破")
            self.assertEqual(payload["candidates"][0]["close_raw"], payload["candidates"][0]["close_qfq"])
            self.assertTrue(payload["technical_pattern_contract"]["selection_is_not_entry"])
            self.assertEqual(payload["readiness"]["candidate_grade_counts"], {"A": 1, "B": 1, "C": 0})
            self.assertEqual(payload["candidates"][0]["candidate_grade_label"], "A类：可执行候选")
            self.assertEqual(payload["candidates"][1]["candidate_grade_label"], "B类：研究合格但等待价格")
            self.assertIn("price_extension_atr", payload["candidates"][0])
            self.assertIn("own_extension_percentile_120d", payload["candidates"][0])
            self.assertIn("return_acceleration_5v20", payload["candidates"][0])
            report_json = json.dumps(payload["report"], ensure_ascii=False)
            self.assertNotIn("setup", report_json)
            self.assertNotIn("momentum_breakout", report_json)
            self.assertEqual(payload["driver_diagnostics"]["industry"]["status"], "available")
            self.assertIn("advancer_share_1d", payload["driver_diagnostics"]["industry"]["sectors"][0])
            self.assertEqual(payload["data_quality"]["stored_amount_coverage_20d"], 1.0)

            snapshot_payload = build_screen(
                panel,
                benchmark,
                as_of=dates[-1].strftime("%Y%m%d"),
                profile=PROFILES["trade"],
                limit=5,
            )
            snapshot_industry = snapshot_payload["driver_diagnostics"]["industry"]
            self.assertEqual(snapshot_industry["status"], "available")
            self.assertEqual(snapshot_industry["classification_source"], "stock_basic_current_snapshot")

            quality = build_data_quality_report(
                panel,
                benchmark,
                as_of=dates[-1].strftime("%Y%m%d"),
            )
            self.assertEqual(quality["status"], "ready")
            self.assertEqual(quality["decision_blockers"], [])

            degraded = panel.copy()
            degraded[["open_qfq", "amount", "close_raw", "adj_factor"]] = None
            degraded_quality = build_data_quality_report(
                degraded,
                benchmark,
                as_of=dates[-1].strftime("%Y%m%d"),
            )
            self.assertEqual(degraded_quality["status"], "blocked_for_execution")
            self.assertIn("stored_amount_incomplete_proxy_used", degraded_quality["decision_blockers"])

    def test_backtest_uses_next_session_open_and_reports_path_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "market.sqlite"
            dates = self._seed_database(db_path)
            panel = load_daily_screening_panel(db_path=db_path)
            benchmark = load_index_daily_history(db_path=db_path, benchmark="000300.SH")

            payload = evaluate_screen_history(
                panel,
                benchmark,
                start_date=dates[150].strftime("%Y%m%d"),
                end_date=dates[175].strftime("%Y%m%d"),
                profile=PROFILES["trade"],
                limit=3,
                rebalance_sessions=5,
                max_signals=2,
                out_of_sample_start=dates[165].strftime("%Y%m%d"),
            )

            self.assertGreater(payload["evaluated_observations"], 0)
            self.assertEqual(payload["execution"]["close_fallback_observations"], 0)
            first_horizon = payload["horizons"][0]
            self.assertGreater(first_horizon["mean_net_return"], 0)
            self.assertLess(first_horizon["mean_mae"], 0)
            self.assertGreater(first_horizon["mean_mfe"], 0)
            self.assertGreater(payload["sample_split"]["development_signal_dates"], 0)
            self.assertGreater(payload["sample_split"]["out_of_sample_signal_dates"], 0)
            self.assertEqual(payload["signal_dates"], 2)
            self.assertEqual(payload["inference"]["status"], "exploratory")
            self.assertEqual(payload["execution"]["quality_blocked_signal_dates"], 0)
            self.assertGreater(payload["trigger_replay"]["pattern_triggered"], 0)
            self.assertTrue(payload["trigger_replay"]["no_trade_is_counted"])
            self.assertEqual(payload["schema_version"], 4)
            self.assertIn("daily_bar_trigger", payload["trigger_replay"]["execution_assumption"])
            self.assertIn("expected_return_after_cost", first_horizon["distribution"])
            self.assertTrue(payload["candidate_grade_performance"])
            self.assertGreater(payload["trigger_replay"]["candidate_grade_selected"]["A"], 0)
            self.assertFalse(any("survivorship" in item for item in payload["known_biases"]))
            self.assertEqual(
                {row["sample"] for row in payload["equal_weight_signal_baskets"]},
                {"development", "out_of_sample"},
            )

    def test_setup_replay_respects_the_frozen_strategy_contract(self) -> None:
        signal_history = pd.DataFrame(
            {"high_qfq": [10.1], "low_qfq": [9.8]},
            index=pd.to_datetime(["2026-07-20"]),
        )
        trigger = _setup_trigger(
            {
                "close_qfq": 10.0,
                "setup_hint": "momentum_breakout",
                "trend_state": "supportive",
                "sma_60": 9.9,
            },
            signal_history,
            {"open_qfq": 10.0, "high_qfq": 10.1, "low_qfq": 9.85, "close_qfq": 10.05},
            strategy_contract="catalyst_swing",
        )

        self.assertEqual(trigger["setup_type"], "trend_pullback")
        self.assertEqual(trigger["status"], "triggered")

    def test_backtest_skips_limit_up_entries_and_delays_untradable_exits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "market.sqlite"
            dates = self._seed_database(db_path)
            panel = load_daily_screening_panel(db_path=db_path)
            benchmark = load_index_daily_history(db_path=db_path, benchmark="000300.SH")
            signal_date = dates[150]
            entry_date = dates[151]
            first_target_exit = dates[156]

            panel.loc[
                panel["ts_code"].eq("000001.SZ") & panel["trade_date"].eq(entry_date),
                "limit_types",
            ] = "U"
            panel = panel.loc[
                ~(panel["ts_code"].eq("000002.SZ") & panel["trade_date"].eq(first_target_exit))
            ].copy()

            payload = evaluate_screen_history(
                panel,
                benchmark,
                start_date=signal_date.strftime("%Y%m%d"),
                end_date=signal_date.strftime("%Y%m%d"),
                profile=PROFILES["trade"],
                limit=3,
                rebalance_sessions=1,
                max_signals=1,
                include_observations=True,
            )

            self.assertEqual(payload["execution"]["entry_skips_limit_up"], 1)
            delayed = [
                row for row in payload["outcome_records"]
                if row["symbol"] == "000002.SZ" and row["horizon"] == 5
            ]
            self.assertEqual(delayed[0]["exit_delay_sessions"], 1)
            self.assertEqual(payload["execution"]["delayed_exit_observations"], 1)

    def test_position_plan_is_bounded_by_risk_and_a_share_lot(self) -> None:
        payload = build_position_plan(
            account_value=1_000_000,
            entry_price=20,
            invalidation_price=18,
            risk_budget_pct=0.5,
            max_weight_pct=20,
            gap_buffer_pct=2,
        )

        self.assertEqual(payload["shares"] % 100, 0)
        self.assertLessEqual(payload["planned_loss_at_effective_invalidation"], 5_000)
        self.assertEqual(payload["binding_constraint"], "risk_budget")
        self.assertEqual(payload["position_sizing_status"], "pass")

    def test_position_plan_blocks_when_portfolio_heat_is_exhausted(self) -> None:
        payload = build_position_plan(
            account_value=1_000_000,
            entry_price=20,
            invalidation_price=18,
            risk_budget_pct=0.5,
            max_weight_pct=20,
            gap_buffer_pct=2,
            current_portfolio_heat_pct=2.0,
            portfolio_heat_limit_pct=2.0,
            open_positions=4,
            maximum_open_positions=5,
            median_daily_amount=50_000_000,
            maximum_order_to_daily_amount_pct=1.0,
        )

        self.assertEqual(payload["shares"], 0)
        self.assertEqual(payload["position_sizing_status"], "blocked")
        self.assertIn("portfolio_heat_limit_reached", payload["decision_blockers"])

    def test_risk_cli_distinguishes_a_ready_plan_from_execution(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "risk",
                    "--account-value", "1000000",
                    "--entry-price", "20",
                    "--invalidation-price", "18",
                    "--risk-budget-pct", "0.5",
                    "--max-weight-pct", "20",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["plan_ready"])
        self.assertFalse(payload["execution_ready"])
        self.assertEqual(payload["execution_status"], "not_observed")

    def test_risk_cli_blocks_waiting_or_watch_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "market.sqlite"
            recommendation_run_id = write_short_screen_run(
                {
                    "operation": "short_confirmation",
                    "schema_version": 4,
                    "strategy_contract": "momentum_trade",
                    "symbol": "000001.SZ",
                    "decision_ready": False,
                    "recommendation": {
                        "report_card": {"候选等级": "B类：研究合格但等待价格"}
                    },
                },
                db_path=db_path,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "risk",
                        "--account-value", "1000000",
                        "--entry-price", "20",
                        "--invalidation-price", "18",
                        "--risk-budget-pct", "0.5",
                        "--max-weight-pct", "20",
                        "--recommendation-run-id", recommendation_run_id,
                        "--db-path", str(db_path),
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["shares"], 0)
        self.assertFalse(payload["plan_ready"])
        self.assertIn("candidate_grade_not_executable", payload["decision_blockers"])

    def test_persists_replay_summary_and_raw_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "market.sqlite"
            payload = {
                "operation": "short_screen_backtest",
                "profile": "trade",
                "benchmark": "000300.SH",
                "requested_range": {"start_date": "20260101", "end_date": "20260301"},
            }
            run_id = write_short_screen_run(
                payload,
                outcomes=[
                    {
                        "signal_date": "20260202",
                        "entry_date": "20260203",
                        "exit_date": "20260210",
                        "symbol": "000001.SZ",
                        "horizon": 5,
                        "entry_basis": "next_session_open_qfq",
                        "net_return": 0.03,
                        "benchmark_return": 0.01,
                        "excess_return": 0.02,
                        "mae": -0.01,
                        "mfe": 0.04,
                    }
                ],
                db_path=db_path,
            )

            with closing(sqlite3.connect(db_path)) as connection:
                run = connection.execute(
                    "SELECT operation, profile FROM short_screen_run WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                outcome = connection.execute(
                    "SELECT ts_code, horizon_sessions, excess_return FROM short_screen_outcome WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            self.assertEqual(run, ("short_screen_backtest", "trade"))
            self.assertEqual(outcome, ("000001.SZ", 5, 0.02))

    def test_cli_research_flow_saves_recommendation_without_starting_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            db_path = project_dir / "data" / "research-library" / "database" / "investment_research.sqlite"
            dates = self._seed_database(db_path)
            as_of = dates[-1].strftime("%Y%m%d")

            screen_output = io.StringIO()
            with redirect_stdout(screen_output):
                code = main(
                    [
                        "screen", "--as-of", as_of, "--profile", "trade",
                        "--db-path", str(db_path), "--limit", "5", "--save-run",
                    ]
                )
            self.assertEqual(code, 0)
            screen_run_id = json.loads(screen_output.getvalue())["saved_run_id"]

            evidence_output = io.StringIO()
            with redirect_stdout(evidence_output):
                code = main(
                    [
                        "evidence", "--screen-run-id", screen_run_id,
                        "--symbol", "000001.SZ", "--strategy-contract", "momentum_trade",
                        "--db-path", str(db_path), "--save-run",
                    ]
                )
            self.assertEqual(code, 0)
            evidence_run_id = json.loads(evidence_output.getvalue())["saved_run_id"]
            evidence_payload = json.loads(evidence_output.getvalue())
            self.assertTrue(
                evidence_payload["technical_snapshot"]["indicator_snapshot_available"]
            )

            assessment_path = project_dir / "assessment.json"
            assessment_path.write_text(
                json.dumps(
                    {
                        "assessment_version": 1,
                        "symbol": "000001.SZ",
                        "as_of": pd.Timestamp(dates[-1]).date().isoformat(),
                        "strategy_contract": "momentum_trade",
                        "event": {"status": "not_required", "sources": []},
                        "expectation_gap": {"status": "positive", "thesis": "相对强弱仍有扩散空间"},
                        "priced_in": {"status": "moderate", "thesis": "价格与参与度匹配"},
                        "crowding": {"status": "moderate", "thesis": "流动性可承接"},
                        "counter_scenario": {"thesis": "风格反转", "trigger": "相对强弱跌破"},
                        "trade_plan": {
                            "action_label": "等待证据",
                            "entry_trigger": "突破确认",
                            "price_invalidation": "跌破结构低点",
                            "event_invalidation": "动量消失",
                            "time_invalidation": "五日未触发",
                            "maximum_holding_sessions": 20,
                            "expected_upside_pct": 9,
                            "effective_downside_pct": 4,
                            "cash_comparison": "赔率优于现金",
                        },
                        "confidence": "medium",
                        "thesis": "动量与参与度共同确认",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            confirmation_output = io.StringIO()
            with redirect_stdout(confirmation_output):
                code = main(
                    [
                        "confirm", "--evidence-run-id", evidence_run_id,
                        "--assessment", str(assessment_path), "--db-path", str(db_path),
                        "--project-dir", str(project_dir),
                    ]
                )
            self.assertEqual(code, 0)
            confirmation = json.loads(confirmation_output.getvalue())
            self.assertTrue(confirmation["saved_run_id"])
            self.assertFalse(confirmation["decision_snapshot_saved"])
            self.assertTrue(Path(confirmation["recommendation_store"]["watchlist_path"]).is_file())

            with closing(sqlite3.connect(db_path)) as connection:
                operations = connection.execute(
                    "SELECT operation, COUNT(*) FROM short_screen_run GROUP BY operation"
                ).fetchall()
                confirmation_json = connection.execute(
                    "SELECT payload_json FROM short_screen_run WHERE operation = 'short_confirmation'"
                ).fetchone()[0]
            self.assertEqual(dict(operations).get("short_review", 0), 0)
            self.assertNotIn("assessment", json.loads(confirmation_json))
            self.assertNotIn("evidence", json.loads(confirmation_json))


if __name__ == "__main__":
    unittest.main()
