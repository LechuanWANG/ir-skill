#!/usr/bin/env python3
"""Structured evidence, readiness, confirmation, and opt-in review for short research."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


SCHEMA_VERSION = 4
GATE_STATUSES = {"pass", "fail", "review", "unknown", "not_required"}
ACTION_LABELS = {"优先行动", "等待价格", "等待证据", "选择现金"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
TECHNICAL_SETUP_TYPES = {"momentum_breakout", "trend_pullback", "event_continuation"}
TECHNICAL_ASSESSMENT_STATUSES = {"pass", "review", "fail", "unknown"}
TECHNICAL_PATTERN_LABELS = {
    "momentum_breakout": "动量突破",
    "trend_pullback": "趋势回踩",
    "event_continuation": "事件延续",
}
CANDIDATE_GRADE_LABELS = {
    "A": "A类：可执行候选",
    "B": "B类：研究合格但等待价格",
    "C": "C类：强势观察对象",
}
STRATEGY_CONTRACTS = {
    "momentum_trade": {
        "contract_version": 2,
        "profile": "trade",
        "event_required": False,
        "default_setup_type": "momentum_breakout",
        "allowed_setup_types": ["momentum_breakout", "trend_pullback"],
        "maximum_holding_sessions": 20,
        "minimum_reward_risk": 1.5,
        "decision_frequency": "close_review_next_session_execution",
        "description": "5–20 个交易日的价格、相对强弱与参与度驱动交易。",
    },
    "event_trade": {
        "contract_version": 2,
        "profile": "trade",
        "event_required": True,
        "default_setup_type": "event_continuation",
        "allowed_setup_types": ["event_continuation", "momentum_breakout"],
        "maximum_holding_sessions": 20,
        "minimum_reward_risk": 1.5,
        "decision_frequency": "close_review_next_session_execution",
        "description": "5–20 个交易日的已核验事件与预期差交易。",
    },
    "catalyst_swing": {
        "contract_version": 2,
        "profile": "swing",
        "event_required": True,
        "default_setup_type": "trend_pullback",
        "allowed_setup_types": ["trend_pullback", "event_continuation"],
        "maximum_holding_sessions": 60,
        "minimum_reward_risk": 1.5,
        "decision_frequency": "close_review_next_session_execution",
        "description": "20–60 个交易日、同时依赖中期催化与短期执行的波段研究。",
    },
}


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON object from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def strategy_contract(name: str) -> dict[str, Any]:
    try:
        return dict(STRATEGY_CONTRACTS[str(name)])
    except KeyError as exc:
        raise ValueError(f"Unsupported strategy contract: {name}") from exc


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def _text(value: object) -> str:
    return str(value or "").strip()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _gate(status: str, reason: str, **evidence: object) -> dict[str, object]:
    if status not in GATE_STATUSES:
        raise ValueError(f"Unsupported gate status: {status}")
    result: dict[str, object] = {"status": status, "reason": reason}
    if evidence:
        result["evidence"] = evidence
    return result


def aggregate_gate_status(gates: Mapping[str, Mapping[str, object]]) -> str:
    statuses = [str(item.get("status") or "unknown") for item in gates.values()]
    if not statuses or "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    if "review" in statuses:
        return "review"
    if all(status == "not_required" for status in statuses):
        return "not_required"
    return "pass"


def technical_pattern_label(value: object) -> str:
    text = _text(value)
    if text in TECHNICAL_PATTERN_LABELS.values():
        return text
    return TECHNICAL_PATTERN_LABELS.get(text, "待确认")


def technical_pattern_code(value: object) -> str:
    text = _text(value)
    if text in TECHNICAL_PATTERN_LABELS:
        return text
    return next(
        (code for code, label in TECHNICAL_PATTERN_LABELS.items() if label == text),
        "",
    )


def _candidate_grade(
    candidate: Mapping[str, object],
    gates: Mapping[str, Mapping[str, object]],
    screening_status: str,
) -> tuple[str, str, str, list[str]]:
    chase_score = _number(candidate.get("chase_risk_score"))
    gate_statuses = {name: _text(item.get("status")) for name, item in gates.items()}
    reasons: list[str] = []
    if gate_statuses.get("data_quality") == "fail":
        reasons.append("数据暂不支持执行判断")
    if gate_statuses.get("trend_structure") == "fail":
        reasons.append("趋势结构不支持")
    if gate_statuses.get("price_extension") == "review":
        reasons.append("价格偏离趋势结构，等待回撤")
    if gate_statuses.get("chase_risk") == "review":
        reasons.append("追高风险处于中等水平")
    if gate_statuses.get("chase_risk") == "fail":
        reasons.append("追高风险过高")
    if gate_statuses.get("participation") == "review":
        reasons.append("成交参与尚未确认")
    if gate_statuses.get("volatility") == "review":
        reasons.append("波动风险偏高")
    if gate_statuses.get("market_regime") == "review":
        reasons.append("市场环境不利于追逐强势股")
    if screening_status == "pass":
        grade = "A"
        buying_status = "进入执行检查，仍须满足入场条件"
        reasons = reasons or ["强度、趋势、成交和价格位置通过机械筛选"]
    elif "fail" in gate_statuses.values() or (chase_score is not None and chase_score >= 80):
        grade = "C"
        buying_status = "强势观察，不追价"
        reasons = reasons or ["存在不可由排序分数抵消的硬性风险"]
    else:
        grade = "B"
        buying_status = "研究合格，等待价格"
        reasons = reasons or ["研究方向保留，但当前尚不满足行动条件"]
    return grade, CANDIDATE_GRADE_LABELS[grade], buying_status, reasons


def _candidate_report(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "证券代码": candidate.get("ts_code"),
        "证券名称": candidate.get("name"),
        "候选等级": candidate.get("candidate_grade_label"),
        "当前动作": candidate.get("buying_status"),
        "技术形态": technical_pattern_label(
            candidate.get("technical_pattern") or candidate.get("setup_hint")
        ),
        "追高风险": candidate.get("chase_risk_label"),
        "综合可买性得分": _number(candidate.get("buyability_score")),
        "追高风险得分": _number(candidate.get("chase_risk_score")),
        "最新未复权价格": _number(candidate.get("close_raw")),
        "判断理由": list(candidate.get("candidate_grade_reasons") or []),
    }


def screening_gates(candidate: Mapping[str, object], screen: Mapping[str, object]) -> dict[str, dict[str, object]]:
    data_quality = _mapping(screen.get("data_quality"))
    quality_status = str(data_quality.get("status") or "unknown")
    participation = str(candidate.get("participation_state") or "unknown")
    extension = str(candidate.get("extension_state") or "unknown")
    volatility_percentile = _number(candidate.get("volatility_percentile"))
    momentum_percentile = _number(candidate.get("momentum_percentile"))
    chase_risk_score = _number(candidate.get("chase_risk_score"))
    trend = str(candidate.get("trend_state") or "unknown")
    legacy_ready = str(candidate.get("candidate_state") or "") == "evidence_ready"
    market_state = str(_mapping(screen.get("market_regime")).get("state") or "unknown")
    return {
        "data_quality": _gate(
            "pass" if quality_status == "ready" else "fail",
            "point-in-time data audit",
            quality_status=quality_status,
            blockers=data_quality.get("decision_blockers") or [],
        ),
        "price_extension": _gate(
            "review" if extension == "stretched" else "pass" if extension == "not_stretched" else "unknown",
            "distance from the strategy moving-average structure",
            extension_state=extension,
        ),
        "chase_risk": _gate(
            "pass" if chase_risk_score is not None and chase_risk_score < 60 else
            "review" if chase_risk_score is not None and chase_risk_score < 80 else
            "fail" if chase_risk_score is not None else
            "pass" if legacy_ready else "unknown",
            "combined risk of price extension, acceleration, volume climax, and opening gap",
            chase_risk_score=chase_risk_score,
            review_threshold=60,
            fail_threshold=80,
            legacy_inference=chase_risk_score is None and legacy_ready,
        ),
        "relative_strength": _gate(
            "pass" if momentum_percentile is not None and momentum_percentile >= 0.7 else
            "review" if momentum_percentile is not None else
            "pass" if legacy_ready else "unknown",
            "cross-sectional relative-strength threshold",
            momentum_percentile=momentum_percentile,
            minimum=0.7,
            legacy_inference=momentum_percentile is None and legacy_ready,
        ),
        "trend_structure": _gate(
            "pass" if trend == "supportive" else
            "review" if trend == "mixed" else
            "fail" if trend == "adverse" else
            "pass" if legacy_ready else "unknown",
            "moving-average trend structure",
            trend_state=trend,
            legacy_inference=trend == "unknown" and legacy_ready,
        ),
        "participation": _gate(
            "review" if participation == "adverse" else "pass" if participation in {"supportive", "mixed"} else "unknown",
            "volume participation confirmation",
            participation_state=participation,
        ),
        "volatility": _gate(
            "review" if volatility_percentile is not None and volatility_percentile >= 0.9 else "pass",
            "cross-sectional volatility risk",
            volatility_percentile=volatility_percentile,
        ),
        "market_regime": _gate(
            "review" if market_state == "hostile" else "pass" if market_state in {"supportive", "mixed"} else "unknown",
            "broad-market regime",
            market_state=market_state,
        ),
    }


def enrich_screen_readiness(payload: Mapping[str, object]) -> dict[str, Any]:
    """Attach independent mechanical gates while retaining one-cycle legacy fields."""
    result = deepcopy(dict(payload))
    result["schema_version"] = SCHEMA_VERSION
    candidates = result.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    statuses: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        gates = screening_gates(candidate, result)
        screening_status = aggregate_gate_status(gates)
        statuses.append(screening_status)
        legacy_state = str(candidate.get("candidate_state") or "")
        candidate["gates"] = gates
        candidate["readiness"] = {
            "screening": screening_status,
            "research": "unknown",
            "trade_plan": "unknown",
            "personal_investor_controls": "unknown",
            "position_sizing": "not_required",
        }
        candidate["decision_ready"] = False
        candidate["execution_ready"] = False
        candidate["evidence_ready"] = screening_status == "pass"
        grade, grade_label, buying_status, grade_reasons = _candidate_grade(
            candidate,
            gates,
            screening_status,
        )
        candidate["candidate_grade"] = grade
        candidate["candidate_grade_label"] = grade_label
        candidate["buying_status"] = buying_status
        candidate["candidate_grade_reasons"] = grade_reasons
        chase_score = _number(candidate.get("chase_risk_score"))
        stretched = _text(candidate.get("extension_state")) == "stretched"
        candidate["chase_risk_label"] = (
            "高"
            if chase_score is not None and chase_score >= 80
            else "中"
            if chase_score is not None and (chase_score >= 60 or stretched)
            else "低"
            if chase_score is not None
            else "待确认"
        )
        candidate["compatibility"] = {
            "candidate_state": legacy_state,
            "candidate_state_deprecated": True,
            "evidence_ready_scope": "mechanical_screening_only",
        }
    screening_summary = {
        status: statuses.count(status)
        for status in ("pass", "review", "unknown", "fail")
    }
    grade_summary = {
        grade: sum(
            1 for candidate in candidates
            if isinstance(candidate, Mapping) and candidate.get("candidate_grade") == grade
        )
        for grade in ("A", "B", "C")
    }
    result["screen_status"] = (
        "executable_candidates_available"
        if grade_summary["A"]
        else "research_candidates_waiting_for_price"
        if grade_summary["B"]
        else "strong_watch_candidates_only"
        if grade_summary["C"]
        else "no_edge_found"
    )
    result["readiness"] = {
        "screening": "pass" if screening_summary["pass"] else "review" if candidates else "fail",
        "research": "unknown",
        "trade_plan": "unknown",
        "personal_investor_controls": "unknown",
        "position_sizing": "not_required",
        "decision_ready": False,
        "execution_ready": False,
        "candidate_counts": screening_summary,
        "candidate_grade_counts": grade_summary,
    }
    result["report"] = {
        "报告说明": "候选等级不是成交指令；A类进入执行检查但仍须满足入场条件，B类等待价格，C类只观察强势、不追价。",
        "候选分档": [
            _candidate_report(candidate)
            for candidate in candidates
            if isinstance(candidate, Mapping)
        ],
    }
    result["compatibility"] = {
        "screen_status_deprecated": True,
        "candidate_state_deprecated": True,
        "evidence_ready_is_not_decision_ready": True,
    }
    return result


def _event_records(events: Sequence[Mapping[str, object]], symbol: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in events:
        if str(item.get("ts_code") or "") != symbol:
            continue
        payload: object = item.get("payload_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {"raw": payload}
        records.append(
            {
                "dataset": item.get("dataset"),
                "event_date": item.get("event_date"),
                "source": item.get("source"),
                "available_at": item.get("retrieved_at"),
                "payload": payload if isinstance(payload, Mapping) else {},
            }
        )
    return records


def assessment_template(symbol: str, as_of: str, contract_name: str) -> dict[str, object]:
    contract = strategy_contract(contract_name)
    return {
        "assessment_version": 2,
        "symbol": symbol,
        "as_of": as_of,
        "strategy_contract": contract_name,
        "event": {
            "status": "unknown" if contract["event_required"] else "not_required",
            "thesis": "",
            "sources": [],
            "unknowns": [],
        },
        "expectation_gap": {"status": "unknown", "thesis": "", "basis": ""},
        "priced_in": {"status": "unknown", "thesis": ""},
        "crowding": {"status": "unknown", "thesis": ""},
        "counter_scenario": {"thesis": "", "trigger": ""},
        "technical_setup": {
            "setup_type": contract["default_setup_type"],
            "hypothesis": "",
            "relative_strength_status": "unknown",
            "trend_structure_status": "unknown",
            "participation_status": "unknown",
            "extension_status": "unknown",
            "trigger_rule": "",
            "invalidation_rule": "",
            "valid_until": "",
            "counter_evidence": [],
        },
        "trade_plan": {
            "action_label": "等待证据",
            "entry_trigger": "",
            "price_invalidation": "",
            "event_invalidation": "",
            "time_invalidation": "",
            "maximum_holding_sessions": contract["maximum_holding_sessions"],
            "expected_upside_pct": None,
            "effective_downside_pct": None,
            "cash_comparison": "",
        },
        "investor_constraints": {
            "decision_frequency": contract["decision_frequency"],
            "maximum_open_positions": None,
            "single_trade_risk_budget_pct": None,
            "portfolio_heat_limit_pct": None,
            "theme_concentration_limit_pct": None,
            "maximum_new_trades_per_session": None,
            "loss_streak_pause_after": None,
            "overnight_gap_buffer_pct": None,
            "minimum_liquidity_multiple": None,
        },
        "confidence": "low",
        "thesis": "",
    }


def _technical_snapshot(candidate: Mapping[str, object], contract: Mapping[str, object]) -> dict[str, object]:
    raw_price = _number(candidate.get("close_raw"))
    adjusted_price = _number(candidate.get("close_qfq"))
    contract_default = _text(contract.get("default_setup_type"))
    setup_hint = (
        contract_default
        if contract_default == "event_continuation"
        else technical_pattern_code(candidate.get("technical_pattern"))
        or _text(candidate.get("setup_hint"))
        or contract_default
    )
    return {
        "setup_hint": setup_hint,
        "allowed_setup_types": list(contract.get("allowed_setup_types") or []),
        "trend_state": candidate.get("trend_state"),
        "participation_state": candidate.get("participation_state"),
        "extension_state": candidate.get("extension_state"),
        "momentum_percentile": _number(candidate.get("momentum_percentile")),
        "primary_relative_return": _number(candidate.get("primary_relative_strength")),
        "primary_relative_return_field": candidate.get("primary_relative_strength_field"),
        "price_vs_primary_ma": _number(candidate.get("price_vs_primary_ma")),
        "price_extension_atr": _number(candidate.get("price_extension_atr")),
        "own_extension_percentile_120d": _number(candidate.get("own_extension_percentile_120d")),
        "return_acceleration_5v20": _number(candidate.get("return_acceleration_5v20")),
        "return_acceleration_percentile": _number(candidate.get("return_acceleration_percentile")),
        "open_gap_pct": _number(candidate.get("open_gap_pct")),
        "positive_sessions_3d": _number(candidate.get("positive_sessions_3d")),
        "close_location_20d": _number(candidate.get("close_location_20d")),
        "volume_ratio_20d": _number(candidate.get("volume_ratio_20d")),
        "up_volume_share_20d": _number(candidate.get("up_volume_share_20d")),
        "chase_risk_score": _number(candidate.get("chase_risk_score")),
        "buyability_score": _number(candidate.get("buyability_score")),
        "candidate_grade": candidate.get("candidate_grade"),
        "candidate_grade_label": candidate.get("candidate_grade_label"),
        "analysis_price": adjusted_price,
        "analysis_price_basis": "forward_adjusted_qfq",
        "execution_reference_price": raw_price,
        "execution_price_basis": "raw_unadjusted_required",
        "execution_reference_available": raw_price is not None,
        "adjustment_factor": _number(candidate.get("adj_factor")),
        "usage_boundary": (
            "Adjusted prices support historical comparisons only. Entry, invalidation, and orders must use "
            "a contemporaneous raw market price before execution."
        ),
    }


def build_evidence_bundle(
    screen: Mapping[str, object],
    *,
    symbol: str,
    contract_name: str,
    events: Sequence[Mapping[str, object]] = (),
    indicator_snapshot: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    contract = strategy_contract(contract_name)
    candidates = [
        item for item in screen.get("candidates", [])
        if isinstance(item, Mapping) and str(item.get("ts_code") or "") == symbol
    ]
    candidate = dict(candidates[0]) if candidates else None
    screening_status = str(_mapping(candidate or {}).get("readiness", {}).get("screening") or "fail")
    technical_snapshot = _technical_snapshot(_mapping(candidate), contract)
    technical_snapshot["indicator_snapshot"] = deepcopy(dict(indicator_snapshot or {}))
    technical_snapshot["indicator_snapshot_available"] = bool(indicator_snapshot)
    return {
        "operation": "short_evidence",
        "schema_version": SCHEMA_VERSION,
        "strategy_contract": contract_name,
        "strategy_rules": contract,
        "profile": contract["profile"],
        "benchmark": screen.get("benchmark"),
        "requested_as_of": screen.get("requested_as_of"),
        "effective_trade_date": screen.get("effective_trade_date"),
        "symbol": symbol,
        "screening_status": screening_status,
        "candidate": candidate,
        "technical_snapshot": technical_snapshot,
        "price_basis_contract": {
            "analysis": "forward_adjusted_qfq",
            "execution": "raw_unadjusted_required",
            "execution_reference_available": technical_snapshot["execution_reference_available"],
        },
        "market_regime": screen.get("market_regime"),
        "driver_diagnostics": screen.get("driver_diagnostics"),
        "data_quality": screen.get("data_quality"),
        "event_leads": _event_records(events, symbol),
        "readiness": {
            "screening": screening_status,
            "technical_setup": "unknown",
            "research": "unknown",
            "trade_plan": "unknown",
            "personal_investor_controls": "unknown",
            "position_sizing": "not_required",
            "decision_ready": False,
            "execution_ready": False,
        },
        "assessment_template": assessment_template(
            symbol,
            str(screen.get("requested_as_of") or ""),
            contract_name,
        ),
        "boundary": (
            "This bundle contains point-in-time evidence and mechanical gates only. "
            "It is not a recommendation until a separate Agent assessment passes validation. "
            "Adjusted prices are never executable order prices."
        ),
    }


def _assessment_status(value: object) -> str:
    status = _text(value) or "unknown"
    return status if status in TECHNICAL_ASSESSMENT_STATUSES else "unknown"


def _technical_setup_gates(
    evidence: Mapping[str, object],
    assessment: Mapping[str, object],
    plan: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    supplied = _mapping(assessment.get("technical_setup"))
    compatibility_inferred = not bool(supplied)
    snapshot = _mapping(evidence.get("technical_snapshot"))
    screening = _mapping(_mapping(evidence.get("candidate")).get("gates"))
    setup_type = _text(supplied.get("setup_type")) or _text(snapshot.get("setup_hint")) or _text(
        contract.get("default_setup_type")
    )
    allowed_setup_types = set(contract.get("allowed_setup_types") or [])
    hypothesis = _text(supplied.get("hypothesis")) or _text(assessment.get("thesis"))
    trigger_rule = _text(supplied.get("trigger_rule")) or _text(plan.get("entry_trigger"))
    invalidation_rule = _text(supplied.get("invalidation_rule")) or _text(plan.get("price_invalidation"))
    valid_until = _text(supplied.get("valid_until")) or _text(plan.get("time_invalidation"))

    def assessed_or_screened(field: str, screening_gate: str) -> str:
        if supplied:
            return _assessment_status(supplied.get(field))
        return _text(_mapping(screening.get(screening_gate)).get("status")) or "unknown"

    relative_strength = assessed_or_screened("relative_strength_status", "relative_strength")
    trend_structure = assessed_or_screened("trend_structure_status", "trend_structure")
    participation = assessed_or_screened("participation_status", "participation")
    extension = assessed_or_screened("extension_status", "price_extension")
    gates = {
        "setup_identified": _gate(
            "pass" if setup_type in allowed_setup_types and setup_type in TECHNICAL_SETUP_TYPES else "fail",
            "setup type must be defined by the frozen strategy contract",
            setup_type=setup_type,
            allowed_setup_types=sorted(allowed_setup_types),
        ),
        "behavioral_hypothesis": _gate(
            "pass" if hypothesis else "unknown",
            "the setup requires a falsifiable behavioral or flow hypothesis",
        ),
        "relative_strength": _gate(relative_strength, "relative-strength evidence for this setup"),
        "trend_structure": _gate(trend_structure, "trend structure for this setup"),
        "participation": _gate(participation, "volume participation for this setup"),
        "extension": _gate(extension, "entry must not rely on an overextended price"),
        "trigger_defined": _gate("pass" if trigger_rule else "unknown", "observable entry trigger"),
        "invalidation_defined": _gate(
            "pass" if invalidation_rule else "unknown",
            "observable price invalidation",
        ),
        "validity_window": _gate("pass" if valid_until else "unknown", "finite trigger validity window"),
        "execution_price_basis": _gate(
            "pass",
            "raw price is required before execution; research readiness does not imply an executable quote",
            execution_reference_available=bool(snapshot.get("execution_reference_available")),
            analysis_price_basis=snapshot.get("analysis_price_basis"),
            execution_price_basis=snapshot.get("execution_price_basis"),
        ),
    }
    normalized = {
        "setup_type": setup_type,
        "hypothesis": hypothesis,
        "relative_strength_status": relative_strength,
        "trend_structure_status": trend_structure,
        "participation_status": participation,
        "extension_status": extension,
        "trigger_rule": trigger_rule,
        "invalidation_rule": invalidation_rule,
        "valid_until": valid_until,
        "counter_evidence": list(supplied.get("counter_evidence") or []),
        "compatibility_inferred": compatibility_inferred,
    }
    return gates, normalized


def _source_timestamp_gate(
    sources: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    required: bool,
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    if not sources:
        if required:
            return _gate("unknown", "required event sources are missing"), errors
        return _gate("not_required", "event sources are not required by this strategy"), errors
    cutoff = pd.Timestamp(as_of).normalize() + pd.Timedelta(days=1)
    valid = 0
    for position, source in enumerate(sources):
        if not _text(source.get("source") or source.get("title")):
            errors.append(f"event.sources[{position}] requires source or title")
        available_at = _text(source.get("available_at"))
        if not available_at:
            errors.append(f"event.sources[{position}] requires available_at")
            continue
        try:
            timestamp = pd.Timestamp(available_at)
            comparable = timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp
        except (TypeError, ValueError):
            errors.append(f"event.sources[{position}].available_at is invalid")
            continue
        if comparable >= cutoff:
            errors.append(f"event.sources[{position}] was not available by as_of")
            continue
        valid += 1
    return _gate("pass" if valid and not errors else "fail", "source availability audit", valid_sources=valid), errors


def confirm_evidence(evidence: Mapping[str, object], assessment: Mapping[str, object]) -> dict[str, Any]:
    symbol = _text(evidence.get("symbol"))
    contract_name = _text(evidence.get("strategy_contract"))
    contract = strategy_contract(contract_name)
    as_of = _text(evidence.get("requested_as_of"))
    errors: list[str] = []
    if _text(assessment.get("symbol")) != symbol:
        errors.append("assessment.symbol must match evidence.symbol")
    if _text(assessment.get("strategy_contract")) != contract_name:
        errors.append("assessment.strategy_contract must match evidence.strategy_contract")
    if pd.Timestamp(_text(assessment.get("as_of"))).normalize() != pd.Timestamp(as_of).normalize():
        errors.append("assessment.as_of must match evidence.requested_as_of")

    event = _mapping(assessment.get("event"))
    event_status = _text(event.get("status")) or "unknown"
    event_required = bool(contract["event_required"])
    sources = _list_of_mappings(event.get("sources"))
    source_gate, source_errors = _source_timestamp_gate(sources, as_of=as_of, required=event_required)
    errors.extend(source_errors)
    event_gate = _gate(
        "pass" if event_status == "verified" else "not_required" if not event_required else "unknown",
        "event verification required by strategy contract" if event_required else "event is optional for momentum_trade",
        assessment_status=event_status,
    )

    expectation = _mapping(assessment.get("expectation_gap"))
    expectation_status = _text(expectation.get("status")) or "unknown"
    expectation_gate = _gate(
        "pass" if expectation_status == "positive" and _text(expectation.get("thesis")) else
        "review" if expectation_status == "neutral" else "fail" if expectation_status == "negative" else "unknown",
        "expected information or positioning gap",
        assessment_status=expectation_status,
    )
    priced = _mapping(assessment.get("priced_in"))
    priced_status = _text(priced.get("status")) or "unknown"
    priced_gate = _gate(
        "pass" if priced_status in {"low", "moderate"} and _text(priced.get("thesis")) else
        "review" if priced_status == "high" else "unknown",
        "degree to which the thesis is already reflected in price",
        assessment_status=priced_status,
    )
    crowding = _mapping(assessment.get("crowding"))
    crowding_status = _text(crowding.get("status")) or "unknown"
    crowding_gate = _gate(
        "pass" if crowding_status in {"low", "moderate"} and _text(crowding.get("thesis")) else
        "review" if crowding_status == "high" else "unknown",
        "crowding and exit-liquidity judgment",
        assessment_status=crowding_status,
    )
    counter = _mapping(assessment.get("counter_scenario"))
    counter_gate = _gate(
        "pass" if _text(counter.get("thesis")) and _text(counter.get("trigger")) else "unknown",
        "falsifiable counter-scenario",
    )
    research_gates = {
        "event_verification": event_gate,
        "source_timestamps": source_gate,
        "expectation_gap": expectation_gate,
        "priced_in": priced_gate,
        "crowding": crowding_gate,
        "counter_scenario": counter_gate,
    }

    plan = _mapping(assessment.get("trade_plan"))
    action_label = _text(plan.get("action_label"))
    if action_label not in ACTION_LABELS:
        errors.append(f"trade_plan.action_label must be one of: {', '.join(sorted(ACTION_LABELS))}")
    maximum_holding = _number(plan.get("maximum_holding_sessions"))
    holding_gate = _gate(
        "pass" if maximum_holding is not None and 0 < maximum_holding <= int(contract["maximum_holding_sessions"]) else "fail",
        "maximum holding period must fit the strategy contract",
        proposed=maximum_holding,
        contract_maximum=contract["maximum_holding_sessions"],
    )
    required_plan_fields = (
        "entry_trigger", "price_invalidation", "event_invalidation", "time_invalidation", "cash_comparison"
    )
    plan_fields_gate = _gate(
        "pass" if all(_text(plan.get(field)) for field in required_plan_fields) else "unknown",
        "entry, invalidation, time, and cash-comparison plan",
        missing=[field for field in required_plan_fields if not _text(plan.get(field))],
    )
    upside = _number(plan.get("expected_upside_pct"))
    downside = _number(plan.get("effective_downside_pct"))
    reward_risk = upside / downside if upside is not None and downside is not None and downside > 0 else None
    reward_risk_gate = _gate(
        "pass" if reward_risk is not None and reward_risk >= float(contract["minimum_reward_risk"]) else
        "review" if reward_risk is not None else "unknown",
        "expected upside divided by effective downside",
        ratio=reward_risk,
        minimum=contract["minimum_reward_risk"],
    )
    trade_plan_gates = {
        "plan_fields": plan_fields_gate,
        "holding_period": holding_gate,
        "reward_risk": reward_risk_gate,
    }

    technical_gates, technical_setup = _technical_setup_gates(
        evidence,
        assessment,
        plan,
        contract,
    )
    constraints = _mapping(assessment.get("investor_constraints"))
    required_control_fields = (
        "maximum_open_positions",
        "single_trade_risk_budget_pct",
        "portfolio_heat_limit_pct",
        "maximum_new_trades_per_session",
        "overnight_gap_buffer_pct",
        "minimum_liquidity_multiple",
    )
    missing_control_fields = [
        field
        for field in required_control_fields
        if (_number(constraints.get(field)) or 0) <= 0
    ]
    decision_frequency = _text(constraints.get("decision_frequency")) or _text(
        contract.get("decision_frequency")
    )
    if action_label == "选择现金":
        investor_control_gate = _gate(
            "not_required",
            "cash selection does not require position-risk parameters",
        )
    elif decision_frequency != _text(contract.get("decision_frequency")):
        investor_control_gate = _gate(
            "fail",
            "decision frequency must match the frozen strategy contract",
            proposed=decision_frequency,
            required=contract.get("decision_frequency"),
        )
    else:
        investor_control_gate = _gate(
            "pass" if not missing_control_fields else "unknown",
            "core personal-investor limits must be recorded before priority action",
            missing=missing_control_fields,
        )
    investor_controls = {
        "status": (
            "not_required_for_cash"
            if investor_control_gate["status"] == "not_required"
            else "recorded_not_position_sized"
            if investor_control_gate["status"] == "pass"
            else "user_parameters_required"
        ),
        "decision_frequency": decision_frequency,
        "maximum_open_positions": _number(constraints.get("maximum_open_positions")),
        "single_trade_risk_budget_pct": _number(constraints.get("single_trade_risk_budget_pct")),
        "portfolio_heat_limit_pct": _number(constraints.get("portfolio_heat_limit_pct")),
        "theme_concentration_limit_pct": _number(constraints.get("theme_concentration_limit_pct")),
        "maximum_new_trades_per_session": _number(
            constraints.get("maximum_new_trades_per_session")
        ),
        "loss_streak_pause_after": _number(constraints.get("loss_streak_pause_after")),
        "overnight_gap_buffer_pct": _number(constraints.get("overnight_gap_buffer_pct")),
        "minimum_liquidity_multiple": _number(constraints.get("minimum_liquidity_multiple")),
        "boundary": (
            "These controls are not position sizing. Account value, portfolio exposures, raw entry price, "
            "raw invalidation price, and user-approved limits are still required before execution."
        ),
    }

    screening_status = _text(_mapping(evidence.get("readiness")).get("screening")) or "unknown"
    technical_status = aggregate_gate_status(technical_gates)
    research_status = aggregate_gate_status(research_gates)
    trade_plan_status = aggregate_gate_status(trade_plan_gates)
    research_decision_ready = all(
        status == "pass"
        for status in (screening_status, technical_status, research_status, trade_plan_status)
    )
    investor_control_status = str(investor_control_gate["status"])
    decision_ready = research_decision_ready and investor_control_status in {"pass", "not_required"}
    if action_label == "优先行动" and not decision_ready:
        errors.append(
            "优先行动 requires screening, technical_setup, research, trade_plan, and personal-investor "
            "controls readiness to pass"
        )
    confidence = _text(assessment.get("confidence"))
    if confidence not in CONFIDENCE_LEVELS:
        errors.append("confidence must be high, medium, or low")
    if not _text(assessment.get("thesis")):
        errors.append("thesis is required")
    if errors:
        raise ValueError("Assessment validation failed: " + "; ".join(errors))

    recommendation = None
    report: dict[str, object]
    if action_label != "选择现金":
        candidate = _mapping(evidence.get("candidate"))
        pattern_name = technical_pattern_label(technical_setup.get("setup_type"))
        report_card = {
            "证券代码": symbol,
            "证券名称": candidate.get("name"),
            "候选等级": candidate.get("candidate_grade_label") or "待确认",
            "当前行动": action_label,
            "技术形态": pattern_name,
            "行为假设": technical_setup.get("hypothesis"),
            "入场条件": technical_setup.get("trigger_rule"),
            "价格失效": technical_setup.get("invalidation_rule"),
            "有效期": technical_setup.get("valid_until"),
            "预期上行百分比": upside,
            "有效下行百分比": downside,
            "预期赔率": reward_risk,
            "现金比较": _text(plan.get("cash_comparison")),
            "追高风险": candidate.get("chase_risk_label") or "待确认",
            "追高风险得分": _number(candidate.get("chase_risk_score")),
            "仓位测算状态": "尚未测算",
        }
        recommendation = {
            "symbol": symbol,
            "name": candidate.get("name"),
            "strategy_contract": contract_name,
            "action_label": action_label,
            "confidence": confidence,
            "thesis": _text(assessment.get("thesis")),
            "technical_pattern": {
                "name": pattern_name,
                "hypothesis": technical_setup.get("hypothesis"),
                "trigger": technical_setup.get("trigger_rule"),
                "invalidation": technical_setup.get("invalidation_rule"),
                "valid_until": technical_setup.get("valid_until"),
            },
            "entry_trigger": _text(plan.get("entry_trigger")),
            "invalidation": {
                "price": _text(plan.get("price_invalidation")),
                "event": _text(plan.get("event_invalidation")),
                "time": _text(plan.get("time_invalidation")),
            },
            "maximum_holding_sessions": int(maximum_holding) if maximum_holding is not None else None,
            "price_basis": deepcopy(_mapping(evidence.get("price_basis_contract"))),
            "personal_investor_controls": deepcopy(investor_controls),
            "report_card": report_card,
            "recommended_on": as_of,
        }
        report = report_card
    else:
        report = {
            "当前行动": "选择现金",
            "结论": "没有候选同时通过证据、价格、赔率和个人风险约束。",
        }
    return {
        "operation": "short_confirmation",
        "schema_version": SCHEMA_VERSION,
        "strategy_contract": contract_name,
        "profile": evidence.get("profile"),
        "benchmark": evidence.get("benchmark"),
        "requested_as_of": as_of,
        "symbol": symbol,
        "readiness": {
            "screening": screening_status,
            "technical_setup": technical_status,
            "research": research_status,
            "trade_plan": trade_plan_status,
            "personal_investor_controls": investor_control_status,
            "position_sizing": "not_required",
        },
        "gates": {
            "screening": _mapping(_mapping(evidence.get("candidate")).get("gates")),
            "technical_setup": technical_gates,
            "research": research_gates,
            "trade_plan": trade_plan_gates,
            "personal_investor_controls": {"core_parameters": investor_control_gate},
        },
        "decision_ready": decision_ready,
        "execution_ready": False,
        "execution_status": "not_observed",
        "personal_investor_controls": investor_controls,
        "recommendation": recommendation,
        "report": report,
        "cash_selected": action_label == "选择现金",
        "assessment": deepcopy(dict(assessment)),
        "evidence": deepcopy(dict(evidence)),
        "boundary": (
            "This is a research recommendation, not evidence that the user traded. "
            "Execution remains not_observed unless separately provided by the user."
        ),
    }


def compact_confirmation(confirmation: Mapping[str, object]) -> dict[str, Any]:
    """Keep the recommendation index while omitting the optional full decision snapshot."""
    result = {
        key: deepcopy(value)
        for key, value in confirmation.items()
        if key not in {"assessment", "evidence", "gates"}
    }
    readiness = result.get("readiness")
    if isinstance(readiness, Mapping):
        readiness = dict(readiness)
        if "technical_setup" in readiness:
            readiness["technical_pattern"] = readiness.pop("technical_setup")
        result["readiness"] = readiness
    result["decision_snapshot_saved"] = False
    result["snapshot_scope"] = "recommendation_record_only"
    return result


def review_recommendation(
    recommendation_record: Mapping[str, object],
    review_assessment: Mapping[str, object],
    *,
    review_as_of: str,
    price_history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
) -> dict[str, Any]:
    """Review one explicitly requested recommendation without assuming execution."""
    recommendation = _mapping(recommendation_record.get("recommendation"))
    symbol = _text(recommendation.get("symbol") or recommendation_record.get("symbol"))
    recommended_on = _text(recommendation.get("recommended_on") or recommendation_record.get("requested_as_of"))
    if not symbol or not recommended_on:
        raise ValueError("Recommendation record lacks symbol or recommended_on")
    allowed_event_outcomes = {"occurred", "not_occurred", "partial", "unknown", "not_applicable"}
    allowed_thesis_outcomes = {"confirmed", "refuted", "mixed", "unknown"}
    event_outcome = _text(review_assessment.get("event_outcome"))
    thesis_outcome = _text(review_assessment.get("thesis_outcome"))
    if event_outcome not in allowed_event_outcomes:
        raise ValueError("review event_outcome is invalid")
    if thesis_outcome not in allowed_thesis_outcomes:
        raise ValueError("review thesis_outcome is invalid")

    frame = price_history.copy()
    frame["trade_date"] = pd.to_datetime(frame.get("trade_date"), errors="coerce")
    frame = frame.loc[
        frame.get("ts_code").astype(str).eq(symbol)
        & frame["trade_date"].between(pd.Timestamp(recommended_on), pd.Timestamp(review_as_of))
    ].sort_values("trade_date")
    entry = _number(frame.iloc[0].get("close_qfq")) if not frame.empty else None
    exit_price = _number(frame.iloc[-1].get("close_qfq")) if not frame.empty else None
    forward_return = (exit_price / entry) - 1.0 if entry and exit_price else None
    path_low = _number(pd.to_numeric(frame.get("low_qfq"), errors="coerce").min()) if not frame.empty else None
    path_high = _number(pd.to_numeric(frame.get("high_qfq"), errors="coerce").max()) if not frame.empty else None

    benchmark = benchmark_history.copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark.get("trade_date"), errors="coerce")
    benchmark = benchmark.loc[
        benchmark["trade_date"].between(pd.Timestamp(recommended_on), pd.Timestamp(review_as_of))
    ].sort_values("trade_date")
    benchmark_entry = _number(benchmark.iloc[0].get("close")) if not benchmark.empty else None
    benchmark_exit = _number(benchmark.iloc[-1].get("close")) if not benchmark.empty else None
    benchmark_return = (
        (benchmark_exit / benchmark_entry) - 1.0
        if benchmark_entry and benchmark_exit else None
    )
    execution_status = _text(review_assessment.get("execution_status")) or "not_observed"
    return {
        "operation": "short_review",
        "schema_version": SCHEMA_VERSION,
        "strategy_contract": recommendation_record.get("strategy_contract"),
        "benchmark": recommendation_record.get("benchmark"),
        "requested_as_of": review_as_of,
        "symbol": symbol,
        "recommended_on": recommended_on,
        "review_status": "completed" if forward_return is not None else "insufficient_evidence",
        "review_trigger": "explicit_user_request",
        "original_recommendation": deepcopy(dict(recommendation)),
        "research_outcome": {
            "event_outcome": event_outcome,
            "thesis_outcome": thesis_outcome,
            "forward_return": forward_return,
            "benchmark_return": benchmark_return,
            "excess_return": forward_return - benchmark_return
            if forward_return is not None and benchmark_return is not None else None,
            "mae": (path_low / entry) - 1.0 if path_low is not None and entry else None,
            "mfe": (path_high / entry) - 1.0 if path_high is not None and entry else None,
            "price_basis": "first available close_qfq through review_as_of close_qfq",
        },
        "execution_status": execution_status,
        "execution_review": "not_observed" if execution_status == "not_observed" else "user_reported",
        "error_classification": review_assessment.get("error_classification") or "not_observed",
        "assessment": deepcopy(dict(review_assessment)),
        "boundary": (
            "Forward price paths evaluate the research recommendation. They are not account returns "
            "and do not imply that the recommendation was executed."
        ),
    }
