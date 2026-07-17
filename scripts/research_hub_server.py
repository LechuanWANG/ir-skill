#!/usr/bin/env python3
"""Local HTTP API and static server for the IR Skill research hub."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sqlite3
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import parse_qs, unquote, urlparse

from research_library import (
    DOMAIN_LABELS,
    KIND_LABELS,
    LIBRARY_DATABASE,
    PROJECT_ROOT,
    WIKI_ROOT,
    cancel_wiki_ingest,
    enqueue_wiki_ingest,
    get_profile,
    get_record,
    list_reports,
    list_records,
    list_visible_records,
    move_record_to_trash,
    record_preview,
    save_profile,
)
from tushare_sync import SyncConfig, sync_daily, sync_factor_data


WEB_DIST = PROJECT_ROOT / "web" / "dist"
ENV_PATH = PROJECT_ROOT / ".env"
SECRET_ENV_KEYS = {"TUSHARE_TOKEN"}
COMMON_ENV_KEYS = ("TUSHARE_TOKEN",)
TABLE_LABELS = {
    "a_share_daily": "个股日线行情",
    "a_share_daily_basic": "个股估值与流动性",
    "a_share_fina_indicator": "财务指标",
    "a_share_stock_basic": "股票基础信息",
    "market_trading_calendar": "交易日历",
    "market_index_daily": "指数日线行情",
    "market_index_daily_basic": "指数估值与流动性",
    "market_industry_classification": "行业分类",
    "market_index_member": "行业/指数成分",
    "market_index_weight": "行业/指数权重",
    "market_daily_info": "市场日度概况",
    "market_moneyflow": "市场资金流",
    "market_margin": "市场两融",
    "tushare_research_observation": "研究观察原始缓存",
    "tushare_capability": "接口可用性记录",
}
HIDDEN_UI_TABLES = {"tushare_research_observation"}
TABLE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LATEST_SYNC_TABLES = ("a_share_daily", "a_share_daily_basic")
DATA_SYNC_LOCK = Lock()
DATA_SYNC_STATUS: dict[str, object] = {
    "state": "idle",
    "message": "可同步个股日线、估值与股票基础信息。",
}


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def read_request_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0 or length > 2_000_000:
        raise ValueError("请求内容为空或过大")
    raw = handler.rfile.read(length)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("请求内容必须是对象")
    return payload


def read_env_values() -> dict[str, str]:
    if not ENV_PATH.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            values[key.strip()] = value.strip().strip("\"'")
    return values


def update_env_values(updates: dict[str, str]) -> None:
    existing_lines = ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines() if ENV_PATH.is_file() else []
    output: list[str] = []
    handled: set[str] = set()
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(raw_line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key not in updates:
            output.append(raw_line)
            continue
        if key in handled:
            continue
        handled.add(key)
        value = updates[key]
        if value:
            output.append(f"{key}={value}")
    for key, value in updates.items():
        if key not in handled and value:
            output.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass


def safe_table_name(name: str) -> str:
    if not TABLE_IDENT.fullmatch(name):
        raise ValueError("无效的数据表")
    return f'"{name}"'


def table_latest_date(connection: sqlite3.Connection, table_name: str, columns: list[str]) -> tuple[str | None, str | None]:
    quoted_table = safe_table_name(table_name)
    latest_sync = None
    latest_data = None
    if "retrieved_at" in columns:
        latest_sync = connection.execute(f"SELECT MAX(retrieved_at) FROM {quoted_table}").fetchone()[0]
    for candidate in ("trade_date", "event_date", "end_date", "cal_date", "checked_at", "available_at"):
        if candidate in columns:
            latest_data = connection.execute(f"SELECT MAX({candidate}) FROM {quoted_table}").fetchone()[0]
            break
    return latest_sync, latest_data


def data_sync_status() -> dict[str, object]:
    with DATA_SYNC_LOCK:
        return dict(DATA_SYNC_STATUS)


def data_sync_window() -> tuple[date, date] | None:
    end_date = date.today()
    if not LIBRARY_DATABASE.is_file():
        return end_date, end_date

    latest_dates: list[date] = []
    with sqlite3.connect(LIBRARY_DATABASE) as connection:
        existing_tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        for table_name in LATEST_SYNC_TABLES:
            if table_name not in existing_tables:
                continue
            value = connection.execute(f"SELECT MAX(trade_date) FROM {safe_table_name(table_name)}").fetchone()[0]
            if value:
                latest_dates.append(date.fromisoformat(str(value)[:10]))

    if not latest_dates:
        return end_date, end_date
    start_date = min(latest_dates) + timedelta(days=1)
    return None if start_date > end_date else start_date, end_date


def run_data_sync() -> None:
    try:
        sync_window = data_sync_window()
        if sync_window is None:
            with DATA_SYNC_LOCK:
                DATA_SYNC_STATUS.update(
                    {
                        "state": "success",
                        "message": "本地日度数据已是最新，无需增量抓取。",
                        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "rows": {},
                    }
                )
            return

        start_date, end_date = sync_window
        sync_config = SyncConfig(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            db_path=LIBRARY_DATABASE,
            daily_basic=True,
            stock_basic=True,
        )
        _, daily_rows = sync_daily(sync_config)
        _, factor_rows = sync_factor_data(sync_config)
        with DATA_SYNC_LOCK:
            DATA_SYNC_STATUS.update(
                {
                    "state": "success",
                    "message": f"已同步 {start_date.isoformat()} 至 {end_date.isoformat()} 的市场数据。",
                    "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "rows": {"daily": daily_rows, **factor_rows},
                }
            )
    except Exception as exc:
        with DATA_SYNC_LOCK:
            DATA_SYNC_STATUS.update(
                {
                    "state": "error",
                    "message": f"同步失败：{exc}",
                    "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )


def start_data_sync() -> tuple[dict[str, object], bool]:
    with DATA_SYNC_LOCK:
        if DATA_SYNC_STATUS.get("state") == "running":
            return dict(DATA_SYNC_STATUS), False
        DATA_SYNC_STATUS.update(
            {
                "state": "running",
                "message": "正在同步个股日线、估值与股票基础信息。",
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "finished_at": None,
                "rows": {},
            }
        )
        status = dict(DATA_SYNC_STATUS)

    Thread(target=run_data_sync, name="ir-data-sync", daemon=True).start()
    return status, True


def database_tables() -> list[dict[str, object]]:
    if not LIBRARY_DATABASE.is_file():
        return []
    tables: list[dict[str, object]] = []
    with sqlite3.connect(LIBRARY_DATABASE) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        for row in rows:
            table_name = str(row[0])
            if table_name in HIDDEN_UI_TABLES:
                continue
            quoted_table = safe_table_name(table_name)
            columns = [str(item[1]) for item in connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()]
            row_count = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
            if row_count == 0:
                continue
            latest_sync, latest_data = table_latest_date(connection, table_name, columns)
            tables.append(
                {
                    "name": table_name,
                    "label": TABLE_LABELS.get(table_name, table_name),
                    "rows": row_count,
                    "latest_sync": latest_sync,
                    "latest_data": latest_data,
                    "columns": columns,
                }
            )
    return tables


def database_preview(table_name: str, limit: int = 12) -> dict[str, object]:
    if not LIBRARY_DATABASE.is_file():
        raise FileNotFoundError("尚未找到集中数据层中的 SQLite 数据库")
    quoted_table = safe_table_name(table_name)
    with sqlite3.connect(LIBRARY_DATABASE) as connection:
        cursor = connection.execute(f"SELECT * FROM {quoted_table} LIMIT ?", (max(1, min(limit, 100)),))
        columns = [item[0] for item in cursor.description]
        rows = []
        for row in cursor.fetchall():
            rows.append([format_cell(value) for value in row])
        latest_sync, latest_data = table_latest_date(connection, table_name, columns)
    return {
        "name": table_name,
        "label": TABLE_LABELS.get(table_name, table_name),
        "columns": columns,
        "rows": rows,
        "latest_sync": latest_sync,
        "latest_data": latest_data,
    }


def format_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    return f"{text[:177]}…" if len(text) > 180 else text


def wiki_records() -> list[dict[str, object]]:
    wiki_directory = WIKI_ROOT / "wiki"
    if not wiki_directory.is_dir():
        return []
    records: list[dict[str, object]] = []
    for path in wiki_directory.rglob("*.md"):
        relative = path.relative_to(wiki_directory)
        parts = relative.parts
        domain = parts[0] if parts and parts[0] in DOMAIN_LABELS else "other"
        subject = parts[1] if len(parts) > 2 else path.stem
        records.append(
            {
                "id": hashlib_sha(str(relative)),
                "path": str(path.relative_to(PROJECT_ROOT)),
                "domain": domain,
                "subject": subject,
                "title": path.stem,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            }
        )
    return sorted(records, key=lambda item: str(item["updated_at"]), reverse=True)


def hashlib_sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def wiki_preview(record_id: str) -> dict[str, object]:
    for record in wiki_records():
        if record["id"] != record_id:
            continue
        path = PROJECT_ROOT / str(record["path"])
        return {"content": path.read_text(encoding="utf-8", errors="replace")[:160000], "path": record["path"]}
    raise FileNotFoundError("未找到 Wiki 页面")


class ResearchHubHandler(BaseHTTPRequestHandler):
    server_version = "IRResearchHub/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/overview":
                self.handle_overview()
            elif parsed.path == "/api/records":
                self.handle_records(parse_qs(parsed.query))
            elif parsed.path.startswith("/api/records/") and parsed.path.endswith("/preview"):
                self.handle_record_preview(parsed.path.split("/")[3])
            elif parsed.path == "/api/wiki-records":
                json_response(self, HTTPStatus.OK, {"records": wiki_records()})
            elif parsed.path.startswith("/api/wiki-records/") and parsed.path.endswith("/preview"):
                json_response(self, HTTPStatus.OK, wiki_preview(parsed.path.split("/")[3]))
            elif parsed.path == "/api/data/tables":
                json_response(self, HTTPStatus.OK, {"database_path": str(LIBRARY_DATABASE.relative_to(PROJECT_ROOT)), "tables": database_tables()})
            elif parsed.path == "/api/data/sync":
                json_response(self, HTTPStatus.OK, {"sync": data_sync_status()})
            elif parsed.path.startswith("/api/data/tables/"):
                json_response(self, HTTPStatus.OK, database_preview(unquote(parsed.path.rsplit("/", 1)[-1])))
            elif parsed.path == "/api/profile":
                json_response(self, HTTPStatus.OK, get_profile())
            elif parsed.path == "/api/settings":
                self.handle_settings()
            else:
                self.serve_static(parsed.path)
        except FileNotFoundError as exc:
            json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, sqlite3.Error) as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/records/") and parsed.path.endswith("/wiki-queue"):
                record = enqueue_wiki_ingest(parsed.path.split("/")[3])
                json_response(self, HTTPStatus.OK, {"record": record, "message": "已加入待沉淀队列，原件已复制到 Wiki Raw。"})
            elif parsed.path.startswith("/api/records/") and parsed.path.endswith("/trash"):
                result = move_record_to_trash(parsed.path.split("/")[3])
                json_response(self, HTTPStatus.OK, {"message": "资料已移至集中数据层回收区。", **result})
            elif parsed.path == "/api/profile":
                json_response(self, HTTPStatus.OK, save_profile(read_request_json(self)))
            elif parsed.path == "/api/settings":
                self.save_settings(read_request_json(self))
            elif parsed.path == "/api/data/sync":
                status, started = start_data_sync()
                json_response(
                    self,
                    HTTPStatus.ACCEPTED if started else HTTPStatus.OK,
                    {"sync": status, "started": started},
                )
            else:
                json_response(self, HTTPStatus.NOT_FOUND, {"error": "未找到接口"})
        except FileNotFoundError as exc:
            json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/records/") and parsed.path.endswith("/wiki-queue"):
                result = cancel_wiki_ingest(parsed.path.split("/")[3])
                message = "已取消待沉淀队列。"
                if result["raw_removed"]:
                    message = "已取消待沉淀队列，并移除本次创建的 Wiki Raw 副本。"
                json_response(self, HTTPStatus.OK, {"message": message, **result})
            else:
                json_response(self, HTTPStatus.NOT_FOUND, {"error": "未找到接口"})
        except (OSError, ValueError) as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def handle_overview(self) -> None:
        records = list_records()
        reports = list_reports()
        visible_records = [*reports, *records]
        table_data = database_tables()
        latest_sync = max((str(table["latest_sync"]) for table in table_data if table.get("latest_sync")), default=None)
        by_domain = {domain: sum(record["domain"] == domain for record in visible_records) for domain in DOMAIN_LABELS}
        by_kind = {kind: sum(record["kind"] == kind for record in records) for kind in KIND_LABELS}
        json_response(
            self,
            HTTPStatus.OK,
            {
                "records": len(records),
                "temporary_sources": by_kind["temporary_source"],
                "reports": len(reports),
                "wiki_pages": len(wiki_records()),
                "latest_sync": latest_sync,
                "by_domain": by_domain,
                "database_tables": len(table_data),
            },
        )

    def handle_records(self, query: dict[str, list[str]]) -> None:
        domain = query.get("domain", [""])[0]
        kind = query.get("kind", [""])[0]
        search = query.get("search", [""])[0].strip().lower()
        records = []
        for record in list_visible_records():
            if domain and record["domain"] != domain:
                continue
            if kind and record["kind"] != kind:
                continue
            searchable = " ".join(str(record.get(key, "")) for key in ("title", "subject", "research_type", "path")).lower()
            if search and search not in searchable:
                continue
            records.append(record)
        json_response(self, HTTPStatus.OK, {"records": records, "labels": {"domains": DOMAIN_LABELS, "kinds": KIND_LABELS}})

    def handle_record_preview(self, record_id: str) -> None:
        record = get_record(record_id)
        if record is None:
            raise FileNotFoundError("未找到该资料")
        json_response(self, HTTPStatus.OK, {"record": record, "preview": record_preview(record)})

    def handle_settings(self) -> None:
        values = read_env_values()
        json_response(
            self,
            HTTPStatus.OK,
            {
                "path": ".env",
                "fields": [
                    {"key": key, "has_value": bool(values.get(key)), "secret": key in SECRET_ENV_KEYS}
                    for key in COMMON_ENV_KEYS
                ],
            },
        )

    def save_settings(self, payload: dict[str, object]) -> None:
        updates = payload.get("updates", {})
        if not isinstance(updates, dict):
            raise ValueError("updates 必须是对象")
        clean_updates = {
            key: str(value).strip()
            for key, value in updates.items()
            if key in COMMON_ENV_KEYS and isinstance(value, str)
        }
        update_env_values(clean_updates)
        self.handle_settings()

    def serve_static(self, request_path: str) -> None:
        index_path = WEB_DIST / "index.html"
        if not index_path.is_file():
            body = "<h1>前端尚未构建</h1><p>请先运行 npm install && npm run build，再重新启动服务。</p>".encode("utf-8")
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        relative = request_path.lstrip("/") or "index.html"
        candidate = (WEB_DIST / relative).resolve()
        if not str(candidate).startswith(str(WEB_DIST.resolve())) or not candidate.is_file():
            candidate = index_path
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        content = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the local IR research hub.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local hub in the default browser.")
    args = parser.parse_args()
    address = f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), ResearchHubHandler)
    print(f"IR Research Hub is available at {address}")
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
