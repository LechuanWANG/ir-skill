"""Deterministic technical indicators derived from locally stored market data."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log, sqrt
from typing import Any

import pandas as pd


TRADING_DAYS_PER_YEAR = 252
HISTORICAL_PRICE_WINDOWS = {
    "trailing_1y": TRADING_DAYS_PER_YEAR,
    "trailing_3y": TRADING_DAYS_PER_YEAR * 3,
}
MIN_OBSERVATIONS_FOR_PATH_LABEL = TRADING_DAYS_PER_YEAR // 2


@dataclass(frozen=True)
class TechnicalIndicatorSettings:
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_window: int = 14
    bollinger_window: int = 20
    bollinger_std: float = 2.0
    sma_short: int = 20
    sma_long: int = 60
    volume_window: int = 20

    def validate(self) -> None:
        positive_windows = (
            self.macd_fast,
            self.macd_slow,
            self.macd_signal,
            self.rsi_window,
            self.bollinger_window,
            self.sma_short,
            self.sma_long,
            self.volume_window,
        )
        if any(value <= 0 for value in positive_windows):
            raise ValueError("technical-indicator windows must be greater than zero")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("MACD fast window must be smaller than the slow window")
        if self.sma_short >= self.sma_long:
            raise ValueError("short SMA window must be smaller than the long SMA window")
        if self.bollinger_std <= 0:
            raise ValueError("Bollinger standard-deviation multiplier must be greater than zero")

    @property
    def warmup_observations(self) -> int:
        return max(
            self.macd_slow + self.macd_signal - 1,
            self.rsi_window,
            self.bollinger_window,
            self.sma_long,
            self.volume_window,
        )


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float).sort_index()


def calculate_technical_indicators(
    close_prices: pd.Series,
    volumes: pd.Series | None = None,
    *,
    benchmark_prices: pd.Series | None = None,
    high_prices: pd.Series | None = None,
    low_prices: pd.Series | None = None,
    settings: TechnicalIndicatorSettings = TechnicalIndicatorSettings(),
) -> pd.DataFrame:
    """Calculate indicators and preserve available forward-adjusted price extremes."""
    settings.validate()
    prices = _numeric_series(close_prices)
    if prices.empty:
        return pd.DataFrame(index=prices.index)

    returns = prices.pct_change(fill_method=None)
    rolling_short = prices.rolling(settings.sma_short, min_periods=settings.sma_short).mean()
    rolling_long = prices.rolling(settings.sma_long, min_periods=settings.sma_long).mean()

    macd_fast = prices.ewm(
        span=settings.macd_fast,
        adjust=False,
        min_periods=settings.macd_fast,
    ).mean()
    macd_slow = prices.ewm(
        span=settings.macd_slow,
        adjust=False,
        min_periods=settings.macd_slow,
    ).mean()
    macd_line = macd_fast - macd_slow
    macd_signal = macd_line.ewm(
        span=settings.macd_signal,
        adjust=False,
        min_periods=settings.macd_signal,
    ).mean()

    price_changes = prices.diff()
    gains = price_changes.clip(lower=0)
    losses = -price_changes.clip(upper=0)
    average_gain = gains.ewm(
        alpha=1 / settings.rsi_window,
        adjust=False,
        min_periods=settings.rsi_window,
    ).mean()
    average_loss = losses.ewm(
        alpha=1 / settings.rsi_window,
        adjust=False,
        min_periods=settings.rsi_window,
    ).mean()
    relative_strength = average_gain / average_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + relative_strength))
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
    rsi = rsi.mask((average_gain == 0) & (average_loss > 0), 0.0)
    rsi = rsi.mask((average_gain == 0) & (average_loss == 0), 50.0)

    bollinger_middle = prices.rolling(
        settings.bollinger_window,
        min_periods=settings.bollinger_window,
    ).mean()
    bollinger_deviation = prices.rolling(
        settings.bollinger_window,
        min_periods=settings.bollinger_window,
    ).std(ddof=0)
    bollinger_upper = bollinger_middle + (settings.bollinger_std * bollinger_deviation)
    bollinger_lower = bollinger_middle - (settings.bollinger_std * bollinger_deviation)
    bollinger_range = (bollinger_upper - bollinger_lower).replace(0, float("nan"))

    result = pd.DataFrame(index=prices.index)
    result.index.name = prices.index.name or "trade_date"
    result["close_qfq"] = prices
    if high_prices is not None:
        result["high_qfq"] = _numeric_series(high_prices).reindex(prices.index)
    if low_prices is not None:
        result["low_qfq"] = _numeric_series(low_prices).reindex(prices.index)
    result[f"sma_{settings.sma_short}"] = rolling_short
    result[f"sma_{settings.sma_long}"] = rolling_long
    result[f"price_vs_sma_{settings.sma_short}"] = (prices / rolling_short) - 1
    result[f"price_vs_sma_{settings.sma_long}"] = (prices / rolling_long) - 1
    result[f"return_{settings.sma_short}d"] = prices.pct_change(settings.sma_short, fill_method=None)
    if benchmark_prices is not None:
        benchmark = _numeric_series(benchmark_prices).reindex(prices.index)
        benchmark_return = benchmark.pct_change(settings.sma_short, fill_method=None)
        result["benchmark_close"] = benchmark
        result[f"benchmark_return_{settings.sma_short}d"] = benchmark_return
        result[f"relative_return_{settings.sma_short}d"] = (
            result[f"return_{settings.sma_short}d"] - benchmark_return
        )
    result[f"volatility_{settings.sma_short}d_annualized"] = (
        returns.rolling(settings.sma_short, min_periods=settings.sma_short).std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR)
    )
    result[f"macd_{settings.macd_fast}_{settings.macd_slow}"] = macd_line
    result[f"macd_signal_{settings.macd_signal}"] = macd_signal
    result["macd_histogram"] = macd_line - macd_signal
    result[f"rsi_{settings.rsi_window}"] = rsi
    result[f"bollinger_middle_{settings.bollinger_window}"] = bollinger_middle
    result[f"bollinger_upper_{settings.bollinger_window}"] = bollinger_upper
    result[f"bollinger_lower_{settings.bollinger_window}"] = bollinger_lower
    result[f"bollinger_percent_b_{settings.bollinger_window}"] = (prices - bollinger_lower) / bollinger_range
    result[f"bollinger_bandwidth_{settings.bollinger_window}"] = bollinger_range / bollinger_middle.replace(0, float("nan"))

    if volumes is not None:
        volume_series = _numeric_series(volumes).reindex(prices.index)
        average_volume = volume_series.rolling(
            settings.volume_window,
            min_periods=settings.volume_window,
        ).mean()
        turnover_value_proxy = prices * volume_series
        average_turnover_value = turnover_value_proxy.rolling(
            settings.volume_window,
            min_periods=settings.volume_window,
        ).mean()
        volume_changes = volume_series.pct_change(fill_method=None)
        up_day_volume = volume_series.where(returns > 0, 0.0)
        result["volume"] = volume_series
        result[f"volume_ratio_{settings.volume_window}d"] = volume_series / average_volume.replace(0, float("nan"))
        result[f"price_volume_ratio_{settings.volume_window}d"] = turnover_value_proxy / average_turnover_value.replace(
            0,
            float("nan"),
        )
        result[f"price_volume_correlation_{settings.volume_window}d"] = returns.rolling(
            settings.volume_window,
            min_periods=settings.volume_window,
        ).corr(volume_changes)
        result[f"up_volume_share_{settings.volume_window}d"] = up_day_volume.rolling(
            settings.volume_window,
            min_periods=settings.volume_window,
        ).sum() / volume_series.rolling(
            settings.volume_window,
            min_periods=settings.volume_window,
        ).sum().replace(0, float("nan"))

    return result


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _change_over_sessions(series: pd.Series, sessions: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= sessions:
        return None
    return _finite_number(values.iloc[-1] - values.iloc[-1 - sessions])


def _last_macd_cross(histogram: pd.Series, lookback_sessions: int) -> dict[str, Any] | None:
    values = pd.to_numeric(histogram, errors="coerce").dropna().tail(lookback_sessions + 1)
    if len(values) < 2:
        return None
    for position in range(len(values) - 1, 0, -1):
        previous = float(values.iloc[position - 1])
        current = float(values.iloc[position])
        if previous <= 0 < current:
            direction = "crossed_above_signal"
        elif previous >= 0 > current:
            direction = "crossed_below_signal"
        else:
            continue
        return {
            "trade_date": pd.Timestamp(values.index[position]).strftime("%Y-%m-%d"),
            "direction": direction,
            "sessions_ago": len(values) - 1 - position,
        }
    return None


def _price_path_label(
    annualized_log_trend: float | None,
    trend_r_squared: float | None,
    observations: int,
) -> str:
    """Classify a price path descriptively; it is not a trading signal."""
    if observations < MIN_OBSERVATIONS_FOR_PATH_LABEL:
        return "insufficient_history_for_path_label"
    if annualized_log_trend is None or trend_r_squared is None:
        return "insufficient_price_data_for_path_label"
    if annualized_log_trend >= 0.10 and trend_r_squared >= 0.45:
        return "persistent_uptrend"
    if annualized_log_trend <= -0.10 and trend_r_squared >= 0.45:
        return "persistent_downtrend"
    if abs(annualized_log_trend) < 0.10 and trend_r_squared < 0.25:
        return "sideways_or_oscillating"
    return "mixed_or_transitional"


def _linear_log_price_trend(prices: pd.Series) -> tuple[float | None, float | None]:
    """Return annualized log-price slope and fit quality without adding a numpy dependency."""
    values = [float(value) for value in prices.tolist() if value > 0 and isfinite(float(value))]
    count = len(values)
    if count < 2:
        return None, None

    x_mean = (count - 1) / 2
    log_values = [log(value) for value in values]
    y_mean = sum(log_values) / count
    denominator = sum((position - x_mean) ** 2 for position in range(count))
    if denominator == 0:
        return None, None
    slope = sum(
        (position - x_mean) * (value - y_mean)
        for position, value in enumerate(log_values)
    ) / denominator
    intercept = y_mean - (slope * x_mean)
    total_sum_squares = sum((value - y_mean) ** 2 for value in log_values)
    residual_sum_squares = sum(
        (value - (intercept + (slope * position))) ** 2
        for position, value in enumerate(log_values)
    )
    trend_r_squared = 1.0 if total_sum_squares == 0 else max(0.0, 1 - (residual_sum_squares / total_sum_squares))
    return exp(slope * TRADING_DAYS_PER_YEAR) - 1, trend_r_squared


def _summarize_price_path(
    close_prices: pd.Series,
    high_prices: pd.Series | None,
    low_prices: pd.Series | None,
    *,
    requested_sessions: int | None,
) -> dict[str, Any]:
    """Describe the available price path for one explicit lookback window."""
    prices = _numeric_series(close_prices).dropna()
    if requested_sessions is not None:
        if len(prices) < requested_sessions:
            return {
                "available": False,
                "required_sessions": requested_sessions,
                "available_sessions": len(prices),
            }
        prices = prices.tail(requested_sessions)

    high_basis = "forward_adjusted_intraday_high"
    highs = _numeric_series(high_prices).reindex(prices.index) if high_prices is not None else pd.Series(index=prices.index, dtype=float)
    highs = highs.where(highs >= prices, prices).fillna(prices)
    if high_prices is None or highs.eq(prices).all():
        high_basis = "forward_adjusted_close_fallback"

    low_basis = "forward_adjusted_intraday_low"
    lows = _numeric_series(low_prices).reindex(prices.index) if low_prices is not None else pd.Series(index=prices.index, dtype=float)
    lows = lows.where(lows <= prices, prices).fillna(prices)
    if low_prices is None or lows.eq(prices).all():
        low_basis = "forward_adjusted_close_fallback"

    historical_high = _finite_number(highs.max())
    historical_low = _finite_number(lows.min())
    peak_date = highs.idxmax() if historical_high is not None else None
    running_high = highs.cummax()
    drawdown = (prices / running_high) - 1
    first_price = _finite_number(prices.iloc[0])
    latest_price = _finite_number(prices.iloc[-1])
    observations = len(prices)
    years = (observations - 1) / TRADING_DAYS_PER_YEAR
    cagr = None
    if first_price is not None and latest_price is not None and first_price > 0 and years > 0:
        cagr = (latest_price / first_price) ** (1 / years) - 1
    annualized_log_trend, trend_r_squared = _linear_log_price_trend(prices)
    range_position = None
    if historical_high is not None and historical_low is not None and historical_high > historical_low and latest_price is not None:
        range_position = (latest_price - historical_low) / (historical_high - historical_low)

    return {
        "available": True,
        "observations": observations,
        "start_trade_date": pd.Timestamp(prices.index[0]).strftime("%Y-%m-%d"),
        "end_trade_date": pd.Timestamp(prices.index[-1]).strftime("%Y-%m-%d"),
        "start_close_qfq": first_price,
        "latest_close_qfq": latest_price,
        "total_return": ((latest_price / first_price) - 1) if first_price not in {None, 0} and latest_price is not None else None,
        "cagr": cagr,
        "annualized_log_trend": annualized_log_trend,
        "trend_r_squared": trend_r_squared,
        "price_path_label": _price_path_label(annualized_log_trend, trend_r_squared, observations),
        "historical_high_qfq": historical_high,
        "historical_high_trade_date": (
            pd.Timestamp(peak_date).strftime("%Y-%m-%d") if peak_date is not None else None
        ),
        "historical_high_basis": high_basis,
        "distance_to_historical_high": (
            (latest_price / historical_high) - 1
            if latest_price is not None and historical_high not in {None, 0}
            else None
        ),
        "historical_low_qfq": historical_low,
        "historical_low_basis": low_basis,
        "position_in_historical_range": range_position,
        "current_drawdown_from_running_high": _finite_number(drawdown.iloc[-1]),
        "maximum_drawdown": _finite_number(drawdown.min()),
    }


def summarize_historical_price_structure(indicators: pd.DataFrame) -> dict[str, Any]:
    """Expose long-run price context that a short-horizon indicator snapshot otherwise omits."""
    close_prices = indicators["close_qfq"] if "close_qfq" in indicators else pd.Series(dtype=float)
    high_prices = indicators["high_qfq"] if "high_qfq" in indicators else None
    low_prices = indicators["low_qfq"] if "low_qfq" in indicators else None
    available_prices = _numeric_series(close_prices).dropna()
    if available_prices.empty:
        return {
            "available_history": {"observations": 0},
            "periods": {},
        }

    periods = {
        "full_available_history": _summarize_price_path(
            available_prices,
            high_prices,
            low_prices,
            requested_sessions=None,
        )
    }
    for name, sessions in HISTORICAL_PRICE_WINDOWS.items():
        periods[name] = _summarize_price_path(
            available_prices,
            high_prices,
            low_prices,
            requested_sessions=sessions,
        )
    return {
        "available_history": {
            "observations": len(available_prices),
            "start_trade_date": pd.Timestamp(available_prices.index[0]).strftime("%Y-%m-%d"),
            "end_trade_date": pd.Timestamp(available_prices.index[-1]).strftime("%Y-%m-%d"),
        },
        "periods": periods,
        "usage_boundary": (
            "These are descriptive summaries of the stored forward-adjusted price path. "
            "Full available history begins at the earliest local SQLite observation, not necessarily the listing date; "
            "the path label is not a trading signal."
        ),
    }


def summarize_technical_indicators(
    indicators: pd.DataFrame,
    *,
    settings: TechnicalIndicatorSettings = TechnicalIndicatorSettings(),
    change_sessions: int = 5,
    cross_lookback_sessions: int = 10,
) -> dict[str, Any]:
    """Build a compact, descriptive snapshot for short-horizon research."""
    settings.validate()
    if indicators.empty:
        raise ValueError("cannot summarize an empty technical-indicator history")
    if change_sessions <= 0 or cross_lookback_sessions <= 0:
        raise ValueError("technical snapshot lookback windows must be greater than zero")

    latest = indicators.iloc[-1]

    def value(column: str) -> float | None:
        return _finite_number(latest.get(column))

    sma_short = value(f"sma_{settings.sma_short}")
    sma_long = value(f"sma_{settings.sma_long}")
    sma_alignment = None
    if sma_short is not None and sma_long is not None:
        sma_alignment = "short_above_long" if sma_short > sma_long else "short_below_or_equal_long"

    rsi_column = f"rsi_{settings.rsi_window}"
    rsi = value(rsi_column)
    if rsi is None:
        rsi_zone = None
    elif rsi <= 30:
        rsi_zone = "at_or_below_30"
    elif rsi >= 70:
        rsi_zone = "at_or_above_70"
    else:
        rsi_zone = "between_30_and_70"

    histogram = indicators["macd_histogram"] if "macd_histogram" in indicators else pd.Series(dtype=float)
    histogram_value = value("macd_histogram")
    if histogram_value is None:
        macd_position = None
    elif histogram_value > 0:
        macd_position = "above_signal"
    elif histogram_value < 0:
        macd_position = "below_signal"
    else:
        macd_position = "at_signal"

    percent_b = value(f"bollinger_percent_b_{settings.bollinger_window}")
    if percent_b is None:
        bollinger_location = None
    elif percent_b < 0:
        bollinger_location = "below_lower_band"
    elif percent_b > 1:
        bollinger_location = "above_upper_band"
    elif percent_b < 0.5:
        bollinger_location = "lower_half"
    else:
        bollinger_location = "upper_half"

    volume_ratio_column = f"volume_ratio_{settings.volume_window}d"
    volume_ratio = value(volume_ratio_column)
    if volume_ratio is None:
        volume_regime = None
    elif volume_ratio < 0.8:
        volume_regime = "below_recent_average"
    elif volume_ratio > 1.2:
        volume_regime = "above_recent_average"
    else:
        volume_regime = "near_recent_average"

    dimensions = {
        "trend": {
            "close_qfq": value("close_qfq"),
            f"return_{settings.sma_short}d": value(f"return_{settings.sma_short}d"),
            f"benchmark_return_{settings.sma_short}d": value(
                f"benchmark_return_{settings.sma_short}d"
            ),
            f"relative_return_{settings.sma_short}d": value(
                f"relative_return_{settings.sma_short}d"
            ),
            f"price_vs_sma_{settings.sma_short}": value(f"price_vs_sma_{settings.sma_short}"),
            f"price_vs_sma_{settings.sma_long}": value(f"price_vs_sma_{settings.sma_long}"),
            "sma_alignment": sma_alignment,
        },
        "momentum": {
            "macd_line": value(f"macd_{settings.macd_fast}_{settings.macd_slow}"),
            "macd_signal": value(f"macd_signal_{settings.macd_signal}"),
            "macd_histogram": histogram_value,
            f"macd_histogram_change_{change_sessions}d": _change_over_sessions(histogram, change_sessions),
            "macd_position": macd_position,
            f"last_macd_cross_within_{cross_lookback_sessions}d": _last_macd_cross(
                histogram,
                cross_lookback_sessions,
            ),
            rsi_column: rsi,
            f"rsi_change_{change_sessions}d": (
                _change_over_sessions(indicators[rsi_column], change_sessions)
                if rsi_column in indicators
                else None
            ),
            "rsi_zone": rsi_zone,
        },
        "risk_and_location": {
            f"volatility_{settings.sma_short}d_annualized": value(
                f"volatility_{settings.sma_short}d_annualized"
            ),
            f"bollinger_percent_b_{settings.bollinger_window}": percent_b,
            f"bollinger_bandwidth_{settings.bollinger_window}": value(
                f"bollinger_bandwidth_{settings.bollinger_window}"
            ),
            "bollinger_location": bollinger_location,
        },
        "participation": {
            volume_ratio_column: volume_ratio,
            f"price_volume_correlation_{settings.volume_window}d": value(
                f"price_volume_correlation_{settings.volume_window}d"
            ),
            f"up_volume_share_{settings.volume_window}d": value(
                f"up_volume_share_{settings.volume_window}d"
            ),
            "volume_regime": volume_regime,
        },
    }
    available_dimensions = [
        name
        for name, observations in dimensions.items()
        if any(item is not None for item in observations.values())
    ]
    return {
        "as_of_trade_date": pd.Timestamp(indicators.index[-1]).strftime("%Y-%m-%d"),
        "change_lookback_sessions": change_sessions,
        "cross_lookback_sessions": cross_lookback_sessions,
        "dimensions": dimensions,
        "available_dimensions": available_dimensions,
        "missing_dimensions": [name for name in dimensions if name not in available_dimensions],
        "historical_price_structure": summarize_historical_price_structure(indicators),
        "usage_boundary": (
            "These labels describe price, momentum, risk, participation, and historical price-path states. "
            "They are not a composite score or an automatic buy/sell signal."
        ),
    }
