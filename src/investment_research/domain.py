from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class LongTermVerdict(str, Enum):
    PASS = "passed"
    INSUFFICIENT = "needs_evidence"
    REJECT = "rejected"

    @classmethod
    def _missing_(cls, value: object):
        aliases = {"pass": cls.PASS, "insufficient": cls.INSUFFICIENT, "reject": cls.REJECT}
        return aliases.get(str(value))


class EntryAction(str, Enum):
    SCALE_IN = "staged_buy"
    WAIT_PRICE = "wait_price"
    WAIT_EVIDENCE = "wait_evidence"
    AVOID = "avoid"

    @classmethod
    def _missing_(cls, value: object):
        aliases = {"scale_in": cls.SCALE_IN}
        return aliases.get(str(value))


class DimensionStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    MISSING = "missing"


class WorkflowStage(str, Enum):
    CREATED = "created"
    LONG_TERM_REVIEWED = "long_term_reviewed"
    CURRENT_REVIEWED = "current_reviewed"
    DECIDED = "decided"


class ResearchStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DECISION_READY = "decision_ready"
    STALE = "stale"


class AssessmentStage(str, Enum):
    LONG_TERM = "long_term"
    CURRENT = "current"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"
    OFFICIAL = "official"
    REJECTED = "rejected"


class ContextStatus(str, Enum):
    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    ADVERSE = "adverse"
    MISSING = "missing"


