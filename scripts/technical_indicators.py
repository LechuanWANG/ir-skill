"""Deterministic technical indicators derived from locally stored market data."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any

import pandas as pd


TRADING_DAYS_PER_YEAR = 252


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
    settings: TechnicalIndicatorSettings = TechnicalIndicatorSettings(),
) -> pd.DataFrame:
    """Calculate price and volume indicators for one forward-adjusted price series."""
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
    result[f"sma_{settings.sma_short}"] = rolling_short
    result[f"sma_{settings.sma_long}"] = rolling_long
    result[f"price_vs_sma_{settings.sma_short}"] = (prices / rolling_short) - 1
    result[f"price_vs_sma_{settings.sma_long}"] = (prices / rolling_long) - 1
    result[f"return_{settings.sma_short}d"] = prices.pct_change(settings.sma_short, fill_method=None)
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
        "usage_boundary": (
            "These labels describe price, momentum, risk, and participation states. "
            "They are not a composite score or an automatic buy/sell signal."
        ),
    }
