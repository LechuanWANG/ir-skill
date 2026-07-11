from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .domain import (
    AssessmentStage,
    ContextStatus,
    CurrentAssessment,
    DecisionCard,
    DimensionResult,
    DimensionStatus,
    EntryAction,
    EvidenceItem,
    Hypothesis,
    LongTermAssessment,
    LongTermVerdict,
    OutcomeSnapshot,
    OverheatAssessment,
    PortfolioAction,
    ResearchClaim,
    ResearchRun,
    ResearchStatus,
    WorkflowStage,
)
from .store import ResearchStore


DEFAULT_LONG_TERM_DIMENSIONS = (
    "business_demand",
    "growth_runway",
    "competitive_advantage",
    "financial_quality",
    "capital_allocation",
    "governance_tail_risk",
    "implied_expectations",
)

CORE_OVERHEAT_METRICS = {
    "price_bars",
    "close",
    "return_20d",
    "return_60d",
    "return_20d_market_percentile",
    "return_60d_industry_percentile",
    "valuation_history_percentile",
    "data_timestamp",
}


def resolve_trade_horizon_dates(
    *,
    as_of: str,
    trade_calendar: Sequence[str | Mapping[str, Any]],
    horizons: Sequence[int] = (20, 60, 120),
) -> dict[int, str]:
    as_of_date = datetime.fromisoformat(
        f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of.isdigit() and len(as_of) == 8 else as_of[:10]
    ).date()
    open_dates = []
    for item in trade_calendar:
        if isinstance(item, Mapping):
            if str(item.get("is_open", "1")) not in {"1", "True", "true"}:
                continue
            value = str(item.get("cal_date") or item.get("trade_date") or item.get("date") or "")
        else:
            value = str(item)
        if not value:
            continue
        normalized = (
            f"{value[:4]}-{value[4:6]}-{value[6:8]}"
            if value.isdigit() and len(value) == 8
            else value[:10]
        )
        parsed = datetime.fromisoformat(normalized).date()
        if parsed > as_of_date:
            open_dates.append(parsed)
    ordered = sorted(set(open_dates))
    resolved = {}
    for horizon in horizons:
        if horizon <= 0 or len(ordered) < horizon:
            raise ValueError(f"trade calendar does not cover {horizon} sessions after {as_of}")
        resolved[int(horizon)] = ordered[horizon - 1].isoformat()
    return resolved


def assess_long_term(
    *,
    run_id: str,
    symbol: str,
    years_covered: float,
    dimensions: Sequence[DimensionResult],
    hypotheses: Sequence[Hypothesis],
    rationale: str,
    structural_risks: Sequence[str] = (),
    hard_vetoes: Sequence[str] = (),
    missing_evidence: Sequence[str] = (),
    blocking_evidence: Sequence[str] = (),
    confidence_limiters: Sequence[str] = (),
    monitoring_items: Sequence[str] = (),
    process_gaps: Sequence[str] = (),
    confidence: float = 0.5,
    minimum_years: float = 3.0,
    minimum_hypotheses: int = 3,
    required_dimensions: Sequence[str] = DEFAULT_LONG_TERM_DIMENSIONS,
    hard_reject_dimensions: Sequence[str] = (
        "business_demand",
        "financial_quality",
        "governance_tail_risk",
    ),
    current_stage_dimensions: Sequence[str] = ("implied_expectations",),
    minimum_distinct_evidence: int = 3,
) -> LongTermAssessment:
    dimension_map = {dimension.name: dimension for dimension in dimensions}
    if len(dimension_map) != len(dimensions):
        raise ValueError("long-term dimensions must be unique")
    hypothesis_keys = [hypothesis.thesis_key for hypothesis in hypotheses]
    if len(set(hypothesis_keys)) != len(hypothesis_keys):
        raise ValueError("active long-term hypothesis keys must be unique")
    required_missing = [name for name in required_dimensions if name not in dimension_map]
    hypothesis_gaps = [
        hypothesis.thesis_key
        for hypothesis in hypotheses
        if (
            not hypothesis.validation_metrics
            or not hypothesis.falsification_condition.strip()
            or not hypothesis.next_review_date
        )
    ]
    workflow_gaps = list(process_gaps)
    workflow_gaps.extend(f"missing dimension: {name}" for name in required_missing)
    dimension_evidence_gaps = [
        name
        for name in required_dimensions
        if name in dimension_map and not dimension_map[name].evidence_ids
    ]
    workflow_gaps.extend(
        f"long-term dimension lacks evidence: {name}"
        for name in dimension_evidence_gaps
    )
    distinct_evidence = {
        evidence_id
        for dimension in dimensions
        for evidence_id in dimension.evidence_ids
    }
    if len(distinct_evidence) < minimum_distinct_evidence:
        workflow_gaps.append(
            f"fewer than {minimum_distinct_evidence} distinct long-term evidence items"
        )
    workflow_gaps.extend(f"hypothesis lacks validation contract: {key}" for key in hypothesis_gaps)
    if years_covered < minimum_years:
        workflow_gaps.append(f"history coverage below {minimum_years:g} years")
    if len(hypotheses) < minimum_hypotheses:
        workflow_gaps.append(f"fewer than {minimum_hypotheses} active hypotheses")

    failed_dimensions = {dimension.name for dimension in dimensions if dimension.status == DimensionStatus.FAIL}
    hard_failed = failed_dimensions.intersection(hard_reject_dimensions)
    soft_failed = failed_dimensions.difference(hard_reject_dimensions).difference(current_stage_dimensions)
    blockers = list((*missing_evidence, *blocking_evidence))
    blockers.extend(f"failed long-term dimension needs resolution: {name}" for name in sorted(soft_failed))
    if hard_failed or hard_vetoes:
        verdict = LongTermVerdict.REJECT
        research_complete = True
    elif workflow_gaps or any(dimension.status == DimensionStatus.MISSING for dimension in dimensions):
        verdict = LongTermVerdict.INSUFFICIENT
        research_complete = False
    elif blockers:
        verdict = LongTermVerdict.INSUFFICIENT
        research_complete = True
    else:
        verdict = LongTermVerdict.PASS
        research_complete = True

    return LongTermAssessment(
        run_id=run_id,
        symbol=symbol,
        verdict=verdict,
        years_covered=years_covered,
        dimensions=tuple(dimensions),
        hypothesis_ids=tuple(hypothesis.hypothesis_id for hypothesis in hypotheses),
        rationale=rationale,
        structural_risks=tuple(structural_risks),
        hard_vetoes=tuple(hard_vetoes),
        missing_evidence=tuple(dict.fromkeys(blockers)),
        blocking_evidence=tuple(dict.fromkeys(blockers)),
        confidence_limiters=tuple(dict.fromkeys(confidence_limiters)),
        monitoring_items=tuple(dict.fromkeys(monitoring_items)),
        process_gaps=tuple(dict.fromkeys(workflow_gaps)),
        research_complete=research_complete,
        confidence=confidence,
    )


def assess_current(
    *,
    run_id: str,
    symbol: str,
    long_term: LongTermAssessment,
    overheat: OverheatAssessment,
    recent_event_status: ContextStatus,
    macro_status: ContextStatus,
    industry_status: ContextStatus,
    valuation_status: ContextStatus,
    technical_liquidity_status: ContextStatus,
    evidence_complete: bool,
    odds_adequate: bool,
    rationale: str,
    recent_event_assessment: str = "",
    macro_assessment: str = "",
    industry_assessment: str = "",
    valuation_assessment: str = "",
    technical_liquidity_assessment: str = "",
    base_case: str = "",
    upside_case: str = "",
    downside_case: str = "",
    acceptable_price_low: float | None = None,
    acceptable_price_high: float | None = None,
    wait_conditions: Sequence[str] = (),
    key_risks: Sequence[str] = (),
    hard_current_risks: Sequence[str] = (),
    liquidity_unacceptable: bool = False,
    portfolio_fit: str = "not_assessed",
    portfolio_constraints: Sequence[str] = (),
    concentration_impact: str | None = None,
    liquidity_exit_assessment: str | None = None,
    alternative_cost: str | None = None,
    missing_evidence: Sequence[str] = (),
    blocking_evidence: Sequence[str] = (),
    confidence_limiters: Sequence[str] = (),
    monitoring_items: Sequence[str] = (),
    process_gaps: Sequence[str] = (),
    price_regime: str = "not_assessed",
    opportunity_cost_assessment: str | None = None,
    total_shareholder_return_3y: float | None = None,
) -> CurrentAssessment:
    if long_term.verdict != LongTermVerdict.PASS:
        raise ValueError("current assessment requires long-term pass")
    statuses = (
        recent_event_status,
        macro_status,
        industry_status,
        valuation_status,
        technical_liquidity_status,
    )
    workflow_gaps = list(process_gaps)
    if any(status == ContextStatus.MISSING for status in statuses):
        workflow_gaps.append("one or more current-context dimensions are missing")
    core_overheat_missing = CORE_OVERHEAT_METRICS.intersection(overheat.missing_metrics)
    core_values = {
        "close": overheat.reference_price,
        "return_20d": overheat.return_20d,
        "return_60d": overheat.return_60d,
        "return_20d_market_percentile": overheat.return_20d_market_percentile,
        "return_60d_industry_percentile": overheat.return_60d_industry_percentile,
        "valuation_history_percentile": overheat.valuation_history_percentile,
    }
    core_overheat_missing.update(
        name for name, value in core_values.items() if value is None
    )
    if overheat.data_timestamp is None:
        core_overheat_missing.add("data_timestamp")
    if core_overheat_missing and technical_liquidity_status != ContextStatus.MISSING:
        workflow_gaps.extend(f"missing core overheat metric: {name}" for name in sorted(core_overheat_missing))
    workflow_gaps.extend(
        f"missing scenario: {name}"
        for name, value in (
            ("base_case", base_case),
            ("upside_case", upside_case),
            ("downside_case", downside_case),
        )
        if not value.strip()
    )
    if acceptable_price_low is None and acceptable_price_high is None:
        workflow_gaps.append("acceptable price range is missing")
    blockers = tuple(dict.fromkeys((*missing_evidence, *blocking_evidence)))
    research_complete = bool(evidence_complete and not workflow_gaps)
    return CurrentAssessment(
        run_id=run_id,
        symbol=symbol,
        evidence_complete=research_complete,
        odds_adequate=odds_adequate,
        recent_event_status=recent_event_status,
        macro_status=macro_status,
        industry_status=industry_status,
        valuation_status=valuation_status,
        technical_liquidity_status=technical_liquidity_status,
        overheat=overheat,
        rationale=rationale,
        recent_event_assessment=recent_event_assessment or f"{recent_event_status.value}: {rationale}",
        macro_assessment=macro_assessment or f"{macro_status.value}: {rationale}",
        industry_assessment=industry_assessment or f"{industry_status.value}: {rationale}",
        valuation_assessment=valuation_assessment or f"{valuation_status.value}: {rationale}",
        technical_liquidity_assessment=(
            technical_liquidity_assessment or f"{technical_liquidity_status.value}: {rationale}"
        ),
        base_case=base_case,
        upside_case=upside_case,
        downside_case=downside_case,
        acceptable_price_low=acceptable_price_low,
        acceptable_price_high=acceptable_price_high,
        wait_conditions=tuple(wait_conditions),
        key_risks=tuple(key_risks),
        hard_current_risks=tuple(hard_current_risks),
        liquidity_unacceptable=liquidity_unacceptable,
        portfolio_fit=portfolio_fit,
        portfolio_constraints=tuple(portfolio_constraints),
        concentration_impact=concentration_impact,
        liquidity_exit_assessment=liquidity_exit_assessment,
        alternative_cost=alternative_cost,
        missing_evidence=blockers,
        blocking_evidence=blockers,
        confidence_limiters=tuple(dict.fromkeys(confidence_limiters)),
        monitoring_items=tuple(dict.fromkeys(monitoring_items)),
        process_gaps=tuple(dict.fromkeys(workflow_gaps)),
        research_complete=research_complete,
        price_regime=price_regime,
        opportunity_cost_assessment=opportunity_cost_assessment,
        total_shareholder_return_3y=total_shareholder_return_3y,
    )


