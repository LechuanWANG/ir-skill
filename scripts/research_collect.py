#!/usr/bin/env python3
"""Collect explicit public research sources into a task's traceable staging area."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from research_library import load_research_task, raw_staging_path, safe_segment, task_directory, write_json


DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = "IR-Skill-Research-Collector/1.0 (+local research archive)"
PDF_MAGIC = b"%PDF-"
HTML_PREFIXES = (b"<!doctype html", b"<html", b"<head", b"<body")
CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_BASE_URL = "https://static.cninfo.com.cn/"
CNINFO_REFERER = "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice"
REPORT_TYPES = ("all", "annual", "q1", "q2", "q3")


def require_writable_task(metadata: dict[str, Any], *, operation: str) -> None:
    """Keep terminal task staging immutable after its final archive has run."""

    if metadata["status"] in {"completed", "abandoned"}:
        raise ValueError(
            f"任务 {metadata['task_id']} 已处于终态 {metadata['status']}，不能再{operation}。"
            "请新建一个研究任务，或在完成归档前继续使用 active/blocked 任务。"
        )


def load_writable_task(task_id: str, *, operation: str) -> dict[str, Any]:
    """Explain why completed tasks no longer have a staging directory."""

    try:
        metadata = load_research_task(task_id)
    except FileNotFoundError as error:
        raise ValueError(
            f"任务 {task_id} 的暂存目录不存在，可能已完成归档并清理。请新建研究任务后再{operation}。"
        ) from error
    require_writable_task(metadata, operation=operation)
    return metadata


class VisibleTextExtractor(HTMLParser):
    """Keep visible text only; this is a review aid, not a fact extractor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._parts)).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def content_type(headers: Message | Any) -> str:
    value = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
    return value


def filename_from_response(*, final_url: str, headers: Message | Any, kind: str, requested_name: str | None) -> str:
    if requested_name:
        candidate = requested_name
    else:
        disposition = str(headers.get("Content-Disposition", ""))
        match = re.search(r"filename\*?=(?:UTF-8''|\")?([^;\"]+)", disposition, flags=re.IGNORECASE)
        candidate = unquote(match.group(1)).strip() if match else Path(unquote(urlparse(final_url).path)).name
    candidate = safe_segment(Path(candidate).name, "source")
    suffix = Path(candidate).suffix.lower()
    if kind == "pdf" and suffix != ".pdf":
        candidate = f"{candidate}.pdf"
    if kind == "html" and suffix not in {".html", ".htm"}:
        candidate = f"{candidate}.html"
    return candidate


def unique_destination(directory: Path, filename: str, source_url: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    suffix = destination.suffix
    stem = destination.stem
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:8]
    return directory / f"{stem}-{digest}{suffix}"


def payload_kind(*, payload: bytes, response_type: str, requested_type: str, final_url: str, requested_name: str | None) -> tuple[str | None, str | None]:
    pdf = payload.startswith(PDF_MAGIC)
    compact = payload.lstrip().lower()
    html = compact.startswith(HTML_PREFIXES)
    url_suffix = Path(urlparse(final_url).path).suffix.lower()
    name_suffix = Path(requested_name or "").suffix.lower()
    expected = requested_type
    if expected == "auto" and (url_suffix == ".pdf" or name_suffix == ".pdf" or response_type == "application/pdf"):
        expected = "pdf"
    if expected == "pdf":
        return ("pdf", None) if pdf else (None, "响应不是有效 PDF 文件（缺少 %PDF- 文件头）")
    if expected == "html":
        return ("html", None) if html else (None, "响应不是可识别的 HTML 文档")
    if pdf:
        return "pdf", None
    if html or response_type in {"text/html", "application/xhtml+xml"}:
        return "html", None
    return None, f"不支持或无法识别的响应类型：{response_type or '未提供 Content-Type'}"


