#!/usr/bin/env python3
"""Fetch, normalize, and query provider-scoped sector market data."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_sector_cached_dates,
    load_sector_daily_history,
    load_sector_memberships,
    load_sector_master,
    persist_tushare_collection,
    write_tushare_capabilities,
)
from project_context import ensure_project_layout, project_paths
from tushare_sync import create_tushare_client
from tushare_transport import TushareEndpointError, TushareRequestPolicy, request_endpoint


DEFAULT_PREVIEW_ROWS = 5
DEFAULT_RANKING_LIMIT = 20
DEFAULT_PROVIDER = "ths"
PERFORMANCE_SORT_FIELDS = (
    "pct_chg",
    "return_5d",
    "return_20d",
    "amount",
    "net_amount",
)
ROTATION_SORT_FIELDS = (
    "rank_change_5d",
    "return_5d_change",
    *PERFORMANCE_SORT_FIELDS,
)


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    label: str
    endpoints: dict[str, str]


PROVIDER_SPECS = {
    "ths": ProviderSpec(
        provider="ths",
        label="同花顺行业与概念板块",
        endpoints={
            "master": "ths_index",
            "daily": "ths_daily",
            "flow": "moneyflow_ind_ths",
            "members": "ths_member",
        },
    ),
    "dc": ProviderSpec(
        provider="dc",
        label="东方财富行业与概念板块",
        endpoints={
            "master": "dc_index",
            "daily": "dc_daily",
            "members": "dc_member",
        },
    ),
    "tdx": ProviderSpec(
        provider="tdx",
        label="通达信行业与概念板块",
        endpoints={
            "master": "tdx_index",
            "daily": "tdx_daily",
            "members": "tdx_member",
        },
    ),
}


def _date(value: str) -> str:
    text = value.strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise argparse.ArgumentTypeError("date must use YYYYMMDD or YYYY-MM-DD")
    try:
        pd.Timestamp(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc
    return text


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


def _preview(frame: pd.DataFrame, rows: int) -> list[dict[str, Any]]:
    if frame.empty or rows <= 0:
        return []
    return json.loads(
        frame.head(rows).to_json(orient="records", force_ascii=False, date_format="iso")
    )


def _window_return(history: pd.DataFrame, window: int) -> float | None:
    """Return the close-to-close percentage change across stored trading sessions."""
    if len(history) <= window:
        return None
    previous_close = pd.to_numeric(history.iloc[-(window + 1)]["close"], errors="coerce")
    latest_close = pd.to_numeric(history.iloc[-1]["close"], errors="coerce")
    if pd.isna(previous_close) or pd.isna(latest_close) or previous_close == 0:
        return None
    return (float(latest_close) / float(previous_close) - 1.0) * 100.0


def _breadth_snapshot(frame: pd.DataFrame) -> dict[str, int | float | None]:
    daily_returns = pd.to_numeric(frame.get("pct_chg"), errors="coerce")
    return {
        "sector_count": int(len(frame)),
        "advancers": int((daily_returns > 0).sum()),
        "decliners": int((daily_returns < 0).sum()),
        "unchanged": int((daily_returns == 0).sum()),
        "missing_returns": int(daily_returns.isna().sum()),
        "median_pct_chg": float(daily_returns.median()) if daily_returns.notna().any() else None,
    }


def _breadth_change(
    current: dict[str, int | float | None],
    previous: dict[str, int | float | None] | None,
) -> dict[str, int | float | None] | None:
    if previous is None:
        return None
    change: dict[str, int | float | None] = {}
    for key in current:
        current_value = current[key]
        previous_value = previous.get(key)
        if current_value is None or previous_value is None:
            change[key] = None
        else:
            change[key] = current_value - previous_value
    return change


def _selected_datasets(provider: str, requested: Sequence[str] | None) -> tuple[str, ...]:
    available = PROVIDER_SPECS[provider].endpoints
    if requested:
        unknown = [dataset for dataset in requested if dataset not in available]
        if unknown:
            raise ValueError(
                f"provider {provider} does not support dataset(s): {', '.join(unknown)}"
            )
        selected = tuple(dict.fromkeys(requested))
    else:
        selected = tuple(dataset for dataset in ("master", "daily", "flow") if dataset in available)
    return selected


def _request_params(
    dataset: str,
    *,
    as_of: str,
    start_date: str,
    sector_code: str | None,
    stock_code: str | None,
    sector_type: str | None,
) -> dict[str, str]:
    if dataset == "master":
        params: dict[str, str] = {}
        if sector_code:
            params["ts_code"] = sector_code
        if sector_type:
            params["type"] = sector_type
        return params
    if dataset == "members":
        if sector_code:
            return {"ts_code": sector_code}
        if stock_code:
            return {"con_code": stock_code}
        raise ValueError("members requires --sector-code or --stock-code")
    if sector_code:
        return {
            "ts_code": sector_code,
            "start_date": start_date,
            "end_date": as_of,
        }
    if start_date != as_of:
        return {"start_date": start_date, "end_date": as_of}
    return {"trade_date": as_of}


def _dataset_requests(
    dataset: str,
    *,
    endpoint: str,
    provider: str,
    as_of: str,
    start_date: str,
    sector_code: str | None,
    stock_code: str | None,
    sector_type: str | None,
) -> list[dict[str, Any]]:
    cache_dataset = f"sector_{provider}_{dataset}"
    if dataset in {"daily", "flow"} and not sector_code:
        requests = []
        for trade_date in pd.bdate_range(start=start_date, end=as_of):
            compact_date = trade_date.strftime("%Y%m%d")
            requests.append(
                {
                    "dataset": dataset,
                    "cache_dataset": cache_dataset,
                    "endpoint": endpoint,
                    "params": {"trade_date": compact_date},
                    "requested_trade_date": compact_date,
                    "permission_sensitive": True,
                }
            )
        return requests
    return [
        {
            "dataset": dataset,
            "cache_dataset": cache_dataset,
            "endpoint": endpoint,
            "params": _request_params(
                dataset,
                as_of=as_of,
                start_date=start_date,
                sector_code=sector_code,
                stock_code=stock_code,
                sector_type=sector_type,
            ),
            "permission_sensitive": True,
        }
    ]


def _cached_snapshot_coverage(
    request: dict[str, Any],
    *,
    cached_dates: set[str],
) -> dict[str, Any] | None:
    requested_trade_date = request.get("requested_trade_date")
    if not requested_trade_date:
        return None
    normalized_date = pd.Timestamp(str(requested_trade_date)).date().isoformat()
    is_cached = normalized_date in cached_dates
    return {
        "status": "complete" if is_cached else "missing",
        "requested_trade_date": str(requested_trade_date),
        "normalized_trade_date": normalized_date,
        "cached_date_count": int(is_cached),
        "missing_date_count": int(not is_cached),
    }


def _plan_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.start_date and args.start_date > args.as_of:
        raise ValueError("--start-date cannot be later than --as-of")
    start_date = args.start_date or args.as_of
    spec = PROVIDER_SPECS[args.provider]
    selected = _selected_datasets(args.provider, args.datasets)
    requests = []
    for dataset in selected:
        endpoint = spec.endpoints[dataset]
        requests.extend(
            _dataset_requests(
                dataset,
                endpoint=endpoint,
                provider=args.provider,
                as_of=args.as_of,
                start_date=start_date,
                sector_code=args.sector_code,
                stock_code=args.stock_code,
                sector_type=args.sector_type,
            )
        )
    return {
        "operation": "plan",
        "provider": args.provider,
        "provider_label": spec.label,
        "taxonomy_policy": {
            "market_sector_default": "THS",
            "fundamental_industry_reference": "SW2021",
            "cross_provider_codes_are_not_interchangeable": True,
        },
        "as_of": args.as_of,
        "start_date": start_date,
        "sector_code": args.sector_code,
        "stock_code": args.stock_code,
        "sector_type": args.sector_type,
        "request_count": len(requests),
        "cross_section_history_policy": (
            "Daily and flow history without a sector code is split into one request per business day "
            "to avoid silent row-limit truncation; exchange holidays may return empty snapshots."
        ),
        "requests": requests,
    }


def _filter_as_of(frame: pd.DataFrame, as_of: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty:
        return frame, {"status": "empty", "excluded_rows": 0}
    if "trade_date" not in frame.columns:
        return frame, {"status": "snapshot_without_effective_date", "excluded_rows": 0}
    parsed = pd.to_datetime(frame["trade_date"], errors="coerce", format="mixed")
    cutoff = pd.Timestamp(as_of)
    valid = parsed.notna()
    keep = valid & (parsed <= cutoff)
    filtered = frame.loc[keep].copy()
    return filtered, {
        "status": "verified" if bool(valid.all()) else "partial",
        "field": "trade_date",
        "excluded_rows": int((~keep).sum()),
        "invalid_or_missing_date_rows": int((~valid).sum()),
    }


def _run_catalog(_: argparse.Namespace) -> int:
    _print_json(
        {
            "operation": "catalog",
            "default_provider": DEFAULT_PROVIDER,
            "providers": [
                {
                    "provider": spec.provider,
                    "label": spec.label,
                    "datasets": spec.endpoints,
                }
                for spec in PROVIDER_SPECS.values()
            ],
            "ths_type_codes": {
                "I": "industry",
                "N": "concept",
                "R": "region",
                "S": "THS feature",
                "ST": "style",
                "TH": "theme",
                "BB": "broad market",
            },
            "commands": {
                "plan": "Plan provider-specific requests without reading a token.",
                "fetch": "Fetch and normalize sector master, daily, flow, and membership data.",
                "performance": "Rank locally stored sector performance with 5/20-session context.",
                "rotation": "Compare sector price, strength-rank, and breadth changes across sessions.",
                "memberships": "Resolve locally stored stock-to-sector or sector-to-stock membership.",
            },
        }
    )
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    _print_json(_plan_payload(args))
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    plan = _plan_payload(args)
    if args.dry_run:
        plan["operation"] = "dry_run"
        plan["cache"] = args.cache
        plan["refresh"] = args.refresh
        _print_json(plan)
        return 0

    policy = TushareRequestPolicy(
        min_interval_seconds=args.min_request_interval,
        max_attempts=args.max_attempts,
    )
    results: list[dict[str, Any]] = []
    capability_records: list[dict[str, Any]] = []
    failures = 0
    network_requests = 0
    client: Any | None = None
    project_layout_ready = False
    cache_reuse_enabled = args.cache and not args.refresh
    cached_dates_by_dataset: dict[str, set[str]] = {}
    for request in plan["requests"]:
        endpoint = str(request["endpoint"])
        dataset = str(request["dataset"])
        cached_dates: set[str] = set()
        if cache_reuse_enabled and dataset in {"daily", "flow"}:
            if dataset not in cached_dates_by_dataset:
                cached_dates_by_dataset[dataset] = load_sector_cached_dates(
                    db_path=args.db_path,
                    provider=args.provider,
                    dataset=dataset,
                    start_date=plan["start_date"],
                    end_date=plan["as_of"],
                )
            cached_dates = cached_dates_by_dataset[dataset]
        coverage = _cached_snapshot_coverage(request, cached_dates=cached_dates)
        if coverage and coverage["status"] == "complete":
            results.append(
                {
                    "dataset": dataset,
                    "endpoint": endpoint,
                    "status": "cached",
                    "network_requested": False,
                    "requested_trade_date": request["requested_trade_date"],
                    "cache_coverage": coverage,
                }
            )
            continue
        if client is None:
            if args.cache and not project_layout_ready:
                ensure_project_layout(project_paths())
                project_layout_ready = True
            client = create_tushare_client(env_path=args.env_file)
        try:
            network_requests += 1
            frame = request_endpoint(client, endpoint, dict(request["params"]), policy=policy)
        except TushareEndpointError as exc:
            failures += 1
            result = {
                "dataset": request["dataset"],
                "endpoint": endpoint,
                "status": "unavailable",
                "error": str(exc),
                "error_type": exc.category,
                "attempts": exc.attempts,
                "retryable": exc.retryable,
                "network_requested": True,
                "cache_coverage": coverage,
            }
            results.append(result)
            capability_records.append({"endpoint": endpoint, "category": "sector", **result})
            continue
        except ValueError as exc:
            failures += 1
            result = {
                "dataset": request["dataset"],
                "endpoint": endpoint,
                "status": "unavailable",
                "error_type": "invalid_endpoint",
                "error": str(exc),
                "network_requested": True,
                "cache_coverage": coverage,
            }
            results.append(result)
            capability_records.append({"endpoint": endpoint, "category": "sector", **result})
            continue

        raw_rows = len(frame)
        filtered, verification = _filter_as_of(frame, args.as_of)
        cached_rows = 0
        normalized_rows = 0
        if args.cache:
            cached_rows, normalized_rows = persist_tushare_collection(
                str(request["cache_dataset"]),
                endpoint,
                filtered,
                db_path=args.db_path,
            )
        status = "empty" if filtered.empty else "available"
        result = {
            "dataset": request["dataset"],
            "endpoint": endpoint,
            "status": status,
            "raw_rows": raw_rows,
            "rows": len(filtered),
            "cached_rows": cached_rows,
            "normalized_rows": normalized_rows,
            "network_requested": True,
            "requested_trade_date": request.get("requested_trade_date"),
            "cache_coverage": coverage,
            "columns": list(filtered.columns),
            "as_of_verification": verification,
            "preview": _preview(filtered, args.preview_rows),
        }
        results.append(result)
        capability_records.append(
            {
                "endpoint": endpoint,
                "category": "sector",
                "status": status,
                "rows": len(filtered),
                "provider": args.provider,
                "as_of": args.as_of,
            }
        )

    if args.cache:
        write_tushare_capabilities(capability_records, db_path=args.db_path)
    _print_json(
        {
            "operation": "fetch",
            "provider": args.provider,
            "as_of": args.as_of,
            "cache": args.cache,
            "refresh": args.refresh,
            "network_requests": network_requests,
            "results": results,
            "failures": failures,
            "next_step": (
                "Run performance for market breadth and strength, and memberships for stock exposure. "
                "Treat provider taxonomies as separate definitions."
            ),
        }
    )
    return 1 if args.strict and failures else 0


def summarize_sector_performance(
    frame: pd.DataFrame,
    *,
    as_of: str,
    provider: str,
    sort_by: str = "pct_chg",
    descending: bool = True,
    limit: int = DEFAULT_RANKING_LIMIT,
) -> dict[str, Any]:
    if frame.empty:
        return {
            "operation": "performance",
            "provider": provider,
            "as_of": as_of,
            "status": "no_data",
            "effective_trade_date": None,
            "breadth": None,
            "ranking": [],
        }
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce")
    working = working.loc[working["trade_date"].notna()].copy()
    if working.empty:
        raise ValueError("sector data contains no valid trade_date values")
    for column in ("close", "pct_chg", "amount", "net_amount"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    effective_date = working["trade_date"].max()
    records: list[dict[str, Any]] = []
    for (_, sector_code), history in working.groupby(["provider", "sector_code"], sort=False):
        history = history.sort_values("trade_date")
        latest = history.iloc[-1]
        if latest["trade_date"] != effective_date:
            continue
        record = latest.to_dict()
        for window in (5, 20):
            record[f"return_{window}d"] = _window_return(history, window)
        record["sector_code"] = sector_code
        records.append(record)
    ranking = pd.DataFrame(records)
    if ranking.empty:
        raise ValueError("no sector rows share the latest effective trade date")
    if sort_by not in ranking.columns:
        raise ValueError(f"sort field is unavailable: {sort_by}")
    ranking = ranking.sort_values(sort_by, ascending=not descending, na_position="last").head(limit)
    effective_cross_section = pd.DataFrame(records)
    breadth = _breadth_snapshot(effective_cross_section)
    output_columns = [
        "sector_code",
        "sector_name",
        "sector_type",
        "trade_date",
        "close",
        "pct_chg",
        "return_5d",
        "return_20d",
        "amount",
        "turnover_rate",
        "company_num",
        "lead_stock",
        "lead_stock_pct_chg",
        "net_buy_amount",
        "net_sell_amount",
        "net_amount",
    ]
    existing_columns = [column for column in output_columns if column in ranking.columns]
    ranking_records = json.loads(
        ranking[existing_columns].to_json(
            orient="records",
            force_ascii=False,
            date_format="iso",
        )
    )
    return {
        "operation": "performance",
        "provider": provider,
        "as_of": as_of,
        "status": "available",
        "effective_trade_date": effective_date.date().isoformat(),
        "sort_by": sort_by,
        "descending": descending,
        "breadth": breadth,
        "coverage": {
            "with_5d_return": int(effective_cross_section["return_5d"].notna().sum()),
            "with_20d_return": int(effective_cross_section["return_20d"].notna().sum()),
            "with_moneyflow": int(effective_cross_section["net_amount"].notna().sum()),
        },
        "ranking": ranking_records,
    }


def summarize_sector_rotation(
    frame: pd.DataFrame,
    *,
    as_of: str,
    provider: str,
    sort_by: str = "rank_change_5d",
    limit: int = DEFAULT_RANKING_LIMIT,
) -> dict[str, Any]:
    """Compare the latest two stored sector cross-sections without producing a trade signal."""
    if frame.empty:
        return {
            "operation": "rotation",
            "provider": provider,
            "as_of": as_of,
            "status": "no_data",
            "effective_trade_date": None,
            "previous_effective_trade_date": None,
            "top_changes": [],
            "bottom_changes": [],
        }
    if sort_by not in ROTATION_SORT_FIELDS:
        raise ValueError(f"rotation sort field is unavailable: {sort_by}")

    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce")
    working = working.loc[working["trade_date"].notna()].copy()
    if working.empty:
        raise ValueError("sector data contains no valid trade_date values")
    for column in ("close", "pct_chg", "amount", "net_amount"):
        working[column] = pd.to_numeric(working[column], errors="coerce")

    effective_date = working["trade_date"].max()
    earlier_dates = working.loc[working["trade_date"] < effective_date, "trade_date"]
    previous_date = earlier_dates.max() if not earlier_dates.empty else None
    current_records: list[dict[str, Any]] = []
    previous_records: list[dict[str, Any]] = []

    for (_, sector_code), history in working.groupby(["provider", "sector_code"], sort=False):
        history = history.sort_values("trade_date")
        current_history = history.loc[history["trade_date"] <= effective_date]
        if current_history.empty or current_history.iloc[-1]["trade_date"] != effective_date:
            continue
        current = current_history.iloc[-1].to_dict()
        current["sector_code"] = sector_code
        current["return_5d"] = _window_return(current_history, 5)
        current["return_20d"] = _window_return(current_history, 20)

        if previous_date is not None:
            previous_history = history.loc[history["trade_date"] <= previous_date]
            if not previous_history.empty and previous_history.iloc[-1]["trade_date"] == previous_date:
                previous = previous_history.iloc[-1].to_dict()
                previous["sector_code"] = sector_code
                previous["return_5d"] = _window_return(previous_history, 5)
                previous_records.append(previous)
                current["previous_pct_chg"] = previous["pct_chg"]
                current["pct_chg_change"] = (
                    float(current["pct_chg"] - previous["pct_chg"])
                    if pd.notna(current["pct_chg"]) and pd.notna(previous["pct_chg"])
                    else None
                )
                current["previous_return_5d"] = previous["return_5d"]
                current["return_5d_change"] = (
                    float(current["return_5d"] - previous["return_5d"])
                    if current["return_5d"] is not None and previous["return_5d"] is not None
                    else None
                )
            else:
                current["previous_pct_chg"] = None
                current["pct_chg_change"] = None
                current["previous_return_5d"] = None
                current["return_5d_change"] = None
        else:
            current["previous_pct_chg"] = None
            current["pct_chg_change"] = None
            current["previous_return_5d"] = None
            current["return_5d_change"] = None
        current_records.append(current)

    current_cross_section = pd.DataFrame(current_records)
    if current_cross_section.empty:
        raise ValueError("no sector rows share the latest effective trade date")
    previous_cross_section = pd.DataFrame(previous_records)
    current_cross_section["rank_5d"] = current_cross_section["return_5d"].rank(
        ascending=False,
        method="min",
    )
    if previous_cross_section.empty:
        current_cross_section["previous_rank_5d"] = None
        current_cross_section["rank_change_5d"] = None
        previous_breadth = None
    else:
        previous_cross_section["rank_5d"] = previous_cross_section["return_5d"].rank(
            ascending=False,
            method="min",
        )
        previous_ranks = previous_cross_section.set_index("sector_code")["rank_5d"]
        current_cross_section["previous_rank_5d"] = current_cross_section["sector_code"].map(
            previous_ranks
        )
        current_cross_section["rank_change_5d"] = (
            current_cross_section["previous_rank_5d"] - current_cross_section["rank_5d"]
        )
        previous_breadth = _breadth_snapshot(previous_cross_section)

    current_breadth = _breadth_snapshot(current_cross_section)
    output_columns = [
        "sector_code",
        "sector_name",
        "sector_type",
        "trade_date",
        "close",
        "pct_chg",
        "previous_pct_chg",
        "pct_chg_change",
        "return_5d",
        "previous_return_5d",
        "return_5d_change",
        "rank_5d",
        "previous_rank_5d",
        "rank_change_5d",
        "return_20d",
        "turnover_rate",
        "company_num",
        "lead_stock",
        "lead_stock_pct_chg",
        "net_amount",
    ]
    existing_columns = [column for column in output_columns if column in current_cross_section.columns]
    top_changes = _preview(
        current_cross_section.sort_values(sort_by, ascending=False, na_position="last")[existing_columns],
        limit,
    )
    bottom_changes = _preview(
        current_cross_section.sort_values(sort_by, ascending=True, na_position="last")[existing_columns],
        limit,
    )
    return {
        "operation": "rotation",
        "provider": provider,
        "as_of": as_of,
        "status": "available",
        "effective_trade_date": effective_date.date().isoformat(),
        "previous_effective_trade_date": (
            previous_date.date().isoformat() if previous_date is not None else None
        ),
        "sort_by": sort_by,
        "rank_change_interpretation": "positive means the sector's 5-day return rank improved",
        "breadth": current_breadth,
        "previous_breadth": previous_breadth,
        "breadth_change": _breadth_change(current_breadth, previous_breadth),
        "coverage": {
            "current_sector_count": int(len(current_cross_section)),
            "previous_sector_count": int(len(previous_cross_section)),
            "with_5d_rank_change": int(current_cross_section["rank_change_5d"].notna().sum()),
            "with_moneyflow": int(current_cross_section["net_amount"].notna().sum()),
        },
        "top_changes": top_changes,
        "bottom_changes": bottom_changes,
    }


def select_performance_universe(frame: pd.DataFrame, universe: str) -> pd.DataFrame:
    if universe == "all" or frame.empty:
        return frame
    trade_dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    effective_date = trade_dates.max()
    latest_rows = frame.loc[trade_dates.eq(effective_date)]
    eligible_codes = latest_rows.loc[
        pd.to_numeric(latest_rows["net_amount"], errors="coerce").notna(),
        "sector_code",
    ].dropna()
    if eligible_codes.empty:
        raise ValueError(
            "industry-flow universe requires same-date moneyflow_ind_ths coverage; fetch the flow dataset first"
        )
    return frame.loc[frame["sector_code"].isin(set(eligible_codes.astype(str)))].copy()


def _run_performance(args: argparse.Namespace) -> int:
    frame = load_sector_daily_history(
        db_path=args.db_path,
        provider=args.provider,
        end_date=args.as_of,
        sector_type=args.sector_type,
        sector_codes=args.sector_codes,
    )
    universe = args.universe
    if universe == "auto":
        universe = "industry-flow" if args.provider == "ths" and args.sector_type == "I" else "all"
    frame = select_performance_universe(frame, universe)
    payload = summarize_sector_performance(
        frame,
        as_of=args.as_of,
        provider=args.provider,
        sort_by=args.sort_by,
        descending=args.direction == "desc",
        limit=args.limit,
    )
    payload["sector_type"] = args.sector_type
    payload["universe"] = universe
    payload["database_path"] = str(args.db_path)
    _print_json(payload)
    return 0


def _run_rotation(args: argparse.Namespace) -> int:
    frame = load_sector_daily_history(
        db_path=args.db_path,
        provider=args.provider,
        end_date=args.as_of,
        sector_type=args.sector_type,
        sector_codes=args.sector_codes,
    )
    universe = args.universe
    if universe == "auto":
        universe = "industry-flow" if args.provider == "ths" and args.sector_type == "I" else "all"
    frame = select_performance_universe(frame, universe)
    payload = summarize_sector_rotation(
        frame,
        as_of=args.as_of,
        provider=args.provider,
        sort_by=args.sort_by,
        limit=args.limit,
    )
    payload["sector_type"] = args.sector_type
    payload["universe"] = universe
    payload["database_path"] = str(args.db_path)
    _print_json(payload)
    return 0


def _run_memberships(args: argparse.Namespace) -> int:
    frame = load_sector_memberships(
        db_path=args.db_path,
        provider=args.provider,
        stock_code=args.stock_code,
        sector_code=args.sector_code,
        as_of=args.as_of,
    )
    _print_json(
        {
            "operation": "memberships",
            "provider": args.provider,
            "as_of": args.as_of,
            "stock_code": args.stock_code,
            "sector_code": args.sector_code,
            "rows": len(frame),
            "memberships": _preview(frame, max(len(frame), 1)),
        }
    )
    return 0


def _run_master(args: argparse.Namespace) -> int:
    frame = load_sector_master(
        db_path=args.db_path,
        provider=args.provider,
        sector_type=args.sector_type,
        sector_codes=args.sector_codes,
    )
    _print_json(
        {
            "operation": "master",
            "provider": args.provider,
            "sector_type": args.sector_type,
            "rows": len(frame),
            "sectors": _preview(frame, args.limit),
        }
    )
    return 0


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=tuple(PROVIDER_SPECS), default=DEFAULT_PROVIDER)
    parser.add_argument("--as-of", type=_date, required=True, help="Research cutoff date")
    parser.add_argument("--start-date", type=_date, help="Optional first trade date for history")
    parser.add_argument("--sector-code", help="Provider-specific sector code")
    parser.add_argument("--stock-code", help="Stock ts_code used to fetch provider memberships")
    parser.add_argument("--sector-type", help="Provider-specific industry/concept type filter")
    parser.add_argument("--datasets", nargs="+", choices=("master", "daily", "flow", "members"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and query provider-scoped sector data for investment research."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog", help="List sector providers, datasets, and commands")

    plan_parser = subparsers.add_parser("plan", help="Plan sector requests without reading a token")
    _add_request_arguments(plan_parser)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and normalize sector data")
    _add_request_arguments(fetch_parser)
    fetch_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    fetch_parser.add_argument("--env-file", type=Path)
    fetch_parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist raw observations, normalized rows, and endpoint capabilities",
    )
    fetch_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore reusable daily and flow snapshots and force selected endpoints to refresh",
    )
    fetch_parser.add_argument("--dry-run", action="store_true")
    fetch_parser.add_argument("--strict", action="store_true")
    fetch_parser.add_argument("--preview-rows", type=_positive_int, default=DEFAULT_PREVIEW_ROWS)
    fetch_parser.add_argument("--min-request-interval", type=float, default=0.6)
    fetch_parser.add_argument("--max-attempts", type=_positive_int, default=3)

    performance_parser = subparsers.add_parser(
        "performance",
        help="Rank locally stored sector performance and market breadth",
    )
    performance_parser.add_argument("--provider", choices=tuple(PROVIDER_SPECS), default=DEFAULT_PROVIDER)
    performance_parser.add_argument("--as-of", type=_date, required=True)
    performance_parser.add_argument(
        "--sector-type",
        default="I",
        help="Provider-specific type; THS defaults to I (industry), use N for concepts",
    )
    performance_parser.add_argument("--sector-codes", nargs="+")
    performance_parser.add_argument(
        "--universe",
        choices=("auto", "industry-flow", "all"),
        default="auto",
        help="Auto uses THS industry-flow coverage for type I and all codes otherwise",
    )
    performance_parser.add_argument("--sort-by", choices=PERFORMANCE_SORT_FIELDS, default="pct_chg")
    performance_parser.add_argument("--direction", choices=("desc", "asc"), default="desc")
    performance_parser.add_argument("--limit", type=_positive_int, default=DEFAULT_RANKING_LIMIT)
    performance_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    rotation_parser = subparsers.add_parser(
        "rotation",
        help="Compare current and previous stored sector performance cross-sections",
    )
    rotation_parser.add_argument("--provider", choices=tuple(PROVIDER_SPECS), default=DEFAULT_PROVIDER)
    rotation_parser.add_argument("--as-of", type=_date, required=True)
    rotation_parser.add_argument(
        "--sector-type",
        default="I",
        help="Provider-specific type; THS defaults to I (industry), use N for concepts",
    )
    rotation_parser.add_argument("--sector-codes", nargs="+")
    rotation_parser.add_argument(
        "--universe",
        choices=("auto", "industry-flow", "all"),
        default="auto",
        help="Auto uses THS industry-flow coverage for type I and all codes otherwise",
    )
    rotation_parser.add_argument("--sort-by", choices=ROTATION_SORT_FIELDS, default="rank_change_5d")
    rotation_parser.add_argument("--limit", type=_positive_int, default=DEFAULT_RANKING_LIMIT)
    rotation_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    memberships_parser = subparsers.add_parser(
        "memberships",
        help="Resolve locally cached stock-to-sector or sector-to-stock membership",
    )
    memberships_parser.add_argument("--provider", choices=tuple(PROVIDER_SPECS), default=DEFAULT_PROVIDER)
    memberships_parser.add_argument("--as-of", type=_date)
    membership_target = memberships_parser.add_mutually_exclusive_group(required=True)
    membership_target.add_argument("--stock-code")
    membership_target.add_argument("--sector-code")
    memberships_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    master_parser = subparsers.add_parser("master", help="Read the locally stored sector dictionary")
    master_parser.add_argument("--provider", choices=tuple(PROVIDER_SPECS), default=DEFAULT_PROVIDER)
    master_parser.add_argument("--sector-type")
    master_parser.add_argument("--sector-codes", nargs="+")
    master_parser.add_argument("--limit", type=_positive_int, default=200)
    master_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            return _run_catalog(args)
        if args.command == "plan":
            return _run_plan(args)
        if args.command == "fetch":
            return _run_fetch(args)
        if args.command == "performance":
            return _run_performance(args)
        if args.command == "rotation":
            return _run_rotation(args)
        if args.command == "memberships":
            return _run_memberships(args)
        return _run_master(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