class PortfolioAction(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    ADD = "add"
    HOLD = "hold"
    REDUCE = "reduce"
    EXIT = "exit"


class ClaimStatus(str, Enum):
    OPEN = "open"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"


ACTION_LABELS = {
    EntryAction.SCALE_IN: "可分批买入",
    EntryAction.WAIT_PRICE: "等价格",
    EntryAction.WAIT_EVIDENCE: "等证据",
    EntryAction.AVOID: "回避",
}


@dataclass(frozen=True)
class DimensionResult:
    name: str
    status: DimensionStatus
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("dimension name is required")
        if not self.rationale.strip():
            raise ValueError("dimension rationale is required")


@dataclass(frozen=True)
class Hypothesis:
    symbol: str
    thesis_key: str
    statement: str
    return_source: str
    falsification_condition: str
    horizon_months: int = 36
    confidence: float = 0.5
    validation_metrics: tuple[str, ...] = ()
    next_review_date: str | None = None
    hypothesis_id: str = field(default_factory=lambda: new_id("hyp"))
    version: int = 1
    status: str = "active"
    valid_from: str = field(default_factory=utc_now)
    valid_to: str | None = None
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.thesis_key.strip():
            raise ValueError("symbol and thesis_key are required")
        if not self.statement.strip() or not self.return_source.strip():
            raise ValueError("statement and return_source are required")
        if not self.falsification_condition.strip():
            raise ValueError("falsification_condition is required")
        if self.horizon_months <= 0:
            raise ValueError("horizon_months must be positive")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ResearchRun:
    symbol: str
    as_of: str
    intent: str
    horizon_months: int = 36
    run_id: str = field(default_factory=lambda: new_id("run"))
    stage: WorkflowStage = WorkflowStage.CREATED
    research_status: ResearchStatus = ResearchStatus.QUEUED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.intent.strip():
            raise ValueError("symbol and intent are required")
        if self.horizon_months <= 0:
            raise ValueError("horizon_months must be positive")


@dataclass(frozen=True)
class EvidenceItem:
    run_id: str
    symbol: str
    evidence_type: str
    time_scale: str
    source_name: str
    source_url: str
    source_date: str
    available_at: str
    verification_status: VerificationStatus
    payload: Mapping[str, Any] = field(default_factory=dict)
    evidence_id: str = field(default_factory=lambda: new_id("evidence"))
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        required = (
            self.run_id,
            self.symbol,
            self.evidence_type,
            self.time_scale,
            self.source_name,
            self.source_url,
            self.source_date,
            self.available_at,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("all evidence identity and source fields are required")


@dataclass(frozen=True)
class LongTermAssessment:
    run_id: str
    symbol: str
    verdict: LongTermVerdict
    years_covered: float
    dimensions: tuple[DimensionResult, ...]
    hypothesis_ids: tuple[str, ...]
    rationale: str
    structural_risks: tuple[str, ...] = ()
    hard_vetoes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    blocking_evidence: tuple[str, ...] = ()
    confidence_limiters: tuple[str, ...] = ()
    monitoring_items: tuple[str, ...] = ()
    process_gaps: tuple[str, ...] = ()
    research_complete: bool = True
    confidence: float = 0.5
    assessment_id: str = field(default_factory=lambda: new_id("assessment"))
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.years_covered < 0:
            raise ValueError("years_covered cannot be negative")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not self.rationale.strip():
            raise ValueError("rationale is required")


@dataclass(frozen=True)
class OverheatAssessment:
    is_overheated: bool
    severity: str
    data_timestamp: str | None
    reference_price: float | None = None
    valuation_history_percentile: float | None = None
    valuation_peer_percentile: float | None = None
    return_20d: float | None = None
    return_60d: float | None = None
    return_20d_market_percentile: float | None = None
    return_60d_industry_percentile: float | None = None
    benchmark_excess_20d: float | None = None
    benchmark_excess_60d: float | None = None
    atr_available: bool = False
    atr14_percent: float | None = None
    ma60_distance_atr: float | None = None
    volatility14_percent: float | None = None
    ma60_distance_volatility: float | None = None
    volume_percentile: float | None = None
    turnover_percentile: float | None = None
    margin_change_percentile: float | None = None
    gap_count_20d: int | None = None
    limit_count_20d: int | None = None
    average_amount_20d: float | None = None
    triggers: tuple[str, ...] = ()
    missing_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrentAssessment:
    run_id: str
    symbol: str
    evidence_complete: bool
    odds_adequate: bool
    recent_event_status: ContextStatus
    macro_status: ContextStatus
    industry_status: ContextStatus
    valuation_status: ContextStatus
    technical_liquidity_status: ContextStatus
    overheat: OverheatAssessment
    rationale: str
    recent_event_assessment: str = ""
    macro_assessment: str = ""
    industry_assessment: str = ""
    valuation_assessment: str = ""
    technical_liquidity_assessment: str = ""
    base_case: str = ""
    upside_case: str = ""
    downside_case: str = ""
    acceptable_price_low: float | None = None
    acceptable_price_high: float | None = None
    wait_conditions: tuple[str, ...] = ()
    key_risks: tuple[str, ...] = ()
    hard_current_risks: tuple[str, ...] = ()
    liquidity_unacceptable: bool = False
    portfolio_fit: str = "not_assessed"
    portfolio_constraints: tuple[str, ...] = ()
    concentration_impact: str | None = None
    liquidity_exit_assessment: str | None = None
    alternative_cost: str | None = None
    missing_evidence: tuple[str, ...] = ()
    blocking_evidence: tuple[str, ...] = ()
    confidence_limiters: tuple[str, ...] = ()
    monitoring_items: tuple[str, ...] = ()
    process_gaps: tuple[str, ...] = ()
    research_complete: bool = True
    price_regime: str = "not_assessed"
    opportunity_cost_assessment: str | None = None
    total_shareholder_return_3y: float | None = None
    assessment_id: str = field(default_factory=lambda: new_id("assessment"))
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("rationale is required")
        if (
            self.acceptable_price_low is not None
            and self.acceptable_price_high is not None
            and self.acceptable_price_low > self.acceptable_price_high
        ):
            raise ValueError("acceptable price range is inverted")
        if self.portfolio_fit not in {"not_assessed", "fits", "constrained", "incompatible"}:
            raise ValueError(f"unsupported portfolio_fit: {self.portfolio_fit}")

    @property
    def adverse_context(self) -> bool:
        statuses = (
            self.recent_event_status,
            self.macro_status,
            self.industry_status,
            self.valuation_status,
            self.technical_liquidity_status,
        )
        return any(status == ContextStatus.ADVERSE for status in statuses)

    @property
    def missing_context(self) -> bool:
        statuses = (
            self.recent_event_status,
            self.macro_status,
            self.industry_status,
            self.valuation_status,
            self.technical_liquidity_status,
        )
        return any(status == ContextStatus.MISSING for status in statuses)


@dataclass(frozen=True)
class DecisionCard:
    run_id: str
    symbol: str
    as_of: str
    long_term_verdict: LongTermVerdict
    entry_action: EntryAction
    portfolio_action: PortfolioAction
    rationale: str
    acceptable_price_low: float | None = None
    acceptable_price_high: float | None = None
    wait_conditions: tuple[str, ...] = ()
    entry_triggers: tuple[str, ...] = ()
    key_risks: tuple[str, ...] = ()
    falsification_conditions: tuple[str, ...] = ()
    next_review_date: str | None = None
    portfolio_role: str | None = None
    evidence_ids: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    holding_horizon_months: int | None = None
    candidate_source: str | None = None
    thesis_ids: tuple[str, ...] = ()
    long_term_thesis: str | None = None
    return_sources_3_5y: tuple[str, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    contrary_evidence: tuple[str, ...] = ()
    recent_event_assessment: str | None = None
    macro_assessment: str | None = None
    industry_assessment: str | None = None
    valuation_assessment: str | None = None
    technical_liquidity_assessment: str | None = None
    anti_chase_flags: tuple[str, ...] = ()
    anti_chase_assessment: Mapping[str, str] = field(default_factory=dict)
    reference_price: float | None = None
    base_case: str | None = None
    upside_case: str | None = None
    downside_case: str | None = None
    confidence: float | None = None
    missing_evidence: tuple[str, ...] = ()
    blocking_evidence: tuple[str, ...] = ()
    confidence_limiters: tuple[str, ...] = ()
    monitoring_items: tuple[str, ...] = ()
    price_regime: str = "not_assessed"
    opportunity_cost_assessment: str | None = None
    total_shareholder_return_3y: float | None = None
    previous_decision_id: str | None = None
    previous_long_term_verdict: str | None = None
    previous_entry_action: str | None = None
    decision_change: str = "new"
    change_reasons: tuple[str, ...] = ()
    methodology_change: bool = False
    portfolio_fit: str = "not_assessed"
    portfolio_constraints: tuple[str, ...] = ()
    concentration_impact: str | None = None
    liquidity_exit_assessment: str | None = None
    alternative_cost: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    decision_id: str = field(default_factory=lambda: new_id("decision"))
    created_at: str = field(default_factory=utc_now)

    @property
    def action_label(self) -> str:
        return ACTION_LABELS[self.entry_action]

    def __post_init__(self) -> None:
        if self.holding_horizon_months is not None and self.holding_horizon_months <= 0:
            raise ValueError("holding_horizon_months must be positive")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.portfolio_fit not in {"not_assessed", "fits", "constrained", "incompatible"}:
            raise ValueError(f"unsupported portfolio_fit: {self.portfolio_fit}")
        if self.previous_decision_id and self.decision_change not in {
            "unchanged",
            "changed",
            "methodology_rebase",
        }:
            raise ValueError(f"unsupported decision_change: {self.decision_change}")
        if self.previous_decision_id and self.decision_change != "unchanged" and not self.change_reasons:
            raise ValueError("changed decisions require change_reasons")


@dataclass(frozen=True)
class ResearchClaim:
    run_id: str
    stage: AssessmentStage
    time_scale: str
    statement: str
    proposer: str
    initial_confidence: float
    final_confidence: float
    hypothesis_id: str | None = None
    supporting_evidence: tuple[str, ...] = ()
    contrary_evidence: tuple[str, ...] = ()
    challenger: str | None = None
    response: str | None = None
    unresolved_questions: tuple[str, ...] = ()
    status: ClaimStatus = ClaimStatus.OPEN
    claim_id: str = field(default_factory=lambda: new_id("claim"))
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.run_id, self.time_scale, self.statement, self.proposer)
        ):
            raise ValueError("run_id, time_scale, statement and proposer are required")
        for confidence in (self.initial_confidence, self.final_confidence):
            if not 0 <= confidence <= 1:
                raise ValueError("claim confidence must be between 0 and 1")
        if self.challenger and not (self.response or "").strip():
            raise ValueError("challenged claims require a response")
        overlap = set(self.supporting_evidence).intersection(self.contrary_evidence)
        if overlap:
            raise ValueError(f"evidence cannot be both supporting and contrary: {sorted(overlap)}")


@dataclass(frozen=True)
class NewsSignal:
    provider: str
    published_at: str
    title: str
    summary: str
    source_url: str
    important: bool = False
    symbols: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    independent_source_count: int = 1
    external_id: str | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: new_id("signal"))
    content_hash: str | None = None
    ingested_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.title.strip():
            raise ValueError("provider and title are required")
        if not self.source_url.strip():
            raise ValueError("source_url is required")
        if self.independent_source_count < 1:
            raise ValueError("independent_source_count must be positive")


