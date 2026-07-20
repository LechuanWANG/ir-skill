#!/usr/bin/env python3
"""Fetch mode-specific TuShare research data without verifying financial statements."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_daily_matrices,
    load_daily_price_history,
    load_normalized_endpoint_dates,
    load_research_observations,
    load_research_observation_dates,
    load_trading_calendar,
    persist_tushare_collection,
    write_tushare_capabilities,
)
from project_context import ensure_project_layout, project_paths
from technical_indicators import (
    TechnicalIndicatorSettings,
    calculate_technical_indicators,
    summarize_technical_indicators,
)
from tushare_gateway import request_endpoint
from tushare_sync import create_tushare_client
from tushare_transport import TushareEndpointError, TushareRequestPolicy


DATE_FORMAT = "%Y%m%d"
CACHE_DATE_FORMAT = "%Y-%m-%d"
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
    "TuShare 是结构化财务筛选、披露时间线和横向比较的默认来源。公司年报、半年报、季报等"
    "原始披露，以及交易所/公司公告，仍是报告级收入、利润、现金流、资产负债表和关键财务"
    "口径的最终核验来源；只有需要正式引用、单位/币种/合并范围确认或处理修订冲突时才读取原件。"
)
CACHEABLE_END_OF_DAY_ENDPOINTS = frozenset({"daily", "adj_factor", "daily_basic", "index_daily", "moneyflow"})
CACHEABLE_MARKET_DATE_ENDPOINTS = frozenset({"stk_limit"})
CACHEABLE_CALENDAR_ENDPOINTS = frozenset({"trade_cal"})
MARKET_DATA_AVAILABLE_AFTER = time(hour=16)
MARKET_TIMEZONE = ZoneInfo("Asia/Hong_Kong")


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


@dataclass(frozen=True)
class CacheCoverage:
    expected_dates: tuple[str, ...]
    raw_cached_dates: tuple[str, ...]
    normalized_cached_dates: tuple[str, ...]

    @property
    def cached_dates(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.raw_cached_dates) | set(self.normalized_cached_dates)))

    @property
    def missing_dates(self) -> tuple[str, ...]:
        cached_dates = set(self.cached_dates)
        return tuple(date for date in self.expected_dates if date not in cached_dates)

    @property
    def missing_raw_dates(self) -> tuple[str, ...]:
        raw_cached_dates = set(self.raw_cached_dates)
        return tuple(date for date in self.expected_dates if date not in raw_cached_dates)

    @property
    def is_complete(self) -> bool:
        return not self.missing_dates

    @property
    def has_complete_raw_export(self) -> bool:
        return not self.missing_raw_dates


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


def _market_range_params(context: RequestContext) -> dict[str, str]:
    return {"start_date": context.start_date, "end_date": context.end_date}


def _trade_date_only_params(context: RequestContext) -> dict[str, str]:
    return {"trade_date": context.end_date}


def _symbol_trade_date_params(context: RequestContext) -> dict[str, str]:
    return {"ts_code": context.symbol, "trade_date": context.end_date}


def _symbol_freq_params(context: RequestContext) -> dict[str, str]:
    return {
        "ts_code": context.symbol,
        "start_date": context.start_date,
        "end_date": context.end_date,
        "freq": "1min",
    }


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
        DatasetSpec(
            key="pledge_detail",
            endpoint="pledge_detail",
            purpose="补充质押发生日、质押方和质押数量，识别长期治理与平仓尾部风险。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="质押合同、处置状态和控制权影响以公司公告及定期报告为准。",
        ),
        DatasetSpec(
            key="repurchase",
            endpoint="repurchase",
            purpose="观察回购计划、进度和价格区间，区分已执行资本回报与仅有承诺。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="回购计划与实际完成量以公告原文和交易所披露为准。",
        ),
        DatasetSpec(
            key="holder_trade",
            endpoint="stk_holdertrade",
            purpose="观察重要股东增减持及执行进度，识别长期供给和治理信号。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="股东身份、计划与实际成交以权益变动公告为准。",
        ),
        DatasetSpec(
            key="block_trade",
            endpoint="block_trade",
            purpose="观察大宗交易折溢价和成交规模，作为流动性与股东行为线索。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="name_change",
            endpoint="namechange",
            purpose="记录证券简称、风险警示和上市状态变化，避免长期比较使用错误证券身份。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="float_holders",
            endpoint="top10_floatholders",
            purpose="观察前十大流通股东及集中度变化，补充长期股东结构核验。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="流通股东状态以对应报告期定期报告为准，不推断实时持仓。",
        ),
        DatasetSpec(
            key="new_share",
            endpoint="new_share",
            purpose="观察新股发行、上市和发行规模，识别长期股票池的供给与稀释变化。",
            params_builder=_market_range_params,
            optional=True,
            permission_sensitive=True,
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
        DatasetSpec(
            key="broker_expectation",
            endpoint="report_rc",
            purpose="按需获取券商研报评级、目标价或盈利预测变化，作为预期差线索而非事实来源。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="研报观点和目标价不替代公司披露或独立估值核验。",
        ),
        DatasetSpec(
            key="institutional_research",
            endpoint="stk_surv",
            purpose="观察机构调研日期、参与机构和问题主题，定位可能的中期催化线索。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="调研纪要和公司回答以原始公告或投资者关系记录为准。",
        ),
        DatasetSpec(
            key="industry_moneyflow",
            endpoint="moneyflow_ind_ths",
            purpose="观察行业资金净流入及其变化，区分个股催化与板块轮动。",
            params_builder=_market_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="sector_index",
            endpoint="ths_index",
            purpose="获取同花顺行业/概念指数定义，统一中期板块比较口径。",
            params_builder=_market_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="sector_members",
            endpoint="ths_member",
            purpose="获取板块成分股，核验个股实际行业暴露和催化传导。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="share_float",
            endpoint="share_float",
            purpose="观察催化窗口内的限售解禁和流通股供给。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="解禁数量、股东类型和执行日期以公司公告为准。",
        ),
        DatasetSpec(
            key="repurchase",
            endpoint="repurchase",
            purpose="跟踪回购计划、进度和价格区间，判断资本行为是否进入催化窗口。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="回购计划与完成进度以公司公告为准。",
        ),
        DatasetSpec(
            key="holder_trade",
            endpoint="stk_holdertrade",
            purpose="跟踪重要股东增减持及其对中期供给的影响。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="股东身份、计划和实际成交以权益变动公告为准。",
        ),
        DatasetSpec(
            key="block_trade",
            endpoint="block_trade",
            purpose="观察大宗交易规模和折溢价，辅助判断筹码供给与流动性。",
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
        DatasetSpec(
            key="limit_step",
            endpoint="limit_step",
            purpose="观察连板高度、首次封板和开板结构，识别短线强弱与隔夜退出约束。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="limit_concept",
            endpoint="limit_cpt_list",
            purpose="观察涨停板块汇总和连板梯队，形成题材热度背景。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="kpl_board",
            endpoint="kpl_list",
            purpose="观察开盘啦涨停池和强势股标签，作为盘面事件线索。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="kpl_concept",
            endpoint="kpl_concept",
            purpose="观察开盘啦概念热度和涨停家数，区分单股异动与题材扩散。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="kpl_stock_rank",
            endpoint="kpl_stock_rank",
            purpose="观察开盘啦强势股排名和短线标签，辅助事件归因。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="sector_index",
            endpoint="ths_index",
            purpose="获取同花顺行业/概念指数，判断题材是否有板块级确认。",
            params_builder=_market_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="concept_daily",
            endpoint="ths_daily",
            purpose="观察同花顺概念指数短期收益与成交，核验题材是否得到板块确认。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="concept_members",
            endpoint="ths_member",
            purpose="映射概念指数到成分股，避免把题材标签误当作公司实际暴露。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="dc_index",
            endpoint="dc_index",
            purpose="获取东方财富行业/概念板块指数，交叉验证题材广度。",
            params_builder=_market_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="dc_members",
            endpoint="dc_member",
            purpose="获取东方财富板块成分股，核验个股题材归属。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="dc_daily",
            endpoint="dc_daily",
            purpose="观察东方财富板块日线涨跌和成交，验证短线题材扩散。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="tdx_index",
            endpoint="tdx_index",
            purpose="获取通达信板块索引作为第三方题材口径交叉检查。",
            params_builder=_market_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="tdx_members",
            endpoint="tdx_member",
            purpose="获取通达信板块成分，识别不同板块口径下的暴露差异。",
            params_builder=_symbol_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="tdx_daily",
            endpoint="tdx_daily",
            purpose="观察通达信板块日线表现，辅助短线热板确认。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="moneyflow_ths",
            endpoint="moneyflow_ths",
            purpose="补充同花顺口径个股资金流，和通用资金流交叉验证，不单独生成信号。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="moneyflow_dc",
            endpoint="moneyflow_dc",
            purpose="补充东方财富口径资金流与超大单结构，检查数据源差异。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="chip_distribution",
            endpoint="cyq_chips",
            purpose="观察筹码价格分布和集中度，辅助判断突破后的获利盘与套牢盘压力。",
            params_builder=_symbol_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="chip_performance",
            endpoint="cyq_perf",
            purpose="观察不同持有成本区间的获利比例，辅助识别短线拥挤。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="factor_daily",
            endpoint="stk_factor_pro",
            purpose="按需获取扩展技术和量价因子，先核验可得性再用于候选排序。",
            params_builder=_range_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="factor_basic",
            endpoint="stk_factor",
            purpose="获取基础技术因子，作为扩展因子接口不可用时的轻量回退。",
            params_builder=_symbol_trade_date_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="hot_board",
            endpoint="hot_list",
            purpose="观察个股热度排名和热板扩散，识别注意力拥挤而非基本面改善。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="hot_board_detail",
            endpoint="hot_detail",
            purpose="查看热度榜单的成分和变化，辅助短线事件归因。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="hot_money",
            endpoint="hm_detail",
            purpose="观察游资席位交易明细，区分短线资金接力与单日噪音。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="hot_money_list",
            endpoint="hm_list",
            purpose="获取游资席位列表和活跃度，辅助识别短线资金风格。",
            params_builder=_trade_date_only_params,
            optional=True,
            permission_sensitive=True,
        ),
        DatasetSpec(
            key="minute_price",
            endpoint="stk_mins",
            purpose="在具备分钟权限时补充盘中执行窗口；不能替代日线技术、流动性和事件核验。",
            params_builder=_symbol_freq_params,
            optional=True,
            permission_sensitive=True,
            source_boundary="分钟/实时数据权限与独立购买的集合竞价、A股日线 RT 权限分开核验。",
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


def _calendar_dates(context: RequestContext) -> tuple[str, ...]:
    return tuple(pd.date_range(context.start_date, context.end_date, freq="D").strftime(CACHE_DATE_FORMAT))


def _cached_open_dates(context: RequestContext, db_path: Path) -> tuple[str, ...] | None:
    """Return covered SSE trading dates, or ``None`` if the local calendar has a gap."""
    calendar = load_trading_calendar(
        start_date=context.start_date,
        end_date=context.end_date,
        db_path=db_path,
    )
    expected_calendar_dates = set(_calendar_dates(context))
    if calendar.empty:
        return None

    cached_calendar_dates = {
        pd.Timestamp(value).strftime(CACHE_DATE_FORMAT)
        for value in calendar["cal_date"].dropna().tolist()
    }
    if not expected_calendar_dates.issubset(cached_calendar_dates):
        return None

    latest_completed_date = datetime.strptime(context.end_date, DATE_FORMAT).strftime(CACHE_DATE_FORMAT)
    now = datetime.now(MARKET_TIMEZONE)
    if context.end_date == now.strftime(DATE_FORMAT) and now.time() < MARKET_DATA_AVAILABLE_AFTER:
        latest_completed_date = (now - timedelta(days=1)).strftime(CACHE_DATE_FORMAT)

    normalized = calendar.copy()
    normalized["cal_date"] = pd.to_datetime(normalized["cal_date"], errors="coerce")
    normalized["is_open"] = pd.to_numeric(normalized["is_open"], errors="coerce").fillna(0)
    open_dates = normalized.loc[
        normalized["cal_date"].notna()
        & (normalized["cal_date"].dt.strftime(CACHE_DATE_FORMAT) <= latest_completed_date)
        & (normalized["is_open"] == 1),
        "cal_date",
    ]
    return tuple(open_dates.dt.strftime(CACHE_DATE_FORMAT).tolist())


def _cache_symbol(spec: DatasetSpec, context: RequestContext) -> list[str] | None:
    if spec.endpoint == "trade_cal":
        return None
    if spec.endpoint == "index_daily":
        return [context.benchmark]
    return [context.symbol]


def _cache_coverage(mode: str, spec: DatasetSpec, context: RequestContext, db_path: Path) -> CacheCoverage | None:
    if spec.endpoint in CACHEABLE_CALENDAR_ENDPOINTS:
        expected_dates = _calendar_dates(context)
    elif spec.endpoint in CACHEABLE_END_OF_DAY_ENDPOINTS:
        expected_dates = _cached_open_dates(context, db_path)
        if expected_dates is None:
            return None
    elif spec.endpoint in CACHEABLE_MARKET_DATE_ENDPOINTS:
        if _cached_open_dates(context, db_path) is None:
            return None
        # Price-limit data is usable during the current session, unlike EOD daily data.
        calendar = load_trading_calendar(
            start_date=context.start_date,
            end_date=context.end_date,
            db_path=db_path,
        )
        expected_dates = tuple(
            pd.to_datetime(calendar.loc[pd.to_numeric(calendar["is_open"], errors="coerce").fillna(0) == 1, "cal_date"])
            .dt.strftime(CACHE_DATE_FORMAT)
            .tolist()
        )
    else:
        return None

    symbols = _cache_symbol(spec, context)
    raw_cached_dates = load_research_observation_dates(
        _dataset_name(mode, spec),
        db_path=db_path,
        symbols=symbols,
    )
    normalized_cached_dates = load_normalized_endpoint_dates(
        spec.endpoint,
        db_path=db_path,
        symbols=symbols,
    )
    return CacheCoverage(
        expected_dates=tuple(expected_dates),
        raw_cached_dates=tuple(sorted(set(expected_dates) & raw_cached_dates)),
        normalized_cached_dates=tuple(sorted(set(expected_dates) & normalized_cached_dates)),
    )


def _cache_coverage_payload(coverage: CacheCoverage | None) -> dict[str, Any] | None:
    if coverage is None:
        return None
    return {
        "status": "complete" if coverage.is_complete else "partial",
        "expected_date_count": len(coverage.expected_dates),
        "cached_date_count": len(coverage.cached_dates),
        "raw_cached_date_count": len(coverage.raw_cached_dates),
        "normalized_cached_date_count": len(coverage.normalized_cached_dates),
        "missing_date_count": len(coverage.missing_dates),
        "missing_raw_date_count": len(coverage.missing_raw_dates),
        "first_missing_date": coverage.missing_dates[0] if coverage.missing_dates else None,
        "last_missing_date": coverage.missing_dates[-1] if coverage.missing_dates else None,
        "latest_cached_date": coverage.cached_dates[-1] if coverage.cached_dates else None,
    }


def _context_for_missing_dates(context: RequestContext, coverage: CacheCoverage | None) -> RequestContext:
    if coverage is None or not coverage.missing_dates:
        return context
    return replace(
        context,
        start_date=pd.Timestamp(coverage.missing_dates[0]).strftime(DATE_FORMAT),
        end_date=pd.Timestamp(coverage.missing_dates[-1]).strftime(DATE_FORMAT),
    )


def _context_for_missing_raw_dates(context: RequestContext, coverage: CacheCoverage) -> RequestContext:
    """Narrow an export-only backfill to dates absent from the raw payload cache."""
    return replace(
        context,
        start_date=pd.Timestamp(coverage.missing_raw_dates[0]).strftime(DATE_FORMAT),
        end_date=pd.Timestamp(coverage.missing_raw_dates[-1]).strftime(DATE_FORMAT),
    )


def _cached_collection_frame(
    mode: str,
    spec: DatasetSpec,
    context: RequestContext,
    coverage: CacheCoverage,
    db_path: Path,
) -> pd.DataFrame:
    """Rehydrate cached payload fields only when a caller requests a CSV export."""
    if not coverage.expected_dates:
        return pd.DataFrame()
    cached = load_research_observations(
        db_path=db_path,
        dataset=_dataset_name(mode, spec),
        symbols=_cache_symbol(spec, context),
        start_date=coverage.expected_dates[0],
        end_date=coverage.expected_dates[-1],
        limit=max(10_000, len(coverage.expected_dates) * 2),
    )
    if cached.empty:
        return cached

    metadata_columns = {
        "dataset",
        "row_hash",
        "business_key",
        "ts_code",
        "event_date",
        "available_at",
        "source",
        "retrieved_at",
        "first_seen_at",
        "last_seen_at",
        "revision",
        "is_current",
    }
    payload_columns = [column for column in cached.columns if column not in metadata_columns]
    payload = cached.loc[:, payload_columns].copy()
    payload = payload.rename(
        columns={column: column.removeprefix("payload_") for column in payload.columns if column.startswith("payload_")}
    )
    for date_column in ("trade_date", "cal_date"):
        if date_column in payload.columns:
            return payload.sort_values(date_column, kind="mergesort", na_position="last").reset_index(drop=True)
    return payload


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


AS_OF_FIELDS = ("ann_date", "surv_date", "trade_date", "float_date", "release_date", "imp_date", "holder_trade_date")


def _filter_available_as_of(frame: pd.DataFrame, as_of: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply a conservative availability boundary to mode data responses."""
    if frame.empty:
        return frame, {"status": "empty", "field": None, "excluded_rows": 0}
    field = next((candidate for candidate in AS_OF_FIELDS if candidate in frame.columns), None)
    if field is None:
        return frame, {"status": "historically_unverified", "field": None, "excluded_rows": 0}
    parsed = pd.to_datetime(frame[field], errors="coerce", format="mixed")
    cutoff = pd.Timestamp(as_of)
    valid = parsed.notna()
    keep = valid & (parsed <= cutoff)
    filtered = frame.loc[keep].copy()
    invalid_rows = int((~valid).sum())
    return filtered, {
        "status": "verified" if invalid_rows == 0 else "partial",
        "field": field,
        "excluded_rows": int((~keep).sum()),
        "invalid_or_missing_date_rows": invalid_rows,
    }


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
        plan["refresh"] = args.refresh
        plan["output_dir"] = str(args.output_dir) if args.output_dir else None
        print(json.dumps(plan, ensure_ascii=False, default=str, indent=2))
        return 0

    request_policy = TushareRequestPolicy(
        min_interval_seconds=args.min_request_interval,
        max_attempts=args.max_attempts,
    )
    results: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []
    failures = 0
    network_requests = 0
    client: Any | None = None
    project_layout_ready = False
    cache_reuse_enabled = args.cache and not args.refresh
    for spec in selected_specs:
        coverage = _cache_coverage(args.mode, spec, context, args.db_path) if cache_reuse_enabled else None
        export_needs_raw_backfill = bool(args.output_dir and coverage is not None and not coverage.has_complete_raw_export)
        if coverage is not None and coverage.is_complete and not export_needs_raw_backfill:
            cached_frame = (
                _cached_collection_frame(args.mode, spec, context, coverage, args.db_path)
                if args.output_dir
                else pd.DataFrame()
            )
            output = _write_csv(cached_frame, args.output_dir, args.mode, spec, context) if args.output_dir else None
            results.append(
                {
                    "key": spec.key,
                    "endpoint": spec.endpoint,
                    "status": "cached",
                    "network_requested": False,
                    "cached_rows": len(coverage.cached_dates),
                    "normalized_rows": 0,
                    "rows": len(cached_frame) if args.output_dir else None,
                    "columns": list(cached_frame.columns) if args.output_dir else [],
                    "output": str(output) if output else None,
                    "permission_sensitive": spec.permission_sensitive,
                    "source_boundary": spec.source_boundary,
                    "cache_coverage": _cache_coverage_payload(coverage),
                    "preview": _preview_records(cached_frame, args.preview_rows) if args.output_dir else [],
                }
            )
            continue

        request_context = (
            _context_for_missing_raw_dates(context, coverage)
            if export_needs_raw_backfill and coverage is not None
            else _context_for_missing_dates(context, coverage)
        )
        request = _request_for_spec(spec, request_context)
        if client is None:
            # Only create project storage and read the token if a request is genuinely needed.
            if args.cache and not project_layout_ready:
                ensure_project_layout(project_paths())
                project_layout_ready = True
            client = create_tushare_client(env_path=args.env_file)
        try:
            network_requests += 1
            frame = request_endpoint(client, spec.endpoint, request["params"], policy=request_policy)
        except TushareEndpointError as exc:
            failures += 1
            error = str(exc)
            capabilities.append(_capability_record(spec, "unavailable", error=exc.category))
            results.append(
                {
                    "key": spec.key,
                    "endpoint": spec.endpoint,
                    "status": "unavailable",
                    "error": error,
                    "error_type": exc.category,
                    "attempts": exc.attempts,
                    "retryable": exc.retryable,
                    "permission_sensitive": spec.permission_sensitive,
                    "network_requested": True,
                    "cache_coverage": _cache_coverage_payload(coverage),
                }
            )
            continue
        except ValueError as exc:
            failures += 1
            error = str(exc)
            capabilities.append(_capability_record(spec, "unavailable", error="invalid_endpoint"))
            results.append(
                {
                    "key": spec.key,
                    "endpoint": spec.endpoint,
                    "status": "unavailable",
                    "error": error,
                    "error_type": "invalid_endpoint",
                    "permission_sensitive": spec.permission_sensitive,
                    "network_requested": True,
                    "cache_coverage": _cache_coverage_payload(coverage),
                }
            )
            continue

        raw_rows = len(frame)
        frame, as_of_verification = _filter_available_as_of(frame, context.end_date)
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
        output_frame = (
            _cached_collection_frame(args.mode, spec, context, coverage, args.db_path)
            if args.output_dir and args.cache and coverage is not None
            else frame
        )
        output = _write_csv(output_frame, args.output_dir, args.mode, spec, context) if args.output_dir else None
        capabilities.append(_capability_record(spec, status, rows=len(frame)))
        results.append(
            {
                "key": spec.key,
                "endpoint": spec.endpoint,
                "status": status,
                "network_requested": True,
                "raw_rows": raw_rows,
                "rows": len(output_frame),
                "columns": list(output_frame.columns),
                "cached_rows": cached_rows,
                "normalized_rows": normalized_rows,
                "output": str(output) if output else None,
                "permission_sensitive": spec.permission_sensitive,
                "source_boundary": spec.source_boundary,
                "preview": _preview_records(output_frame, args.preview_rows),
                "as_of_verification": as_of_verification,
                "cache_coverage": _cache_coverage_payload(coverage),
                "request_date_range": {
                    "start_date": request_context.start_date,
                    "end_date": request_context.end_date,
                },
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
        "refresh": args.refresh,
        "network_requests": network_requests,
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
    price_history = load_daily_price_history(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=[args.symbol],
    )
    price_history = price_history.set_index("trade_date") if not price_history.empty else price_history
    high_prices = price_history["high_qfq"].reindex(close_prices.index) if "high_qfq" in price_history else None
    low_prices = price_history["low_qfq"].reindex(close_prices.index) if "low_qfq" in price_history else None
    indicators = calculate_technical_indicators(
        close_prices,
        volume_series,
        high_prices=high_prices,
        low_prices=low_prices,
        settings=settings,
    )
    latest_record = _indicator_latest_record(indicators)
    technical_snapshot = summarize_technical_indicators(indicators, settings=settings)
    unavailable_indicators = [
        field
        for field, value in latest_record.items()
        if field not in {"trade_date", "close_qfq", "high_qfq", "low_qfq", "volume"} and value is None
    ]
    output = _write_indicator_history(indicators, args.output, args.symbol) if args.output else None
    payload = {
        "operation": "indicators",
        "symbol": args.symbol,
        "price_basis": (
            "forward-adjusted close (close_qfq), with intraday high/low when available, from local SQLite"
        ),
        "requested_date_range": {"start_date": args.start_date, "end_date": args.end_date},
        "latest_trade_date": latest_record["trade_date"],
        "observations": len(indicators),
        "required_observations_for_standard_set": settings.warmup_observations,
        "sufficient_history_for_standard_set": len(indicators) >= settings.warmup_observations,
        "settings": asdict(settings),
        "latest": latest_record,
        "technical_snapshot": technical_snapshot,
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
    parser.add_argument("--env-file", type=Path, help="Optional dotenv path used when no process token is set")
    parser.add_argument("--min-request-interval", type=_positive_float, default=0.6, help="Minimum seconds between TuShare calls")
    parser.add_argument("--max-attempts", type=_positive_int, default=3, help="Attempts for rate-limit and transient-network failures")
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
    fetch_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore reusable SQLite coverage and force every selected endpoint to refresh",
    )
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory for one CSV per dataset; raw payload gaps are backfilled only when needed for export",
    )
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
