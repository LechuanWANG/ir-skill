#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment_research import (
    DEFAULT_RESEARCH_DB,
    EvidenceItem,
    NewsSignal,
    ResearchStore,
    ResearchWorkflow,
    SignalHypothesisMapping,
    VerificationStatus,
    assess_signal_mapping,
    extract_gelonghui_signals,
    ingest_signals,
    to_jsonable,
)
from investment_research.news import DEFAULT_GELONGHUI_URL, load_signal_records


IMPORTANT_SELECTOR = ".live-data-item:has(.desc.is-weight)"


def _print(value: object) -> None:
    print(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2))


def fetch_gelonghui_payload(
    *,
    url: str = DEFAULT_GELONGHUI_URL,
    important_only: bool = True,
    webclaw_binary: str = "webclaw",
    timeout_seconds: int = 90,
) -> str:
    command = [webclaw_binary, url, "--format", "json"]
    if important_only:
        command.extend(("--include", IMPORTANT_SELECTOR))
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError("webclaw is not installed or not available on PATH") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or str(error)
        raise RuntimeError(f"webclaw failed: {detail}") from error
    return result.stdout


def _signal_from_row(row: Mapping[str, Any]) -> NewsSignal:
    return NewsSignal(
        signal_id=str(row["signal_id"]),
        provider=str(row["provider"]),
        external_id=row.get("external_id"),
        content_hash=str(row["content_hash"]),
        published_at=str(row["published_at"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        source_url=str(row["source_url"]),
        important=bool(row["important"]),
        symbols=tuple(row.get("symbols", [])),
        industries=tuple(row.get("industries", [])),
        verification_status=VerificationStatus(str(row["verification_status"])),
        independent_source_count=int(row["independent_source_count"]),
        raw_payload=row.get("raw_payload", {}),
        ingested_at=str(row["ingested_at"]),
    )


def _load_payload(path: Path) -> str | list[dict[str, Any]] | dict[str, Any]:
    if path.suffix.lower() in {".json", ".jsonl", ".ndjson", ".csv"}:
        return load_signal_records(path)
    return path.read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest and map on-demand news signals without building a full-text news warehouse.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_RESEARCH_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="Fetch Gelonghui live signals through Webclaw and persist structured cards.")
    fetch.add_argument("--url", default=DEFAULT_GELONGHUI_URL)
    fetch.add_argument("--all", action="store_true", help="Fetch all live items instead of the important selector.")
    fetch.add_argument("--since-hours", type=int, default=72)
    fetch.add_argument("--webclaw-binary", default="webclaw")
    fetch.add_argument("--timeout-seconds", type=int, default=90)

    ingest = subparsers.add_parser("ingest", help="Ingest a Webclaw JSON/text fixture or normalized JSON/CSV signals.")
    ingest.add_argument("--input", type=Path, required=True)
    ingest.add_argument("--all", action="store_true")
    ingest.add_argument("--since-hours", type=int, default=72)

    parse = subparsers.add_parser("parse", help="Parse a Webclaw JSON/text fixture without persisting it.")
    parse.add_argument("--input", type=Path, required=True)
    parse.add_argument("--all", action="store_true")
    parse.add_argument("--since-hours", type=int, default=72)

    listing = subparsers.add_parser("list", help="List structured signal cards.")
    listing.add_argument("--symbol")
    listing.add_argument("--important-only", action="store_true")
    listing.add_argument("--limit", type=int, default=200)

    mapping = subparsers.add_parser("map", help="Map a signal to a versioned hypothesis or a specific assumption.")
    mapping.add_argument("--signal-id", required=True)
    mapping.add_argument("--hypothesis-id", required=True)
    mapping.add_argument("--thesis-key")
    mapping.add_argument("--assumption-key", default="__thesis__")
    mapping.add_argument("--direction", choices=["positive", "negative", "mixed"], required=True)
    mapping.add_argument(
        "--financial-channel",
        choices=["revenue", "profit", "cashflow", "capital_cost", "risk_premium"],
        required=True,
    )
    mapping.add_argument("--verification-status", choices=[status.value for status in VerificationStatus], required=True)
    mapping.add_argument("--magnitude-low", type=float)
    mapping.add_argument("--magnitude-high", type=float)
    mapping.add_argument("--duration-days", type=int)
    mapping.add_argument("--priced-in-status", default="unknown")
    mapping.add_argument("--relevance", type=float, default=0.5)
    mapping.add_argument("--notes", default="")
    mapping.add_argument("--run-id", help="Also persist the mapped signal as point-in-time run evidence.")

    mappings = subparsers.add_parser("mappings", help="List persisted signal-to-hypothesis mappings.")
    mappings.add_argument("--hypothesis-id")

    query = subparsers.add_parser("query", help="Query signal cards and their hypothesis mappings together.")
    query.add_argument("--symbol")
    query.add_argument("--important-only", action="store_true")
    query.add_argument("--hypothesis-id")
    query.add_argument("--limit", type=int, default=200)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ResearchStore(args.db_path)
    if args.command in {"fetch", "ingest", "parse"}:
        reference = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        if args.command == "fetch":
            payload = fetch_gelonghui_payload(
                url=args.url,
                important_only=not args.all,
                webclaw_binary=args.webclaw_binary,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            payload = _load_payload(args.input)
        signals = extract_gelonghui_signals(
            payload,
            important_only=not args.all,
            since_hours=args.since_hours,
            reference_time=reference,
            content_is_important=not args.all,
        )
        if args.command == "parse":
            _print({"signals": len(signals), "data": signals})
            return 0
        signal_ids = ingest_signals(store, signals)
        _print({"signals": len(signals), "signal_ids": signal_ids, "db_path": str(args.db_path)})
        return 0
    if args.command == "list":
        _print(
            store.list_signals(
                symbol=args.symbol,
                important_only=args.important_only,
                limit=args.limit,
            )
        )
        return 0
    if args.command == "map":
        signal_row = store.get_signal(args.signal_id)
        signal = _signal_from_row(signal_row)
        if VerificationStatus(args.verification_status) != signal.verification_status:
            signal = NewsSignal(
                **{
                    **to_jsonable(signal),
                    "verification_status": VerificationStatus(args.verification_status),
                }
            )
            store.add_signal(signal)
        mapping = SignalHypothesisMapping(
            signal_id=signal.signal_id,
            hypothesis_id=args.hypothesis_id,
            thesis_key=args.thesis_key,
            assumption_key=args.assumption_key,
            direction=args.direction,
            financial_channel=args.financial_channel,
            verification_status=VerificationStatus(args.verification_status),
            magnitude_low=args.magnitude_low,
            magnitude_high=args.magnitude_high,
            duration_days=args.duration_days,
            priced_in_status=args.priced_in_status,
            relevance=args.relevance,
            notes=args.notes,
        )
        mapping_id = store.add_signal_mapping(mapping)
        assessment = assess_signal_mapping(signal, mapping)
        evidence_id = None
        if args.run_id:
            run = store.get_run(args.run_id)
            evidence = EvidenceItem(
                run_id=run.run_id,
                symbol=run.symbol,
                evidence_type="recent_event",
                time_scale="event",
                source_name=signal.provider,
                source_url=signal.source_url,
                source_date=signal.published_at,
                available_at=signal.published_at,
                verification_status=mapping.verification_status,
                payload={
                    "signal": to_jsonable(signal),
                    "mapping": to_jsonable(mapping),
                    "assessment": assessment,
                },
            )
            workflow = ResearchWorkflow(store)
            evidence_id = workflow.add_evidence(evidence)
            store.link_hypothesis_evidence(
                hypothesis_id=args.hypothesis_id,
                evidence_id=evidence_id,
                direction=args.direction,
                relevance=args.relevance,
                magnitude={"low": args.magnitude_low, "high": args.magnitude_high},
                duration_days=args.duration_days,
                priced_in_status=args.priced_in_status,
            )
        _print({"mapping_id": mapping_id, "evidence_id": evidence_id, "assessment": assessment})
        return 0
    if args.command == "mappings":
        _print(store.list_signal_mappings(hypothesis_id=args.hypothesis_id))
        return 0
    if args.command == "query":
        _print(
            {
                "signals": store.list_signals(
                    symbol=args.symbol,
                    important_only=args.important_only,
                    limit=args.limit,
                ),
                "mappings": store.list_signal_mappings(hypothesis_id=args.hypothesis_id),
            }
        )
        return 0
    raise RuntimeError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
