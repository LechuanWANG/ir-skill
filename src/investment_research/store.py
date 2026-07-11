from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo

from .domain import (
    AssessmentStage,
    ClaimStatus,
    CurrentAssessment,
    DecisionCard,
    EntryAction,
    EvidenceItem,
    Hypothesis,
    LongTermAssessment,
    LongTermVerdict,
    NewsSignal,
    OutcomeSnapshot,
    PortfolioAction,
    ResearchClaim,
    ResearchRun,
    ResearchStatus,
    SignalHypothesisMapping,
    VerificationStatus,
    WorkflowStage,
    to_jsonable,
    utc_now,
)
from .migrations import MIGRATIONS


DEFAULT_RESEARCH_DB = Path("data/investment_research.sqlite")

DECISION_CONTEXT_FIELDS = (
    "holding_horizon_months",
    "candidate_source",
    "thesis_ids",
    "long_term_thesis",
    "return_sources_3_5y",
    "supporting_evidence",
    "contrary_evidence",
    "recent_event_assessment",
    "macro_assessment",
    "industry_assessment",
    "valuation_assessment",
    "technical_liquidity_assessment",
    "anti_chase_flags",
    "anti_chase_assessment",
    "reference_price",
    "base_case",
    "upside_case",
    "downside_case",
    "confidence",
    "missing_evidence",
    "blocking_evidence",
    "confidence_limiters",
    "monitoring_items",
    "price_regime",
    "opportunity_cost_assessment",
    "total_shareholder_return_3y",
    "previous_decision_id",
    "previous_long_term_verdict",
    "previous_entry_action",
    "decision_change",
    "change_reasons",
    "methodology_change",
    "portfolio_fit",
    "portfolio_constraints",
    "concentration_impact",
    "liquidity_exit_assessment",
    "alternative_cost",
)


def _json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: object, default: Any) -> Any:
    if value is None or str(value).strip() == "":
        return default
    return json.loads(str(value))


def _parse_date(value: str) -> date:
    text = str(value).strip()
    if text.isdigit() and len(text) == 8:
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.fromisoformat(text[:10]).date()


def _parse_timestamp(value: str, *, date_only_is_end_of_day: bool) -> datetime:
    text = str(value).strip()
    timezone = ZoneInfo("Asia/Hong_Kong")
    date_only = (text.isdigit() and len(text) == 8) or (
        len(text) == 10 and text[4] == "-" and text[7] == "-"
    )
    if text.isdigit() and len(text) == 8:
        parsed = datetime.strptime(text, "%Y%m%d")
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if date_only and date_only_is_end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _add_approximate_business_days(value: str, days: int) -> str:
    current = _parse_date(value)
    remaining = int(days)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current.isoformat()


