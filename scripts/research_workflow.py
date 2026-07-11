#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_SCRIPTS = _ROOT / "scripts"
for path in (_SRC, _SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from investment_research import (
    AssessmentStage,
    ClaimStatus,
    ContextStatus,
    DEFAULT_LONG_TERM_DIMENSIONS,
    DEFAULT_RESEARCH_DB,
    DecisionCard,
    DimensionResult,
    DimensionStatus,
    EntryAction,
    EvidenceItem,
    LongTermVerdict,
    OutcomeSnapshot,
    PortfolioAction,
    ResearchClaim,
    ResearchRun,
    ResearchStatus,
    ResearchStore,
    ResearchWorkflow,
    VerificationStatus,
    WorkflowStage,
    assess_relative_overheat,
    build_decision_report,
    prepare_adjusted_bars,
    render_decision_markdown,
    resolve_trade_horizon_dates,
    to_jsonable,
    write_decision_report,
)
from market_data_store import (
    load_daily_basic_history,
    load_daily_matrices,
    load_factor_inputs,
    load_research_observations,
)
from tushare_research import build_staged_research_plan


def _print(value: object) -> None:
    print(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2))


def _read_json_value(value: str | None, default: Any) -> Any:
    if not value:
        return default
    path = Path(value)
    text = path.read_text(encoding="utf-8") if path.exists() else value
    return json.loads(text)


