#!/usr/bin/env python3
"""Fetch arbitrary TuShare endpoint data without making research decisions.

Use company and exchange disclosures as the final source for financial-statement
facts. This gateway only retrieves structured secondary-source observations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from market_data_store import (
    DEFAULT_DB_PATH,
    load_research_observations,
    write_research_observations,
    write_tushare_capabilities,
)
from tushare_sync import create_tushare_client


DEFAULT_PREVIEW_ROWS = 20
SENSITIVE_PARAM_NAMES = frozenset(
    {"access_token", "api_key", "apikey", "password", "secret", "token"}
)


def _endpoint_name(value: str) -> str:
    endpoint = value.strip()
    if not endpoint.isidentifier() or endpoint.startswith("_"):
        raise argparse.ArgumentTypeError("endpoint must be a public Python identifier")
    return endpoint


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _json_object(text: str, source: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} must contain valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{source} must contain one JSON object")
    if not all(isinstance(key, str) and key.strip() for key in value):
        raise ValueError(f"{source} keys must be non-empty strings")
    return value


def _request_params(args: argparse.Namespace) -> dict[str, Any]:
    if args.params_file is not None:
        text = args.params_file.read_text(encoding="utf-8")
        params = _json_object(text, str(args.params_file))
    elif args.params is not None:
        params = _json_object(args.params, "--params")
    else:
        params = {}

    if args.fields is not None:
        fields = args.fields.strip()
        if not fields:
            raise ValueError("--fields cannot be empty")
        if "fields" in params:
            raise ValueError("pass fields through either --fields or --params, not both")
        params["fields"] = fields
    return params


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in SENSITIVE_PARAM_NAMES else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def request_endpoint(client: Any, endpoint: str, params: dict[str, Any]) -> pd.DataFrame:
    method = getattr(client, endpoint, None)
    if not callable(method):
        raise ValueError(f"TuShare client does not expose endpoint '{endpoint}'")
    try:
        frame = method(**params)
    except Exception as exc:
        raise RuntimeError(f"TuShare endpoint '{endpoint}' failed: {exc}") from exc
    if not isinstance(frame, pd.DataFrame):
        raise RuntimeError(f"TuShare endpoint '{endpoint}' returned {type(frame).__name__}, not a DataFrame")
    return frame


def _write_output(frame: pd.DataFrame, output: Path) -> Path:
    suffix = output.suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise ValueError("--output must end in .csv or .json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        frame.to_csv(output, index=False)
    else:
        output.write_text(
            frame.to_json(orient="records", force_ascii=False, date_format="iso"),
            encoding="utf-8",
        )
    return output


def _preview_records(frame: pd.DataFrame, preview_rows: int) -> list[dict[str, Any]]:
    if preview_rows == 0 or frame.empty:
        return []
    return json.loads(
        frame.head(preview_rows).to_json(orient="records", force_ascii=False, date_format="iso")
    )


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


def _dataset_name(endpoint: str, requested_dataset: str | None) -> str:
    dataset = (requested_dataset or endpoint).strip()
    if not dataset:
        raise ValueError("--dataset cannot be empty")
    return dataset


def _run_fetch(args: argparse.Namespace) -> int:
    params = _request_params(args)
    dataset = _dataset_name(args.endpoint, args.dataset)
    if args.dry_run:
        _print_json(
            {
                "mode": "dry_run",
                "endpoint": args.endpoint,
                "params": _redact(params),
                "dataset": dataset,
                "cache": args.cache,
            }
        )
        return 0

    frame = request_endpoint(create_tushare_client(), args.endpoint, params)
    cached_rows = 0
    if args.cache:
        cached_rows = write_research_observations(dataset, frame, db_path=args.db_path)
    output = _write_output(frame, args.output) if args.output is not None else None
    _print_json(
        {
            "endpoint": args.endpoint,
            "dataset": dataset,
            "rows": len(frame),
            "columns": list(frame.columns),
            "cached_rows": cached_rows,
            "output": str(output) if output is not None else None,
            "preview": _preview_records(frame, args.preview_rows),
        }
    )
    return 0


def _run_probe(args: argparse.Namespace) -> int:
    params = _request_params(args)
    if args.dry_run:
        _print_json(
            {
                "mode": "dry_run",
                "endpoint": args.endpoint,
                "params": _redact(params),
                "cache": args.cache,
            }
        )
        return 0

    try:
        client = create_tushare_client()
    except RuntimeError as exc:
        record: dict[str, Any] = {
            "endpoint": args.endpoint,
            "status": "error",
            "error": str(exc),
        }
        exit_code = 2
    else:
        try:
            frame = request_endpoint(client, args.endpoint, params)
        except (RuntimeError, ValueError) as exc:
            record = {
                "endpoint": args.endpoint,
                "status": "unavailable",
                "error": str(exc),
            }
            exit_code = 1
        else:
            record = {
                "endpoint": args.endpoint,
                "status": "available",
                "rows": len(frame),
                "columns": list(frame.columns),
            }
            exit_code = 0

    if args.cache:
        cached_record = {
            key: value
            for key, value in record.items()
            if key != "error"
        }
        if "error" in record:
            cached_record["error_type"] = "endpoint_request_failed"
        write_tushare_capabilities([cached_record], db_path=args.db_path)
    _print_json(record)
    return exit_code


def _run_cache(args: argparse.Namespace) -> int:
    frame = load_research_observations(
        db_path=args.db_path,
        dataset=args.dataset,
        symbols=args.symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        available_as_of=args.available_as_of,
        observed_as_of=args.observed_as_of,
        include_revisions=args.include_revisions,
        limit=args.limit,
    )
    output = _write_output(frame, args.output) if args.output is not None else None
    _print_json(
        {
            "dataset": args.dataset,
            "rows": len(frame),
            "columns": list(frame.columns),
            "output": str(output) if output is not None else None,
            "preview": _preview_records(frame, args.preview_rows),
        }
    )
    return 0


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("endpoint", type=_endpoint_name)
    params_group = parser.add_mutually_exclusive_group()
    params_group.add_argument("--params", help="JSON object passed to the TuShare endpoint")
    params_group.add_argument("--params-file", type=Path, help="Path to a JSON object of endpoint parameters")
    parser.add_argument("--fields", help="Optional comma-separated TuShare fields")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--cache", action="store_true", help="Persist response metadata and rows to SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the request without calling TuShare")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call arbitrary TuShare endpoints without screening or investment decisions."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one endpoint with explicit parameters")
    _add_request_arguments(fetch_parser)
    fetch_parser.add_argument("--dataset", help="Optional cache dataset name; defaults to the endpoint")
    fetch_parser.add_argument("--output", type=Path, help="Optional .csv or .json output path")
    fetch_parser.add_argument("--preview-rows", type=_non_negative_int, default=DEFAULT_PREVIEW_ROWS)

    probe_parser = subparsers.add_parser("probe", help="Probe one endpoint with a minimal explicit request")
    _add_request_arguments(probe_parser)

    cache_parser = subparsers.add_parser("cache", help="Read rows previously stored by fetch --cache")
    cache_parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    cache_parser.add_argument("--dataset")
    cache_parser.add_argument("--symbols", nargs="+")
    cache_parser.add_argument("--start-date")
    cache_parser.add_argument("--end-date")
    cache_parser.add_argument("--available-as-of")
    cache_parser.add_argument("--observed-as-of")
    cache_parser.add_argument("--include-revisions", action="store_true")
    cache_parser.add_argument("--limit", type=_positive_int, default=200)
    cache_parser.add_argument("--output", type=Path, help="Optional .csv or .json output path")
    cache_parser.add_argument("--preview-rows", type=_non_negative_int, default=DEFAULT_PREVIEW_ROWS)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            return _run_fetch(args)
        if args.command == "probe":
            return _run_probe(args)
        return _run_cache(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
