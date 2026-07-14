#!/usr/bin/env python3
"""Fetch mode-specific TuShare research data without verifying financial statements."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    write_research_observations,
    write_tushare_capabilities,
)
from tushare_gateway import request_endpoint
from tushare_sync import create_tushare_client


DATE_FORMAT = "%Y%m%d"
DEFAULT_PREVIEW_ROWS = 5
MODE_WINDOWS_DAYS = {"long": 365 * 5, "medium": 183, "short": 31}
MODE_LABELS = {
    "long": "长期价值投资（多年）",
    "medium": "中期投资（约 3–6 个月）",
    "short": "短期投资（一个月内）",
}
MODE_ALIASES = {
    "long": "long",
    "long-term": "long",
    "medium": "medium",
    "mid": "medium",
    "medium-term": "medium",
    "short": "short",
    "short-term": "short",
}
FINANCIAL_FACTS_POLICY = (
    "公司年报、半年报、季报等 PDF 原始披露，以及交易所/公司公告，是收入、利润、现金流、"
    "资产负债表和关键财务口径的最终事实来源。此脚本不复算、不核验、不替代这些披露；"
    "TuShare 的财务相关字段只可用于发现披露、时间线和待进一步阅读的线索。"
)


@dataclass(frozen=True)
class RequestContext:
    symbol: str
    start_date: str
    end_date: str


ParamsBuilder = Callable[[RequestContext], dict[str, str]]


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    endpoint: str
    purpose: str
    params_builder: ParamsBuilder
    fields: str | None = None
    optional: bool = False
    permission_sensitive: bool = False
    source_boundary: str | None = None


def _range_params(context: RequestContext) -> dict[str, str]:
    return {
        "ts_code": context.symbol,
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _symbol_params(context: RequestContext) -> dict[str, str]:
    return {"ts_code": context.symbol}


def _trade_date_params(context: RequestContext) -> dict[str, str]:
    return {"ts_code": context.symbol, "trade_date": context.end_date}


MARKET_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,"
    "dv_ratio,dv_ttm,total_mv,circ_mv,total_share,float_share,free_share"
)
ADJ_FACTOR_FIELDS = "ts_code,trade_date,adj_factor"
STOCK_BASIC_FIELDS = "ts_code,name,area,industry,market,list_date"
MONEYFLOW_FIELDS = (
    "ts_code,trade_date,buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount,"
    "buy_md_vol,buy_md_amount,sell_md_vol,sell_md_amount,buy_lg_vol,buy_lg_amount,"
    "sell_lg_vol,sell_lg_amount,buy_elg_vol,buy_elg_amount,sell_elg_vol,"
    "sell_elg_amount,net_mf_vol,net_mf_amount"
)
FORECAST_FIELDS = (
    "ts_code,ann_date,end_date,type,p_change_min,p_change_max,net_profit_min,"
    "net_profit_max,last_parent_net,last_year,summary,change_reason"
)
DISCLOSURE_DATE_FIELDS = "ts_code,ann_date,end_date,pre_date,actual_date,modify_date"
STK_LIMIT_FIELDS = "ts_code,trade_date,pre_close,up_limit,down_limit"


MODE_DATASETS: dict[str, tuple[DatasetSpec, ...]] = {
    "long": (
        DatasetSpec(
            key="market_price",
            endpoint="daily",
            purpose="建立长期价格、成交额和波动背景；不把日常价格波动升级为长期逻辑。",
            params_builder=_range_params,
            fields=MARKET_FIELDS,
        ),
        DatasetSpec(
            key="adjustment_factor",
            endpoint="adj_factor",
            purpose="明确历史价格复权口径，支持可复现的长期价格序列。",
            params_builder=_range_params,
            fields=ADJ_FACTOR_FIELDS,
        ),
        DatasetSpec(
            key="valuation_liquidity",
            endpoint="daily_basic",
            purpose="获取 PE、PB、PS、股息率、市值、换手和流通股本的历史观察。",
            params_builder=_range_params,
            fields=DAILY_BASIC_FIELDS,
        ),
        DatasetSpec(
            key="company_profile",
            endpoint="stock_basic",
            purpose="获取名称、行业、市场和上市日期，界定比较范围。",
            params_builder=_symbol_params,
            fields=STOCK_BASIC_FIELDS,
        ),
        DatasetSpec(
            key="dividend_history",
            endpoint="dividend",
            purpose="获取分红方案与日期，观察资本回报的历史线索。",
            params_builder=_symbol_params,
            source_boundary="分红方案的最终解释和执行状态以公司公告或财报 PDF 为准。",
        ),
        DatasetSpec(
            key="share_float",
            endpoint="share_float",
            purpose="观察限售解禁和流通股变化，识别潜在稀释与供给压力。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="major_holders",
            endpoint="top10_holders",
            purpose="观察大股东结构变化，形成治理和集中度研究线索。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="股东持股和治理结论以定期报告、权益变动或交易所公告为准。",
        ),
        DatasetSpec(
            key="pledge_risk",
            endpoint="pledge_stat",
            purpose="观察股权质押风险线索，决定是否追加原始披露阅读。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="质押风险的金额、比例和后续处置以公告原文为准。",
        ),
    ),
    "medium": (
        DatasetSpec(
            key="market_price",
            endpoint="daily",
            purpose="跟踪催化窗口内的价格、成交额和波动变化。",
            params_builder=_range_params,
            fields=MARKET_FIELDS,
        ),
        DatasetSpec(
            key="adjustment_factor",
            endpoint="adj_factor",
            purpose="统一价格复权口径，避免把除权除息误读为催化反应。",
            params_builder=_range_params,
            fields=ADJ_FACTOR_FIELDS,
        ),
        DatasetSpec(
            key="valuation_liquidity",
            endpoint="daily_basic",
            purpose="观察估值、换手、市值和流动性是否已反映预期。",
            params_builder=_range_params,
            fields=DAILY_BASIC_FIELDS,
        ),
        DatasetSpec(
            key="money_flow",
            endpoint="moneyflow",
            purpose="观察不同单量资金流的变化；资金流只解释拥挤和定价，不证明基本面。",
            params_builder=_range_params,
            fields=MONEYFLOW_FIELDS,
        ),
        DatasetSpec(
            key="earnings_forecast",
            endpoint="forecast",
            purpose="定位业绩预告、发布时间和预期变化，建立催化时间线。",
            params_builder=_range_params,
            fields=FORECAST_FIELDS,
            source_boundary="业绩预告不替代正式财报；公布后必须阅读公司或交易所披露的 PDF/原文。",
        ),
        DatasetSpec(
            key="earnings_express",
            endpoint="express",
            purpose="定位业绩快报与预期差线索，检查市场是否已定价。",
            params_builder=_range_params,
            source_boundary="业绩快报和正式财报的数字以公司披露原文为准。",
        ),
        DatasetSpec(
            key="disclosure_calendar",
            endpoint="disclosure_date",
            purpose="获取预披露、实际披露和变更日期，区分事件发生、公开披露和市场定价。",
            params_builder=_symbol_params,
            fields=DISCLOSURE_DATE_FIELDS,
        ),
        DatasetSpec(
            key="margin_detail",
            endpoint="margin_detail",
            purpose="观察最近交易日融资融券余额与变化，识别拥挤和流动性风险。",
            params_builder=_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="top_list",
            endpoint="top_list",
            purpose="观察最近交易日龙虎榜异动，作为事件定价和拥挤线索。",
            params_builder=_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="institutional_seats",
            endpoint="top_inst",
            purpose="观察龙虎榜机构席位净买卖，辅助判断成交结构。",
            params_builder=_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="stock_factor",
            endpoint="stk_factor_pro",
            purpose="按需获取扩展量价因子，辅助研究而不直接生成交易信号。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
    ),
    "short": (
        DatasetSpec(
            key="market_price",
            endpoint="daily",
            purpose="跟踪一个月内的价格、成交额、波动和跳空风险。",
            params_builder=_range_params,
            fields=MARKET_FIELDS,
        ),
        DatasetSpec(
            key="adjustment_factor",
            endpoint="adj_factor",
            purpose="统一事件窗口的价格复权口径。",
            params_builder=_range_params,
            fields=ADJ_FACTOR_FIELDS,
        ),
        DatasetSpec(
            key="valuation_liquidity",
            endpoint="daily_basic",
            purpose="观察换手、量比、市值和估值变化，评估可执行性与拥挤。",
            params_builder=_range_params,
            fields=DAILY_BASIC_FIELDS,
        ),
        DatasetSpec(
            key="money_flow",
            endpoint="moneyflow",
            purpose="观察资金流和成交结构的短期变化；它不构成单独的交易依据。",
            params_builder=_range_params,
            fields=MONEYFLOW_FIELDS,
        ),
        DatasetSpec(
            key="price_limit",
            endpoint="stk_limit",
            purpose="获取每日涨跌停价，纳入 A 股涨跌停和隔夜跳空约束。",
            params_builder=_range_params,
            fields=STK_LIMIT_FIELDS,
        ),
        DatasetSpec(
            key="limit_list",
            endpoint="limit_list_d",
            purpose="观察最近交易日涨跌停状态和封单线索，评估流动性与退出约束。",
            params_builder=_trade_date_params,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="top_list",
            endpoint="top_list",
            purpose="观察最近交易日龙虎榜异动，区分事件反应与单纯热度。",
            params_builder=_trade_date_params,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="institutional_seats",
            endpoint="top_inst",
            purpose="观察龙虎榜机构席位净买卖，辅助判断成交结构与拥挤。",
            params_builder=_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="margin_detail",
            endpoint="margin_detail",
            purpose="观察最近交易日融资融券余额，识别杠杆与流动性风险。",
            params_builder=_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="suspensions",
            endpoint="suspend_d",
            purpose="观察停复牌信息，纳入无法交易和事件跳空风险。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
        ),
    ),
}


def _mode(value: str) -> str:
    normalized = value.strip().lower()
    mode = MODE_ALIASES.get(normalized)
    if mode is None:
        choices = ", ".join(sorted(MODE_ALIASES))
        raise argparse.ArgumentTypeError(f"mode must be one of: {choices}")
    return mode


def _symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not symbol:
        raise argparse.ArgumentTypeError("symbol cannot be empty")
    return symbol


def _date(value: str) -> str:
    normalized = value.strip().replace("-", "")
    try:
        return datetime.strptime(normalized, DATE_FORMAT).strftime(DATE_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYYMMDD or YYYY-MM-DD") from exc


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _default_start_date(mode: str, end_date: str) -> str:
    parsed_end_date = datetime.strptime(end_date, DATE_FORMAT)
    return (parsed_end_date - timedelta(days=MODE_WINDOWS_DAYS[mode])).strftime(DATE_FORMAT)


def _context_from_args(args: argparse.Namespace, *, allow_default_end_date: bool) -> tuple[RequestContext, bool, bool]:
    end_date = args.end_date
    defaulted_end_date = False
    if end_date is None:
        if not allow_default_end_date:
            raise ValueError("--end-date is required for fetch so the research as_of is explicit")
        end_date = datetime.now().strftime(DATE_FORMAT)
        defaulted_end_date = True
    start_date = args.start_date or _default_start_date(args.mode, end_date)
    if start_date > end_date:
        raise ValueError("start_date must be earlier than or equal to end_date")
    return RequestContext(symbol=args.symbol, start_date=start_date, end_date=end_date), args.start_date is None, defaulted_end_date


def _request_for_spec(spec: DatasetSpec, context: RequestContext) -> dict[str, Any]:
    params = spec.params_builder(context)
    if spec.fields:
        params["fields"] = spec.fields
    return {"endpoint": spec.endpoint, "params": params}


def _selected_specs(
    mode: str,
    requested_keys: Sequence[str] | None,
    include_optional: bool,
) -> tuple[DatasetSpec, ...]:
    specs = MODE_DATASETS[mode]
    available_keys = {spec.key for spec in specs}
    requested = {key.strip() for key in requested_keys or [] if key.strip()}
    unknown_keys = sorted(requested - available_keys)
    if unknown_keys:
        raise ValueError(f"unknown dataset key(s) for {mode}: {', '.join(unknown_keys)}")
    if requested:
        selected = tuple(spec for spec in specs if spec.key in requested)
    else:
        selected = tuple(spec for spec in specs if include_optional or not spec.optional)
    if not selected:
        raise ValueError("select at least one dataset")
    return selected


def _dataset_name(mode: str, spec: DatasetSpec) -> str:
    return f"mode_{mode}_{spec.key}"


def _plan_payload(
    *,
    mode: str,
    context: RequestContext,
    selected_specs: Sequence[DatasetSpec],
    defaulted_start_date: bool,
    defaulted_end_date: bool,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "symbol": context.symbol,
        "date_range": {
            "start_date": context.start_date,
            "end_date": context.end_date,
            "start_date_defaulted": defaulted_start_date,
            "end_date_defaulted": defaulted_end_date,
        },
        "financial_facts_policy": FINANCIAL_FACTS_POLICY,
        "instructions": [
            "Use the data as research observations, not a rating, screening result, or buy/sell signal.",
            "Record the requested end date, endpoint permission, retrieval time, and any missing dataset in the research record.",
            "Use original disclosure for final financial facts and material corporate actions.",
        ],
        "datasets": [
            {
                "key": spec.key,
                "cache_dataset": _dataset_name(mode, spec),
                "purpose": spec.purpose,
                "optional": spec.optional,
                "permission_sensitive": spec.permission_sensitive,
                "source_boundary": spec.source_boundary,
                "request": _request_for_spec(spec, context),
            }
            for spec in selected_specs
        ],
    }


def _preview_records(frame: pd.DataFrame, preview_rows: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.head(preview_rows).to_json(orient="records", force_ascii=False, date_format="iso"))


def _write_csv(frame: pd.DataFrame, output_dir: Path, mode: str, spec: DatasetSpec, context: RequestContext) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{mode}_{spec.key}_{context.symbol.replace('.', '_')}_{context.end_date}.csv"
    output_path = output_dir / filename
    frame.to_csv(output_path, index=False)
    return output_path


def _capability_record(spec: DatasetSpec, status: str, rows: int = 0, error: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "endpoint": spec.endpoint,
        "category": "mode_data",
        "status": status,
        "rows": rows,
        "mode_dataset": spec.key,
    }
    if error:
        record["error_type"] = error
    return record


def _run_plan(args: argparse.Namespace) -> int:
    context, defaulted_start_date, defaulted_end_date = _context_from_args(args, allow_default_end_date=True)
    selected_specs = _selected_specs(args.mode, args.datasets, args.include_optional)
    print(
        json.dumps(
            _plan_payload(
                mode=args.mode,
                context=context,
                selected_specs=selected_specs,
                defaulted_start_date=defaulted_start_date,
                defaulted_end_date=defaulted_end_date,
            ),
            ensure_ascii=False,
            default=str,
            indent=2,
        )
    )
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    context, defaulted_start_date, defaulted_end_date = _context_from_args(args, allow_default_end_date=False)
    selected_specs = _selected_specs(args.mode, args.datasets, args.include_optional)
    plan = _plan_payload(
        mode=args.mode,
        context=context,
        selected_specs=selected_specs,
        defaulted_start_date=defaulted_start_date,
        defaulted_end_date=defaulted_end_date,
    )
    if args.dry_run:
        plan["operation"] = "dry_run"
        plan["cache"] = args.cache
        plan["output_dir"] = str(args.output_dir) if args.output_dir else None
        print(json.dumps(plan, ensure_ascii=False, default=str, indent=2))
        return 0

    client = create_tushare_client()
    results: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []
    failures = 0
    for spec in selected_specs:
        request = _request_for_spec(spec, context)
        try:
            frame = request_endpoint(client, spec.endpoint, request["params"])
        except (RuntimeError, ValueError) as exc:
            failures += 1
            error = str(exc)
            capabilities.append(_capability_record(spec, "unavailable", error=error))
            results.append(
                {
                    "key": spec.key,
                    "endpoint": spec.endpoint,
                    "status": "unavailable",
                    "error": error,
                    "permission_sensitive": spec.permission_sensitive,
                }
            )
            continue

        status = "empty" if frame.empty else "available"
        cached_rows = write_research_observations(_dataset_name(args.mode, spec), frame, db_path=args.db_path) if args.cache else 0
        output = _write_csv(frame, args.output_dir, args.mode, spec, context) if args.output_dir else None
        capabilities.append(_capability_record(spec, status, rows=len(frame)))
        results.append(
            {
                "key": spec.key,
                "endpoint": spec.endpoint,
                "status": status,
                "rows": len(frame),
                "columns": list(frame.columns),
                "cached_rows": cached_rows,
                "output": str(output) if output else None,
                "permission_sensitive": spec.permission_sensitive,
                "source_boundary": spec.source_boundary,
                "preview": _preview_records(frame, args.preview_rows),
            }
        )

    if args.cache:
        write_tushare_capabilities(capabilities, db_path=args.db_path)
    payload = {
        "operation": "fetch",
        "status": "partial" if failures else "complete",
        "mode": args.mode,
        "mode_label": MODE_LABELS[args.mode],
        "symbol": context.symbol,
        "date_range": {"start_date": context.start_date, "end_date": context.end_date},
        "financial_facts_policy": FINANCIAL_FACTS_POLICY,
        "cache": args.cache,
        "output_dir": str(args.output_dir) if args.output_dir else None,
        "results": results,
        "next_step": "Read original disclosures for any financial or corporate-action fact used in the report.",
    }
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    return 1 if failures and args.strict else 0


def _add_common_arguments(parser: argparse.ArgumentParser, *, require_end_date: bool) -> None:
    parser.add_argument("mode", type=_mode, help="long, medium, or short")
    parser.add_argument("--symbol", type=_symbol, required=True, help="TuShare ts_code, such as 000001.SZ")
    parser.add_argument("--start-date", type=_date, help="YYYYMMDD; defaults to a mode-specific lookback window")
    parser.add_argument("--end-date", type=_date, required=require_end_date, help="YYYYMMDD research as_of date")
    parser.add_argument(
        "--datasets",
        nargs="+",
        help="Optional dataset keys from this mode's plan; selecting a key also selects an optional dataset",
    )
    parser.add_argument("--include-optional", action="store_true", help="Include permission-sensitive optional datasets")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch mode-specific TuShare market research data without financial-statement verification."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Show the smallest mode-specific data plan without calling TuShare")
    _add_common_arguments(plan_parser, require_end_date=False)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one mode-specific data plan")
    _add_common_arguments(fetch_parser, require_end_date=True)
    fetch_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    fetch_parser.add_argument("--cache", action="store_true", help="Store raw endpoint rows and capability status in SQLite")
    fetch_parser.add_argument("--output-dir", type=Path, help="Optional directory for one CSV per dataset")
    fetch_parser.add_argument("--dry-run", action="store_true", help="Print requests without reading a token or calling TuShare")
    fetch_parser.add_argument("--strict", action="store_true", help="Return a nonzero exit status when any endpoint is unavailable")
    fetch_parser.add_argument("--preview-rows", type=_positive_int, default=DEFAULT_PREVIEW_ROWS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            return _run_plan(args)
        return _run_fetch(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
