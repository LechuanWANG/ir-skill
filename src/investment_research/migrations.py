from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_run (
    run_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    intent TEXT NOT NULL,
    horizon_months INTEGER NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('created', 'long_term_reviewed', 'current_reviewed', 'decided')),
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_run_symbol_asof
ON research_run (symbol, as_of, created_at);

CREATE TABLE IF NOT EXISTS investment_hypothesis (
    hypothesis_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    thesis_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    statement TEXT NOT NULL,
    return_source TEXT NOT NULL,
    falsification_condition TEXT NOT NULL,
    horizon_months INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    validation_metrics_json TEXT NOT NULL,
    next_review_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'closed')),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    supersedes_id TEXT REFERENCES investment_hypothesis(hypothesis_id),
    UNIQUE (symbol, thesis_key, version)
);

CREATE INDEX IF NOT EXISTS idx_investment_hypothesis_symbol_active
ON investment_hypothesis (symbol, status, thesis_key, version);

CREATE TABLE IF NOT EXISTS evidence_item (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_run(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    time_scale TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_date TEXT NOT NULL,
    available_at TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unverified', 'corroborated', 'official', 'rejected')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_item_run_available
ON evidence_item (run_id, symbol, available_at, evidence_type);

CREATE TABLE IF NOT EXISTS hypothesis_evidence (
    hypothesis_id TEXT NOT NULL REFERENCES investment_hypothesis(hypothesis_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence_item(evidence_id) ON DELETE CASCADE,
    direction TEXT NOT NULL,
    relevance REAL NOT NULL CHECK (relevance >= 0 AND relevance <= 1),
    magnitude_json TEXT NOT NULL,
    duration_days INTEGER,
    priced_in_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (hypothesis_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS research_signal (
    signal_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_url TEXT NOT NULL,
    important INTEGER NOT NULL CHECK (important IN (0, 1)),
    symbols_json TEXT NOT NULL,
    industries_json TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unverified', 'corroborated', 'official', 'rejected')),
    independent_source_count INTEGER NOT NULL,
    raw_payload_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_signal_time_provider
ON research_signal (published_at, provider, important);

CREATE TABLE IF NOT EXISTS signal_hypothesis_mapping (
    mapping_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL REFERENCES research_signal(signal_id) ON DELETE CASCADE,
    hypothesis_id TEXT NOT NULL REFERENCES investment_hypothesis(hypothesis_id) ON DELETE CASCADE,
    thesis_key TEXT,
    assumption_key TEXT NOT NULL,
    direction TEXT NOT NULL,
    financial_channel TEXT NOT NULL CHECK (financial_channel IN ('revenue', 'profit', 'cashflow', 'capital_cost', 'risk_premium')),
    verification_status TEXT NOT NULL CHECK (verification_status IN ('unverified', 'corroborated', 'official', 'rejected')),
    magnitude_low REAL,
    magnitude_high REAL,
    duration_days INTEGER,
    priced_in_status TEXT NOT NULL,
    relevance REAL NOT NULL CHECK (relevance >= 0 AND relevance <= 1),
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (signal_id, hypothesis_id, assumption_key, financial_channel)
);

CREATE INDEX IF NOT EXISTS idx_signal_mapping_hypothesis
ON signal_hypothesis_mapping (hypothesis_id, verification_status);

CREATE TABLE IF NOT EXISTS research_assessment (
    assessment_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_run(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('long_term', 'current')),
    status TEXT NOT NULL,
    confidence REAL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_assessment_run_stage
ON research_assessment (run_id, stage, created_at);

CREATE TABLE IF NOT EXISTS research_claim (
    claim_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_run(run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('long_term', 'current')),
    time_scale TEXT NOT NULL,
    hypothesis_id TEXT REFERENCES investment_hypothesis(hypothesis_id),
    statement TEXT NOT NULL,
    proposer TEXT NOT NULL,
    challenger TEXT,
    response TEXT,
    initial_confidence REAL NOT NULL CHECK (initial_confidence >= 0 AND initial_confidence <= 1),
    final_confidence REAL NOT NULL CHECK (final_confidence >= 0 AND final_confidence <= 1),
    status TEXT NOT NULL CHECK (status IN ('open', 'supported', 'weakened', 'rejected')),
    supporting_evidence_json TEXT NOT NULL,
    contrary_evidence_json TEXT NOT NULL,
    unresolved_questions_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_claim_run_stage
ON research_claim (run_id, stage, status);

CREATE TABLE IF NOT EXISTS overheat_snapshot (
    assessment_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_run(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    data_timestamp TEXT,
    is_overheated INTEGER NOT NULL CHECK (is_overheated IN (0, 1)),
    severity TEXT NOT NULL,
    valuation_history_percentile REAL,
    valuation_peer_percentile REAL,
    return_20d REAL,
    return_60d REAL,
    return_20d_market_percentile REAL,
    return_60d_industry_percentile REAL,
    benchmark_excess_20d REAL,
    benchmark_excess_60d REAL,
    atr_available INTEGER NOT NULL CHECK (atr_available IN (0, 1)),
    atr14_percent REAL,
    ma60_distance_atr REAL,
    volatility14_percent REAL,
    ma60_distance_volatility REAL,
    volume_percentile REAL,
    turnover_percentile REAL,
    margin_change_percentile REAL,
    gap_count_20d INTEGER,
    limit_count_20d INTEGER,
    average_amount_20d REAL,
    triggers_json TEXT NOT NULL,
    missing_metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_overheat_snapshot_symbol_time
ON overheat_snapshot (symbol, data_timestamp);

CREATE TABLE IF NOT EXISTS decision_card (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES research_run(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    long_term_verdict TEXT NOT NULL CHECK (long_term_verdict IN ('passed', 'needs_evidence', 'rejected')),
    entry_action TEXT NOT NULL CHECK (entry_action IN ('staged_buy', 'wait_price', 'wait_evidence', 'avoid')),
    portfolio_action TEXT NOT NULL CHECK (portfolio_action IN ('not_applicable', 'add', 'hold', 'reduce', 'exit')),
    rationale TEXT NOT NULL,
    acceptable_price_low REAL,
    acceptable_price_high REAL,
    wait_conditions_json TEXT NOT NULL,
    entry_triggers_json TEXT NOT NULL,
    key_risks_json TEXT NOT NULL,
    falsification_conditions_json TEXT NOT NULL,
    next_review_date TEXT,
    portfolio_role TEXT,
    evidence_ids_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decision_card_action_asof
ON decision_card (entry_action, as_of, symbol);

CREATE TABLE IF NOT EXISTS outcome_snapshot (
    decision_id TEXT NOT NULL REFERENCES decision_card(decision_id) ON DELETE CASCADE,
    horizon_days INTEGER NOT NULL CHECK (horizon_days IN (20, 60, 120)),
    target_date TEXT NOT NULL,
    actual_date TEXT,
    price_return REAL,
    benchmark_return REAL,
    max_adverse_excursion REAL,
    earnings_revision REAL,
    catalyst_status TEXT,
    falsification_status TEXT,
    notes TEXT NOT NULL,
    recorded_at TEXT,
    PRIMARY KEY (decision_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_outcome_snapshot_due
ON outcome_snapshot (target_date, recorded_at);
"""


OUTCOME_EVALUATION_SCHEMA = """
ALTER TABLE outcome_snapshot ADD COLUMN industry_return REAL;
ALTER TABLE outcome_snapshot ADD COLUMN max_favorable_excursion REAL;
ALTER TABLE outcome_snapshot ADD COLUMN realized_volatility REAL;
ALTER TABLE outcome_snapshot ADD COLUMN liquidity_change REAL;
ALTER TABLE outcome_snapshot ADD COLUMN valuation_change REAL;
ALTER TABLE outcome_snapshot ADD COLUMN waiting_condition_status TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN first_acceptable_price_date TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN first_acceptable_price REAL;
ALTER TABLE outcome_snapshot ADD COLUMN thesis_status TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN entry_action_review TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN research_quality TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN timing_quality TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN risk_control_quality TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN process_adherence TEXT;
ALTER TABLE outcome_snapshot ADD COLUMN data_sources_json TEXT NOT NULL DEFAULT '[]';
"""


RESEARCH_STATUS_SCHEMA = """
ALTER TABLE research_run ADD COLUMN research_status TEXT NOT NULL DEFAULT 'queued'
CHECK (research_status IN ('queued', 'in_progress', 'decision_ready', 'stale'));

CREATE INDEX IF NOT EXISTS idx_research_run_status_symbol_asof
ON research_run (research_status, symbol, as_of, created_at);
"""


MIGRATIONS = (
    Migration(1, "institutional_research_core", CORE_SCHEMA),
    Migration(2, "outcome_evaluation_contract", OUTCOME_EVALUATION_SCHEMA),
    Migration(3, "research_status_contract", RESEARCH_STATUS_SCHEMA),
)