def failure_path(task_root: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return task_root / "working" / "collection-failures" / f"{digest}.json"


def record_failure(
    task_root: Path,
    *,
    url: str,
    reason: str,
    failure_type: str,
    retryable: bool = False,
    status_code: int | None = None,
    response_type: str | None = None,
    final_url: str | None = None,
) -> Path:
    path = failure_path(task_root, url)
    write_json(
        path,
        {
            "status": "failed",
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "content_type": response_type,
            "reason": reason,
            "failure_type": failure_type,
            "retryable": retryable,
            "retrieved_at": now_iso(),
        },
    )
    return path


def pdf_rejection_type(*, url: str, final_url: str, response_type: str) -> str:
    """Treat an HTML response to a PDF request as an access issue, not missing disclosure."""

    requested_pdf = Path(urlparse(url).path).suffix.lower() == ".pdf"
    final_pdf = Path(urlparse(final_url).path).suffix.lower() == ".pdf"
    if response_type in {"text/html", "application/xhtml+xml"} and (requested_pdf or final_pdf):
        return "source_access_challenge"
    return "invalid_source_payload"


def cninfo_plate(symbol: str) -> str:
    """Return the CNINFO market filter for an A-share ticker."""

    if not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("symbol 必须是 6 位 A 股代码")
    return "sh" if symbol.startswith(("5", "6", "9")) else "sz"


def cninfo_report_type_matches(title: str, report_type: str) -> bool:
    normalized = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", title))
    if "摘要" in normalized:
        return False
    annual = bool(re.search(r"\d{4}(?:年年度|年度)报告$", normalized))
    first_quarter = bool(re.search(r"\d{4}年(?:第一季度|一季度)报告$", normalized))
    half_year = bool(re.search(r"\d{4}年(?:半年度|半年)报告$", normalized))
    third_quarter = bool(re.search(r"\d{4}年(?:第三季度|三季度)报告$", normalized))
    matches = {
        "annual": annual,
        "q1": first_quarter,
        "q2": half_year,
        "q3": third_quarter,
    }
    return any(matches.values()) if report_type == "all" else matches.get(report_type, False)


def cninfo_source_url(adjunct_url: str) -> str:
    """Normalize CNINFO's relative attachment path to its official static URL."""

    return urljoin(CNINFO_STATIC_BASE_URL, adjunct_url.lstrip("/"))


def discover_cninfo_reports(
    *,
    symbol: str,
    company_name: str,
    start_date: str,
    end_date: str,
    report_type: str = "all",
    max_pages: int = 5,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Locate official CNINFO annual or first-quarter report PDFs without guessing an org ID."""

    symbol = symbol.strip()
    company_name = company_name.strip()
    if not company_name:
        raise ValueError("company_name 不能为空")
    if report_type not in REPORT_TYPES:
        raise ValueError("report_type 必须是 all、annual、q1、q2 或 q3")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须为正数")
    if max_pages <= 0:
        raise ValueError("max_pages 必须为正数")
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("start_date 和 end_date 必须为 YYYY-MM-DD") from error
    if start > end:
        raise ValueError("start_date 不能晚于 end_date")

    query = {
        "pageNum": "1",
        "pageSize": "100",
        "tabName": "fulltext",
        # Company-name search avoids assuming that CNINFO's opaque org ID is derivable from a ticker.
        "stock": "",
        "searchkey": company_name,
        "secid": "",
        "plate": cninfo_plate(symbol),
        # CNINFO's unfiltered result pages are dominated by routine announcements.
        # Annual-report classification prevents the original report from falling beyond page one.
        "category": "category_ndbg_szsh" if report_type == "annual" else "",
        "trade": "",
        "seDate": f"{start_date}~{end_date}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    open_request = opener or urlopen
    reports_by_id: dict[str, dict[str, Any]] = {}
    total_records: int | None = None
    pages_checked = 0
    truncated = False
    for page_number in range(1, max_pages + 1):
        page_query = {**query, "pageNum": str(page_number)}
        request = Request(
            CNINFO_QUERY_URL,
            data=urlencode(page_query).encode("utf-8"),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": CNINFO_REFERER,
            },
        )
        try:
            with open_request(request, timeout=timeout_seconds) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                if status_code and int(status_code) >= 400:
                    return {"status": "failed", "reason": f"CNINFO 返回 HTTP {status_code}", "query": query}
                payload = read_limited(response, DEFAULT_MAX_BYTES)
        except HTTPError as error:
            return {"status": "failed", "reason": f"CNINFO 返回 HTTP {error.code}", "query": query}
        except (URLError, OSError, ValueError) as error:
            return {"status": "failed", "reason": str(error), "query": query}
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return {"status": "failed", "reason": f"CNINFO 响应不是有效 JSON：{error}", "query": query}

        pages_checked += 1
        records = decoded.get("announcements") or []
        total = decoded.get("totalRecordNum")
        total_records = int(total) if isinstance(total, int) or isinstance(total, str) and total.isdigit() else total_records
        for announcement in records:
            if str(announcement.get("secCode", "")).strip() != symbol:
                continue
            title = str(announcement.get("announcementTitle", ""))
            adjunct_url = str(announcement.get("adjunctUrl", "")).strip()
            if not adjunct_url or not cninfo_report_type_matches(title, report_type):
                continue
            announcement_id = str(announcement.get("announcementId", ""))
            reports_by_id[announcement_id] = {
                "title": re.sub(r"<[^>]+>", "", title),
                "announcement_id": announcement_id,
                "announcement_time": announcement.get("announcementTime"),
                "source_url": cninfo_source_url(adjunct_url),
            }
        page_size = int(query["pageSize"])
        if not records or total_records is None or page_number * page_size >= total_records:
            break
    else:
        truncated = total_records is None or pages_checked * int(query["pageSize"]) < total_records

    reports = sorted(reports_by_id.values(), key=lambda item: (str(item["title"]), str(item["announcement_id"])))
    return {
        "status": "found" if reports else "not_found",
        "symbol": symbol,
        "company_name": company_name,
        "report_type": report_type,
        "query": query,
        "total_records": total_records,
        "pages_checked": pages_checked,
        "truncated": truncated,
        "reports": reports,
    }


def read_limited(response: Any, max_bytes: int) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise ValueError(f"响应声明大小超过上限 {max_bytes} bytes")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"响应实际大小超过上限 {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def render_html_review(*, raw_path: Path, final_url: str, retrieved_at: str) -> str:
    parser = VisibleTextExtractor()
    source = raw_path.read_text(encoding="utf-8", errors="replace")
    parser.feed(source)
    parser.close()
    body = parser.text() or "> HTML 未发现可读正文；请检查原始页面。"
    return (
        f"# {raw_path.stem} HTML 审阅副本\n\n"
        "> 这是从静态 HTML 提取的可读文本，仅用于定位和人工核验，不是已经确认的研究事实。\n\n"
        f"- 原始文件：`raw/{raw_path.name}`\n"
        f"- 最终 URL：{final_url}\n"
        f"- 获取时间：{retrieved_at}\n\n"
        "## 可读正文\n\n"
        f"{body}\n"
    )


def render_pdf_review(*, raw_path: Path, final_url: str, retrieved_at: str) -> str:
    return (
        f"# {raw_path.stem} PDF 审阅卡\n\n"
        "> 未执行 PDF 自动文字抽取。财务表格和关键事实必须以渲染页面、页码和官方结构化来源核验。\n\n"
        f"- 原始文件：`raw/{raw_path.name}`\n"
        f"- 最终 URL：{final_url}\n"
        f"- 获取时间：{retrieved_at}\n\n"
        "## 下一步\n\n"
        "1. 执行 `research_collect.py render-pdf` 渲染页面，或使用已有 PDF 工具查看原件。\n"
        "2. 记录公告日、报告期、单位、页码和表名。\n"
        "3. 将经核验的摘要和 `pdf_validations` 写入 `archive-plan.json`，再执行归档。\n"
    )


def collect_source(
    *,
    task_id: str,
    url: str,
    filename: str | None = None,
    expected_type: str = "auto",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download one public source into task raw storage after strict validation."""

    if expected_type not in {"auto", "pdf", "html"}:
        raise ValueError("expected_type 必须是 auto、pdf 或 html")
    if not urlparse(url).scheme in {"http", "https"}:
        raise ValueError("仅允许 http 或 https URL")
    if timeout_seconds <= 0 or max_bytes <= 0:
        raise ValueError("timeout_seconds 和 max_bytes 必须为正数")
    metadata = load_writable_task(task_id, operation="采集原始资料")
    task_root = task_directory(metadata["task_id"])
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html,application/xhtml+xml"})
    open_request = opener or urlopen
    try:
        with open_request(request, timeout=timeout_seconds) as response:
            status_code = getattr(response, "status", None) or response.getcode()
            final_url = response.geturl()
            response_type = content_type(response.headers)
            if status_code and int(status_code) >= 400:
                reason = f"服务器返回 HTTP {status_code}"
                path = record_failure(
                    task_root,
                    url=url,
                    reason=reason,
                    failure_type="http_error",
                    retryable=int(status_code) >= 500,
                    status_code=int(status_code),
                    response_type=response_type,
                    final_url=final_url,
                )
                return {"status": "failed", "reason": reason, "failure_type": "http_error", "failure_path": str(path), "task": metadata["task_id"]}
            payload = read_limited(response, max_bytes)
    except HTTPError as error:
        failure_type = "http_error"
        path = record_failure(
            task_root,
            url=url,
            reason=f"服务器返回 HTTP {error.code}",
            failure_type=failure_type,
            retryable=error.code >= 500,
            status_code=error.code,
            response_type=content_type(error.headers or {}),
            final_url=error.geturl(),
        )
        return {"status": "failed", "reason": f"HTTP {error.code}", "failure_type": failure_type, "failure_path": str(path), "task": metadata["task_id"]}
    except (URLError, OSError, ValueError) as error:
        path = record_failure(task_root, url=url, reason=str(error), failure_type="transient_network", retryable=True)
        return {"status": "failed", "reason": str(error), "failure_type": "transient_network", "failure_path": str(path), "task": metadata["task_id"]}

    kind, rejection_reason = payload_kind(
        payload=payload,
        response_type=response_type,
        requested_type=expected_type,
        final_url=final_url,
        requested_name=filename,
    )
    if rejection_reason:
        failure_type = pdf_rejection_type(url=url, final_url=final_url, response_type=response_type)
        path = record_failure(
            task_root,
            url=url,
            reason=rejection_reason,
            failure_type=failure_type,
            status_code=int(status_code) if status_code else None,
            response_type=response_type,
            final_url=final_url,
        )
        return {"status": "rejected", "reason": rejection_reason, "failure_type": failure_type, "failure_path": str(path), "task": metadata["task_id"]}

    raw_root = task_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    target_name = filename_from_response(final_url=final_url, headers=response.headers, kind=kind or "", requested_name=filename)
    raw_path = unique_destination(raw_root, target_name, url)
    raw_path.write_bytes(payload)
    retrieved_at = now_iso()
    review_path = task_root / "working" / "collection-reviews" / f"{raw_path.stem}-review.md"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review = render_pdf_review(raw_path=raw_path, final_url=final_url, retrieved_at=retrieved_at) if kind == "pdf" else render_html_review(raw_path=raw_path, final_url=final_url, retrieved_at=retrieved_at)
    review_path.write_text(review, encoding="utf-8")
    metadata_path = task_root / "working" / "collection-metadata" / f"{raw_path.name}.json"
    write_json(
        metadata_path,
        {
            "status": "collected",
            "source_kind": kind,
            "url": url,
            "final_url": final_url,
            "status_code": int(status_code) if status_code else None,
            "content_type": response_type,
            "bytes": len(payload),
            "retrieved_at": retrieved_at,
            "raw_path": str(raw_path.relative_to(task_root)),
            "review_path": str(review_path.relative_to(task_root)),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    return {
        "status": "collected",
        "task": metadata["task_id"],
        "source_kind": kind,
        "raw_path": str(raw_path),
        "review_path": str(review_path),
        "metadata_path": str(metadata_path),
        "final_url": final_url,
        "bytes": len(payload),
    }


def _collection_attempt(source: str, url: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source,
        "url": url,
        "status": result["status"],
        "failure_type": result.get("failure_type"),
        "reason": result.get("reason"),
    }


def collect_financial_report(
    *,
    task_id: str,
    symbol: str,
    company_name: str,
    start_date: str,
    end_date: str,
    report_type: str,
    primary_url: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_pages: int = 5,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Collect one official report with CNInfo discovery as a recoverable fallback.

    An HTML security page from an exchange is never treated as evidence that the
    company failed to disclose. The attempted sources remain in the result so a
    browser or another official origin can continue from the exact failure.
    """

    if report_type not in REPORT_TYPES[1:]:
        raise ValueError("collect-report 的 report_type 必须是 annual、q1、q2 或 q3")
    attempts: list[dict[str, Any]] = []
    if primary_url:
        primary = collect_source(
            task_id=task_id,
            url=primary_url,
            expected_type="pdf",
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            opener=opener,
        )
        attempts.append(_collection_attempt("primary", primary_url, primary))
        if primary["status"] == "collected":
            return {"status": "collected", "source": "primary", "result": primary, "attempts": attempts}

    discovery = discover_cninfo_reports(
        symbol=symbol,
        company_name=company_name,
        start_date=start_date,
        end_date=end_date,
        report_type=report_type,
        max_pages=max_pages,
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    if discovery["status"] != "found":
        return {
            "status": "needs_source_resolution",
            "reason": "CNInfo 未返回可验证的匹配定期报告；请使用公司官网、交易所公告页或浏览器定位公开原件。",
            "attempts": attempts,
            "cninfo_discovery": discovery,
        }

    for report in discovery["reports"]:
        source_url = str(report["source_url"])
        result = collect_source(
            task_id=task_id,
            url=source_url,
            expected_type="pdf",
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            opener=opener,
        )
        attempts.append(_collection_attempt("cninfo", source_url, result))
        if result["status"] == "collected":
            return {
                "status": "collected",
                "source": "cninfo",
                "report": report,
                "result": result,
                "attempts": attempts,
            }

    failure_types = {attempt.get("failure_type") for attempt in attempts}
    status = "needs_source_resolution" if "source_access_challenge" in failure_types else "failed"
    return {
        "status": status,
        "reason": "已尝试显式来源与 CNInfo 官方原件，仍未获得有效 PDF。",
        "attempts": attempts,
        "cninfo_discovery": discovery,
    }


def render_pdf_pages(*, task_id: str, source_file: str, dpi: int = 144) -> dict[str, Any]:
    """Render a staged PDF to PNG pages for manual review without text extraction."""

    if dpi < 72 or dpi > 300:
        raise ValueError("dpi 必须在 72 到 300 之间")
    metadata = load_writable_task(task_id, operation="写入 PDF 审阅页")
    task_root = task_directory(metadata["task_id"])
    source = raw_staging_path(task_root, source_file)
    if source.suffix.lower() != ".pdf" or not source.is_file() or not source.read_bytes()[:5] == PDF_MAGIC:
        raise ValueError("source_file 必须是 raw/ 下有效的 PDF 文件")
    binary = shutil.which("pdftoppm")
    if not binary:
        raise RuntimeError("未找到 pdftoppm；请安装 Poppler 或使用已有 PDF 渲染工具")
    output_dir = task_root / "working" / "pdf-pages" / source.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "page"
    result = subprocess.run([binary, "-png", "-r", str(dpi), str(source), str(prefix)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "pdftoppm 渲染失败")
    pages = sorted(str(path.relative_to(task_root)) for path in output_dir.glob("page-*.png"))
    if not pages:
        raise RuntimeError("pdftoppm 未生成页面图像")
    return {
        "task": metadata["task_id"],
        "source_file": source_file,
        "dpi": dpi,
        "page_count": len(pages),
        "output_dir": str(output_dir.relative_to(task_root)),
        "first_page": pages[0],
        "last_page": pages[-1],
    }


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect explicit public HTML/PDF sources into traceable research task staging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Validate one URL and save the valid original to staging/<task>/raw/.")
    collect_parser.add_argument("--task", required=True, help="Existing task folder below data/research-library/staging/.")
    collect_parser.add_argument("--url", required=True, help="Explicit public http(s) source URL.")
    collect_parser.add_argument("--filename", help="Optional local filename; it cannot contain directories.")
    collect_parser.add_argument("--expected-type", choices=("auto", "pdf", "html"), default="auto")
    collect_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    collect_parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)

    render_parser = subparsers.add_parser("render-pdf", help="Render a valid staged PDF to task-local PNG pages for manual review.")
    render_parser.add_argument("--task", required=True)
    render_parser.add_argument("--source-file", required=True, help="PDF path relative to the task, for example raw/annual-report.pdf.")
    render_parser.add_argument("--dpi", type=int, default=144)

    cninfo_parser = subparsers.add_parser("discover-cninfo", help="Find CNINFO annual, interim, or quarterly report PDF URLs by company name, then verify the ticker.")
    cninfo_parser.add_argument("--symbol", required=True, help="6-digit A-share ticker, for example 000338.")
    cninfo_parser.add_argument("--company-name", required=True, help="Exact listed-company name, for example 潍柴动力.")
    cninfo_parser.add_argument("--start-date", required=True, help="Search-window start date: YYYY-MM-DD.")
    cninfo_parser.add_argument("--end-date", required=True, help="Search-window end date: YYYY-MM-DD.")
    cninfo_parser.add_argument("--report-type", choices=REPORT_TYPES, default="all")
    cninfo_parser.add_argument("--max-pages", type=int, default=5, help="Maximum CNINFO result pages to inspect; output marks a truncated search.")
    cninfo_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)

    report_parser = subparsers.add_parser("collect-report", help="Collect an official financial report and fall back to CNInfo after a failed explicit source.")
    report_parser.add_argument("--task", required=True, help="Existing active task folder below data/research-library/staging/.")
    report_parser.add_argument("--symbol", required=True, help="6-digit A-share ticker, for example 000338.")
    report_parser.add_argument("--company-name", required=True, help="Exact listed-company name used for CNInfo discovery.")
    report_parser.add_argument("--start-date", required=True, help="Announcement-search start date: YYYY-MM-DD.")
    report_parser.add_argument("--end-date", required=True, help="Announcement-search end date: YYYY-MM-DD.")
    report_parser.add_argument("--report-type", choices=REPORT_TYPES[1:], required=True)
    report_parser.add_argument("--url", help="Optional official company or exchange PDF URL to try before CNInfo.")
    report_parser.add_argument("--max-pages", type=int, default=5)
    report_parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    report_parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)

    args = parser.parse_args()
    if args.command == "collect":
        result = collect_source(
            task_id=args.task,
            url=args.url,
            filename=args.filename,
            expected_type=args.expected_type,
            timeout_seconds=args.timeout_seconds,
            max_bytes=args.max_bytes,
        )
        print_json(result)
        return 0 if result["status"] == "collected" else 2
    if args.command == "discover-cninfo":
        result = discover_cninfo_reports(
            symbol=args.symbol,
            company_name=args.company_name,
            start_date=args.start_date,
            end_date=args.end_date,
            report_type=args.report_type,
            max_pages=args.max_pages,
            timeout_seconds=args.timeout_seconds,
        )
        print_json(result)
        return 0 if result["status"] == "found" else 2
    if args.command == "collect-report":
        result = collect_financial_report(
            task_id=args.task,
            symbol=args.symbol,
            company_name=args.company_name,
            start_date=args.start_date,
            end_date=args.end_date,
            report_type=args.report_type,
            primary_url=args.url,
            max_pages=args.max_pages,
            timeout_seconds=args.timeout_seconds,
            max_bytes=args.max_bytes,
        )
        print_json(result)
        return 0 if result["status"] == "collected" else 2
    print_json(render_pdf_pages(task_id=args.task, source_file=args.source_file, dpi=args.dpi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