class ResearchStore:
    def __init__(self, db_path: Path | str = DEFAULT_RESEARCH_DB):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_schema_migration (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            existing = {
                int(row["version"]): str(row["checksum"])
                for row in connection.execute("SELECT version, checksum FROM research_schema_migration")
            }
            for migration in MIGRATIONS:
                if migration.version in existing:
                    if existing[migration.version] != migration.checksum:
                        raise RuntimeError(f"migration checksum mismatch: {migration.version}")
                    continue
                if migration.name == "outcome_evaluation_contract":
                    columns = {
                        str(row[1])
                        for row in connection.execute("PRAGMA table_info(outcome_snapshot)")
                    }
                    for statement in migration.sql.split(";"):
                        normalized = statement.strip()
                        if not normalized:
                            continue
                        parts = normalized.split()
                        column = parts[5]
                        if column not in columns:
                            connection.execute(normalized)
                            columns.add(column)
                else:
                    connection.executescript(migration.sql)
                connection.execute(
                    "INSERT INTO research_schema_migration(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, utc_now()),
                )
                applied.append(migration.version)
            connection.commit()
        return applied

    def create_run(self, run: ResearchRun) -> ResearchRun:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_run(
                    run_id, symbol, as_of, intent, horizon_months, stage,
                    research_status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.symbol,
                    run.as_of,
                    run.intent,
                    run.horizon_months,
                    run.stage.value,
                    run.research_status.value,
                    _json_dumps(run.metadata),
                    run.created_at,
                    run.updated_at,
                ),
            )
            connection.commit()
        return run

    def get_run(self, run_id: str) -> ResearchRun:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM research_run WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"research run not found: {run_id}")
        return ResearchRun(
            run_id=str(row["run_id"]),
            symbol=str(row["symbol"]),
            as_of=str(row["as_of"]),
            intent=str(row["intent"]),
            horizon_months=int(row["horizon_months"]),
            stage=WorkflowStage(str(row["stage"])),
            research_status=ResearchStatus(str(row["research_status"])),
            metadata=_json_loads(row["metadata_json"], {}),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def update_run_stage(self, run_id: str, stage: WorkflowStage) -> ResearchRun:
        run = self.get_run(run_id)
        transitions = {
            WorkflowStage.CREATED: {WorkflowStage.LONG_TERM_REVIEWED},
            WorkflowStage.LONG_TERM_REVIEWED: {WorkflowStage.CURRENT_REVIEWED, WorkflowStage.DECIDED},
            WorkflowStage.CURRENT_REVIEWED: {WorkflowStage.DECIDED},
            WorkflowStage.DECIDED: set(),
        }
        if stage == run.stage:
            return run
        if stage not in transitions[run.stage]:
            raise ValueError(f"invalid workflow transition: {run.stage.value} -> {stage.value}")
        updated_at = utc_now()
        research_status = (
            ResearchStatus.DECISION_READY
            if stage == WorkflowStage.DECIDED
            else ResearchStatus.IN_PROGRESS
        )
        with self.connect() as connection:
            connection.execute(
                "UPDATE research_run SET stage = ?, research_status = ?, updated_at = ? WHERE run_id = ?",
                (stage.value, research_status.value, updated_at, run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def update_research_status(self, run_id: str, status: ResearchStatus) -> ResearchRun:
        self.get_run(run_id)
        with self.connect() as connection:
            connection.execute(
                "UPDATE research_run SET research_status = ?, updated_at = ? WHERE run_id = ?",
                (status.value, utc_now(), run_id),
            )
            connection.commit()
        return self.get_run(run_id)

    def list_runs(
        self,
        *,
        statuses: Sequence[ResearchStatus] | None = None,
        latest_per_symbol: bool = False,
        limit: int = 1000,
    ) -> list[ResearchRun]:
        self.migrate()
        where = ""
        params: list[Any] = []
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            where = f"WHERE research_status IN ({placeholders})"
            params.extend(status.value for status in statuses)
        params.append(int(limit))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT run_id FROM research_run {where} ORDER BY as_of DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        runs = [self.get_run(str(row["run_id"])) for row in rows]
        if not latest_per_symbol:
            return runs
        latest: dict[str, ResearchRun] = {}
        for run in runs:
            latest.setdefault(run.symbol, run)
        return list(latest.values())

    def add_hypothesis(
        self,
        *,
        symbol: str,
        thesis_key: str,
        statement: str,
        return_source: str,
        falsification_condition: str,
        horizon_months: int = 36,
        confidence: float = 0.5,
        validation_metrics: Sequence[str] = (),
        next_review_date: str | None = None,
    ) -> Hypothesis:
        self.migrate()
        created_at = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT hypothesis_id, version
                FROM investment_hypothesis
                WHERE symbol = ? AND thesis_key = ? AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (symbol, thesis_key),
            ).fetchone()
            version = int(previous["version"]) + 1 if previous else 1
            supersedes_id = str(previous["hypothesis_id"]) if previous else None
            hypothesis = Hypothesis(
                symbol=symbol,
                thesis_key=thesis_key,
                statement=statement,
                return_source=return_source,
                falsification_condition=falsification_condition,
                horizon_months=horizon_months,
                confidence=confidence,
                validation_metrics=tuple(validation_metrics),
                next_review_date=next_review_date,
                version=version,
                supersedes_id=supersedes_id,
                valid_from=created_at,
            )
            if previous:
                connection.execute(
                    "UPDATE investment_hypothesis SET status = 'superseded', valid_to = ? WHERE hypothesis_id = ?",
                    (created_at, supersedes_id),
                )
            connection.execute(
                """
                INSERT INTO investment_hypothesis(
                    hypothesis_id, symbol, thesis_key, version, statement,
                    return_source, falsification_condition, horizon_months,
                    confidence, validation_metrics_json, next_review_date,
                    status, valid_from, valid_to, supersedes_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hypothesis.hypothesis_id,
                    hypothesis.symbol,
                    hypothesis.thesis_key,
                    hypothesis.version,
                    hypothesis.statement,
                    hypothesis.return_source,
                    hypothesis.falsification_condition,
                    hypothesis.horizon_months,
                    hypothesis.confidence,
                    _json_dumps(hypothesis.validation_metrics),
                    hypothesis.next_review_date,
                    hypothesis.status,
                    hypothesis.valid_from,
                    hypothesis.valid_to,
                    hypothesis.supersedes_id,
                ),
            )
            connection.commit()
        return hypothesis

    def list_hypotheses(self, symbol: str, *, active_only: bool = True) -> list[Hypothesis]:
        self.migrate()
        predicate = "AND status = 'active'" if active_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM investment_hypothesis
                WHERE symbol = ? {predicate}
                ORDER BY thesis_key, version DESC
                """,
                (symbol,),
            ).fetchall()
        return [
            Hypothesis(
                hypothesis_id=str(row["hypothesis_id"]),
                symbol=str(row["symbol"]),
                thesis_key=str(row["thesis_key"]),
                version=int(row["version"]),
                statement=str(row["statement"]),
                return_source=str(row["return_source"]),
                falsification_condition=str(row["falsification_condition"]),
                horizon_months=int(row["horizon_months"]),
                confidence=float(row["confidence"]),
                validation_metrics=tuple(_json_loads(row["validation_metrics_json"], [])),
                next_review_date=row["next_review_date"],
                status=str(row["status"]),
                valid_from=str(row["valid_from"]),
                valid_to=row["valid_to"],
                supersedes_id=row["supersedes_id"],
            )
            for row in rows
        ]

    def add_evidence(self, evidence: EvidenceItem) -> str:
        self.migrate()
        run = self.get_run(evidence.run_id)
        if evidence.symbol != run.symbol:
            raise ValueError("evidence symbol does not match research run")
        if _parse_timestamp(
            evidence.available_at,
            date_only_is_end_of_day=True,
        ) > _parse_timestamp(run.as_of, date_only_is_end_of_day=True):
            raise ValueError("evidence available_at is later than research run as_of")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO evidence_item(
                    evidence_id, run_id, symbol, evidence_type, time_scale,
                    source_name, source_url, source_date, available_at,
                    verification_status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.run_id,
                    evidence.symbol,
                    evidence.evidence_type,
                    evidence.time_scale,
                    evidence.source_name,
                    evidence.source_url,
                    evidence.source_date,
                    evidence.available_at,
                    evidence.verification_status.value,
                    _json_dumps(evidence.payload),
                    evidence.created_at,
                ),
            )
            connection.commit()
        return evidence.evidence_id

    def list_evidence(
        self,
        *,
        run_id: str | None = None,
        hypothesis_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if run_id and hypothesis_id:
            raise ValueError("filter evidence by run_id or hypothesis_id, not both")
        self.migrate()
        join = ""
        where = ""
        params: Sequence[Any] = ()
        if hypothesis_id:
            join = "JOIN hypothesis_evidence USING(evidence_id)"
            where = "WHERE hypothesis_evidence.hypothesis_id = ?"
            params = (hypothesis_id,)
        elif run_id:
            where = "WHERE evidence_item.run_id = ?"
            params = (run_id,)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT evidence_item.* FROM evidence_item
                {join}
                {where}
                ORDER BY evidence_item.available_at, evidence_item.created_at
                """,
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = _json_loads(item.pop("payload_json"), {})
            output.append(item)
        return output

    def link_hypothesis_evidence(
        self,
        *,
        hypothesis_id: str,
        evidence_id: str,
        direction: str,
        relevance: float,
        magnitude: Mapping[str, Any] | None = None,
        duration_days: int | None = None,
        priced_in_status: str = "unknown",
    ) -> None:
        if not 0 <= relevance <= 1:
            raise ValueError("relevance must be between 0 and 1")
        self.migrate()
        with self.connect() as connection:
            hypothesis = connection.execute(
                "SELECT symbol FROM investment_hypothesis WHERE hypothesis_id = ?",
                (hypothesis_id,),
            ).fetchone()
            evidence = connection.execute(
                "SELECT symbol FROM evidence_item WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            if hypothesis is None or evidence is None:
                raise KeyError("hypothesis or evidence not found")
            if hypothesis["symbol"] != evidence["symbol"]:
                raise ValueError("hypothesis and evidence symbols do not match")
            connection.execute(
                """
                INSERT INTO hypothesis_evidence(
                    hypothesis_id, evidence_id, direction, relevance,
                    magnitude_json, duration_days, priced_in_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hypothesis_id, evidence_id) DO UPDATE SET
                    direction = excluded.direction,
                    relevance = excluded.relevance,
                    magnitude_json = excluded.magnitude_json,
                    duration_days = excluded.duration_days,
                    priced_in_status = excluded.priced_in_status,
                    created_at = excluded.created_at
                """,
                (
                    hypothesis_id,
                    evidence_id,
                    direction,
                    relevance,
                    _json_dumps(magnitude or {}),
                    duration_days,
                    priced_in_status,
                    utc_now(),
                ),
            )
            connection.commit()

    def list_hypothesis_evidence(
        self,
        *,
        run_id: str | None = None,
        hypothesis_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if run_id and hypothesis_id:
            raise ValueError("filter hypothesis evidence by run_id or hypothesis_id, not both")
        self.migrate()
        where = ""
        params: Sequence[Any] = ()
        if run_id:
            where = "WHERE evidence_item.run_id = ?"
            params = (run_id,)
        elif hypothesis_id:
            where = "WHERE hypothesis_evidence.hypothesis_id = ?"
            params = (hypothesis_id,)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT hypothesis_evidence.*, investment_hypothesis.symbol,
                       investment_hypothesis.thesis_key, evidence_item.run_id,
                       evidence_item.source_url, evidence_item.available_at
                FROM hypothesis_evidence
                JOIN investment_hypothesis USING(hypothesis_id)
                JOIN evidence_item USING(evidence_id)
                {where}
                ORDER BY hypothesis_evidence.created_at, hypothesis_evidence.evidence_id
                """,
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["magnitude"] = _json_loads(item.pop("magnitude_json"), {})
            output.append(item)
        return output

    def add_signal(self, signal: NewsSignal) -> str:
        self.migrate()
        content_hash = signal.content_hash or hashlib.sha256(
            _json_dumps(
                {
                    "provider": signal.provider,
                    "external_id": signal.external_id,
                    "published_at": signal.published_at,
                    "title": signal.title,
                    "source_url": signal.source_url,
                }
            ).encode("utf-8")
        ).hexdigest()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT signal_id, verification_status, independent_source_count FROM research_signal WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if existing:
                verification_rank = {"unverified": 0, "corroborated": 1, "official": 2, "rejected": 3}
                current_status = str(existing["verification_status"])
                next_status = signal.verification_status.value
                strongest_status = next_status if verification_rank[next_status] > verification_rank[current_status] else current_status
                connection.execute(
                    """
                    UPDATE research_signal
                    SET verification_status = ?, independent_source_count = ?, last_seen_at = ?
                    WHERE signal_id = ?
                    """,
                    (
                        strongest_status,
                        max(int(existing["independent_source_count"]), signal.independent_source_count),
                        utc_now(),
                        str(existing["signal_id"]),
                    ),
                )
                connection.commit()
                return str(existing["signal_id"])
            connection.execute(
                """
                INSERT INTO research_signal(
                    signal_id, provider, external_id, content_hash, published_at,
                    title, summary, source_url, important, symbols_json,
                    industries_json, verification_status, independent_source_count,
                    raw_payload_json, ingested_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.provider,
                    signal.external_id,
                    content_hash,
                    signal.published_at,
                    signal.title,
                    signal.summary,
                    signal.source_url,
                    int(signal.important),
                    _json_dumps(signal.symbols),
                    _json_dumps(signal.industries),
                    signal.verification_status.value,
                    signal.independent_source_count,
                    _json_dumps(signal.raw_payload),
                    signal.ingested_at,
                    signal.ingested_at,
                ),
            )
            connection.commit()
        return signal.signal_id

    def list_signals(
        self,
        *,
        symbol: str | None = None,
        important_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.migrate()
        where: list[str] = []
        params: list[Any] = []
        if important_only:
            where.append("important = 1")
        if symbol:
            where.append("symbols_json LIKE ?")
            params.append(f'%"{symbol}"%')
        predicate = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(int(limit))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM research_signal {predicate} ORDER BY published_at DESC LIMIT ?",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            for column in ("symbols_json", "industries_json", "raw_payload_json"):
                item[column.removesuffix("_json")] = _json_loads(item.pop(column), [] if column != "raw_payload_json" else {})
            item["important"] = bool(item["important"])
            output.append(item)
        return output

    def get_signal(self, signal_id: str) -> dict[str, Any]:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_signal WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"signal not found: {signal_id}")
        item = dict(row)
        for column in ("symbols_json", "industries_json", "raw_payload_json"):
            item[column.removesuffix("_json")] = _json_loads(
                item.pop(column),
                [] if column != "raw_payload_json" else {},
            )
        item["important"] = bool(item["important"])
        return item

    def add_signal_mapping(self, mapping: SignalHypothesisMapping) -> str:
        self.migrate()
        assumption_key = mapping.assumption_key or "__thesis__"
        with self.connect() as connection:
            signal_row = connection.execute(
                "SELECT symbols_json, verification_status FROM research_signal WHERE signal_id = ?",
                (mapping.signal_id,),
            ).fetchone()
            hypothesis_row = connection.execute(
                "SELECT symbol, thesis_key FROM investment_hypothesis WHERE hypothesis_id = ?",
                (mapping.hypothesis_id,),
            ).fetchone()
            if signal_row is None or hypothesis_row is None:
                raise KeyError("signal or hypothesis not found")
            signal_symbols = set(_json_loads(signal_row["symbols_json"], []))
            hypothesis_symbol = str(hypothesis_row["symbol"])
            if signal_symbols and hypothesis_symbol not in signal_symbols:
                raise ValueError("signal symbols do not include the hypothesis company")
            if mapping.thesis_key and mapping.thesis_key != str(hypothesis_row["thesis_key"]):
                raise ValueError("mapping thesis_key does not match the persisted hypothesis")
            if mapping.verification_status.value != str(signal_row["verification_status"]):
                raise ValueError("mapping verification_status must match the persisted signal")
            connection.execute(
                """
                INSERT INTO signal_hypothesis_mapping(
                    mapping_id, signal_id, hypothesis_id, thesis_key, assumption_key,
                    direction, financial_channel, verification_status,
                    magnitude_low, magnitude_high, duration_days,
                    priced_in_status, relevance, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id, hypothesis_id, assumption_key, financial_channel) DO UPDATE SET
                    thesis_key = excluded.thesis_key,
                    assumption_key = excluded.assumption_key,
                    direction = excluded.direction,
                    verification_status = excluded.verification_status,
                    magnitude_low = excluded.magnitude_low,
                    magnitude_high = excluded.magnitude_high,
                    duration_days = excluded.duration_days,
                    priced_in_status = excluded.priced_in_status,
                    relevance = excluded.relevance,
                    notes = excluded.notes,
                    created_at = excluded.created_at
                """,
                (
                    mapping.mapping_id,
                    mapping.signal_id,
                    mapping.hypothesis_id,
                    mapping.thesis_key,
                    assumption_key,
                    mapping.direction,
                    mapping.financial_channel,
                    mapping.verification_status.value,
                    mapping.magnitude_low,
                    mapping.magnitude_high,
                    mapping.duration_days,
                    mapping.priced_in_status,
                    mapping.relevance,
                    mapping.notes,
                    mapping.created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT mapping_id FROM signal_hypothesis_mapping
                WHERE signal_id = ? AND hypothesis_id = ? AND assumption_key = ? AND financial_channel = ?
                """,
                (
                    mapping.signal_id,
                    mapping.hypothesis_id,
                    assumption_key,
                    mapping.financial_channel,
                ),
            ).fetchone()
            connection.commit()
        return str(row["mapping_id"])

    def list_signal_mappings(self, *, hypothesis_id: str | None = None) -> list[dict[str, Any]]:
        self.migrate()
        if hypothesis_id:
            query = "SELECT * FROM signal_hypothesis_mapping WHERE hypothesis_id = ? ORDER BY created_at DESC"
            params: Sequence[Any] = (hypothesis_id,)
        else:
            query = "SELECT * FROM signal_hypothesis_mapping ORDER BY created_at DESC"
            params = ()
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def save_long_term_assessment(self, assessment: LongTermAssessment) -> str:
        return self._save_assessment(
            assessment_id=assessment.assessment_id,
            run_id=assessment.run_id,
            symbol=assessment.symbol,
            stage=AssessmentStage.LONG_TERM,
            status=assessment.verdict.value,
            confidence=assessment.confidence,
            payload=assessment,
            created_at=assessment.created_at,
        )

    def save_current_assessment(self, assessment: CurrentAssessment) -> str:
        status = "complete" if assessment.evidence_complete and not assessment.missing_context else "incomplete"
        assessment_id = self._save_assessment(
            assessment_id=assessment.assessment_id,
            run_id=assessment.run_id,
            symbol=assessment.symbol,
            stage=AssessmentStage.CURRENT,
            status=status,
            confidence=None,
            payload=assessment,
            created_at=assessment.created_at,
        )
        self.save_overheat_snapshot(assessment)
        return assessment_id

    def _save_assessment(
        self,
        *,
        assessment_id: str,
        run_id: str,
        symbol: str,
        stage: AssessmentStage,
        status: str,
        confidence: float | None,
        payload: Any,
        created_at: str,
    ) -> str:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_assessment(
                    assessment_id, run_id, symbol, stage, status,
                    confidence, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    run_id,
                    symbol,
                    stage.value,
                    status,
                    confidence,
                    _json_dumps(payload),
                    created_at,
                ),
            )
            connection.commit()
        return assessment_id

    def latest_assessment_payload(self, run_id: str, stage: AssessmentStage) -> dict[str, Any] | None:
        self.migrate()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM research_assessment
                WHERE run_id = ? AND stage = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id, stage.value),
            ).fetchone()
        return _json_loads(row["payload_json"], {}) if row else None

    def list_assessments(
        self,
        *,
        run_id: str | None = None,
        stage: AssessmentStage | None = None,
    ) -> list[dict[str, Any]]:
        self.migrate()
        where: list[str] = []
        params: list[Any] = []
        if run_id:
            where.append("run_id = ?")
            params.append(run_id)
        if stage:
            where.append("stage = ?")
            params.append(stage.value)
        predicate = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM research_assessment {predicate} ORDER BY created_at",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = _json_loads(item.pop("payload_json"), {})
            output.append(item)
        return output

    def save_overheat_snapshot(self, assessment: CurrentAssessment) -> str:
        overheat = assessment.overheat
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO overheat_snapshot(
                    assessment_id, run_id, symbol, data_timestamp, is_overheated,
                    severity, valuation_history_percentile, valuation_peer_percentile,
                    return_20d, return_60d, return_20d_market_percentile,
                    return_60d_industry_percentile, benchmark_excess_20d,
                    benchmark_excess_60d, atr_available, atr14_percent,
                    ma60_distance_atr, volatility14_percent,
                    ma60_distance_volatility,
                    volume_percentile, turnover_percentile,
                    margin_change_percentile, gap_count_20d, limit_count_20d,
                    average_amount_20d, triggers_json, missing_metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    assessment.run_id,
                    assessment.symbol,
                    overheat.data_timestamp,
                    int(overheat.is_overheated),
                    overheat.severity,
                    overheat.valuation_history_percentile,
                    overheat.valuation_peer_percentile,
                    overheat.return_20d,
                    overheat.return_60d,
                    overheat.return_20d_market_percentile,
                    overheat.return_60d_industry_percentile,
                    overheat.benchmark_excess_20d,
                    overheat.benchmark_excess_60d,
                    int(overheat.atr_available),
                    overheat.atr14_percent,
                    overheat.ma60_distance_atr,
                    overheat.volatility14_percent,
                    overheat.ma60_distance_volatility,
                    overheat.volume_percentile,
                    overheat.turnover_percentile,
                    overheat.margin_change_percentile,
                    overheat.gap_count_20d,
                    overheat.limit_count_20d,
                    overheat.average_amount_20d,
                    _json_dumps(overheat.triggers),
                    _json_dumps(overheat.missing_metrics),
                    assessment.created_at,
                ),
            )
            connection.commit()
        return assessment.assessment_id

    def add_claim(self, claim: ResearchClaim) -> str:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_claim(
                    claim_id, run_id, stage, time_scale, hypothesis_id,
                    statement, proposer, challenger, response,
                    initial_confidence, final_confidence, status,
                    supporting_evidence_json, contrary_evidence_json,
                    unresolved_questions_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.claim_id,
                    claim.run_id,
                    claim.stage.value,
                    claim.time_scale,
                    claim.hypothesis_id,
                    claim.statement,
                    claim.proposer,
                    claim.challenger,
                    claim.response,
                    claim.initial_confidence,
                    claim.final_confidence,
                    claim.status.value,
                    _json_dumps(claim.supporting_evidence),
                    _json_dumps(claim.contrary_evidence),
                    _json_dumps(claim.unresolved_questions),
                    claim.created_at,
                ),
            )
            connection.commit()
        return claim.claim_id

    def list_claims(
        self,
        *,
        run_id: str | None = None,
        stage: AssessmentStage | None = None,
    ) -> list[dict[str, Any]]:
        self.migrate()
        where: list[str] = []
        params: list[Any] = []
        if run_id:
            where.append("run_id = ?")
            params.append(run_id)
        if stage:
            where.append("stage = ?")
            params.append(stage.value)
        predicate = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM research_claim {predicate} ORDER BY created_at",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            for column in (
                "supporting_evidence_json",
                "contrary_evidence_json",
                "unresolved_questions_json",
            ):
                item[column.removesuffix("_json")] = _json_loads(item.pop(column), [])
            output.append(item)
        return output

    def save_decision(self, decision: DecisionCard) -> str:
        self.migrate()
        decision_payload = to_jsonable(decision)
        stored_metadata = dict(decision.metadata)
        stored_metadata["_decision_context_v1"] = {
            field: decision_payload[field]
            for field in DECISION_CONTEXT_FIELDS
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO decision_card(
                    decision_id, run_id, symbol, as_of, long_term_verdict,
                    entry_action, portfolio_action, rationale,
                    acceptable_price_low, acceptable_price_high,
                    wait_conditions_json, entry_triggers_json, key_risks_json,
                    falsification_conditions_json, next_review_date,
                    portfolio_role, evidence_ids_json, sources_json,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.run_id,
                    decision.symbol,
                    decision.as_of,
                    decision.long_term_verdict.value,
                    decision.entry_action.value,
                    decision.portfolio_action.value,
                    decision.rationale,
                    decision.acceptable_price_low,
                    decision.acceptable_price_high,
                    _json_dumps(decision.wait_conditions),
                    _json_dumps(decision.entry_triggers),
                    _json_dumps(decision.key_risks),
                    _json_dumps(decision.falsification_conditions),
                    decision.next_review_date,
                    decision.portfolio_role,
                    _json_dumps(decision.evidence_ids),
                    _json_dumps(decision.sources),
                    _json_dumps(stored_metadata),
                    decision.created_at,
                ),
            )
            for horizon_days in (20, 60, 120):
                connection.execute(
                    """
                    INSERT INTO outcome_snapshot(
                        decision_id, horizon_days, target_date, notes
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        decision.decision_id,
                        horizon_days,
                        _add_approximate_business_days(decision.as_of, horizon_days),
                        "approximate weekday schedule; replace with exchange-calendar date when recorded",
                    ),
                )
            connection.commit()
        return decision.decision_id

    def get_decision(self, *, run_id: str | None = None, decision_id: str | None = None) -> DecisionCard:
        if bool(run_id) == bool(decision_id):
            raise ValueError("provide exactly one of run_id or decision_id")
        self.migrate()
        column = "run_id" if run_id else "decision_id"
        value = run_id or decision_id
        with self.connect() as connection:
            row = connection.execute(f"SELECT * FROM decision_card WHERE {column} = ?", (value,)).fetchone()
        if row is None:
            raise KeyError(f"decision not found for {column}={value}")
        return self._decision_from_row(row)

    def list_decisions(
        self,
        *,
        action: EntryAction | None = None,
        symbol: str | None = None,
        latest_per_symbol: bool = False,
        limit: int = 1000,
    ) -> list[DecisionCard]:
        self.migrate()
        predicates: list[str] = []
        params: list[Any] = []
        if action:
            predicates.append("entry_action = ?")
            params.append(action.value)
        if symbol:
            predicates.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        params.append(int(limit))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM decision_card {where} ORDER BY as_of DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        decisions = [self._decision_from_row(row) for row in rows]
        if not latest_per_symbol:
            return decisions
        latest: dict[str, DecisionCard] = {}
        for decision in decisions:
            latest.setdefault(decision.symbol, decision)
        return list(latest.values())

    def latest_decision_for_symbol(
        self,
        symbol: str,
        *,
        before_as_of: str | None = None,
        exclude_run_id: str | None = None,
    ) -> DecisionCard | None:
        self.migrate()
        predicates = ["symbol = ?"]
        params: list[Any] = [symbol]
        if before_as_of:
            predicates.append("as_of <= ?")
            params.append(before_as_of)
        if exclude_run_id:
            predicates.append("run_id <> ?")
            params.append(exclude_run_id)
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM decision_card WHERE {' AND '.join(predicates)} "
                "ORDER BY as_of DESC, created_at DESC LIMIT 1",
                params,
            ).fetchone()
        return self._decision_from_row(row) if row is not None else None

    def _decision_from_row(self, row: sqlite3.Row) -> DecisionCard:
        metadata = _json_loads(row["metadata_json"], {})
        context = metadata.pop("_decision_context_v1", {})
        return DecisionCard(
            decision_id=str(row["decision_id"]),
            run_id=str(row["run_id"]),
            symbol=str(row["symbol"]),
            as_of=str(row["as_of"]),
            long_term_verdict=LongTermVerdict(str(row["long_term_verdict"])),
            entry_action=EntryAction(str(row["entry_action"])),
            portfolio_action=PortfolioAction(str(row["portfolio_action"])),
            rationale=str(row["rationale"]),
            acceptable_price_low=row["acceptable_price_low"],
            acceptable_price_high=row["acceptable_price_high"],
            wait_conditions=tuple(_json_loads(row["wait_conditions_json"], [])),
            entry_triggers=tuple(_json_loads(row["entry_triggers_json"], [])),
            key_risks=tuple(_json_loads(row["key_risks_json"], [])),
            falsification_conditions=tuple(_json_loads(row["falsification_conditions_json"], [])),
            next_review_date=row["next_review_date"],
            portfolio_role=row["portfolio_role"],
            evidence_ids=tuple(_json_loads(row["evidence_ids_json"], [])),
            sources=tuple(_json_loads(row["sources_json"], [])),
            holding_horizon_months=context.get("holding_horizon_months"),
            candidate_source=context.get("candidate_source"),
            thesis_ids=tuple(context.get("thesis_ids", [])),
            long_term_thesis=context.get("long_term_thesis"),
            return_sources_3_5y=tuple(context.get("return_sources_3_5y", [])),
            supporting_evidence=tuple(context.get("supporting_evidence", [])),
            contrary_evidence=tuple(context.get("contrary_evidence", [])),
            recent_event_assessment=context.get("recent_event_assessment"),
            macro_assessment=context.get("macro_assessment"),
            industry_assessment=context.get("industry_assessment"),
            valuation_assessment=context.get("valuation_assessment"),
            technical_liquidity_assessment=context.get("technical_liquidity_assessment"),
            anti_chase_flags=tuple(context.get("anti_chase_flags", [])),
            anti_chase_assessment=context.get("anti_chase_assessment", {}),
            reference_price=context.get("reference_price"),
            base_case=context.get("base_case"),
            upside_case=context.get("upside_case"),
            downside_case=context.get("downside_case"),
            confidence=context.get("confidence"),
            missing_evidence=tuple(context.get("missing_evidence", [])),
            blocking_evidence=tuple(
                context.get("blocking_evidence", context.get("missing_evidence", []))
            ),
            confidence_limiters=tuple(context.get("confidence_limiters", [])),
            monitoring_items=tuple(context.get("monitoring_items", [])),
            price_regime=str(context.get("price_regime", "not_assessed")),
            opportunity_cost_assessment=context.get("opportunity_cost_assessment"),
            total_shareholder_return_3y=context.get("total_shareholder_return_3y"),
            previous_decision_id=context.get("previous_decision_id"),
            previous_long_term_verdict=context.get("previous_long_term_verdict"),
            previous_entry_action=context.get("previous_entry_action"),
            decision_change=str(context.get("decision_change", "new")),
            change_reasons=tuple(context.get("change_reasons", [])),
            methodology_change=bool(context.get("methodology_change", False)),
            portfolio_fit=str(context.get("portfolio_fit", "not_assessed")),
            portfolio_constraints=tuple(context.get("portfolio_constraints", [])),
            concentration_impact=context.get("concentration_impact"),
            liquidity_exit_assessment=context.get("liquidity_exit_assessment"),
            alternative_cost=context.get("alternative_cost"),
            metadata=metadata,
            created_at=str(row["created_at"]),
        )

    def record_outcome(self, outcome: OutcomeSnapshot) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO outcome_snapshot(
                    decision_id, horizon_days, target_date, actual_date,
                    price_return, benchmark_return, industry_return,
                    max_adverse_excursion, max_favorable_excursion,
                    realized_volatility, liquidity_change, valuation_change,
                    earnings_revision, waiting_condition_status,
                    first_acceptable_price_date, first_acceptable_price,
                    catalyst_status, falsification_status, thesis_status,
                    entry_action_review, research_quality, timing_quality,
                    risk_control_quality, process_adherence, data_sources_json,
                    notes, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id, horizon_days) DO UPDATE SET
                    target_date = excluded.target_date,
                    actual_date = excluded.actual_date,
                    price_return = excluded.price_return,
                    benchmark_return = excluded.benchmark_return,
                    industry_return = excluded.industry_return,
                    max_adverse_excursion = excluded.max_adverse_excursion,
                    max_favorable_excursion = excluded.max_favorable_excursion,
                    realized_volatility = excluded.realized_volatility,
                    liquidity_change = excluded.liquidity_change,
                    valuation_change = excluded.valuation_change,
                    earnings_revision = excluded.earnings_revision,
                    waiting_condition_status = excluded.waiting_condition_status,
                    first_acceptable_price_date = excluded.first_acceptable_price_date,
                    first_acceptable_price = excluded.first_acceptable_price,
                    catalyst_status = excluded.catalyst_status,
                    falsification_status = excluded.falsification_status,
                    thesis_status = excluded.thesis_status,
                    entry_action_review = excluded.entry_action_review,
                    research_quality = excluded.research_quality,
                    timing_quality = excluded.timing_quality,
                    risk_control_quality = excluded.risk_control_quality,
                    process_adherence = excluded.process_adherence,
                    data_sources_json = excluded.data_sources_json,
                    notes = excluded.notes,
                    recorded_at = excluded.recorded_at
                """,
                (
                    outcome.decision_id,
                    outcome.horizon_days,
                    outcome.target_date,
                    outcome.actual_date,
                    outcome.price_return,
                    outcome.benchmark_return,
                    outcome.industry_return,
                    outcome.max_adverse_excursion,
                    outcome.max_favorable_excursion,
                    outcome.realized_volatility,
                    outcome.liquidity_change,
                    outcome.valuation_change,
                    outcome.earnings_revision,
                    outcome.waiting_condition_status,
                    outcome.first_acceptable_price_date,
                    outcome.first_acceptable_price,
                    outcome.catalyst_status,
                    outcome.falsification_status,
                    outcome.thesis_status,
                    outcome.entry_action_review,
                    outcome.research_quality,
                    outcome.timing_quality,
                    outcome.risk_control_quality,
                    outcome.process_adherence,
                    _json_dumps(outcome.data_sources),
                    outcome.notes,
                    outcome.recorded_at or utc_now(),
                ),
            )
            connection.commit()

    def reschedule_outcomes(self, decision_id: str, horizon_trade_dates: Mapping[int, str]) -> None:
        self.migrate()
        unsupported = set(horizon_trade_dates).difference({20, 60, 120})
        if unsupported:
            raise ValueError(f"unsupported outcome horizons: {sorted(unsupported)}")
        with self.connect() as connection:
            for horizon_days, target_date in horizon_trade_dates.items():
                connection.execute(
                    """
                    UPDATE outcome_snapshot
                    SET target_date = ?, notes = ?
                    WHERE decision_id = ? AND horizon_days = ?
                    """,
                    (
                        _parse_date(target_date).isoformat(),
                        "target date resolved from exchange trading calendar",
                        decision_id,
                        int(horizon_days),
                    ),
                )
            connection.commit()

    def list_outcomes(
        self,
        *,
        run_id: str | None = None,
        decision_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if run_id and decision_id:
            raise ValueError("filter outcomes by run_id or decision_id, not both")
        self.migrate()
        where = ""
        params: Sequence[Any] = ()
        if run_id:
            where = "WHERE decision_card.run_id = ?"
            params = (run_id,)
        elif decision_id:
            where = "WHERE outcome_snapshot.decision_id = ?"
            params = (decision_id,)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT outcome_snapshot.*, decision_card.run_id,
                       decision_card.symbol, decision_card.as_of AS decision_as_of,
                       decision_card.entry_action
                FROM outcome_snapshot
                JOIN decision_card USING(decision_id)
                {where}
                ORDER BY decision_card.as_of, decision_card.symbol, outcome_snapshot.horizon_days
                """,
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["data_sources"] = _json_loads(item.pop("data_sources_json"), [])
            output.append(item)
        return output

    def outcome_quality_summary(self) -> list[dict[str, Any]]:
        rows = self.list_outcomes()
        groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault((str(row["entry_action"]), int(row["horizon_days"])), []).append(row)
        output = []
        for entry_action in EntryAction:
            for horizon_days in (20, 60, 120):
                items = groups.get((entry_action.value, horizon_days), [])
                recorded = [item for item in items if item.get("recorded_at")]
                quality_counts = {}
                for field in (
                    "research_quality",
                    "timing_quality",
                    "risk_control_quality",
                    "process_adherence",
                ):
                    counts: dict[str, int] = {}
                    for item in recorded:
                        value = str(item.get(field) or "unrated")
                        counts[value] = counts.get(value, 0) + 1
                    quality_counts[field] = counts

                def average(field: str) -> float | None:
                    values = [float(item[field]) for item in recorded if item.get(field) is not None]
                    return sum(values) / len(values) if values else None

                relative_returns = [
                    float(item["price_return"]) - float(item["benchmark_return"])
                    for item in recorded
                    if item.get("price_return") is not None and item.get("benchmark_return") is not None
                ]
                output.append(
                    {
                        "entry_action": entry_action.value,
                        "horizon_days": horizon_days,
                        "scheduled": len(items),
                        "recorded": len(recorded),
                        "average_price_return": average("price_return"),
                        "average_benchmark_relative_return": (
                            sum(relative_returns) / len(relative_returns) if relative_returns else None
                        ),
                        "average_max_adverse_excursion": average("max_adverse_excursion"),
                        "quality_counts": quality_counts,
                    }
                )
        return output

    def pending_outcomes(self, as_of: str) -> list[dict[str, Any]]:
        self.migrate()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT outcome_snapshot.*, decision_card.symbol, decision_card.as_of AS decision_as_of
                FROM outcome_snapshot
                JOIN decision_card USING(decision_id)
                WHERE outcome_snapshot.recorded_at IS NULL
                  AND outcome_snapshot.target_date <= ?
                ORDER BY outcome_snapshot.target_date, decision_card.symbol
                """,
                (_parse_date(as_of).isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def table_counts(self) -> dict[str, int]:
        self.migrate()
        tables = [
            "research_run",
            "investment_hypothesis",
            "evidence_item",
            "hypothesis_evidence",
            "research_signal",
            "signal_hypothesis_mapping",
            "research_assessment",
            "research_claim",
            "overheat_snapshot",
            "decision_card",
            "outcome_snapshot",
        ]
        with self.connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }
