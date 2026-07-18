#!/usr/bin/env python3
"""Fetch catalogued TuShare research data across asset classes.

The catalog supplies reproducible, source-bounded requests for structured
financial, macroeconomic, and cross-asset observations. It intentionally does
not turn a secondary data vendor into a substitute for an issuer's final
financial-statement disclosure.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    persist_tushare_collection,
    write_tushare_capabilities,
)
from tushare_sync import create_tushare_client
from tushare_transport import TushareEndpointError, TushareRequestPolicy, request_endpoint


DATE_FORMAT = "%Y%m%d"
DEFAULT_PREVIEW_ROWS = 5
DEFAULT_LOOKBACK_DAYS = 31

FINANCIAL_SOURCE_POLICY = (
    "Use TuShare as the default structured source for financial screens, peer comparisons, "
    "disclosure timelines, and preliminary analysis. Confirm any financial-statement fact used "
    "as a final report conclusion against the issuer, exchange, CNInfo, or regulator disclosure "
    "when the result needs a formal citation, a unit/currency/consolidation check, or conflict resolution."
)
MARKET_SOURCE_POLICY = (
    "TuShare is the default structured source for market and cross-asset observations. Record "
    "the request date, market code, currency, adjustment basis, and returned fields before comparing assets."
)
MACRO_SOURCE_POLICY = (
    "TuShare is the default structured source for macroeconomic series. Preserve statistical period, "
    "release timing, revisions, and units; use the official release when a historical as-of release date "
    "or a definition conflict must be verified."
)


@dataclass(frozen=True)
class ResearchContext:
    family: str
    as_of: str
    start_date: str
    end_date: str
    symbol: str | None
    period: str | None
    market: str | None
    exchange: str | None
    macro_period: str | None
    curve_type: str | None


ParamsBuilder = Callable[[ResearchContext], dict[str, str]]


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    endpoint: str
    purpose: str
    params_builder: ParamsBuilder
    required_inputs: tuple[str, ...] = ()
    availability_fields: tuple[str, ...] = ()
    source_boundary: str = MARKET_SOURCE_POLICY
    optional: bool = False
    permission_sensitive: bool = False


@dataclass(frozen=True)
class FamilySpec:
    key: str
    label: str
    purpose: str
    source_policy: str
    datasets: tuple[DatasetSpec, ...]
    default_market: str | None = None
    default_exchange: str | None = None


def _period_params(context: ResearchContext) -> dict[str, str]:
    return {"period": _required(context.period, "period")}


def _symbol_params(context: ResearchContext) -> dict[str, str]:
    return {"ts_code": _required(context.symbol, "symbol")}


def _symbol_period_params(context: ResearchContext) -> dict[str, str]:
    return {
        "ts_code": _required(context.symbol, "symbol"),
        "period": _required(context.period, "period"),
    }


def _symbol_optional_period_params(context: ResearchContext) -> dict[str, str]:
    params = {"ts_code": _required(context.symbol, "symbol")}
    if context.period:
        params["period"] = context.period
    return params


def _symbol_range_params(context: ResearchContext) -> dict[str, str]:
    return {
        "ts_code": _required(context.symbol, "symbol"),
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _date_range_params(context: ResearchContext) -> dict[str, str]:
    return {
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _symbol_end_date_params(context: ResearchContext) -> dict[str, str]:
    return {
        "ts_code": _required(context.symbol, "symbol"),
        "trade_date": context.end_date,
    }


def _option_daily_params(context: ResearchContext) -> dict[str, str]:
    params = {"trade_date": context.end_date}
    if context.symbol:
        params["ts_code"] = context.symbol
    if context.exchange:
        params["exchange"] = context.exchange
    return params


def _fut_holding_params(context: ResearchContext) -> dict[str, str]:
    params = {
        "symbol": _required(context.symbol, "symbol"),
        "start_date": context.start_date,
        "end_date": context.end_date,
    }
    if context.exchange:
        params["exchange"] = context.exchange
    return params


def _yield_curve_params(context: ResearchContext) -> dict[str, str]:
    return {
        "ts_code": context.symbol or "1001.CB",
        "curve_type": context.curve_type or "0",
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _forecast_params(context: ResearchContext) -> dict[str, str]:
    return {
        "ts_code": _required(context.symbol, "symbol"),
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _fund_basic_params(context: ResearchContext) -> dict[str, str]:
    return {"market": _required(context.market, "market")}


def _index_basic_params(context: ResearchContext) -> dict[str, str]:
    return {"market": _required(context.market, "market")}


def _index_member_params(context: ResearchContext) -> dict[str, str]:
    return {"index_code": _required(context.symbol, "symbol")}


def _index_weight_params(context: ResearchContext) -> dict[str, str]:
    return {
        "index_code": _required(context.symbol, "symbol"),
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _fut_basic_params(context: ResearchContext) -> dict[str, str]:
    return {"exchange": _required(context.exchange, "exchange")}


def _option_basic_params(context: ResearchContext) -> dict[str, str]:
    return {"exchange": _required(context.exchange, "exchange")}


def _sge_daily_params(context: ResearchContext) -> dict[str, str]:
    return {"trade_date": context.end_date}


def _hk_basic_params(_: ResearchContext) -> dict[str, str]:
    return {"list_status": "L"}


def _macro_month_params(context: ResearchContext) -> dict[str, str]:
    return {"m": context.macro_period} if context.macro_period else {}


def _macro_quarter_params(context: ResearchContext) -> dict[str, str]:
    return {"q": context.macro_period} if context.macro_period else {}


def _no_params(_: ResearchContext) -> dict[str, str]:
    return {}


def _required(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} is required for this dataset")
    return value


FAMILIES: dict[str, FamilySpec] = {
    "financial": FamilySpec(
        key="financial",
        label="A-share financial statements and events",
        purpose="Run same-period, all-market statement screens and retrieve company-level financial events.",
        source_policy=FINANCIAL_SOURCE_POLICY,
        datasets=(
            DatasetSpec(
                key="income_vip",
                endpoint="income_vip",
                purpose="All-market income statements for one reporting period.",
                params_builder=_period_params,
                required_inputs=("period",),
                availability_fields=("ann_date", "f_ann_date"),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                permission_sensitive=True,
            ),
            DatasetSpec(
                key="balancesheet_vip",
                endpoint="balancesheet_vip",
                purpose="All-market balance sheets for one reporting period.",
                params_builder=_period_params,
                required_inputs=("period",),
                availability_fields=("ann_date", "f_ann_date"),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                permission_sensitive=True,
            ),
            DatasetSpec(
                key="cashflow_vip",
                endpoint="cashflow_vip",
                purpose="All-market cash-flow statements for one reporting period.",
                params_builder=_period_params,
                required_inputs=("period",),
                availability_fields=("ann_date", "f_ann_date"),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                permission_sensitive=True,
            ),
            DatasetSpec(
                key="fina_indicator_vip",
                endpoint="fina_indicator_vip",
                purpose="All-market financial indicators for one reporting period.",
                params_builder=_period_params,
                required_inputs=("period",),
                availability_fields=("ann_date", "f_ann_date"),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                permission_sensitive=True,
            ),
            DatasetSpec(
                key="forecast",
                endpoint="forecast",
                purpose="Company earnings forecasts and stated change reasons.",
                params_builder=_forecast_params,
                required_inputs=("symbol",),
                availability_fields=("ann_date",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
            ),
            DatasetSpec(
                key="express",
                endpoint="express",
                purpose="Company preliminary earnings releases.",
                params_builder=_symbol_params,
                required_inputs=("symbol",),
                availability_fields=("ann_date",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
            ),
            DatasetSpec(
                key="dividend",
                endpoint="dividend",
                purpose="Company dividend plans and execution dates.",
                params_builder=_symbol_params,
                required_inputs=("symbol",),
                availability_fields=("ann_date",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
            ),
            DatasetSpec(
                key="disclosure_date",
                endpoint="disclosure_date",
                purpose="Company scheduled and actual report disclosure dates.",
                params_builder=_symbol_params,
                required_inputs=("symbol",),
                availability_fields=("actual_date", "ann_date"),
                source_boundary=FINANCIAL_SOURCE_POLICY,
            ),
            DatasetSpec(
                key="fina_audit",
                endpoint="fina_audit",
                purpose="Company audit opinions and auditor information; optionally constrain to one reporting period.",
                params_builder=_symbol_optional_period_params,
                required_inputs=("symbol",),
                availability_fields=("ann_date",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
            ),
            DatasetSpec(
                key="fina_mainbz",
                endpoint="fina_mainbz",
                purpose="Company main-business composition; optionally constrain to one reporting period.",
                params_builder=_symbol_optional_period_params,
                required_inputs=("symbol",),
                availability_fields=("ann_date",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
            ),
        ),
    ),
    "macro": FamilySpec(
        key="macro",
        label="China macroeconomic data",
        purpose="Retrieve central macroeconomic series with their statistical periods preserved.",
        source_policy=MACRO_SOURCE_POLICY,
        datasets=(
            DatasetSpec("cn_gdp", "cn_gdp", "China GDP and sector contribution series.", _macro_quarter_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("cn_cpi", "cn_cpi", "China CPI series.", _macro_month_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("cn_ppi", "cn_ppi", "China PPI series.", _macro_month_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("cn_m", "cn_m", "China money-supply series.", _macro_month_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("sf_month", "sf_month", "China monthly aggregate-financing series.", _macro_month_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("cn_pmi", "cn_pmi", "China purchasing-manager indices.", _macro_month_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("shibor", "shibor", "Shanghai interbank offered-rate series.", _no_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("shibor_quote", "shibor_quote", "Shanghai interbank offered-rate quote observations.", _no_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec("shibor_lpr", "shibor_lpr", "China loan-prime-rate series.", _no_params, source_boundary=MACRO_SOURCE_POLICY),
            DatasetSpec(
                "yc_cb",
                "yc_cb",
                "ChinaBond government-yield curve observations; defaults to the maturity curve and 1001.CB.",
                _yield_curve_params,
                availability_fields=("trade_date",),
                source_boundary=MACRO_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
        ),
    ),
    "etf": FamilySpec(
        key="etf",
        label="Exchange-traded funds",
        purpose="Retrieve ETF master data and, when a code is supplied, its market history.",
        source_policy=MARKET_SOURCE_POLICY,
        default_market="E",
        datasets=(
            DatasetSpec("fund_basic", "fund_basic", "ETF instrument master data.", _fund_basic_params),
            DatasetSpec("fund_daily", "fund_daily", "ETF daily prices and volume.", _symbol_range_params, ("symbol",), ("trade_date",)),
            DatasetSpec("fund_adj", "fund_adj", "ETF adjustment factors.", _symbol_range_params, ("symbol",), ("trade_date",), optional=True),
            DatasetSpec("fund_share", "fund_share", "ETF fund-share changes.", _symbol_range_params, ("symbol",), ("trade_date",), optional=True),
        ),
    ),
    "fund": FamilySpec(
        key="fund",
        label="Public funds",
        purpose="Retrieve public-fund master data, NAV, and disclosed portfolio observations.",
        source_policy=MARKET_SOURCE_POLICY,
        default_market="O",
        datasets=(
            DatasetSpec("fund_basic", "fund_basic", "Open-ended fund master data.", _fund_basic_params),
            DatasetSpec("fund_nav", "fund_nav", "Fund net-asset-value history.", _symbol_range_params, ("symbol",), ("nav_date", "ann_date")),
            DatasetSpec("fund_portfolio", "fund_portfolio", "Fund disclosed holdings for a report period.", _symbol_period_params, ("symbol", "period"), ("ann_date",)),
            DatasetSpec("fund_manager", "fund_manager", "Fund-manager appointments and tenure history.", _symbol_params, ("symbol",), ("ann_date",)),
        ),
    ),
    "index": FamilySpec(
        key="index",
        label="Indices",
        purpose="Retrieve index universe, daily history, constituents, and historical weights.",
        source_policy=MARKET_SOURCE_POLICY,
        default_market="CSI",
        datasets=(
            DatasetSpec("index_basic", "index_basic", "Index master data for the selected index market.", _index_basic_params),
            DatasetSpec("index_daily", "index_daily", "Index daily price and volume history.", _symbol_range_params, ("symbol",), ("trade_date",)),
            DatasetSpec("index_dailybasic", "index_dailybasic", "Index daily valuation, turnover, and market-value snapshot.", _symbol_end_date_params, ("symbol",), ("trade_date",)),
            DatasetSpec("index_member", "index_member", "Current and historical index constituent records.", _index_member_params, ("symbol",), ("in_date", "out_date")),
            DatasetSpec("index_weight", "index_weight", "Index constituent weights over the requested period.", _index_weight_params, ("symbol",), ("trade_date",)),
        ),
    ),
    "futures": FamilySpec(
        key="futures",
        label="Futures",
        purpose="Retrieve contract universe and daily futures market observations.",
        source_policy=MARKET_SOURCE_POLICY,
        default_exchange="CFFEX",
        datasets=(
            DatasetSpec("fut_basic", "fut_basic", "Futures contract master data for the selected exchange.", _fut_basic_params),
            DatasetSpec("fut_daily", "fut_daily", "Futures daily prices, open interest, and turnover.", _symbol_range_params, ("symbol",), ("trade_date",)),
            DatasetSpec("fut_holding", "fut_holding", "Futures broker ranking by volume and long/short holdings.", _fut_holding_params, ("symbol",), ("trade_date",)),
        ),
    ),
    "spot": FamilySpec(
        key="spot",
        label="Spot commodities",
        purpose="Retrieve the Shanghai Gold Exchange spot market daily observations.",
        source_policy=MARKET_SOURCE_POLICY,
        datasets=(
            DatasetSpec("sge_basic", "sge_basic", "Shanghai Gold Exchange spot instrument master data.", _no_params),
            DatasetSpec("sge_daily", "sge_daily", "Shanghai Gold Exchange spot daily observations.", _sge_daily_params, availability_fields=("trade_date",)),
        ),
    ),
    "options": FamilySpec(
        key="options",
        label="Options",
        purpose="Retrieve option contract universe and one requested trading-day market snapshot.",
        source_policy=MARKET_SOURCE_POLICY,
        default_exchange="SSE",
        datasets=(
            DatasetSpec("opt_basic", "opt_basic", "Option contract master data for the selected exchange.", _option_basic_params),
            DatasetSpec("opt_daily", "opt_daily", "Market-wide option daily price, open-interest, and turnover snapshot; optionally narrow by contract.", _option_daily_params, availability_fields=("trade_date",)),
        ),
    ),
    "bond": FamilySpec(
        key="bond",
        label="Convertible bonds",
        purpose="Retrieve convertible-bond master data and daily market observations.",
        source_policy=MARKET_SOURCE_POLICY,
        datasets=(
            DatasetSpec("cb_basic", "cb_basic", "Convertible-bond instrument master data.", _no_params),
            DatasetSpec("cb_issue", "cb_issue", "Convertible-bond issuance plans, results, and subscription observations.", _date_range_params, availability_fields=("ann_date", "res_ann_date")),
            DatasetSpec("cb_daily", "cb_daily", "Convertible-bond daily market history.", _symbol_range_params, ("symbol",), ("trade_date",)),
        ),
    ),
    "forex": FamilySpec(
        key="forex",
        label="Foreign exchange",
        purpose="Retrieve exchange-rate daily history for an explicit TuShare FX code.",
        source_policy=MARKET_SOURCE_POLICY,
        datasets=(
            DatasetSpec("fx_obasic", "fx_obasic", "FXCM foreign-exchange and CFD instrument master data.", _no_params, permission_sensitive=True),
            DatasetSpec("fx_daily", "fx_daily", "FX daily price history.", _symbol_range_params, ("symbol",), ("trade_date",)),
        ),
    ),
    "hk": FamilySpec(
        key="hk",
        label="Hong Kong equities",
        purpose="Retrieve Hong Kong equity universe and daily observations.",
        source_policy=MARKET_SOURCE_POLICY,
        datasets=(
            DatasetSpec("hk_basic", "hk_basic", "Listed Hong Kong equity master data.", _hk_basic_params),
            DatasetSpec("hk_daily", "hk_daily", "Hong Kong equity daily price and volume history.", _symbol_range_params, ("symbol",), ("trade_date",)),
            DatasetSpec(
                "hk_income",
                "hk_income",
                "Hong Kong equity income-statement line items for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
            DatasetSpec(
                "hk_balancesheet",
                "hk_balancesheet",
                "Hong Kong equity balance-sheet line items for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
            DatasetSpec(
                "hk_cashflow",
                "hk_cashflow",
                "Hong Kong equity cash-flow line items for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
            DatasetSpec(
                "hk_fina_indicator",
                "hk_fina_indicator",
                "Hong Kong equity financial indicators for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
        ),
    ),
    "us": FamilySpec(
        key="us",
        label="United States equities",
        purpose="Retrieve United States equity universe and daily observations.",
        source_policy=MARKET_SOURCE_POLICY,
        datasets=(
            DatasetSpec("us_basic", "us_basic", "United States equity master data.", _no_params),
            DatasetSpec("us_daily", "us_daily", "United States equity daily price and volume history.", _symbol_range_params, ("symbol",), ("trade_date",)),
            DatasetSpec(
                "us_income",
                "us_income",
                "United States equity income-statement line items for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
            DatasetSpec(
                "us_balancesheet",
                "us_balancesheet",
                "United States equity balance-sheet line items for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
            DatasetSpec(
                "us_cashflow",
                "us_cashflow",
                "United States equity cash-flow line items for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
            DatasetSpec(
                "us_fina_indicator",
                "us_fina_indicator",
                "United States equity financial indicators for one reporting period.",
                _symbol_optional_period_params,
                ("symbol",),
                source_boundary=FINANCIAL_SOURCE_POLICY,
                optional=True,
                permission_sensitive=True,
            ),
        ),
    ),
}


def _date(value: str) -> str:
    normalized = value.strip().replace("-", "")
    try:
        return datetime.strptime(normalized, DATE_FORMAT).strftime(DATE_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYYMMDD or YYYY-MM-DD") from exc


def _symbol(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise argparse.ArgumentTypeError("symbol cannot be empty")
    return normalized


def _choice_text(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise argparse.ArgumentTypeError("value cannot be empty")
    return normalized


def _macro_period(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise argparse.ArgumentTypeError("macro period cannot be empty")
    return normalized


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _family(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in FAMILIES:
        raise argparse.ArgumentTypeError(f"family must be one of: {', '.join(sorted(FAMILIES))}")
    return normalized


def _context_from_args(args: argparse.Namespace) -> ResearchContext:
    family = FAMILIES[args.family]
    end_date = args.end_date or args.as_of
    start_date = args.start_date
    if start_date is None:
        end = datetime.strptime(end_date, DATE_FORMAT)
        start_date = (end - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime(DATE_FORMAT)
    if start_date > end_date:
        raise ValueError("--start-date must be earlier than or equal to --end-date")
    if end_date > args.as_of:
        raise ValueError("--end-date cannot be later than --as-of")
    context = ResearchContext(
        family=args.family,
        as_of=args.as_of,
        start_date=start_date,
        end_date=end_date,
        symbol=args.symbol,
        period=args.period,
        market=args.market or family.default_market,
        exchange=args.exchange or family.default_exchange,
        macro_period=args.macro_period,
        curve_type=args.curve_type,
    )
    return context


def _missing_inputs(spec: DatasetSpec, context: ResearchContext) -> tuple[str, ...]:
    return tuple(name for name in spec.required_inputs if not getattr(context, name))


def _selected_specs(
    family: FamilySpec,
    context: ResearchContext,
    requested_keys: Sequence[str] | None,
    include_optional: bool,
) -> tuple[tuple[DatasetSpec, ...], tuple[tuple[DatasetSpec, tuple[str, ...]], ...]]:
    requested = {key.strip() for key in requested_keys or [] if key.strip()}
    available_keys = {spec.key for spec in family.datasets}
    unknown_keys = sorted(requested - available_keys)
    if unknown_keys:
        raise ValueError(f"unknown dataset key(s) for {family.key}: {', '.join(unknown_keys)}")

    candidates = (
        tuple(spec for spec in family.datasets if spec.key in requested)
        if requested
        else tuple(spec for spec in family.datasets if include_optional or not spec.optional)
    )
    deferred: list[tuple[DatasetSpec, tuple[str, ...]]] = []
    selected: list[DatasetSpec] = []
    for spec in candidates:
        missing = _missing_inputs(spec, context)
        if missing:
            if requested:
                raise ValueError(f"{family.key}/{spec.key} requires: {', '.join(missing)}")
            deferred.append((spec, missing))
            continue
        selected.append(spec)
    if not selected:
        needs = sorted({name for _, missing in deferred for name in missing})
        suffix = f"; provide --{needs[0].replace('_', '-')}" if needs else ""
        raise ValueError(f"no runnable default datasets for {family.key}{suffix}")
    return tuple(selected), tuple(deferred)


def _dataset_name(family: str, spec: DatasetSpec) -> str:
    return f"catalog_{family}_{spec.key}"


def _request_for_spec(spec: DatasetSpec, context: ResearchContext) -> dict[str, Any]:
    return {"endpoint": spec.endpoint, "params": spec.params_builder(context)}


def _catalog_dataset(spec: DatasetSpec, family: FamilySpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "endpoint": spec.endpoint,
        "cache_dataset": _dataset_name(family.key, spec),
        "purpose": spec.purpose,
        "required_inputs": list(spec.required_inputs),
        "availability_fields": list(spec.availability_fields),
        "optional": spec.optional,
        "permission_sensitive": spec.permission_sensitive,
        "source_boundary": spec.source_boundary,
    }


def _context_payload(context: ResearchContext, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "as_of": context.as_of,
        "date_range": {
            "start_date": context.start_date,
            "end_date": context.end_date,
            "start_date_defaulted": args.start_date is None,
            "end_date_defaulted": args.end_date is None,
        },
        "symbol": context.symbol,
        "period": context.period,
        "market": context.market,
        "exchange": context.exchange,
        "macro_period": context.macro_period,
        "curve_type": context.curve_type,
    }


def _plan_payload(
    family: FamilySpec,
    context: ResearchContext,
    args: argparse.Namespace,
    selected: Sequence[DatasetSpec],
    deferred: Sequence[tuple[DatasetSpec, tuple[str, ...]]],
) -> dict[str, Any]:
    return {
        "operation": "plan",
        "family": family.key,
        "family_label": family.label,
        "family_purpose": family.purpose,
        "source_policy": family.source_policy,
        "context": _context_payload(context, args),
        "datasets": [
            {
                **_catalog_dataset(spec, family),
                "request": _request_for_spec(spec, context),
            }
            for spec in selected
        ],
        "deferred_datasets": [
            {
                **_catalog_dataset(spec, family),
                "missing_inputs": list(missing),
            }
            for spec, missing in deferred
        ],
        "as_of_rule": (
            "When a returned endpoint has an announced or actual disclosure date, records later than "
            "as_of are excluded before caching. Endpoints without a release-date field are marked as "
            "historically unverified rather than being treated as point-in-time data."
        ),
    }


def _normalized_date_strings(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip().str.replace(r"[^0-9]", "", regex=True)


def _filter_available_as_of(
    frame: pd.DataFrame,
    spec: DatasetSpec,
    as_of: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Exclude future disclosures only when the API supplied a usable release field."""
    if frame.empty:
        return frame, {"status": "not_applicable", "field": None, "excluded_rows": 0}
    if not spec.availability_fields:
        return frame, {
            "status": "historically_unverified",
            "field": None,
            "excluded_rows": 0,
            "reason": "endpoint has no configured release-date field",
        }
    for field in spec.availability_fields:
        if field not in frame.columns:
            continue
        normalized = _normalized_date_strings(frame[field])
        valid = normalized.str.fullmatch(r"\d{8}", na=False)
        if not valid.any():
            continue
        allowed = valid & (normalized <= as_of)
        filtered = frame.loc[allowed].copy()
        return filtered, {
            "status": "filtered",
            "field": field,
            "excluded_rows": int((~allowed).sum()),
            "known_release_rows": int(valid.sum()),
            "as_of": as_of,
        }
    return frame, {
        "status": "historically_unverified",
        "field": None,
        "excluded_rows": 0,
        "reason": "configured release-date field was absent or unusable in the response",
    }