def validate_directional_context_evidence(
    *,
    evidence: Sequence[Mapping[str, Any]],
    recent_event_status: ContextStatus,
    macro_status: ContextStatus,
    industry_status: ContextStatus,
) -> tuple[str, ...]:
    missing: list[str] = []
    verified_statuses = {"official", "corroborated"}
    if recent_event_status in {ContextStatus.FAVORABLE, ContextStatus.ADVERSE}:
        eligible_event_evidence = [
            item
            for item in evidence
            if str(item["evidence_type"]) == "recent_event"
            and str(item["verification_status"]) in verified_statuses
            and bool(item.get("payload", {}).get("assessment", {}).get("entry_action_eligible"))
        ]
        if not eligible_event_evidence:
            missing.append(
                "directional recent-event status lacks an eligible verified hypothesis mapping"
            )
    if macro_status in {ContextStatus.FAVORABLE, ContextStatus.ADVERSE}:
        has_macro_evidence = any(
            str(item["evidence_type"]) in {"macro", "macro_context", "policy"}
            and str(item["verification_status"]) in verified_statuses
            for item in evidence
        )
        if not has_macro_evidence:
            missing.append("directional macro status lacks verified run evidence")
    if industry_status in {ContextStatus.FAVORABLE, ContextStatus.ADVERSE}:
        has_industry_evidence = any(
            str(item["evidence_type"]) in {"industry", "industry_context", "industry_structure"}
            and str(item["verification_status"]) in verified_statuses
            for item in evidence
        )
        if not has_industry_evidence:
            missing.append("directional industry status lacks verified run evidence")
    return tuple(missing)


