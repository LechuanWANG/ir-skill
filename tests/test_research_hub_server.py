from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_data_store import ensure_database
import research_hub_server as hub
import research_library as library


class InMemoryResearchHubHandler(hub.ResearchHubHandler):
    """Drive the real handler without requiring a locally bindable test socket."""

    def __init__(self, path: str, payload: object | None = None) -> None:
        self.path = path
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.status: int | None = None

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        return

    def end_headers(self) -> None:
        return


class ResearchHubServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.library_root = self.root / "data" / "research-library"
        self.library_files = self.library_root / "files"
        self.database_path = self.library_root / "database" / "investment_research.sqlite"
        self.report_root = self.root / "report"
        self.wiki_root = self.root / "docs" / "investment-llm-wiki"
        self.watchlist_path = self.library_root / "tracking" / "research-watchlist.json"
        self.env_path = self.root / ".env"
        self.patchers = [
            patch.object(library, "PROJECT_ROOT", self.root),
            patch.object(library, "REPORT_ROOT", self.report_root),
            patch.object(library, "LIBRARY_ROOT", self.library_root),
            patch.object(library, "LIBRARY_FILES", self.library_files),
            patch.object(library, "LIBRARY_DATABASE", self.database_path),
            patch.object(library, "CATALOG_PATH", self.library_root / "catalog.json"),
            patch.object(library, "WIKI_QUEUE_PATH", self.library_root / "wiki-ingest-queue.json"),
            patch.object(library, "PROFILE_PATH", self.library_root / "settings" / "investor-profile.json"),
            patch.object(library, "TRASH_ROOT", self.library_root / "trash"),
            patch.object(library, "STAGING_ROOT", self.library_root / "staging"),
            patch.object(library, "WIKI_ROOT", self.wiki_root),
            patch.object(library, "WIKI_RAW_ROOT", self.wiki_root / "raw"),
            patch.object(hub, "PROJECT_ROOT", self.root),
            patch.object(hub, "LIBRARY_DATABASE", self.database_path),
            patch.object(hub, "WIKI_ROOT", self.wiki_root),
            patch.object(hub, "WATCHLIST_PATH", self.watchlist_path),
            patch.object(hub, "ENV_PATH", self.env_path),
            patch.object(hub, "WEB_DIST", self.root / "web-dist"),
            patch.object(hub, "DATA_SYNC_STATUS", {"state": "idle", "message": "test"}),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        library.ensure_library()
        ensure_database(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO a_share_daily "
                "(trade_date, ts_code, close_qfq, source, retrieved_at) "
                "VALUES ('2026-07-20', '000001.SZ', 10.5, 'test', '2026-07-20T12:00:00+08:00')"
            )
            connection.commit()

        source = self.library_files / "company" / "测试公司" / "公告" / "公告-2026-07-20.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# 测试公告\n", encoding="utf-8")
        library.save_catalog(
            [
                {
                    "id": "test-record",
                    "path": str(source.relative_to(self.library_root)),
                    "domain": "company",
                    "subject": "测试公司",
                    "category": "公告",
                    "date": "2026-07-20",
                    "kind": "source_markdown",
                    "title": "测试公告",
                    "extension": "md",
                    "size": source.stat().st_size,
                    "updated_at": library.now_iso(),
                    "origin": "test",
                }
            ]
        )
        self.addCleanup(self.temp_dir.cleanup)

    def request(self, path: str, *, method: str = "GET", payload: object | None = None) -> tuple[int, dict[str, object]]:
        handler = InMemoryResearchHubHandler(path, payload)
        getattr(handler, f"do_{method}")()
        self.assertIsNotNone(handler.status)
        return handler.status or 500, json.loads(handler.wfile.getvalue().decode("utf-8"))

    def test_overview_and_record_preview_use_project_local_assets(self) -> None:
        status, overview = self.request("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(overview["records"], 1)
        self.assertGreaterEqual(overview["database_tables"], 1)

        status, preview = self.request("/api/records/test-record/preview")
        self.assertEqual(status, 200)
        self.assertEqual(preview["record"]["title"], "测试公告")
        self.assertIn("测试公告", preview["preview"]["content"])

    def test_data_preview_rejects_invalid_table_names(self) -> None:
        status, payload = self.request("/api/data/tables/a_share_daily")
        self.assertEqual(status, 200)
        self.assertEqual(payload["rows"][0][1], "000001.SZ")

        status, payload = self.request("/api/data/tables/%2E%2E%2Fcatalog")
        self.assertEqual(status, 400)
        self.assertIn("无效的数据表", payload["error"])

    def test_profile_watchlist_and_settings_writes_are_sanitized(self) -> None:
        status, profile = self.request(
            "/api/profile",
            method="POST",
            payload={"holdings": [{"symbol": "600519.SH", "quantity": 10, "as_of": "2026-07-20"}]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(profile["holdings"][0]["symbol"], "600519.SH")

        status, watchlist = self.request(
            "/api/watchlist",
            method="POST",
            payload={"items": [{"symbol": "00700.HK", "research_path": "medium-term", "thesis": "等待证据"}]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(watchlist["items"][0]["symbol"], "00700.HK")

        status, settings = self.request("/api/settings", method="POST", payload={"updates": {"TUSHARE_TOKEN": "secret-value"}})
        self.assertEqual(status, 200)
        self.assertTrue(settings["fields"][0]["has_value"])
        self.assertNotIn("secret-value", json.dumps(settings, ensure_ascii=False))

    def test_unknown_api_path_returns_json_not_the_frontend_shell(self) -> None:
        status, payload = self.request("/api/not-found")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "未找到接口")