def _preview_records(frame: pd.DataFrame, preview_rows: int) -> list[dict[str, Any]]:
    if preview_rows == 0 or frame.empty:
        return []
    return json.loads(frame.head(preview_rows).to_json(orient="records", force_ascii=False, date_format="iso"))


def _write_csv(
    frame: pd.DataFrame,
    output_dir: Path,
    family: str,
    spec: DatasetSpec,
    context: ResearchContext,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = context.symbol.replace(".", "_") if context.symbol else context.period or context.end_date
    output_path = output_dir / f"{family}_{spec.key}_{suffix}_{context.as_of}.csv"
    frame.to_csv(output_path, index=False)
    return output_path


def _capability_record(
    family: FamilySpec,
    spec: DatasetSpec,
    status: str,
    *,
    rows: int = 0,
    error_type: str | None = None,
    as_of_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "endpoint": spec.endpoint,
        "category": "research_catalog",
        "status": status,
        "rows": rows,
        "family": family.key,
        "catalog_dataset": spec.key,
        "permission_sensitive": spec.permission_sensitive,
    }
    if error_type:
        record["error_type"] = error_type
    if as_of_verification:
        record["as_of_verification"] = as_of_verification
    return record


def _run_catalog(_: argparse.Namespace) -> int:
    payload = {
        "operation": "catalog",
        "families": [
            {
                "key": family.key,
                "label": family.label,
                "purpose": family.purpose,
                "source_policy": family.source_policy,
                "default_market": family.default_market,
                "default_exchange": family.default_exchange,
                "datasets": [_catalog_dataset(spec, family) for spec in family.datasets],
            }
            for family in FAMILIES.values()
        ],
        "fallback": {
            "tool": "scripts/tushare_gateway.py",
            "use_for": "new or specialist TuShare endpoints not yet represented by this catalog",
            "boundary": "Pass explicit endpoint parameters and preserve the same source and as_of controls.",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    family = FAMILIES[args.family]
    context = _context_from_args(args)
    selected, deferred = _selected_specs(family, context, args.datasets, args.include_optional)
    print(json.dumps(_plan_payload(family, context, args, selected, deferred), ensure_ascii=False, indent=2))
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    family = FAMILIES[args.family]
    context = _context_from_args(args)
    selected, deferred = _selected_specs(family, context, args.datasets, args.include_optional)
    plan = _plan_payload(family, context, args, selected, deferred)
    if args.dry_run:
        plan["operation"] = "dry_run"
        plan["cache"] = args.cache
        plan["output_dir"] = str(args.output_dir) if args.output_dir else None
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    client = create_tushare_client(env_path=args.env_file)
    policy = TushareRequestPolicy(
        min_interval_seconds=args.min_request_interval,
        max_attempts=args.max_attempts,
    )
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []
    failures = 0

    for spec in selected:
        request = _request_for_spec(spec, context)
        try:
            raw_frame = request_endpoint(client, spec.endpoint, request["params"], policy=policy)
        except TushareEndpointError as exc:
            failures += 1
            capabilities.append(
                _capability_record(family, spec, "unavailable", error_type=exc.category)
            )
            results.append(
                {
                    "key": spec.key,
                    "endpoint": spec.endpoint,
                    "status": "unavailable",
                    "error": str(exc),
                    "error_type": exc.category,
                    "attempts": exc.attempts,
                    "retryable": exc.retryable,
                    "permission_sensitive": spec.permission_sensitive,
                    "source_boundary": spec.source_boundary,
                }
            )
            continue
        except ValueError as exc:
            failures += 1
            capabilities.append(
                _capability_record(family, spec, "unavailable", error_type="invalid_endpoint")
            )
            results.append(
                {
                    "key": spec.key,
                    "endpoint": spec.endpoint,
                    "status": "unavailable",
                    "error": str(exc),
                    "error_type": "invalid_endpoint",
                    "attempts": 0,
                    "retryable": False,
                    "permission_sensitive": spec.permission_sensitive,
                    "source_boundary": spec.source_boundary,
                }
            )
            continue

        frame, as_of_verification = _filter_available_as_of(raw_frame, spec, context.as_of)
        status = "empty" if frame.empty else "available"
        cached_rows = 0
        normalized_rows = 0
        if args.cache:
            cached_rows, normalized_rows = persist_tushare_collection(
                _dataset_name(family.key, spec),
                spec.endpoint,
                frame,
                db_path=args.db_path,
                retrieved_at=retrieved_at,
            )
        output = (
            _write_csv(frame, args.output_dir, family.key, spec, context)
            if args.output_dir is not None
            else None
        )
        capabilities.append(
            _capability_record(
                family,
                spec,
                status,
                rows=len(frame),
                as_of_verification=as_of_verification,
            )
        )
        results.append(
            {
                "key": spec.key,
                "endpoint": spec.endpoint,
                "status": status,
                "raw_rows": len(raw_frame),
                "rows": len(frame),
                "columns": list(frame.columns),
                "as_of_verification": as_of_verification,
                "cached_rows": cached_rows,
                "normalized_rows": normalized_rows,
                "output": str(output) if output else None,
                "permission_sensitive": spec.permission_sensitive,
                "source_boundary": spec.source_boundary,
                "preview": _preview_records(frame, args.preview_rows),
            }
        )

    if args.cache:
        write_tushare_capabilities(capabilities, db_path=args.db_path, checked_at=retrieved_at)
    payload = {
        "operation": "fetch",
        "status": "partial" if failures else "complete",
        "family": family.key,
        "family_label": family.label,
        "source_policy": family.source_policy,
        "context": _context_payload(context, args),
        "retrieved_at": retrieved_at,
        "cache": args.cache,
        "output_dir": str(args.output_dir) if args.output_dir else None,
        "deferred_datasets": [
            {"key": spec.key, "missing_inputs": list(missing)} for spec, missing in deferred
        ],
        "results": results,
        "next_step": (
            "Use the filtered structured data for screening and comparison. For a financial fact that "
            "will be presented as final evidence, perform source-boundary verification before reporting it."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    return 1 if failures and args.strict else 0


def _add_family_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("family", type=_family)
    parser.add_argument("--as-of", type=_date, required=True, help="Research information cutoff date")
    parser.add_argument("--symbol", type=_symbol, help="TuShare code for an instrument, company, or futures product")
    parser.add_argument("--period", type=_date, help="Financial or portfolio report period")
    parser.add_argument("--start-date", type=_date, help="Requested history start; defaults to 31 calendar days before end date")
    parser.add_argument("--end-date", type=_date, help="Requested history end; defaults to --as-of")
    parser.add_argument("--market", type=_choice_text, help="TuShare market code; family default applies when documented")
    parser.add_argument("--exchange", type=_choice_text, help="TuShare exchange code; family default applies when documented")
    parser.add_argument("--macro-period", type=_macro_period, help="Optional TuShare macro period, such as 202606 or 2026Q2")
    parser.add_argument("--curve-type", choices=("0", "1"), help="ChinaBond yield curve: 0=maturity, 1=spot")
    parser.add_argument("--datasets", nargs="+", help="Optional catalog dataset keys; explicit selection requires every input")
    parser.add_argument("--include-optional", action="store_true", help="Include optional, potentially higher-cost catalog datasets")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch catalogued TuShare financial, macro, and cross-asset research observations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("catalog", help="List productized TuShare research families and endpoints")

    plan_parser = subparsers.add_parser("plan", help="Show a family request plan without reading a token")
    _add_family_arguments(plan_parser)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one family request plan")
    _add_family_arguments(fetch_parser)
    fetch_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    fetch_parser.add_argument("--env-file", type=Path, help="Optional dotenv path used when no process token is set")
    fetch_parser.add_argument("--min-request-interval", type=_positive_float, default=0.6)
    fetch_parser.add_argument("--max-attempts", type=_positive_int, default=3)
    fetch_parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist rows and endpoint capability state to SQLite (default)",
    )
    fetch_parser.add_argument("--output-dir", type=Path, help="Optional directory for one CSV per dataset")
    fetch_parser.add_argument("--dry-run", action="store_true", help="Print requests without reading a token or calling TuShare")
    fetch_parser.add_argument("--strict", action="store_true", help="Return nonzero when any endpoint is unavailable")
    fetch_parser.add_argument("--preview-rows", type=_non_negative_int, default=DEFAULT_PREVIEW_ROWS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            return _run_catalog(args)
        if args.command == "plan":
            return _run_plan(args)
        return _run_fetch(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
