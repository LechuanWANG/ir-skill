from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_library as library


class WikiQueueRawCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.report_root = self.root / "report"
        self.library_root = self.root / "data" / "research-library"
        self.library_files = self.library_root / "files"
        self.wiki_root = self.root / "docs" / "investment-llm-wiki"
        self.patchers = [
            patch.object(library, "PROJECT_ROOT", self.root),
            patch.object(library, "REPORT_ROOT", self.report_root),
            patch.object(library, "LIBRARY_ROOT", self.library_root),
            patch.object(library, "LIBRARY_FILES", self.library_files),
            patch.object(library, "LIBRARY_DATABASE", self.library_root / "database" / "investment_research.sqlite"),
            patch.object(library, "CATALOG_PATH", self.library_root / "catalog.json"),
            patch.object(library, "WIKI_QUEUE_PATH", self.library_root / "wiki-ingest-queue.json"),
            patch.object(library, "PROFILE_PATH", self.library_root / "settings" / "investor-profile.json"),
            patch.object(library, "TRASH_ROOT", self.library_root / "trash"),
            patch.object(library, "STAGING_ROOT", self.library_root / "staging"),
            patch.object(library, "WIKI_ROOT", self.wiki_root),
            patch.object(library, "WIKI_RAW_ROOT", self.wiki_root / "raw"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        library.ensure_library()
        self.source = self.library_files / "company" / "示例公司" / "公告" / "2026-07-16" / "半年度业绩预告.pdf"
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_bytes(b"immutable source material")
        self.record = {
            "id": "example-record",
            "path": str(self.source.relative_to(self.library_root)),
            "domain": "company",
            "subject": "示例公司",
            "category": "公告",
            "date": "2026-07-16",
            "kind": "temporary_source",
            "title": "半年度业绩预告",
            "extension": "pdf",
            "size": self.source.stat().st_size,
            "updated_at": library.now_iso(),
            "origin": "test",
        }
        library.save_catalog([self.record])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_enqueue_copies_to_raw_and_cancel_removes_created_copy(self) -> None:
        library.enqueue_wiki_ingest(self.record["id"])
        queue = library.read_json(library.WIKI_QUEUE_PATH, {"items": []})
        item = queue["items"][0]
        raw_path = self.root / item["raw_path"]

        self.assertTrue(raw_path.is_file())
        self.assertEqual(raw_path.read_bytes(), self.source.read_bytes())
        self.assertTrue(item["raw_created"])
        self.assertTrue(self.source.is_file())

        result = library.cancel_wiki_ingest(self.record["id"])

        self.assertTrue(result["raw_removed"])
        self.assertFalse(raw_path.exists())
        self.assertTrue(self.source.is_file())
        self.assertEqual(library.read_json(library.WIKI_QUEUE_PATH, {"items": []})["items"], [])

    def test_cancel_preserves_existing_raw_copy(self) -> None:
        raw_path = self.wiki_root / "raw" / "company" / "示例公司" / "2026-07-16" / self.source.name
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(self.source.read_bytes())

        library.enqueue_wiki_ingest(self.record["id"])
        result = library.cancel_wiki_ingest(self.record["id"])

        self.assertFalse(result["raw_removed"])
        self.assertTrue(raw_path.is_file())

    def test_reports_are_read_from_the_dedicated_report_folder(self) -> None:
        report = self.report_root / "company" / "示例公司" / "示例研究报告-2026-07-16.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "---\n"
            "title: 示例研究报告\n"
            "domain: company\n"
            "subject: 示例公司\n"
            "as_of: 2026-07-16\n"
            "---\n\n"
            "# 示例研究报告\n",
            encoding="utf-8",
        )

        records = library.list_reports()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["storage"], "report")
        self.assertEqual(records[0]["path"], "company/示例公司/示例研究报告-2026-07-16.md")
        self.assertEqual(library.record_preview(records[0])["kind"], "text")

    def test_system_metadata_is_excluded_from_reports_and_catalog(self) -> None:
        report_metadata = self.report_root / "market" / ".DS_Store"
        report_metadata.parent.mkdir(parents=True, exist_ok=True)
        report_metadata.write_bytes(b"finder metadata")
        library_metadata = self.library_files / "company" / "示例公司" / "公告" / ".DS_Store"
        library_metadata.parent.mkdir(parents=True, exist_ok=True)
        library_metadata.write_bytes(b"finder metadata")
        metadata_record = {
            **self.record,
            "id": "finder-metadata",
            "path": str(library_metadata.relative_to(self.library_root)),
            "title": ".DS_Store",
            "extension": "",
        }
        library.save_catalog([self.record, metadata_record])

        self.assertEqual(library.list_reports(), [])
        self.assertEqual([record["id"] for record in library.list_records()], [self.record["id"]])

    def test_curation_removes_system_metadata_from_temporary_sources(self) -> None:
        source_dir = self.library_files / "company" / "示例公司" / "2026-07-16" / "temporary_source"
        source_dir.mkdir(parents=True, exist_ok=True)
        metadata = source_dir / ".DS_Store"
        metadata.write_bytes(b"finder metadata")

        summary = library.curate_temporary_sources(apply=True)

        self.assertEqual(summary["system_metadata_files"], 1)
        self.assertEqual(summary["system_metadata_files_removed"], 1)
        self.assertFalse(metadata.exists())

    def test_report_list_displays_archive_date_without_losing_market_as_of(self) -> None:
        report = self.report_root / "market" / "2026-07-19" / "2026-07-19-日期分离测试.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "---\n"
            "title: 日期分离测试\n"
            "domain: market\n"
            "subject: A股\n"
            "as_of: 2026-07-17\n"
            "archived_on: 2026-07-19\n"
            "---\n\n"
            "# 日期分离测试\n",
            encoding="utf-8",
        )

        record = library.report_record_from_path(report)

        self.assertEqual(record["date"], "2026-07-19")
        self.assertEqual(record["as_of"], "2026-07-17")

    def test_report_migration_removes_library_catalog_entry(self) -> None:
        legacy_report = self.library_files / "company" / "示例公司" / "研究报告" / "示例研究报告-2026-07-16.md"
        legacy_report.parent.mkdir(parents=True, exist_ok=True)
        legacy_report.write_text("# 示例研究报告\n", encoding="utf-8")
        legacy_record = {
            "id": "legacy-report",
            "path": str(legacy_report.relative_to(self.library_root)),
            "domain": "company",
            "subject": "示例公司",
            "category": "研究报告",
            "date": "2026-07-16",
            "kind": "report",
            "title": "示例研究报告",
            "extension": "md",
            "size": legacy_report.stat().st_size,
            "updated_at": library.now_iso(),
            "origin": "test",
        }
        library.save_catalog([self.record, legacy_record])

        summary = library.migrate_report_storage(apply=True)

        self.assertEqual(summary["migrated"], 1)
        self.assertFalse(legacy_report.exists())
        self.assertTrue((self.report_root / "company" / "示例公司" / legacy_report.name).is_file())
        self.assertEqual([record["id"] for record in library.load_catalog()], [self.record["id"]])

    def test_daily_market_query_is_removed_from_source_archive(self) -> None:
        query_file = self.library_files / "market" / "沪深A股" / "交易制度" / "交易日历-2026-07-16.md"
        query_file.parent.mkdir(parents=True, exist_ok=True)
        query_file.write_text("临时查询结果\n", encoding="utf-8")
        query_record = {
            "id": "daily-query",
            "path": str(query_file.relative_to(self.library_root)),
            "domain": "market",
            "subject": "沪深A股",
            "category": "交易制度",
            "date": "2026-07-16",
            "kind": "source_markdown",
            "title": "交易日历",
            "extension": "md",
            "size": query_file.stat().st_size,
            "updated_at": library.now_iso(),
            "origin": "test",
        }
        library.save_catalog([self.record, query_record])

        summary = library.cleanup_low_reuse_query_artifacts(apply=True)

        self.assertEqual(summary["removed"], 1)
        self.assertFalse(query_file.exists())
        self.assertEqual([record["id"] for record in library.load_catalog()], [self.record["id"]])

    def test_catalog_write_rebuilds_the_agent_facing_files_index(self) -> None:
        index_path = self.library_files / library.FILES_INDEX_NAME

        content = index_path.read_text(encoding="utf-8")

        self.assertIn("# 研究资料库索引", content)
        self.assertIn("Agent 的历史资料入口", content)
        self.assertIn("个股 / 示例公司 / 公告", content)
        self.assertIn("[半年度业绩预告](company/示例公司/公告/2026-07-16/半年度业绩预告.pdf)", content)


class ResearchTaskStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.library_root = self.root / "data" / "research-library"
        self.staging_root = self.library_root / "staging"
        self.patchers = [
            patch.object(library, "PROJECT_ROOT", self.root),
            patch.object(library, "REPORT_ROOT", self.root / "report"),
            patch.object(library, "LIBRARY_ROOT", self.library_root),
            patch.object(library, "LIBRARY_FILES", self.library_root / "files"),
            patch.object(library, "LIBRARY_DATABASE", self.library_root / "database" / "investment_research.sqlite"),
            patch.object(library, "CATALOG_PATH", self.library_root / "catalog.json"),
            patch.object(library, "PROFILE_PATH", self.library_root / "settings" / "investor-profile.json"),
            patch.object(library, "TRASH_ROOT", self.library_root / "trash"),
            patch.object(library, "STAGING_ROOT", self.staging_root),
            patch.object(library, "WIKI_ROOT", self.root / "docs" / "investment-llm-wiki"),
            patch.object(library, "WIKI_RAW_ROOT", self.root / "docs" / "investment-llm-wiki" / "raw"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        library.ensure_library()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_init_preserves_existing_free_form_state_and_never_overwrites_task(self) -> None:
        task_root = self.staging_root / "event-map"
        task_root.mkdir(parents=True)
        state_path = task_root / library.RESEARCH_STATE_FILE
        free_form = "事件窗口 -> 风险偏好 -> 电子行业 -> 候选A\n\n当前反证：成交未确认。\n"
        state_path.write_text(free_form, encoding="utf-8")

        metadata = library.init_research_task("event-map", title="事件驱动候选")

        self.assertEqual(metadata["revision"], 0)
        self.assertEqual(state_path.read_text(encoding="utf-8"), free_form)
        with self.assertRaises(FileExistsError):
            library.init_research_task("event-map", title="覆盖标题")
        self.assertEqual(state_path.read_text(encoding="utf-8"), free_form)

    def test_task_id_uses_the_same_normalization_as_staging_directories(self) -> None:
        metadata = library.init_research_task(" macro/event ")

        self.assertEqual(metadata["task_id"], "macro-event")
        self.assertEqual(library.load_research_task("macro/event")["task_id"], "macro-event")

    def test_checkpoint_accepts_arbitrary_markdown_and_rejects_empty_state(self) -> None:
        library.init_research_task("single-stock", title="单股核验")
        state_path = self.staging_root / "single-stock" / library.RESEARCH_STATE_FILE
        state_path.write_text("只有一段叙述也可以；下一步核验公告原文。\n", encoding="utf-8")

        metadata = library.checkpoint_research_task("single-stock", status="blocked")

        self.assertEqual(metadata["revision"], 1)
        self.assertEqual(metadata["status"], "blocked")
        self.assertFalse((self.staging_root / "single-stock" / "task-state.json.tmp").exists())
        state_path.write_text("\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不存在或为空"):
            library.checkpoint_research_task("single-stock")

    def test_lifecycle_metadata_can_still_be_read_when_state_document_is_broken(self) -> None:
        library.init_research_task("broken-state", title="待修复状态")
        state_path = self.staging_root / "broken-state" / library.RESEARCH_STATE_FILE
        state_path.write_text("", encoding="utf-8")

        metadata = library.load_research_task("broken-state", require_state=False)

        self.assertEqual(metadata["status"], "active")
        with self.assertRaisesRegex(ValueError, "不存在或为空"):
            library.load_research_task("broken-state")

    def test_fresh_process_can_load_checkpointed_state(self) -> None:
        library.init_research_task("resume-me", title="跨进程恢复")
        state_path = self.staging_root / "resume-me" / library.RESEARCH_STATE_FILE
        state_path.write_text("已核验来源在 raw/source.md；下一步检查数据日期。\n", encoding="utf-8")
        library.checkpoint_research_task("resume-me")
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'scripts')!r})\n"
            "import research_library as lib\n"
            f"lib.STAGING_ROOT = Path({str(self.staging_root)!r})\n"
            "print(json.dumps(lib.load_research_task('resume-me'), ensure_ascii=False))\n"
        )

        result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
        loaded = json.loads(result.stdout)

        self.assertEqual(loaded["task_id"], "resume-me")
        self.assertEqual(loaded["revision"], 1)

    def test_list_returns_multiple_active_tasks_without_merging(self) -> None:
        library.init_research_task("candidate-a", title="候选比较 A")
        library.init_research_task("candidate-b", title="候选比较 B")

        tasks = library.list_research_tasks(statuses={"active", "blocked"})

        self.assertEqual({task["task_id"] for task in tasks}, {"candidate-a", "candidate-b"})
        self.assertEqual(len(tasks), 2)

    def test_archive_preserves_research_state_until_explicit_completion_and_cleanup(self) -> None:
        library.init_research_task("archive-and-resume", title="归档后继续")
        task_root = self.staging_root / "archive-and-resume"
        raw_path = task_root / "raw" / "empty-page.html"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text("navigation only", encoding="utf-8")
        (task_root / "archive-plan.json").write_text(
            json.dumps(
                {
                    "documents": [],
                    "discard_files": [
                        {"source_file": "raw/empty-page.html", "reason": "页面只有导航，没有研究正文"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        library.archive_staged_task("archive-and-resume", apply=True)

        self.assertTrue((task_root / library.RESEARCH_TASK_STATE_FILE).is_file())
        self.assertTrue((task_root / library.RESEARCH_STATE_FILE).is_file())
        self.assertEqual(library.load_research_task("archive-and-resume")["status"], "active")

    def test_complete_archives_every_raw_source_and_removes_its_staging_directory(self) -> None:
        library.init_research_task("complete-and-archive", title="完成后归档")
        task_root = self.staging_root / "complete-and-archive"
        raw_path = task_root / "raw" / "annual-report.pdf"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(b"%PDF-1.7\noriginal disclosure")
        (task_root / "archive-plan.json").write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "domain": "company",
                            "subject": "归档测试公司",
                            "category": "定期报告",
                            "title": "2025年年度报告要点",
                            "as_of": "2026-07-17",
                            "content": "已人工审阅原始年报并记录关键事实。",
                            "source_files": ["raw/annual-report.pdf"],
                        }
                    ],
                    "discard_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(library, "current_archive_date", return_value="2026-07-19"):
            result = library.complete_research_task("complete-and-archive")

        self.assertEqual(result["task_state"]["status"], "completed")
        self.assertEqual(result["archive"]["pdf_sources_archived"], 1)
        self.assertTrue(result["staging_cleanup"]["task_directory_removed"])
        self.assertFalse(raw_path.exists())
        self.assertFalse(task_root.exists())
        archived_pdfs = list((self.library_root / "files").rglob("*.pdf"))
        self.assertEqual(len(archived_pdfs), 1)
        self.assertEqual(archived_pdfs[0].read_bytes(), b"%PDF-1.7\noriginal disclosure")
        self.assertIn("2026-07-19", archived_pdfs[0].name)
        archived_document = next(
            path
            for path in (self.library_root / "files").rglob("*.md")
            if path.name != library.FILES_INDEX_NAME
        )
        metadata = library.parse_frontmatter(archived_document)
        self.assertEqual(metadata["as_of"], "2026-07-17")
        self.assertEqual(metadata["archived_on"], "2026-07-19")

    def test_complete_refuses_unplanned_raw_sources_and_keeps_task_active(self) -> None:
        library.init_research_task("unplanned-completion", title="未规划资料不能完成")
        task_root = self.staging_root / "unplanned-completion"
        raw_path = task_root / "raw" / "unplanned.pdf"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(b"%PDF-1.7\nunplanned source")

        with self.assertRaisesRegex(ValueError, "archive-plan.json 至少需要"):
            library.complete_research_task("unplanned-completion")

        self.assertEqual(library.load_research_task("unplanned-completion")["status"], "active")
        self.assertTrue(raw_path.is_file())

    def test_archive_rejects_a_market_date_in_archived_on(self) -> None:
        document = {
            "domain": "company",
            "subject": "日期分离测试",
            "category": "公告",
            "title": "公告摘要",
            "as_of": "2026-07-17",
            "archived_on": "2026-07-17",
            "content": "已人工审阅公告原件并记录可复用事实。",
            "source_files": ["raw/release.html"],
        }

        with patch.object(library, "current_archive_date", return_value="2026-07-19"):
            with self.assertRaisesRegex(ValueError, "执行归档当天"):
                library.normalized_plan_document("date-separation", document)

    def test_archive_rejects_any_uncovered_raw_source(self) -> None:
        library.init_research_task("uncovered-source", title="遗漏来源")
        task_root = self.staging_root / "uncovered-source"
        raw_root = task_root / "raw"
        raw_root.mkdir(parents=True)
        (raw_root / "keep.pdf").write_bytes(b"%PDF-1.7\nkeep")
        (raw_root / "unplanned.html").write_text("unplanned", encoding="utf-8")
        (task_root / "archive-plan.json").write_text(
            json.dumps(
                {
                    "documents": [
                        {
                            "domain": "company",
                            "subject": "遗漏来源测试",
                            "category": "定期报告",
                            "title": "保留 PDF",
                            "as_of": "2026-07-17",
                            "content": "保留原始披露。",
                            "source_files": ["raw/keep.pdf"],
                        }
                    ],
                    "discard_files": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "必须覆盖 raw/ 下所有文件"):
            library.archive_staged_task("uncovered-source", apply=True)
        self.assertTrue((raw_root / "keep.pdf").is_file())
        self.assertTrue((raw_root / "unplanned.html").is_file())

    def test_cleanup_only_removes_due_state_and_working_files(self) -> None:
        library.init_research_task("finished", title="已完成研究", retention_days=0)
        task_root = self.staging_root / "finished"
        working_file = task_root / "working" / "temporary.csv"
        raw_file = task_root / "raw" / "source.pdf"
        archive_plan = task_root / "archive-plan.json"
        working_file.parent.mkdir(parents=True)
        raw_file.parent.mkdir(parents=True)
        working_file.write_text("temporary", encoding="utf-8")
        raw_file.write_bytes(b"source")
        archive_plan.write_text('{"documents": [], "discard_files": []}\n', encoding="utf-8")
        database = self.library_root / "database" / "investment_research.sqlite"
        database.parent.mkdir(parents=True, exist_ok=True)
        database.write_bytes(b"sqlite")
        report = self.root / "report" / "company" / "example" / "final.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("final", encoding="utf-8")
        completed = library.finish_research_task("finished", status="completed")
        after_deadline = datetime.fromisoformat(completed["cleanup_after"]) + timedelta(seconds=1)

        preview = library.cleanup_research_task_states(task_id="finished", apply=False, current_time=after_deadline)

        self.assertEqual(preview["eligible"][0]["task_id"], "finished")
        self.assertTrue((task_root / library.RESEARCH_TASK_STATE_FILE).is_file())
        library.cleanup_research_task_states(task_id="finished", apply=True, current_time=after_deadline)
        self.assertFalse((task_root / library.RESEARCH_TASK_STATE_FILE).exists())
        self.assertFalse((task_root / library.RESEARCH_STATE_FILE).exists())
        self.assertFalse((task_root / "working").exists())
        self.assertTrue(raw_file.is_file())
        self.assertTrue(archive_plan.is_file())
        self.assertTrue(database.is_file())
        self.assertTrue(report.is_file())

    def test_cleanup_does_not_remove_active_or_not_due_tasks(self) -> None:
        library.init_research_task("active", title="仍在研究")
        active_result = library.cleanup_research_task_states(task_id="active", apply=True)
        self.assertEqual(active_result["not_due"][0]["reason"], "任务尚未结束")
        self.assertTrue((self.staging_root / "active" / library.RESEARCH_TASK_STATE_FILE).is_file())

        library.init_research_task("recent", title="刚完成研究", retention_days=7)
        completed = library.finish_research_task("recent", status="completed")
        before_deadline = datetime.fromisoformat(completed["cleanup_after"]) - timedelta(days=1)
        recent_result = library.cleanup_research_task_states(task_id="recent", apply=True, current_time=before_deadline)
        self.assertEqual(recent_result["not_due"][0]["reason"], "仍在恢复保留期")
        self.assertTrue((self.staging_root / "recent" / library.RESEARCH_TASK_STATE_FILE).is_file())

if __name__ == "__main__":
    unittest.main()
