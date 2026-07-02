#!/usr/bin/env python3
"""Technical and basic-fundamental A-share screening helpers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from market_data_store import DEFAULT_DB_PATH, load_daily_matrices


DEFAULT_WINDOWS = (5, 10, 15, 30, 60)


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


def calculate_metrics(
    prices: pd.Series,
    volumes: pd.Series,
    *,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    min_valid: int = 60,
) -> dict[str, float]:
    aligned_prices = pd.to_numeric(prices, errors="coerce")
    aligned_volumes = pd.to_numeric(volumes, errors="coerce").reindex(aligned_prices.index)
    valid_count = int(aligned_prices.notna().sum())
    total_count = int(len(aligned_prices))
    completeness = valid_count / total_count if total_count else 0.0

    result: dict[str, float] = {
        "completeness": float(completeness),
        "actual_window": float(total_count),
        "max_drawdown": 0.0,
        "sharpe_all": 0.0,
    }
    if total_count == 0 or valid_count < min_valid:
        return result

    filled_prices = aligned_prices.ffill()
    filled_volumes = aligned_volumes.ffill()
    returns = filled_prices.pct_change().dropna()
    result["max_drawdown"] = _max_drawdown(filled_prices)
    result["sharpe_all"] = _safe_sharpe(returns)

    for window in windows:
        price_window = filled_prices.tail(window)
        volume_window = filled_volumes.tail(window)
        moving_average = price_window.mean()
        volume_average = volume_window.mean()
        result[f"bias_{window}d"] = float(filled_prices.iloc[-1] / moving_average - 1) if moving_average else 0.0
        result[f"sharpe_{window}d"] = _safe_sharpe(returns.tail(window))
        result[f"vr_{window}d"] = float(filled_volumes.iloc[-1] / volume_average) if volume_average else 0.0

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


def build_screen(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    fundamentals: pd.DataFrame | None = None,
    *,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    recent_days: int = 10,
    min_valid: int = 60,
) -> pd.DataFrame:
    prices = prices.sort_index()
    volumes = volumes.sort_index()
    symbols = [symbol for symbol in prices.columns if symbol in volumes.columns]

    metric_rows: list[dict[str, float | str]] = []
    for symbol in symbols:
        metrics = calculate_metrics(prices[symbol], volumes[symbol], windows=windows, min_valid=min_valid)
        metric_rows.append({"ts_code": symbol, **metrics})

    metrics_frame = pd.DataFrame(metric_rows)
    returns_frame = recent_return_columns(prices[symbols], recent_days=recent_days)
    result = metrics_frame.merge(returns_frame, on="ts_code", how="left")

    if fundamentals is not None and not fundamentals.empty:
        result = fundamentals.merge(result, on="ts_code", how="inner")

    return result


def read_fundamentals_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def build_screen_from_database(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: Sequence[str] | None = None,
    fundamentals: pd.DataFrame | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    recent_days: int = 10,
    min_valid: int = 60,
) -> pd.DataFrame:
    prices, volumes = load_daily_matrices(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
    )
    return build_screen(
        prices,
        volumes,
        fundamentals,
        windows=windows,
        recent_days=recent_days,
        min_valid=min_valid,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an A-share technical/fundamental screening table.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, type=Path)
    parser.add_argument("--start-date", help="Optional start date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional end date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", help="Optional ts_code list. Defaults to all symbols in the database.")
    parser.add_argument("--fundamentals", type=Path, help="Optional fundamentals table keyed by ts_code")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--recent-days", type=int, default=10)
    parser.add_argument("--min-valid", type=int, default=60)
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
        recent_days=args.recent_days,
        min_valid=args.min_valid,
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
