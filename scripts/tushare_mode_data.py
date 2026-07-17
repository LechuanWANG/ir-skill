#!/usr/bin/env python3
"""Fetch mode-specific TuShare research data without verifying financial statements."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_daily_matrices,
    persist_tushare_collection,
    write_tushare_capabilities,
)
from technical_indicators import TechnicalIndicatorSettings, calculate_technical_indicators
from tushare_gateway import request_endpoint
from tushare_sync import create_tushare_client


DATE_FORMAT = "%Y%m%d"
DEFAULT_PREVIEW_ROWS = 5
DEFAULT_BENCHMARK = "000300.SH"
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
    benchmark: str
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


def _benchmark_range_params(context: RequestContext) -> dict[str, str]:
    return {
        "ts_code": context.benchmark,
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _market_trade_date_params(context: RequestContext) -> dict[str, str]:
    return {"trade_date": context.end_date}


def _calendar_params(context: RequestContext) -> dict[str, str]:
    return {
        "exchange": "SSE",
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


def _industry_classification_params(_: RequestContext) -> dict[str, str]:
    return {"src": "SW2021", "level": "L1"}


def _benchmark_weight_params(context: RequestContext) -> dict[str, str]:
    return {
        "index_code": context.benchmark,
        "start_date": context.start_date,
        "end_date": context.end_date,
    }


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
INDEX_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
INDEX_DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,total_mv,float_mv,total_share,float_share,free_share,turnover_rate,"
    "turnover_rate_f,pe,pe_ttm,pb"
)
TRADE_CAL_FIELDS = "exchange,cal_date,is_open,pretrade_date"
DAILY_INFO_FIELDS = (
    "trade_date,ts_code,ts_name,com_count,total_share,float_share,total_mv,float_mv,amount,vol,"
    "trans_count,pe,tr,exchange"
)
MARKET_MONEYFLOW_FIELDS = (
    "trade_date,close_sh,pct_change_sh,close_sz,pct_change_sz,net_amount,net_amount_rate,"
    "buy_elg_amount,buy_elg_amount_rate,buy_lg_amount,buy_lg_amount_rate,buy_md_amount,"
    "buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate"
)
MARKET_MARGIN_FIELDS = "trade_date,exchange_id,rzye,rzmre,rzche,rqye,rqmcl,rzrqye,rqyl"
INDEX_CLASSIFICATION_FIELDS = "index_code,industry_name,level,industry_code,is_pub,parent_code,src"
INDEX_WEIGHT_FIELDS = "index_code,con_code,trade_date,weight"


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
            key="benchmark_price",
            endpoint="index_daily",
            purpose="以指定宽基或行业指数建立长期相对收益、成交和波动基准。",
            params_builder=_benchmark_range_params,
            fields=INDEX_DAILY_FIELDS,
        ),
        DatasetSpec(
            key="benchmark_valuation",
            endpoint="index_dailybasic",
            purpose="观察基准指数的估值、换手和流通市值，避免孤立解读个股估值。",
            params_builder=_benchmark_range_params,
            fields=INDEX_DAILY_BASIC_FIELDS,
        ),
        DatasetSpec(
            key="market_calendar",
            endpoint="trade_cal",
            purpose="记录交易日与前一交易日，区分非交易日、停牌和真实数据缺口。",
            params_builder=_calendar_params,
            fields=TRADE_CAL_FIELDS,
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
            key="industry_taxonomy",
            endpoint="index_classify",
            purpose="获取申万一级行业定义，支持行业口径一致的横向比较。",
            params_builder=_industry_classification_params,
            fields=INDEX_CLASSIFICATION_FIELDS,
            optional=True,
        ),
        DatasetSpec(
            key="benchmark_weights",
            endpoint="index_weight",
            purpose="获取指定基准历史权重，判断相对表现是否主要来自指数权重与行业暴露。",
            params_builder=_benchmark_weight_params,
            fields=INDEX_WEIGHT_FIELDS,
            optional=True,
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
            key="benchmark_price",
            endpoint="index_daily",
            purpose="以指定基准分离个股催化与市场整体价格变化。",
            params_builder=_benchmark_range_params,
            fields=INDEX_DAILY_FIELDS,
        ),
        DatasetSpec(
            key="benchmark_valuation",
            endpoint="index_dailybasic",
            purpose="比较个股与市场基准的估值、换手和流通市值变化。",
            params_builder=_benchmark_range_params,
            fields=INDEX_DAILY_BASIC_FIELDS,
        ),
        DatasetSpec(
            key="market_calendar",
            endpoint="trade_cal",
            purpose="固定交易日口径，避免把非交易日或停牌误读为数据缺口。",
            params_builder=_calendar_params,
            fields=TRADE_CAL_FIELDS,
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
            key="market_breadth",
            endpoint="daily_info",
            purpose="观察交易所级市值、成交和估值背景，判断个股变化是否发生在普遍风险偏好切换中。",
            params_builder=_market_trade_date_params,
            fields=DAILY_INFO_FIELDS,
        ),
        DatasetSpec(
            key="market_money_flow",
            endpoint="moneyflow_mkt_dc",
            purpose="观察全市场分单资金净流入，作为个股资金流的背景而非基本面证据。",
            params_builder=_market_trade_date_params,
            fields=MARKET_MONEYFLOW_FIELDS,
        ),
        DatasetSpec(
            key="market_margin",
            endpoint="margin",
            purpose="观察交易所级融资融券余额和增减，识别市场杠杆与流动性状态。",
            params_builder=_market_trade_date_params,
            fields=MARKET_MARGIN_FIELDS,
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
            key="benchmark_price",
            endpoint="index_daily",
            purpose="以指定基准判断短期相对强弱，避免把市场普涨或普跌误读为个股信号。",
            params_builder=_benchmark_range_params,
            fields=INDEX_DAILY_FIELDS,
        ),
        DatasetSpec(
            key="market_calendar",
            endpoint="trade_cal",
            purpose="明确可交易日期和前一交易日，纳入停牌与事件窗口约束。",
            params_builder=_calendar_params,
            fields=TRADE_CAL_FIELDS,
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
            key="market_breadth",
            endpoint="daily_info",
            purpose="观察交易所级成交、估值和市场广度，避免只用个股盘口判断风险偏好。",
            params_builder=_market_trade_date_params,
            fields=DAILY_INFO_FIELDS,
        ),
        DatasetSpec(
            key="market_money_flow",
            endpoint="moneyflow_mkt_dc",
            purpose="观察全市场分单资金净流入，识别短线资金环境是否支持执行。",
            params_builder=_market_trade_date_params,
            fields=MARKET_MONEYFLOW_FIELDS,
        ),
        DatasetSpec(
            key="market_margin",
            endpoint="margin",
            purpose="观察交易所级融资融券杠杆，识别拥挤与流动性恶化风险。",
            params_builder=_market_trade_date_params,
            fields=MARKET_MARGIN_FIELDS,
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


def _positive_float(value: str) -> float:
    parsed = float(value)
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
    return (
        RequestContext(
            symbol=args.symbol,
            benchmark=args.benchmark,
            start_date=start_date,
            end_date=end_date,
        ),
        args.start_date is None,
        defaulted_end_date,
    )


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
        "benchmark": context.benchmark,
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
        cached_rows = 0
        normalized_rows = 0
        if args.cache:
            cached_rows, normalized_rows = persist_tushare_collection(
                _dataset_name(args.mode, spec),
                spec.endpoint,
                frame,
                db_path=args.db_path,
            )
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
                "normalized_rows": normalized_rows,
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
        "benchmark": context.benchmark,
        "date_range": {"start_date": context.start_date, "end_date": context.end_date},
        "financial_facts_policy": FINANCIAL_FACTS_POLICY,
        "cache": args.cache,
        "output_dir": str(args.output_dir) if args.output_dir else None,
        "results": results,
        "next_step": "Read original disclosures for any financial or corporate-action fact used in the report.",
    }
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    return 1 if failures and args.strict else 0


def _indicator_settings_from_args(args: argparse.Namespace) -> TechnicalIndicatorSettings:
    settings = TechnicalIndicatorSettings(
        macd_fast=args.macd_fast,
        macd_slow=args.macd_slow,
        macd_signal=args.macd_signal,
        rsi_window=args.rsi_window,
        bollinger_window=args.bollinger_window,
        bollinger_std=args.bollinger_std,
        sma_short=args.sma_short,
        sma_long=args.sma_long,
        volume_window=args.volume_window,
    )
    settings.validate()
    return settings


def _indicator_latest_record(indicators: pd.DataFrame) -> dict[str, Any]:
    history = indicators.reset_index()
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.strftime("%Y-%m-%d")
    return json.loads(history.tail(1).to_json(orient="records", force_ascii=False))[0]


def _write_indicator_history(indicators: pd.DataFrame, output: Path, symbol: str) -> Path:
    if output.suffix.lower() != ".csv":
        raise ValueError("--output must use a .csv extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    history = indicators.reset_index()
    history.insert(1, "ts_code", symbol)
    history.to_csv(output, index=False)
    return output


def _run_indicators(args: argparse.Namespace) -> int:
    settings = _indicator_settings_from_args(args)
    prices, volumes = load_daily_matrices(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=[args.symbol],
    )
    if args.symbol not in prices:
        raise ValueError(f"no forward-adjusted daily price data stored for {args.symbol}")

    close_prices = prices[args.symbol].dropna()
    if close_prices.empty:
        raise ValueError(f"no usable forward-adjusted daily price data stored for {args.symbol}")
    volume_series = volumes[args.symbol].reindex(close_prices.index) if args.symbol in volumes else None
    indicators = calculate_technical_indicators(close_prices, volume_series, settings=settings)
    latest_record = _indicator_latest_record(indicators)
    unavailable_indicators = [
        field
        for field, value in latest_record.items()
        if field not in {"trade_date", "close_qfq", "volume"} and value is None
    ]
    output = _write_indicator_history(indicators, args.output, args.symbol) if args.output else None
    payload = {
        "operation": "indicators",
        "symbol": args.symbol,
        "price_basis": "forward-adjusted close (close_qfq) from local SQLite",
        "requested_date_range": {"start_date": args.start_date, "end_date": args.end_date},
        "latest_trade_date": latest_record["trade_date"],
        "observations": len(indicators),
        "required_observations_for_standard_set": settings.warmup_observations,
        "sufficient_history_for_standard_set": len(indicators) >= settings.warmup_observations,
        "settings": asdict(settings),
        "latest": latest_record,
        "unavailable_latest_indicators": unavailable_indicators,
        "output": str(output) if output else None,
        "interpretation_boundary": (
            "Indicators are reproducible market observations, not automatic buy/sell signals or personalized position advice. "
            "Use them with price, liquidity, event risk, and the main Skill's decision discipline."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser, *, require_end_date: bool) -> None:
    parser.add_argument("mode", type=_mode, help="long, medium, or short")
    parser.add_argument("--symbol", type=_symbol, required=True, help="TuShare ts_code, such as 000001.SZ")
    parser.add_argument(
        "--benchmark",
        type=_symbol,
        default=DEFAULT_BENCHMARK,
        help=f"Index ts_code used for market comparison (default: {DEFAULT_BENCHMARK})",
    )
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
    fetch_parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Store endpoint rows, capabilities, and eligible core-table rows in SQLite (default)",
    )
    fetch_parser.add_argument("--output-dir", type=Path, help="Optional directory for one CSV per dataset")
    fetch_parser.add_argument("--dry-run", action="store_true", help="Print requests without reading a token or calling TuShare")
    fetch_parser.add_argument("--strict", action="store_true", help="Return a nonzero exit status when any endpoint is unavailable")
    fetch_parser.add_argument("--preview-rows", type=_positive_int, default=DEFAULT_PREVIEW_ROWS)

    indicators_parser = subparsers.add_parser(
        "indicators",
        help="Calculate reproducible technical indicators from locally stored forward-adjusted daily data",
    )
    indicators_parser.add_argument("--symbol", type=_symbol, required=True, help="TuShare ts_code, such as 000001.SZ")
    indicators_parser.add_argument("--start-date", type=_date, help="Optional earliest stored trade date to include")
    indicators_parser.add_argument("--end-date", type=_date, required=True, help="YYYYMMDD research as_of date")
    indicators_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    indicators_parser.add_argument("--output", type=Path, help="Optional CSV path for full indicator history")
    indicators_parser.add_argument("--macd-fast", type=_positive_int, default=12)
    indicators_parser.add_argument("--macd-slow", type=_positive_int, default=26)
    indicators_parser.add_argument("--macd-signal", type=_positive_int, default=9)
    indicators_parser.add_argument("--rsi-window", type=_positive_int, default=14)
    indicators_parser.add_argument("--bollinger-window", type=_positive_int, default=20)
    indicators_parser.add_argument("--bollinger-std", type=_positive_float, default=2.0)
    indicators_parser.add_argument("--sma-short", type=_positive_int, default=20)
    indicators_parser.add_argument("--sma-long", type=_positive_int, default=60)
    indicators_parser.add_argument("--volume-window", type=_positive_int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            return _run_plan(args)
        if args.command == "fetch":
            return _run_fetch(args)
        return _run_indicators(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
