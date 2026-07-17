"""Deterministic technical indicators derived from locally stored market data."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

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
