from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_data_store import load_research_observations, load_tushare_capabilities
from tushare_research_data import FAMILIES, DatasetSpec, _filter_available_as_of, main


class FinancialCatalogClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, endpoint: str):
        if endpoint not in {
            "income_vip",
            "balancesheet_vip",
            "cashflow_vip",
            "fina_indicator_vip",
        }:
            raise AttributeError(endpoint)

        def request(**params: object) -> pd.DataFrame:
            self.calls.append((endpoint, params))
            if endpoint == "income_vip":
                return pd.DataFrame(
                    [
                        {
                            "ts_code": "000001.SZ",
                            "ann_date": "20260701",
                            "end_date": "20260331",
                            "total_revenue": 100.0,
                        },
                        {
                            "ts_code": "000002.SZ",
                            "ann_date": "20260720",
                            "end_date": "20260331",
                            "total_revenue": 200.0,
                        },
                    ]
                )
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20260701",
                        "end_date": "20260331",
                        "value": 1.0,
                    }
                ]
            )

        return request


class TushareResearchDataTests(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            exit_code = main(args)
        return exit_code, json.loads(stream.getvalue())

    def test_catalog_includes_financial_macro_and_every_cross_asset_family(self) -> None:
        exit_code, payload = self._run_main(["catalog"])

        self.assertEqual(exit_code, 0)
        families = {item["key"] for item in payload["families"]}
        self.assertEqual(families, set(FAMILIES))
        financial = next(item for item in payload["families"] if item["key"] == "financial")
        endpoints = {item["endpoint"] for item in financial["datasets"]}
        self.assertTrue({"income_vip", "balancesheet_vip", "cashflow_vip", "fina_indicator_vip"}.issubset(endpoints))
        macro = next(item for item in payload["families"] if item["key"] == "macro")
        macro_endpoints = {item["endpoint"] for item in macro["datasets"]}
        self.assertTrue({"sf_month", "shibor", "shibor_quote", "shibor_lpr"}.issubset(macro_endpoints))
        self.assertFalse({"cn_sf", "cn_trade", "cn_money", "cn_finance"}.intersection(macro_endpoints))
        self.assertIn("yc_cb", macro_endpoints)
        self.assertTrue(next(item for item in macro["datasets"] if item["key"] == "yc_cb")["optional"])
        self.assertTrue(next(item for item in macro["datasets"] if item["key"] == "yc_cb")["permission_sensitive"])
        for family_name, prefix in (("hk", "hk"), ("us", "us")):
            family = next(item for item in payload["families"] if item["key"] == family_name)
            endpoints = {item["endpoint"] for item in family["datasets"]}
            self.assertTrue(
                {f"{prefix}_income", f"{prefix}_balancesheet", f"{prefix}_cashflow", f"{prefix}_fina_indicator"}.issubset(endpoints)
            )
        spot = next(item for item in payload["families"] if item["key"] == "spot")
        forex = next(item for item in payload["families"] if item["key"] == "forex")
        self.assertIn("sge_basic", {item["endpoint"] for item in spot["datasets"]})
        self.assertIn("fx_obasic", {item["endpoint"] for item in forex["datasets"]})
        self.assertIn("fund_manager", {item["endpoint"] for item in next(item for item in payload["families"] if item["key"] == "fund")["datasets"]})
        self.assertIn("index_dailybasic", {item["endpoint"] for item in next(item for item in payload["families"] if item["key"] == "index")["datasets"]})
        self.assertIn("fut_holding", {item["endpoint"] for item in next(item for item in payload["families"] if item["key"] == "futures")["datasets"]})
        self.assertIn("cb_issue", {item["endpoint"] for item in next(item for item in payload["families"] if item["key"] == "bond")["datasets"]})

    def test_financial_plan_uses_vip_period_requests_and_defers_company_events(self) -> None:
        exit_code, payload = self._run_main(
            ["plan", "financial", "--period", "20260331", "--as-of", "20260718"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["context"]["as_of"], "20260718")
        self.assertEqual(
            [dataset["endpoint"] for dataset in payload["datasets"]],
            ["income_vip", "balancesheet_vip", "cashflow_vip", "fina_indicator_vip"],
        )
        self.assertTrue(all(dataset["request"]["params"] == {"period": "20260331"} for dataset in payload["datasets"]))
        self.assertIn("forecast", {item["key"] for item in payload["deferred_datasets"]})

    def test_financial_fetch_filters_future_disclosures_and_caches_capabilities(self) -> None:
        client = FinancialCatalogClient()
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "research.sqlite"
            with patch("tushare_research_data.create_tushare_client", return_value=client):
                exit_code, payload = self._run_main(
                    [
                        "fetch",
                        "financial",
                        "--period",
                        "20260331",
                        "--as-of",
                        "20260718",
                        "--db-path",
                        str(db_path),
                        "--min-request-interval",
                        "0.001",
                        "--max-attempts",
                        "1",
                        "--preview-rows",
                        "0",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "complete")
            self.assertEqual([call[1] for call in client.calls], [{"period": "20260331"}] * 4)
            income = next(item for item in payload["results"] if item["key"] == "income_vip")
            self.assertEqual(income["raw_rows"], 2)
            self.assertEqual(income["rows"], 1)
            self.assertEqual(income["as_of_verification"]["field"], "ann_date")
            self.assertEqual(income["as_of_verification"]["excluded_rows"], 1)

            cached = load_research_observations(
                db_path=db_path,
                dataset="catalog_financial_income_vip",
                available_as_of="20260718",
            )
            self.assertEqual(cached["ts_code"].tolist(), ["000001.SZ"])
            capabilities = load_tushare_capabilities(db_path=db_path)
            self.assertEqual(set(capabilities["endpoint"]), {"income_vip", "balancesheet_vip", "cashflow_vip", "fina_indicator_vip"})

    def test_macro_without_release_date_is_not_presented_as_point_in_time_data(self) -> None:
        spec = DatasetSpec("cn_cpi", "cn_cpi", "test", lambda _context: {})
        frame = pd.DataFrame([{"month": "202606", "nt_yoy": 0.1}])

        filtered, verification = _filter_available_as_of(frame, spec, "20260718")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(verification["status"], "historically_unverified")

    def test_etf_plan_uses_market_master_without_symbol_and_adds_history_with_symbol(self) -> None:
        without_symbol_code, without_symbol = self._run_main(["plan", "etf", "--as-of", "20260718"])
        with_symbol_code, with_symbol = self._run_main(
            ["plan", "etf", "--symbol", "510300.SH", "--as-of", "20260718"]
        )

        self.assertEqual(without_symbol_code, 0)
        self.assertEqual([item["key"] for item in without_symbol["datasets"]], ["fund_basic"])
        self.assertEqual(with_symbol_code, 0)
        self.assertEqual([item["key"] for item in with_symbol["datasets"]], ["fund_basic", "fund_daily"])
        daily = with_symbol["datasets"][1]
        self.assertEqual(daily["request"]["params"]["ts_code"], "510300.SH")

    def test_overseas_financial_period_is_optional_but_preserved_when_requested(self) -> None:
        no_period_code, no_period = self._run_main(
            ["plan", "us", "--symbol", "NVDA", "--as-of", "20260718", "--datasets", "us_income"]
        )
        with_period_code, with_period = self._run_main(
            [
                "plan",
                "us",
                "--symbol",
                "NVDA",
                "--period",
                "20250126",
                "--as-of",
                "20260718",
                "--datasets",
                "us_income",
            ]
        )

        self.assertEqual(no_period_code, 0)
        self.assertEqual(no_period["datasets"][0]["request"]["params"], {"ts_code": "NVDA"})
        self.assertEqual(with_period_code, 0)
        self.assertEqual(
            with_period["datasets"][0]["request"]["params"],
            {"ts_code": "NVDA", "period": "20250126"},
        )

    def test_audit_and_main_business_period_are_optional(self) -> None:
        no_period_code, no_period = self._run_main(
            [
                "plan",
                "financial",
                "--symbol",
                "601088.SH",
                "--as-of",
                "20260718",
                "--datasets",
                "fina_audit",
                "fina_mainbz",
            ]
        )

        self.assertEqual(no_period_code, 0)
        self.assertEqual(
            [item["request"]["params"] for item in no_period["datasets"]],
            [{"ts_code": "601088.SH"}, {"ts_code": "601088.SH"}],
        )

    def test_end_date_cannot_extend_beyond_research_as_of(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "plan",
                        "etf",
                        "--as-of",
                        "20260718",
                        "--end-date",
                        "20260719",
                    ]
                )

        self.assertEqual(caught.exception.code, 2)

    def test_extended_catalog_uses_the_documented_market_specific_parameters(self) -> None:
        fund_code, fund = self._run_main(
            ["plan", "fund", "--symbol", "110011.OF", "--as-of", "20260718", "--datasets", "fund_manager"]
        )
        index_code, index = self._run_main(
            ["plan", "index", "--symbol", "000300.SH", "--as-of", "20260718", "--datasets", "index_dailybasic"]
        )
        futures_code, futures = self._run_main(
            ["plan", "futures", "--symbol", "IF", "--exchange", "CFFEX", "--as-of", "20260718", "--datasets", "fut_holding"]
        )
        bond_code, bond = self._run_main(
            ["plan", "bond", "--as-of", "20260718", "--datasets", "cb_issue"]
        )
        macro_code, macro = self._run_main(
            ["plan", "macro", "--as-of", "20260718", "--curve-type", "1", "--datasets", "yc_cb"]
        )

        self.assertEqual(fund_code, 0)
        self.assertEqual(fund["datasets"][0]["request"]["params"], {"ts_code": "110011.OF"})
        self.assertEqual(index_code, 0)
        self.assertEqual(index["datasets"][0]["request"]["params"], {"ts_code": "000300.SH", "trade_date": "20260718"})
        self.assertEqual(futures_code, 0)
        self.assertEqual(
            futures["datasets"][0]["request"]["params"],
            {"symbol": "IF", "start_date": "20260617", "end_date": "20260718", "exchange": "CFFEX"},
        )
        self.assertEqual(bond_code, 0)
        self.assertEqual(
            bond["datasets"][0]["request"]["params"],
            {"start_date": "20260617", "end_date": "20260718"},
        )
        self.assertEqual(macro_code, 0)
        self.assertEqual(
            macro["datasets"][0]["request"]["params"],
            {"ts_code": "1001.CB", "curve_type": "1", "start_date": "20260617", "end_date": "20260718"},
        )

    def test_option_daily_defaults_to_an_exchange_scoped_market_snapshot(self) -> None:
        market_code, market = self._run_main(["plan", "options", "--as-of", "20260718"])
        contract_code, contract = self._run_main(
            ["plan", "options", "--symbol", "10001313.SH", "--as-of", "20260718", "--datasets", "opt_daily"]
        )

        self.assertEqual(market_code, 0)
        daily = next(item for item in market["datasets"] if item["key"] == "opt_daily")
        self.assertEqual(daily["request"]["params"], {"trade_date": "20260718", "exchange": "SSE"})
        self.assertEqual(contract_code, 0)
        self.assertEqual(
            contract["datasets"][0]["request"]["params"],
            {"trade_date": "20260718", "ts_code": "10001313.SH", "exchange": "SSE"},
        )


if __name__ == "__main__":
    unittest.main()
