#!/usr/bin/env python3
"""Stage-N technical, liquidity and overheat checks for known candidates."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_daily_basic_history,
    load_daily_matrices,
    load_research_observations,
)


_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from investment_research.overheat import assess_relative_overheat, prepare_adjusted_bars


DEFAULT_WINDOWS = (5, 10, 20, 30, 60, 120, 250, 500, 750)
LONG_REGIME_MIN_VALID = 500


def _safe_sharpe(returns: pd.Series) -> float:
    clean = returns.dropna()
    if len(clean) < 2:
        return 0.0
    std = clean.std()
    if pd.isna(std) or std == 0:
        return 0.0
    return float((clean.mean() / std) * np.sqrt(252))


def _max_drawdown(prices: pd.Series) -> float:
    clean = prices.dropna()
    if len(clean) < 2:
        return 0.0
    returns = clean.pct_change().dropna()
    cumulative = (1 + returns).cumprod()
    drawdown = 1 - cumulative / cumulative.cummax()
    return float(drawdown.max()) if not drawdown.empty else 0.0


def _efficiency_ratio(prices: pd.Series) -> float:
    clean = prices.dropna()
    if len(clean) < 2:
        return float("nan")
    travelled = float(clean.diff().abs().sum())
    if travelled == 0:
        return 0.0
    return float(abs(clean.iloc[-1] - clean.iloc[0]) / travelled)


def _annualized_return(prices: pd.Series) -> float:
    clean = prices.dropna()
    if len(clean) < 2 or clean.iloc[0] <= 0:
        return float("nan")
    years = (len(clean) - 1) / 252
    if years <= 0:
        return float("nan")
    return float((clean.iloc[-1] / clean.iloc[0]) ** (1 / years) - 1)


def _annualized_log_slope(prices: pd.Series) -> float:
    clean = prices.dropna()
    if len(clean) < 2 or (clean <= 0).any():
        return float("nan")
    slope = np.polyfit(np.arange(len(clean)), np.log(clean.to_numpy(dtype="float64")), 1)[0]
    return float(np.expm1(slope * 252))


def _range_occupancy(prices: pd.Series, band: float = 0.15) -> float:
    clean = prices.dropna()
    if clean.empty:
        return float("nan")
    median = float(clean.median())
    if median <= 0:
        return float("nan")
    return float(((clean / median - 1).abs() <= band).mean())


def _breakout_failure_rate(
    prices: pd.Series,
    *,
    lookback: int = 60,
    confirmation: int = 20,
) -> float:
    clean = prices.dropna().reset_index(drop=True)
    if len(clean) < lookback + confirmation + 1:
        return float("nan")
    failures = 0
    breakouts = 0
    for index in range(lookback, len(clean) - confirmation):
        prior_high = float(clean.iloc[index - lookback : index].max())
        breakout_price = float(clean.iloc[index])
        if breakout_price <= prior_high:
            continue
        breakouts += 1
        if float(clean.iloc[index + 1 : index + confirmation + 1].min()) < prior_high:
            failures += 1
    return float(failures / breakouts) if breakouts else 0.0


def _classify_price_regime(
    prices: pd.Series,
    *,
    min_valid: int = LONG_REGIME_MIN_VALID,
) -> str:
    clean = prices.dropna()
    if len(clean) < min_valid:
        return "insufficient_history"
    window = clean.tail(min(750, len(clean)))
    annualized_return = _annualized_return(window)
    slope = _annualized_log_slope(window)
    efficiency = _efficiency_ratio(window)
    occupancy = _range_occupancy(window)
    if efficiency <= 0.18 and occupancy >= 0.60:
        return "range_bound"
    if annualized_return >= 0.10 and slope >= 0.08:
        return "uptrend"
    if annualized_return <= -0.10 and slope <= -0.08:
        return "downtrend"
    return "transitional"


def calculate_metrics(
    prices: pd.Series,
    volumes: pd.Series,
    *,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    min_valid: int = 60,
    long_regime_min_valid: int = LONG_REGIME_MIN_VALID,
    annual_return_hurdle: float = 0.08,
) -> dict[str, float | str]:
    aligned_prices = pd.to_numeric(prices, errors="coerce")
    aligned_volumes = pd.to_numeric(volumes, errors="coerce").reindex(aligned_prices.index)
    valid_count = int(aligned_prices.notna().sum())
    total_count = int(len(aligned_prices))
    completeness = valid_count / total_count if total_count else 0.0

    result: dict[str, float] = {
        "completeness": float(completeness),
        "actual_window": float(valid_count),
        "max_drawdown": 0.0,
        "sharpe_all": 0.0,
        "long_history_status": "insufficient",
        "price_regime": "insufficient_history",
        "opportunity_cost_flag": "unknown",
        "opportunity_cost_reason": "long-term adjusted-price history below minimum",
    }
    if total_count == 0 or valid_count < min_valid:
        return result

    filled_prices = aligned_prices.ffill()
    filled_volumes = aligned_volumes.ffill()
    returns = filled_prices.pct_change().dropna()
    result["max_drawdown"] = _max_drawdown(filled_prices)
    result["sharpe_all"] = _safe_sharpe(returns)

    for window in windows:
        if len(filled_prices) < window:
            result[f"return_{window}d"] = float("nan")
            result[f"bias_{window}d"] = float("nan")
            result[f"sharpe_{window}d"] = float("nan")
            result[f"vr_{window}d"] = float("nan")
            result[f"realized_volatility_{window}d"] = float("nan")
            continue
        price_window = filled_prices.tail(window)
        volume_window = filled_volumes.tail(window)
        moving_average = price_window.mean()
        volume_average = volume_window.mean()
        result[f"return_{window}d"] = float(price_window.iloc[-1] / price_window.iloc[0] - 1)
        result[f"bias_{window}d"] = float(filled_prices.iloc[-1] / moving_average - 1) if moving_average else 0.0
        result[f"sharpe_{window}d"] = _safe_sharpe(returns.tail(window))
        result[f"vr_{window}d"] = float(filled_volumes.iloc[-1] / volume_average) if volume_average else 0.0
        result[f"realized_volatility_{window}d"] = float(returns.tail(window).std() * np.sqrt(252))

    if valid_count >= long_regime_min_valid:
        long_window = filled_prices.tail(min(750, valid_count))
        result["long_history_status"] = "sufficient"
        result["long_window_days"] = float(len(long_window))
        result["price_regime"] = _classify_price_regime(
            long_window,
            min_valid=long_regime_min_valid,
        )
        result["annualized_adjusted_return_long"] = _annualized_return(long_window)
        result["long_efficiency_ratio"] = _efficiency_ratio(long_window)
        result["long_range_occupancy_15pct"] = _range_occupancy(long_window)
        result["long_range_width"] = float(long_window.max() / long_window.min() - 1)
        result["ma250_annualized_slope"] = _annualized_log_slope(long_window.tail(250))
        result["breakout_failure_rate"] = _breakout_failure_rate(long_window)
        opportunity_flag = bool(result["annualized_adjusted_return_long"] < annual_return_hurdle)
        result["opportunity_cost_flag"] = "flagged" if opportunity_flag else "clear"
        result["opportunity_cost_reason"] = (
            f"annualized adjusted return below {annual_return_hurdle:.1%} hurdle"
            if opportunity_flag
            else f"annualized adjusted return clears {annual_return_hurdle:.1%} hurdle"
        )

    return result


def recent_return_columns(prices: pd.DataFrame, recent_days: int = 10) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame(index=prices.columns)
    starts = prices.tail(recent_days)
    latest = prices.ffill().iloc[-1]
    returns = (latest / starts) - 1
    output = returns.T
    output.columns = [f"return_from_{pd.Timestamp(date).date().isoformat()}" for date in output.columns]
    output.index.name = "ts_code"
    return output.reset_index()


def _relative_return(
    stock_prices: pd.Series,
    benchmark_prices: pd.Series,
    window: int,
) -> float:
    aligned = pd.concat(
        [
            pd.to_numeric(stock_prices, errors="coerce").rename("stock"),
            pd.to_numeric(benchmark_prices, errors="coerce").rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < window:
        return float("nan")
    recent = aligned.tail(window)
    stock_return = float(recent["stock"].iloc[-1] / recent["stock"].iloc[0] - 1)
    benchmark_return = float(recent["benchmark"].iloc[-1] / recent["benchmark"].iloc[0] - 1)
    return stock_return - benchmark_return


def _valuation_and_shareholder_context(
    symbol: str,
    daily_basic_history: pd.DataFrame | None,
    dividends: pd.DataFrame | None,
    *,
    long_regime_min_valid: int,
) -> dict[str, float | str]:
    result: dict[str, float | str] = {
        "unadjusted_price_return_3y": float("nan"),
        "cash_dividend_per_share_3y": float("nan"),
        "total_shareholder_return_3y": float("nan"),
        "pe_ttm_change_3y": float("nan"),
        "shareholder_return_method": "insufficient_history",
    }
    if daily_basic_history is None or daily_basic_history.empty:
        return result
    symbol_history = daily_basic_history.loc[
        daily_basic_history["ts_code"].astype(str) == symbol
    ].copy()
    if symbol_history.empty or "close" not in symbol_history.columns:
        return result
    symbol_history["trade_date"] = pd.to_datetime(symbol_history["trade_date"], errors="coerce")
    symbol_history["close"] = pd.to_numeric(symbol_history["close"], errors="coerce")
    symbol_history = symbol_history.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
    if len(symbol_history) < long_regime_min_valid:
        return result
    window = symbol_history.tail(min(750, len(symbol_history)))
    start_price = float(window["close"].iloc[0])
    end_price = float(window["close"].iloc[-1])
    cash_dividend = 0.0
    if dividends is not None and not dividends.empty:
        symbol_dividends = dividends.loc[dividends["ts_code"].astype(str) == symbol].copy()
        date_column = "pay_date" if "pay_date" in symbol_dividends.columns else "event_date"
        if date_column in symbol_dividends.columns and "cash_div" in symbol_dividends.columns:
            symbol_dividends[date_column] = pd.to_datetime(symbol_dividends[date_column], errors="coerce")
            symbol_dividends["cash_div"] = pd.to_numeric(symbol_dividends["cash_div"], errors="coerce")
            if "div_proc" in symbol_dividends.columns:
                symbol_dividends = symbol_dividends.loc[
                    symbol_dividends["div_proc"].astype(str).eq("实施")
                ]
            symbol_dividends = symbol_dividends.loc[
                symbol_dividends[date_column].between(
                    window["trade_date"].iloc[0],
                    window["trade_date"].iloc[-1],
                    inclusive="both",
                )
            ]
            cash_dividend = float(symbol_dividends["cash_div"].fillna(0).sum())
    result["unadjusted_price_return_3y"] = float(end_price / start_price - 1)
    result["cash_dividend_per_share_3y"] = cash_dividend
    result["total_shareholder_return_3y"] = float(
        (end_price + cash_dividend) / start_price - 1
    )
    result["shareholder_return_method"] = "simple_unadjusted_close_plus_cash_dividend"
    if "pe_ttm" in window.columns:
        pe_values = pd.to_numeric(window["pe_ttm"], errors="coerce").dropna()
        if len(pe_values) >= 2 and pe_values.iloc[0] != 0:
            result["pe_ttm_change_3y"] = float(pe_values.iloc[-1] / pe_values.iloc[0] - 1)
    return result


def _price_regime_interpretation(row: pd.Series) -> str:
    regime = str(row.get("price_regime") or "not_assessed")
    if regime != "range_bound":
        return regime
    growth = pd.to_numeric(pd.Series([row.get("netprofit_yoy")]), errors="coerce").iloc[0]
    cash_quality = pd.to_numeric(pd.Series([row.get("ocf_to_or")]), errors="coerce").iloc[0]
    dividend_yield = pd.to_numeric(pd.Series([row.get("dv_ttm")]), errors="coerce").iloc[0]
    if pd.notna(growth) and growth > 0 and pd.notna(cash_quality) and cash_quality > 0:
        if pd.notna(dividend_yield) and dividend_yield >= 2:
            return "range_bound_value_candidate"
        return "range_bound_neutral"
    if (pd.notna(growth) and growth < 0) or (pd.notna(cash_quality) and cash_quality < 0):
        return "range_bound_value_trap_risk"
    return "range_bound_neutral"


def build_screen(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    fundamentals: pd.DataFrame | None = None,
    *,
    market_benchmark: pd.Series | None = None,
    industry_benchmarks: Mapping[str, pd.Series] | None = None,
    daily_basic_history: pd.DataFrame | None = None,
    dividends: pd.DataFrame | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    recent_days: int = 10,
    min_valid: int = 60,
    long_regime_min_valid: int = LONG_REGIME_MIN_VALID,
    annual_return_hurdle: float = 0.08,
) -> pd.DataFrame:
    prices = prices.sort_index()
    volumes = volumes.sort_index()
    symbols = [symbol for symbol in prices.columns if symbol in volumes.columns]

    metric_rows: list[dict[str, float | str]] = []
    for symbol in symbols:
        metrics = calculate_metrics(
            prices[symbol],
            volumes[symbol],
            windows=windows,
            min_valid=min_valid,
            long_regime_min_valid=long_regime_min_valid,
            annual_return_hurdle=annual_return_hurdle,
        )
        if market_benchmark is not None:
            for window in (20, 60, 250, 500, 750):
                metrics[f"relative_return_market_{window}d"] = _relative_return(
                    prices[symbol],
                    market_benchmark,
                    window,
                )
        if industry_benchmarks and symbol in industry_benchmarks:
            for window in (20, 60, 250, 500, 750):
                metrics[f"relative_return_industry_{window}d"] = _relative_return(
                    prices[symbol],
                    industry_benchmarks[symbol],
                    window,
                )
        metrics.update(
            _valuation_and_shareholder_context(
                symbol,
                daily_basic_history,
                dividends,
                long_regime_min_valid=long_regime_min_valid,
            )
        )
        metric_rows.append({"ts_code": symbol, **metrics})

    metrics_frame = pd.DataFrame(metric_rows)
    returns_frame = recent_return_columns(prices[symbols], recent_days=recent_days)
    result = metrics_frame.merge(returns_frame, on="ts_code", how="left")

    if fundamentals is not None and not fundamentals.empty:
        result = fundamentals.merge(result, on="ts_code", how="inner")

    if not result.empty:
        result["price_regime_interpretation"] = result.apply(
            _price_regime_interpretation,
            axis=1,
        )
        shareholder_return = pd.to_numeric(
            result.get("total_shareholder_return_3y"), errors="coerce"
        )
        if "long_window_days" in result.columns:
            years = pd.to_numeric(result["long_window_days"], errors="coerce") / 252
            annualized_total_return = (1 + shareholder_return).pow(1 / years) - 1
            result["annualized_total_shareholder_return_3y"] = annualized_total_return
            has_total_return = annualized_total_return.notna()
            result.loc[has_total_return, "opportunity_cost_flag"] = np.where(
                annualized_total_return.loc[has_total_return] < annual_return_hurdle,
                "flagged",
                "clear",
            )
            result.loc[has_total_return, "opportunity_cost_reason"] = np.where(
                annualized_total_return.loc[has_total_return] < annual_return_hurdle,
                f"annualized total shareholder return below {annual_return_hurdle:.1%} hurdle",
                f"annualized total shareholder return clears {annual_return_hurdle:.1%} hurdle",
            )

    return result


def read_fundamentals_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def _load_index_benchmark(
    *,
    db_path: Path,
    index_code: str | None,
    start_date: str | None,
    end_date: str | None,
) -> pd.Series | None:
    if not index_code:
        return None
    try:
        frame = load_research_observations(
            db_path=db_path,
            dataset="index_daily",
            symbols=[index_code],
            start_date=start_date,
            end_date=end_date,
            available_as_of=end_date,
            limit=5000,
        )
    except (FileNotFoundError, sqlite3.DatabaseError):
        return None
    if frame.empty or "close" not in frame.columns:
        return None
    date_column = "trade_date" if "trade_date" in frame.columns else "event_date"
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame["close"], errors="coerce")
    benchmark = pd.Series(values.to_numpy(), index=dates, name=index_code).dropna().sort_index()
    return benchmark[~benchmark.index.duplicated(keep="last")]


def build_screen_from_database(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: Sequence[str] | None = None,
    fundamentals: pd.DataFrame | None = None,
    market_benchmark_code: str | None = "000300.SH",
    windows: Sequence[int] = DEFAULT_WINDOWS,
    recent_days: int = 10,
    min_valid: int = 60,
    long_regime_min_valid: int = LONG_REGIME_MIN_VALID,
    annual_return_hurdle: float = 0.08,
) -> pd.DataFrame:
    prices, volumes = load_daily_matrices(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
    )
    if prices.empty:
        return pd.DataFrame()
    resolved_as_of = end_date or pd.Timestamp(prices.index.max()).strftime("%Y%m%d")
    daily_basic_history = load_daily_basic_history(
        db_path=db_path,
        as_of=resolved_as_of,
        symbols=symbols,
    )
    try:
        dividends = load_research_observations(
            db_path=db_path,
            dataset="dividend",
            symbols=symbols,
            available_as_of=resolved_as_of,
            limit=5000,
        )
    except (FileNotFoundError, sqlite3.DatabaseError):
        dividends = pd.DataFrame()
    market_benchmark = _load_index_benchmark(
        db_path=db_path,
        index_code=market_benchmark_code,
        start_date=start_date,
        end_date=resolved_as_of,
    )
    return build_screen(
        prices,
        volumes,
        fundamentals,
        market_benchmark=market_benchmark,
        daily_basic_history=daily_basic_history,
        dividends=dividends,
        windows=windows,
        recent_days=recent_days,
        min_valid=min_valid,
        long_regime_min_valid=long_regime_min_valid,
        annual_return_hurdle=annual_return_hurdle,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assess Stage-N technical, liquidity and overheat context for Stage-L candidates."
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, type=Path)
    parser.add_argument("--start-date", help="Optional start date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional end date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="Stage-L shortlisted ts_code values; this command cannot run as a full-market first-pass screen.",
    )
    parser.add_argument("--fundamentals", type=Path, help="Optional fundamentals table keyed by ts_code")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--recent-days", type=int, default=10)
    parser.add_argument("--min-valid", type=int, default=60)
    parser.add_argument("--long-regime-min-valid", type=int, default=LONG_REGIME_MIN_VALID)
    parser.add_argument("--annual-return-hurdle", type=float, default=0.08)
    parser.add_argument("--market-benchmark-code", default="000300.SH")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fundamentals = read_fundamentals_table(args.fundamentals) if args.fundamentals else None
    screen = build_screen_from_database(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=args.symbols,
        fundamentals=fundamentals,
        market_benchmark_code=args.market_benchmark_code,
        recent_days=args.recent_days,
        min_valid=args.min_valid,
        long_regime_min_valid=args.long_regime_min_valid,
        annual_return_hurdle=args.annual_return_hurdle,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == ".xlsx":
        screen.to_excel(args.output, index=False)
    else:
        screen.to_csv(args.output, index=False)
    print(f"saved screen: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
