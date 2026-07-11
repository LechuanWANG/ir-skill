#!/usr/bin/env python3
"""Capability-aware TuShare research packets for intent-driven stock research."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_research_observations,
    load_tushare_capabilities,
    write_research_observations,
    write_tushare_capabilities,
)
from tushare_sync import create_tushare_client


DATE_FMT = "%Y%m%d"
USABLE_CAPABILITY_STATUSES = {"available", "empty"}
UNUSABLE_CAPABILITY_STATUSES = {"denied", "error"}


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    category: str
    scope: str
    lookback_days: int
    purpose: str
    fields: str | None = None
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ResearchProfile:
    name: str
    objective: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


def _spec(
    name: str,
    category: str,
    scope: str,
    lookback_days: int,
    purpose: str,
    *,
    fields: str | None = None,
    params: Mapping[str, str] | None = None,
) -> EndpointSpec:
    return EndpointSpec(
        name=name,
        category=category,
        scope=scope,
        lookback_days=lookback_days,
        purpose=purpose,
        fields=fields,
        params=tuple((params or {}).items()),
    )


ENDPOINT_SPECS = {
    spec.name: spec
    for spec in [
        _spec("trade_cal", "calendar", "calendar", 40, "Resolve trading dates and prevent stale as-of assumptions.", params={"exchange": "SSE"}),
        _spec("stock_basic", "universe", "static", 0, "Build the listed A-share universe and basic industry labels.", fields="ts_code,name,industry,market,list_date", params={"list_status": "L"}),
        _spec("daily", "market", "symbol_range", 1100, "Measure three-year return path, range regime, drawdown, volatility and liquidity context.", fields="ts_code,trade_date,open,high,low,close,vol,amount"),
        _spec("adj_factor", "market", "symbol_range", 1100, "Keep three-year price and shareholder-return comparisons consistent across corporate actions."),
        _spec("daily_basic", "valuation", "symbol_range", 1100, "Track valuation, turnover, market value and historical valuation percentiles.", fields="ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_mv,circ_mv,total_share,float_share,free_share"),
        _spec("fina_indicator", "quality", "symbol_range", 1300, "Measure profitability, growth, leverage and cash conversion."),
        _spec("income", "financials", "symbol_range", 1300, "Reconstruct revenue and profit trends from standardized statements."),
        _spec("balancesheet", "financials", "symbol_range", 1300, "Assess leverage, asset quality, working capital and solvency."),
        _spec("cashflow", "financials", "symbol_range", 1300, "Test earnings quality and financing dependence."),
        _spec("fina_mainbz", "business_segments", "symbol_range", 1300, "Identify segment mix, margin drivers and concentration risk.", params={"type": "P"}),
        _spec("forecast", "earnings", "symbol_range", 730, "Capture management earnings guidance and expected profit changes."),
        _spec("express", "earnings", "symbol_range", 730, "Capture preliminary earnings releases before full reports."),
        _spec("disclosure_date", "earnings_calendar", "symbol_calendar", 180, "Define the next financial validation window."),
        _spec("report_rc", "sell_side", "symbol_range", 730, "Measure sell-side forecast dispersion, revisions and target-price narratives."),
        _spec("stk_surv", "institutional_research", "symbol_range", 730, "Track institutional visits and management communication intensity."),
        _spec("dividend", "capital_actions", "symbol_only", 0, "Assess shareholder returns and dividend consistency."),
        _spec("repurchase", "capital_actions", "symbol_range", 730, "Detect buyback commitments and execution progress."),
        _spec("share_float", "capital_actions", "symbol_calendar", 180, "Identify upcoming lock-up expiries and supply pressure."),
        _spec("stk_holdertrade", "ownership", "symbol_range", 730, "Track controlling shareholder and executive transactions."),
        _spec("stk_holdernumber", "ownership", "symbol_range", 900, "Measure shareholder concentration and crowding changes."),
        _spec("top10_holders", "ownership", "symbol_range", 900, "Inspect major shareholder stability and ownership changes."),
        _spec("top10_floatholders", "ownership", "symbol_range", 900, "Inspect tradable-share ownership and institutional positioning."),
        _spec("pledge_stat", "risk", "symbol_only", 0, "Flag controlling-shareholder pledge and forced-sale risk."),
        _spec("moneyflow", "positioning", "symbol_range", 90, "Use order-size flows as positioning context, not a standalone signal."),
        _spec("cyq_perf", "positioning", "symbol_range", 90, "Estimate cost distribution, winner rate and trapped supply."),
        _spec("cyq_chips", "positioning", "symbol_trade_date", 0, "Inspect the latest detailed cost distribution when needed."),
        _spec("top_list", "event_flow", "symbol_trade_date", 0, "Check whether unusual trading reached the official top-list threshold."),
        _spec("top_inst", "event_flow", "symbol_trade_date", 0, "Separate institutional top-list activity from general turnover."),
        _spec("block_trade", "event_flow", "symbol_trade_date", 0, "Identify negotiated transactions and discount or premium clues."),
        _spec("margin_detail", "leverage_flow", "symbol_trade_date", 0, "Measure margin financing and short-selling exposure."),
        _spec("limit_list_d", "event", "symbol_trade_date", 0, "Describe limit-up or limit-down structure and trading crowding."),
        _spec("suspend_d", "event", "symbol_trade_date", 0, "Detect suspensions that invalidate price or liquidity assumptions."),
        _spec("stk_factor_pro", "technical_context", "symbol_range", 180, "Provide standardized technical context without making it the selection thesis."),
        _spec("index_daily", "benchmark", "index_range", 1100, "Compare three-year candidate returns and opportunity cost with a benchmark and market regime."),
        _spec("index_classify", "industry", "static", 0, "Load the current Shenwan level-one industry taxonomy.", params={"level": "L1", "src": "SW2021"}),
        _spec("index_member_all", "industry", "symbol_only", 0, "Map a stock to current Shenwan industry levels without relying on fuzzy labels."),
        _spec("ths_index", "theme", "static", 0, "Discover current Tonghuashun industry and concept indices.", params={"exchange": "A", "type": "N"}),
        _spec("ths_member", "theme", "index_only", 0, "Expand a chosen Tonghuashun theme into constituent candidates."),
        _spec("broker_recommend", "sell_side", "month", 0, "Use broker monthly picks only as a consensus and crowding reference."),
        _spec("shibor", "macro", "date_range", 400, "Track domestic money-market liquidity and funding conditions."),
        _spec("cn_cpi", "macro", "month_range", 730, "Track inflation and household pricing pressure."),
        _spec("cn_ppi", "macro", "month_range", 730, "Track industrial pricing and margin pressure."),
        _spec("cn_pmi", "macro", "month_range", 730, "Track manufacturing and services cycle direction."),
        _spec("cn_m", "macro", "month_range", 730, "Track money and credit conditions."),
    ]
}


PROFILE_SPECS = {
    profile.name: profile
    for profile in [
        ResearchProfile(
            "long-term-quality",
            "Find durable businesses with cash-backed earnings, sensible valuation and survivable balance sheets.",
            ("daily_basic", "fina_indicator", "income", "balancesheet", "cashflow", "fina_mainbz", "dividend", "pledge_stat"),
            ("stk_holdernumber", "top10_holders", "top10_floatholders", "report_rc", "stk_surv", "index_member_all"),
        ),
        ResearchProfile(
            "earnings-inflection",
            "Test whether earnings expectations are turning and identify the next validation window.",
            ("daily_basic", "fina_indicator", "income", "cashflow", "forecast", "express", "report_rc", "disclosure_date"),
            ("stk_surv", "moneyflow", "cyq_perf", "index_member_all"),
        ),
        ResearchProfile(
            "event-driven",
            "Evaluate corporate actions or trading events while separating durable catalysts from transient excitement.",
            ("daily_basic", "repurchase", "share_float", "stk_holdertrade", "stk_surv", "moneyflow", "limit_list_d", "suspend_d"),
            ("top_list", "top_inst", "block_trade", "margin_detail", "cyq_perf", "report_rc"),
        ),
        ResearchProfile(
            "valuation-repair",
            "Distinguish a genuine mispricing from a value trap.",
            ("daily_basic", "income", "balancesheet", "cashflow", "fina_indicator", "dividend"),
            ("report_rc", "pledge_stat", "stk_holdernumber", "index_member_all"),
        ),
        ResearchProfile(
            "industry-signal",
            "Translate an industry or policy signal into beneficiaries, earnings transmission and cycle risk.",
            ("index_member_all", "fina_mainbz", "report_rc", "stk_surv", "index_daily", "shibor", "cn_pmi", "cn_ppi", "cn_m"),
            ("daily_basic", "fina_indicator", "income", "moneyflow", "ths_index"),
        ),
        ResearchProfile(
            "risk-review",
            "Search for solvency, governance, ownership, pledge and liquidity risks before taking exposure.",
            ("balancesheet", "cashflow", "fina_indicator", "pledge_stat", "stk_holdernumber", "top10_holders", "top10_floatholders"),
            ("margin_detail", "suspend_d", "stk_holdertrade", "share_float"),
        ),
        ResearchProfile(
            "timing-liquidity",
            "Assess liquidity, crowding, cost distribution and entry timing after the investment thesis exists.",
            ("daily", "adj_factor", "daily_basic", "stk_factor_pro", "moneyflow", "cyq_perf"),
            ("cyq_chips", "top_list", "top_inst", "block_trade", "margin_detail", "limit_list_d"),
        ),
        ResearchProfile(
            "market-context",
            "Build the macro and benchmark context needed to interpret a stock or industry signal.",
            ("index_daily", "shibor", "cn_cpi", "cn_ppi", "cn_pmi", "cn_m"),
            ("stock_basic", "index_classify", "ths_index", "broker_recommend"),
        ),
    ]
}


def _normalize_date(value: str) -> str:
    return datetime.strptime(value, DATE_FMT).strftime(DATE_FMT)


def _start_date(as_of: str, lookback_days: int) -> str:
    end = datetime.strptime(_normalize_date(as_of), DATE_FMT)
    return (end - timedelta(days=max(lookback_days, 0))).strftime(DATE_FMT)


def _future_date(as_of: str, days: int) -> str:
    end = datetime.strptime(_normalize_date(as_of), DATE_FMT)
    return (end + timedelta(days=days)).strftime(DATE_FMT)


def _month(value: str) -> str:
    return _normalize_date(value)[:6]


def endpoint_requires_symbols(spec: EndpointSpec) -> bool:
    return spec.scope in {"symbol_range", "symbol_only", "symbol_calendar", "symbol_trade_date"}


def build_endpoint_requests(
    endpoint: str,
    *,
    symbols: Sequence[str] | None,
    as_of: str,
    lookback_days: int = 0,
    index_codes: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    if endpoint not in ENDPOINT_SPECS:
        raise KeyError(f"Unknown TuShare endpoint: {endpoint}")
    spec = ENDPOINT_SPECS[endpoint]
    end_date = _normalize_date(as_of)
    start_date = _start_date(end_date, max(lookback_days, spec.lookback_days))
    clean_symbols = [str(symbol) for symbol in symbols or [] if symbol]
    clean_indices = [str(code) for code in index_codes or [] if code]
    base: dict[str, object] = dict(spec.params)
    if spec.fields:
        base["fields"] = spec.fields

    if spec.scope == "static":
        return [base]
    if spec.scope == "calendar":
        return [{**base, "start_date": start_date, "end_date": end_date}]
    if spec.scope == "symbol_range":
        return [{**base, "ts_code": symbol, "start_date": start_date, "end_date": end_date} for symbol in clean_symbols]
    if spec.scope == "symbol_only":
        return [{**base, "ts_code": symbol} for symbol in clean_symbols]
    if spec.scope == "symbol_calendar":
        return [
            {
                **base,
                "ts_code": symbol,
                "start_date": _start_date(end_date, max(lookback_days, 180)),
                "end_date": _future_date(end_date, 365),
            }
            for symbol in clean_symbols
        ]
    if spec.scope == "symbol_trade_date":
        return [{**base, "ts_code": symbol, "trade_date": end_date} for symbol in clean_symbols]
    if spec.scope == "index_range":
        codes = clean_indices or ["000300.SH"]
        return [{**base, "ts_code": code, "start_date": start_date, "end_date": end_date} for code in codes]
    if spec.scope == "index_only":
        return [{**base, "ts_code": code} for code in clean_indices]
    if spec.scope == "month":
        return [{**base, "month": _month(end_date)}]
    if spec.scope == "month_range":
        return [{**base, "start_m": _month(start_date), "end_m": _month(end_date)}]
    if spec.scope == "date_range":
        return [{**base, "start_date": start_date, "end_date": end_date}]
    raise ValueError(f"Unsupported endpoint scope: {spec.scope}")


def _capability_statuses(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty:
        return {}
    return {
        str(row.endpoint): str(row.status)
        for row in frame[["endpoint", "status"]].itertuples(index=False)
    }


def build_research_plan(
    profiles: Sequence[str],
    *,
    symbols: Sequence[str] | None,
    as_of: str,
    lookback_days: int = 0,
    index_codes: Sequence[str] | None = None,
    capabilities: pd.DataFrame | None = None,
) -> dict[str, object]:
    if not profiles:
        raise ValueError("At least one research profile is required")
    unknown = [profile for profile in profiles if profile not in PROFILE_SPECS]
    if unknown:
        raise ValueError(f"Unknown research profile(s): {', '.join(unknown)}")

    selected: dict[str, bool] = {}
    objectives = []
    for profile_name in profiles:
        profile = PROFILE_SPECS[profile_name]
        objectives.append(profile.objective)
        for endpoint in profile.required:
            selected[endpoint] = True
        for endpoint in profile.optional:
            selected.setdefault(endpoint, False)

    statuses = _capability_statuses(capabilities if capabilities is not None else pd.DataFrame())
    datasets = []
    missing_inputs = []
    unavailable_required = []
    for endpoint, required in selected.items():
        spec = ENDPOINT_SPECS[endpoint]
        requests = build_endpoint_requests(
            endpoint,
            symbols=symbols,
            as_of=as_of,
            lookback_days=lookback_days,
            index_codes=index_codes,
        )
        capability = statuses.get(endpoint, "unverified")
        if not requests and (endpoint_requires_symbols(spec) or spec.scope == "index_only"):
            availability = "needs_input"
            missing_inputs.append(endpoint)
        elif capability in UNUSABLE_CAPABILITY_STATUSES:
            availability = capability
            if required:
                unavailable_required.append(endpoint)
        else:
            availability = capability
        datasets.append(
            {
                "endpoint": endpoint,
                "category": spec.category,
                "required": required,
                "purpose": spec.purpose,
                "scope": spec.scope,
                "lookback_days": max(lookback_days, spec.lookback_days),
                "capability": availability,
                "estimated_calls": len(requests),
            }
        )

    return {
        "profiles": list(profiles),
        "objectives": objectives,
        "as_of": _normalize_date(as_of),
        "symbols": [str(symbol) for symbol in symbols or [] if symbol],
        "index_codes": [str(code) for code in index_codes or [] if code],
        "workflow": "hypothesis -> data plan -> targeted collection -> evidence validation -> comparison",
        "technical_role": "liquidity, crowding and timing context only; never the sole selection thesis",
        "datasets": datasets,
        "missing_inputs": missing_inputs,
        "unavailable_required": unavailable_required,
    }


def build_staged_research_plan(
    *,
    symbols: Sequence[str] | None,
    as_of: str,
    current_profiles: Sequence[str] = ("market-context", "timing-liquidity"),
    lookback_days: int = 0,
    index_codes: Sequence[str] | None = None,
    capabilities: pd.DataFrame | None = None,
) -> dict[str, object]:
    long_term_profiles = ("long-term-quality", "risk-review")
    ordered_current = tuple(
        profile
        for profile in dict.fromkeys(current_profiles)
        if profile not in long_term_profiles and profile != "timing-liquidity"
    )
    ordered_current = (*ordered_current, "timing-liquidity")
    return {
        "as_of": _normalize_date(as_of),
        "symbols": [str(symbol) for symbol in symbols or [] if symbol],
        "stages": [
            {
                "stage": "long_term",
                "order": 1,
                "profiles": list(long_term_profiles),
                "gate_output": ["passed", "needs_evidence", "rejected"],
                "plan": build_research_plan(
                    long_term_profiles,
                    symbols=symbols,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    index_codes=index_codes,
                    capabilities=capabilities,
                ),
            },
            {
                "stage": "current_buyability",
                "order": 2,
                "profiles": list(ordered_current),
                "requires": "long_term.verdict == passed",
                "plan": build_research_plan(
                    ordered_current,
                    symbols=symbols,
                    as_of=as_of,
                    lookback_days=lookback_days,
                    index_codes=index_codes,
                    capabilities=capabilities,
                ),
            },
        ],
        "entry_action_values": ["staged_buy", "wait_price", "wait_evidence", "avoid"],
        "technical_role": "timing-liquidity is always the final profile and cannot change long-term admission",
    }


def _error_status(error: Exception) -> str:
    message = str(error).lower()
    return "denied" if "权限" in str(error) or "permission" in message or "积分" in str(error) else "error"


def _error_message(error: Exception) -> str:
    return str(error).replace("\n", " ")[:240]


def probe_capabilities(
    pro,
    *,
    endpoints: Sequence[str] | None = None,
    sample_symbol: str = "000001.SZ",
    as_of: str,
    index_codes: Sequence[str] | None = None,
    sleep_seconds: float = 0.08,
) -> list[dict[str, object]]:
    selected = list(endpoints) if endpoints else list(ENDPOINT_SPECS)
    results = []
    for endpoint in selected:
        if endpoint not in ENDPOINT_SPECS:
            results.append({"endpoint": endpoint, "category": "unknown", "status": "error", "rows": 0, "error": "unknown endpoint"})
            continue
        spec = ENDPOINT_SPECS[endpoint]
        requests = build_endpoint_requests(
            endpoint,
            symbols=[sample_symbol],
            as_of=as_of,
            lookback_days=min(max(spec.lookback_days, 30), 730),
            index_codes=index_codes,
        )
        if not requests:
            results.append({"endpoint": endpoint, "category": spec.category, "status": "needs_input", "rows": 0})
            continue
        try:
            frame = getattr(pro, endpoint)(**requests[0])
            rows = 0 if frame is None else len(frame)
            results.append(
                {
                    "endpoint": endpoint,
                    "category": spec.category,
                    "status": "available" if rows else "empty",
                    "rows": rows,
                    "columns": [] if frame is None else list(frame.columns),
                }
            )
        except Exception as error:
            results.append(
                {
                    "endpoint": endpoint,
                    "category": spec.category,
                    "status": _error_status(error),
                    "rows": 0,
                    "error": _error_message(error),
                }
            )
        time.sleep(max(sleep_seconds, 0))
    return results


def collect_research_data(
    pro,
    profiles: Sequence[str],
    *,
    symbols: Sequence[str] | None,
    as_of: str,
    db_path: Path = DEFAULT_DB_PATH,
    lookback_days: int = 0,
    index_codes: Sequence[str] | None = None,
    sleep_seconds: float = 0.08,
) -> dict[str, object]:
    capabilities = load_tushare_capabilities(db_path=db_path)
    plan = build_research_plan(
        profiles,
        symbols=symbols,
        as_of=as_of,
        lookback_days=lookback_days,
        index_codes=index_codes,
        capabilities=capabilities,
    )
    dataset_results = []
    capability_updates = []
    required_failures = []

    for item in plan["datasets"]:
        endpoint = str(item["endpoint"])
        required = bool(item["required"])
        if item["capability"] in UNUSABLE_CAPABILITY_STATUSES:
            result = {"endpoint": endpoint, "status": item["capability"], "calls": 0, "rows": 0, "stored_rows": 0}
            dataset_results.append(result)
            if required:
                required_failures.append(endpoint)
            continue

        requests = build_endpoint_requests(
            endpoint,
            symbols=symbols,
            as_of=as_of,
            lookback_days=lookback_days,
            index_codes=index_codes,
        )
        if not requests:
            result = {"endpoint": endpoint, "status": "needs_input", "calls": 0, "rows": 0, "stored_rows": 0}
            dataset_results.append(result)
            if required:
                required_failures.append(endpoint)
            continue

        rows_seen = 0
        stored_rows = 0
        calls = 0
        status = "empty"
        errors = []
        columns: set[str] = set()
        for request in requests:
            calls += 1
            try:
                frame = getattr(pro, endpoint)(**request)
                if frame is None:
                    frame = pd.DataFrame()
                rows_seen += len(frame)
                columns.update(str(column) for column in frame.columns)
                stored_rows += write_research_observations(endpoint, frame, db_path=db_path, source="tushare")
                if not frame.empty:
                    status = "available"
            except Exception as error:
                status = _error_status(error)
                errors.append(_error_message(error))
            time.sleep(max(sleep_seconds, 0))

        result = {
            "endpoint": endpoint,
            "status": status,
            "calls": calls,
            "rows": rows_seen,
            "stored_rows": stored_rows,
        }
        if errors:
            result["errors"] = errors
        dataset_results.append(result)
        capability_updates.append(
            {
                "endpoint": endpoint,
                "category": ENDPOINT_SPECS[endpoint].category,
                "status": status,
                "rows": rows_seen,
                "columns": sorted(columns),
                "errors": errors,
            }
        )
        if required and status in UNUSABLE_CAPABILITY_STATUSES:
            required_failures.append(endpoint)

    if capability_updates:
        write_tushare_capabilities(capability_updates, db_path=db_path)
    return {
        "plan": plan,
        "datasets": dataset_results,
        "required_failures": sorted(set(required_failures)),
        "db_path": str(db_path),
    }


def catalog_payload() -> dict[str, object]:
    return {
        "profiles": {
            name: {
                "objective": profile.objective,
                "required": list(profile.required),
                "optional": list(profile.optional),
            }
            for name, profile in PROFILE_SPECS.items()
        },
        "endpoints": {
            name: {
                "category": spec.category,
                "scope": spec.scope,
                "lookback_days": spec.lookback_days,
                "purpose": spec.purpose,
            }
            for name, spec in ENDPOINT_SPECS.items()
        },
    }


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _print_json(payload: object) -> None:
    print(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2, default=str, allow_nan=False))


def _add_context_arguments(parser: argparse.ArgumentParser, *, require_profiles: bool) -> None:
    if require_profiles:
        parser.add_argument("--profile", nargs="+", required=True, choices=sorted(PROFILE_SPECS))
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--index-codes", nargs="*", default=[])
    parser.add_argument("--as-of", default=datetime.now().strftime(DATE_FMT))
    parser.add_argument("--lookback-days", type=int, default=0, help="Optional minimum lookback override; each dataset has its own default.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and collect intent-driven TuShare research data packets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("catalog", help="List research profiles and endpoint purposes.")

    doctor = subparsers.add_parser("doctor", help="Probe current TuShare endpoint permissions with small requests.")
    doctor.add_argument("--endpoints", nargs="*", default=[])
    doctor.add_argument("--sample-symbol", default="000001.SZ")
    doctor.add_argument("--index-codes", nargs="*", default=[])
    doctor.add_argument("--as-of", default=datetime.now().strftime(DATE_FMT))
    doctor.add_argument("--sleep-seconds", type=float, default=0.08)
    doctor.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    plan = subparsers.add_parser("plan", help="Create a deterministic data plan without calling TuShare.")
    _add_context_arguments(plan, require_profiles=True)

    staged_plan = subparsers.add_parser(
        "staged-plan",
        help="Create a long-term-first data plan with a hard gate before current buyability data.",
    )
    staged_plan.add_argument("--symbols", nargs="*", default=[])
    staged_plan.add_argument("--current-profile", nargs="*", choices=sorted(PROFILE_SPECS), default=["market-context", "timing-liquidity"])
    staged_plan.add_argument("--index-codes", nargs="*", default=[])
    staged_plan.add_argument("--as-of", default=datetime.now().strftime(DATE_FMT))
    staged_plan.add_argument("--lookback-days", type=int, default=0)
    staged_plan.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    collect = subparsers.add_parser("collect", help="Execute a targeted plan and cache rows in SQLite.")
    _add_context_arguments(collect, require_profiles=True)
    collect.add_argument("--sleep-seconds", type=float, default=0.08)

    query = subparsers.add_parser("query", help="Read cached research observations from SQLite.")
    query.add_argument("--dataset")
    query.add_argument("--symbols", nargs="*", default=[])
    query.add_argument("--start-date")
    query.add_argument("--end-date")
    query.add_argument("--available-as-of", help="Return the latest revision publicly available by this date.")
    query.add_argument("--observed-as-of", help="Optional strict local-replay cutoff using first_seen_at.")
    query.add_argument("--include-revisions", action="store_true")
    query.add_argument("--limit", type=int, default=200)
    query.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "catalog":
        _print_json(catalog_payload())
        return 0
    if args.command == "doctor":
        pro = create_tushare_client()
        records = probe_capabilities(
            pro,
            endpoints=args.endpoints or None,
            sample_symbol=args.sample_symbol,
            as_of=args.as_of,
            index_codes=args.index_codes,
            sleep_seconds=args.sleep_seconds,
        )
        write_tushare_capabilities(records, db_path=args.db_path)
        _print_json({"db_path": str(args.db_path), "capabilities": records})
        return 0
    if args.command == "plan":
        capabilities = load_tushare_capabilities(db_path=args.db_path)
        plan = build_research_plan(
            args.profile,
            symbols=args.symbols,
            as_of=args.as_of,
            lookback_days=args.lookback_days,
            index_codes=args.index_codes,
            capabilities=capabilities,
        )
        _print_json(plan)
        return 0
    if args.command == "staged-plan":
        capabilities = load_tushare_capabilities(db_path=args.db_path)
        plan = build_staged_research_plan(
            symbols=args.symbols,
            as_of=args.as_of,
            current_profiles=args.current_profile,
            lookback_days=args.lookback_days,
            index_codes=args.index_codes,
            capabilities=capabilities,
        )
        _print_json(plan)
        return 0
    if args.command == "collect":
        pro = create_tushare_client()
        result = collect_research_data(
            pro,
            args.profile,
            symbols=args.symbols,
            as_of=args.as_of,
            db_path=args.db_path,
            lookback_days=args.lookback_days,
            index_codes=args.index_codes,
            sleep_seconds=args.sleep_seconds,
        )
        _print_json(result)
        return 2 if result["required_failures"] else 0
    if args.command == "query":
        frame = load_research_observations(
            db_path=args.db_path,
            dataset=args.dataset,
            symbols=args.symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            available_as_of=args.available_as_of,
            observed_as_of=args.observed_as_of,
            include_revisions=args.include_revisions,
            limit=args.limit,
        )
        _print_json({"rows": len(frame), "data": frame.to_dict(orient="records")})
        return 0
    raise RuntimeError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
