from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_data_store import (
    list_short_recommendation_runs,
    load_short_screen_run,
    write_short_screen_run,
)
from short_term_decision import (
    build_evidence_bundle,
    compact_confirmation,
    confirm_evidence,
    enrich_screen_readiness,
    review_recommendation,
)


class ShortTermDecisionTests(unittest.TestCase):
    def screen_payload(self) -> dict[str, object]:
        return {
            "operation": "short_screen",
            "requested_as_of": "2026-07-19",
            "effective_trade_date": "2026-07-17",
            "profile": "trade",
            "benchmark": "000300.SH",
            "market_regime": {"state": "supportive"},
            "driver_diagnostics": {"dominant_driver": "industry_theme"},
            "data_quality": {"status": "ready", "decision_blockers": []},
            "candidates": [
                {
                    "ts_code": "000001.SZ",
                    "name": "样本",
                    "close_qfq": 12.0,
                    "close_raw": 12.0,
                    "adj_factor": 1.0,
                    "candidate_state": "evidence_ready",
                    "setup_hint": "momentum_breakout",
                    "momentum_percentile": 0.9,
                    "trend_state": "supportive",
                    "participation_state": "supportive",
                    "extension_state": "not_stretched",
                    "volatility_percentile": 0.4,
                }
            ],
        }

    def valid_assessment(self) -> dict[str, object]:
        return {
            "assessment_version": 2,
            "symbol": "000001.SZ",
            "as_of": "2026-07-19",
            "strategy_contract": "momentum_trade",
            "event": {"status": "not_required", "thesis": "", "sources": [], "unknowns": []},
            "expectation_gap": {"status": "positive", "thesis": "相对强弱尚未充分扩散", "basis": "breadth"},
            "priced_in": {"status": "moderate", "thesis": "涨幅与成交仍匹配"},
            "crowding": {"status": "moderate", "thesis": "换手可承接"},
            "counter_scenario": {"thesis": "市场风格快速反转", "trigger": "相对强弱跌破"},
            "technical_setup": {
                "setup_type": "momentum_breakout",
                "hypothesis": "信息反应不足与增量资金延续形成短期惯性",
                "relative_strength_status": "pass",
                "trend_structure_status": "pass",
                "participation_status": "pass",
                "extension_status": "pass",
                "trigger_rule": "下一交易日突破确认",
                "invalidation_rule": "跌破结构低点",
                "valid_until": "五个交易日内",
                "counter_evidence": ["市场宽度快速恶化"],
            },
            "trade_plan": {
                "action_label": "优先行动",
                "entry_trigger": "放量突破前高",
                "price_invalidation": "跌破结构低点",
                "event_invalidation": "动量驱动消失",
                "time_invalidation": "五个交易日未触发",
                "maximum_holding_sessions": 20,
                "expected_upside_pct": 9,
                "effective_downside_pct": 4,
                "cash_comparison": "预期赔率优于现金",
            },
            "investor_constraints": {
                "decision_frequency": "close_review_next_session_execution",
                "maximum_open_positions": 5,
                "single_trade_risk_budget_pct": 0.5,
                "portfolio_heat_limit_pct": 2.0,
                "maximum_new_trades_per_session": 2,
                "overnight_gap_buffer_pct": 2.0,
                "minimum_liquidity_multiple": 20,
            },
            "confidence": "medium",
            "thesis": "相对强弱与参与度形成可验证的短线结构",
        }

    def test_screening_readiness_is_layered_and_legacy_scope_is_explicit(self) -> None:
        payload = enrich_screen_readiness(self.screen_payload())
        candidate = payload["candidates"][0]

        self.assertEqual(candidate["readiness"]["screening"], "pass")
        self.assertEqual(candidate["readiness"]["research"], "unknown")
        self.assertTrue(candidate["evidence_ready"])
        self.assertFalse(candidate["decision_ready"])
        self.assertEqual(
            candidate["compatibility"]["evidence_ready_scope"],
            "mechanical_screening_only",
        )

    def test_candidate_grades_separate_execution_waiting_and_watch_only(self) -> None:
        payload = self.screen_payload()
        base = payload["candidates"][0]
        candidates = []
        for symbol, chase_score, extension in (
            ("000001.SZ", 20.0, "not_stretched"),
            ("000002.SZ", 50.0, "stretched"),
            ("000003.SZ", 85.0, "not_stretched"),
        ):
            candidate = dict(base)
            candidate.update(
                {
                    "ts_code": symbol,
                    "chase_risk_score": chase_score,
                    "extension_state": extension,
                }
            )
            candidates.append(candidate)
        payload["candidates"] = candidates

        result = enrich_screen_readiness(payload)

        self.assertEqual(
            [candidate["candidate_grade_label"] for candidate in result["candidates"]],
            ["A类：可执行候选", "B类：研究合格但等待价格", "C类：强势观察对象"],
        )
        self.assertEqual(result["readiness"]["candidate_grade_counts"], {"A": 1, "B": 1, "C": 1})

    def test_confirmation_combines_agent_judgment_without_assuming_execution(self) -> None:
        screen = enrich_screen_readiness(self.screen_payload())
        evidence = build_evidence_bundle(
            screen,
            symbol="000001.SZ",
            contract_name="momentum_trade",
            indicator_snapshot={"as_of_trade_date": "2026-07-17", "dimensions": {"trend": {}}},
        )
        confirmation = confirm_evidence(evidence, self.valid_assessment())

        self.assertTrue(confirmation["decision_ready"])
        self.assertFalse(confirmation["execution_ready"])
        self.assertEqual(confirmation["execution_status"], "not_observed")
        self.assertEqual(confirmation["recommendation"]["action_label"], "优先行动")
        self.assertEqual(confirmation["readiness"]["technical_setup"], "pass")
        self.assertEqual(confirmation["readiness"]["personal_investor_controls"], "pass")
        self.assertEqual(confirmation["recommendation"]["report_card"]["技术形态"], "动量突破")
        self.assertEqual(
            confirmation["recommendation"]["report_card"]["候选等级"],
            "A类：可执行候选",
        )
        report_json = json.dumps(confirmation["report"], ensure_ascii=False)
        self.assertNotIn("setup", report_json)
        self.assertNotIn("momentum_breakout", report_json)
        self.assertNotIn("technical_setup", confirmation["recommendation"])
        self.assertEqual(
            confirmation["recommendation"]["price_basis"]["execution"],
            "raw_unadjusted_required",
        )
        self.assertTrue(evidence["technical_snapshot"]["indicator_snapshot_available"])

        compact = compact_confirmation(confirmation)
        self.assertNotIn("assessment", compact)
        self.assertNotIn("evidence", compact)
        self.assertNotIn("gates", compact)
        self.assertNotIn("setup", json.dumps(compact, ensure_ascii=False))
        self.assertNotIn("momentum_breakout", json.dumps(compact, ensure_ascii=False))
        self.assertFalse(compact["decision_snapshot_saved"])

    def test_priority_action_is_rejected_when_research_is_unknown(self) -> None:
        screen = enrich_screen_readiness(self.screen_payload())
        evidence = build_evidence_bundle(
            screen,
            symbol="000001.SZ",
            contract_name="momentum_trade",
        )
        assessment = self.valid_assessment()
        assessment["expectation_gap"] = {"status": "unknown", "thesis": "", "basis": ""}

        with self.assertRaisesRegex(ValueError, "优先行动 requires"):
            confirm_evidence(evidence, assessment)

    def test_priority_action_is_rejected_when_technical_setup_is_unknown(self) -> None:
        screen = enrich_screen_readiness(self.screen_payload())
        evidence = build_evidence_bundle(
            screen,
            symbol="000001.SZ",
            contract_name="momentum_trade",
        )
        assessment = self.valid_assessment()
        assessment["technical_setup"]["trigger_rule"] = ""
        assessment["trade_plan"]["entry_trigger"] = ""

        with self.assertRaisesRegex(ValueError, "technical_setup"):
            confirm_evidence(evidence, assessment)

    def test_priority_action_requires_core_personal_risk_limits(self) -> None:
        screen = enrich_screen_readiness(self.screen_payload())
        evidence = build_evidence_bundle(
            screen,
            symbol="000001.SZ",
            contract_name="momentum_trade",
        )
        assessment = self.valid_assessment()
        assessment["investor_constraints"].pop("portfolio_heat_limit_pct")

        with self.assertRaisesRegex(ValueError, "personal-investor controls"):
            confirm_evidence(evidence, assessment)

    def test_recommendation_record_is_append_only_and_review_is_not_started(self) -> None:
        screen = enrich_screen_readiness(self.screen_payload())
        evidence = build_evidence_bundle(
            screen,
            symbol="000001.SZ",
            contract_name="momentum_trade",
        )
        compact = compact_confirmation(confirm_evidence(evidence, self.valid_assessment()))

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "market.sqlite"
            run_id = write_short_screen_run(compact, db_path=db_path, parent_run_id="evidence-1")
            loaded = load_short_screen_run(
                run_id,
                db_path=db_path,
                expected_operations=("short_confirmation",),
            )
            recommendations = list_short_recommendation_runs(db_path=db_path)

            self.assertEqual(loaded["parent_run_id"], "evidence-1")
            self.assertEqual(recommendations[0]["recommendation_run_id"], run_id)
            self.assertNotIn("review_status", recommendations[0])
            with closing(sqlite3.connect(db_path)) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(short_screen_run)")
                }
            self.assertTrue({"schema_version", "strategy_contract", "ts_code", "parent_run_id"} <= columns)

    def test_review_is_explicit_and_reports_research_path_not_account_return(self) -> None:
        screen = enrich_screen_readiness(self.screen_payload())
        evidence = build_evidence_bundle(
            screen,
            symbol="000001.SZ",
            contract_name="momentum_trade",
        )
        confirmation = compact_confirmation(confirm_evidence(evidence, self.valid_assessment()))
        dates = pd.bdate_range("2026-07-20", periods=5)
        price_history = pd.DataFrame(
            {
                "trade_date": dates,
                "ts_code": "000001.SZ",
                "close_qfq": [10.0, 10.4, 10.2, 10.8, 11.0],
                "low_qfq": [9.9, 10.1, 10.0, 10.5, 10.8],
                "high_qfq": [10.2, 10.5, 10.4, 10.9, 11.2],
            }
        )
        benchmark = pd.DataFrame(
            {"trade_date": dates, "close": [4000, 4010, 4005, 4020, 4040]}
        )

        review = review_recommendation(
            confirmation,
            {
                "event_outcome": "not_applicable",
                "thesis_outcome": "confirmed",
                "error_classification": "not_applicable",
            },
            review_as_of="20260724",
            price_history=price_history,
            benchmark_history=benchmark,
        )

        self.assertEqual(review["review_trigger"], "explicit_user_request")
        self.assertEqual(review["execution_status"], "not_observed")
        self.assertAlmostEqual(review["research_outcome"]["forward_return"], 0.1)
        self.assertIn("not account returns", review["boundary"])


if __name__ == "__main__":
    unittest.main()
