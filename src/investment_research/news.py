from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .domain import (
    NewsSignal,
    SignalHypothesisMapping,
    VerificationStatus,
)
from .store import ResearchStore


DEFAULT_GELONGHUI_URL = "https://www.gelonghui.com/live"
SYMBOL_PATTERN = re.compile(r"\b\d{6}\.(?:SZ|SH|BJ)\b", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s)]+")
DATETIME_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\b")
GELONGHUI_LINE_PATTERN = re.compile(
    r"^\s*[-*]?\s*(\d{1,2}:\d{2})\s+格隆汇(?:(\d{1,2})月(\d{1,2})日)?\s*[｜|]\s*(.+?)\s*$"
)


def _parse_datetime(value: object, reference_time: datetime) -> datetime:
    text = str(value or "").strip()
    if not text:
        return reference_time
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M", "%Y%m%d %H:%M", "%H:%M"):
            try:
                parsed = datetime.strptime(text, pattern)
                if pattern == "%H:%M":
                    parsed = parsed.replace(
                        year=reference_time.year,
                        month=reference_time.month,
                        day=reference_time.day,
                    )
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unsupported signal timestamp: {text}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=reference_time.tzinfo or timezone.utc)
    return parsed


def _clean_live_text(value: str) -> str:
    text = re.sub(r"\*+\s*分享.*$", "", value).strip()
    text = re.sub(r"\s+分享\s+微信\s+微博.*$", "", text).strip()
    return re.sub(r"\s+", " ", text).strip(" -*|｜")


def _records_from_text(
    text: str,
    reference_time: datetime,
    *,
    default_url: str = DEFAULT_GELONGHUI_URL,
    default_important: bool = False,
) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        return [dict(item) for item in loaded if isinstance(item, Mapping)]
    if isinstance(loaded, Mapping):
        content = loaded.get("content")
        if isinstance(content, Mapping):
            content_text = content.get("markdown") or content.get("plain_text") or content.get("text") or ""
            metadata = loaded.get("metadata") if isinstance(loaded.get("metadata"), Mapping) else {}
            return _records_from_text(
                str(content_text),
                reference_time,
                default_url=str(metadata.get("url") or default_url),
                default_important=default_important,
            )
        candidates = loaded.get("signals") or loaded.get("data") or [loaded]
        return [dict(item) for item in candidates if isinstance(item, Mapping)]

    live_records: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        clean_line = re.sub(r"^[>#]+\s*", "", line).strip()
        match = GELONGHUI_LINE_PATTERN.match(clean_line)
        if not match:
            continue
        time_text, month_text, day_text, body = match.groups()
        month = int(month_text) if month_text else reference_time.month
        day = int(day_text) if day_text else reference_time.day
        hour, minute = (int(part) for part in time_text.split(":"))
        published_at = datetime(
            reference_time.year,
            month,
            day,
            hour,
            minute,
            tzinfo=reference_time.tzinfo or ZoneInfo("Asia/Hong_Kong"),
        )
        if month_text and published_at > reference_time + timedelta(days=1):
            published_at = published_at.replace(year=reference_time.year - 1)
        cleaned_body = _clean_live_text(body)
        live_records.append(
            {
                "published_at": published_at.isoformat(timespec="minutes"),
                "title": cleaned_body[:240],
                "summary": cleaned_body,
                "source_url": default_url,
                "important": default_important,
                "symbols": SYMBOL_PATTERN.findall(cleaned_body),
            }
        )
    if live_records:
        return live_records

    records: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", stripped):
        clean = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if not clean:
            continue
        timestamp_match = DATETIME_PATTERN.search(clean)
        url_match = URL_PATTERN.search(clean)
        timestamp = timestamp_match.group(1) if timestamp_match else reference_time.isoformat(timespec="minutes")
        url = url_match.group(0) if url_match else default_url
        title = clean
        if timestamp_match:
            title = title.replace(timestamp_match.group(0), "").strip(" |-：:")
        if url_match:
            title = title.replace(url_match.group(0), "").strip(" |-：:")
        records.append(
            {
                "published_at": timestamp,
                "title": title[:240],
                "summary": title,
                "source_url": url,
                "important": default_important or "重要" in clean or "is-weight" in clean.lower(),
                "symbols": SYMBOL_PATTERN.findall(clean),
            }
        )
    return records


def load_signal_records(path: Path) -> list[dict[str, Any]] | dict[str, Any]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            if isinstance(payload.get("content"), Mapping):
                return dict(payload)
            payload = payload.get("signals") or payload.get("data") or [payload]
        if not isinstance(payload, list):
            raise ValueError("JSON signal input must contain an object or list")
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return [
            dict(item)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and isinstance((item := json.loads(line)), Mapping)
        ]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    return _records_from_text(
        path.read_text(encoding="utf-8"),
        datetime.now(ZoneInfo("Asia/Hong_Kong")),
    )


