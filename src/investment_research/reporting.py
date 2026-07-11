from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .domain import ACTION_LABELS, DecisionCard, EntryAction, ResearchRun, to_jsonable, utc_now


ACTION_ORDER = (
    EntryAction.SCALE_IN,
    EntryAction.WAIT_PRICE,
    EntryAction.WAIT_EVIDENCE,
    EntryAction.AVOID,
)


def _decision_payload(decision: DecisionCard | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(decision, DecisionCard):
        payload = dict(to_jsonable(decision))
        payload["entry_action_label"] = decision.action_label
        return payload
    payload = dict(decision)
    action = EntryAction(str(payload["entry_action"]))
    payload["entry_action"] = action.value
    payload.setdefault("entry_action_label", ACTION_LABELS[action])
    return payload


def bucket_decisions(
    decisions: Sequence[DecisionCard | Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    buckets = {action.value: [] for action in ACTION_ORDER}
    for decision in decisions:
        payload = _decision_payload(decision)
        buckets[EntryAction(str(payload["entry_action"])).value].append(payload)
    return buckets


def build_decision_report(
    decisions: Sequence[DecisionCard | Mapping[str, Any]],
    *,
    generated_at: str | None = None,
    research_queue: Sequence[ResearchRun | Mapping[str, Any]] = (),
) -> dict[str, Any]:
    buckets = bucket_decisions(decisions)
    flat_decisions = [item for action in ACTION_ORDER for item in buckets[action.value]]
    action_priority = {action.value: index for index, action in enumerate(ACTION_ORDER)}
    ranked = sorted(
        flat_decisions,
        key=lambda item: (
            action_priority.get(str(item.get("entry_action")), len(ACTION_ORDER)),
            -(float(item.get("confidence")) if item.get("confidence") is not None else -1.0),
        ),
    )
    closest = ranked[0] if ranked else None
    if buckets[EntryAction.SCALE_IN.value]:
        best_action_today = "可分批买入"
    elif buckets[EntryAction.WAIT_PRICE.value] or buckets[EntryAction.WAIT_EVIDENCE.value]:
        best_action_today = "等待／现金优先"
    elif buckets[EntryAction.AVOID.value]:
        best_action_today = "回避／现金优先"
    else:
        best_action_today = "研究未完成"
    queue_payloads = [dict(to_jsonable(item)) for item in research_queue]
    changes = [
        {
            "symbol": item.get("symbol"),
            "decision_change": item.get("decision_change", "new"),
            "previous_long_term_verdict": item.get("previous_long_term_verdict"),
            "previous_entry_action": item.get("previous_entry_action"),
            "long_term_verdict": item.get("long_term_verdict"),
            "entry_action": item.get("entry_action"),
            "change_reasons": item.get("change_reasons", []),
            "methodology_change": bool(item.get("methodology_change", False)),
        }
        for item in flat_decisions
        if item.get("decision_change", "new") != "unchanged"
    ]
    return {
        "schema_version": "2.0",
        "generated_at": generated_at or utc_now(),
        "summary": {
            "best_action_today": best_action_today,
            "cash_preferred": not bool(buckets[EntryAction.SCALE_IN.value]),
            "closest_to_buy": (
                {
                    "symbol": closest.get("symbol"),
                    "entry_action": closest.get("entry_action"),
                    "long_term_verdict": closest.get("long_term_verdict"),
                    "blocking_evidence": closest.get("blocking_evidence", []),
                    "next_review_date": closest.get("next_review_date"),
                }
                if closest
                else None
            ),
            "assessed_count": len(flat_decisions),
            "research_queue_count": len(queue_payloads),
        },
        "changes": changes,
        "research_queue": queue_payloads,
        "bucket_order": [action.value for action in ACTION_ORDER],
        "buckets": buckets,
        "counts": {key: len(items) for key, items in buckets.items()},
    }


def _format_list(values: Sequence[Any] | None, empty: str = "无") -> str:
    clean = [str(value) for value in values or [] if str(value).strip()]
    return "；".join(clean) if clean else empty


def render_decision_markdown(
    decisions_or_report: Sequence[DecisionCard | Mapping[str, Any]] | Mapping[str, Any],
) -> str:
    if isinstance(decisions_or_report, Mapping) and "buckets" in decisions_or_report:
        report = dict(decisions_or_report)
    else:
        report = build_decision_report(list(decisions_or_report))
    buckets = report["buckets"]
    summary = report.get("summary", {})
    closest = summary.get("closest_to_buy")
    lines = [
        "# 机构投研决策清单",
        "",
        "## PM 结论",
        "",
        f"- 今天最优行动：{summary.get('best_action_today', '未评估')}",
        f"- 已完成决策：{summary.get('assessed_count', 0)}",
        f"- 研究队列：{summary.get('research_queue_count', 0)}",
        f"- 最接近买入：{closest.get('symbol') if closest else '无'}",
        f"- 当前唯一阻断项：{_format_list(closest.get('blocking_evidence') if closest else [])}",
        "",
        "## 与上次比较",
        "",
    ]
    changes = report.get("changes", [])
    if not changes:
        lines.extend(("- 无结论变化", ""))
    else:
        for change in changes:
            lines.append(
                "- "
                f"{change.get('symbol', 'UNKNOWN')}：{change.get('decision_change', 'changed')}；"
                f"{change.get('previous_long_term_verdict') or '无'} / {change.get('previous_entry_action') or '无'}"
                " -> "
                f"{change.get('long_term_verdict')} / {change.get('entry_action')}；"
                f"原因={_format_list(change.get('change_reasons'))}"
            )
        lines.append("")
    lines.extend(("## 尚未形成决策的研究队列", ""))
    research_queue = report.get("research_queue", [])
    if not research_queue:
        lines.extend(("- 无", ""))
    else:
        for run in research_queue:
            lines.append(
                f"- {run.get('symbol', 'UNKNOWN')}：{run.get('research_status', 'in_progress')}；"
                f"阶段={run.get('stage', 'unknown')}；as_of={run.get('as_of', 'unknown')}"
            )
        lines.append("")
    for action in ACTION_ORDER:
        lines.extend((f"## {ACTION_LABELS[action]}", ""))
        items = buckets.get(action.value, [])
        if not items:
            lines.extend(("- 无", ""))
            continue
        for item in items:
            price_low = item.get("acceptable_price_low")
            price_high = item.get("acceptable_price_high")
            if price_low is None and price_high is None:
                price_range = "未设定"
            else:
                price_range = f"{price_low if price_low is not None else '-∞'}–{price_high if price_high is not None else '+∞'}"
            lines.extend(
                (
                    f"### {item.get('symbol', 'UNKNOWN')}",
                    "",
                    f"- 决策时点：{item.get('as_of', 'unknown')}",
                    f"- 持有周期（月）：{item.get('holding_horizon_months') or '未设定'}",
                    f"- 候选来源：{item.get('candidate_source') or '未设定'}",
                    f"- 长期状态：{item.get('long_term_verdict', 'unknown')}",
                    f"- 长期假设：{item.get('long_term_thesis') or '未设定'}",
                    f"- 3–5 年收益来源：{_format_list(item.get('return_sources_3_5y'))}",
                    f"- 支持证据：{_format_list(item.get('supporting_evidence'))}",
                    f"- 反方证据：{_format_list(item.get('contrary_evidence'))}",
                    f"- 近期事件：{item.get('recent_event_assessment') or '不适用'}",
                    f"- 宏观环境：{item.get('macro_assessment') or '不适用'}",
                    f"- 行业景气：{item.get('industry_assessment') or '不适用'}",
                    f"- 估值赔率：{item.get('valuation_assessment') or '不适用'}",
                    f"- 技术/流动性：{item.get('technical_liquidity_assessment') or '不适用'}",
                    "- 防追高状态："
                    f"估值={item.get('anti_chase_assessment', {}).get('valuation_chasing', 'not_assessed')}；"
                    f"价格={item.get('anti_chase_assessment', {}).get('price_chasing', 'not_assessed')}；"
                    f"叙事={item.get('anti_chase_assessment', {}).get('narrative_chasing', 'not_assessed')}",
                    f"- 防追高警示：{_format_list(item.get('anti_chase_flags'))}",
                    f"- 参考价格：{item.get('reference_price') if item.get('reference_price') is not None else '未设定'}",
                    f"- 入场动作：{item.get('entry_action_label', ACTION_LABELS[action])}",
                    f"- 组合动作：{item.get('portfolio_action', 'not_applicable')}",
                    f"- 决策理由：{item.get('rationale', '')}",
                    f"- 可接受价格：{price_range}",
                    f"- 基准情景：{item.get('base_case') or '未设定'}",
                    f"- 上行情景：{item.get('upside_case') or '未设定'}",
                    f"- 下行情景：{item.get('downside_case') or '未设定'}",
                    f"- 入场触发：{_format_list(item.get('entry_triggers'))}",
                    f"- 等待条件：{_format_list(item.get('wait_conditions'))}",
                    f"- 关键风险：{_format_list(item.get('key_risks'))}",
                    f"- 证伪条件：{_format_list(item.get('falsification_conditions'))}",
                    f"- 置信度：{item.get('confidence') if item.get('confidence') is not None else '未设定'}",
                    f"- 阻断证据：{_format_list(item.get('blocking_evidence'))}",
                    f"- 置信度限制项：{_format_list(item.get('confidence_limiters'))}",
                    f"- 持续监测项：{_format_list(item.get('monitoring_items'))}",
                    f"- 价格状态：{item.get('price_regime') or 'not_assessed'}",
                    f"- 三年股东总回报：{item.get('total_shareholder_return_3y') if item.get('total_shareholder_return_3y') is not None else '不可得'}",
                    f"- 机会成本：{item.get('opportunity_cost_assessment') or item.get('alternative_cost') or '未评估'}",
                    f"- 相对上次：{item.get('decision_change', 'new')}；原因={_format_list(item.get('change_reasons'))}",
                    f"- 组合适配：{item.get('portfolio_fit') or 'not_assessed'}",
                    f"- 组合约束：{_format_list(item.get('portfolio_constraints'))}",
                    f"- 集中度影响：{item.get('concentration_impact') or '未评估'}",
                    f"- 退出流动性：{item.get('liquidity_exit_assessment') or '未评估'}",
                    f"- 替代成本：{item.get('alternative_cost') or '未评估'}",
                    f"- 下一验证日：{item.get('next_review_date') or '未设定'}",
                    f"- 证据 ID：{_format_list(item.get('evidence_ids'))}",
                    f"- 来源：{_format_list(item.get('sources'))}",
                    "",
                )
            )
    return "\n".join(lines).rstrip() + "\n"


def write_decision_report(
    decisions: Sequence[DecisionCard | Mapping[str, Any]],
    output: Path,
    *,
    research_queue: Sequence[ResearchRun | Mapping[str, Any]] = (),
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_decision_report(decisions, research_queue=research_queue)
    if output.suffix.lower() == ".md":
        output.write_text(render_decision_markdown(report), encoding="utf-8")
    else:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
