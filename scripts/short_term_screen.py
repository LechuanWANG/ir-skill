#!/usr/bin/env python3
"""Point-in-time A-share screening, driver diagnostics, replay, and risk sizing."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import timedelta
from math import floor, isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_daily_screening_panel,
    load_index_daily_history,
    load_known_corporate_events,
    load_daily_price_history,
    load_short_screen_run,
    list_short_recommendation_runs,
    load_sector_memberships,
    write_short_screen_run,
)
from short_term_decision import (
    STRATEGY_CONTRACTS,
    build_evidence_bundle,
    compact_confirmation,
    confirm_evidence,
    enrich_screen_readiness,
    load_json_object,
    review_recommendation,
    technical_pattern_code,
    technical_pattern_label,
)
from technical_indicators import calculate_technical_indicators, summarize_technical_indicators
from project_context import project_paths
from research_watchlist import upsert_watch_item, watchlist_path


DEFAULT_BENCHMARK = "000300.SH"
DEFAULT_MIN_MEDIAN_AMOUNT_CNY = 50_000_000.0
DEFAULT_MIN_LIST_DAYS = 120


@dataclass(frozen=True)
class ScreenProfile:
    name: str
    momentum_window: int
    trend_window: int
    history_sessions: int
    forward_horizons: tuple[int, ...]


PROFILES = {
    "trade": ScreenProfile("trade", 20, 60, 100, (5, 10, 20)),
    "swing": ScreenProfile("swing", 60, 120, 180, (20, 40, 60)),
}


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y%m%d")


def _profile(value: str) -> ScreenProfile:
    try:
        return PROFILES[value]
    except KeyError as exc:
        raise argparse.ArgumentTypeError(f"unsupported profile: {value}") from exc


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


def _fraction(value: str) -> float:
    parsed = float(value)
    if not 0 < parsed < 1:
        raise argparse.ArgumentTypeError("value must be between zero and one")
    return parsed


def _json_value(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> list[dict[str, object]]:
    if frame.empty:
        return []
    selected = frame.loc[:, [column for column in (columns or frame.columns) if column in frame.columns]]
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in selected.to_dict(orient="records")
    ]


def _mapping_readiness(candidate: Mapping[str, object]) -> Mapping[str, object]:
    value = candidate.get("readiness")
    return value if isinstance(value, Mapping) else {}


def _bounded(value: object, *, lower: float = 0.0, upper: float = 1.0) -> float:
    number = _number(value)
    if number is None:
        return lower
    return min(upper, max(lower, number))


def _latest_percentile(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return _number(values.rank(pct=True, method="average").iloc[-1])


def _chase_risk_score(row: Mapping[str, object]) -> float:
    cross_extension = _number(row.get("extension_percentile")) or 0.0
    own_extension = _number(row.get("own_extension_percentile_120d")) or 0.0
    extension_tail = max(cross_extension, own_extension)
    extension_component = _bounded((extension_tail - 0.8) / 0.2)
    atr_extension = max(0.0, _number(row.get("price_extension_atr")) or 0.0)
    atr_component = _bounded((atr_extension - 1.5) / 1.5)
    acceleration = _number(row.get("return_acceleration_5v20")) or 0.0
    acceleration_percentile = _number(row.get("return_acceleration_percentile")) or 0.0
    acceleration_component = (
        _bounded((acceleration_percentile - 0.8) / 0.2)
        if acceleration > 0
        else 0.0
    )
    volume_component = _bounded(((_number(row.get("volume_ratio_20d")) or 0.0) - 1.5) / 1.5)
    gap_component = _bounded(max(0.0, _number(row.get("open_gap_pct")) or 0.0) / 0.08)
    streak_component = _bounded(((_number(row.get("positive_sessions_3d")) or 0.0) - 1.0) / 2.0)
    return round(
        (25.0 * extension_component)
        + (25.0 * atr_component)
        + (15.0 * acceleration_component)
        + (15.0 * volume_component)
        + (10.0 * gap_component)
        + (10.0 * streak_component),
        2,
    )


def _buyability_score(row: Mapping[str, object]) -> float:
    trend_score = 20.0 if row.get("trend_state") == "supportive" else 10.0
    participation_score = (
        15.0
        if row.get("participation_state") == "supportive"
        else 8.0
        if row.get("participation_state") == "mixed"
        else 0.0
    )
    chase_score = _number(row.get("chase_risk_score")) or 0.0
    return round(
        (30.0 * _bounded(row.get("momentum_percentile")))
        + trend_score
        + participation_score
        + (20.0 * (1.0 - _bounded(chase_score / 100.0)))
        + (15.0 * _bounded(row.get("liquidity_percentile"))),
        2,
    )


def _series_return(series: pd.Series, sessions: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= sessions:
        return None
    return _number((values.iloc[-1] / values.iloc[-1 - sessions]) - 1.0)


def _has_price_limit(value: object, direction: str) -> bool:
    tokens = [item.strip().upper() for item in str(value or "").split(",") if item.strip()]
    if direction == "up":
        return any(item in {"U", "UP", "LIMIT_UP"} or "涨" in item for item in tokens)
    return any(item in {"D", "DOWN", "LIMIT_DOWN"} or "跌" in item for item in tokens)


def _sample_signal_dates(dates: pd.DatetimeIndex, max_signals: int) -> pd.DatetimeIndex:
    """Cap replay work while retaining coverage of the full requested period."""
    if len(dates) <= max_signals:
        return dates
    if max_signals == 1:
        return dates[-1:]
    positions = [round(index * (len(dates) - 1) / (max_signals - 1)) for index in range(max_signals)]
    return dates.take(positions)


def _setup_trigger(
    candidate: Mapping[str, object],
    signal_history: pd.DataFrame,
    entry_row: Mapping[str, object],
    *,
    strategy_contract: str,
) -> dict[str, object]:
    """Replay a small, frozen trigger contract instead of treating selection as entry."""
    contract = STRATEGY_CONTRACTS[strategy_contract]
    allowed_setups = set(contract["allowed_setup_types"])
    setup = technical_pattern_code(
        candidate.get("technical_pattern") or candidate.get("setup_hint")
    ) or str(contract["default_setup_type"])
    if setup not in allowed_setups:
        setup = str(contract["default_setup_type"])
    signal_close = _number(candidate.get("close_qfq"))
    signal_high = None
    if not signal_history.empty and "high_qfq" in signal_history:
        signal_high = _number(signal_history.iloc[-1].get("high_qfq"))
    entry_open = _number(entry_row.get("open_qfq"))
    entry_high = _number(entry_row.get("high_qfq"))
    entry_low = _number(entry_row.get("low_qfq"))
    entry_close = _number(entry_row.get("close_qfq"))
    if signal_close is None or entry_close is None:
        return {"status": "unknown", "reason": "missing adjusted trigger prices", "setup_type": setup}
    if setup == "momentum_breakout":
        trigger_level = max(signal_close * 1.002, signal_high or signal_close)
    elif setup == "event_continuation":
        trigger_level = signal_close * 1.002
    else:
        primary_ma = _number(candidate.get("sma_20")) or _number(candidate.get("sma_60"))
        trigger_level = primary_ma if primary_ma is not None and primary_ma < signal_close else signal_close * 0.995
    if setup in {"momentum_breakout", "event_continuation"}:
        triggered = (entry_open is not None and entry_open >= trigger_level) or (
            entry_high is not None and entry_high >= trigger_level
        ) or entry_close >= trigger_level
    else:
        triggered = (
            entry_low is not None
            and entry_low <= trigger_level
            and entry_close >= trigger_level
            and str(candidate.get("trend_state") or "") == "supportive"
        )
    if not triggered:
        return {
            "status": "not_triggered",
            "reason": "next-session price did not satisfy the frozen setup trigger",
            "setup_type": setup,
            "trigger_level_qfq": trigger_level,
        }
    if setup == "trend_pullback":
        trigger_price = trigger_level
        trigger_basis = "next_session_low_touch_reclaim_qfq"
    else:
        trigger_price = entry_open if entry_open is not None and entry_open >= trigger_level else trigger_level
        trigger_basis = "next_session_open_qfq" if trigger_price == entry_open else "next_session_intraday_high_qfq"
    return {
        "status": "triggered",
        "reason": "next-session price satisfied the frozen setup trigger",
        "setup_type": setup,
        "trigger_level_qfq": trigger_level,
        "trigger_price_qfq": trigger_price,
        "trigger_basis": trigger_basis,
        "execution_assumption": (
            "daily_bar_trigger; open gaps use observed open, intraday crosses assume a stop order at the frozen level; "
            "slippage is represented only by the configured transaction-cost deduction"
        ),
    }


def _return_distribution(series: pd.Series) -> dict[str, object]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {}
    wins = values.loc[values > 0]
    losses = values.loc[values < 0]
    average_win = _number(wins.mean())
    average_loss = _number(losses.mean())
    standard_error = _number(values.std(ddof=1) / (len(values) ** 0.5)) if len(values) > 1 else None
    mean_return = _number(values.mean())
    maximum_loss_streak = 0
    current_loss_streak = 0
    for value in values:
        current_loss_streak = current_loss_streak + 1 if value < 0 else 0
        maximum_loss_streak = max(maximum_loss_streak, current_loss_streak)
    gross_profit = _number(wins.sum()) or 0.0
    gross_loss = abs(_number(losses.sum()) or 0.0)
    return {
        "expected_return_after_cost": mean_return,
        "average_win": average_win,
        "average_loss": average_loss,
        "payoff_ratio": (
            average_win / abs(average_loss)
            if average_win is not None and average_loss not in {None, 0}
            else None
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "return_p05": _number(values.quantile(0.05)),
        "return_p95": _number(values.quantile(0.95)),
        "maximum_loss_streak": maximum_loss_streak,
        "mean_return_95ci_normal": (
            [mean_return - (1.96 * standard_error), mean_return + (1.96 * standard_error)]
            if mean_return is not None and standard_error is not None
            else None
        ),
    }


def _benchmark_metrics(history: pd.DataFrame, effective_date: pd.Timestamp, windows: Sequence[int]) -> dict[str, Any]:
    if history.empty:
        return {"status": "missing", "effective_trade_date": None, "returns": {str(item): None for item in windows}}
    working = history.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce")
    working = working.loc[working["trade_date"] <= effective_date].sort_values("trade_date")
    if working.empty:
        return {"status": "missing", "effective_trade_date": None, "returns": {str(item): None for item in windows}}
    close = pd.to_numeric(working["close"], errors="coerce")
    benchmark_date = working.iloc[-1]["trade_date"]
    payload = {
        "status": "available" if benchmark_date == effective_date else "misaligned",
        "effective_trade_date": benchmark_date.date().isoformat(),
        "returns": {str(item): _series_return(close, item) for item in windows},
    }
    return payload


def build_data_quality_report(
    panel: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    *,
    as_of: str,
    min_history_sessions: int = 60,
    require_historical_lifecycle: bool = False,
) -> dict[str, Any]:
    """Report whether the local panel is fit for screening, replay, and execution."""
    requested_date = pd.Timestamp(as_of).normalize()
    if panel.empty:
        return {
            "operation": "short_screen_data_quality",
            "status": "blocked",
            "requested_as_of": requested_date.date().isoformat(),
            "effective_trade_date": None,
            "coverage": {},
            "decision_blockers": ["empty_screening_panel"],
            "boundary": "No screening conclusion is allowed without a non-empty local panel.",
        }

    working = panel.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce")
    working = working.loc[working["trade_date"].notna() & (working["trade_date"] <= requested_date)]
    if working.empty:
        return {
            "operation": "short_screen_data_quality",
            "status": "blocked",
            "requested_as_of": requested_date.date().isoformat(),
            "effective_trade_date": None,
            "coverage": {},
            "decision_blockers": ["no_price_at_or_before_as_of"],
            "boundary": "No screening conclusion is allowed without a price row at or before as_of.",
        }
    for column in (
        "open_qfq", "high_qfq", "low_qfq", "amount", "close_raw", "adj_factor",
        "circ_mv", "list_date",
        "list_status",
    ):
        if column not in working.columns:
            working[column] = None

    effective_date = working["trade_date"].max()
    latest = working.loc[working["trade_date"] == effective_date].drop_duplicates("ts_code")
    prices = working.pivot(index="trade_date", columns="ts_code", values="close_qfq").sort_index()
    recent = prices.tail(20)
    amount = working.pivot(index="trade_date", columns="ts_code", values="amount").reindex_like(prices)
    recent_price_cells = int(recent.notna().sum().sum())
    recent_amount_cells = int(amount.tail(20).notna().sum().sum())
    latest_count = max(len(latest), 1)
    benchmark = _benchmark_metrics(benchmark_history, effective_date, (20,))
    business_day_lag = len(pd.bdate_range(effective_date + timedelta(days=1), requested_date))
    history_sessions = int(prices.notna().sum().median()) if not prices.empty else 0
    coverage = {
        "latest_cross_section_rows": int(len(latest)),
        "symbols_with_history": int(prices.notna().any().sum()),
        "median_history_sessions": history_sessions,
        "adjusted_open": _number(latest["open_qfq"].notna().mean()),
        "adjusted_high_low": _number(
            (latest["high_qfq"].notna() & latest["low_qfq"].notna()).mean()
        ),
        "stored_amount_20d": _number(recent_amount_cells / max(recent_price_cells, 1)),
        "raw_close_and_adjustment_factor": _number(
            (latest["close_raw"].notna() & latest["adj_factor"].notna()).mean()
        ),
        "daily_basic": _number(latest["circ_mv"].notna().mean()),
        "stock_metadata": _number(latest["list_date"].notna().mean()),
        "stock_lifecycle": _number(latest["list_status"].notna().mean()),
        "benchmark_20d": bool(
            benchmark["status"] == "available" and benchmark["returns"].get("20") is not None
        ),
    }
    blockers: list[str] = []
    if history_sessions < min_history_sessions:
        blockers.append("insufficient_history_for_standard_screen")
    if business_day_lag > 2:
        blockers.append("stale_price_data")
    if not coverage["benchmark_20d"]:
        blockers.append("benchmark_missing_or_misaligned")
    if (_number(coverage["stored_amount_20d"]) or 0) < 0.95:
        blockers.append("stored_amount_incomplete_proxy_used")
    if (_number(coverage["adjusted_open"]) or 0) < 0.95:
        blockers.append("adjusted_open_incomplete")
    if (_number(coverage["raw_close_and_adjustment_factor"]) or 0) < 0.95:
        blockers.append("raw_adjustment_contract_incomplete")
    if require_historical_lifecycle and (_number(coverage["stock_lifecycle"]) or 0) < 0.95:
        blockers.append("historical_stock_lifecycle_incomplete")
    status = "ready" if not blockers else "blocked_for_execution"
    if blockers and blockers == ["raw_adjustment_contract_incomplete"]:
        status = "usable_with_caveats"
    return {
        "operation": "short_screen_data_quality",
        "status": status,
        "requested_as_of": requested_date.date().isoformat(),
        "effective_trade_date": effective_date.date().isoformat(),
        "as_of_business_day_lag": business_day_lag,
        "coverage": coverage,
        "benchmark": benchmark,
        "decision_blockers": blockers,
        "boundary": "ready means the local data supports the declared screen; it does not validate a trading edge.",
    }


def _exclusion_reasons(row: pd.Series, *, profile: ScreenProfile, effective_date: pd.Timestamp,
                       min_list_days: int, min_median_amount_cny: float) -> list[str]:
    reasons: list[str] = []
    name = str(row.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        reasons.append("special_treatment_or_delisting")
    list_date = pd.to_datetime(row.get("list_date"), errors="coerce")
    if pd.isna(list_date):
        reasons.append("missing_list_date")
    elif (effective_date - list_date).days < min_list_days:
        reasons.append("insufficient_listing_age")
    delist_date = pd.to_datetime(row.get("delist_date"), errors="coerce")
    if pd.notna(delist_date) and effective_date >= delist_date:
        reasons.append("delisted_before_effective_date")
    if (_number(row.get("latest_volume")) or 0.0) <= 0:
        reasons.append("not_tradable_on_effective_date")
    if _has_price_limit(row.get("limit_types"), "up"):
        reasons.append("entry_blocked_by_limit_up")
    if (_number(row.get("observations")) or 0.0) < profile.trend_window + 1:
        reasons.append("insufficient_price_history")
    median_amount = _number(row.get("median_amount_20d_cny"))
    if median_amount is None:
        reasons.append("missing_liquidity")
    elif median_amount < min_median_amount_cny:
        reasons.append("insufficient_liquidity")
    if _number(row.get(f"return_{profile.momentum_window}d")) is None:
        reasons.append("missing_primary_return")
    return reasons


def _industry_diagnostics(metrics: pd.DataFrame, memberships: pd.DataFrame | None) -> dict[str, Any]:
    if metrics.empty:
        return {"status": "missing", "signal": "unknown", "coverage_ratio": 0.0, "sectors": []}

    membership_coverage = 0.0
    ambiguity = 0
    joined = pd.DataFrame()
    if memberships is not None and not memberships.empty:
        mapping = memberships.copy()
        if "sector_type" in mapping:
            sector_type = mapping["sector_type"].fillna("").astype(str).str.lower()
            industry_rows = mapping.loc[sector_type.str.contains("industry") | sector_type.eq("i")]
            if not industry_rows.empty:
                mapping = industry_rows
        mapping = mapping.loc[mapping["stock_code"].notna() & mapping["sector_code"].notna()].copy()
        ambiguity = int(mapping.groupby("stock_code")["sector_code"].nunique().gt(1).sum())
        mapping = mapping.sort_values(["stock_code", "sector_code"]).drop_duplicates("stock_code")
        joined = metrics.merge(
            mapping[["stock_code", "sector_code", "sector_name"]],
            left_on="ts_code",
            right_on="stock_code",
            how="inner",
        )
        membership_coverage = joined["ts_code"].nunique() / max(metrics["ts_code"].nunique(), 1)

    source = "provider_membership"
    ambiguity_ratio = ambiguity / max(metrics["ts_code"].nunique(), 1)
    if membership_coverage < 0.5 or ambiguity_ratio > 0.1:
        direct = metrics.copy()
        industry_values = (
            direct["industry"]
            if "industry" in direct.columns
            else pd.Series("", index=direct.index, dtype=object)
        )
        direct["industry"] = industry_values.fillna("").astype(str).str.strip()
        direct = direct.loc[direct["industry"].ne("")].copy()
        direct_coverage = direct["ts_code"].nunique() / max(metrics["ts_code"].nunique(), 1)
        if direct_coverage >= 0.5:
            joined = direct.assign(
                stock_code=direct["ts_code"],
                sector_code=direct["industry"],
                sector_name=direct["industry"],
            )
            source = "stock_basic_current_snapshot"
        else:
            return {
                "status": "insufficient_coverage",
                "signal": "unknown",
                "coverage_ratio": max(membership_coverage, direct_coverage),
                "membership_coverage_ratio": membership_coverage,
                "stock_basic_coverage_ratio": direct_coverage,
                "membership_ambiguity_count": ambiguity,
                "sectors": [],
                "boundary": "Do not infer the absence of industry differentiation from incomplete coverage.",
            }

    primary = "primary_return"
    joined = joined.loc[pd.to_numeric(joined[primary], errors="coerce").notna()].copy()
    coverage = joined["ts_code"].nunique() / max(metrics["ts_code"].nunique(), 1)
    if joined.empty:
        return {"status": "missing", "signal": "unknown", "coverage_ratio": coverage, "sectors": []}
    grand_mean = joined[primary].mean()
    total_ss = ((joined[primary] - grand_mean) ** 2).sum()
    grouped = joined.groupby(["sector_code", "sector_name"], dropna=False)
    sector_rows: list[dict[str, object]] = []
    between_ss = 0.0
    for (sector_code, sector_name), group in grouped:
        if len(group) < 3:
            continue
        sector_median = float(group[primary].median())
        sector_mean = float(group[primary].mean())
        between_ss += len(group) * ((sector_mean - grand_mean) ** 2)
        positive = group[primary].clip(lower=0)
        top_contribution = float(positive.max() / positive.sum()) if positive.sum() > 0 else None
        sign = 1 if sector_median > 0 else -1 if sector_median < 0 else 0
        same_sign = float(((group[primary] * sign) > 0).mean()) if sign else None
        sector_rows.append(
            {
                "sector_code": sector_code,
                "sector_name": sector_name,
                "member_count": int(len(group)),
                "median_primary_return": sector_median,
                "advancer_share_1d": float((group["return_1d"] > 0).mean()),
                "positive_primary_share": float((group[primary] > 0).mean()),
                "same_sign_share": same_sign,
                "top_positive_contribution": top_contribution,
            }
        )
    sectors = pd.DataFrame(sector_rows)
    between_share = float(between_ss / total_ss) if total_ss > 0 else 0.0

    top_count = max(1, int(len(joined) * 0.1))
    top = joined.nlargest(top_count, primary)
    top_sector_share = float(top["sector_code"].value_counts(normalize=True).iloc[0]) if not top.empty else None
    leading_alignment = None
    if not sectors.empty:
        leading_alignment = _number(sectors.nlargest(min(3, len(sectors)), "median_primary_return")["same_sign_share"].mean())
    checks = [
        coverage >= 0.5,
        between_share >= 0.15,
        top_sector_share is not None and top_sector_share >= 0.3,
        leading_alignment is not None and leading_alignment >= 0.6,
    ]
    passed = sum(checks)
    signal = "significant" if passed >= 3 else "mixed" if passed == 2 else "not_significant"
    if not sectors.empty:
        sectors = sectors.sort_values("median_primary_return", ascending=False).head(10)
    return {
        "status": "available",
        "signal": signal,
        "classification_source": source,
        "coverage_ratio": coverage,
        "membership_coverage_ratio": membership_coverage,
        "membership_ambiguity_count": ambiguity,
        "between_industry_variance_share": between_share,
        "top_decile_max_industry_share": top_sector_share,
        "leading_industry_same_sign_share": leading_alignment,
        "sectors": _records(sectors),
        "boundary": (
            "Current stock_basic industry is a snapshot, not point-in-time history. "
            "Descriptive thresholds identify participation, not a buy signal."
            if source == "stock_basic_current_snapshot"
            else "Descriptive thresholds identify unusually coherent industry participation; they are not a buy signal."
        ),
    }


def _style_diagnostics(metrics: pd.DataFrame) -> dict[str, Any]:
    working = metrics.loc[
        pd.to_numeric(metrics.get("circ_mv"), errors="coerce").notna()
        & pd.to_numeric(metrics.get("primary_return"), errors="coerce").notna()
    ].copy()
    if len(working) < 30 or working["circ_mv"].nunique() < 3:
        return {"status": "missing", "signal": "unknown"}
    working["size_bucket"] = pd.qcut(
        working["circ_mv"].rank(method="first"),
        3,
        labels=["small", "mid", "large"],
    )
    grand_mean = working["primary_return"].mean()
    total_ss = ((working["primary_return"] - grand_mean) ** 2).sum()
    medians = working.groupby("size_bucket", observed=True)["primary_return"].median()
    means = working.groupby("size_bucket", observed=True)["primary_return"].agg(["mean", "count"])
    between_ss = ((means["mean"] - grand_mean) ** 2 * means["count"]).sum()
    between_share = float(between_ss / total_ss) if total_ss > 0 else 0.0
    spread = float(medians.max() - medians.min())
    return {
        "status": "available",
        "signal": "significant" if between_share >= 0.12 else "not_significant",
        "between_size_variance_share": between_share,
        "size_median_returns": {str(key): _json_value(value) for key, value in medians.items()},
        "size_return_spread": spread,
    }


def build_screen(
    panel: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    *,
    as_of: str,
    profile: ScreenProfile,
    benchmark: str = DEFAULT_BENCHMARK,
    limit: int = 20,
    min_median_amount_cny: float = DEFAULT_MIN_MEDIAN_AMOUNT_CNY,
    min_list_days: int = DEFAULT_MIN_LIST_DAYS,
    momentum_percentile: float = 0.7,
    memberships: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
) -> dict[str, Any]:
    if panel.empty:
        raise ValueError("screening panel is empty")
    working = panel.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce")
    requested_date = pd.Timestamp(as_of).normalize()
    working = working.loc[working["trade_date"].notna() & (working["trade_date"] <= requested_date)]
    if working.empty:
        raise ValueError("screening panel has no rows at or before as_of")
    effective_date = working["trade_date"].max()
    for column in (
        "open_qfq", "high_qfq", "low_qfq", "amount", "close_raw", "adj_factor",
        "circ_mv", "list_date", "list_status", "name", "industry", "market",
        "turnover_rate", "limit_types",
    ):
        if column not in working.columns:
            working[column] = None
    quality_report = build_data_quality_report(
        working,
        benchmark_history,
        as_of=as_of,
        min_history_sessions=profile.trend_window,
    )

    prices = working.pivot(index="trade_date", columns="ts_code", values="close_qfq").sort_index()
    opens = working.pivot(index="trade_date", columns="ts_code", values="open_qfq").sort_index()
    highs = working.pivot(index="trade_date", columns="ts_code", values="high_qfq").sort_index()
    lows = working.pivot(index="trade_date", columns="ts_code", values="low_qfq").sort_index()
    raw_prices = working.pivot(index="trade_date", columns="ts_code", values="close_raw").sort_index()
    volumes = working.pivot(index="trade_date", columns="ts_code", values="volume").sort_index()
    amounts = working.pivot(index="trade_date", columns="ts_code", values="amount").sort_index()
    liquidity_prices = raw_prices.where(raw_prices.notna(), prices)
    amount_proxy = liquidity_prices * volumes * 100.0
    amount_cny = amounts * 1000.0
    amount_cny = amount_cny.where(amount_cny.notna(), amount_proxy)
    returns_1d = prices.pct_change(fill_method=None)
    previous_close = prices.shift(1)
    high_low_range = highs - lows
    high_previous_range = (highs - previous_close).abs()
    low_previous_range = (lows - previous_close).abs()
    true_range = high_low_range.where(high_low_range.ge(high_previous_range), high_previous_range)
    true_range = true_range.where(true_range.ge(low_previous_range), low_previous_range)
    atr_20d = true_range.rolling(20).mean()
    latest = working.loc[working["trade_date"] == effective_date].drop_duplicates("ts_code").set_index("ts_code")

    metrics = latest.copy()
    metrics["latest_volume"] = volumes.loc[effective_date]
    metrics["observations"] = prices.notna().sum()
    metrics["return_1d"] = returns_1d.loc[effective_date]
    windows = sorted({5, 20, 60, profile.momentum_window, profile.trend_window})
    for window in windows:
        metrics[f"return_{window}d"] = prices.pct_change(window, fill_method=None).loc[effective_date]
    metrics["primary_return"] = metrics[f"return_{profile.momentum_window}d"]
    primary_ma_history = prices.rolling(profile.momentum_window).mean()
    metrics[f"sma_{profile.momentum_window}"] = primary_ma_history.loc[effective_date]
    metrics[f"sma_{profile.trend_window}"] = prices.rolling(profile.trend_window).mean().loc[effective_date]
    metrics["price_vs_primary_ma"] = (
        metrics["close_qfq"] / metrics[f"sma_{profile.momentum_window}"] - 1.0
    )
    metrics["volatility_20d_annualized"] = returns_1d.rolling(20).std(ddof=0).loc[effective_date] * (252**0.5)
    metrics["atr_20d_pct"] = atr_20d.loc[effective_date] / metrics["close_qfq"]
    metrics["price_extension_atr"] = (
        metrics["close_qfq"] - metrics[f"sma_{profile.momentum_window}"]
    ) / atr_20d.loc[effective_date]
    extension_history = (prices / primary_ma_history) - 1.0
    metrics["own_extension_percentile_120d"] = extension_history.loc[:effective_date].tail(120).apply(
        _latest_percentile,
        axis=0,
    )
    metrics["return_acceleration_5v20"] = (
        metrics["return_5d"] - (metrics["return_20d"] * 0.25)
    )
    metrics["open_gap_pct"] = (opens / previous_close - 1.0).loc[effective_date]
    metrics["positive_sessions_3d"] = returns_1d.gt(0).rolling(3).sum().loc[effective_date]
    rolling_high_20d = highs.rolling(20).max().loc[effective_date]
    rolling_low_20d = lows.rolling(20).min().loc[effective_date]
    metrics["close_location_20d"] = (
        (metrics["close_qfq"] - rolling_low_20d) / (rolling_high_20d - rolling_low_20d)
    ).where(rolling_high_20d.gt(rolling_low_20d))
    metrics["drawdown_from_60d_high"] = prices.loc[:effective_date].tail(60).apply(
        lambda series: (series.iloc[-1] / series.max()) - 1.0 if series.notna().any() else None
    )
    metrics["volume_ratio_20d"] = volumes.loc[effective_date] / volumes.rolling(20).mean().loc[effective_date]
    up_volume = volumes.where(returns_1d > 0, 0.0)
    metrics["up_volume_share_20d"] = (
        up_volume.rolling(20).sum().loc[effective_date] / volumes.rolling(20).sum().loc[effective_date]
    )
    metrics["median_amount_20d_cny"] = amount_cny.tail(20).median()
    stored_amount_count = amounts.tail(20).notna().sum()
    price_count = prices.tail(20).notna().sum()
    metrics["liquidity_amount_basis"] = pd.Series("mixed", index=metrics.index)
    metrics.loc[stored_amount_count.eq(0), "liquidity_amount_basis"] = "price_volume_proxy"
    metrics.loc[stored_amount_count.ge(price_count) & price_count.gt(0), "liquidity_amount_basis"] = "stored_amount"

    benchmark_data = _benchmark_metrics(benchmark_history, effective_date, windows)
    for window in windows:
        benchmark_return = benchmark_data["returns"].get(str(window))
        metrics[f"benchmark_return_{window}d"] = benchmark_return
        metrics[f"relative_return_{window}d"] = (
            metrics[f"return_{window}d"] - benchmark_return if benchmark_return is not None else None
        )
    primary_relative = f"relative_return_{profile.momentum_window}d"
    primary_rank_field = (
        primary_relative
        if benchmark_data["status"] == "available"
        and benchmark_data["returns"].get(str(profile.momentum_window)) is not None
        else "primary_return"
    )

    metrics = metrics.reset_index()
    metrics["exclusion_reasons"] = metrics.apply(
        _exclusion_reasons,
        axis=1,
        profile=profile,
        effective_date=effective_date,
        min_list_days=min_list_days,
        min_median_amount_cny=min_median_amount_cny,
    )
    metrics["eligible"] = metrics["exclusion_reasons"].map(lambda item: not item)
    eligible = metrics.loc[metrics["eligible"]].copy()

    if not eligible.empty:
        eligible["momentum_percentile"] = eligible[primary_rank_field].rank(pct=True, method="average")
        eligible["liquidity_percentile"] = eligible["median_amount_20d_cny"].rank(pct=True, method="average")
        eligible["participation_percentile"] = eligible["volume_ratio_20d"].rank(pct=True, method="average")
        eligible["volatility_percentile"] = eligible["volatility_20d_annualized"].rank(pct=True, method="average")
        eligible["extension_percentile"] = eligible["price_vs_primary_ma"].rank(pct=True, method="average")
        eligible["return_acceleration_percentile"] = eligible["return_acceleration_5v20"].rank(
            pct=True,
            method="average",
        )
        eligible["trend_state"] = eligible.apply(
            lambda row: "supportive"
            if row["close_qfq"] > row[f"sma_{profile.momentum_window}"] > row[f"sma_{profile.trend_window}"]
            else "adverse"
            if row["close_qfq"] < row[f"sma_{profile.momentum_window}"] < row[f"sma_{profile.trend_window}"]
            else "mixed",
            axis=1,
        )
        eligible["participation_state"] = eligible.apply(
            lambda row: "supportive"
            if (_number(row["volume_ratio_20d"]) or 0) >= 1.0 and (_number(row["up_volume_share_20d"]) or 0) >= 0.5
            else "adverse"
            if (_number(row["volume_ratio_20d"]) or 0) < 0.8 and (_number(row["up_volume_share_20d"]) or 0) < 0.5
            else "mixed",
            axis=1,
        )
        eligible["extension_state"] = eligible.apply(
            lambda row: "stretched"
            if (
                max(
                    _number(row["extension_percentile"]) or 0,
                    _number(row["own_extension_percentile_120d"]) or 0,
                ) >= 0.9
                and (_number(row["price_vs_primary_ma"]) or 0) > 0
            )
            else "not_stretched",
            axis=1,
        )
        eligible["chase_risk_score"] = eligible.apply(_chase_risk_score, axis=1)
        eligible["buyability_score"] = eligible.apply(_buyability_score, axis=1)
    else:
        for column in (
            "momentum_percentile", "liquidity_percentile", "participation_percentile",
            "volatility_percentile", "extension_percentile", "trend_state",
            "return_acceleration_percentile", "participation_state", "extension_state",
            "chase_risk_score", "buyability_score",
        ):
            eligible[column] = None

    event_summary = pd.DataFrame(columns=["ts_code", "known_event_count", "next_known_event_date"])
    if events is not None and not events.empty:
        event_working = events.copy()
        event_working["event_date"] = pd.to_datetime(event_working["event_date"], errors="coerce")
        event_summary = event_working.groupby("ts_code").agg(
            known_event_count=("event_date", "count"),
            next_known_event_date=("event_date", lambda values: values.loc[values >= effective_date].min()),
        ).reset_index()
        eligible = eligible.merge(event_summary, on="ts_code", how="left")
    eligible["known_event_count"] = eligible.get("known_event_count", pd.Series(index=eligible.index, dtype=float)).fillna(0).astype(int)

    candidate_pool = eligible.loc[
        (eligible["momentum_percentile"] >= momentum_percentile)
        & eligible["trend_state"].isin(["supportive", "mixed"])
    ].copy()
    candidate_pool = candidate_pool.sort_values(
        ["buyability_score", "momentum_percentile", "participation_percentile", "liquidity_percentile"],
        ascending=False,
    )
    selected = candidate_pool.head(limit)

    eligible_diagnostics = eligible[["ts_code", "industry", "return_1d", "primary_return", "circ_mv"]].copy()
    industry = _industry_diagnostics(eligible_diagnostics, memberships)
    style = _style_diagnostics(eligible_diagnostics)
    advancer_share = _number((eligible["return_1d"] > 0).mean()) if not eligible.empty else None
    median_return_1d = _number(eligible["return_1d"].median()) if not eligible.empty else None
    benchmark_primary = benchmark_data["returns"].get(str(profile.momentum_window))
    if advancer_share is None:
        market_state = "unknown"
    elif advancer_share >= 0.55 and (benchmark_primary is None or benchmark_primary > 0):
        market_state = "supportive"
    elif advancer_share <= 0.35 and (benchmark_primary is None or benchmark_primary < 0):
        market_state = "hostile"
    else:
        market_state = "mixed"
    if industry["signal"] == "significant":
        dominant_driver = "industry_theme"
    elif style.get("signal") == "significant":
        dominant_driver = "style_factor"
    elif market_state in {"supportive", "hostile"}:
        dominant_driver = "market_beta"
    elif industry["signal"] == "not_significant":
        dominant_driver = "idiosyncratic_or_mixed"
    else:
        dominant_driver = "mixed_or_unknown"

    if not selected.empty:
        selected = selected.copy()
        selected["primary_relative_strength"] = selected[primary_rank_field]
        selected["primary_relative_strength_field"] = primary_rank_field
        selected["technical_pattern"] = selected.apply(
            lambda row: technical_pattern_label("trend_pullback")
            if row["trend_state"] == "supportive" and row["extension_state"] == "stretched"
            else technical_pattern_label("momentum_breakout")
            if row["trend_state"] == "supportive" and row["participation_state"] == "supportive"
            else technical_pattern_label("trend_pullback")
            if row["trend_state"] == "supportive"
            else "待确认",
            axis=1,
        )
        selected["candidate_state"] = selected.apply(
            lambda row: "data_quality_review"
            if quality_report["status"] == "blocked_for_execution"
            else "waiting_price"
            if row["extension_state"] == "stretched"
            else "waiting_confirmation"
            if row["participation_state"] == "adverse"
            else "high_risk_review"
            if (_number(row["volatility_percentile"]) or 0) >= 0.9
            else "hostile_market_review"
            if market_state == "hostile"
            else "evidence_ready",
            axis=1,
        )

    exclusion_counts: dict[str, int] = {}
    for reasons in metrics.loc[~metrics["eligible"], "exclusion_reasons"]:
        for reason in reasons:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
    candidate_columns = [
        "ts_code", "name", "industry", "market", "close_qfq", "close_raw", "adj_factor",
        primary_rank_field, "primary_relative_strength", "primary_relative_strength_field",
        "momentum_percentile", "trend_state", "participation_state", "extension_state",
        "technical_pattern", "price_vs_primary_ma", "price_extension_atr",
        "own_extension_percentile_120d", "atr_20d_pct", "return_acceleration_5v20",
        "return_acceleration_percentile", "open_gap_pct", "positive_sessions_3d",
        "close_location_20d", "volume_ratio_20d", "up_volume_share_20d",
        "chase_risk_score", "buyability_score",
        f"sma_{profile.momentum_window}", f"sma_{profile.trend_window}",
        "volatility_20d_annualized", "volatility_percentile", "drawdown_from_60d_high",
        "median_amount_20d_cny",
        "turnover_rate", "liquidity_amount_basis", "known_event_count", "next_known_event_date",
        "candidate_state",
    ]
    recent_price_cells = int(prices.tail(20).notna().sum().sum())
    recent_amount_cells = int(amounts.tail(20).notna().sum().sum())
    latest_count = max(len(latest), 1)
    stored_amount_coverage = recent_amount_cells / max(recent_price_cells, 1)
    raw_adjustment_coverage = _number(
        (latest["close_raw"].notna() & latest["adj_factor"].notna()).sum() / latest_count
    )
    business_day_lag = len(pd.bdate_range(effective_date + timedelta(days=1), requested_date))
    if selected.empty:
        screen_status = "no_edge_found"
    elif (selected["candidate_state"] == "evidence_ready").any():
        screen_status = "research_candidates_available"
    else:
        screen_status = "candidates_require_waiting_or_review"
    payload = {
        "operation": "short_screen",
        "requested_as_of": requested_date.date().isoformat(),
        "effective_trade_date": effective_date.date().isoformat(),
        "as_of_business_day_lag": business_day_lag,
        "profile": profile.name,
        "benchmark": benchmark,
        "benchmark_data": benchmark_data,
        "universe": {
            "observed": int(len(metrics)),
            "eligible": int(len(eligible)),
            "candidate_pool": int(len(candidate_pool)),
            "selected": int(len(selected)),
            "exclusions": exclusion_counts,
            "minimum_listing_days": min_list_days,
            "minimum_median_amount_20d_cny": min_median_amount_cny,
        },
        "market_regime": {
            "state": market_state,
            "advancer_share_1d": advancer_share,
            "median_return_1d": median_return_1d,
        },
        "data_quality": {
            "status": quality_report["status"],
            "decision_blockers": quality_report["decision_blockers"],
            "latest_cross_section_rows": int(len(latest)),
            "adjusted_open_coverage": _number(latest["open_qfq"].notna().sum() / latest_count),
            "adjusted_high_low_coverage": _number(
                (latest["high_qfq"].notna() & latest["low_qfq"].notna()).sum() / latest_count
            ),
            "stored_amount_coverage_20d": _number(stored_amount_coverage),
            "raw_adjustment_contract_coverage": raw_adjustment_coverage,
            "daily_basic_coverage": _number(latest["circ_mv"].notna().sum() / latest_count),
            "stock_metadata_coverage": _number(latest["list_date"].notna().sum() / latest_count),
            "stock_lifecycle_coverage": _number(latest["list_status"].notna().sum() / latest_count),
            "liquidity_fallback": "close_raw * volume * 100; close_qfq only for legacy rows",
        },
        "driver_diagnostics": {
            "dominant_driver": dominant_driver,
            "industry": industry,
            "style": style,
        },
        "ranking_basis": {
            "primary": "buyability_score",
            "minimum_percentile": momentum_percentile,
            "strength_reference": primary_rank_field,
            "tie_breakers": ["momentum_percentile", "participation_percentile", "liquidity_percentile"],
            "composite_score": True,
            "components": {
                "relative_strength": 30,
                "trend_structure": 20,
                "participation": 15,
                "price_quality_after_chase_risk": 20,
                "liquidity": 15,
            },
        },
        "technical_pattern_contract": {
            "patterns": ["动量突破", "趋势回踩", "事件延续"],
            "analysis_price_basis": "forward_adjusted_qfq",
            "execution_price_basis": "raw_unadjusted_required",
            "selection_is_not_entry": True,
        },
        "screen_status": screen_status,
        "cash_comparison_required": True,
        "candidates": _records(selected, candidate_columns),
        "data_gaps": [
            item
            for item, missing in (
                ("benchmark_relative_return", benchmark_data["status"] != "available"),
                ("industry_membership", industry["status"] != "available"),
                ("known_events", events is None or events.empty),
                ("price_data_not_at_requested_as_of", business_day_lag > 0),
                ("turnover_amount_partly_proxied", stored_amount_coverage < 0.95),
                ("adjusted_open_history", latest["open_qfq"].notna().mean() < 0.95),
                (
                    "intraday_high_low_history",
                    (latest["high_qfq"].notna() & latest["low_qfq"].notna()).mean() < 0.95,
                ),
                (
                    "raw_price_and_adjustment_factor_history",
                    raw_adjustment_coverage is None or raw_adjustment_coverage < 0.95,
                ),
                *[
                    (f"quality:{item}", True)
                    for item in quality_report["decision_blockers"]
                    if item not in {"stale_price_data"}
                ],
            )
            if missing
        ],
        "boundary": "Candidates are research leads. Execution still requires event verification, priced-in analysis, invalidation, and cash comparison.",
    }
    return enrich_screen_readiness(payload)


def evaluate_screen_history(
    panel: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    profile: ScreenProfile,
    benchmark: str = DEFAULT_BENCHMARK,
    limit: int = 10,
    rebalance_sessions: int = 5,
    cost_bps: float = 20.0,
    max_signals: int = 60,
    min_median_amount_cny: float = DEFAULT_MIN_MEDIAN_AMOUNT_CNY,
    min_list_days: int = DEFAULT_MIN_LIST_DAYS,
    momentum_percentile: float = 0.7,
    out_of_sample_start: str | None = None,
    include_observations: bool = False,
    strategy_contract: str = "momentum_trade",
) -> dict[str, Any]:
    working = panel.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce")
    dates = pd.DatetimeIndex(sorted(working["trade_date"].dropna().unique()))
    requested = dates[(dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))]
    oos_date = pd.Timestamp(out_of_sample_start) if out_of_sample_start else None
    if oos_date is not None and not (pd.Timestamp(start_date) <= oos_date <= pd.Timestamp(end_date)):
        raise ValueError("out_of_sample_start must fall within the requested backtest range")
    signal_dates = _sample_signal_dates(requested[::rebalance_sessions], max_signals)
    date_positions = {date: position for position, date in enumerate(dates)}
    by_symbol = {symbol: frame.set_index("trade_date").sort_index() for symbol, frame in working.groupby("ts_code")}
    benchmark_frame = benchmark_history.copy()
    benchmark_frame["trade_date"] = pd.to_datetime(benchmark_frame["trade_date"], errors="coerce")
    benchmark_frame = benchmark_frame.set_index("trade_date").sort_index()
    observations: list[dict[str, object]] = []
    selected_total = 0
    entry_skips_untradable = 0
    entry_skips_limit_up = 0
    pattern_not_triggered = 0
    pattern_triggered = 0
    grade_selected = {grade: 0 for grade in ("A", "B", "C")}
    grade_triggered = {grade: 0 for grade in ("A", "B", "C")}
    grade_not_triggered = {grade: 0 for grade in ("A", "B", "C")}
    unresolved_exits = 0
    delayed_exits = 0
    limit_down_delayed_exits = 0
    maximum_exit_delay = 0
    quality_blocked_signal_dates = 0
    quality_report = build_data_quality_report(
        working,
        benchmark_history,
        as_of=end_date,
        min_history_sessions=profile.trend_window,
        require_historical_lifecycle=True,
    )

    for signal_date in signal_dates:
        sample = "out_of_sample" if oos_date is not None and signal_date >= oos_date else "development"
        if oos_date is None:
            sample = "all"
        history = working.loc[working["trade_date"] <= signal_date]
        benchmark_to_signal = benchmark_history.loc[
            pd.to_datetime(benchmark_history["trade_date"], errors="coerce") <= signal_date
        ] if not benchmark_history.empty else benchmark_history
        screen = build_screen(
            history,
            benchmark_to_signal,
            as_of=signal_date.strftime("%Y%m%d"),
            profile=profile,
            benchmark=benchmark,
            limit=limit,
            min_median_amount_cny=min_median_amount_cny,
            min_list_days=min_list_days,
            momentum_percentile=momentum_percentile,
        )
        if screen["data_quality"]["status"] == "blocked_for_execution":
            quality_blocked_signal_dates += 1
            continue
        for candidate in screen["candidates"]:
            grade = str(candidate.get("candidate_grade") or "C")
            if grade in grade_selected:
                grade_selected[grade] += 1
        replay_candidates = [
            candidate for candidate in screen["candidates"]
            if candidate.get("candidate_grade") in {"A", "B"}
        ]
        selected_total += len(replay_candidates)
        signal_position = date_positions[signal_date]
        if signal_position + 1 >= len(dates):
            continue
        entry_date = dates[signal_position + 1]
        for candidate in replay_candidates:
            candidate_grade = str(candidate.get("candidate_grade") or "C")
            symbol = str(candidate["ts_code"])
            history_by_symbol = by_symbol.get(symbol)
            if history_by_symbol is None or entry_date not in history_by_symbol.index:
                entry_skips_untradable += 1
                continue
            entry_row = history_by_symbol.loc[entry_date]
            if isinstance(entry_row, pd.DataFrame):
                entry_row = entry_row.iloc[-1]
            if (_number(entry_row.get("volume")) or 0) <= 0:
                entry_skips_untradable += 1
                continue
            if _has_price_limit(entry_row.get("limit_types"), "up"):
                entry_skips_limit_up += 1
                continue
            signal_history = history_by_symbol.loc[history_by_symbol.index <= signal_date]
            trigger = _setup_trigger(
                candidate,
                signal_history,
                entry_row,
                strategy_contract=strategy_contract,
            )
            if trigger["status"] != "triggered":
                pattern_not_triggered += 1
                grade_not_triggered[candidate_grade] += 1
                continue
            pattern_triggered += 1
            grade_triggered[candidate_grade] += 1
            entry_price = _number(trigger.get("trigger_price_qfq"))
            if entry_price is None or entry_price <= 0:
                continue
            entry_basis = str(trigger.get("trigger_basis") or "next_session_close_qfq_fallback")
            raw_entry_reference = _number(entry_row.get("open_raw")) or _number(entry_row.get("close_raw"))
            recent_low = _number(pd.to_numeric(signal_history.tail(10)["low_qfq"], errors="coerce").min())
            primary_ma = _number(candidate.get("sma_20")) or _number(candidate.get("sma_60"))
            if str(trigger.get("setup_type")) == "trend_pullback":
                invalidation_price = recent_low
            else:
                supports = [value for value in (recent_low, primary_ma) if value is not None and value < entry_price]
                invalidation_price = max(supports) if supports else entry_price * 0.97
            if invalidation_price is None or invalidation_price >= entry_price:
                invalidation_price = entry_price * 0.97
            for horizon in profile.forward_horizons:
                exit_position = signal_position + 1 + horizon
                if exit_position >= len(dates):
                    unresolved_exits += 1
                    continue
                target_exit_date = dates[exit_position]
                stop_window = history_by_symbol.loc[
                    (history_by_symbol.index > entry_date)
                    & (history_by_symbol.index <= target_exit_date)
                ]
                stop_lows = pd.to_numeric(stop_window.get("low_qfq"), errors="coerce")
                stop_hits = stop_window.loc[stop_lows.le(invalidation_price)] if not stop_window.empty else stop_window
                desired_exit_date = stop_hits.index[0] if not stop_hits.empty else target_exit_date
                exit_reason = "price_invalidation" if not stop_hits.empty else "time_horizon"
                future_rows = history_by_symbol.loc[history_by_symbol.index >= desired_exit_date].copy()
                if future_rows.empty:
                    unresolved_exits += 1
                    continue
                tradable_exit = (
                    pd.to_numeric(future_rows["close_qfq"], errors="coerce").notna()
                    & pd.to_numeric(future_rows["volume"], errors="coerce").fillna(0).gt(0)
                    & ~future_rows["limit_types"].map(lambda value: _has_price_limit(value, "down"))
                )
                future_rows = future_rows.loc[tradable_exit]
                if future_rows.empty:
                    unresolved_exits += 1
                    continue
                exit_date = future_rows.index[0]
                desired_exit_position = date_positions.get(desired_exit_date, exit_position)
                exit_delay = max(0, date_positions.get(exit_date, desired_exit_position) - desired_exit_position)
                if exit_delay:
                    delayed_exits += 1
                    maximum_exit_delay = max(maximum_exit_delay, exit_delay)
                    if desired_exit_date in history_by_symbol.index:
                        target_row = history_by_symbol.loc[desired_exit_date]
                        if isinstance(target_row, pd.DataFrame):
                            target_row = target_row.iloc[-1]
                        if _has_price_limit(target_row.get("limit_types"), "down"):
                            limit_down_delayed_exits += 1
                exit_row = future_rows.iloc[0]
                if isinstance(exit_row, pd.DataFrame):
                    exit_row = exit_row.iloc[-1]
                if exit_reason == "price_invalidation" and exit_date == desired_exit_date:
                    stop_open = _number(exit_row.get("open_qfq"))
                    exit_price = min(stop_open, invalidation_price) if stop_open is not None else invalidation_price
                else:
                    exit_price = _number(exit_row.get("close_qfq"))
                if exit_price is None:
                    continue
                raw_exit_reference = _number(exit_row.get("close_raw"))
                path = history_by_symbol.loc[entry_date:exit_date]
                path_low = pd.to_numeric(path["low_qfq"], errors="coerce").min()
                path_high = pd.to_numeric(path["high_qfq"], errors="coerce").max()
                gross_return = (exit_price / entry_price) - 1.0
                benchmark_return = None
                if entry_date in benchmark_frame.index and exit_date in benchmark_frame.index:
                    benchmark_entry_row = benchmark_frame.loc[entry_date]
                    benchmark_exit_row = benchmark_frame.loc[exit_date]
                    if isinstance(benchmark_entry_row, pd.DataFrame):
                        benchmark_entry_row = benchmark_entry_row.iloc[-1]
                    if isinstance(benchmark_exit_row, pd.DataFrame):
                        benchmark_exit_row = benchmark_exit_row.iloc[-1]
                    benchmark_entry = _number(benchmark_entry_row.get("open")) or _number(benchmark_entry_row.get("close"))
                    benchmark_exit = _number(benchmark_exit_row.get("close"))
                    if benchmark_entry and benchmark_exit:
                        benchmark_return = (benchmark_exit / benchmark_entry) - 1.0
                net_return = gross_return - (cost_bps / 10_000.0)
                observations.append(
                    {
                        "signal_date": signal_date,
                        "sample": sample,
                        "entry_date": entry_date,
                        "target_exit_date": target_exit_date,
                        "exit_date": exit_date,
                        "exit_delay_sessions": exit_delay,
                        "symbol": symbol,
                        "horizon": horizon,
                        "candidate_grade": candidate_grade,
                        "technical_pattern": technical_pattern_label(trigger.get("setup_type")),
                        "chase_risk_score": candidate.get("chase_risk_score"),
                        "buyability_score": candidate.get("buyability_score"),
                        "trigger_level_qfq": trigger.get("trigger_level_qfq"),
                        "execution_assumption": trigger.get("execution_assumption"),
                        "invalidation_price_qfq": invalidation_price,
                        "exit_reason": exit_reason,
                        "entry_basis": entry_basis,
                        "analysis_price_basis": "forward_adjusted_qfq",
                        "execution_price_basis": "raw_unadjusted_reference",
                        "raw_entry_reference": raw_entry_reference,
                        "raw_exit_reference": raw_exit_reference,
                        "net_return": net_return,
                        "benchmark_return": benchmark_return,
                        "excess_return": net_return - benchmark_return if benchmark_return is not None else None,
                        "mae": (path_low / entry_price) - 1.0 if pd.notna(path_low) else None,
                        "mfe": (path_high / entry_price) - 1.0 if pd.notna(path_high) else None,
                    }
                )

    outcomes = pd.DataFrame(observations)
    summaries: list[dict[str, object]] = []
    if not outcomes.empty:
        for (sample, horizon), group in outcomes.groupby(["sample", "horizon"]):
            summaries.append(
                {
                    "sample": str(sample),
                    "horizon_sessions": int(horizon),
                    "observations": int(len(group)),
                    "mean_net_return": _number(group["net_return"].mean()),
                    "median_net_return": _number(group["net_return"].median()),
                    "hit_rate": _number((group["net_return"] > 0).mean()),
                    "mean_excess_return": _number(group["excess_return"].mean()),
                    "mean_mae": _number(group["mae"].mean()),
                    "mean_mfe": _number(group["mfe"].mean()),
                    "worst_return": _number(group["net_return"].min()),
                    "distribution": _return_distribution(group["net_return"]),
                }
            )
    grade_summaries: list[dict[str, object]] = []
    if not outcomes.empty:
        for (sample, grade, horizon), group in outcomes.groupby(
            ["sample", "candidate_grade", "horizon"]
        ):
            grade_summaries.append(
                {
                    "sample": str(sample),
                    "candidate_grade": str(grade),
                    "horizon_sessions": int(horizon),
                    "observations": int(len(group)),
                    "mean_net_return": _number(group["net_return"].mean()),
                    "hit_rate": _number((group["net_return"] > 0).mean()),
                    "mean_excess_return": _number(group["excess_return"].mean()),
                    "worst_return": _number(group["net_return"].min()),
                    "distribution": _return_distribution(group["net_return"]),
                }
            )
    basket_summaries: list[dict[str, object]] = []
    if not outcomes.empty:
        baskets = outcomes.groupby(["sample", "signal_date", "horizon"], as_index=False).agg(
            basket_net_return=("net_return", "mean"),
            basket_excess_return=("excess_return", "mean"),
            positions=("symbol", "nunique"),
        )
        for (sample, horizon), group in baskets.groupby(["sample", "horizon"]):
            basket_summaries.append(
                {
                    "sample": str(sample),
                    "horizon_sessions": int(horizon),
                    "signal_baskets": int(len(group)),
                    "mean_positions": _number(group["positions"].mean()),
                    "mean_basket_net_return": _number(group["basket_net_return"].mean()),
                    "median_basket_net_return": _number(group["basket_net_return"].median()),
                    "basket_hit_rate": _number((group["basket_net_return"] > 0).mean()),
                    "mean_basket_excess_return": _number(group["basket_excess_return"].mean()),
                    "worst_basket_return": _number(group["basket_net_return"].min()),
                    "distribution": _return_distribution(group["basket_net_return"]),
                }
            )
    fallback_count = int((outcomes.get("entry_basis") == "next_session_close_qfq_fallback").sum()) if not outcomes.empty else 0
    mae_coverage = _number(outcomes["mae"].notna().mean()) if not outcomes.empty else None
    mfe_coverage = _number(outcomes["mfe"].notna().mean()) if not outcomes.empty else None
    basket_counts = (
        baskets.groupby("sample")["signal_date"].nunique().astype(int).to_dict()
        if not outcomes.empty else {}
    )
    required_samples = ["development", "out_of_sample"] if oos_date is not None else ["all"]
    sample_warnings: list[str] = []
    if quality_report["status"] != "ready" or quality_blocked_signal_dates:
        sample_warnings.append("data_quality_not_ready_for_all_signal_dates")
    for sample in required_samples:
        count = int(basket_counts.get(sample, 0))
        if count == 0:
            sample_warnings.append(f"{sample}_sample_missing")
        elif count < 20:
            sample_warnings.append(f"{sample}_sample_below_20_signal_dates")
    if unresolved_exits:
        sample_warnings.append("forward_outcomes_not_fully_matured")
    inference_status = (
        "blocked_by_data_quality"
        if quality_report["status"] != "ready" or quality_blocked_signal_dates
        else "insufficient_sample"
        if any(item.endswith("_sample_missing") for item in sample_warnings)
        else "exploratory"
        if sample_warnings
        else "reviewable_not_validated"
    )
    known_biases = [
        "Industry and event diagnostics are excluded from replay unless historical point-in-time coverage is available.",
        "Signals and holding periods overlap; summary observations are not independent portfolio returns.",
    ]
    if (_number(quality_report.get("coverage", {}).get("stock_lifecycle")) or 0) < 0.95:
        known_biases.insert(
            0,
            "The symbol universe lacks sufficient historical lifecycle coverage; survivorship bias remains possible.",
        )
    payload = {
        "operation": "short_screen_backtest",
        "schema_version": 4,
        "strategy_contract": strategy_contract,
        "profile": profile.name,
        "benchmark": benchmark,
        "requested_range": {"start_date": str(start_date), "end_date": str(end_date)},
        "sample_split": {
            "out_of_sample_start": oos_date.date().isoformat() if oos_date is not None else None,
            "development_signal_dates": int(sum(date < oos_date for date in signal_dates)) if oos_date is not None else 0,
            "out_of_sample_signal_dates": int(sum(date >= oos_date for date in signal_dates)) if oos_date is not None else 0,
        },
        "signal_dates": int(len(signal_dates)),
        "selected_candidates": selected_total,
        "evaluated_observations": int(len(outcomes)),
        "trigger_replay": {
            "contract": "selection_then_next_session_pattern_trigger_then_price_or_time_invalidation",
            "pattern_triggered": pattern_triggered,
            "pattern_not_triggered": pattern_not_triggered,
            "trigger_rate": (
                pattern_triggered / (pattern_triggered + pattern_not_triggered)
                if pattern_triggered + pattern_not_triggered
                else None
            ),
            "no_trade_is_counted": True,
            "candidate_grade_selected": grade_selected,
            "candidate_grade_triggered": grade_triggered,
            "candidate_grade_not_triggered": grade_not_triggered,
            "price_invalidation_basis": "forward_adjusted_low_with_raw_execution_reference",
            "execution_assumption": (
                "daily_bar_trigger; open gaps use observed open, intraday crosses assume a stop order at the "
                "frozen level; slippage is represented only by the configured transaction-cost deduction"
            ),
        },
        "inference": {
            "status": inference_status,
            "signal_baskets_by_sample": basket_counts,
            "warnings": sample_warnings,
            "review_floor_signal_dates_per_sample": 20,
        },
        "execution": {
            "entry": "next market session open_qfq; close_qfq only when stored open is missing",
            "round_trip_cost_bps": cost_bps,
            "close_fallback_observations": fallback_count,
            "entry_skips_untradable": entry_skips_untradable,
            "entry_skips_limit_up": entry_skips_limit_up,
            "delayed_exit_observations": delayed_exits,
            "limit_down_delayed_exits": limit_down_delayed_exits,
            "unresolved_exit_observations": unresolved_exits,
            "quality_blocked_signal_dates": quality_blocked_signal_dates,
            "maximum_exit_delay_sessions": maximum_exit_delay,
            "suspension_policy": (
                "skip an untradable entry; delay a suspended or limit-down exit to the first stored tradable session"
            ),
        },
        "data_quality": {
            "status": quality_report["status"],
            "decision_blockers": quality_report["decision_blockers"],
            "adjusted_open_coverage": _number(1.0 - (fallback_count / len(outcomes))) if not outcomes.empty else None,
            "mae_coverage": mae_coverage,
            "mfe_coverage": mfe_coverage,
        },
        "horizons": summaries,
        "candidate_grade_performance": grade_summaries,
        "equal_weight_signal_baskets": basket_summaries,
        "data_gaps": [
            item
            for item, missing in (
                ("open_qfq", fallback_count > 0),
                ("intraday_high_low_for_mae_mfe", mae_coverage is not None and mae_coverage < 0.95),
            )
            if missing
        ],
        "known_biases": known_biases,
        "boundary": (
            "Out-of-sample labels are valid only when thresholds were fixed before that interval. "
            "Do not tune on the same outcomes used for evaluation. Technical pattern triggers and mechanical "
            "price/time invalidations are replayed; event, expectation-gap, and Agent research judgments are not."
        ),
        "research_judgment_replayed": False,
    }
    if include_observations:
        payload["outcome_records"] = _records(outcomes)
    return payload


def build_position_plan(
    *,
    account_value: float,
    entry_price: float,
    invalidation_price: float,
    risk_budget_pct: float,
    max_weight_pct: float,
    gap_buffer_pct: float = 0.0,
    lot_size: int = 100,
    current_portfolio_heat_pct: float | None = None,
    portfolio_heat_limit_pct: float | None = None,
    open_positions: int | None = None,
    maximum_open_positions: int | None = None,
    median_daily_amount: float | None = None,
    maximum_order_to_daily_amount_pct: float | None = None,
) -> dict[str, Any]:
    if min(account_value, entry_price, invalidation_price, risk_budget_pct, max_weight_pct) <= 0:
        raise ValueError("account, prices, risk budget, and maximum weight must be positive")
    if risk_budget_pct > 100 or max_weight_pct > 100 or gap_buffer_pct > 100:
        raise ValueError("percentage inputs cannot exceed 100")
    if invalidation_price >= entry_price:
        raise ValueError("long-position invalidation price must be below entry price")
    if gap_buffer_pct < 0:
        raise ValueError("gap buffer cannot be negative")
    structural_loss = (entry_price - invalidation_price) / entry_price
    effective_loss = structural_loss + (gap_buffer_pct / 100.0)
    risk_capital = account_value * (risk_budget_pct / 100.0)
    blockers: list[str] = []
    if current_portfolio_heat_pct is not None or portfolio_heat_limit_pct is not None:
        if current_portfolio_heat_pct is None or portfolio_heat_limit_pct is None:
            raise ValueError("current portfolio heat and portfolio heat limit must be provided together")
        if min(current_portfolio_heat_pct, portfolio_heat_limit_pct) < 0:
            raise ValueError("portfolio heat percentages cannot be negative")
        remaining_heat = max(0.0, portfolio_heat_limit_pct - current_portfolio_heat_pct)
        risk_capital = min(risk_capital, account_value * (remaining_heat / 100.0))
        if remaining_heat <= 0:
            blockers.append("portfolio_heat_limit_reached")
    if open_positions is not None or maximum_open_positions is not None:
        if open_positions is None or maximum_open_positions is None:
            raise ValueError("open positions and maximum open positions must be provided together")
        if open_positions < 0 or maximum_open_positions <= 0:
            raise ValueError("position counts are invalid")
        if open_positions >= maximum_open_positions:
            blockers.append("maximum_open_positions_reached")
    shares_by_risk = floor((risk_capital / (entry_price * effective_loss)) / lot_size) * lot_size
    shares_by_weight = floor(((account_value * max_weight_pct / 100.0) / entry_price) / lot_size) * lot_size
    shares_by_liquidity: int | None = None
    if median_daily_amount is not None or maximum_order_to_daily_amount_pct is not None:
        if median_daily_amount is None or maximum_order_to_daily_amount_pct is None:
            raise ValueError("median daily amount and maximum order share must be provided together")
        if median_daily_amount <= 0 or not 0 < maximum_order_to_daily_amount_pct <= 100:
            raise ValueError("liquidity inputs are invalid")
        liquidity_capital = median_daily_amount * (maximum_order_to_daily_amount_pct / 100.0)
        shares_by_liquidity = floor((liquidity_capital / entry_price) / lot_size) * lot_size
        if shares_by_liquidity <= 0:
            blockers.append("order_too_large_for_liquidity_policy")
    limits = {
        "risk_budget": shares_by_risk,
        "maximum_weight": shares_by_weight,
    }
    if shares_by_liquidity is not None:
        limits["liquidity"] = shares_by_liquidity
    binding_constraint = min(limits, key=limits.get)
    shares = max(0, min(limits.values()))
    if blockers:
        shares = 0
    capital = shares * entry_price
    return {
        "operation": "position_risk_plan",
        "shares": shares,
        "planned_capital": capital,
        "account_weight_pct": (capital / account_value) * 100.0,
        "structural_loss_pct": structural_loss * 100.0,
        "effective_loss_pct": effective_loss * 100.0,
        "planned_loss_at_effective_invalidation": capital * effective_loss,
        "risk_budget_amount": risk_capital,
        "binding_constraint": binding_constraint,
        "position_sizing_status": "pass" if shares > 0 else "blocked",
        "decision_blockers": blockers,
        "constraints": {
            "shares_by_risk": shares_by_risk,
            "shares_by_weight": shares_by_weight,
            "shares_by_liquidity": shares_by_liquidity,
            "current_portfolio_heat_pct": current_portfolio_heat_pct,
            "portfolio_heat_limit_pct": portfolio_heat_limit_pct,
            "open_positions": open_positions,
            "maximum_open_positions": maximum_open_positions,
            "median_daily_amount": median_daily_amount,
            "maximum_order_to_daily_amount_pct": maximum_order_to_daily_amount_pct,
        },
        "boundary": (
            "This sizes a long position only. It cannot guarantee a stop fill under T+1, suspension, "
            "limit-down, or overnight-gap conditions; correlation and theme concentration can require less risk."
        ),
    }


def _load_window(
    db_path: Path,
    start_date: str,
    end_date: str,
    profile: ScreenProfile,
    *,
    benchmark: str,
    include_forward: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp(start_date) - timedelta(days=profile.history_sessions * 2)
    forward = max(profile.forward_horizons) * 2 if include_forward else 0
    end = pd.Timestamp(end_date) + timedelta(days=forward)
    panel = load_daily_screening_panel(
        db_path=db_path,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    benchmark = load_index_daily_history(
        db_path=db_path,
        benchmark=benchmark,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    return panel, benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Point-in-time A-share short-horizon screening and replay")
    subparsers = parser.add_subparsers(dest="command", required=True)

    screen = subparsers.add_parser("screen", help="Build an investable universe and ranked candidate evidence")
    screen.add_argument("--as-of", type=_date, required=True)
    screen.add_argument("--profile", type=_profile, default=PROFILES["trade"])
    screen.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    screen.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    screen.add_argument("--limit", type=_positive_int, default=20)
    screen.add_argument("--min-median-amount", type=_positive_float, default=DEFAULT_MIN_MEDIAN_AMOUNT_CNY)
    screen.add_argument("--min-list-days", type=_positive_int, default=DEFAULT_MIN_LIST_DAYS)
    screen.add_argument("--momentum-percentile", type=_fraction, default=0.7)
    screen.add_argument("--strategy-contract", choices=tuple(STRATEGY_CONTRACTS), default="momentum_trade")
    screen.add_argument("--save-run", action="store_true", help="Persist the screen evidence; does not save a decision")

    evidence = subparsers.add_parser("evidence", help="Build a point-in-time evidence bundle for one candidate")
    evidence.add_argument("--screen-run-id", required=True, help="An explicitly saved short_screen run")
    evidence.add_argument("--symbol", required=True)
    evidence.add_argument("--strategy-contract", choices=tuple(STRATEGY_CONTRACTS))
    evidence.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    evidence.add_argument("--save-run", action="store_true", help="Persist this evidence bundle; no recommendation is implied")

    confirm = subparsers.add_parser("confirm", help="Validate an Agent assessment and produce a recommendation")
    confirm.add_argument("--evidence-run-id", required=True)
    confirm.add_argument("--assessment", type=Path, required=True)
    confirm.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    confirm.add_argument("--project-dir", type=Path, help="Project whose research watchlist receives recommendations")
    confirm.add_argument(
        "--save-run",
        action="store_true",
        help="Compatibility flag; non-cash recommendations are indexed automatically",
    )
    confirm.add_argument("--save-decision", action="store_true", help="Also persist the full evidence and assessment snapshot")

    recommendations = subparsers.add_parser("recommendations", help="List saved recommendations without reviewing them")
    recommendations.add_argument("--symbol")
    recommendations.add_argument("--limit", type=_positive_int, default=50)
    recommendations.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    recommendations.add_argument("--project-dir", type=Path)

    review = subparsers.add_parser("review", help="Explicitly review one saved recommendation")
    review.add_argument("--recommendation-run-id", required=True)
    review.add_argument("--review-as-of", type=_date, required=True)
    review.add_argument("--assessment", type=Path, required=True)
    review.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    review.add_argument("--save-run", action="store_true", help="Persist the optional review result")

    quality = subparsers.add_parser("quality", help="Audit whether local data is fit for screening and execution")
    quality.add_argument("--as-of", type=_date, required=True)
    quality.add_argument("--profile", type=_profile, default=PROFILES["trade"])
    quality.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    quality.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    quality.add_argument("--for-replay", action="store_true", help="Also require historical listing/delisting metadata")

    backtest = subparsers.add_parser("backtest", help="Replay the same screen with point-in-time inputs")
    backtest.add_argument("--start-date", type=_date, required=True)
    backtest.add_argument("--end-date", type=_date, required=True)
    backtest.add_argument("--profile", type=_profile, default=PROFILES["trade"])
    backtest.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    backtest.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    backtest.add_argument("--limit", type=_positive_int, default=10)
    backtest.add_argument("--rebalance-sessions", type=_positive_int, default=5)
    backtest.add_argument("--max-signals", type=_positive_int, default=60)
    backtest.add_argument("--cost-bps", type=_positive_float, default=20.0)
    backtest.add_argument("--min-median-amount", type=_positive_float, default=DEFAULT_MIN_MEDIAN_AMOUNT_CNY)
    backtest.add_argument("--min-list-days", type=_positive_int, default=DEFAULT_MIN_LIST_DAYS)
    backtest.add_argument("--momentum-percentile", type=_fraction, default=0.7)
    backtest.add_argument("--strategy-contract", choices=tuple(STRATEGY_CONTRACTS), default="momentum_trade")
    backtest.add_argument(
        "--out-of-sample-start",
        type=_date,
        help="Label later signal dates as held-out; thresholds must have been fixed beforehand",
    )
    backtest.add_argument("--save-run", action="store_true", help="Persist summary and raw outcomes in the project SQLite")

    risk = subparsers.add_parser("risk", help="Translate a research candidate into a capped A-share lot size")
    risk.add_argument("--account-value", type=_positive_float, required=True)
    risk.add_argument("--entry-price", type=_positive_float, required=True)
    risk.add_argument("--invalidation-price", type=_positive_float, required=True)
    risk.add_argument("--risk-budget-pct", type=_positive_float, required=True)
    risk.add_argument("--max-weight-pct", type=_positive_float, required=True)
    risk.add_argument("--gap-buffer-pct", type=float, default=0.0)
    risk.add_argument("--lot-size", type=_positive_int, default=100)
    risk.add_argument("--current-portfolio-heat-pct", type=float)
    risk.add_argument("--portfolio-heat-limit-pct", type=_positive_float)
    risk.add_argument("--open-positions", type=int)
    risk.add_argument("--maximum-open-positions", type=_positive_int)
    risk.add_argument("--median-daily-amount", type=_positive_float)
    risk.add_argument("--maximum-order-to-daily-amount-pct", type=_positive_float)
    risk.add_argument("--recommendation-run-id")
    risk.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    risk.add_argument("--save-run", action="store_true", help="Persist the optional position risk plan")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"screen", "backtest"}:
            expected_profile = STRATEGY_CONTRACTS[args.strategy_contract]["profile"]
            if args.profile.name != expected_profile:
                raise ValueError(
                    f"{args.strategy_contract} requires profile {expected_profile}; got {args.profile.name}"
                )
        if args.command == "risk":
            payload = build_position_plan(
                account_value=args.account_value,
                entry_price=args.entry_price,
                invalidation_price=args.invalidation_price,
                risk_budget_pct=args.risk_budget_pct,
                max_weight_pct=args.max_weight_pct,
                gap_buffer_pct=args.gap_buffer_pct,
                lot_size=args.lot_size,
                current_portfolio_heat_pct=args.current_portfolio_heat_pct,
                portfolio_heat_limit_pct=args.portfolio_heat_limit_pct,
                open_positions=args.open_positions,
                maximum_open_positions=args.maximum_open_positions,
                median_daily_amount=args.median_daily_amount,
                maximum_order_to_daily_amount_pct=args.maximum_order_to_daily_amount_pct,
            )
            payload["operation"] = "position_risk_plan"
            payload["schema_version"] = 4
            payload["execution_status"] = "not_observed"
            payload["plan_ready"] = payload["position_sizing_status"] == "pass"
            payload["execution_ready"] = False
            payload["boundary"] = (
                "This is a risk-budget plan, not an order or evidence that the user executed it. "
                "A-share T+1, suspension, limit-down, and overnight gaps can prevent the modeled exit."
            )
            if args.recommendation_run_id:
                source = load_short_screen_run(
                    args.recommendation_run_id,
                    db_path=args.db_path,
                    expected_operations=("short_confirmation",),
                )
                recommendation = source["payload"]
                payload["parent_run_id"] = args.recommendation_run_id
                payload["strategy_contract"] = recommendation.get("strategy_contract")
                payload["profile"] = recommendation.get("profile")
                payload["benchmark"] = recommendation.get("benchmark")
                payload["requested_as_of"] = recommendation.get("requested_as_of")
                payload["symbol"] = recommendation.get("symbol")
                payload["research_decision_ready"] = recommendation.get("decision_ready")
                recommendation_record = recommendation.get("recommendation")
                recommendation_record = (
                    recommendation_record if isinstance(recommendation_record, Mapping) else {}
                )
                report_card = recommendation_record.get("report_card")
                report_card = report_card if isinstance(report_card, Mapping) else {}
                candidate_grade = str(report_card.get("候选等级") or "")
                payload["candidate_grade"] = candidate_grade or None
                if candidate_grade and not candidate_grade.startswith("A类："):
                    payload["shares"] = 0
                    payload["planned_capital"] = 0.0
                    payload["account_weight_pct"] = 0.0
                    payload["planned_loss_at_effective_invalidation"] = 0.0
                    payload["position_sizing_status"] = "blocked"
                    payload["plan_ready"] = False
                    payload["decision_blockers"] = list(payload.get("decision_blockers") or []) + [
                        "candidate_grade_not_executable"
                    ]
            if args.save_run:
                payload["saved_run_id"] = write_short_screen_run(
                    payload,
                    db_path=args.db_path,
                    parent_run_id=args.recommendation_run_id,
                )
        elif args.command == "recommendations":
            recommendation_db = (
                project_paths(args.project_dir).database_path if args.project_dir else args.db_path
            )
            payload = {
                "status": "available",
                "review_started": False,
                "recommendations": list_short_recommendation_runs(
                    db_path=recommendation_db, symbol=args.symbol, limit=args.limit
                ),
            }
        elif args.command == "evidence":
            source = load_short_screen_run(
                args.screen_run_id,
                db_path=args.db_path,
                expected_operations=("short_screen",),
            )
            screen_payload = enrich_screen_readiness(source["payload"])
            contract = args.strategy_contract or str(screen_payload.get("strategy_contract") or "momentum_trade")
            screen_date = pd.Timestamp(screen_payload.get("requested_as_of"))
            events = load_known_corporate_events(
                db_path=args.db_path,
                as_of=str(screen_payload.get("requested_as_of")),
                start_date=(screen_date - timedelta(days=10)).strftime("%Y%m%d"),
                end_date=(screen_date + timedelta(days=30)).strftime("%Y%m%d"),
                symbols=[args.symbol],
            )
            price_history = load_daily_price_history(
                db_path=args.db_path,
                end_date=str(screen_payload.get("requested_as_of")),
                symbols=[args.symbol],
            )
            indicator_snapshot: dict[str, object] = {}
            if not price_history.empty:
                technical_history = price_history.copy()
                technical_history["trade_date"] = pd.to_datetime(
                    technical_history["trade_date"], errors="coerce"
                )
                technical_history = technical_history.dropna(subset=["trade_date"]).set_index(
                    "trade_date"
                ).sort_index()
                indicator_benchmark = load_index_daily_history(
                    db_path=args.db_path,
                    benchmark=str(screen_payload.get("benchmark") or DEFAULT_BENCHMARK),
                    end_date=str(screen_payload.get("requested_as_of")),
                )
                benchmark_prices = None
                if not indicator_benchmark.empty:
                    indicator_benchmark = indicator_benchmark.copy()
                    indicator_benchmark["trade_date"] = pd.to_datetime(
                        indicator_benchmark["trade_date"], errors="coerce"
                    )
                    benchmark_prices = indicator_benchmark.dropna(subset=["trade_date"]).set_index(
                        "trade_date"
                    ).sort_index()["close"]
                indicators = calculate_technical_indicators(
                    technical_history["close_qfq"],
                    technical_history.get("volume"),
                    benchmark_prices=benchmark_prices,
                    high_prices=technical_history.get("high_qfq"),
                    low_prices=technical_history.get("low_qfq"),
                )
                if not indicators.empty:
                    indicator_snapshot = summarize_technical_indicators(indicators)
            payload = build_evidence_bundle(
                screen_payload,
                symbol=args.symbol,
                contract_name=contract,
                events=events.to_dict(orient="records"),
                indicator_snapshot=indicator_snapshot,
            )
            payload["parent_run_id"] = args.screen_run_id
        elif args.command == "confirm":
            source = load_short_screen_run(
                args.evidence_run_id,
                db_path=args.db_path,
                expected_operations=("short_evidence",),
            )
            payload = confirm_evidence(source["payload"], load_json_object(args.assessment))
            payload["parent_run_id"] = args.evidence_run_id
            if args.save_decision:
                payload["decision_snapshot_saved"] = True
                payload["snapshot_scope"] = "full_evidence_and_assessment"
            else:
                payload = compact_confirmation(payload)
            if payload.get("recommendation") is not None or args.save_run or args.save_decision:
                payload["saved_run_id"] = write_short_screen_run(
                    payload,
                    db_path=args.db_path,
                    parent_run_id=args.evidence_run_id,
                )
            recommendation = payload.get("recommendation")
            if isinstance(recommendation, Mapping):
                selected_project = project_paths(args.project_dir).root
                action_label = str(recommendation.get("action_label") or "")
                status = {
                    "等待价格": "waiting-price",
                    "等待证据": "waiting-evidence",
                }.get(action_label, "tracking")
                invalidation = recommendation.get("invalidation")
                invalidation = invalidation if isinstance(invalidation, Mapping) else {}
                action, item = upsert_watch_item(
                    watchlist_path(selected_project),
                    {
                        "symbol": recommendation.get("symbol"),
                        "name": recommendation.get("name"),
                        "status": status,
                        "research_path": "short-term",
                        "action_label": action_label,
                        "confidence": recommendation.get("confidence"),
                        "thesis": recommendation.get("thesis"),
                        "follow_up": recommendation.get("entry_trigger"),
                        "invalidation": "; ".join(
                            f"{key}: {value}" for key, value in invalidation.items() if value
                        ),
                        "recommended_on": recommendation.get("recommended_on"),
                        "last_researched_on": recommendation.get("recommended_on"),
                        "notes": f"short_confirmation:{payload.get('saved_run_id', '')}",
                    },
                )
                payload["recommendation_store"] = {
                    "status": action,
                    "watchlist_path": str(watchlist_path(selected_project)),
                    "symbol": item["symbol"],
                }
        elif args.command == "review":
            source = load_short_screen_run(
                args.recommendation_run_id,
                db_path=args.db_path,
                expected_operations=("short_confirmation",),
            )
            recommendation = source["payload"]
            if not isinstance(recommendation, Mapping):
                raise ValueError("Saved recommendation payload is invalid")
            symbol = str(recommendation.get("symbol") or "")
            start = str(recommendation.get("requested_as_of") or "")
            price_history = load_daily_price_history(
                db_path=args.db_path,
                start_date=start,
                end_date=args.review_as_of,
                symbols=[symbol],
            )
            benchmark_history = load_index_daily_history(
                db_path=args.db_path,
                benchmark=str(recommendation.get("benchmark") or DEFAULT_BENCHMARK),
                start_date=start,
                end_date=args.review_as_of,
            )
            payload = review_recommendation(
                recommendation,
                load_json_object(args.assessment),
                review_as_of=args.review_as_of,
                price_history=price_history,
                benchmark_history=benchmark_history,
            )
            payload["parent_run_id"] = args.recommendation_run_id
            if args.save_run:
                payload["saved_run_id"] = write_short_screen_run(
                    payload,
                    db_path=args.db_path,
                    parent_run_id=args.recommendation_run_id,
                )
        elif args.command in {"quality", "screen"}:
            panel, benchmark_history = _load_window(
                args.db_path,
                args.as_of,
                args.as_of,
                args.profile,
                benchmark=args.benchmark,
                include_forward=False,
            )
            if args.command == "quality":
                payload = build_data_quality_report(
                    panel,
                    benchmark_history,
                    as_of=args.as_of,
                    min_history_sessions=args.profile.trend_window,
                    require_historical_lifecycle=args.for_replay,
                )
                print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
                return 0
            memberships = load_sector_memberships(db_path=args.db_path, provider="ths", as_of=args.as_of)
            event_start = (pd.Timestamp(args.as_of) - timedelta(days=10)).strftime("%Y%m%d")
            event_end = (pd.Timestamp(args.as_of) + timedelta(days=30)).strftime("%Y%m%d")
            events = load_known_corporate_events(
                db_path=args.db_path,
                as_of=args.as_of,
                start_date=event_start,
                end_date=event_end,
            )
            payload = build_screen(
                panel,
                benchmark_history,
                as_of=args.as_of,
                profile=args.profile,
                benchmark=args.benchmark,
                limit=args.limit,
                min_median_amount_cny=args.min_median_amount,
                min_list_days=args.min_list_days,
                momentum_percentile=args.momentum_percentile,
                memberships=memberships,
                events=events,
            )
            if args.command == "screen":
                payload["strategy_contract"] = args.strategy_contract
                payload = enrich_screen_readiness(payload)
        else:
            panel, benchmark_history = _load_window(
                args.db_path,
                args.start_date,
                args.end_date,
                args.profile,
                benchmark=args.benchmark,
                include_forward=True,
            )
            payload = evaluate_screen_history(
                panel,
                benchmark_history,
                start_date=args.start_date,
                end_date=args.end_date,
                profile=args.profile,
                benchmark=args.benchmark,
                limit=args.limit,
                rebalance_sessions=args.rebalance_sessions,
                cost_bps=args.cost_bps,
                max_signals=args.max_signals,
                min_median_amount_cny=args.min_median_amount,
                min_list_days=args.min_list_days,
                momentum_percentile=args.momentum_percentile,
                out_of_sample_start=args.out_of_sample_start,
                include_observations=args.save_run,
                strategy_contract=args.strategy_contract,
            )
        if getattr(args, "save_run", False) and args.command in {"screen", "evidence", "backtest"}:
            outcomes = payload.pop("outcome_records", [])
            payload["saved_run_id"] = write_short_screen_run(
                payload,
                outcomes=outcomes,
                db_path=args.db_path,
                parent_run_id=str(payload.get("parent_run_id") or "") or None,
            )
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
