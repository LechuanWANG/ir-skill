#!/usr/bin/env python3
"""Build a long-term fundamental research pool without technical-price screening."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_factor_inputs,
    load_fina_indicator_history,
)


@dataclass(frozen=True)
class FundamentalPoolConfig:
    min_total_mv: float = 500_000
    min_circ_mv: float = 200_000
    min_roe_dt: float = 0.0
    max_debt_to_assets: float = 80.0
    minimum_annual_reports: int = 3
    min_industry_size: int = 8
    minimum_durability_coverage: float = 0.8
    new_candidate_share: float = 0.5
    retained_candidate_share: float = 0.4
    repeat_cooldown_days: int = 60
    material_price_change: float = 0.15


OUTPUT_COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "market",
    "candidate_source",
    "total_mv_100m",
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
    "financial_history_years",
    "history_coverage",
    "financial_history_status",
    "data_readiness",
    "value_signal",
    "quality_signal",
    "growth_signal",
    "durability_signal",
    "durability_applied",
    "research_priority_score",
    "research_priority_rank",
    "prior_decision_count",
    "last_decision_as_of",
    "last_entry_action",
    "days_since_last_decision",
    "material_update",
    "material_update_reason",
    "selection_sleeve",
    "research_gaps",
    "long_term_status",
    "next_step",
    "stage_l_profiles",
    "as_of",
]


def _to_numeric(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = np.nan
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _percentile(values: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(0.5, index=values.index, dtype="float64")
    return numeric.rank(method="average", pct=True, ascending=higher_is_better).fillna(0.5).astype("float64")


def _industry_percentile(
    frame: pd.DataFrame,
    column: str,
    *,
    higher_is_better: bool,
    min_group_size: int,
) -> pd.Series:
    scores = _percentile(frame[column], higher_is_better=higher_is_better)
    if "industry" not in frame.columns:
        return scores
    for _, group in frame.groupby("industry", dropna=False):
        if len(group) >= min_group_size:
            scores.loc[group.index] = _percentile(group[column], higher_is_better=higher_is_better)
    return scores.fillna(0.5)


def _mean_scores(scores: Sequence[pd.Series]) -> pd.Series:
    if not scores:
        raise ValueError("scores must not be empty")
    return pd.concat(scores, axis=1).mean(axis=1).fillna(0.5).clip(0, 1)


def _timestamp(value: object) -> pd.Timestamp:
    text = str(value).strip()
    if text.isdigit() and len(text) == 8:
        return pd.to_datetime(text, format="%Y%m%d")
    return pd.Timestamp(text)


def _annual_report_counts(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty or not {"ts_code", "end_date"}.issubset(history.columns):
        return pd.DataFrame(columns=["ts_code", "financial_history_years"])
    annual = history.loc[
        history["end_date"].astype(str).str.replace("-", "", regex=False).str.endswith("1231"),
        ["ts_code", "end_date"],
    ].copy()
    if annual.empty:
        return pd.DataFrame(columns=["ts_code", "financial_history_years"])
    annual["report_year"] = annual["end_date"].astype(str).str.replace("-", "", regex=False).str[:4]
    return (
        annual.drop_duplicates(["ts_code", "report_year"])
        .groupby("ts_code", as_index=False)["report_year"]
        .nunique()
        .rename(columns={"report_year": "financial_history_years"})
    )


def _stability(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 2:
        return float("nan")
    scale = max(abs(float(clean.mean())), 1.0)
    return float(1.0 / (1.0 + float(clean.std(ddof=0)) / scale))


def summarize_financial_history(history: pd.DataFrame) -> pd.DataFrame:
    counts = _annual_report_counts(history)
    if counts.empty:
        return pd.DataFrame(
            columns=[
                "ts_code",
                "financial_history_years",
                "history_roe_median",
                "history_margin_stability",
                "history_cash_stability",
                "history_growth_resilience",
                "latest_financial_announcement",
            ]
        )
    prepared = history.copy()
    prepared["normalized_end_date"] = prepared["end_date"].astype(str).str.replace("-", "", regex=False)
    annual = prepared.loc[prepared["normalized_end_date"].str.endswith("1231")].copy()
    annual["report_year"] = annual["normalized_end_date"].str[:4]
    annual = annual.sort_values(["ts_code", "report_year", "ann_date", "end_date"]).drop_duplicates(
        ["ts_code", "report_year"],
        keep="last",
    )
    rows: list[dict[str, float | str]] = []
    for symbol, group in annual.groupby("ts_code"):
        growth_values = pd.concat(
            [
                pd.to_numeric(group.get("netprofit_yoy"), errors="coerce"),
                pd.to_numeric(group.get("or_yoy"), errors="coerce"),
            ],
            ignore_index=True,
        ).dropna()
        rows.append(
            {
                "ts_code": str(symbol),
                "history_roe_median": float(
                    pd.to_numeric(group.get("roe_dt"), errors="coerce").median()
                ),
                "history_margin_stability": _stability(group.get("netprofit_margin")),
                "history_cash_stability": _stability(group.get("ocf_to_or")),
                "history_growth_resilience": (
                    float((growth_values >= 0).mean()) if not growth_values.empty else float("nan")
                ),
                "latest_financial_announcement": str(group["ann_date"].dropna().max() or ""),
            }
        )
    return counts.merge(pd.DataFrame(rows), on="ts_code", how="left")


def load_prior_decision_history(db_path: Path, *, as_of: str) -> pd.DataFrame:
    normalized_as_of = _timestamp(as_of).date().isoformat()
    try:
        with sqlite3.connect(db_path) as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'decision_card'"
            ).fetchone()
            if table_exists is None:
                return pd.DataFrame()
            rows = pd.read_sql_query(
                """
                SELECT symbol, as_of, entry_action, next_review_date, metadata_json, created_at
                FROM decision_card
                WHERE as_of <= ?
                ORDER BY symbol, as_of, created_at
                """,
                connection,
                params=[normalized_as_of],
            )
    except sqlite3.DatabaseError:
        return pd.DataFrame()
    if rows.empty:
        return pd.DataFrame()
    history_rows: list[dict[str, object]] = []
    for symbol, group in rows.groupby("symbol"):
        latest = group.iloc[-1]
        try:
            metadata = json.loads(str(latest["metadata_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        context = metadata.get("_decision_context_v1", {})
        history_rows.append(
            {
                "ts_code": str(symbol),
                "prior_decision_count": int(len(group)),
                "last_decision_as_of": str(latest["as_of"]),
                "last_entry_action": str(latest["entry_action"]),
                "last_reference_price": context.get("reference_price"),
                "last_next_review_date": latest["next_review_date"],
            }
        )
    return pd.DataFrame(history_rows)


def annotate_candidate_history(
    frame: pd.DataFrame,
    *,
    as_of: str,
    config: FundamentalPoolConfig = FundamentalPoolConfig(),
) -> pd.DataFrame:
    result = frame.copy()
    as_of_date = _timestamp(as_of).normalize()
    result["prior_decision_count"] = pd.to_numeric(
        result.get("prior_decision_count", 0), errors="coerce"
    ).fillna(0).astype(int)
    last_date_values = (
        result["last_decision_as_of"]
        if "last_decision_as_of" in result.columns
        else pd.Series(pd.NaT, index=result.index)
    )
    last_dates = pd.to_datetime(last_date_values, errors="coerce")
    result["days_since_last_decision"] = (as_of_date - last_dates).dt.days
    material_flags: list[bool] = []
    material_reasons: list[str] = []
    for _, row in result.iterrows():
        reasons: list[str] = []
        last_decision = pd.to_datetime(row.get("last_decision_as_of"), errors="coerce")
        latest_financial = pd.to_datetime(row.get("latest_financial_announcement"), errors="coerce")
        if pd.notna(last_decision) and pd.notna(latest_financial) and latest_financial > last_decision:
            reasons.append("new_financial_disclosure")
        reference_price = pd.to_numeric(pd.Series([row.get("last_reference_price")]), errors="coerce").iloc[0]
        current_price = pd.to_numeric(pd.Series([row.get("close")]), errors="coerce").iloc[0]
        if pd.notna(reference_price) and reference_price > 0 and pd.notna(current_price):
            if abs(float(current_price / reference_price - 1)) >= config.material_price_change:
                reasons.append("material_price_change")
        next_review = pd.to_datetime(row.get("last_next_review_date"), errors="coerce")
        if pd.notna(next_review) and next_review <= as_of_date:
            reasons.append("review_due")
        material_flags.append(bool(reasons))
        material_reasons.append(",".join(reasons))
    result["material_update"] = material_flags
    result["material_update_reason"] = material_reasons
    return result


def apply_fundamental_gates(
    frame: pd.DataFrame,
    config: FundamentalPoolConfig = FundamentalPoolConfig(),
) -> tuple[pd.DataFrame, list[dict[str, int | str]]]:
    """Remove clearly unsuitable research-pool members without using price technicals."""
    current = _to_numeric(
        frame,
        ("total_mv", "circ_mv", "pe_ttm", "pb", "roe_dt", "debt_to_assets"),
    )
    log: list[dict[str, int | str]] = []

    def apply(rule: str, mask: pd.Series) -> None:
        nonlocal current
        before = len(current)
        current = current.loc[mask.reindex(current.index).fillna(False)].copy()
        after = len(current)
        log.append({"rule": rule, "before": before, "after": after, "removed": before - after})

    names = current.get("name", pd.Series("", index=current.index)).astype(str)
    apply("ST/退市", ~names.str.contains(r"\*?ST|退", case=False, regex=True, na=False))
    apply(
        "基础数据",
        current[["total_mv", "circ_mv", "pe_ttm", "pb", "roe_dt", "debt_to_assets"]].notna().all(axis=1),
    )
    apply("规模/可交易性", (current["total_mv"] >= config.min_total_mv) & (current["circ_mv"] >= config.min_circ_mv))
    apply("财务质量底线", current["roe_dt"] >= config.min_roe_dt)
    apply("资产负债表底线", current["debt_to_assets"] <= config.max_debt_to_assets)
    apply("估值有效性", (current["pe_ttm"] > 0) & (current["pb"] > 0))
    return current.reset_index(drop=True), log


def score_fundamental_candidates(
    frame: pd.DataFrame,
    *,
    config: FundamentalPoolConfig = FundamentalPoolConfig(),
    as_of: str,
) -> pd.DataFrame:
    """Prioritize Stage-L research work; never infer a long-term investment verdict."""
    numeric_columns = (
        "total_mv",
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
        "financial_history_years",
        "history_roe_median",
        "history_margin_stability",
        "history_cash_stability",
        "history_growth_resilience",
    )
    result = _to_numeric(frame, numeric_columns).reset_index(drop=True)
    result["financial_history_years"] = result["financial_history_years"].fillna(0).clip(lower=0)

    result["value_signal"] = _mean_scores(
        (
            _industry_percentile(result, "pe_ttm", higher_is_better=False, min_group_size=config.min_industry_size),
            _industry_percentile(result, "pb", higher_is_better=False, min_group_size=config.min_industry_size),
            _industry_percentile(result, "ps_ttm", higher_is_better=False, min_group_size=config.min_industry_size),
            _industry_percentile(result, "dv_ttm", higher_is_better=True, min_group_size=config.min_industry_size),
        )
    )
    result["quality_signal"] = _mean_scores(
        (
            _percentile(result["roe_dt"], higher_is_better=True),
            _industry_percentile(result, "netprofit_margin", higher_is_better=True, min_group_size=config.min_industry_size),
            _industry_percentile(result, "grossprofit_margin", higher_is_better=True, min_group_size=config.min_industry_size),
            _percentile(result["debt_to_assets"], higher_is_better=False),
            _percentile(result["ocf_to_or"], higher_is_better=True),
        )
    )
    result["growth_signal"] = _mean_scores(
        (
            _percentile(result["netprofit_yoy"], higher_is_better=True),
            _percentile(result["or_yoy"], higher_is_better=True),
        )
    )
    result["history_coverage"] = (
        result["financial_history_years"] / max(config.minimum_annual_reports, 1)
    ).clip(upper=1.0)
    eligible_history = result["financial_history_years"] >= config.minimum_annual_reports
    durability_coverage = float(eligible_history.mean()) if len(result) else 0.0
    durability_applied = durability_coverage >= config.minimum_durability_coverage
    if durability_applied:
        durability = _mean_scores(
            (
                _percentile(result["history_roe_median"], higher_is_better=True),
                _percentile(result["history_margin_stability"], higher_is_better=True),
                _percentile(result["history_cash_stability"], higher_is_better=True),
                _percentile(result["history_growth_resilience"], higher_is_better=True),
            )
        )
        result["durability_signal"] = durability.where(eligible_history, 0.5)
        result["research_priority_score"] = (
            0.30 * result["value_signal"]
            + 0.35 * result["quality_signal"]
            + 0.20 * result["growth_signal"]
            + 0.15 * result["durability_signal"]
        ).round(4)
    else:
        result["durability_signal"] = np.nan
        result["research_priority_score"] = (
            0.35 * result["value_signal"]
            + 0.40 * result["quality_signal"]
            + 0.25 * result["growth_signal"]
        ).round(4)
    result["durability_applied"] = durability_applied
    result["candidate_source"] = "long_term_fundamental_pool"
    result["long_term_status"] = "not_evaluated"
    result["next_step"] = "stage_L"
    result["stage_l_profiles"] = "long-term-quality,risk-review"
    result["as_of"] = str(as_of)
    result["total_mv_100m"] = result["total_mv"] / 10_000
    result["financial_history_status"] = np.where(
        result["financial_history_years"] >= config.minimum_annual_reports,
        "history_available",
        "needs_history_evidence",
    )
    result["data_readiness"] = np.where(
        result["financial_history_years"] >= config.minimum_annual_reports,
        "history_ready",
        "history_partial",
    )

    gaps: list[str] = []
    required = ("netprofit_margin", "grossprofit_margin", "netprofit_yoy", "or_yoy", "ocf_to_or")
    for _, row in result.iterrows():
        row_gaps = [column for column in required if pd.isna(row[column])]
        if int(row["financial_history_years"]) < config.minimum_annual_reports:
            row_gaps.append(f"annual_reports_below_{config.minimum_annual_reports}y")
        gaps.append(",".join(row_gaps) if row_gaps else "stage_L_primary_disclosure_review_required"
        )
    result["research_gaps"] = gaps

    for column in OUTPUT_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result.sort_values(
        ["research_priority_score", "ts_code"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)


def apply_industry_cap(
    frame: pd.DataFrame,
    *,
    top: int,
    industry_cap: float,
) -> pd.DataFrame:
    if top <= 0:
        raise ValueError("top must be positive")
    if not 0 < industry_cap <= 1:
        raise ValueError("industry_cap must be in (0, 1]")
    if frame.empty:
        return frame.copy()
    ordered = frame.sort_values(
        ["research_priority_score", "ts_code"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
    if industry_cap >= 1:
        return ordered.head(top).reset_index(drop=True)

    cap_count = max(1, int(np.ceil(top * industry_cap)))
    counts: dict[str, int] = {}
    selected: list[pd.Series] = []
    for _, row in ordered.iterrows():
        industry = str(row.get("industry") or "unknown")
        if counts.get(industry, 0) >= cap_count:
            continue
        selected.append(row)
        counts[industry] = counts.get(industry, 0) + 1
        if len(selected) >= top:
            break
    return pd.DataFrame(selected).reset_index(drop=True)


def select_research_pool(
    frame: pd.DataFrame,
    *,
    top: int,
    industry_cap: float,
    config: FundamentalPoolConfig = FundamentalPoolConfig(),
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if top <= 0:
        raise ValueError("top must be positive")
    if not 0 < industry_cap <= 1:
        raise ValueError("industry_cap must be in (0, 1]")
    ordered = frame.sort_values(
        ["research_priority_score", "ts_code"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
    prior_count = pd.to_numeric(ordered.get("prior_decision_count", 0), errors="coerce").fillna(0)
    days_since = pd.to_numeric(ordered.get("days_since_last_decision"), errors="coerce")
    material_update = ordered.get("material_update", pd.Series(False, index=ordered.index)).fillna(False)
    is_new = (prior_count <= 0) | (days_since >= config.repeat_cooldown_days)
    new_candidates = ordered.loc[is_new].copy()
    retained_candidates = ordered.loc[~is_new].copy()
    retained_candidates["_material_order"] = material_update.loc[retained_candidates.index].astype(int)
    retained_candidates = retained_candidates.sort_values(
        ["_material_order", "research_priority_score", "ts_code"],
        ascending=[False, False, True],
        kind="stable",
    )

    cap_count = max(1, int(np.ceil(top * industry_cap)))
    selected_indices: list[int] = []
    selected_sleeves: dict[int, str] = {}
    industry_counts: dict[str, int] = {}

    def add_candidates(candidates: pd.DataFrame, *, limit: int, sleeve: str) -> None:
        if limit <= 0:
            return
        added = 0
        for index, row in candidates.iterrows():
            if index in selected_sleeves:
                continue
            industry = str(row.get("industry") or "unknown")
            if industry_counts.get(industry, 0) >= cap_count:
                continue
            selected_indices.append(index)
            selected_sleeves[index] = sleeve
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            added += 1
            if added >= limit or len(selected_indices) >= top:
                return

    new_target = min(top, max(1, int(np.ceil(top * config.new_candidate_share))))
    retained_target = min(
        top - min(new_target, len(new_candidates)),
        max(0, int(np.floor(top * config.retained_candidate_share))),
    )
    add_candidates(new_candidates, limit=new_target, sleeve="new_discovery")
    add_candidates(retained_candidates, limit=retained_target, sleeve="core_refresh")
    remaining = ordered.loc[~ordered.index.isin(selected_indices)]
    add_candidates(remaining, limit=top - len(selected_indices), sleeve="research_challenger")

    selected = ordered.loc[selected_indices].copy()
    selected["selection_sleeve"] = [selected_sleeves[index] for index in selected_indices]
    if len(selected) >= 5:
        new_positions = selected.index[selected["selection_sleeve"] == "new_discovery"].tolist()
        if len(new_positions) >= 3:
            challenger_index = new_positions[-1]
            selected.loc[challenger_index, "selection_sleeve"] = "research_challenger"
    return selected.reset_index(drop=True)


def build_fundamental_pool(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    as_of: str,
    symbols: Sequence[str] | None = None,
    top: int = 30,
    industry_cap: float = 0.25,
    config: FundamentalPoolConfig = FundamentalPoolConfig(),
) -> tuple[pd.DataFrame, list[dict[str, int | str]]]:
    """Build a Stage-L research pool from valuation and financial data only."""
    inputs = load_factor_inputs(db_path=db_path, as_of=as_of, symbols=symbols)
    if inputs.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), [
            {"rule": "基础数据", "before": 0, "after": 0, "removed": 0}
        ]
    history = load_fina_indicator_history(db_path=db_path, as_of=as_of, symbols=symbols)
    history_summary = summarize_financial_history(history)
    prepared = inputs.merge(history_summary, on="ts_code", how="left")
    decision_history = load_prior_decision_history(db_path, as_of=as_of)
    if not decision_history.empty:
        prepared = prepared.merge(decision_history, on="ts_code", how="left")
    for column, default in (
        ("prior_decision_count", 0),
        ("last_decision_as_of", pd.NA),
        ("last_entry_action", pd.NA),
        ("last_reference_price", np.nan),
        ("last_next_review_date", pd.NA),
    ):
        if column not in prepared.columns:
            prepared[column] = default
    prepared = annotate_candidate_history(prepared, as_of=as_of, config=config)
    survivors, filter_log = apply_fundamental_gates(prepared, config=config)
    if survivors.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), filter_log
    scored = score_fundamental_candidates(survivors, config=config, as_of=as_of)
    selected = select_research_pool(
        scored,
        top=top,
        industry_cap=industry_cap,
        config=config,
    )
    selected["research_priority_rank"] = pd.Series(range(1, len(selected) + 1), dtype="Int64")
    for column in OUTPUT_COLUMNS:
        if column not in selected.columns:
            selected[column] = pd.NA
    return selected[OUTPUT_COLUMNS].reset_index(drop=True), filter_log


def write_pool(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".xlsx", ".xls"}:
        frame.to_excel(output, index=False)
    else:
        frame.to_csv(output, index=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fundamental research pool for Stage L; this is not a buy list or technical screen."
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, type=Path)
    parser.add_argument("--as-of", required=True, help="Research cutoff date, YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--symbols", nargs="*", help="Optional ts_code list. Defaults to cached A-share universe.")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--industry-cap", type=float, default=0.25)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pool, filter_log = build_fundamental_pool(
        db_path=args.db_path,
        as_of=args.as_of,
        symbols=args.symbols,
        top=args.top,
        industry_cap=args.industry_cap,
    )
    write_pool(pool, args.output)
    print(f"saved fundamental research pool: {args.output}")
    for item in filter_log:
        print(
            "filter_log | "
            f"{item['rule']} | before={item['before']} | after={item['after']} | removed={item['removed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