def _read_table(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if path.suffix.lower() in {".json", ".jsonl", ".ndjson"}:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                payload = payload.get("data") or payload.get("rows") or [payload]
            return pd.DataFrame(payload)
        return pd.DataFrame(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return pd.read_csv(path)


def _load_dimensions(args: argparse.Namespace) -> list[DimensionResult]:
    if args.dimensions_file:
        records = _read_json_value(str(args.dimensions_file), [])
        return [
            DimensionResult(
                name=str(record["name"]),
                status=DimensionStatus(str(record["status"])),
                rationale=str(record["rationale"]),
                evidence_ids=tuple(record.get("evidence_ids", [])),
                metrics=record.get("metrics", {}),
            )
            for record in records
        ]
    dimensions = []
    for value in args.dimension or []:
        name, status, rationale = (value.split(":", 2) + [""])[:3]
        dimensions.append(
            DimensionResult(
                name=name,
                status=DimensionStatus(status),
                rationale=rationale or f"{name} assessed as {status}",
            )
        )
    return dimensions


def _load_cached_frame(
    *,
    db_path: Path,
    dataset: str,
    symbol: str,
    as_of: str,
    limit: int = 5000,
) -> pd.DataFrame:
    try:
        return load_research_observations(
            db_path=db_path,
            dataset=dataset,
            symbols=[symbol],
            end_date=as_of,
            available_as_of=as_of,
            limit=limit,
        )
    except (FileNotFoundError, ValueError):
        return pd.DataFrame()


def _add_common_db_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", type=Path, default=DEFAULT_RESEARCH_DB)


def _snapshot_confidence(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("snapshot confidence cannot be boolean")
    if isinstance(value, (int, float)):
        confidence = float(value)
    else:
        normalized = str(value).strip().lower()
        labels = {"high": 0.8, "medium": 0.6, "low": 0.4}
        if normalized in labels:
            return labels[normalized]
        try:
            confidence = float(normalized)
        except ValueError as error:
            raise ValueError(f"unsupported snapshot confidence: {value}") from error
    if not 0 <= confidence <= 1:
        raise ValueError("snapshot confidence must be between 0 and 1")
    return confidence


def _import_decision_snapshot(
    *,
    store: ResearchStore,
    input_path: Path,
) -> dict[str, object]:
    payload = _read_json_value(str(input_path), {})
    if not isinstance(payload, Mapping):
        raise ValueError("decision snapshot must be a JSON object")
    records = payload.get("decisions")
    if not isinstance(records, list):
        raise ValueError("decision snapshot must contain a decisions list")

    imported_ids: list[str] = []
    skipped_ids: list[str] = []
    candidate_source = str(payload.get("candidate_source") or "imported_snapshot")
    request_type = str(payload.get("request_type") or "imported historical decision")
    source_path = str(input_path.resolve())

    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise ValueError(f"decisions[{index}] must be a JSON object")
        decision_id = str(raw_record.get("decision_id") or "").strip()
        symbol = str(raw_record.get("symbol") or "").strip()
        as_of = str(raw_record.get("as_of") or payload.get("as_of") or "").strip()
        if not decision_id or not symbol or not as_of:
            raise ValueError(
                f"decisions[{index}] requires decision_id, symbol, and as_of"
            )
        try:
            store.get_decision(decision_id=decision_id)
        except KeyError:
            pass
        else:
            skipped_ids.append(decision_id)
            continue

        long_term_verdict = LongTermVerdict(str(raw_record["long_term_status"]))
        entry_action = EntryAction(str(raw_record["entry_action"]))
        portfolio_action = PortfolioAction(
            str(raw_record.get("portfolio_action") or PortfolioAction.NOT_APPLICABLE.value)
        )
        wait_conditions = tuple(str(item) for item in raw_record.get("waiting_conditions", []))
        run_id = f"snapshot_{decision_id}"
        run = ResearchRun(
            run_id=run_id,
            symbol=symbol,
            as_of=as_of,
            intent=request_type,
            stage=WorkflowStage.DECIDED,
            research_status=ResearchStatus.DECISION_READY,
            metadata={
                "candidate_source": candidate_source,
                "company_name": raw_record.get("name"),
                "holding_horizon": payload.get("holding_horizon"),
                "imported_from_snapshot": source_path,
            },
        )
        try:
            existing_run = store.get_run(run_id)
        except KeyError:
            store.create_run(run)
        else:
            if existing_run.symbol != symbol or existing_run.as_of != as_of:
                raise ValueError(f"snapshot run identity conflict: {run_id}")
            run = existing_run

        decision = DecisionCard(
            decision_id=decision_id,
            run_id=run.run_id,
            symbol=symbol,
            as_of=as_of,
            long_term_verdict=long_term_verdict,
            entry_action=entry_action,
            portfolio_action=portfolio_action,
            rationale=str(
                raw_record.get("rationale")
                or (
                    "历史快照导入：长期状态为 "
                    f"{long_term_verdict.value}，入场行动为 {entry_action.value}。"
                )
            ),
            wait_conditions=wait_conditions,
            falsification_conditions=tuple(
                str(item) for item in raw_record.get("falsification_conditions", [])
            ),
            next_review_date=raw_record.get("next_validation_date"),
            holding_horizon_months=run.horizon_months,
            candidate_source=candidate_source,
            anti_chase_flags=tuple(
                str(item) for item in raw_record.get("anti_chase_flags", [])
            ),
            confidence=_snapshot_confidence(raw_record.get("confidence")),
            blocking_evidence=wait_conditions,
            metadata={
                "company_name": raw_record.get("name"),
                "request_type": request_type,
                "snapshot_confidence": raw_record.get("confidence"),
                "imported_from_snapshot": source_path,
            },
            sources=(source_path,),
        )
        store.save_decision(decision)
        imported_ids.append(decision_id)

    return {
        "db_path": str(store.db_path),
        "input": source_path,
        "imported": len(imported_ids),
        "skipped": len(skipped_ids),
        "imported_decision_ids": imported_ids,
        "skipped_decision_ids": skipped_ids,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the long-term-first institutional research workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate", help="Apply idempotent research schema migrations.")
    _add_common_db_path(migrate)

    snapshot_import = subparsers.add_parser(
        "snapshot-import",
        help="Import historical decision cards from a report snapshot.",
    )
    _add_common_db_path(snapshot_import)
    snapshot_import.add_argument("--input", type=Path, required=True)

    staged_plan = subparsers.add_parser("staged-plan", help="Build the mandatory long-term-first TuShare plan.")
    staged_plan.add_argument("--symbols", nargs="+", required=True)
    staged_plan.add_argument("--as-of", required=True)
    staged_plan.add_argument("--current-profile", nargs="*", default=["market-context", "timing-liquidity"])
    staged_plan.add_argument("--index-codes", nargs="*", default=[])
    staged_plan.add_argument("--lookback-days", type=int, default=0)

    start = subparsers.add_parser("start", help="Create a research run before writing evidence or assessments.")
    _add_common_db_path(start)
    start.add_argument("--symbol", required=True)
    start.add_argument("--as-of", required=True)
    start.add_argument("--intent", required=True)
    start.add_argument("--horizon-months", type=int, default=36)
    start.add_argument("--metadata-json")

    hypothesis = subparsers.add_parser("hypothesis-add", help="Add a new version of a long-term hypothesis.")
    _add_common_db_path(hypothesis)
    hypothesis.add_argument("--symbol", required=True)
    hypothesis.add_argument("--thesis-key", required=True)
    hypothesis.add_argument("--statement", required=True)
    hypothesis.add_argument("--return-source", required=True)
    hypothesis.add_argument("--falsification", required=True)
    hypothesis.add_argument("--metric", action="append", default=[])
    hypothesis.add_argument("--horizon-months", type=int, default=36)
    hypothesis.add_argument("--confidence", type=float, default=0.5)
    hypothesis.add_argument("--next-review-date", required=True)

    evidence = subparsers.add_parser("evidence-add", help="Persist point-in-time evidence for a research run.")
    _add_common_db_path(evidence)
    evidence.add_argument("--run-id", required=True)
    evidence.add_argument("--type", required=True)
    evidence.add_argument("--time-scale", required=True)
    evidence.add_argument("--source-name", required=True)
    evidence.add_argument("--source-url", required=True)
    evidence.add_argument("--source-date", required=True)
    evidence.add_argument("--available-at", required=True)
    evidence.add_argument("--verification-status", choices=[status.value for status in VerificationStatus], default="official")
    evidence.add_argument("--payload-json")

    evidence_link = subparsers.add_parser("evidence-link", help="Link evidence to a specific long-term hypothesis.")
    _add_common_db_path(evidence_link)
    evidence_link.add_argument("--hypothesis-id", required=True)
    evidence_link.add_argument("--evidence-id", required=True)
    evidence_link.add_argument("--direction", required=True)
    evidence_link.add_argument("--relevance", type=float, required=True)
    evidence_link.add_argument("--magnitude-json")
    evidence_link.add_argument("--duration-days", type=int)
    evidence_link.add_argument("--priced-in-status", default="unknown")

    long_term = subparsers.add_parser("long-term-assess", help="Evaluate and persist the mandatory long-term gate.")
    _add_common_db_path(long_term)
    long_term.add_argument("--run-id", required=True)
    long_term.add_argument("--years-covered", type=float, required=True)
    long_term.add_argument("--dimensions-file", type=Path)
    long_term.add_argument("--dimension", action="append", help="name:status:rationale")
    long_term.add_argument("--rationale", required=True)
    long_term.add_argument("--structural-risk", action="append", default=[])
    long_term.add_argument("--hard-veto", action="append", default=[])
    long_term.add_argument("--missing-evidence", action="append", default=[])
    long_term.add_argument("--blocking-evidence", action="append", default=[])
    long_term.add_argument("--confidence-limiter", action="append", default=[])
    long_term.add_argument("--monitoring-item", action="append", default=[])
    long_term.add_argument("--confidence", type=float, default=0.5)
    long_term.add_argument("--existing-position", action="store_true")
    long_term.add_argument("--portfolio-role")
    long_term.add_argument("--portfolio-action", choices=[action.value for action in PortfolioAction])
    long_term.add_argument("--next-review-date")
    long_term.add_argument("--change-reason", action="append", default=[])
    long_term.add_argument("--methodology-change", action="store_true")

    current = subparsers.add_parser("current-assess", help="Evaluate current event, macro, industry, valuation and entry conditions.")
    _add_common_db_path(current)
    current.add_argument("--run-id", required=True)
    current.add_argument("--bars-file", type=Path)
    current.add_argument("--valuation-file", type=Path)
    current.add_argument("--market-snapshot-file", type=Path)
    current.add_argument("--industry-snapshot-file", type=Path)
    current.add_argument("--peer-valuation-file", type=Path)
    current.add_argument("--benchmark-file", type=Path)
    current.add_argument("--margin-file", type=Path)
    current.add_argument("--earnings-revision-positive", action="store_true")
    for name in ("recent-event", "macro", "industry", "valuation", "technical-liquidity"):
        current.add_argument(
            f"--{name}-status",
            choices=[status.value for status in ContextStatus],
            default=ContextStatus.MISSING.value,
        )
    current.add_argument("--evidence-complete", action="store_true")
    current.add_argument("--odds-adequate", action="store_true")
    current.add_argument("--rationale", required=True)
    current.add_argument("--recent-event-assessment", default="")
    current.add_argument("--macro-assessment", default="")
    current.add_argument("--industry-assessment", default="")
    current.add_argument("--valuation-assessment", default="")
    current.add_argument("--technical-liquidity-assessment", default="")
    current.add_argument("--base-case", default="")
    current.add_argument("--upside-case", default="")
    current.add_argument("--downside-case", default="")
    current.add_argument("--acceptable-price-low", type=float)
    current.add_argument("--acceptable-price-high", type=float)
    current.add_argument("--wait-condition", action="append", default=[])
    current.add_argument("--entry-trigger", action="append", default=[])
    current.add_argument("--key-risk", action="append", default=[])
    current.add_argument("--hard-current-risk", action="append", default=[])
    current.add_argument("--liquidity-unacceptable", action="store_true")
    current.add_argument(
        "--portfolio-fit",
        choices=["not_assessed", "fits", "constrained", "incompatible"],
        default="not_assessed",
    )
    current.add_argument("--portfolio-constraint", action="append", default=[])
    current.add_argument("--concentration-impact")
    current.add_argument("--liquidity-exit-assessment")
    current.add_argument("--alternative-cost")
    current.add_argument("--missing-evidence", action="append", default=[])
    current.add_argument("--blocking-evidence", action="append", default=[])
    current.add_argument("--confidence-limiter", action="append", default=[])
    current.add_argument("--monitoring-item", action="append", default=[])
    current.add_argument("--price-regime", default="not_assessed")
    current.add_argument("--opportunity-cost-assessment")
    current.add_argument("--total-shareholder-return-3y", type=float)
    current.add_argument("--existing-position", action="store_true")
    current.add_argument("--portfolio-role")
    current.add_argument("--portfolio-action", choices=[action.value for action in PortfolioAction])
    current.add_argument("--next-review-date")
    current.add_argument("--change-reason", action="append", default=[])
    current.add_argument("--methodology-change", action="store_true")

    claim = subparsers.add_parser("claim-add", help="Persist a challenged research claim.")
    _add_common_db_path(claim)
    claim.add_argument("--run-id", required=True)
    claim.add_argument("--stage", choices=[stage.value for stage in AssessmentStage], required=True)
    claim.add_argument("--time-scale", required=True)
    claim.add_argument("--statement", required=True)
    claim.add_argument("--proposer", required=True)
    claim.add_argument("--hypothesis-id")
    claim.add_argument("--supporting-evidence", action="append", default=[])
    claim.add_argument("--contrary-evidence", action="append", default=[])
    claim.add_argument("--challenger")
    claim.add_argument("--response")
    claim.add_argument("--initial-confidence", type=float, required=True)
    claim.add_argument("--final-confidence", type=float, required=True)
    claim.add_argument("--unresolved", action="append", default=[])
    claim.add_argument("--status", choices=[status.value for status in ClaimStatus], default="open")

    report = subparsers.add_parser("report", help="Render all four action buckets as JSON or Markdown.")
    _add_common_db_path(report)
    report.add_argument("--output", type=Path)
    report.add_argument("--format", choices=["json", "md"], default="json")

    show = subparsers.add_parser("show", help="Show a complete research run with audit links.")
    _add_common_db_path(show)
    show.add_argument("--run-id", required=True)

    outcome = subparsers.add_parser("outcome-record", help="Record a 20/60/120-day outcome.")
    _add_common_db_path(outcome)
    outcome.add_argument("--decision-id", required=True)
    outcome.add_argument("--horizon-days", type=int, choices=[20, 60, 120], required=True)
    outcome.add_argument("--target-date", required=True)
    outcome.add_argument("--actual-date", required=True)
    outcome.add_argument("--price-return", type=float)
    outcome.add_argument("--benchmark-return", type=float)
    outcome.add_argument("--industry-return", type=float)
    outcome.add_argument("--max-adverse-excursion", type=float)
    outcome.add_argument("--max-favorable-excursion", type=float)
    outcome.add_argument("--realized-volatility", type=float)
    outcome.add_argument("--liquidity-change", type=float)
    outcome.add_argument("--valuation-change", type=float)
    outcome.add_argument("--earnings-revision", type=float)
    outcome.add_argument("--waiting-condition-status")
    outcome.add_argument("--first-acceptable-price-date")
    outcome.add_argument("--first-acceptable-price", type=float)
    outcome.add_argument("--catalyst-status")
    outcome.add_argument("--falsification-status")
    outcome.add_argument("--thesis-status")
    outcome.add_argument("--entry-action-review")
    for quality_field in ("research-quality", "timing-quality", "risk-control-quality"):
        outcome.add_argument(
            f"--{quality_field}",
            choices=["strong", "adequate", "weak", "unrateable"],
        )
    outcome.add_argument(
        "--process-adherence",
        choices=["passed", "deviated", "unverified"],
    )
    outcome.add_argument("--data-source", action="append", default=[])
    outcome.add_argument("--notes", default="")

    due = subparsers.add_parser("outcomes-due", help="List due outcome snapshots.")
    _add_common_db_path(due)
    due.add_argument("--as-of", required=True)

    summary = subparsers.add_parser("outcomes-summary", help="Compare recorded outcome quality across all four actions.")
    _add_common_db_path(summary)

    reschedule = subparsers.add_parser("outcomes-reschedule", help="Replace approximate dates with exchange-calendar dates.")
    _add_common_db_path(reschedule)
    reschedule.add_argument("--decision-id", required=True)
    reschedule.add_argument("--date", action="append", default=[], help="20=YYYY-MM-DD")
    reschedule.add_argument("--trade-cal-file", type=Path, help="CSV/JSON with cal_date and is_open from TuShare trade_cal.")
    return parser


def _current_overheat(args: argparse.Namespace, store: ResearchStore):
    run = store.get_run(args.run_id)
    bars = _read_table(args.bars_file)
    valuation_history = _read_table(args.valuation_file)
    margin_history = _read_table(args.margin_file)
    normalized_as_of = (
        f"{run.as_of[:4]}-{run.as_of[4:6]}-{run.as_of[6:8]}"
        if run.as_of.isdigit() and len(run.as_of) == 8
        else run.as_of[:10]
    )
    market_start = (pd.Timestamp(normalized_as_of) - pd.Timedelta(days=220)).date().isoformat()
    market_prices = pd.DataFrame()
    market_volumes = pd.DataFrame()
    if any(
        path is None
        for path in (
            args.bars_file,
            args.market_snapshot_file,
            args.industry_snapshot_file,
            args.peer_valuation_file,
        )
    ):
        try:
            market_prices, market_volumes = load_daily_matrices(
                db_path=args.db_path,
                start_date=market_start,
                end_date=run.as_of,
            )
        except (FileNotFoundError, ValueError):
            pass
    if bars is None:
        daily = _load_cached_frame(db_path=args.db_path, dataset="daily", symbol=run.symbol, as_of=run.as_of)
        adjustment = _load_cached_frame(db_path=args.db_path, dataset="adj_factor", symbol=run.symbol, as_of=run.as_of)
        if daily.empty and run.symbol in market_prices.columns:
            bars = pd.DataFrame(
                {
                    "trade_date": market_prices.index,
                    "close_qfq": market_prices[run.symbol].to_numpy(),
                    "volume": (
                        market_volumes[run.symbol].to_numpy()
                        if run.symbol in market_volumes.columns
                        else pd.NA
                    ),
                }
            )
        else:
            bars = prepare_adjusted_bars(daily, adjustment)
    else:
        bars = prepare_adjusted_bars(bars)
    if valuation_history is None:
        valuation_history = _load_cached_frame(
            db_path=args.db_path,
            dataset="daily_basic",
            symbol=run.symbol,
            as_of=run.as_of,
        )
        if valuation_history.empty:
            try:
                valuation_history = load_daily_basic_history(
                    db_path=args.db_path,
                    as_of=run.as_of,
                    symbols=[run.symbol],
                )
            except (FileNotFoundError, ValueError):
                pass
    if margin_history is None:
        margin_history = _load_cached_frame(
            db_path=args.db_path,
            dataset="margin_detail",
            symbol=run.symbol,
            as_of=run.as_of,
        )
    benchmark_frame = _read_table(args.benchmark_file)
    benchmark_close = None
    if benchmark_frame is not None and not benchmark_frame.empty:
        for column in ("close", "close_qfq"):
            if column in benchmark_frame.columns:
                benchmark_close = pd.to_numeric(benchmark_frame[column], errors="coerce")
                break
    market_snapshot = _read_table(args.market_snapshot_file)
    industry_snapshot = _read_table(args.industry_snapshot_file)
    peer_valuation_snapshot = _read_table(args.peer_valuation_file)
    factor_inputs = pd.DataFrame()
    if market_snapshot is None and len(market_prices) > 20:
        market_snapshot = pd.DataFrame(
            {
                "ts_code": market_prices.columns,
                "return_20d": (
                    market_prices.ffill().iloc[-1] / market_prices.ffill().iloc[-21] - 1
                ).to_numpy(),
            }
        ).dropna(subset=["return_20d"])
    if industry_snapshot is None or peer_valuation_snapshot is None:
        try:
            factor_inputs = load_factor_inputs(db_path=args.db_path, as_of=run.as_of)
        except (FileNotFoundError, ValueError):
            factor_inputs = pd.DataFrame()
    if not factor_inputs.empty and "industry" in factor_inputs.columns:
        target_rows = factor_inputs.loc[factor_inputs["ts_code"].astype(str) == run.symbol]
        target_industry = None if target_rows.empty else target_rows.iloc[-1].get("industry")
        industry_members = factor_inputs.loc[factor_inputs["industry"] == target_industry]
        if industry_snapshot is None and len(market_prices) > 60 and target_industry is not None:
            return_60d = market_prices.ffill().iloc[-1] / market_prices.ffill().iloc[-61] - 1
            industry_snapshot = pd.DataFrame(
                {
                    "ts_code": return_60d.index,
                    "return_60d": return_60d.to_numpy(),
                }
            )
            industry_snapshot = industry_snapshot.merge(
                industry_members[["ts_code"]],
                on="ts_code",
                how="inner",
            )
        if peer_valuation_snapshot is None:
            peer_columns = [
                column
                for column in ("ts_code", "pe_ttm", "pb", "ps_ttm")
                if column in industry_members.columns
            ]
            peer_valuation_snapshot = industry_members[peer_columns].copy()
    return assess_relative_overheat(
        bars,
        valuation_history=valuation_history,
        market_snapshot=market_snapshot,
        industry_snapshot=industry_snapshot,
        peer_valuation_snapshot=peer_valuation_snapshot,
        benchmark_close=benchmark_close,
        margin_history=margin_history,
        earnings_revision_positive=args.earnings_revision_positive,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "staged-plan":
        _print(
            build_staged_research_plan(
                symbols=args.symbols,
                as_of=args.as_of,
                current_profiles=args.current_profile,
                lookback_days=args.lookback_days,
                index_codes=args.index_codes,
            )
        )
        return 0

    store = ResearchStore(args.db_path)
    workflow = ResearchWorkflow(store)
    if args.command == "migrate":
        _print({"db_path": str(args.db_path), "applied_versions": store.migrate()})
        return 0
    if args.command == "snapshot-import":
        _print(_import_decision_snapshot(store=store, input_path=args.input))
        return 0
    if args.command == "start":
        run = workflow.start_run(
            symbol=args.symbol,
            as_of=args.as_of,
            intent=args.intent,
            horizon_months=args.horizon_months,
            metadata=_read_json_value(args.metadata_json, {}),
        )
        _print(run)
        return 0
    if args.command == "hypothesis-add":
        hypothesis = store.add_hypothesis(
            symbol=args.symbol,
            thesis_key=args.thesis_key,
            statement=args.statement,
            return_source=args.return_source,
            falsification_condition=args.falsification,
            horizon_months=args.horizon_months,
            confidence=args.confidence,
            validation_metrics=args.metric,
            next_review_date=args.next_review_date,
        )
        _print(hypothesis)
        return 0
    if args.command == "evidence-add":
        run = store.get_run(args.run_id)
        evidence = EvidenceItem(
            run_id=run.run_id,
            symbol=run.symbol,
            evidence_type=args.type,
            time_scale=args.time_scale,
            source_name=args.source_name,
            source_url=args.source_url,
            source_date=args.source_date,
            available_at=args.available_at,
            verification_status=VerificationStatus(args.verification_status),
            payload=_read_json_value(args.payload_json, {}),
        )
        workflow.add_evidence(evidence)
        _print(evidence)
        return 0
    if args.command == "evidence-link":
        store.link_hypothesis_evidence(
            hypothesis_id=args.hypothesis_id,
            evidence_id=args.evidence_id,
            direction=args.direction,
            relevance=args.relevance,
            magnitude=_read_json_value(args.magnitude_json, {}),
            duration_days=args.duration_days,
            priced_in_status=args.priced_in_status,
        )
        _print({"hypothesis_id": args.hypothesis_id, "evidence_id": args.evidence_id})
        return 0
    if args.command == "long-term-assess":
        dimensions = _load_dimensions(args)
        assessment, decision = workflow.evaluate_long_term(
            args.run_id,
            years_covered=args.years_covered,
            dimensions=dimensions,
            rationale=args.rationale,
            structural_risks=args.structural_risk,
            hard_vetoes=args.hard_veto,
            missing_evidence=args.missing_evidence,
            blocking_evidence=args.blocking_evidence,
            confidence_limiters=args.confidence_limiter,
            monitoring_items=args.monitoring_item,
            confidence=args.confidence,
            existing_position=args.existing_position,
            portfolio_role=args.portfolio_role,
            portfolio_action_override=(
                PortfolioAction(args.portfolio_action) if args.portfolio_action else None
            ),
            next_review_date=args.next_review_date,
            change_reasons=args.change_reason,
            methodology_change=args.methodology_change,
        )
        _print({"assessment": assessment, "decision": decision})
        return 0
    if args.command == "current-assess":
        overheat = _current_overheat(args, store)
        current, decision = workflow.evaluate_current(
            args.run_id,
            overheat=overheat,
            recent_event_status=ContextStatus(args.recent_event_status),
            macro_status=ContextStatus(args.macro_status),
            industry_status=ContextStatus(args.industry_status),
            valuation_status=ContextStatus(args.valuation_status),
            technical_liquidity_status=ContextStatus(args.technical_liquidity_status),
            evidence_complete=args.evidence_complete,
            odds_adequate=args.odds_adequate,
            rationale=args.rationale,
            recent_event_assessment=args.recent_event_assessment,
            macro_assessment=args.macro_assessment,
            industry_assessment=args.industry_assessment,
            valuation_assessment=args.valuation_assessment,
            technical_liquidity_assessment=args.technical_liquidity_assessment,
            base_case=args.base_case,
            upside_case=args.upside_case,
            downside_case=args.downside_case,
            acceptable_price_low=args.acceptable_price_low,
            acceptable_price_high=args.acceptable_price_high,
            wait_conditions=args.wait_condition,
            entry_triggers=args.entry_trigger,
            key_risks=args.key_risk,
            hard_current_risks=args.hard_current_risk,
            liquidity_unacceptable=args.liquidity_unacceptable,
            portfolio_fit=args.portfolio_fit,
            portfolio_constraints=args.portfolio_constraint,
            concentration_impact=args.concentration_impact,
            liquidity_exit_assessment=args.liquidity_exit_assessment,
            alternative_cost=args.alternative_cost,
            missing_evidence=args.missing_evidence,
            blocking_evidence=args.blocking_evidence,
            confidence_limiters=args.confidence_limiter,
            monitoring_items=args.monitoring_item,
            price_regime=args.price_regime,
            opportunity_cost_assessment=args.opportunity_cost_assessment,
            total_shareholder_return_3y=args.total_shareholder_return_3y,
            existing_position=args.existing_position,
            portfolio_role=args.portfolio_role,
            portfolio_action_override=(
                PortfolioAction(args.portfolio_action) if args.portfolio_action else None
            ),
            next_review_date=args.next_review_date,
            change_reasons=args.change_reason,
            methodology_change=args.methodology_change,
        )
        _print({"overheat": overheat, "assessment": current, "decision": decision})
        return 0
    if args.command == "claim-add":
        claim = ResearchClaim(
            run_id=args.run_id,
            stage=AssessmentStage(args.stage),
            time_scale=args.time_scale,
            statement=args.statement,
            proposer=args.proposer,
            hypothesis_id=args.hypothesis_id,
            supporting_evidence=tuple(args.supporting_evidence),
            contrary_evidence=tuple(args.contrary_evidence),
            challenger=args.challenger,
            response=args.response,
            initial_confidence=args.initial_confidence,
            final_confidence=args.final_confidence,
            unresolved_questions=tuple(args.unresolved),
            status=ClaimStatus(args.status),
        )
        workflow.add_claim(claim)
        _print(claim)
        return 0
    if args.command == "report":
        decisions = store.list_decisions(latest_per_symbol=True)
        research_queue = store.list_runs(
            statuses=(ResearchStatus.QUEUED, ResearchStatus.IN_PROGRESS, ResearchStatus.STALE),
            latest_per_symbol=True,
        )
        if args.output:
            output = args.output
            if output.suffix == "":
                output = output.with_suffix(".md" if args.format == "md" else ".json")
            write_decision_report(decisions, output, research_queue=research_queue)
            _print(
                {
                    "output": str(output),
                    "counts": build_decision_report(
                        decisions,
                        research_queue=research_queue,
                    )["counts"],
                }
            )
        elif args.format == "md":
            print(
                render_decision_markdown(
                    build_decision_report(decisions, research_queue=research_queue)
                ),
                end="",
            )
        else:
            _print(build_decision_report(decisions, research_queue=research_queue))
        return 0
    if args.command == "show":
        run = store.get_run(args.run_id)
        try:
            decision = store.get_decision(run_id=args.run_id)
        except KeyError:
            decision = None
        _print(
            {
                "run": run,
                "hypotheses": store.list_hypotheses(run.symbol, active_only=False),
                "evidence": store.list_evidence(run_id=args.run_id),
                "assessments": store.list_assessments(run_id=args.run_id),
                "claims": store.list_claims(run_id=args.run_id),
                "decision": decision,
                "outcomes": store.list_outcomes(run_id=args.run_id) if decision else [],
            }
        )
        return 0
    if args.command == "outcome-record":
        outcome = OutcomeSnapshot(
            decision_id=args.decision_id,
            horizon_days=args.horizon_days,
            target_date=args.target_date,
            actual_date=args.actual_date,
            price_return=args.price_return,
            benchmark_return=args.benchmark_return,
            industry_return=args.industry_return,
            max_adverse_excursion=args.max_adverse_excursion,
            max_favorable_excursion=args.max_favorable_excursion,
            realized_volatility=args.realized_volatility,
            liquidity_change=args.liquidity_change,
            valuation_change=args.valuation_change,
            earnings_revision=args.earnings_revision,
            waiting_condition_status=args.waiting_condition_status,
            first_acceptable_price_date=args.first_acceptable_price_date,
            first_acceptable_price=args.first_acceptable_price,
            catalyst_status=args.catalyst_status,
            falsification_status=args.falsification_status,
            thesis_status=args.thesis_status,
            entry_action_review=args.entry_action_review,
            research_quality=args.research_quality,
            timing_quality=args.timing_quality,
            risk_control_quality=args.risk_control_quality,
            process_adherence=args.process_adherence,
            data_sources=tuple(args.data_source),
            notes=args.notes,
        )
        workflow.record_outcome(outcome)
        _print(outcome)
        return 0
    if args.command == "outcomes-due":
        _print(store.pending_outcomes(args.as_of))
        return 0
    if args.command == "outcomes-summary":
        _print(store.outcome_quality_summary())
        return 0
    if args.command == "outcomes-reschedule":
        if args.trade_cal_file:
            calendar_frame = _read_table(args.trade_cal_file)
            decision = store.get_decision(decision_id=args.decision_id)
            dates = resolve_trade_horizon_dates(
                as_of=decision.as_of,
                trade_calendar=calendar_frame.to_dict(orient="records") if calendar_frame is not None else [],
            )
        else:
            if not args.date:
                raise ValueError("provide --trade-cal-file or one or more --date horizon=YYYY-MM-DD values")
            dates = {int(value.split("=", 1)[0]): value.split("=", 1)[1] for value in args.date}
        store.reschedule_outcomes(args.decision_id, dates)
        _print(store.list_outcomes(decision_id=args.decision_id))
        return 0
    raise RuntimeError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