@dataclass(frozen=True)
class SignalHypothesisMapping:
    signal_id: str
    hypothesis_id: str
    direction: str
    financial_channel: str
    verification_status: VerificationStatus
    thesis_key: str | None = None
    assumption_key: str = "__thesis__"
    magnitude_low: float | None = None
    magnitude_high: float | None = None
    duration_days: int | None = None
    priced_in_status: str = "unknown"
    relevance: float = 0.5
    notes: str = ""
    mapping_id: str = field(default_factory=lambda: new_id("mapping"))
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.signal_id.strip() or not self.hypothesis_id.strip():
            raise ValueError("signal_id and hypothesis_id are required")
        if self.direction not in {"positive", "negative", "mixed"}:
            raise ValueError(f"unsupported mapping direction: {self.direction}")
        allowed_channels = {"revenue", "profit", "cashflow", "capital_cost", "risk_premium"}
        if self.financial_channel not in allowed_channels:
            raise ValueError(f"unsupported financial_channel: {self.financial_channel}")
        if self.duration_days is not None and self.duration_days <= 0:
            raise ValueError("duration_days must be positive")
        if (
            self.magnitude_low is not None
            and self.magnitude_high is not None
            and self.magnitude_low > self.magnitude_high
        ):
            raise ValueError("magnitude range is inverted")
        if self.priced_in_status not in {"unknown", "not_priced", "partially_priced", "fully_priced"}:
            raise ValueError(f"unsupported priced_in_status: {self.priced_in_status}")
        if not 0 <= self.relevance <= 1:
            raise ValueError("relevance must be between 0 and 1")


