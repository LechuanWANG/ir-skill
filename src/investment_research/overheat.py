from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .domain import OverheatAssessment


def _numeric(frame: pd.DataFrame, candidates: Iterable[str]) -> pd.Series | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return pd.to_numeric(frame[candidate], errors="coerce")
    return None


def _percentile_rank(value: float | None, population: pd.Series | None) -> float | None:
    if value is None or population is None:
        return None
    clean = pd.to_numeric(population, errors="coerce").dropna()
    if clean.empty:
        return None
    return float((clean <= value).mean())


def _period_return(close: pd.Series, days: int) -> float | None:
    clean = pd.to_numeric(close, errors="coerce").dropna()
    if len(clean) <= days:
        return None
    return float(clean.iloc[-1] / clean.iloc[-days - 1] - 1)


def _snapshot_values(frame: pd.DataFrame | None, column: str) -> pd.Series | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    return pd.to_numeric(frame[column], errors="coerce")


def _chronological(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return frame
    result = frame.copy()
    for column in ("trade_date", "event_date", "date", "ann_date", "report_date"):
        if column not in result.columns:
            continue
        parsed = pd.to_datetime(result[column], errors="coerce")
        if parsed.notna().any():
            result = result.assign(_chronological_date=parsed).sort_values(
                "_chronological_date",
                kind="stable",
            )
            return result.drop(columns=["_chronological_date"]).reset_index(drop=True)
    return result.reset_index(drop=True)


def prepare_adjusted_bars(
    daily: pd.DataFrame,
    adj_factor: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    bars = daily.copy()
    date_column = "trade_date" if "trade_date" in bars.columns else "date"
    bars[date_column] = pd.to_datetime(bars[date_column])
    bars = bars.sort_values(date_column).drop_duplicates(subset=[date_column], keep="last")
    bars = bars.rename(columns={date_column: "trade_date", "vol": "volume"})

    if adj_factor is not None and not adj_factor.empty and "adj_factor" in adj_factor.columns:
        factors = adj_factor.copy()
        factor_date = "trade_date" if "trade_date" in factors.columns else "date"
        factors[factor_date] = pd.to_datetime(factors[factor_date])
        factors = factors.rename(columns={factor_date: "trade_date"})
        merge_columns = ["trade_date"]
        if "ts_code" in bars.columns and "ts_code" in factors.columns:
            merge_columns.append("ts_code")
        bars = bars.merge(
            factors[[*merge_columns, "adj_factor"]],
            on=merge_columns,
            how="left",
        )
        bars["adj_factor"] = pd.to_numeric(bars["adj_factor"], errors="coerce").ffill().bfill()
        latest_factor = bars["adj_factor"].dropna().iloc[-1] if bars["adj_factor"].notna().any() else None
        if latest_factor:
            adjustment_ratio = bars["adj_factor"] / latest_factor
            for column in ("open", "high", "low", "close"):
                if column in bars.columns:
                    bars[f"{column}_qfq"] = pd.to_numeric(bars[column], errors="coerce") * adjustment_ratio

    for column in ("open", "high", "low", "close"):
        adjusted = f"{column}_qfq"
        if adjusted not in bars.columns and column in bars.columns:
            bars[adjusted] = pd.to_numeric(bars[column], errors="coerce")
    return bars.sort_values("trade_date").reset_index(drop=True)


def assess_relative_overheat(
    bars: pd.DataFrame,
    *,
    valuation_history: pd.DataFrame | None = None,
    market_snapshot: pd.DataFrame | None = None,
    industry_snapshot: pd.DataFrame | None = None,
    peer_valuation_snapshot: pd.DataFrame | None = None,
    benchmark_close: pd.Series | None = None,
    margin_history: pd.DataFrame | None = None,
    earnings_revision_positive: bool = False,
) -> OverheatAssessment:
    if bars.empty:
        return OverheatAssessment(
            is_overheated=False,
            severity="unknown",
            data_timestamp=None,
            missing_metrics=("price_bars",),
        )

    ordered = bars.copy()
    valuation_history = _chronological(valuation_history)
    margin_history = _chronological(margin_history)
    if "trade_date" in ordered.columns:
        ordered["trade_date"] = pd.to_datetime(ordered["trade_date"])
        ordered = ordered.sort_values("trade_date")
        data_timestamp = ordered["trade_date"].iloc[-1].date().isoformat()
    else:
        ordered = ordered.sort_index()
        data_timestamp = pd.Timestamp(ordered.index[-1]).date().isoformat()

    close = _numeric(ordered, ("close_qfq", "close"))
    high = _numeric(ordered, ("high_qfq", "high"))
    low = _numeric(ordered, ("low_qfq", "low"))
    open_price = _numeric(ordered, ("open_qfq", "open"))
    volume = _numeric(ordered, ("volume", "vol"))
    amount = _numeric(ordered, ("amount",))
    missing: list[str] = []
    if close is None:
        return OverheatAssessment(
            is_overheated=False,
            severity="unknown",
            data_timestamp=data_timestamp,
            missing_metrics=("close",),
        )

    return_20d = _period_return(close, 20)
    return_60d = _period_return(close, 60)
    if return_20d is None:
        missing.append("return_20d")
    if return_60d is None:
        missing.append("return_60d")

    market_20 = _snapshot_values(market_snapshot, "return_20d")
    industry_60 = _snapshot_values(industry_snapshot, "return_60d")
    return_20d_market_percentile = _percentile_rank(return_20d, market_20)
    return_60d_industry_percentile = _percentile_rank(return_60d, industry_60)
    if return_20d_market_percentile is None:
        missing.append("return_20d_market_percentile")
    if return_60d_industry_percentile is None:
        missing.append("return_60d_industry_percentile")

    benchmark_excess_20d = None
    benchmark_excess_60d = None
    if benchmark_close is not None:
        benchmark_excess_20d = (
            return_20d - benchmark_return
            if return_20d is not None and (benchmark_return := _period_return(benchmark_close, 20)) is not None
            else None
        )
        benchmark_excess_60d = (
            return_60d - benchmark_return
            if return_60d is not None and (benchmark_return := _period_return(benchmark_close, 60)) is not None
            else None
        )

    atr14_percent = None
    ma60_distance_atr = None
    atr_available = False
    volatility14_percent = None
    ma60_distance_volatility = None
    gap_count_20d = None
    return_volatility = daily_returns = close.pct_change()
    rolling_volatility = return_volatility.rolling(14, min_periods=10).std()
    if pd.notna(rolling_volatility.iloc[-1]):
        volatility14_percent = float(rolling_volatility.iloc[-1])
        volatility_unit = close.iloc[-1] * rolling_volatility.iloc[-1]
        ma60 = close.rolling(60, min_periods=40).mean()
        if pd.notna(ma60.iloc[-1]) and volatility_unit:
            ma60_distance_volatility = float((close.iloc[-1] - ma60.iloc[-1]) / volatility_unit)
    if high is not None and low is not None:
        atr_available = True
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr14 = true_range.rolling(14, min_periods=10).mean()
        if pd.notna(atr14.iloc[-1]) and close.iloc[-1]:
            atr14_percent = float(atr14.iloc[-1] / close.iloc[-1])
            ma60 = close.rolling(60, min_periods=40).mean()
            if pd.notna(ma60.iloc[-1]) and atr14.iloc[-1]:
                ma60_distance_atr = float((close.iloc[-1] - ma60.iloc[-1]) / atr14.iloc[-1])
        if open_price is not None:
            gaps = (open_price - previous_close) > atr14.shift(1)
            gap_count_20d = int(gaps.tail(20).fillna(False).sum())
    else:
        missing.extend(("atr14_ohlc_unavailable", "gap_count_20d"))

    limit_count_20d = int((daily_returns.tail(20) >= 0.095).sum()) if len(close) > 1 else None
    volume_percentile = _percentile_rank(
        float(volume.iloc[-1]) if volume is not None and pd.notna(volume.iloc[-1]) else None,
        volume.tail(252) if volume is not None else None,
    )
    if volume_percentile is None:
        missing.append("volume_percentile")
    average_amount_20d = (
        float(amount.tail(20).mean())
        if amount is not None and amount.tail(20).notna().any()
        else None
    )
    if average_amount_20d is None:
        missing.append("average_amount_20d")

    valuation_history_percentiles: list[float] = []
    turnover_percentile = None
    if valuation_history is not None and not valuation_history.empty:
        for column in ("pe_ttm", "pb", "ps_ttm"):
            values = _snapshot_values(valuation_history, column)
            if values is not None and values.notna().any():
                percentile = _percentile_rank(float(values.dropna().iloc[-1]), values)
                if percentile is not None:
                    valuation_history_percentiles.append(percentile)
        turnover = _snapshot_values(valuation_history, "turnover_rate")
        if turnover is not None and turnover.notna().any():
            turnover_percentile = _percentile_rank(float(turnover.dropna().iloc[-1]), turnover)
    valuation_history_percentile = max(valuation_history_percentiles) if valuation_history_percentiles else None
    if valuation_history_percentile is None:
        missing.append("valuation_history_percentile")
    if turnover_percentile is None:
        missing.append("turnover_percentile")

    peer_percentiles: list[float] = []
    if valuation_history is not None and not valuation_history.empty and peer_valuation_snapshot is not None:
        for column in ("pe_ttm", "pb", "ps_ttm"):
            history_values = _snapshot_values(valuation_history, column)
            peer_values = _snapshot_values(peer_valuation_snapshot, column)
            if history_values is not None and history_values.notna().any():
                percentile = _percentile_rank(float(history_values.dropna().iloc[-1]), peer_values)
                if percentile is not None:
                    peer_percentiles.append(percentile)
    valuation_peer_percentile = max(peer_percentiles) if peer_percentiles else None
    if valuation_peer_percentile is None:
        missing.append("valuation_peer_percentile")

    margin_change_percentile = None
    if margin_history is not None and not margin_history.empty:
        margin_balance = _numeric(margin_history, ("margin_balance", "rzye"))
        if margin_balance is not None:
            changes = margin_balance.pct_change(5)
            if changes.notna().any():
                margin_change_percentile = _percentile_rank(float(changes.dropna().iloc[-1]), changes)
    if margin_change_percentile is None:
        missing.append("margin_change_percentile")

    triggers: list[str] = []
    if not earnings_revision_positive and any(
        percentile is not None and percentile >= 0.90
        for percentile in (valuation_history_percentile, valuation_peer_percentile)
    ):
        triggers.append("valuation_extreme_without_revision")
    relative_extreme = any(
        percentile is not None and percentile >= 0.90
        for percentile in (return_20d_market_percentile, return_60d_industry_percentile)
    )
    if relative_extreme:
        triggers.append("relative_return_extreme")
    if ma60_distance_atr is not None:
        if ma60_distance_atr >= 2.0:
            triggers.append("price_above_ma60_by_2atr")
    elif ma60_distance_volatility is not None and ma60_distance_volatility >= 2.0:
        triggers.append("price_above_ma60_by_2volatility_units")
    crowding_count = sum(
        percentile is not None and percentile >= 0.90
        for percentile in (volume_percentile, turnover_percentile, margin_change_percentile)
    )
    if crowding_count >= 2:
        triggers.append("crowding_extreme")
    if (gap_count_20d or 0) >= 2 or (limit_count_20d or 0) >= 2:
        triggers.append("event_gap_or_limit_cluster")

    hard_trigger = any(
        trigger in triggers
        for trigger in (
            "valuation_extreme_without_revision",
            "price_above_ma60_by_2atr",
            "price_above_ma60_by_2volatility_units",
            "event_gap_or_limit_cluster",
        )
    )
    is_overheated = hard_trigger or (
        "relative_return_extreme" in triggers and "crowding_extreme" in triggers
    )
    severity = "severe" if len(triggers) >= 3 else "elevated" if is_overheated else "normal"
    return OverheatAssessment(
        is_overheated=is_overheated,
        severity=severity,
        data_timestamp=data_timestamp,
        reference_price=float(close.dropna().iloc[-1]) if close.notna().any() else None,
        valuation_history_percentile=valuation_history_percentile,
        valuation_peer_percentile=valuation_peer_percentile,
        return_20d=return_20d,
        return_60d=return_60d,
        return_20d_market_percentile=return_20d_market_percentile,
        return_60d_industry_percentile=return_60d_industry_percentile,
        benchmark_excess_20d=benchmark_excess_20d,
        benchmark_excess_60d=benchmark_excess_60d,
        atr_available=atr_available,
        atr14_percent=atr14_percent,
        ma60_distance_atr=ma60_distance_atr,
        volatility14_percent=volatility14_percent,
        ma60_distance_volatility=ma60_distance_volatility,
        volume_percentile=volume_percentile,
        turnover_percentile=turnover_percentile,
        margin_change_percentile=margin_change_percentile,
        gap_count_20d=gap_count_20d,
        limit_count_20d=limit_count_20d,
        average_amount_20d=average_amount_20d,
        triggers=tuple(triggers),
        missing_metrics=tuple(dict.fromkeys(missing)),
    )
