#!/usr/bin/env python3
"""Maintain a project-local index of equities selected for continued research."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from portfolio_context import clean_date, clean_text, normalize_symbol
from project_context import project_paths


SCHEMA_VERSION = 1
MAX_ITEMS = 500
MAX_SOURCE_REPORTS = 20
STATUSES = ("tracking", "waiting-price", "waiting-evidence", "paused", "archived")
RESEARCH_PATHS = ("long-term", "medium-term", "short-term", "mixed")
CONFIDENCE_LEVELS = ("", "high", "medium", "low")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def watchlist_path(project_dir: Path | str) -> Path:
    return project_paths(project_dir).tracking_root / "research-watchlist.json"


def clean_choice(value: object, field: str, choices: Sequence[str], default: str = "") -> str:
    text = clean_text(value, 40) or default
    if text not in choices:
        raise ValueError(f"{field} must be one of: {', '.join(choice or '(empty)' for choice in choices)}")
    return text


def clean_source_report(value: object) -> str:
    text = clean_text(value, 260).replace("\\", "/")
    if not text:
        return ""
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "report":
        raise ValueError("source reports must be project-relative paths under report/")
    if path.suffix.lower() != ".md":
        raise ValueError("source reports must point to Markdown files")
    return path.as_posix()


def clean_source_reports(value: object) -> list[str]:
    if value in (None, ""):
        return []
    raw_values = value if isinstance(value, list) else [value]
    reports: list[str] = []
    for raw in raw_values[:MAX_SOURCE_REPORTS]:
        report = clean_source_report(raw)
        if report and report not in reports:
            reports.append(report)
    return reports


def clean_watch_item(
    item: Mapping[str, Any],
    *,
    default_source: str = "",
    default_recommended_on: str = "",
    default_last_researched_on: str = "",
) -> dict[str, Any] | None:
    meaningful_fields = (
        "symbol",
        "name",
        "research_path",
        "action_label",
        "thesis",
        "follow_up",
        "invalidation",
        "source_reports",
        "notes",
    )
    if not any(item.get(field) not in ("", None, []) for field in meaningful_fields):
        return None

    symbol = normalize_symbol(item.get("symbol"))
    if not symbol:
        raise ValueError("Each tracked research item must include a symbol")
    research_path = clean_choice(item.get("research_path"), "research_path", RESEARCH_PATHS)
    values = {
        "symbol": symbol,
        "name": clean_text(item.get("name"), 80),
        "status": clean_choice(item.get("status"), "status", STATUSES, "tracking"),
        "research_path": research_path,
        "action_label": clean_text(item.get("action_label"), 40),
        "confidence": clean_choice(item.get("confidence"), "confidence", CONFIDENCE_LEVELS),
        "thesis": clean_text(item.get("thesis"), 1_200),
        "follow_up": clean_text(item.get("follow_up"), 1_000),
        "invalidation": clean_text(item.get("invalidation"), 1_000),
        "recommended_on": clean_date(item.get("recommended_on") or default_recommended_on, "recommended_on"),
        "last_researched_on": clean_date(
            item.get("last_researched_on") or default_last_researched_on,
            "last_researched_on",
        ),
        "next_review_on": clean_date(item.get("next_review_on"), "next_review_on"),
        "source_reports": clean_source_reports(item.get("source_reports")),
        "notes": clean_text(item.get("notes"), 1_200),
        "source": clean_text(item.get("source") or default_source, 32),
        "created_at": clean_text(item.get("created_at"), 40),
        "updated_at": clean_text(item.get("updated_at"), 40),
    }
    return values


def clean_watch_items(
    value: object,
    *,
    default_source: str = "",
    default_recommended_on: str = "",
    default_last_researched_on: str = "",
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    symbols: set[str] = set()
    for raw in value[:MAX_ITEMS]:
        if not isinstance(raw, Mapping):
            continue
        item = clean_watch_item(
            raw,
            default_source=default_source,
            default_recommended_on=default_recommended_on,
            default_last_researched_on=default_last_researched_on,
        )
        if item is None:
            continue
        if item["symbol"] in symbols:
            raise ValueError(f"Duplicate tracked symbol: {item['symbol']}")
        symbols.add(item["symbol"])
        items.append(item)
    return items


def read_watchlist(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "updated_at": "", "items": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read research watchlist: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("Research watchlist must contain a JSON object")
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": clean_text(payload.get("updated_at"), 40),
        "items": clean_watch_items(payload.get("items")),
    }


def write_watchlist(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def replace_watchlist(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    current_time = now_iso()
    today = date.today().isoformat()
    items = clean_watch_items(
        payload.get("items"),
        default_source="ui",
        default_recommended_on=today,
        default_last_researched_on=today,
    )
    for item in items:
        item["source"] = "ui"
        item["created_at"] = item["created_at"] or current_time
        item["updated_at"] = current_time
    result = {"schema_version": SCHEMA_VERSION, "updated_at": current_time, "items": items}
    write_watchlist(path, result)
    return result


def upsert_watch_item(path: Path, updates: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = read_watchlist(path)
    items = payload["items"]
    symbol = normalize_symbol(updates.get("symbol"))
    if not symbol:
        raise ValueError("symbol is required")
    matches = [index for index, item in enumerate(items) if item["symbol"] == symbol]
    current = items[matches[0]] if matches else {}
    merged = {**current, **dict(updates), "symbol": symbol}
    if updates.get("source_reports"):
        merged["source_reports"] = (
            list(current.get("source_reports", []))
            + clean_source_reports(updates["source_reports"])
        )

    today = date.today().isoformat()
    current_time = now_iso()
    if not current:
        merged.setdefault("status", "tracking")
        merged.setdefault("recommended_on", today)
        merged.setdefault("last_researched_on", today)
    merged["source"] = "agent"
    merged["created_at"] = clean_text(current.get("created_at"), 40) or current_time
    merged["updated_at"] = current_time
    item = clean_watch_item(merged)
    if item is None:
        raise ValueError("Tracked research item is empty")

    action = "updated" if matches else "created"
    if matches:
        items[matches[0]] = item
    else:
        if len(items) >= MAX_ITEMS:
            raise ValueError(f"Cannot save more than {MAX_ITEMS} tracked research items")
        items.append(item)
    result = {"schema_version": SCHEMA_VERSION, "updated_at": current_time, "items": items}
    write_watchlist(path, result)
    return action, item


def remove_watch_item(path: Path, symbol_value: object) -> dict[str, Any]:
    payload = read_watchlist(path)
    symbol = normalize_symbol(symbol_value)
    remaining = [item for item in payload["items"] if item["symbol"] != symbol]
    if len(remaining) == len(payload["items"]):
        raise ValueError(f"No tracked research item found for {symbol}")
    current_time = now_iso()
    result = {"schema_version": SCHEMA_VERSION, "updated_at": current_time, "items": remaining}
    write_watchlist(path, result)
    return {"status": "removed", "symbol": symbol, "item_count": len(remaining)}


def show_watchlist(
    path: Path,
    project_root: Path,
    *,
    symbols: Sequence[str] = (),
    statuses: Sequence[str] = (),
    include_archived: bool = False,
) -> dict[str, Any]:
    payload = read_watchlist(path)
    requested_symbols = {normalize_symbol(symbol) for symbol in symbols if normalize_symbol(symbol)}
    requested_statuses = {
        clean_choice(status, "status", STATUSES) for status in statuses if clean_text(status, 40)
    }
    selected = []
    for item in payload["items"]:
        if requested_symbols and item["symbol"] not in requested_symbols:
            continue
        if requested_statuses and item["status"] not in requested_statuses:
            continue
        if not requested_statuses and not include_archived and item["status"] == "archived":
            continue
        selected.append(item)

    warnings: list[str] = []
    for item in selected:
        for report in item["source_reports"]:
            if not (project_root / report).is_file():
                warnings.append(f"{item['symbol']} references a missing report: {report}")
    return {
        "status": "available" if selected else "empty",
        "watchlist_path": str(path),
        "updated_at": payload["updated_at"],
        "requested_symbols": sorted(requested_symbols),
        "requested_statuses": sorted(requested_statuses),
        "item_count": len(selected),
        "items": selected,
        "warnings": warnings,
    }


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-dir", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record and reuse equities selected for continued investment research."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="Show tracked research items")
    _add_project_argument(show)
    show.add_argument("--symbol", action="append", default=[], help="Filter by symbol; repeatable")
    show.add_argument("--status", action="append", choices=STATUSES, default=[])
    show.add_argument("--include-archived", action="store_true")

    upsert = subparsers.add_parser("upsert", help="Create or update one tracked research item")
    _add_project_argument(upsert)
    upsert.add_argument("--symbol", required=True)
    upsert.add_argument("--name")
    upsert.add_argument("--status", choices=STATUSES)
    upsert.add_argument("--research-path", choices=RESEARCH_PATHS)
    upsert.add_argument("--action-label")
    upsert.add_argument("--confidence", choices=CONFIDENCE_LEVELS[1:])
    upsert.add_argument("--thesis")
    upsert.add_argument("--follow-up")
    upsert.add_argument("--invalidation")
    upsert.add_argument("--recommended-on")
    upsert.add_argument("--last-researched-on")
    upsert.add_argument("--next-review-on")
    upsert.add_argument("--source-report", action="append", default=[])
    upsert.add_argument("--notes")

    remove = subparsers.add_parser("remove", help="Permanently remove one tracked research item")
    _add_project_argument(remove)
    remove.add_argument("--symbol", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = project_paths(args.project_dir).root
        path = watchlist_path(root)
        if args.command == "show":
            payload = show_watchlist(
                path,
                root,
                symbols=args.symbol,
                statuses=args.status,
                include_archived=args.include_archived,
            )
        elif args.command == "remove":
            payload = remove_watch_item(path, args.symbol)
        else:
            updates: dict[str, Any] = {"symbol": args.symbol}
            for argument, field in (
                ("name", "name"),
                ("status", "status"),
                ("research_path", "research_path"),
                ("action_label", "action_label"),
                ("confidence", "confidence"),
                ("thesis", "thesis"),
                ("follow_up", "follow_up"),
                ("invalidation", "invalidation"),
                ("recommended_on", "recommended_on"),
                ("last_researched_on", "last_researched_on"),
                ("next_review_on", "next_review_on"),
                ("notes", "notes"),
            ):
                value = getattr(args, argument)
                if value is not None:
                    updates[field] = value
            if args.source_report:
                updates["source_reports"] = args.source_report
            action, item = upsert_watch_item(path, updates)
            payload = {"status": action, "watchlist_path": str(path), "item": item}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