@dataclass(frozen=True)
class OutcomeSnapshot:
    decision_id: str
    horizon_days: int
    target_date: str
    actual_date: str | None = None
    price_return: float | None = None
    benchmark_return: float | None = None
    industry_return: float | None = None
    max_adverse_excursion: float | None = None
    max_favorable_excursion: float | None = None
    realized_volatility: float | None = None
    liquidity_change: float | None = None
    valuation_change: float | None = None
    earnings_revision: float | None = None
    waiting_condition_status: str | None = None
    first_acceptable_price_date: str | None = None
    first_acceptable_price: float | None = None
    catalyst_status: str | None = None
    falsification_status: str | None = None
    thesis_status: str | None = None
    entry_action_review: str | None = None
    research_quality: str | None = None
    timing_quality: str | None = None
    risk_control_quality: str | None = None
    process_adherence: str | None = None
    data_sources: tuple[str, ...] = ()
    notes: str = ""
    recorded_at: str | None = None

    def __post_init__(self) -> None:
        if self.horizon_days not in {20, 60, 120}:
            raise ValueError("horizon_days must be one of 20, 60, 120")
        quality_values = {"strong", "adequate", "weak", "unrateable"}
        for field_name in ("research_quality", "timing_quality", "risk_control_quality"):
            value = getattr(self, field_name)
            if value is not None and value not in quality_values:
                raise ValueError(f"unsupported {field_name}: {value}")
        if self.process_adherence is not None and self.process_adherence not in {
            "passed",
            "deviated",
            "unverified",
        }:
            raise ValueError(f"unsupported process_adherence: {self.process_adherence}")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_jsonable(item) for item in value]
    return value
