#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment_research import AssessmentStage, DEFAULT_RESEARCH_DB, ResearchStore


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage institutional-research SQLite schema and audit records.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_RESEARCH_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate", help="Apply idempotent research schema migrations.")
    subparsers.add_parser("stats", help="Show row counts for research tables.")

    assessments = subparsers.add_parser("assessments", help="List persisted stage assessments.")
    assessments.add_argument("--run-id")
    assessments.add_argument("--stage", choices=[stage.value for stage in AssessmentStage])

    claims = subparsers.add_parser("claims", help="List persisted research claims.")
    claims.add_argument("--run-id")
    claims.add_argument("--stage", choices=[stage.value for stage in AssessmentStage])

    outcomes = subparsers.add_parser("outcomes", help="List 20/60/120-day outcome records.")
    outcomes.add_argument("--run-id")
    outcomes.add_argument("--decision-id")
    subparsers.add_parser("outcome-summary", help="Compare outcome quality across all four entry actions.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ResearchStore(args.db_path)
    if args.command == "migrate":
        _print({"db_path": str(args.db_path), "applied_versions": store.migrate()})
        return 0
    if args.command == "stats":
        _print({"db_path": str(args.db_path), "tables": store.table_counts()})
        return 0
    if args.command == "assessments":
        stage = AssessmentStage(args.stage) if args.stage else None
        _print(store.list_assessments(run_id=args.run_id, stage=stage))
        return 0
    if args.command == "claims":
        stage = AssessmentStage(args.stage) if args.stage else None
        _print(store.list_claims(run_id=args.run_id, stage=stage))
        return 0
    if args.command == "outcomes":
        _print(store.list_outcomes(run_id=args.run_id, decision_id=args.decision_id))
        return 0
    if args.command == "outcome-summary":
        _print(store.outcome_quality_summary())
        return 0
    raise RuntimeError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