def decide(
    *,
    run: ResearchRun,
    long_term: LongTermAssessment,
    current: CurrentAssessment | None = None,
    existing_position: bool = False,
    portfolio_role: str | None = None,
    entry_triggers: Sequence[str] = (),
    falsification_conditions: Sequence[str] = (),
    evidence_ids: Sequence[str] = (),
    sources: Sequence[str] = (),
    long_term_thesis: str | None = None,
    return_sources_3_5y: Sequence[str] = (),
    supporting_evidence: Sequence[str] = (),
    contrary_evidence: Sequence[str] = (),
    portfolio_action_override: PortfolioAction | None = None,
    next_review_date: str | None = None,
    previous_decision: DecisionCard | None = None,
    change_reasons: Sequence[str] = (),
    methodology_change: bool = False,
) -> DecisionCard:
    if not long_term.research_complete:
        raise ValueError("incomplete long-term research cannot produce an investment decision")
    if current is not None and not current.research_complete:
        raise ValueError("incomplete current research cannot produce an investment decision")
    long_term_blockers = tuple(long_term.blocking_evidence or long_term.missing_evidence)
    current_blockers = tuple(
        (current.blocking_evidence or current.missing_evidence) if current else ()
    )
    if long_term.verdict == LongTermVerdict.REJECT:
        action = EntryAction.AVOID
        portfolio_action = PortfolioAction.EXIT if existing_position else PortfolioAction.NOT_APPLICABLE
        rationale = f"长期准入不通过：{long_term.rationale}"
        wait_conditions: tuple[str, ...] = ()
        key_risks = tuple((*long_term.hard_vetoes, *long_term.structural_risks))
        price_low = None
        price_high = None
    elif long_term.verdict == LongTermVerdict.INSUFFICIENT:
        action = EntryAction.WAIT_EVIDENCE
        portfolio_action = PortfolioAction.HOLD if existing_position else PortfolioAction.NOT_APPLICABLE
        rationale = f"长期证据不足：{long_term.rationale}"
        wait_conditions = long_term_blockers
        key_risks = tuple(long_term.structural_risks)
        price_low = None
        price_high = None
    else:
        if current is None:
            raise ValueError("long-term pass requires current assessment before decision")
        context_adverse = any(
            status == ContextStatus.ADVERSE
            for status in (current.recent_event_status, current.macro_status, current.industry_status)
        )
        valuation_or_timing_adverse = (
            current.valuation_status == ContextStatus.ADVERSE
            or current.technical_liquidity_status == ContextStatus.ADVERSE
            or any(
                dimension.name == "implied_expectations"
                and dimension.status == DimensionStatus.FAIL
                for dimension in long_term.dimensions
            )
        )
        if current.hard_current_risks or current.liquidity_unacceptable:
            action = EntryAction.AVOID
            portfolio_action = PortfolioAction.EXIT if existing_position else PortfolioAction.NOT_APPLICABLE
        elif current.portfolio_fit == "incompatible":
            action = EntryAction.AVOID
            portfolio_action = PortfolioAction.REDUCE if existing_position else PortfolioAction.NOT_APPLICABLE
        elif current_blockers or context_adverse:
            action = EntryAction.WAIT_EVIDENCE
            portfolio_action = PortfolioAction.HOLD if existing_position else PortfolioAction.NOT_APPLICABLE
        elif current.overheat.is_overheated or valuation_or_timing_adverse or not current.odds_adequate:
            action = EntryAction.WAIT_PRICE
            portfolio_action = PortfolioAction.HOLD if existing_position else PortfolioAction.NOT_APPLICABLE
        else:
            action = EntryAction.SCALE_IN
            portfolio_action = (
                PortfolioAction.ADD
                if existing_position and current.portfolio_fit == "fits"
                else PortfolioAction.HOLD if existing_position else PortfolioAction.NOT_APPLICABLE
            )
        rationale = current.rationale
        wait_conditions = tuple(current.wait_conditions or current_blockers)
        key_risks = tuple((*current.hard_current_risks, *current.key_risks))
        price_low = current.acceptable_price_low
        price_high = current.acceptable_price_high

    if existing_position:
        if portfolio_action_override == PortfolioAction.NOT_APPLICABLE:
            raise ValueError("existing positions cannot use portfolio_action=not_applicable")
        forced_exit = (
            long_term.verdict == LongTermVerdict.REJECT
            or bool(current and (current.hard_current_risks or current.liquidity_unacceptable))
        )
        if forced_exit:
            portfolio_action = PortfolioAction.EXIT
        elif portfolio_action_override is not None:
            if portfolio_action_override == PortfolioAction.ADD and action != EntryAction.SCALE_IN:
                raise ValueError("portfolio_action=add requires entry_action=staged_buy")
            if portfolio_action_override == PortfolioAction.ADD and current and current.portfolio_fit != "fits":
                raise ValueError("portfolio_action=add requires portfolio_fit=fits")
            if (
                current
                and current.portfolio_fit == "incompatible"
                and portfolio_action_override not in {PortfolioAction.REDUCE, PortfolioAction.EXIT}
            ):
                raise ValueError("portfolio_fit=incompatible requires reduce or exit")
            portfolio_action = portfolio_action_override
    else:
        if portfolio_action_override not in {None, PortfolioAction.NOT_APPLICABLE}:
            raise ValueError("new candidates must use portfolio_action=not_applicable")
        portfolio_action = PortfolioAction.NOT_APPLICABLE

    if action == EntryAction.WAIT_PRICE and not wait_conditions:
        wait_conditions = tuple(current.overheat.triggers) if current and current.overheat.triggers else (
            "等待估值、价格或拥挤度回到可接受区间",
        )
    if action == EntryAction.WAIT_EVIDENCE and not wait_conditions:
        wait_conditions = long_term_blockers or (
            current_blockers if current else ("补齐关键证据后复核",)
        )

    active_triggers = tuple(entry_triggers)
    if action == EntryAction.SCALE_IN and not active_triggers:
        active_triggers = ("长期准入通过、赔率充足且未触发过热警示",)
    anti_chase_flags = list(current.overheat.triggers) if current else []
    if current is None:
        anti_chase_assessment = {
            "valuation_chasing": "not_assessed",
            "price_chasing": "not_assessed",
            "narrative_chasing": "not_assessed",
        }
    else:
        valuation_warning = (
            current.valuation_status == ContextStatus.ADVERSE
            or "valuation_extreme_without_revision" in current.overheat.triggers
        )
        valuation_missing = (
            current.valuation_status == ContextStatus.MISSING
            or current.overheat.valuation_history_percentile is None
        )
        price_triggers = {
            "relative_return_extreme",
            "price_above_ma60_by_2atr",
            "price_above_ma60_by_2volatility_units",
            "crowding_extreme",
            "event_gap_or_limit_cluster",
        }
        price_warning = (
            current.overheat.is_overheated
            or current.technical_liquidity_status == ContextStatus.ADVERSE
            or bool(price_triggers.intersection(current.overheat.triggers))
        )
        price_missing = (
            current.technical_liquidity_status == ContextStatus.MISSING
            or current.overheat.data_timestamp is None
        )
        narrative_warning = any(
            "recent-event" in item or "signal" in item
            for item in current.missing_evidence
        )
        narrative_missing = current.recent_event_status == ContextStatus.MISSING
        anti_chase_assessment = {
            "valuation_chasing": (
                "warning" if valuation_warning else "missing" if valuation_missing else "normal"
            ),
            "price_chasing": "warning" if price_warning else "missing" if price_missing else "normal",
            "narrative_chasing": (
                "warning" if narrative_warning else "missing" if narrative_missing else "normal"
            ),
        }
        if narrative_warning:
            anti_chase_flags.append("narrative_chasing_unverified_or_unmapped")
    if previous_decision is None:
        decision_change = "new"
        resolved_change_reasons: tuple[str, ...] = tuple(dict.fromkeys(change_reasons))
    else:
        unchanged = (
            previous_decision.long_term_verdict == long_term.verdict
            and previous_decision.entry_action == action
        )
        decision_change = (
            "methodology_rebase"
            if methodology_change
            else "unchanged" if unchanged else "changed"
        )
        resolved_change_reasons = tuple(dict.fromkeys(change_reasons))
        if decision_change != "unchanged" and not resolved_change_reasons:
            resolved_change_reasons = (rationale,)
    return DecisionCard(
        run_id=run.run_id,
        symbol=run.symbol,
        as_of=run.as_of,
        long_term_verdict=long_term.verdict,
        entry_action=action,
        portfolio_action=portfolio_action,
        rationale=rationale,
        acceptable_price_low=price_low,
        acceptable_price_high=price_high,
        wait_conditions=wait_conditions,
        entry_triggers=active_triggers,
        key_risks=key_risks,
        falsification_conditions=tuple(falsification_conditions),
        next_review_date=next_review_date,
        portfolio_role=portfolio_role,
        evidence_ids=tuple(evidence_ids),
        sources=tuple(sources),
        holding_horizon_months=run.horizon_months,
        candidate_source=str(run.metadata.get("candidate_source") or run.intent),
        thesis_ids=tuple(long_term.hypothesis_ids),
        long_term_thesis=long_term_thesis or long_term.rationale,
        return_sources_3_5y=tuple(return_sources_3_5y),
        supporting_evidence=tuple(supporting_evidence),
        contrary_evidence=tuple(contrary_evidence),
        recent_event_assessment=current.recent_event_assessment if current else None,
        macro_assessment=current.macro_assessment if current else None,
        industry_assessment=current.industry_assessment if current else None,
        valuation_assessment=current.valuation_assessment if current else None,
        technical_liquidity_assessment=current.technical_liquidity_assessment if current else None,
        anti_chase_flags=tuple(dict.fromkeys(anti_chase_flags)),
        anti_chase_assessment=anti_chase_assessment,
        reference_price=current.overheat.reference_price if current else None,
        base_case=current.base_case if current else None,
        upside_case=current.upside_case if current else None,
        downside_case=current.downside_case if current else None,
        confidence=long_term.confidence,
        missing_evidence=(
            long_term_blockers
            if long_term.verdict != LongTermVerdict.PASS
            else current_blockers
        ),
        blocking_evidence=(
            long_term_blockers
            if long_term.verdict != LongTermVerdict.PASS
            else current_blockers
        ),
        confidence_limiters=tuple(
            dict.fromkeys(
                (*long_term.confidence_limiters, *(current.confidence_limiters if current else ()))
            )
        ),
        monitoring_items=tuple(
            dict.fromkeys(
                (*long_term.monitoring_items, *(current.monitoring_items if current else ()))
            )
        ),
        price_regime=current.price_regime if current else "not_assessed",
        opportunity_cost_assessment=current.opportunity_cost_assessment if current else None,
        total_shareholder_return_3y=current.total_shareholder_return_3y if current else None,
        previous_decision_id=previous_decision.decision_id if previous_decision else None,
        previous_long_term_verdict=(
            previous_decision.long_term_verdict.value if previous_decision else None
        ),
        previous_entry_action=previous_decision.entry_action.value if previous_decision else None,
        decision_change=decision_change,
        change_reasons=resolved_change_reasons,
        methodology_change=methodology_change,
        portfolio_fit=current.portfolio_fit if current else "not_assessed",
        portfolio_constraints=tuple(current.portfolio_constraints) if current else (),
        concentration_impact=current.concentration_impact if current else None,
        liquidity_exit_assessment=current.liquidity_exit_assessment if current else None,
        alternative_cost=current.alternative_cost if current else None,
        metadata={
            "long_term_assessment_id": long_term.assessment_id,
            "current_assessment_id": current.assessment_id if current else None,
            "recent_event_status": current.recent_event_status.value if current else None,
            "macro_status": current.macro_status.value if current else None,
            "industry_status": current.industry_status.value if current else None,
            "valuation_status": current.valuation_status.value if current else None,
            "technical_liquidity_status": current.technical_liquidity_status.value if current else None,
        },
    )


