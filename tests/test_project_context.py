from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ir_project import main
from project_context import PROJECT_DIR_ENV, ensure_project_layout, project_paths, resolve_project_root


class ProjectContextTests(unittest.TestCase):
    def test_explicit_project_path_precedes_environment_and_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "explicit"
            configured = root / "configured"
            current = root / "current"
            explicit.mkdir()
            configured.mkdir()
            current.mkdir()

            resolved = resolve_project_root(
                explicit,
                environ={PROJECT_DIR_ENV: str(configured)},
                cwd=current,
            )

            self.assertEqual(resolved, explicit.resolve())

    def test_layout_is_created_only_inside_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "research-project"
            root.mkdir()
            paths = project_paths(root)

            ensure_project_layout(paths)

            self.assertTrue(paths.library_files.is_dir())
            self.assertTrue(paths.staging_root.is_dir())
            self.assertTrue(paths.database_path.parent.is_dir())
            self.assertTrue(paths.report_root.is_dir())
            self.assertTrue(paths.wiki_raw_root.is_dir())
            self.assertFalse((root / ".ir-skill").exists())

    def test_initializer_creates_project_database_and_reports_existing_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "research-project"
            root.mkdir()
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["init", "--project-dir", str(root)])

            payload = json.loads(output.getvalue())
            database = root / "data" / "research-library" / "database" / "investment_research.sqlite"
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["project_dir"], str(root.resolve()))
            self.assertEqual(payload["database_path"], str(database.resolve()))
            self.assertTrue(database.is_file())
            self.assertTrue(payload["python"]["executable"])
            self.assertEqual({item["package"] for item in payload["python"]["dependencies"]}, {"pandas"})


if __name__ == "__main__":
    unittest.main()
