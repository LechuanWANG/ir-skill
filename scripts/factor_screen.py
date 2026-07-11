#!/usr/bin/env python3
"""Explicit deterministic quantitative A-share baseline.

This optional branch narrows the universe with technical and fundamental factors.
It is never the default candidate-discovery path and does not make buy/sell decisions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from market_data_store import DEFAULT_DB_PATH, load_daily_basic_history, load_daily_matrices, load_factor_inputs
from technical_screen import build_screen


@dataclass(frozen=True)
class Preset:
    weights: dict[str, float]
    overext_strength: float = 1.0
    valuation_penalty: float = 10.0


@dataclass(frozen=True)
class GateConfig:
    min_completeness: float = 0.98
    min_window: int = 100
    min_total_mv: float = 500_000
    min_circ_mv: float = 200_000
    max_drawdown: float = 0.45
    min_roe_dt: float = 2.0
    min_netprofit_yoy: float = -20.0
    max_debt_to_assets: float = 75.0
    min_bias_60d: float = -0.20
    max_bias_60d: float = 0.80
    min_vr_60d: float = 0.40
    max_vr_60d: float = 4.00


PRESETS = {
    "balanced": Preset({"trend": 0.20, "value": 0.30, "quality": 0.25, "growth": 0.25}, 1.0, 10.0),
    "value": Preset({"trend": 0.10, "value": 0.45, "quality": 0.30, "growth": 0.15}, 1.0, 15.0),
    "growth": Preset({"trend": 0.20, "value": 0.15, "quality": 0.25, "growth": 0.40}, 1.0, 5.0),
    "prosperity": Preset({"trend": 0.30, "value": 0.10, "quality": 0.20, "growth": 0.40}, 1.25, 5.0),
}

OUTPUT_COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "market",
    "candidate_source",
    "close",
    "total_mv_100m",
    "pe_ttm",
    "pb",
    "pe_pctl_ind",
    "pb_pctl_hist",
    "roe_dt",
    "netprofit_yoy",
    "or_yoy",
    "debt_to_assets",
    "gross_margin",
    "mom_12_1",
    "sharpe_60d",
    "bias_60d",
    "vr_60d",
    "max_drawdown",
    "trend_score",
    "value_score",
    "quality_score",
    "growth_score",
    "overext_penalty",
    "valuation_pctl_penalty",
    "risk_penalty",
    "base_factor_score",
    "composite_score",
    "catalyst_score",
    "research_priority_overlay",
    "research_priority_rank",
    "priority_reason",
    "catalyst_source",
    "catalyst_time",
    "catalyst_signal_id",
    "style_preset",
    "追涨风险",
    "pass_reason",
    "disqualify_risk",
    "long_term_status",
    "next_step",
    "as_of",
]


def _to_numeric(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = np.nan
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def rank_percentile(values: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(0.5, index=values.index, dtype="float64")
    ranked = numeric.rank(method="average", pct=True, ascending=higher_is_better)
    return ranked.fillna(0.5).astype("float64")


def industry_percentile(
    frame: pd.DataFrame,
    column: str,
    *,
    higher_is_better: bool = True,
    min_group_size: int = 8,
) -> pd.Series:
    global_scores = rank_percentile(frame[column], higher_is_better=higher_is_better)
    if "industry" not in frame.columns:
        return global_scores

    scores = global_scores.copy()
    for _, group in frame.groupby("industry", dropna=False):
        if len(group) >= min_group_size:
            scores.loc[group.index] = rank_percentile(group[column], higher_is_better=higher_is_better)
    return scores.fillna(0.5)


def compute_mom_12_1(prices: pd.Series, *, lookback: int = 250, skip: int = 20) -> float:
    clean = pd.to_numeric(prices, errors="coerce").ffill().dropna()
    if len(clean) <= skip + 1:
        return 0.0
    end_pos = len(clean) - skip - 1
    start_pos = max(0, end_pos - lookback)
    if end_pos <= start_pos or clean.iloc[start_pos] == 0:
        return 0.0
    return float(clean.iloc[end_pos] / clean.iloc[start_pos] - 1)


def _compute_momentum_frame(prices: pd.DataFrame) -> pd.DataFrame:
    rows = [{"ts_code": str(symbol), "mom_12_1": compute_mom_12_1(prices[symbol])} for symbol in prices.columns]
    return pd.DataFrame(rows)


def apply_hard_gates(frame: pd.DataFrame, config: GateConfig = GateConfig()) -> tuple[pd.DataFrame, list[dict[str, int | str]]]:
    current = frame.copy()
    log: list[dict[str, int | str]] = []

    def apply(rule: str, mask: pd.Series) -> None:
        nonlocal current
        before = len(current)
        current = current.loc[mask.reindex(current.index).fillna(False)].copy()
        after = len(current)
        log.append({"rule": rule, "before": before, "after": after, "removed": before - after})

    numeric_columns = [
        "completeness",
        "actual_window",
        "total_mv",
        "circ_mv",
        "max_drawdown",
        "roe_dt",
        "netprofit_yoy",
        "debt_to_assets",
        "bias_60d",
        "vr_60d",
        "pe_ttm",
        "pb",
    ]
    current = _to_numeric(current, numeric_columns)

    apply("数据完整度", (current["completeness"] >= config.min_completeness) & (current["actual_window"] >= config.min_window))
    names = current.get("name", pd.Series("", index=current.index)).astype(str)
    apply("ST/退市", ~names.str.contains(r"\*?ST|退", case=False, regex=True, na=False))
    apply("有当日估值", current[["pe_ttm", "pb", "total_mv", "circ_mv"]].notna().all(axis=1))
    apply("市值/流动性", (current["total_mv"] >= config.min_total_mv) & (current["circ_mv"] >= config.min_circ_mv))
    apply("回撤", current["max_drawdown"] <= config.max_drawdown)
    apply("有最近财报", current[["roe_dt", "netprofit_yoy", "debt_to_assets"]].notna().all(axis=1))
    apply("盈利质量", current["roe_dt"] >= config.min_roe_dt)
    apply("利润趋势", current["netprofit_yoy"] >= config.min_netprofit_yoy)
    apply("杠杆", current["debt_to_assets"] <= config.max_debt_to_assets)
    apply(
        "过热硬阈",
        current["bias_60d"].between(config.min_bias_60d, config.max_bias_60d)
        & current["vr_60d"].between(config.min_vr_60d, config.max_vr_60d),
    )
    apply("估值硬阈", (current["pe_ttm"] > 0) & (current["pb"] > 0))
    return current.reset_index(drop=True), log


def _mean_scores(scores: Sequence[pd.Series]) -> pd.Series:
    if not scores:
        raise ValueError("scores must not be empty")
    return pd.concat(scores, axis=1).mean(axis=1).fillna(0.5).clip(0, 1)


def _historical_percentile(
    current: pd.DataFrame,
    history: pd.DataFrame | None,
    column: str,
    fallback: pd.Series,
) -> pd.Series:
    if history is None or history.empty or column not in history.columns:
        return fallback
    values = []
    hist = history[["ts_code", column]].copy()
    hist[column] = pd.to_numeric(hist[column], errors="coerce")
    grouped = hist.dropna(subset=[column]).groupby("ts_code")
    for _, row in current.iterrows():
        ts_code = row["ts_code"]
        current_value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
        if pd.isna(current_value) or ts_code not in grouped.groups:
            values.append(float(fallback.loc[row.name]))
            continue
        series = grouped.get_group(ts_code)[column]
        combined = pd.concat([series, pd.Series([current_value])], ignore_index=True)
        values.append(float(combined.rank(pct=True).iloc[-1]))
    return pd.Series(values, index=current.index, dtype="float64").fillna(fallback)


def _penalty_overextension(frame: pd.DataFrame, strength: float) -> pd.Series:
    bias = pd.to_numeric(frame["bias_60d"], errors="coerce").fillna(0)
    vr = pd.to_numeric(frame["vr_60d"], errors="coerce").fillna(1)
    bias_penalty = ((bias - 0.30) / 0.50 * 15.0).clip(lower=0, upper=15)
    volume_penalty = ((vr - 2.50) / 1.50 * 5.0).clip(lower=0, upper=5)
    return (bias_penalty + volume_penalty).clip(upper=15) * strength


def _penalty_risk(frame: pd.DataFrame) -> pd.Series:
    drawdown = pd.to_numeric(frame["max_drawdown"], errors="coerce").fillna(0)
    return ((drawdown - 0.25) / 0.20 * 10.0).clip(lower=0, upper=10)


def _ensure_catalyst(frame: pd.DataFrame, catalyst: pd.DataFrame | None, with_catalyst: bool) -> pd.DataFrame:
    result = frame.copy()
    catalyst_output_columns = [
        "catalyst_score",
        "catalyst_source",
        "catalyst_time",
        "catalyst_signal_id",
        "research_priority_overlay",
        "priority_reason",
        "_catalyst_present",
    ]
    result = result.drop(columns=[column for column in catalyst_output_columns if column in result.columns])
    if with_catalyst and catalyst is not None and not catalyst.empty:
        required_columns = {"ts_code", "catalyst_score"}
        missing_columns = sorted(required_columns - set(catalyst.columns))
        if missing_columns:
            raise ValueError(f"Catalyst input missing required columns: {', '.join(missing_columns)}")

        metadata_columns = ["catalyst_source", "catalyst_time", "catalyst_signal_id"]
        catalyst_frame = catalyst[["ts_code", "catalyst_score"]].copy()
        for column in metadata_columns:
            catalyst_frame[column] = catalyst[column] if column in catalyst.columns else pd.NA

        numeric_score = pd.to_numeric(catalyst_frame["catalyst_score"], errors="coerce")
        invalid_score = catalyst_frame["catalyst_score"].notna() & numeric_score.isna()
        if invalid_score.any():
            raise ValueError("Catalyst input contains non-numeric catalyst_score values")
        catalyst_frame["catalyst_score"] = numeric_score.fillna(0.0).clip(0, 1)
        catalyst_frame["ts_code"] = catalyst_frame["ts_code"].astype(str)
        catalyst_frame = (
            catalyst_frame.sort_values("catalyst_score", ascending=False, kind="stable")
            .drop_duplicates("ts_code", keep="first")
            .reset_index(drop=True)
        )
        catalyst_frame["_catalyst_present"] = True
        result["ts_code"] = result["ts_code"].astype(str)
        result = result.merge(catalyst_frame, on="ts_code", how="left", validate="many_to_one")

    for column in ["catalyst_source", "catalyst_time", "catalyst_signal_id"]:
        if column not in result.columns:
            result[column] = pd.NA
    if "catalyst_score" not in result.columns:
        result["catalyst_score"] = 0.0
    result["catalyst_score"] = pd.to_numeric(result["catalyst_score"], errors="coerce").fillna(0.0).clip(0, 1)
    if "_catalyst_present" not in result.columns:
        result["_catalyst_present"] = False
    result["_catalyst_present"] = result["_catalyst_present"].fillna(False).astype(bool)
    result["research_priority_overlay"] = result["catalyst_score"] if with_catalyst else 0.0

    def priority_reason(row: pd.Series) -> str:
        if not with_catalyst:
            return "baseline_only"
        if not row["_catalyst_present"]:
            return "no_catalyst_signal"
        details = [f"catalyst_score={row['catalyst_score']:.2f}"]
        for column in ["catalyst_source", "catalyst_time", "catalyst_signal_id"]:
            value = row.get(column)
            if pd.notna(value) and str(value).strip():
                details.append(f"{column}={value}")
        return "; ".join(details)

    result["priority_reason"] = result.apply(priority_reason, axis=1)
    return result


def score_candidates(
    frame: pd.DataFrame,
    *,
    preset: str = "balanced",
    daily_basic_history: pd.DataFrame | None = None,
    with_catalyst: bool = False,
    catalyst: pd.DataFrame | None = None,
    min_industry_size: int = 8,
) -> pd.DataFrame:
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    preset_config = PRESETS[preset]
    result = frame.copy().reset_index(drop=True)
    numeric_columns = [
        "close",
        "total_mv",
        "circ_mv",
        "pe_ttm",
        "pb",
        "ps_ttm",
        "dv_ttm",
        "roe_dt",
        "netprofit_margin",
        "grossprofit_margin",
        "netprofit_yoy",
        "or_yoy",
        "debt_to_assets",
        "ocf_to_or",
        "mom_12_1",
        "sharpe_60d",
        "bias_60d",
        "vr_60d",
        "max_drawdown",
    ]
    missing_map = {
        index: [column for column in numeric_columns if column in result.columns and pd.isna(row.get(column))]
        for index, row in result.iterrows()
    }
    result = _to_numeric(result, numeric_columns)
    result = _ensure_catalyst(result, catalyst, with_catalyst)

    result["pe_pctl_ind"] = industry_percentile(result, "pe_ttm", higher_is_better=True, min_group_size=min_industry_size)
    result["pb_pctl_ind"] = industry_percentile(result, "pb", higher_is_better=True, min_group_size=min_industry_size)
    result["ps_pctl_ind"] = industry_percentile(result, "ps_ttm", higher_is_better=True, min_group_size=min_industry_size)
    result["pb_pctl_hist"] = _historical_percentile(result, daily_basic_history, "pb", result["pb_pctl_ind"])
    result["pe_pctl_hist"] = _historical_percentile(result, daily_basic_history, "pe_ttm", result["pe_pctl_ind"])

    trend_volume = (1 - ((result["vr_60d"] - 1.5).abs() / 2.5)).clip(0, 1).fillna(0.5)
    result["trend_score"] = _mean_scores(
        [
            rank_percentile(result["mom_12_1"], higher_is_better=True),
            rank_percentile(result["sharpe_60d"], higher_is_better=True),
            trend_volume,
        ]
    )
    result["value_score"] = _mean_scores(
        [
            1 - result["pe_pctl_ind"],
            1 - result["pb_pctl_ind"],
            1 - result["ps_pctl_ind"],
            industry_percentile(result, "dv_ttm", higher_is_better=True, min_group_size=min_industry_size),
        ]
    )
    result["quality_score"] = _mean_scores(
        [
            rank_percentile(result["roe_dt"], higher_is_better=True),
            industry_percentile(result, "netprofit_margin", higher_is_better=True, min_group_size=min_industry_size),
            industry_percentile(result, "grossprofit_margin", higher_is_better=True, min_group_size=min_industry_size),
            rank_percentile(result["debt_to_assets"], higher_is_better=False),
            rank_percentile(result["ocf_to_or"], higher_is_better=True),
        ]
    )
    raw_growth = _mean_scores(
        [
            rank_percentile(result["netprofit_yoy"], higher_is_better=True),
            rank_percentile(result["or_yoy"], higher_is_better=True),
        ]
    )
    result["growth_score"] = np.where(result["quality_score"] < 0.4, raw_growth * 0.8, raw_growth)

    result["overext_penalty"] = _penalty_overextension(result, preset_config.overext_strength)
    result["risk_penalty"] = _penalty_risk(result)
    unsupported_expensive = (result["pe_pctl_ind"] > 0.90) & (result["growth_score"] < 0.70)
    result["valuation_pctl_penalty"] = np.where(unsupported_expensive, preset_config.valuation_penalty, 0.0)

    weighted = sum(result[f"{factor}_score"] * weight for factor, weight in preset_config.weights.items())
    result["base_factor_score"] = (weighted * 100).round(4)
    result["composite_score"] = (
        result["base_factor_score"]
        - result["overext_penalty"]
        - result["valuation_pctl_penalty"]
        - result["risk_penalty"]
    ).round(4)
    result["style_preset"] = preset
    result["追涨风险"] = np.where((result["overext_penalty"] > 0) | (result["valuation_pctl_penalty"] > 0), "是", "否")
    result["total_mv_100m"] = result["total_mv"] / 10_000
    result["gross_margin"] = result["grossprofit_margin"]

    pass_reasons = []
    risk_reasons = []
    for index, row in result.iterrows():
        missing = missing_map.get(index, [])
        reason = (
            f"trend={row['trend_score']:.2f}; value={row['value_score']:.2f}; "
            f"quality={row['quality_score']:.2f}; growth={row['growth_score']:.2f}"
        )
        if missing:
            reason += "; missing neutralized: " + ",".join(missing)
        pass_reasons.append(reason)

        risks = []
        if row["overext_penalty"] > 0:
            risks.append("overheat")
        if row["valuation_pctl_penalty"] > 0:
            risks.append("valuation_percentile")
        if row["risk_penalty"] > 0:
            risks.append("drawdown_volatility")
        risk_reasons.append(";".join(risks))

    result["pass_reason"] = pass_reasons
    result["disqualify_risk"] = risk_reasons
    result["candidate_source"] = "factor_baseline"
    result["long_term_status"] = "not_evaluated"
    result["next_step"] = "stage_L"
    result["as_of"] = pd.NA

    for column in OUTPUT_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result.sort_values(["composite_score", "ts_code"], ascending=[False, True], kind="stable").reset_index(drop=True)


def apply_industry_cap(frame: pd.DataFrame, *, top: int = 50, industry_cap: float = 0.25) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    ordered = frame.sort_values(["composite_score", "ts_code"], ascending=[False, True], kind="stable").reset_index(drop=True)
    if industry_cap >= 1:
        return ordered.head(top).reset_index(drop=True)

    cap_count = max(1, int(np.ceil(top * industry_cap)))
    selected_rows = []
    counts: dict[str, int] = {}
    for _, row in ordered.iterrows():
        industry = str(row.get("industry") or "unknown")
        if counts.get(industry, 0) >= cap_count:
            continue
        selected_rows.append(row)
        counts[industry] = counts.get(industry, 0) + 1
        if len(selected_rows) >= top:
            break
    return pd.DataFrame(selected_rows).reset_index(drop=True)


def order_research_priority(frame: pd.DataFrame, *, with_catalyst: bool = False) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        result["research_priority_rank"] = pd.Series(dtype="Int64")
        return result

    sort_columns = ["composite_score", "ts_code"]
    ascending = [False, True]
    if with_catalyst:
        sort_columns.insert(0, "research_priority_overlay")
        ascending.insert(0, False)
    result = result.sort_values(sort_columns, ascending=ascending, kind="stable").reset_index(drop=True)
    result["research_priority_rank"] = pd.Series(range(1, len(result) + 1), dtype="Int64")
    return result


def build_factor_screen(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    as_of: str,
    start_date: str | None = None,
    symbols: Sequence[str] | None = None,
    preset: str = "balanced",
    top: int = 50,
    industry_cap: float = 0.25,
    with_catalyst: bool = False,
    catalyst: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict[str, int | str]]]:
    prices, volumes = load_daily_matrices(db_path=db_path, start_date=start_date, end_date=as_of, symbols=symbols)
    technical = build_screen(prices, volumes, windows=(60,), recent_days=10, min_valid=100)
    momentum = _compute_momentum_frame(prices)
    technical = technical.merge(momentum, on="ts_code", how="left")

    factor_inputs = load_factor_inputs(db_path=db_path, as_of=as_of, symbols=symbols)
    daily_basic_history = load_daily_basic_history(db_path=db_path, as_of=as_of, symbols=symbols)
    merged = factor_inputs.merge(technical, on="ts_code", how="inner")
    survivors, filter_log = apply_hard_gates(merged)
    scored = score_candidates(
        survivors,
        preset=preset,
        daily_basic_history=daily_basic_history,
        with_catalyst=with_catalyst,
        catalyst=catalyst,
    )
    scored["as_of"] = as_of
    selected = apply_industry_cap(scored[OUTPUT_COLUMNS], top=top, industry_cap=industry_cap)
    return order_research_priority(selected, with_catalyst=with_catalyst)[OUTPUT_COLUMNS], filter_log


def read_catalyst_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def write_screen(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".xlsx":
        frame.to_excel(output, index=False)
    else:
        frame.to_csv(output, index=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an explicitly requested quantitative research baseline; not a default or buy-list screen."
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, type=Path)
    parser.add_argument("--as-of", required=True, help="Screening date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--start-date", help="Optional price start date. Defaults to all data up to --as-of.")
    parser.add_argument("--symbols", nargs="*", help="Optional ts_code list. Defaults to all symbols in the database.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="balanced")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--industry-cap", type=float, default=0.25)
    parser.add_argument("--with-catalyst", action="store_true")
    parser.add_argument(
        "--explicit-quantitative-baseline",
        action="store_true",
        help="Required acknowledgement that this technical/multi-factor baseline is explicitly requested.",
    )
    parser.add_argument(
        "--catalyst-input",
        type=Path,
        help="Optional CSV/XLSX with ts_code,catalyst_score for survivor research-priority ordering only.",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.explicit_quantitative_baseline:
        parser.error(
            "factor_screen is an explicit quantitative baseline. Use fundamental_pool for default long-term candidate discovery."
        )
    catalyst = read_catalyst_table(args.catalyst_input) if args.catalyst_input else None
    screen, filter_log = build_factor_screen(
        db_path=args.db_path,
        as_of=args.as_of,
        start_date=args.start_date,
        symbols=args.symbols,
        preset=args.preset,
        top=args.top,
        industry_cap=args.industry_cap,
        with_catalyst=args.with_catalyst,
        catalyst=catalyst,
    )
    write_screen(screen, args.output)
    print(f"saved factor screen: {args.output}")
    for item in filter_log:
        print(f"filter_log | {item['rule']} | before={item['before']} | after={item['after']} | removed={item['removed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