def extract_gelonghui_signals(
    payload: str | Sequence[Mapping[str, Any]] | Mapping[str, Any],
    *,
    important_only: bool = True,
    since_hours: int = 72,
    reference_time: datetime | None = None,
    content_is_important: bool = True,
) -> list[NewsSignal]:
    reference = reference_time or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
    if isinstance(payload, str):
        records = _records_from_text(
            payload,
            reference,
            default_important=content_is_important,
        )
    elif isinstance(payload, Mapping):
        content = payload.get("content")
        if isinstance(content, Mapping):
            content_text = content.get("markdown") or content.get("plain_text") or content.get("text") or ""
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
            source_url = str(metadata.get("url") or DEFAULT_GELONGHUI_URL)
            records = _records_from_text(
                str(content_text),
                reference,
                default_url=source_url,
                default_important=content_is_important,
            )
        else:
            candidates = payload.get("signals") or payload.get("data") or [payload]
            records = [dict(item) for item in candidates if isinstance(item, Mapping)]
    else:
        records = [dict(item) for item in payload]

    cutoff = reference - timedelta(hours=max(since_hours, 0))
    signals: list[NewsSignal] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        important_value = record.get("important", record.get("is_important", record.get("is-weight", False)))
        important = str(important_value).strip().lower() in {"1", "true", "yes", "重要"} or important_value is True
        if important_only and not important:
            continue
        published_at = _parse_datetime(
            record.get("published_at") or record.get("time") or record.get("发布时间"),
            reference,
        )
        if published_at > reference + timedelta(minutes=5):
            continue
        if since_hours and published_at < cutoff:
            continue
        title = str(record.get("title") or record.get("event") or record.get("事件") or "").strip()
        summary = str(record.get("summary") or record.get("description") or record.get("摘要") or title).strip()
        source_url = str(record.get("source_url") or record.get("url") or record.get("原始链接") or DEFAULT_GELONGHUI_URL).strip()
        symbols_value = record.get("symbols") or record.get("涉及公司") or []
        industries_value = record.get("industries") or record.get("涉及行业") or []
        if isinstance(symbols_value, str):
            symbols = tuple(dict.fromkeys(SYMBOL_PATTERN.findall(symbols_value) or re.split(r"[,，\s]+", symbols_value.strip())))
        else:
            symbols = tuple(str(item) for item in symbols_value if item)
        if not symbols:
            symbols = tuple(dict.fromkeys(SYMBOL_PATTERN.findall(f"{title} {summary}")))
        if isinstance(industries_value, str):
            industries = tuple(item for item in re.split(r"[,，;；]+", industries_value) if item.strip())
        else:
            industries = tuple(str(item) for item in industries_value if item)
        verification = VerificationStatus(
            str(record.get("verification_status") or VerificationStatus.UNVERIFIED.value)
        )
        independent_source_count = int(record.get("independent_source_count") or record.get("source_count") or 1)
        dedupe_key = (published_at.isoformat(timespec="minutes"), title, source_url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        signals.append(
            NewsSignal(
                provider="gelonghui",
                external_id=str(record.get("external_id") or record.get("id") or "") or None,
                published_at=published_at.isoformat(timespec="seconds"),
                title=title,
                summary=summary,
                source_url=source_url,
                important=important,
                symbols=symbols,
                industries=industries,
                verification_status=verification,
                independent_source_count=independent_source_count,
                raw_payload=record,
            )
        )
    return signals


def assess_signal_mapping(
    signal: NewsSignal,
    mapping: SignalHypothesisMapping,
) -> dict[str, Any]:
    reasons: list[str] = []
    verified = (
        mapping.verification_status == VerificationStatus.OFFICIAL
        or (
            mapping.verification_status == VerificationStatus.CORROBORATED
            and signal.independent_source_count >= 2
        )
    )
    if not verified:
        reasons.append("signal is not officially confirmed or independently corroborated")
    if mapping.magnitude_low is None and mapping.magnitude_high is None:
        reasons.append("financial magnitude is missing")
    if not mapping.duration_days or mapping.duration_days < 90:
        reasons.append("duration is shorter than one reporting period or unknown")
    if mapping.relevance < 0.5:
        reasons.append("hypothesis relevance is weak")
    if mapping.priced_in_status == "fully_priced":
        reasons.append("signal appears fully priced")
    if mapping.verification_status == VerificationStatus.REJECTED:
        reasons.append("signal mapping was rejected")

    research_priority_eligible = (
        mapping.verification_status != VerificationStatus.REJECTED
        and mapping.relevance >= 0.5
        and bool(mapping.hypothesis_id)
    )
    entry_action_eligible = verified and not reasons and mapping.relevance >= 0.7
    return {
        "signal_id": signal.signal_id,
        "hypothesis_id": mapping.hypothesis_id,
        "thesis_key": mapping.thesis_key,
        "assumption_key": mapping.assumption_key,
        "research_priority_eligible": research_priority_eligible,
        "entry_action_eligible": entry_action_eligible,
        "reasons": reasons,
        "important_is_not_investment_materiality": True,
    }


def ingest_signals(store: ResearchStore, signals: Sequence[NewsSignal]) -> list[str]:
    return [store.add_signal(signal) for signal in signals]
