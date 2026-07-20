#!/usr/bin/env python3
"""Record and read lightweight project-local holdings for research context."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from project_context import project_paths


MAX_HOLDINGS = 200


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_number(value: object, field: str) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def clean_date(value: object, field: str = "as_of") -> str:
    text = clean_text(value, 10)
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ValueError(f"{field} must use YYYY-MM-DD") from error


def normalize_symbol(value: object) -> str:
    return clean_text(value, 32).upper().replace(" ", "")


def clean_holding_item(
    item: Mapping[str, Any],
    *,
    default_as_of: str = "",
    default_source: str = "",
) -> dict[str, Any] | None:
    meaningful_fields = (
        "symbol",
        "name",
        "quantity",
        "average_cost",
        "latest_price",
        "target_weight",
        "notes",
    )
    if not any(item.get(field) not in ("", None) for field in meaningful_fields):
        return None
    values = {
        "symbol": normalize_symbol(item.get("symbol")),
        "name": clean_text(item.get("name"), 80),
        "quantity": clean_number(item.get("quantity"), "quantity"),
        "average_cost": clean_number(item.get("average_cost"), "average_cost"),
        "latest_price": clean_number(item.get("latest_price"), "latest_price"),
        "target_weight": clean_number(item.get("target_weight"), "target_weight"),
        "as_of": clean_date(item.get("as_of") or default_as_of),
        "notes": clean_text(item.get("notes"), 600),
        "source": clean_text(item.get("source") or default_source, 32),
        "updated_at": clean_text(item.get("updated_at"), 40),
    }
    if not values["symbol"]:
        raise ValueError("Each saved holding must include a symbol")
    if values["quantity"] is not None and values["quantity"] <= 0:
        raise ValueError("quantity must be greater than zero; remove a closed holding instead")
    for field in ("average_cost", "latest_price"):
        if values[field] is not None and values[field] < 0:
            raise ValueError(f"{field} cannot be negative")
    if values["target_weight"] is not None and not 0 <= values["target_weight"] <= 100:
        raise ValueError("target_weight must be between 0 and 100")
    return values


def clean_holding_items(
    value: object,
    *,
    default_as_of: str = "",
    default_source: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    holdings: list[dict[str, Any]] = []
    for item in value[:MAX_HOLDINGS]:
        if not isinstance(item, Mapping):
            continue
        holding = clean_holding_item(
            item,
            default_as_of=default_as_of,
            default_source=default_source,
        )
        if holding is not None:
            holdings.append(holding)
    return holdings


def profile_path(project_dir: Path | str) -> Path:
    return project_paths(project_dir).settings_root / "investor-profile.json"


def read_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read investor profile: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("Investor profile must contain a JSON object")
    return payload


def write_profile(path: Path, profile: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(profile), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def holding_metrics(holding: Mapping[str, Any]) -> dict[str, float | None]:
    quantity = clean_number(holding.get("quantity"), "quantity")
    average_cost = clean_number(holding.get("average_cost"), "average_cost")
    latest_price = clean_number(holding.get("latest_price"), "latest_price")
    if quantity is None or average_cost is None:
        cost_value = None
    else:
        cost_value = quantity * average_cost
    market_value = None if quantity is None or latest_price is None else quantity * latest_price
    unrealized_pnl = None if cost_value is None or market_value is None else market_value - cost_value
    unrealized_return_pct = (
        None if unrealized_pnl is None or not cost_value else unrealized_pnl / cost_value * 100
    )
    return {
        "cost_value": cost_value,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_return_pct": unrealized_return_pct,
    }


def holding_context(holding: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(holding), **holding_metrics(holding)}


def load_holdings(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    profile = read_profile(path)
    holdings = clean_holding_items(profile.get("holdings"))
    return profile, holdings


def upsert_holding(path: Path, updates: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    profile, holdings = load_holdings(path)
    symbol = normalize_symbol(updates.get("symbol"))
    if not symbol:
        raise ValueError("symbol is required")
    matches = [index for index, item in enumerate(holdings) if item["symbol"] == symbol]
    if len(matches) > 1:
        raise ValueError(f"Multiple current holdings use symbol {symbol}; reconcile them in the UI first")

    current = holdings[matches[0]] if matches else {}
    merged = {**current, **dict(updates), "symbol": symbol}
    merged.setdefault("as_of", date.today().isoformat())
    merged["source"] = "agent"
    merged["updated_at"] = now_iso()
    holding = clean_holding_item(merged)
    if holding is None or holding["quantity"] is None:
        raise ValueError("quantity is required when recording a holding")

    action = "updated" if matches else "created"
    if matches:
        holdings[matches[0]] = holding
    else:
        if len(holdings) >= MAX_HOLDINGS:
            raise ValueError(f"Cannot save more than {MAX_HOLDINGS} holdings")
        holdings.append(holding)
    profile["holdings"] = holdings
    profile["updated_at"] = now_iso()
    write_profile(path, profile)
    return action, holding_context(holding)


def remove_holding(path: Path, symbol_value: object) -> dict[str, Any]:
    profile, holdings = load_holdings(path)
    symbol = normalize_symbol(symbol_value)
    remaining = [holding for holding in holdings if holding["symbol"] != symbol]
    if len(remaining) == len(holdings):
        raise ValueError(f"No current holding found for {symbol}")
    profile["holdings"] = remaining
    profile["updated_at"] = now_iso()
    write_profile(path, profile)
    return {"status": "removed", "symbol": symbol, "holding_count": len(remaining)}


def show_holdings(path: Path, symbols: Sequence[str] = ()) -> dict[str, Any]:
    profile, holdings = load_holdings(path)
    requested = {normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)}
    selected = [holding for holding in holdings if not requested or holding["symbol"] in requested]
    warnings: list[str] = []
    duplicate_symbols = sorted(
        symbol for symbol in {item["symbol"] for item in holdings}
        if sum(item["symbol"] == symbol for item in holdings) > 1
    )
    if duplicate_symbols:
        warnings.append(f"Duplicate symbols require reconciliation: {', '.join(duplicate_symbols)}")
    for holding in selected:
        if holding["quantity"] is None:
            warnings.append(f"{holding['symbol']} is missing quantity")
        if not holding["as_of"]:
            warnings.append(f"{holding['symbol']} is missing a holdings as-of date")
    return {
        "status": "available" if selected else "empty",
        "profile_path": str(path),
        "profile_updated_at": clean_text(profile.get("updated_at"), 40),
        "requested_symbols": sorted(requested),
        "holding_count": len(selected),
        "holdings": [holding_context(holding) for holding in selected],
        "warnings": warnings,
    }


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-dir", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record and read lightweight current holdings used as IR Agent context."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="Show all or selected current holdings")
    _add_project_argument(show)
    show.add_argument("--symbol", action="append", default=[], help="Filter by symbol; repeatable")

    upsert = subparsers.add_parser("upsert", help="Create or update one current holding")
    _add_project_argument(upsert)
    upsert.add_argument("--symbol", required=True)
    upsert.add_argument("--quantity", type=float, required=True)
    upsert.add_argument("--name")
    upsert.add_argument("--average-cost", type=float)
    upsert.add_argument("--latest-price", type=float)
    upsert.add_argument("--target-weight", type=float)
    upsert.add_argument("--as-of", default=date.today().isoformat())
    upsert.add_argument("--notes")

    remove = subparsers.add_parser("remove", help="Remove a fully closed current holding")
    _add_project_argument(remove)
    remove.add_argument("--symbol", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = profile_path(args.project_dir)
        if args.command == "show":
            payload = show_holdings(path, args.symbol)
        elif args.command == "remove":
            payload = remove_holding(path, args.symbol)
        else:
            updates = {
                "symbol": args.symbol,
                "quantity": args.quantity,
                "as_of": args.as_of,
            }
            for argument, field in (
                ("name", "name"),
                ("average_cost", "average_cost"),
                ("latest_price", "latest_price"),
                ("target_weight", "target_weight"),
                ("notes", "notes"),
            ):
                value = getattr(args, argument)
                if value is not None:
                    updates[field] = value
            action, holding = upsert_holding(path, updates)
            payload = {"status": action, "profile_path": str(path), "holding": holding}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