def build_staged_plan(
    *,
    symbols: Sequence[str],
    as_of: str,
    current_profiles: Sequence[str] = ("market-context", "timing-liquidity"),
    plan_builder: Callable[..., Mapping[str, Any]] | None = None,
    capabilities: Any = None,
    lookback_days: int = 0,
    index_codes: Sequence[str] = (),
) -> dict[str, Any]:
    long_term_profiles = ("long-term-quality", "risk-review")
    deduplicated_current = tuple(
        profile
        for profile in dict.fromkeys(current_profiles)
        if profile not in long_term_profiles and profile != "timing-liquidity"
    )
    deduplicated_current = (*deduplicated_current, "timing-liquidity")

    def build(profiles: Sequence[str]) -> Mapping[str, Any]:
        if plan_builder is None:
            return {
                "profiles": list(profiles),
                "symbols": list(symbols),
                "as_of": as_of,
            }
        return plan_builder(
            profiles,
            symbols=symbols,
            as_of=as_of,
            lookback_days=lookback_days,
            index_codes=index_codes,
            capabilities=capabilities,
        )

    return {
        "as_of": as_of,
        "symbols": list(symbols),
        "stages": [
            {
                "stage": "long_term",
                "order": 1,
                "profiles": list(long_term_profiles),
                "gate_output": [verdict.value for verdict in LongTermVerdict],
                "plan": build(long_term_profiles),
            },
            {
                "stage": "current_buyability",
                "order": 2,
                "profiles": list(deduplicated_current),
                "requires": "long_term.verdict == passed",
                "plan": build(deduplicated_current),
            },
        ],
        "invariants": [
            "rejected cannot be upgraded by event, macro, industry or technical signals",
            "needs_evidence resolves to wait_evidence without current-stage promotion",
            "technical and liquidity evidence can delay entry but cannot create long-term admission",
        ],
    }


