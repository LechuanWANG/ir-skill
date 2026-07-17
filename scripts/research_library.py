#!/usr/bin/env python3
"""Central local storage helpers for reports, source material, and research settings."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = PROJECT_ROOT / "report"
LIBRARY_ROOT = PROJECT_ROOT / "data" / "research-library"
LIBRARY_FILES = LIBRARY_ROOT / "files"
STAGING_ROOT = LIBRARY_ROOT / "staging"
LIBRARY_DATABASE = LIBRARY_ROOT / "database" / "investment_research.sqlite"
CATALOG_PATH = LIBRARY_ROOT / "catalog.json"
WIKI_QUEUE_PATH = LIBRARY_ROOT / "wiki-ingest-queue.json"
PROFILE_PATH = LIBRARY_ROOT / "settings" / "investor-profile.json"
TRASH_ROOT = LIBRARY_ROOT / "trash"
LEGACY_DATABASE = PROJECT_ROOT / "data" / "investment_research.sqlite"
WIKI_ROOT = PROJECT_ROOT / "docs" / "investment-llm-wiki"
WIKI_RAW_ROOT = WIKI_ROOT / "raw"

DOMAIN_LABELS = {
    "company": "个股",
    "industry": "行业",
    "market": "市场",
    "macro": "宏观",
    "other": "其他",
}
KIND_LABELS = {
    "temporary_source": "临时资料",
    "source_markdown": "资料文字归档",
    "report": "正式报告",
    "output_markdown": "输出分析",
}
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".html", ".htm", ".yaml", ".yml"}
CURATABLE_EXTENSIONS = TEXT_EXTENSIONS
RETAINED_SOURCE_EXTENSIONS = {".pdf", ".xls", ".xlsx", ".parquet", ".zip"}
BUILD_ARTIFACT_SUFFIXES = {".html", ".htm", ".tex", ".aux", ".log", ".out", ".fls", ".xdv", ".fdb_latexmk"}
ARCHIVE_KIND = "source_markdown"
MAX_SOURCE_TEXT_CHARS = 500_000
PDF_RECOGNITION_VERSION = "agent-visual-v1"
DATE_PATTERN = re.compile(r"(20\d{2})[-_年](\d{1,2})[-_月](\d{1,2})")
LOW_REUSE_QUERY_LABELS = (
    "交易日历",
    "日线行情",
    "历史行情",
    "每日估值与流动性",
    "涨跌停价格",
    "资金流向",
    "行情快照",
    "股票基础信息",
    "预约披露日",
)
RESEARCH_TASK_SCHEMA_VERSION = 1
RESEARCH_TASK_STATE_FILE = "task-state.json"
RESEARCH_STATE_FILE = "research-state.md"
RESEARCH_TASK_STATUSES = {"active", "blocked", "completed", "abandoned"}
RESEARCH_TASK_TERMINAL_STATUSES = {"completed", "abandoned"}
DEFAULT_RESEARCH_TASK_RETENTION_DAYS = 7
FILES_INDEX_NAME = "INDEX.md"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_library() -> None:
    for path in (REPORT_ROOT, LIBRARY_FILES, STAGING_ROOT, LIBRARY_DATABASE.parent, PROFILE_PATH.parent, TRASH_ROOT, WIKI_RAW_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def safe_segment(value: str, fallback: str) -> str:
    cleaned = value.strip().replace("/", "-").replace("\\", "-").replace("\x00", "")
    return cleaned or fallback


def date_from_text(value: str, fallback: datetime) -> str:
    match = DATE_PATTERN.search(value)
    if not match:
        return fallback.strftime("%Y-%m-%d")
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return fallback.strftime("%Y-%m-%d")


def file_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:20]


def parse_frontmatter(path: Path) -> dict[str, str]:
    if path.suffix.lower() != ".md":
        return {}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")[:65536]
    except OSError:
        return {}
    if not content.startswith("---"):
        return {}
    marker = content.find("\n---", 3)
    if marker == -1:
        return {}
    values: dict[str, str] = {}
    for line in content[3:marker].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip():
            values[key.strip()] = value.strip().strip("\"'")
    return values


def library_relative(path: Path) -> str:
    return str(path.relative_to(LIBRARY_ROOT))


def report_relative(path: Path) -> str:
    return str(path.relative_to(REPORT_ROOT))


def record_path(record: Mapping[str, Any]) -> Path:
    storage = str(record.get("storage", "library"))
    root = REPORT_ROOT if storage == "report" else LIBRARY_ROOT
    path = (root / str(record["path"])).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("资料路径不在允许的本地目录内") from exc
    return path


def record_category(path: Path) -> str:
    try:
        parts = path.relative_to(LIBRARY_FILES).parts
    except ValueError:
        return "未分类"
    if len(parts) < 4 or DATE_PATTERN.fullmatch(parts[2]):
        return "未分类"
    return parts[2]


def load_catalog() -> list[dict[str, Any]]:
    payload = read_json(CATALOG_PATH, {"records": []})
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return []
    existing: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        path = LIBRARY_ROOT / str(record.get("path", ""))
        if path.is_file():
            existing.append(record)
    return existing


def render_files_index(records: Iterable[Mapping[str, Any]]) -> str:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        relative_path = str(record.get("path", ""))
        if not relative_path.startswith("files/") or relative_path == f"files/{FILES_INDEX_NAME}":
            continue
        path_parts = Path(relative_path).parts
        recorded_category = str(record.get("category") or "未分类")
        category = path_parts[3] if recorded_category == "未分类" and len(path_parts) >= 5 else recorded_category
        key = (
            str(record.get("domain") or "other"),
            str(record.get("subject") or "未分类"),
            category,
        )
        grouped.setdefault(key, []).append(record)
    lines = [
        "---",
        "title: 研究资料库索引",
        "type: agent-reuse-entry",
        f"updated_at: {now_iso()}",
        "---",
        "",
        "# 研究资料库索引",
        "",
        "> 本文件是 Agent 的历史资料入口，不是当前事实源。仅在用户明确授权复用历史资料时先阅读本页，再按主题最小化加载相关文件并重核来源与时效。",
        "",
        "## 使用规则",
        "",
        "1. 先按领域、主题和类别定位资料；不要扫描整个 `files/`。",
        "2. 摘要用于定位与交叉核验；涉及财务、公告、监管或重大事项时，回到链接的原始文件。",
        "3. 历史研究结论不继承为当前判断，必须标注其 `as_of` 并以本轮证据重核。",
        "4. 不从资料库推断用户持仓、风险偏好或交易记录。",
        "",
        "## 主题目录",
        "",
    ]
    if not grouped:
        lines.append("当前没有已归档资料。")
    for (domain, subject, category), entries in sorted(grouped.items()):
        lines.append(f"### {DOMAIN_LABELS.get(domain, domain)} / {subject} / {category}")
        lines.append("")
        for entry in sorted(entries, key=lambda item: (str(item.get("date", "")), str(item.get("title", ""))), reverse=True):
            path = str(entry["path"])[len("files/") :].replace(" ", "%20")
            title = str(entry.get("title") or Path(path).stem)
            date = str(entry.get("date") or "日期未知")
            extension = str(entry.get("extension") or Path(path).suffix.lstrip("."))
            lines.append(f"- `{date}` [{title}]({path}) (`{extension}`)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_files_index(records: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    ensure_library()
    index_path = LIBRARY_FILES / FILES_INDEX_NAME
    catalog_records = list(records) if records is not None else load_catalog()
    index_path.write_text(render_files_index(catalog_records), encoding="utf-8")
    return {
        "path": library_relative(index_path),
        "records": sum(1 for record in catalog_records if str(record.get("path", "")).startswith("files/")),
    }


def save_catalog(records: Iterable[dict[str, Any]]) -> None:
    sorted_records = sorted(records, key=lambda record: str(record.get("updated_at", "")), reverse=True)
    write_json(CATALOG_PATH, {"updated_at": now_iso(), "records": sorted_records})
    write_files_index(sorted_records)


def list_records() -> list[dict[str, Any]]:
    queue = read_json(WIKI_QUEUE_PATH, {"items": []})
    queue_items = queue.get("items", []) if isinstance(queue, dict) else []
    queued_ids = {str(item.get("record_id")) for item in queue_items if isinstance(item, dict)}
    records = []
    for record in load_catalog():
        path = LIBRARY_ROOT / str(record["path"])
        item = dict(record)
        item["exists"] = path.is_file()
        item["category"] = str(item.get("category") or record_category(path))
        item["wiki_queued"] = item["id"] in queued_ids
        item["storage"] = "library"
        records.append(item)
    return records


def report_context(path: Path) -> tuple[str, str, str]:
    metadata = parse_frontmatter(path)
    parts = path.relative_to(REPORT_ROOT).parts
    default_domain, default_subject = infer_report_subject(path)
    domain = str(metadata.get("domain") or (parts[0] if parts and parts[0] in DOMAIN_LABELS else default_domain))
    if domain not in DOMAIN_LABELS:
        domain = "other"
    subject = str(metadata.get("subject") or (parts[1] if len(parts) > 2 else default_subject))
    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    report_date = str(metadata.get("as_of") or metadata.get("date") or date_from_text(path.name, modified_at))
    return domain, subject, report_date


def report_record_from_path(path: Path, *, origin: str | None = None) -> dict[str, Any]:
    relative_path = report_relative(path)
    metadata = parse_frontmatter(path)
    domain, subject, report_date = report_context(path)
    return {
        "id": file_id(f"report/{relative_path}"),
        "path": relative_path,
        "storage": "report",
        "domain": domain,
        "subject": subject,
        "category": str(metadata.get("category") or "研究报告"),
        "date": report_date,
        "kind": "report",
        "research_type": metadata.get("type", KIND_LABELS["report"]),
        "title": metadata.get("title", path.stem),
        "extension": path.suffix.lower().lstrip("."),
        "size": path.stat().st_size,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "origin": origin or f"report/{relative_path}",
    }


def list_reports() -> list[dict[str, Any]]:
    if not REPORT_ROOT.is_dir():
        return []
    reports = [report_record_from_path(path) for path in REPORT_ROOT.rglob("*") if path.is_file()]
    return sorted(reports, key=lambda record: str(record["updated_at"]), reverse=True)


def list_visible_records() -> list[dict[str, Any]]:
    return sorted([*list_reports(), *list_records()], key=lambda record: str(record["updated_at"]), reverse=True)


def get_record(record_id: str) -> dict[str, Any] | None:
    return next((record for record in list_visible_records() if record["id"] == record_id), None)


def record_preview(record: dict[str, Any], limit: int = 160000) -> dict[str, Any]:
    path = record_path(record)
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return {
            "kind": "file",
            "content": "该文件是二进制原始材料。界面展示文件信息，原件保存在集中数据层。",
        }
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"kind": "error", "content": f"无法读取文件：{exc}"}
    return {
        "kind": "text",
        "content": content[:limit],
        "truncated": len(content) > limit,
    }


def move_record_to_trash(record_id: str) -> dict[str, Any]:
    record = get_record(record_id)
    if record is None:
        raise FileNotFoundError("未找到该资料")
    if record.get("storage") == "report":
        raise ValueError("正式报告保存在 report/，不能通过资料库回收区移动")
    source = record_path(record)
    destination = TRASH_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S") / str(record["path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    save_catalog(record for record in load_catalog() if record["id"] != record_id)
    return {"destination": library_relative(destination)}


def wiki_raw_copy(record: Mapping[str, Any]) -> tuple[str, bool, str]:
    """Copy one library record to the immutable Wiki raw source tree."""
    source = (LIBRARY_ROOT / str(record["path"])).resolve()
    try:
        source.relative_to(LIBRARY_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("资料路径不在集中资料库内") from exc
    if not source.is_file():
        raise FileNotFoundError("待沉淀的资料文件不存在")

    source_digest = file_digest(source)
    destination_directory = (
        WIKI_RAW_ROOT
        / safe_segment(str(record["domain"]), "other")
        / safe_segment(str(record["subject"]), "未命名主题")
        / safe_segment(str(record["date"]), datetime.now().strftime("%Y-%m-%d"))
    )
    destination_directory.mkdir(parents=True, exist_ok=True)
    filename = safe_segment(source.name, f"{record['id']}{source.suffix.lower()}")
    destination = destination_directory / filename

    if destination.exists() and file_digest(destination) != source_digest:
        destination = destination.with_name(f"{destination.stem}-{source_digest[:8]}{destination.suffix}")
    if destination.exists():
        if file_digest(destination) != source_digest:
            raise ValueError("Wiki Raw 目录中存在同名但内容不同的资料")
        return str(destination.relative_to(PROJECT_ROOT)), False, source_digest

    shutil.copy2(source, destination)
    return str(destination.relative_to(PROJECT_ROOT)), True, source_digest


def wiki_raw_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = (PROJECT_ROOT / value).resolve()
    try:
        path.relative_to(WIKI_RAW_ROOT.resolve())
    except ValueError:
        return None
    return path


def prune_wiki_raw_parents(path: Path) -> None:
    raw_root = WIKI_RAW_ROOT.resolve()
    for directory in path.parents:
        if directory == raw_root:
            break
        try:
            directory.rmdir()
        except OSError:
            break


def enqueue_wiki_ingest(record_id: str) -> dict[str, Any]:
    record = get_record(record_id)
    if record is None:
        raise FileNotFoundError("未找到该资料")
    payload = read_json(WIKI_QUEUE_PATH, {"items": []})
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []

    existing = next((item for item in items if isinstance(item, dict) and item.get("record_id") == record_id), None)
    if existing is not None:
        existing_raw_path = wiki_raw_path(existing.get("raw_path"))
        if existing_raw_path is not None and existing_raw_path.is_file():
            return record
        raw_path, raw_created, source_digest = wiki_raw_copy(record)
        existing.update({"raw_path": raw_path, "raw_created": raw_created, "raw_sha256": source_digest})
        write_json(WIKI_QUEUE_PATH, {"updated_at": now_iso(), "items": items})
        return record

    raw_path, raw_created, source_digest = wiki_raw_copy(record)
    items.append(
        {
            "record_id": record_id,
            "path": record["path"],
            "domain": record["domain"],
            "subject": record["subject"],
            "queued_at": now_iso(),
            "status": "pending_agent_review",
            "raw_path": raw_path,
            "raw_created": raw_created,
            "raw_sha256": source_digest,
        }
    )
    write_json(WIKI_QUEUE_PATH, {"updated_at": now_iso(), "items": items})
    return record


def cancel_wiki_ingest(record_id: str) -> dict[str, Any]:
    payload = read_json(WIKI_QUEUE_PATH, {"items": []})
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    removed = [item for item in items if isinstance(item, dict) and item.get("record_id") == record_id]
    if not removed:
        raise ValueError("该资料不在待沉淀队列中")

    remaining = [item for item in items if not (isinstance(item, dict) and item.get("record_id") == record_id)]
    referenced_raw_paths = {str(item.get("raw_path")) for item in remaining if isinstance(item, dict)}
    raw_removed = False
    for item in removed:
        raw_path_value = str(item.get("raw_path", ""))
        raw_path = wiki_raw_path(raw_path_value)
        if (
            raw_path is None
            or raw_path_value in referenced_raw_paths
            or not item.get("raw_created")
            or not raw_path.is_file()
            or str(item.get("raw_sha256", "")) != file_digest(raw_path)
        ):
            continue
        raw_path.unlink()
        prune_wiki_raw_parents(raw_path)
        raw_removed = True

    write_json(WIKI_QUEUE_PATH, {"updated_at": now_iso(), "items": remaining})
    return {"raw_removed": raw_removed}


def get_profile() -> dict[str, Any]:
    payload = read_json(PROFILE_PATH, {})
    return payload if isinstance(payload, dict) else {}


def clean_profile_text(value: object, limit: int = 800) -> str:
    return str(value or "").strip()[:limit]


def clean_profile_number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_holding_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    holdings: list[dict[str, Any]] = []
    for item in value[:200]:
        if not isinstance(item, Mapping):
            continue
        holding = {
            "symbol": clean_profile_text(item.get("symbol"), 32),
            "name": clean_profile_text(item.get("name"), 80),
            "quantity": clean_profile_number(item.get("quantity")),
            "average_cost": clean_profile_number(item.get("average_cost")),
            "latest_price": clean_profile_number(item.get("latest_price")),
            "target_weight": clean_profile_number(item.get("target_weight")),
            "notes": clean_profile_text(item.get("notes"), 600),
        }
        if any(value not in ("", None) for value in holding.values()):
            holdings.append(holding)
    return holdings


def clean_trade_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    trades: list[dict[str, Any]] = []
    for item in value[:500]:
        if not isinstance(item, Mapping):
            continue
        side = clean_profile_text(item.get("side"), 8)
        trade = {
            "date": clean_profile_text(item.get("date"), 16),
            "side": side if side in {"buy", "sell"} else "",
            "symbol": clean_profile_text(item.get("symbol"), 32),
            "name": clean_profile_text(item.get("name"), 80),
            "quantity": clean_profile_number(item.get("quantity")),
            "price": clean_profile_number(item.get("price")),
            "fees": clean_profile_number(item.get("fees")),
            "realized_pnl": clean_profile_number(item.get("realized_pnl")),
            "notes": clean_profile_text(item.get("notes"), 600),
        }
        if any(value not in ("", None) for value in trade.values()):
            trades.append(trade)
    return trades


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    clean_profile = {
        "horizon": clean_profile_text(profile.get("horizon"), 120),
        "style": clean_profile_text(profile.get("style"), 120),
        "risk_tolerance": clean_profile_text(profile.get("risk_tolerance"), 120),
        "review_cadence": clean_profile_text(profile.get("review_cadence"), 120),
        "focus_sectors": clean_profile_text(profile.get("focus_sectors")),
        "avoid": clean_profile_text(profile.get("avoid")),
        "notes": clean_profile_text(profile.get("notes"), 2_000),
        "holdings": clean_holding_items(profile.get("holdings")),
        "trades": clean_trade_items(profile.get("trades")),
        "updated_at": now_iso(),
    }
    write_json(PROFILE_PATH, clean_profile)
    return clean_profile


def report_destination(source: Path, domain: str, subject: str) -> Path:
    filename = safe_segment(source.name, "untitled")
    base = REPORT_ROOT / safe_segment(domain, "other") / safe_segment(subject, "未分类")
    destination = base / filename
    if not destination.exists():
        return destination
    suffix = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    return base / f"{source.stem}-{suffix}{source.suffix}"


def is_low_reuse_query_artifact(*values: object) -> bool:
    normalized = " ".join(str(value or "") for value in values).lower()
    return any(label.lower() in normalized for label in LOW_REUSE_QUERY_LABELS)


def is_report_library_file(path: Path, record: Mapping[str, Any] | None = None) -> bool:
    if record and str(record.get("kind")) in {"report", "output_markdown"}:
        return True
    try:
        relative_parts = path.relative_to(LIBRARY_FILES).parts
    except ValueError:
        return False
    return "研究报告" in relative_parts


def migrate_report_storage(*, apply: bool) -> dict[str, Any]:
    """Move generated reports out of the source archive and into report/."""

    ensure_library()
    catalog_records = {str(record.get("path", "")): record for record in load_catalog()}
    candidates: list[tuple[Path, dict[str, Any] | None]] = []
    for source in LIBRARY_FILES.rglob("*"):
        if not source.is_file() or source.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        relative_path = library_relative(source)
        record = catalog_records.get(relative_path)
        if is_report_library_file(source, record):
            candidates.append((source, record))
    if not apply:
        return {"apply": False, "reports": len(candidates), "migrated": 0}

    moved_paths: set[str] = set()
    for source, record in candidates:
        metadata = parse_frontmatter(source)
        relative_parts = source.relative_to(LIBRARY_FILES).parts
        inferred_domain, inferred_subject = infer_report_subject(source)
        domain = str(metadata.get("domain") or (relative_parts[0] if relative_parts and relative_parts[0] in DOMAIN_LABELS else (record or {}).get("domain") or inferred_domain))
        subject = str(metadata.get("subject") or (relative_parts[1] if len(relative_parts) > 1 else (record or {}).get("subject") or inferred_subject))
        destination = report_destination(source, domain, subject)
        destination.parent.mkdir(parents=True, exist_ok=True)
        moved_paths.add(library_relative(source))
        shutil.move(str(source), str(destination))
    if moved_paths:
        save_catalog(record for record in load_catalog() if str(record.get("path")) not in moved_paths)
        prune_empty_directories(LIBRARY_FILES)
    return {"apply": True, "reports": len(candidates), "migrated": len(moved_paths)}


def cleanup_low_reuse_query_artifacts(*, apply: bool) -> dict[str, Any]:
    """Remove archived daily market-query exports that belong in SQLite, not files/."""

    candidates: list[Path] = []
    for source in LIBRARY_FILES.rglob("*"):
        if not source.is_file():
            continue
        try:
            category = record_category(source)
            relative_path = library_relative(source)
        except ValueError:
            continue
        if is_low_reuse_query_artifact(source.stem, category, relative_path):
            candidates.append(source)
    if not apply:
        return {"apply": False, "artifacts": len(candidates), "removed": 0}

    removed_paths = {library_relative(source) for source in candidates}
    for source in candidates:
        source.unlink()
    if removed_paths:
        save_catalog(record for record in load_catalog() if str(record.get("path")) not in removed_paths)
        prune_empty_directories(LIBRARY_FILES)
    return {"apply": True, "artifacts": len(candidates), "removed": len(removed_paths)}


class VisibleTextExtractor(HTMLParser):
    """Extract readable text from a saved HTML response without retaining markup."""

    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._IGNORED_TAGS:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n\n".join(self._parts)


def truncate_source_text(content: str) -> str:
    if len(content) <= MAX_SOURCE_TEXT_CHARS:
        return content
    return f"{content[:MAX_SOURCE_TEXT_CHARS]}\n\n> 内容超过 {MAX_SOURCE_TEXT_CHARS:,} 个字符，已截断。结构化完整数据仍保存在 SQLite 或原始可复用文件中。"


def code_fence(content: str, language: str) -> str:
    fence = "````" if "```" in content else "```"
    return f"{fence}{language}\n{content}\n{fence}"


def build_pdf_agent_review_card(path: Path) -> dict[str, Any]:
    """Create an Agent-owned PDF transcription task without programmatic text extraction."""

    content = (
        "> 此处不是 PDF 的自动文字提取结果，不能作为研究事实引用。\n\n"
        "## 待 Agent 视觉转写\n\n"
        "1. 渲染并逐页查看原 PDF；先记录公告日、报告期、单位、币种和页码。\n"
        "2. 只把视觉核对过的叙述和表格写成 Markdown；每个数字附原 PDF 页码和表名。\n"
        "3. 对财务三表、经营指标或复杂表格，优先用官方 HTML、Excel 或 XBRL 逐项交叉验证。\n"
        "4. 将经核验的内容由 Agent 写入 `archive-plan.json`；未完成前保留该 PDF，不能归档此占位页。\n"
    )
    metadata: dict[str, Any] = {
        "pdf_extraction_status": "agent_transcription_required",
        "pdf_transcription_method": "agent_visual_review",
        "pdf_table_policy": "do_not_auto_extract",
        "pdf_markdown_eligible": False,
        "pdf_recognition_version": PDF_RECOGNITION_VERSION,
        "source_filename": path.name,
    }
    return {"content": content, "metadata": metadata}


def extract_pdf_text(path: Path) -> str:
    """Compatibility wrapper that deliberately returns an Agent transcription task."""

    return str(build_pdf_agent_review_card(path)["content"])


def extract_source_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"> 无法读取该来源（{type(exc).__name__}）。"
    if suffix in {".html", ".htm"}:
        parser = VisibleTextExtractor()
        try:
            parser.feed(raw)
            parser.close()
        except OSError:
            pass
        content = parser.text()
        return truncate_source_text(content or "> HTML 中没有可读正文。")
    if suffix == ".json":
        try:
            content = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            content = raw
        return code_fence(truncate_source_text(content), "json")
    if suffix == ".csv":
        try:
            rows = list(csv.reader(io.StringIO(raw)))
            content = "\n".join(" | ".join(cell.replace("|", "\\|") for cell in row) for row in rows)
        except csv.Error:
            content = raw
        return code_fence(truncate_source_text(content), "csv")
    return truncate_source_text(raw)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_entry_id(path: Path) -> str:
    identity = f"{path.name}\0{file_digest(path)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def archive_entry_ids(path: Path) -> set[str]:
    value = parse_frontmatter(path).get("source_entries", "")
    return {item for item in value.split(",") if item}


def remove_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    marker = content.find("\n---", 3)
    return content[marker + 4 :].lstrip("\n") if marker != -1 else content


def archive_destination(domain: str, subject: str, date: str) -> Path:
    filename = safe_segment(f"{subject}-{date}-资料文字归档.md", "资料文字归档.md")
    return LIBRARY_FILES / domain / subject / date / ARCHIVE_KIND / filename


def render_source_archive(
    *,
    subject: str,
    domain: str,
    date: str,
    source_entries: list[str],
    body: str,
) -> str:
    metadata = {
        "title": f"{subject} 资料文字归档",
        "type": KIND_LABELS[ARCHIVE_KIND],
        "domain": domain,
        "subject": subject,
        "as_of": date,
        "generated_at": now_iso(),
        "source_count": str(len(source_entries)),
        "source_entries": ",".join(source_entries),
    }
    frontmatter = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items())
    return f"---\n{frontmatter}\n---\n\n# {subject} 资料文字归档\n\n{body.rstrip()}\n"


def source_section(path: Path) -> str:
    source_type = path.suffix.lower().lstrip(".") or "未知格式"
    if path.suffix.lower() == ".pdf":
        content = extract_pdf_text(path)
        retention = "PDF 原件保留在 `temporary_source/`。"
    else:
        content = extract_source_text(path)
        retention = "该中间文件在归档成功后自动清理。"
    return "\n".join(
        (
            f"## {path.name}",
            "",
            f"- 来源格式：{source_type.upper()}",
            f"- 文件大小：{path.stat().st_size:,} B",
            f"- 处理说明：{retention}",
            "",
            content.strip(),
        )
    )


def record_from_path(
    path: Path,
    *,
    domain: str,
    subject: str,
    date: str,
    kind: str,
    title: str | None = None,
    origin: str,
) -> dict[str, Any]:
    relative_path = library_relative(path)
    metadata = parse_frontmatter(path)
    return {
        "id": file_id(relative_path),
        "path": relative_path,
        "domain": domain,
        "subject": subject,
        "category": record_category(path),
        "date": date,
        "kind": kind,
        "research_type": metadata.get("type", KIND_LABELS[kind]),
        "title": metadata.get("title", title or path.stem),
        "extension": path.suffix.lower().lstrip("."),
        "size": path.stat().st_size,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "origin": origin,
    }


def temporary_source_groups() -> list[tuple[Path, str, str, str]]:
    groups: list[tuple[Path, str, str, str]] = []
    if not LIBRARY_FILES.is_dir():
        return groups
    for source_dir in sorted(path for path in LIBRARY_FILES.rglob("temporary_source") if path.is_dir()):
        parts = source_dir.relative_to(LIBRARY_FILES).parts
        if len(parts) != 4:
            continue
        domain, subject, date, _ = parts
        if domain not in DOMAIN_LABELS:
            domain = "other"
        groups.append((source_dir, domain, subject, date_from_text(date, datetime.fromtimestamp(source_dir.stat().st_mtime))))
    return groups


def is_build_artifact(path: Path) -> bool:
    return path.suffix.lower() in BUILD_ARTIFACT_SUFFIXES or path.name.endswith(".synctex.gz")


def cleanup_build_artifacts(*, apply: bool) -> int:
    candidates: list[Path] = []
    for root in (PROJECT_ROOT / "reports", PROJECT_ROOT / "output"):
        if root.is_dir():
            candidates.extend(path for path in root.rglob("*") if path.is_file() and is_build_artifact(path))
    if apply:
        for path in candidates:
            path.unlink()
    return len(candidates)


def curate_temporary_sources(*, apply: bool) -> dict[str, Any]:
    """Consolidate temporary source text and remove low-reuse intermediates.

    One Markdown archive is maintained per domain/subject/date. PDFs and other
    explicitly reusable binaries remain in place; textual scrape and response
    files are appended to the archive and removed only after a successful write.
    """

    ensure_library()
    summary = {
        "apply": apply,
        "groups": 0,
        "source_entries_added": 0,
        "archives_created": 0,
        "archives_updated": 0,
        "intermediate_files": 0,
        "intermediate_files_removed": 0,
        "retained_pdfs": 0,
        "low_reuse_query_artifacts": 0,
        "low_reuse_query_artifacts_removed": 0,
        "build_artifacts": 0,
        "build_artifacts_removed": 0,
    }
    records_to_register: list[dict[str, Any]] = []
    for source_dir, domain, subject, date in temporary_source_groups():
        sources = sorted(path for path in source_dir.iterdir() if path.is_file())
        query_artifacts = [path for path in sources if is_low_reuse_query_artifact(path.stem, path.name)]
        reusable_sources = [path for path in sources if path not in query_artifacts]
        summary["low_reuse_query_artifacts"] += len(query_artifacts)
        if not reusable_sources:
            if apply:
                for path in query_artifacts:
                    path.unlink()
                summary["low_reuse_query_artifacts_removed"] += len(query_artifacts)
                try:
                    source_dir.rmdir()
                except OSError:
                    pass
            continue
        summary["groups"] += 1
        source_entries = [(path, source_entry_id(path)) for path in reusable_sources if path.suffix.lower() in CURATABLE_EXTENSIONS or path.suffix.lower() == ".pdf"]
        archive = archive_destination(domain, subject, date)
        archive_exists = archive.is_file()
        known_entries = archive_entry_ids(archive) if archive.is_file() else set()
        additions = [(path, entry_id) for path, entry_id in source_entries if entry_id not in known_entries]
        cleanup_candidates = [path for path in reusable_sources if path.suffix.lower() in CURATABLE_EXTENSIONS]
        summary["intermediate_files"] += len(cleanup_candidates)
        summary["retained_pdfs"] += sum(path.suffix.lower() == ".pdf" for path in reusable_sources)
        if additions:
            existing_body = ""
            existing_entries: list[str] = []
            if archive.is_file():
                try:
                    existing_body = remove_frontmatter(archive.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    existing_body = ""
                existing_entries = list(archive_entry_ids(archive))
            new_sections = "\n\n---\n\n".join(source_section(path) for path, _ in additions)
            body = "\n\n---\n\n".join(part for part in (existing_body.strip(), new_sections) if part)
            entries = [*existing_entries, *(entry_id for _, entry_id in additions)]
            if apply:
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_text(
                    render_source_archive(subject=subject, domain=domain, date=date, source_entries=entries, body=body),
                    encoding="utf-8",
                )
                records_to_register.append(
                    record_from_path(
                        archive,
                        domain=domain,
                        subject=subject,
                        date=date,
                        kind=ARCHIVE_KIND,
                        title=f"{subject} 资料文字归档",
                        origin="temporary_source_text_archive",
                    )
                )
            summary["source_entries_added"] += len(additions)
            summary["archives_updated" if archive_exists else "archives_created"] += 1
        elif archive.is_file() and apply:
            records_to_register.append(
                record_from_path(
                    archive,
                    domain=domain,
                    subject=subject,
                    date=date,
                    kind=ARCHIVE_KIND,
                    title=f"{subject} 资料文字归档",
                    origin="temporary_source_text_archive",
                )
            )
        if apply:
            for path in cleanup_candidates:
                path.unlink()
            summary["intermediate_files_removed"] += len(cleanup_candidates)
            for path in query_artifacts:
                path.unlink()
            summary["low_reuse_query_artifacts_removed"] += len(query_artifacts)
            for path in reusable_sources:
                if path.exists():
                    records_to_register.append(
                        record_from_path(
                            path,
                            domain=domain,
                            subject=subject,
                            date=date,
                            kind="temporary_source",
                            origin="temporary_source",
                        )
                    )
            try:
                source_dir.rmdir()
            except OSError:
                pass
    summary["build_artifacts"] = cleanup_build_artifacts(apply=apply)
    if apply:
        summary["build_artifacts_removed"] = summary["build_artifacts"]
        records = {str(record["path"]): record for record in load_catalog()}
        for record in records_to_register:
            records[str(record["path"])] = record
        save_catalog(records.values())
    return summary


def archive_date(value: object) -> str:
    text = str(value or "").strip()
    match = DATE_PATTERN.search(text)
    if not match:
        raise ValueError("归档资料必须提供 YYYY-MM-DD 格式的信息日期")
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("归档资料日期无效") from exc


def canonical_destination(
    *,
    domain: str,
    subject: str,
    category: str,
    title: str,
    date: str,
    suffix: str,
) -> Path:
    if domain not in DOMAIN_LABELS:
        raise ValueError(f"不支持的资料领域：{domain}")
    normalized_date = archive_date(date)
    clean_subject = safe_segment(subject, "未分类")
    clean_category = safe_segment(category, "其他资料")
    clean_title = safe_segment(title, "未命名资料")
    base_name = clean_title if clean_title.endswith(normalized_date) else f"{clean_title}-{normalized_date}"
    return LIBRARY_FILES / domain / clean_subject / clean_category / f"{base_name}{suffix}"


def default_category(domain: str, title: str, kind: str) -> str:
    normalized = title.lower()
    if kind == "report":
        return "研究报告"
    if kind == "output_markdown":
        return "输出分析"
    if domain == "company":
        if any(word in normalized for word in ("财报", "报告", "利润", "现金流", "资产负债", "业绩", "财务")):
            return "财务"
        if any(word in normalized for word in ("公告", "回购", "分配", "投资", "披露")):
            return "公司公告"
        if any(word in normalized for word in ("行情", "资金流", "估值", "涨跌停")):
            return "市场表现"
        if any(word in normalized for word in ("新闻", "网站", "投资者关系")):
            return "外部新闻"
    if domain in {"industry", "macro"}:
        if any(word in normalized for word in ("ppi", "cpi", "通胀", "物价")):
            return "通胀"
        if any(word in normalized for word in ("汇率", "外汇")):
            return "汇率"
        if any(word in normalized for word in ("统计", "运行情况", "数据")):
            return "统计数据"
    if domain == "market":
        if any(word in normalized for word in ("资金流", "两融")):
            return "资金面"
        if any(word in normalized for word in ("交易日历", "交易制度")):
            return "交易制度"
        if any(word in normalized for word in ("行情", "涨跌停", "估值")):
            return "行情与估值"
    return "其他资料"


def legacy_reusable_title(title: str) -> str:
    """Collapse only date-like qualifiers so recurring series share one document."""

    cleaned = re.sub(r"（[^）]*(?:20\d{2}|截至|第\d+季度)[^）]*）", "", title).strip()
    return cleaned or title


def task_directory(task_id: str) -> Path:
    normalized = safe_segment(task_id, "")
    if not normalized or normalized in {".", ".."}:
        raise ValueError("任务暂存目录需要一个明确的任务名称")
    return STAGING_ROOT / normalized


def _research_task_metadata_path(task_id: str) -> Path:
    return task_directory(task_id) / RESEARCH_TASK_STATE_FILE


def _parse_task_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是带时区的 ISO 时间")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是有效的 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return parsed


def _validate_research_task_metadata(task_id: str, metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError(f"任务 {task_id} 的 {RESEARCH_TASK_STATE_FILE} 不是有效对象")
    required = {
        "schema_version",
        "task_id",
        "title",
        "status",
        "state_file",
        "revision",
        "created_at",
        "updated_at",
        "completed_at",
        "cleanup_after",
        "retention_policy",
    }
    missing = sorted(required - metadata.keys())
    if missing:
        raise ValueError(f"任务 {task_id} 的生命周期元数据缺少字段：{', '.join(missing)}")
    if metadata["schema_version"] != RESEARCH_TASK_SCHEMA_VERSION:
        raise ValueError(f"任务 {task_id} 使用了不支持的状态版本：{metadata['schema_version']}")
    if metadata["task_id"] != task_id:
        raise ValueError(f"任务目录 {task_id} 与元数据 task_id 不一致")
    if not isinstance(metadata["title"], str) or not metadata["title"].strip():
        raise ValueError("研究任务标题不能为空")
    if metadata["status"] not in RESEARCH_TASK_STATUSES:
        raise ValueError(f"不支持的研究任务状态：{metadata['status']}")
    if metadata["state_file"] != RESEARCH_STATE_FILE:
        raise ValueError(f"state_file 必须是 {RESEARCH_STATE_FILE}")
    if isinstance(metadata["revision"], bool) or not isinstance(metadata["revision"], int) or metadata["revision"] < 0:
        raise ValueError("revision 必须是非负整数")
    created_at = _parse_task_timestamp(metadata["created_at"], "created_at")
    updated_at = _parse_task_timestamp(metadata["updated_at"], "updated_at")
    if updated_at < created_at:
        raise ValueError("updated_at 不能早于 created_at")
    retention_policy = metadata["retention_policy"]
    if not isinstance(retention_policy, dict) or retention_policy.get("mode") != "terminal-window":
        raise ValueError("retention_policy.mode 必须是 terminal-window")
    retention_days = retention_policy.get("days")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 0:
        raise ValueError("retention_policy.days 必须是非负整数")
    terminal = metadata["status"] in RESEARCH_TASK_TERMINAL_STATUSES
    if terminal:
        completed_at = _parse_task_timestamp(metadata["completed_at"], "completed_at")
        cleanup_after = _parse_task_timestamp(metadata["cleanup_after"], "cleanup_after")
        if cleanup_after < completed_at:
            raise ValueError("cleanup_after 不能早于 completed_at")
    elif metadata["completed_at"] is not None or metadata["cleanup_after"] is not None:
        raise ValueError("活动或阻塞任务不能设置 completed_at/cleanup_after")
    return dict(metadata)


def load_research_task(task_id: str, *, require_state: bool = True) -> dict[str, Any]:
    normalized_task_id = task_directory(task_id).name
    metadata_path = _research_task_metadata_path(task_id)
    if not metadata_path.is_file():
        raise FileNotFoundError(f"任务 {normalized_task_id} 不存在 {RESEARCH_TASK_STATE_FILE}")
    try:
        raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"任务 {normalized_task_id} 的 {RESEARCH_TASK_STATE_FILE} 无法读取") from exc
    metadata = _validate_research_task_metadata(normalized_task_id, raw_metadata)
    if require_state:
        state_path = task_directory(normalized_task_id) / metadata["state_file"]
        if not state_path.is_file() or not state_path.read_text(encoding="utf-8").strip():
            raise ValueError(f"任务 {normalized_task_id} 的 {RESEARCH_STATE_FILE} 不存在或为空")
    return metadata


def init_research_task(task_id: str, *, title: str | None = None, retention_days: int = DEFAULT_RESEARCH_TASK_RETENTION_DAYS) -> dict[str, Any]:
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 0:
        raise ValueError("retention_days 必须是非负整数")
    task_root = task_directory(task_id)
    normalized_task_id = task_root.name
    metadata_path = task_root / RESEARCH_TASK_STATE_FILE
    if metadata_path.exists():
        raise FileExistsError(f"任务 {normalized_task_id} 已有生命周期状态；不会覆盖现有研究")
    clean_title = (title or normalized_task_id).strip()
    if not clean_title:
        raise ValueError("研究任务标题不能为空")
    task_root.mkdir(parents=True, exist_ok=True)
    state_path = task_root / RESEARCH_STATE_FILE
    if not state_path.exists():
        state_path.write_text(f"# {clean_title}\n", encoding="utf-8")
    elif not state_path.read_text(encoding="utf-8").strip():
        state_path.write_text(f"# {clean_title}\n", encoding="utf-8")
    timestamp = now_iso()
    metadata = {
        "schema_version": RESEARCH_TASK_SCHEMA_VERSION,
        "task_id": normalized_task_id,
        "title": clean_title,
        "status": "active",
        "state_file": RESEARCH_STATE_FILE,
        "revision": 0,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "cleanup_after": None,
        "retention_policy": {"mode": "terminal-window", "days": retention_days},
    }
    write_json(metadata_path, metadata)
    return metadata


def checkpoint_research_task(task_id: str, *, status: str | None = None) -> dict[str, Any]:
    metadata = load_research_task(task_id)
    if metadata["status"] in RESEARCH_TASK_TERMINAL_STATUSES:
        raise ValueError(f"任务 {task_id} 已处于终态，不能继续 checkpoint")
    if status is not None and status not in {"active", "blocked"}:
        raise ValueError("checkpoint 只能把任务标记为 active 或 blocked")
    metadata["status"] = status or metadata["status"]
    metadata["revision"] += 1
    metadata["updated_at"] = now_iso()
    write_json(_research_task_metadata_path(task_id), metadata)
    return metadata


def finish_research_task(task_id: str, *, status: str) -> dict[str, Any]:
    if status not in RESEARCH_TASK_TERMINAL_STATUSES:
        raise ValueError("终态只能是 completed 或 abandoned")
    metadata = load_research_task(task_id)
    if metadata["status"] in RESEARCH_TASK_TERMINAL_STATUSES:
        raise ValueError(f"任务 {task_id} 已处于终态 {metadata['status']}")
    completed_at = datetime.now().astimezone()
    retention_days = metadata["retention_policy"]["days"]
    metadata.update(
        {
            "status": status,
            "revision": metadata["revision"] + 1,
            "updated_at": completed_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "cleanup_after": (completed_at + timedelta(days=retention_days)).isoformat(timespec="seconds"),
        }
    )
    write_json(_research_task_metadata_path(task_id), metadata)
    return metadata


def complete_research_task(task_id: str) -> dict[str, Any]:
    """Archive every raw source before a task enters its completed retention window."""

    metadata = load_research_task(task_id)
    task_root = task_directory(metadata["task_id"])
    raw_root = task_root / "raw"
    raw_sources = [path for path in raw_root.rglob("*") if path.is_file()] if raw_root.is_dir() else []
    archive = archive_staged_task(metadata["task_id"], apply=True) if raw_sources else None
    return {
        "task_state": finish_research_task(metadata["task_id"], status="completed"),
        "archive": archive,
    }


def list_research_tasks(*, statuses: Iterable[str] | None = None) -> list[dict[str, Any]]:
    selected = set(RESEARCH_TASK_STATUSES if statuses is None else statuses)
    unsupported = selected - RESEARCH_TASK_STATUSES
    if unsupported:
        raise ValueError(f"不支持的研究任务状态：{', '.join(sorted(unsupported))}")
    if not STAGING_ROOT.is_dir():
        return []
    tasks: list[dict[str, Any]] = []
    for metadata_path in sorted(STAGING_ROOT.glob(f"*/{RESEARCH_TASK_STATE_FILE}")):
        task_id = metadata_path.parent.name
        metadata = load_research_task(task_id, require_state=False)
        if metadata["status"] in selected:
            tasks.append(metadata)
    return sorted(tasks, key=lambda item: (item["updated_at"], item["task_id"]), reverse=True)


def cleanup_research_task_states(
    *,
    task_id: str | None = None,
    apply: bool,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    now = current_time or datetime.now().astimezone()
    if now.tzinfo is None:
        raise ValueError("current_time 必须包含时区")
    candidates = [load_research_task(task_id, require_state=False)] if task_id else list_research_tasks(statuses=RESEARCH_TASK_TERMINAL_STATUSES)
    summary: dict[str, Any] = {"apply": apply, "eligible": [], "not_due": []}
    for metadata in candidates:
        if metadata["status"] not in RESEARCH_TASK_TERMINAL_STATUSES:
            summary["not_due"].append({"task_id": metadata["task_id"], "reason": "任务尚未结束"})
            continue
        if _parse_task_timestamp(metadata["cleanup_after"], "cleanup_after") > now:
            summary["not_due"].append({"task_id": metadata["task_id"], "reason": "仍在恢复保留期"})
            continue
        removable = [RESEARCH_TASK_STATE_FILE, RESEARCH_STATE_FILE]
        task_root = task_directory(metadata["task_id"])
        working_path = task_root / "working"
        if working_path.exists() or working_path.is_symlink():
            removable.append("working/")
        summary["eligible"].append({"task_id": metadata["task_id"], "remove": removable})
        if not apply:
            continue
        if working_path.is_symlink() or working_path.is_file():
            working_path.unlink()
        elif working_path.is_dir():
            shutil.rmtree(working_path)
        for filename in (RESEARCH_STATE_FILE, RESEARCH_TASK_STATE_FILE):
            path = task_root / filename
            if path.is_file() or path.is_symlink():
                path.unlink()
        if task_root.is_dir() and not any(task_root.iterdir()):
            task_root.rmdir()
    return summary


def staging_path(task_root: Path, relative_path: str) -> Path:
    candidate = (task_root / relative_path).resolve()
    root = task_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("归档计划中的来源路径不能离开任务暂存目录")
    return candidate


def raw_staging_path(task_root: Path, relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/").strip()
    if not normalized.startswith("raw/"):
        raise ValueError("归档计划中的来源必须指向 raw/ 下的原始文件")
    candidate = staging_path(task_root, normalized)
    raw_root = (task_root / "raw").resolve()
    if not candidate.is_relative_to(raw_root):
        raise ValueError("归档计划中的来源必须指向 raw/ 下的原始文件")
    return candidate


def source_entries_from_frontmatter(path: Path) -> list[str]:
    value = parse_frontmatter(path).get("source_entries", "")
    return [item for item in value.split(",") if item]


def source_urls_from_frontmatter(path: Path) -> list[str]:
    value = parse_frontmatter(path).get("source_urls", "")
    return [item.strip() for item in value.split("|") if item.strip()]


def document_destination(document: Mapping[str, Any]) -> Path:
    return canonical_destination(
        domain=str(document["domain"]),
        subject=str(document["subject"]),
        category=str(document["category"]),
        title=str(document["title"]),
        date=str(document["date"]),
        suffix=".md",
    )


def render_reusable_document(
    *,
    document: Mapping[str, Any],
    source_entries: list[str],
    source_paths: list[str],
    source_urls: list[str],
    body: str,
) -> str:
    metadata = {
        "title": str(document["title"]),
        "type": KIND_LABELS[ARCHIVE_KIND],
        "domain": str(document["domain"]),
        "subject": str(document["subject"]),
        "category": str(document["category"]),
        "as_of": str(document["date"]),
        "source_task": str(document["task"]),
        "source_entries": ",".join(source_entries),
        "source_paths": " | ".join(source_paths),
        "updated_at": now_iso(),
    }
    if source_urls:
        metadata["source_urls"] = " | ".join(source_urls)
    frontmatter = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items())
    return f"---\n{frontmatter}\n---\n\n# {document['title']}\n\n{body.strip()}\n"


def merge_reusable_document(
    document: Mapping[str, Any],
    *,
    source_entries: list[str],
    source_paths: list[str],
    apply: bool,
    source_urls: list[str] | None = None,
) -> tuple[Path, bool]:
    destination = document_destination(document)
    existing_entries = source_entries_from_frontmatter(destination) if destination.is_file() else []
    existing_urls = source_urls_from_frontmatter(destination) if destination.is_file() else []
    known_entries = set(existing_entries)
    additions = [entry for entry in source_entries if entry not in known_entries]
    if destination.is_file() and not additions:
        return destination, False
    content = str(document["content"]).strip()
    if destination.is_file():
        try:
            existing_body = remove_frontmatter(destination.read_text(encoding="utf-8", errors="replace")).strip()
        except OSError:
            existing_body = ""
        body = f"{existing_body}\n\n---\n\n## {document['date']} 补充资料\n\n{content}"
    else:
        body = content
    entries = [*existing_entries, *additions]
    urls = list(dict.fromkeys([*existing_urls, *(source_urls or [])]))
    if apply:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            render_reusable_document(
                document=document,
                source_entries=entries,
                source_paths=source_paths,
                source_urls=urls,
                body=body,
            ),
            encoding="utf-8",
        )
    return destination, True


def has_substantive_markdown_content(content: str) -> bool:
    """Reject documents that only contain headings or the PDF transcription placeholder."""

    meaningful_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "---" or stripped.startswith("#"):
            continue
        if stripped.startswith("> 此处不是 PDF 的自动文字提取结果") or stripped.startswith("> 已停止使用自动 PDF"):
            continue
        if stripped in {"## 待 Agent 视觉转写", "待 Agent 视觉转写"}:
            continue
        meaningful_lines.append(stripped)
    meaningful = "".join(meaningful_lines)
    visible_characters = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", meaningful)
    return len(visible_characters) >= 4


def normalized_plan_document(task_id: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("归档计划中的 documents 必须是对象列表")
    domain = str(value.get("domain", "")).strip()
    subject = str(value.get("subject", "")).strip()
    category = str(value.get("category", "")).strip()
    title = str(value.get("title", "")).strip()
    content = str(value.get("content", "")).strip()
    if domain not in DOMAIN_LABELS or not subject or not category or not title or not content:
        raise ValueError("每份归档文档都需要 domain、subject、category、title 和 content")
    if not has_substantive_markdown_content(content):
        raise ValueError("归档文档的 content 必须包含可复用的实质正文，不能只写标题、占位提示或空白")
    sources = value.get("source_files", [])
    if not isinstance(sources, list) or not sources or not all(isinstance(item, str) and item.strip() for item in sources):
        raise ValueError("source_files 必须是至少包含一个来源的相对路径数组")
    source_files = [item.replace("\\", "/").strip() for item in sources]
    if not all(item.startswith("raw/") for item in source_files):
        raise ValueError("source_files 只能引用 raw/ 下由 Agent 审阅过的原始文件")
    raw_urls = value.get("source_urls", [])
    if raw_urls is None:
        raw_urls = []
    if not isinstance(raw_urls, list) or not all(isinstance(item, str) and re.match(r"^https?://\S+$", item.strip()) for item in raw_urls):
        raise ValueError("source_urls 必须是 http(s) URL 数组")
    source_urls = list(dict.fromkeys(item.strip() for item in raw_urls))
    raw_pdf_validations = value.get("pdf_validations", [])
    if raw_pdf_validations is None:
        raw_pdf_validations = []
    if not isinstance(raw_pdf_validations, list):
        raise ValueError("pdf_validations 必须是 PDF 核验记录数组")
    pdf_validations: list[dict[str, str]] = []
    for validation in raw_pdf_validations:
        if not isinstance(validation, Mapping):
            raise ValueError("每份 PDF 核验记录必须是对象")
        source_file = str(validation.get("source_file", "")).replace("\\", "/").strip()
        method = str(validation.get("method", "")).strip()
        evidence = str(validation.get("evidence", "")).strip()
        status = str(validation.get("status", "")).strip().lower()
        if not source_file.startswith("raw/") or not method or not evidence or status != "verified":
            raise ValueError("PDF 核验记录需要 raw/ 下的 source_file、method、evidence 和 status=verified")
        pdf_validations.append({"source_file": source_file, "method": method[:120], "evidence": evidence[:500], "status": status})
    return {
        "task": task_id,
        "domain": domain,
        "subject": subject[:120],
        "category": category[:120],
        "title": title[:180],
        "date": archive_date(value.get("as_of") or value.get("date")),
        "content": content[:1_000_000],
        "source_files": source_files,
        "source_urls": source_urls,
        "pdf_validations": pdf_validations,
    }


def normalized_plan_discard(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("discard_files 必须是对象列表")
    source_file = str(value.get("source_file", "")).replace("\\", "/").strip()
    reason = str(value.get("reason", "")).strip()
    if not source_file.startswith("raw/") or not reason:
        raise ValueError("每个丢弃项都需要 raw/ 下的 source_file 和明确 reason")
    return {"source_file": source_file, "reason": reason[:500]}


def load_task_archive_plan(task_id: str) -> tuple[Path, list[dict[str, Any]], list[dict[str, str]]]:
    task_root = task_directory(task_id)
    plan_path = task_root / "archive-plan.json"
    payload = read_json(plan_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError("任务暂存目录需要有效的 archive-plan.json")
    raw_documents = payload.get("documents", [])
    raw_discards = payload.get("discard_files", [])
    if not isinstance(raw_documents, list) or not isinstance(raw_discards, list):
        raise ValueError("archive-plan.json 中的 documents 和 discard_files 都必须是数组")
    if not raw_documents and not raw_discards:
        raise ValueError("archive-plan.json 至少需要一个 documents 或 discard_files 项")
    documents = [normalized_plan_document(task_id, item) for item in raw_documents]
    discards = [normalized_plan_discard(item) for item in raw_discards]
    discarded_paths = [item["source_file"] for item in discards]
    if len(discarded_paths) != len(set(discarded_paths)):
        raise ValueError("discard_files 不能重复引用同一个来源")
    documented_paths = {source for document in documents for source in document["source_files"]}
    overlap = documented_paths.intersection(discarded_paths)
    if overlap:
        raise ValueError(f"同一来源不能同时归档和丢弃：{', '.join(sorted(overlap))}")
    return task_root, documents, discards


def pdf_has_verified_validation(document: Mapping[str, Any], raw_source: Path, task_root: Path) -> bool:
    source_path = str(raw_source.resolve().relative_to(task_root.resolve())).replace("\\", "/")
    validations = document.get("pdf_validations", [])
    if not isinstance(validations, list):
        return False
    return any(isinstance(item, Mapping) and item.get("source_file") == source_path and item.get("status") == "verified" for item in validations)


def pdf_can_be_removed(task_root: Path, raw_source: Path, documents: Iterable[Mapping[str, Any]]) -> bool:
    related_documents = list(documents)
    return bool(related_documents) and all(pdf_has_verified_validation(document, raw_source, task_root) for document in related_documents)


def attachment_destination(document: Mapping[str, Any], source: Path) -> Path:
    return canonical_destination(
        domain=str(document["domain"]),
        subject=str(document["subject"]),
        category=str(document["category"]),
        title=source.stem,
        date=str(document["date"]),
        suffix=source.suffix.lower(),
    )


def source_urls_from_collection_metadata(task_root: Path, source_paths: Iterable[Path]) -> list[str]:
    """Retain collector provenance even after temporary HTML is cleared from raw/."""

    urls: list[str] = []
    for source in source_paths:
        metadata_path = task_root / "working" / "collection-metadata" / f"{source.name}.json"
        metadata = read_json(metadata_path, {})
        expected_raw_path = str(source.resolve().relative_to(task_root.resolve())).replace("\\", "/")
        if not isinstance(metadata, Mapping) or metadata.get("raw_path") != expected_raw_path:
            continue
        candidate = str(metadata.get("final_url") or metadata.get("url") or "").strip()
        if re.match(r"^https?://\S+$", candidate):
            urls.append(candidate)
    return list(dict.fromkeys(urls))


def prune_empty_directories(path: Path) -> None:
    for directory in sorted((item for item in path.rglob("*") if item.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue


def archive_staged_task(task_id: str, *, apply: bool) -> dict[str, Any]:
    """Archive or discard every raw task source according to an Agent-authored plan."""

    ensure_library()
    task_root, documents, discards = load_task_archive_plan(task_id)
    low_reuse_documents = [
        document
        for document in documents
        if is_low_reuse_query_artifact(
            document.get("title"),
            document.get("category"),
            *(document.get("source_files") or []),
        )
    ]
    if low_reuse_documents:
        titles = ", ".join(str(document.get("title") or "未命名查询") for document in low_reuse_documents)
        raise ValueError(f"日常市场查询结果不写入 data/research-library/files/：{titles}。请保留 SQLite 记录或在归档计划中丢弃临时文件。")
    resolved_task_root = task_root.resolve()
    summary = {
        "task": task_id,
        "apply": apply,
        "documents": len(documents),
        "documents_created_or_merged": 0,
        "discarded_files": len(discards),
        "discarded_files_removed": 0,
        "attachments_retained": 0,
        "pdf_sources_archived": 0,
        "temporary_text_files": 0,
        "temporary_text_files_removed": 0,
        "task_cleared": False,
    }
    records_to_register: list[dict[str, Any]] = []
    referenced_raw: set[Path] = set()
    attachment_sources: dict[Path, dict[str, Any]] = {}
    document_sources = [(document, [raw_staging_path(task_root, relative) for relative in document["source_files"]]) for document in documents]
    discarded_sources = {raw_staging_path(task_root, item["source_file"]) for item in discards}
    planned_sources = [source for _, sources in document_sources for source in sources] + list(discarded_sources)
    missing = [str(path.relative_to(resolved_task_root)) for path in planned_sources if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"归档计划引用的来源不存在：{', '.join(sorted(set(missing)))}")
    raw_root = (task_root / "raw").resolve()
    raw_sources = {path.resolve() for path in raw_root.rglob("*") if path.is_file()} if raw_root.is_dir() else set()
    planned_raw_sources = {path.resolve() for path in planned_sources}
    uncovered = sorted(str(path.relative_to(resolved_task_root)) for path in raw_sources - planned_raw_sources)
    if uncovered:
        raise ValueError(f"archive-plan.json 必须覆盖 raw/ 下所有文件；请归档或明确丢弃：{', '.join(uncovered)}")
    for document, source_paths in document_sources:
        source_entries = [source_entry_id(path) for path in source_paths]
        source_entries.append(hashlib.sha256(document["content"].encode("utf-8")).hexdigest()[:20])
        source_urls = list(dict.fromkeys([*(document.get("source_urls") or []), *source_urls_from_collection_metadata(task_root, source_paths)]))
        destination, changed = merge_reusable_document(
            document,
            source_entries=source_entries,
            source_paths=[str(path.relative_to(resolved_task_root)) for path in source_paths],
            apply=apply,
            source_urls=source_urls,
        )
        if changed:
            summary["documents_created_or_merged"] += 1
        if apply and destination.is_file():
            records_to_register.append(
                record_from_path(
                    destination,
                    domain=document["domain"],
                    subject=document["subject"],
                    date=document["date"],
                    kind=ARCHIVE_KIND,
                    title=document["title"],
                    origin=f"staging/{task_id}",
                )
            )
        for source in source_paths:
            referenced_raw.add(source)
            if source.suffix.lower() not in CURATABLE_EXTENSIONS:
                attachment_sources.setdefault(source, document)
    temporary_text = [path for path in raw_root.rglob("*") if path.is_file() and path.suffix.lower() in CURATABLE_EXTENSIONS]
    summary["temporary_text_files"] = sum(path in referenced_raw for path in temporary_text)
    summary["pdf_sources_removed_after_verified_conversion"] = 0
    summary["pdf_sources_retained_for_review"] = sum(source.suffix.lower() == ".pdf" for source in attachment_sources)
    if apply:
        for source, document in attachment_sources.items():
            destination = attachment_destination(document, source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if file_digest(destination) == file_digest(source):
                    source.unlink()
                else:
                    destination = destination.with_name(f"{destination.stem}-{file_digest(source)[:8]}{destination.suffix}")
                    shutil.move(str(source), str(destination))
            else:
                shutil.move(str(source), str(destination))
            records_to_register.append(
                record_from_path(
                    destination,
                    domain=document["domain"],
                    subject=document["subject"],
                    date=document["date"],
                    kind="temporary_source",
                    title=destination.stem,
                    origin=f"staging/{task_id}",
                )
            )
            summary["attachments_retained"] += 1
            if source.suffix.lower() == ".pdf":
                summary["pdf_sources_archived"] += 1
        for source in discarded_sources:
            if source.exists():
                source.unlink()
                summary["discarded_files_removed"] += 1
        for source in temporary_text:
            if source in referenced_raw and source.exists():
                source.unlink()
                summary["temporary_text_files_removed"] += 1
        prune_empty_directories(task_root)
        if task_root.is_dir() and not any(task_root.rglob("*")):
            task_root.rmdir()
            summary["task_cleared"] = True
        elif task_root.is_dir() and not any((task_root / "raw").rglob("*")):
            plan_path = task_root / "archive-plan.json"
            if plan_path.is_file():
                plan_path.unlink()
            prune_empty_directories(task_root)
            if task_root.is_dir() and not any(task_root.rglob("*")):
                task_root.rmdir()
                summary["task_cleared"] = True
        records = {str(record["path"]): record for record in load_catalog()}
        for record in records_to_register:
            records[str(record["path"])] = record
        save_catalog(records.values())
    return summary


def render_refreshed_pdf_archive(path: Path, metadata: Mapping[str, str], recognition: Mapping[str, Any]) -> str:
    refreshed_metadata: dict[str, Any] = dict(metadata)
    refreshed_metadata.update(recognition["metadata"])
    refreshed_metadata["source_pdf"] = library_relative(path)
    refreshed_metadata["updated_at"] = now_iso()
    frontmatter = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in refreshed_metadata.items())
    title = str(refreshed_metadata.get("title") or path.stem)
    body = str(recognition["content"]).strip()
    return (
        f"---\n{frontmatter}\n---\n\n# {title}\n\n"
        "> 已停止使用自动 PDF 文字抽取；以下是等待 Agent 视觉转写的任务卡。\n\n"
        f"- 原始文件：`{library_relative(path)}`\n"
        f"- 识别状态：`{refreshed_metadata['pdf_extraction_status']}`\n\n{body}\n"
    )


def refresh_pdf_text_archives(*, apply: bool) -> dict[str, Any]:
    """Replace legacy automated PDF text with Agent-owned visual-transcription cards."""

    ensure_library()
    summary = {
        "apply": apply,
        "pdf_sources": 0,
        "archives_refreshed": 0,
        "agent_transcription_required": 0,
        "skipped": 0,
    }
    records_to_refresh: list[dict[str, Any]] = []
    for pdf_source in sorted(LIBRARY_FILES.rglob("*.pdf")):
        markdown_archive = pdf_source.with_suffix(".md")
        if not markdown_archive.is_file():
            summary["skipped"] += 1
            continue
        metadata = parse_frontmatter(markdown_archive)
        source_paths = metadata.get("source_paths", "")
        normalized_stem = re.sub(r"-20\d{2}-\d{2}-\d{2}$", "", pdf_source.stem)
        original_name = f"{normalized_stem}{pdf_source.suffix}"
        if metadata.get("type") != KIND_LABELS[ARCHIVE_KIND] or (pdf_source.name not in source_paths and original_name not in source_paths):
            summary["skipped"] += 1
            continue
        summary["pdf_sources"] += 1
        recognition = build_pdf_agent_review_card(pdf_source)
        summary["agent_transcription_required"] += 1
        if apply:
            markdown_archive.write_text(render_refreshed_pdf_archive(pdf_source, metadata, recognition), encoding="utf-8")
            records_to_refresh.append(
                record_from_path(
                    markdown_archive,
                    domain=metadata.get("domain", "other"),
                    subject=metadata.get("subject", "未分类"),
                    date=metadata.get("as_of") or datetime.fromtimestamp(pdf_source.stat().st_mtime).astimezone().strftime("%Y-%m-%d"),
                    kind=ARCHIVE_KIND,
                    title=metadata.get("title", markdown_archive.stem),
                    origin="pdf-layout-safe-refresh",
                )
            )
        summary["archives_refreshed"] += 1
    if apply and records_to_refresh:
        records = {str(record["path"]): record for record in load_catalog()}
        for record in records_to_refresh:
            records[str(record["path"])] = record
        save_catalog(records.values())
    return summary


def migrate_legacy_layout(*, apply: bool) -> dict[str, Any]:
    """Move date-folder records into reusable topic folders without losing text."""

    ensure_library()
    summary = {
        "apply": apply,
        "records": 0,
        "documents_created": 0,
        "attachments_retained": 0,
        "files_relocated": 0,
        "script_artifacts": 0,
        "script_artifacts_removed": 0,
    }
    records_to_register: list[dict[str, Any]] = []
    for record in list_records():
        relative = Path(str(record["path"]))
        parts = relative.parts
        if len(parts) < 6 or parts[0] != "files" or parts[4] not in KIND_LABELS:
            continue
        _, domain, subject, date_part, kind, *rest = parts
        source = LIBRARY_ROOT / relative
        if not source.is_file():
            continue
        date = archive_date(record.get("date") or date_part)
        title = str(record.get("title") or source.stem)
        category = default_category(domain, title, kind)
        reusable_title = legacy_reusable_title(title)
        summary["records"] += 1
        if kind in {"report", "output_markdown"} and source.suffix.lower() == ".md":
            destination = report_destination(source, domain, subject)
            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
            summary["files_relocated"] += 1
            continue
        entry = source_entry_id(source)
        if source.suffix.lower() in CURATABLE_EXTENSIONS or source.suffix.lower() == ".pdf":
            document = {
                "task": "legacy-layout-migration",
                "domain": domain,
                "subject": subject,
                "category": category,
                "title": reusable_title,
                "date": date,
                "content": source_section(source),
            }
            destination, changed = merge_reusable_document(
                document,
                source_entries=[entry],
                source_paths=[str(relative)],
                apply=apply,
            )
            if changed:
                summary["documents_created"] += 1
            if apply and destination.is_file():
                records_to_register.append(
                    record_from_path(destination, domain=domain, subject=subject, date=date, kind=ARCHIVE_KIND, title=reusable_title, origin="legacy-layout-migration")
                )
            if source.suffix.lower() in RETAINED_SOURCE_EXTENSIONS:
                attachment = canonical_destination(domain=domain, subject=subject, category=category, title=source.stem, date=date, suffix=source.suffix.lower())
                if apply:
                    attachment.parent.mkdir(parents=True, exist_ok=True)
                    if attachment.exists():
                        if file_digest(attachment) == file_digest(source):
                            source.unlink()
                        else:
                            attachment = attachment.with_name(f"{attachment.stem}-{file_digest(source)[:8]}{attachment.suffix}")
                            shutil.move(str(source), str(attachment))
                    else:
                        shutil.move(str(source), str(attachment))
                    records_to_register.append(
                        record_from_path(attachment, domain=domain, subject=subject, date=date, kind="temporary_source", title=attachment.stem, origin="legacy-layout-migration")
                    )
                summary["attachments_retained"] += 1
            elif apply:
                source.unlink()
            continue
        destination = canonical_destination(domain=domain, subject=subject, category=category, title=source.stem, date=date, suffix=source.suffix.lower())
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            records_to_register.append(
                record_from_path(destination, domain=domain, subject=subject, date=date, kind=kind, title=title, origin="legacy-layout-migration")
            )
        summary["files_relocated"] += 1
    summary["script_artifacts"] = cleanup_build_artifacts(apply=apply)
    if apply:
        summary["script_artifacts_removed"] = summary["script_artifacts"]
        prune_empty_directories(LIBRARY_FILES)
        records = {str(record["path"]): record for record in load_catalog()}
        for record in records_to_register:
            records[str(record["path"])] = record
        save_catalog(records.values())
    summary["report_migration"] = migrate_report_storage(apply=apply)
    summary["low_reuse_query_cleanup"] = cleanup_low_reuse_query_artifacts(apply=apply)
    return summary


def infer_report_subject(path: Path) -> tuple[str, str]:
    normalized = path.name.lower()
    if "sf-holding" in normalized or "顺丰" in path.name:
        return "company", "顺丰控股"
    if "a-share" in normalized or "candidate" in normalized or "bias_strategy" in normalized:
        return "market", "沪深A股"
    return "other", "未分类报告"


def legacy_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_root = WIKI_ROOT / "raw"
    if raw_root.is_dir():
        for path in raw_root.rglob("*"):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(raw_root).parts
            if len(relative_parts) < 4:
                continue
            domain, subject, date = relative_parts[:3]
            if domain not in DOMAIN_LABELS:
                domain = "other"
            items.append(
                {
                    "source": path,
                    "domain": domain,
                    "subject": subject,
                    "date": date_from_text(date, datetime.fromtimestamp(path.stat().st_mtime)),
                    "kind": "temporary_source",
                    "origin": "docs/investment-llm-wiki/raw",
                }
            )
    for root, kind, origin in (
        (PROJECT_ROOT / "reports", "report", "reports"),
        (PROJECT_ROOT / "output", "output_markdown", "output"),
    ):
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if not path.is_file():
                continue
            metadata = parse_frontmatter(path)
            domain, subject = infer_report_subject(path)
            metadata_domain = metadata.get("domain", "").lower()
            if metadata_domain in DOMAIN_LABELS:
                domain = metadata_domain
            subject = metadata.get("subject", subject)
            modified_at = datetime.fromtimestamp(path.stat().st_mtime)
            items.append(
                {
                    "source": path,
                    "domain": domain,
                    "subject": subject,
                    "date": metadata.get("as_of") or date_from_text(path.name, modified_at),
                    "kind": kind,
                    "origin": origin,
                }
            )
    return items


def migrate_legacy(*, apply: bool) -> dict[str, Any]:
    ensure_library()
    plan = legacy_items()
    database_move = LEGACY_DATABASE.is_file() and not LIBRARY_DATABASE.exists()
    summary = {
        "apply": apply,
        "files": len(plan),
        "temporary_sources": sum(item["kind"] == "temporary_source" for item in plan),
        "markdown_reports": sum(item["kind"] != "temporary_source" for item in plan),
        "database_move": database_move,
        "wiki_pages_preserved": len(list((WIKI_ROOT / "wiki").rglob("*.md"))) if (WIKI_ROOT / "wiki").is_dir() else 0,
    }
    if not apply:
        return summary
    records = load_catalog()
    known_sources = {str(record.get("legacy_source", "")) for record in records}
    for item in plan:
        source = Path(item["source"])
        if str(source) in known_sources:
            continue
        if item["kind"] in {"report", "output_markdown"}:
            destination = report_destination(source, item["domain"], item["subject"])
        else:
            destination = (
                LIBRARY_FILES
                / safe_segment(item["domain"], "other")
                / safe_segment(item["subject"], "未分类")
                / safe_segment(item["date"], datetime.now().strftime("%Y-%m-%d"))
                / safe_segment(item["kind"], "temporary_source")
                / safe_segment(source.name, "untitled")
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        if item["kind"] in {"report", "output_markdown"}:
            continue
        relative_path = library_relative(destination)
        metadata = parse_frontmatter(destination)
        records.append(
            {
                "id": file_id(relative_path),
                "path": relative_path,
                "domain": item["domain"],
                "subject": item["subject"],
                "date": item["date"],
                "kind": item["kind"],
                "research_type": metadata.get("type", KIND_LABELS[item["kind"]]),
                "title": metadata.get("title", destination.stem),
                "extension": destination.suffix.lower().lstrip("."),
                "size": destination.stat().st_size,
                "updated_at": datetime.fromtimestamp(destination.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "legacy_source": str(source.relative_to(PROJECT_ROOT)),
                "origin": item["origin"],
            }
        )
    if database_move:
        LIBRARY_DATABASE.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(LEGACY_DATABASE), str(LIBRARY_DATABASE))
    save_catalog(records)
    summary["canonical_migration"] = migrate_legacy_layout(apply=True)
    return summary
