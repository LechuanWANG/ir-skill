from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_collect as collector
import research_library as library


class FakeResponse:
    def __init__(self, body: bytes, *, url: str, content_type: str, status: int = 200) -> None:
        self._body = io.BytesIO(body)
        self._url = url
        self.status = status
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def geturl(self) -> str:
        return self._url

    def getcode(self) -> int:
        return self.status


class ResearchCollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.library_root = self.root / "data" / "research-library"
        self.patchers = [
            patch.object(library, "PROJECT_ROOT", self.root),
            patch.object(library, "REPORT_ROOT", self.root / "report"),
            patch.object(library, "LIBRARY_ROOT", self.library_root),
            patch.object(library, "LIBRARY_FILES", self.library_root / "files"),
            patch.object(library, "LIBRARY_DATABASE", self.library_root / "database" / "investment_research.sqlite"),
            patch.object(library, "CATALOG_PATH", self.library_root / "catalog.json"),
            patch.object(library, "WIKI_QUEUE_PATH", self.library_root / "wiki-ingest-queue.json"),
            patch.object(library, "PROFILE_PATH", self.library_root / "settings" / "investor-profile.json"),
            patch.object(library, "TRASH_ROOT", self.library_root / "trash"),
            patch.object(library, "STAGING_ROOT", self.library_root / "staging"),
            patch.object(library, "WIKI_ROOT", self.root / "docs" / "investment-llm-wiki"),
            patch.object(library, "WIKI_RAW_ROOT", self.root / "docs" / "investment-llm-wiki" / "raw"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        library.ensure_library()
        library.init_research_task("collection-test", title="资料采集测试")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_collects_valid_pdf_to_raw_and_writes_review_card(self) -> None:
        response = FakeResponse(b"%PDF-1.7\nvalid report", url="https://exchange.example/report.pdf", content_type="application/pdf")

        result = collector.collect_source(task_id="collection-test", url="https://exchange.example/report.pdf", opener=lambda *_args, **_kwargs: response)

        self.assertEqual(result["status"], "collected")
        raw_path = Path(result["raw_path"])
        self.assertEqual(raw_path.read_bytes(), b"%PDF-1.7\nvalid report")
        self.assertIn("未执行 PDF 自动文字抽取", Path(result["review_path"]).read_text(encoding="utf-8"))
        metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_kind"], "pdf")
        self.assertEqual(metadata["raw_path"], "raw/report.pdf")

    def test_rejects_security_html_for_pdf_url_without_writing_raw_source(self) -> None:
        response = FakeResponse(b"<html><body>security challenge</body></html>", url="https://exchange.example/report.pdf", content_type="text/html")

        result = collector.collect_source(task_id="collection-test", url="https://exchange.example/report.pdf", opener=lambda *_args, **_kwargs: response)

        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.library_root / "staging" / "collection-test" / "raw").exists())
        failure = json.loads(Path(result["failure_path"]).read_text(encoding="utf-8"))
        self.assertIn("缺少 %PDF-", failure["reason"])
        self.assertEqual(failure["failure_type"], "source_access_challenge")

    def test_terminal_task_rejects_new_raw_source(self) -> None:
        library.complete_research_task("collection-test")
        response = FakeResponse(b"%PDF-1.7\nlate report", url="https://exchange.example/late-report.pdf", content_type="application/pdf")

        with self.assertRaisesRegex(ValueError, "已完成归档并清理"):
            collector.collect_source(task_id="collection-test", url="https://exchange.example/late-report.pdf", opener=lambda *_args, **_kwargs: response)

        task_root = self.library_root / "staging" / "collection-test"
        self.assertFalse(task_root.exists())

    def test_discovers_cninfo_original_reports_by_company_name_and_verifies_ticker(self) -> None:
        response = FakeResponse(
            json.dumps(
                {
                    "announcements": [
                        {"secCode": "000338", "announcementId": "annual", "announcementTitle": "2025年年度报告", "announcementTime": 1, "adjunctUrl": "finalpage/2026-03-27/annual.PDF"},
                        {"secCode": "000338", "announcementId": "summary", "announcementTitle": "2025年年度报告摘要", "announcementTime": 2, "adjunctUrl": "finalpage/2026-03-27/summary.PDF"},
                        {"secCode": "000001", "announcementId": "wrong", "announcementTitle": "2025年年度报告", "announcementTime": 3, "adjunctUrl": "finalpage/2026-03-27/wrong.PDF"},
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            url="http://www.cninfo.com.cn/new/hisAnnouncement/query",
            content_type="application/json",
        )
        requests = []

        result = collector.discover_cninfo_reports(
            symbol="000338",
            company_name="潍柴动力",
            start_date="2026-01-01",
            end_date="2026-07-17",
            report_type="annual",
            opener=lambda request, **_kwargs: (requests.append(request), response)[1],
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["reports"], [{"title": "2025年年度报告", "announcement_id": "annual", "announcement_time": 1, "source_url": "https://static.cninfo.com.cn/finalpage/2026-03-27/annual.PDF"}])
        self.assertIn("searchkey=%E6%BD%8D%E6%9F%B4%E5%8A%A8%E5%8A%9B", requests[0].data.decode("utf-8"))
        self.assertIn("stock=", requests[0].data.decode("utf-8"))
        self.assertIn("category=category_ndbg_szsh", requests[0].data.decode("utf-8"))

    def test_collect_report_falls_back_to_cninfo_after_exchange_returns_html(self) -> None:
        def opener(request: object, **_kwargs: object) -> FakeResponse:
            url = request.full_url
            if url == "https://exchange.example/report.pdf":
                return FakeResponse(b"<html><body>security challenge</body></html>", url=url, content_type="text/html")
            if url == collector.CNINFO_QUERY_URL:
                payload = {
                    "announcements": [
                        {
                            "secCode": "000338",
                            "announcementId": "annual",
                            "announcementTitle": "2025年年度报告",
                            "announcementTime": 1,
                            "adjunctUrl": "finalpage/2026-03-27/annual.PDF",
                        }
                    ],
                    "totalRecordNum": 1,
                }
                return FakeResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"), url=url, content_type="application/json")
            if url == "https://static.cninfo.com.cn/finalpage/2026-03-27/annual.PDF":
                return FakeResponse(b"%PDF-1.7\nannual report", url=url, content_type="application/pdf")
            raise AssertionError(f"unexpected URL: {url}")

        result = collector.collect_financial_report(
            task_id="collection-test",
            symbol="000338",
            company_name="潍柴动力",
            start_date="2026-01-01",
            end_date="2026-07-17",
            report_type="annual",
            primary_url="https://exchange.example/report.pdf",
            opener=opener,
        )

        self.assertEqual(result["status"], "collected")
        self.assertEqual(result["source"], "cninfo")
        self.assertEqual([attempt["source"] for attempt in result["attempts"]], ["primary", "cninfo"])
        self.assertEqual(result["attempts"][0]["failure_type"], "source_access_challenge")

    def test_matches_interim_and_third_quarter_reports(self) -> None:
        self.assertTrue(collector.cninfo_report_type_matches("2025年度报告", "annual"))
        self.assertTrue(collector.cninfo_report_type_matches("2025年半年度报告", "q2"))
        self.assertTrue(collector.cninfo_report_type_matches("2025年第三季度报告", "q3"))
        self.assertFalse(collector.cninfo_report_type_matches("2025年度报告摘要", "annual"))
        self.assertFalse(collector.cninfo_report_type_matches("2025年半年度报告摘要", "q2"))

    def test_collects_html_and_archives_agent_authored_summary(self) -> None:
        response = FakeResponse(
            b"<html><head><title>ignored</title><script>ignored()</script></head><body><h1>Official release</h1><p>Published fact.</p></body></html>",
            url="https://stats.example/release",
            content_type="text/html; charset=utf-8",
        )

        result = collector.collect_source(task_id="collection-test", url="https://stats.example/release", filename="official-release.html", opener=lambda *_args, **_kwargs: response)

        self.assertEqual(result["source_kind"], "html")
        review = Path(result["review_path"]).read_text(encoding="utf-8")
        self.assertIn("Official release", review)
        self.assertNotIn("ignored()", review)
        task_root = self.library_root / "staging" / "collection-test"
        (task_root / "archive-plan.json").write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "domain": "macro",
                            "subject": "官方统计",
                            "category": "统计数据",
                            "title": "官方发布摘要",
                            "as_of": "2026-07-17",
                            "content": "已人工审阅原始 HTML：页面发布一项可复用的官方统计事实。",
                            "source_files": ["raw/official-release.html"],
                        }
                    ],
                    "discard_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        summary = library.archive_staged_task("collection-test", apply=True)

        archived = self.library_root / "files" / "macro" / "官方统计" / "统计数据" / "官方发布摘要-2026-07-17.md"
        self.assertEqual(summary["documents_created_or_merged"], 1)
        self.assertTrue(archived.is_file())
        self.assertIn("https://stats.example/release", archived.read_text(encoding="utf-8"))
        self.assertFalse((task_root / "raw" / "official-release.html").exists())

    def test_renders_staged_pdf_pages_without_text_extraction(self) -> None:
        response = FakeResponse(b"%PDF-1.7\nvalid report", url="https://exchange.example/report.pdf", content_type="application/pdf")
        collected = collector.collect_source(task_id="collection-test", url="https://exchange.example/report.pdf", opener=lambda *_args, **_kwargs: response)
        task_root = self.library_root / "staging" / "collection-test"

        def fake_pdftoppm(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
            output_prefix = Path(args[-1])
            output_prefix.parent.mkdir(parents=True, exist_ok=True)
            output_prefix.with_name("page-1.png").write_bytes(b"png")
            return CompletedProcess(args, 0, "", "")

        with patch.object(collector.shutil, "which", return_value="/usr/local/bin/pdftoppm"), patch.object(collector.subprocess, "run", side_effect=fake_pdftoppm):
            result = collector.render_pdf_pages(task_id="collection-test", source_file="raw/report.pdf")

        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["first_page"], "working/pdf-pages/report/page-1.png")
        self.assertEqual(result["last_page"], "working/pdf-pages/report/page-1.png")
        self.assertEqual((task_root / result["first_page"]).read_bytes(), b"png")
        self.assertTrue(Path(collected["raw_path"]).is_file())

    def test_terminal_task_rejects_new_pdf_review_pages(self) -> None:
        response = FakeResponse(b"%PDF-1.7\nvalid report", url="https://exchange.example/report.pdf", content_type="application/pdf")
        collector.collect_source(task_id="collection-test", url="https://exchange.example/report.pdf", opener=lambda *_args, **_kwargs: response)
        task_root = self.library_root / "staging" / "collection-test"
        (task_root / "archive-plan.json").write_text(
            json.dumps(
                {
                    "documents": [],
                    "discard_files": [{"source_file": "raw/report.pdf", "reason": "测试终态不可再生成审阅页"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        library.complete_research_task("collection-test")

        with self.assertRaisesRegex(ValueError, "已完成归档并清理"):
            collector.render_pdf_pages(task_id="collection-test", source_file="raw/report.pdf")

        self.assertFalse(task_root.exists())


if __name__ == "__main__":
    unittest.main()