class ResearchWorkflow:
    def __init__(self, store: ResearchStore):
        self.store = store

    def start_run(
        self,
        *,
        symbol: str,
        as_of: str,
        intent: str,
        horizon_months: int = 36,
        metadata: Mapping[str, Any] | None = None,
    ) -> ResearchRun:
        return self.store.create_run(
            ResearchRun(
                symbol=symbol,
                as_of=as_of,
                intent=intent,
                horizon_months=horizon_months,
                metadata=metadata or {},
            )
        )

    def evaluate_long_term(
        self,
        run_id: str,
        *,
        years_covered: float,
        dimensions: Sequence[DimensionResult],
        rationale: str,
        structural_risks: Sequence[str] = (),
        hard_vetoes: Sequence[str] = (),
        missing_evidence: Sequence[str] = (),
        blocking_evidence: Sequence[str] = (),
        confidence_limiters: Sequence[str] = (),
        monitoring_items: Sequence[str] = (),
        confidence: float = 0.5,
        existing_position: bool = False,
        portfolio_role: str | None = None,
        next_review_date: str | None = None,
        portfolio_action_override: PortfolioAction | None = None,
        change_reasons: Sequence[str] = (),
        methodology_change: bool = False,
    ) -> tuple[LongTermAssessment, DecisionCard | None]:
        run = self.store.get_run(run_id)
        if run.stage not in {WorkflowStage.CREATED, WorkflowStage.LONG_TERM_REVIEWED}:
            raise ValueError("long-term assessment requires a new or incomplete long-term run")
        hypotheses = self.store.list_hypotheses(run.symbol)
        stored_evidence = self.store.list_evidence(run_id=run_id)
        stored_evidence_ids = {str(item["evidence_id"]) for item in stored_evidence}
        referenced_evidence_ids = {
            evidence_id
            for dimension in dimensions
            for evidence_id in dimension.evidence_ids
        }
        unknown_evidence_ids = sorted(referenced_evidence_ids.difference(stored_evidence_ids))
        validated_process_gaps: list[str] = []
        validated_process_gaps.extend(
            f"unknown evidence_id: {evidence_id}" for evidence_id in unknown_evidence_ids
        )
        stored_evidence_by_id = {
            str(item["evidence_id"]): item
            for item in stored_evidence
        }
        validated_process_gaps.extend(
            f"long-term evidence is not verified: {evidence_id}"
            for evidence_id in sorted(referenced_evidence_ids.intersection(stored_evidence_ids))
            if str(stored_evidence_by_id[evidence_id]["verification_status"])
            not in {"official", "corroborated"}
        )
        hypothesis_links_before_gate = self.store.list_hypothesis_evidence(run_id=run_id)
        linked_hypothesis_ids = {
            str(item["hypothesis_id"])
            for item in hypothesis_links_before_gate
        }
        validated_process_gaps.extend(
            f"hypothesis lacks linked evidence: {hypothesis.thesis_key}"
            for hypothesis in hypotheses
            if hypothesis.hypothesis_id not in linked_hypothesis_ids
        )
        assessment = assess_long_term(
            run_id=run_id,
            symbol=run.symbol,
            years_covered=years_covered,
            dimensions=dimensions,
            hypotheses=hypotheses,
            rationale=rationale,
            structural_risks=structural_risks,
            hard_vetoes=hard_vetoes,
            missing_evidence=missing_evidence,
            blocking_evidence=blocking_evidence,
            confidence_limiters=confidence_limiters,
            monitoring_items=monitoring_items,
            process_gaps=validated_process_gaps,
            confidence=confidence,
        )
        self.store.save_long_term_assessment(assessment)
        run = self.store.update_run_stage(run_id, WorkflowStage.LONG_TERM_REVIEWED)
        self.store.update_research_status(run_id, ResearchStatus.IN_PROGRESS)
        if not assessment.research_complete:
            return assessment, None
        hypothesis_links = hypothesis_links_before_gate
        dimension_evidence_ids = {
            evidence_id
            for dimension in dimensions
            for evidence_id in dimension.evidence_ids
        }
        supporting_evidence = tuple(dict.fromkeys((
            str(item["evidence_id"])
            for item in hypothesis_links
            if str(item["direction"]).lower() not in {"against", "contrary", "negative", "weakens", "refutes"}
        )))
        contrary_evidence = tuple(
            str(item["evidence_id"])
            for item in hypothesis_links
            if str(item["direction"]).lower() in {"against", "contrary", "negative", "weakens", "refutes"}
        )
        supporting_evidence = tuple(
            dict.fromkeys((*supporting_evidence, *sorted(dimension_evidence_ids)))
        )
        resolved_next_review = next_review_date or min(
            (hypothesis.next_review_date for hypothesis in hypotheses if hypothesis.next_review_date),
            default=None,
        )
        if assessment.verdict == LongTermVerdict.PASS:
            return assessment, None
        previous_decision = self.store.latest_decision_for_symbol(
            run.symbol,
            before_as_of=run.as_of,
            exclude_run_id=run.run_id,
        )
        decision = decide(
            run=run,
            long_term=assessment,
            existing_position=existing_position,
            portfolio_role=portfolio_role,
            falsification_conditions=tuple(
                hypothesis.falsification_condition for hypothesis in hypotheses
            ),
            evidence_ids=tuple(sorted(stored_evidence_ids)),
            sources=tuple(sorted({str(item["source_url"]) for item in stored_evidence})),
            long_term_thesis=str(run.metadata.get("long_term_thesis") or rationale),
            return_sources_3_5y=tuple(hypothesis.return_source for hypothesis in hypotheses),
            supporting_evidence=supporting_evidence,
            contrary_evidence=contrary_evidence,
            portfolio_action_override=portfolio_action_override,
            next_review_date=resolved_next_review,
            previous_decision=previous_decision,
            change_reasons=change_reasons,
            methodology_change=methodology_change,
        )
        self.store.save_decision(decision)
        self.store.update_run_stage(run_id, WorkflowStage.DECIDED)
        return assessment, decision

    def evaluate_current(
        self,
        run_id: str,
        *,
        overheat: OverheatAssessment,
        recent_event_status: ContextStatus,
        macro_status: ContextStatus,
        industry_status: ContextStatus,
        valuation_status: ContextStatus,
        technical_liquidity_status: ContextStatus,
        evidence_complete: bool,
        odds_adequate: bool,
        rationale: str,
        recent_event_assessment: str = "",
        macro_assessment: str = "",
        industry_assessment: str = "",
        valuation_assessment: str = "",
        technical_liquidity_assessment: str = "",
        base_case: str = "",
        upside_case: str = "",
        downside_case: str = "",
        acceptable_price_low: float | None = None,
        acceptable_price_high: float | None = None,
        wait_conditions: Sequence[str] = (),
        entry_triggers: Sequence[str] = (),
        key_risks: Sequence[str] = (),
        hard_current_risks: Sequence[str] = (),
        liquidity_unacceptable: bool = False,
        portfolio_fit: str = "not_assessed",
        portfolio_constraints: Sequence[str] = (),
        concentration_impact: str | None = None,
        liquidity_exit_assessment: str | None = None,
        alternative_cost: str | None = None,
        missing_evidence: Sequence[str] = (),
        blocking_evidence: Sequence[str] = (),
        confidence_limiters: Sequence[str] = (),
        monitoring_items: Sequence[str] = (),
        price_regime: str = "not_assessed",
        opportunity_cost_assessment: str | None = None,
        total_shareholder_return_3y: float | None = None,
        existing_position: bool = False,
        portfolio_role: str | None = None,
        portfolio_action_override: PortfolioAction | None = None,
        next_review_date: str | None = None,
        change_reasons: Sequence[str] = (),
        methodology_change: bool = False,
    ) -> tuple[CurrentAssessment, DecisionCard | None]:
        run = self.store.get_run(run_id)
        if run.stage != WorkflowStage.LONG_TERM_REVIEWED:
            raise ValueError("current assessment requires completed long-term pass")
        payload = self.store.latest_assessment_payload(run_id, AssessmentStage.LONG_TERM)
        if payload is None:
            raise ValueError("long-term assessment is missing")
        verdict = LongTermVerdict(str(payload["verdict"]))
        if verdict != LongTermVerdict.PASS:
            raise ValueError("current assessment cannot run unless long-term verdict is pass")
        dimensions = tuple(
            DimensionResult(
                name=str(item["name"]),
                status=DimensionStatus(str(item["status"])),
                rationale=str(item["rationale"]),
                evidence_ids=tuple(item.get("evidence_ids", [])),
                metrics=item.get("metrics", {}),
            )
            for item in payload.get("dimensions", [])
        )
        long_term = LongTermAssessment(
            assessment_id=str(payload["assessment_id"]),
            run_id=run_id,
            symbol=run.symbol,
            verdict=verdict,
            years_covered=float(payload["years_covered"]),
            dimensions=dimensions,
            hypothesis_ids=tuple(payload.get("hypothesis_ids", [])),
            rationale=str(payload["rationale"]),
            structural_risks=tuple(payload.get("structural_risks", [])),
            hard_vetoes=tuple(payload.get("hard_vetoes", [])),
            missing_evidence=tuple(payload.get("missing_evidence", [])),
            blocking_evidence=tuple(
                payload.get("blocking_evidence", payload.get("missing_evidence", []))
            ),
            confidence_limiters=tuple(payload.get("confidence_limiters", [])),
            monitoring_items=tuple(payload.get("monitoring_items", [])),
            process_gaps=tuple(payload.get("process_gaps", [])),
            research_complete=bool(payload.get("research_complete", True)),
            confidence=float(payload.get("confidence", 0.5)),
            created_at=str(payload["created_at"]),
        )
        stored_current_evidence = self.store.list_evidence(run_id=run_id)
        context_process_gaps = list(
            validate_directional_context_evidence(
                evidence=stored_current_evidence,
                recent_event_status=recent_event_status,
                macro_status=macro_status,
                industry_status=industry_status,
            )
        )
        current = assess_current(
            run_id=run_id,
            symbol=run.symbol,
            long_term=long_term,
            overheat=overheat,
            recent_event_status=recent_event_status,
            macro_status=macro_status,
            industry_status=industry_status,
            valuation_status=valuation_status,
            technical_liquidity_status=technical_liquidity_status,
            evidence_complete=evidence_complete,
            odds_adequate=odds_adequate,
            rationale=rationale,
            recent_event_assessment=recent_event_assessment,
            macro_assessment=macro_assessment,
            industry_assessment=industry_assessment,
            valuation_assessment=valuation_assessment,
            technical_liquidity_assessment=technical_liquidity_assessment,
            base_case=base_case,
            upside_case=upside_case,
            downside_case=downside_case,
            acceptable_price_low=acceptable_price_low,
            acceptable_price_high=acceptable_price_high,
            wait_conditions=wait_conditions,
            key_risks=key_risks,
            hard_current_risks=hard_current_risks,
            liquidity_unacceptable=liquidity_unacceptable,
            portfolio_fit=portfolio_fit,
            portfolio_constraints=portfolio_constraints,
            concentration_impact=concentration_impact,
            liquidity_exit_assessment=liquidity_exit_assessment,
            alternative_cost=alternative_cost,
            missing_evidence=missing_evidence,
            blocking_evidence=blocking_evidence,
            confidence_limiters=confidence_limiters,
            monitoring_items=monitoring_items,
            process_gaps=context_process_gaps,
            price_regime=price_regime,
            opportunity_cost_assessment=opportunity_cost_assessment,
            total_shareholder_return_3y=total_shareholder_return_3y,
        )
        self.store.save_current_assessment(current)
        run = self.store.update_run_stage(run_id, WorkflowStage.CURRENT_REVIEWED)
        self.store.update_research_status(run_id, ResearchStatus.IN_PROGRESS)
        if not current.research_complete:
            return current, None
        hypotheses = self.store.list_hypotheses(run.symbol)
        hypothesis_links = self.store.list_hypothesis_evidence(run_id=run_id)
        negative_directions = {"against", "contrary", "negative", "weakens", "refutes"}
        resolved_next_review = next_review_date or min(
            (hypothesis.next_review_date for hypothesis in hypotheses if hypothesis.next_review_date),
            default=None,
        )
        previous_decision = self.store.latest_decision_for_symbol(
            run.symbol,
            before_as_of=run.as_of,
            exclude_run_id=run.run_id,
        )
        decision = decide(
            run=run,
            long_term=long_term,
            current=current,
            existing_position=existing_position,
            portfolio_role=portfolio_role,
            entry_triggers=entry_triggers,
            falsification_conditions=tuple(
                hypothesis.falsification_condition
                for hypothesis in hypotheses
            ),
            evidence_ids=tuple(
                str(item["evidence_id"])
                for item in self.store.list_evidence(run_id=run_id)
            ),
            sources=tuple(
                sorted(
                    {
                        str(item["source_url"])
                        for item in self.store.list_evidence(run_id=run_id)
                    }
                )
            ),
            long_term_thesis=str(run.metadata.get("long_term_thesis") or long_term.rationale),
            return_sources_3_5y=tuple(hypothesis.return_source for hypothesis in hypotheses),
            supporting_evidence=tuple(
                str(item["evidence_id"])
                for item in hypothesis_links
                if str(item["direction"]).lower() not in negative_directions
            ),
            contrary_evidence=tuple(
                str(item["evidence_id"])
                for item in hypothesis_links
                if str(item["direction"]).lower() in negative_directions
            ),
            portfolio_action_override=portfolio_action_override,
            next_review_date=resolved_next_review,
            previous_decision=previous_decision,
            change_reasons=change_reasons,
            methodology_change=methodology_change,
        )
        self.store.save_decision(decision)
        self.store.update_run_stage(run_id, WorkflowStage.DECIDED)
        return current, decision

    def add_claim(self, claim: ResearchClaim) -> str:
        run = self.store.get_run(claim.run_id)
        if claim.hypothesis_id:
            symbol_hypothesis_ids = {
                hypothesis.hypothesis_id
                for hypothesis in self.store.list_hypotheses(run.symbol, active_only=False)
            }
            if claim.hypothesis_id not in symbol_hypothesis_ids:
                raise ValueError("claim hypothesis does not belong to the research-run company")
        available_evidence = {
            str(item["evidence_id"])
            for item in self.store.list_evidence(run_id=claim.run_id)
        }
        referenced_evidence = set(claim.supporting_evidence).union(claim.contrary_evidence)
        unknown = referenced_evidence.difference(available_evidence)
        if unknown:
            raise ValueError(f"claim references unknown evidence: {sorted(unknown)}")
        return self.store.add_claim(claim)

    def add_evidence(self, evidence: EvidenceItem) -> str:
        run = self.store.get_run(evidence.run_id)
        if evidence.symbol != run.symbol:
            raise ValueError("evidence symbol does not match research run")
        return self.store.add_evidence(evidence)

    def record_outcome(self, outcome: OutcomeSnapshot) -> None:
        self.store.record_outcome(outcome)
