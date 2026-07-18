from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tushare_config import (
    TUSHARE_TOKEN_KEY,
    read_env_values,
    resolve_tushare_token,
    tushare_config_status,
    update_env_values,
)


class TushareConfigTests(unittest.TestCase):
    def test_resolves_explicit_project_env_file_without_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("TUSHARE_TOKEN=file-token\n", encoding="utf-8")

            resolved = resolve_tushare_token(environ={}, env_path=env_path)

            self.assertEqual(resolved.value, "file-token")
            self.assertEqual(resolved.source, "env_file")
            self.assertEqual(resolved.env_path, env_path.resolve())
            self.assertTrue(resolved.env_path.is_absolute())

    def test_process_environment_has_explicit_precedence_without_file_caching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("TUSHARE_TOKEN=file-token\n", encoding="utf-8")
            environment = {TUSHARE_TOKEN_KEY: "process-token"}

            resolved = resolve_tushare_token(environ=environment, env_path=env_path)

            self.assertEqual(resolved.value, "process-token")
            self.assertEqual(resolved.source, "process_environment")
            self.assertEqual(environment, {TUSHARE_TOKEN_KEY: "process-token"})

    def test_parser_supports_export_quotes_and_inline_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("export TUSHARE_TOKEN='quoted-token' # local only\n", encoding="utf-8")

            self.assertEqual(read_env_values(env_path)[TUSHARE_TOKEN_KEY], "quoted-token")

    def test_atomic_update_preserves_comments_and_returns_secret_safe_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("# local credentials\nOTHER=value\n", encoding="utf-8")

            update_env_values({TUSHARE_TOKEN_KEY: "new-token"}, env_path)
            status = tushare_config_status(environ={}, env_path=env_path)

            text = env_path.read_text(encoding="utf-8")
            self.assertIn("# local credentials", text)
            self.assertIn("OTHER=value", text)
            self.assertIn("TUSHARE_TOKEN=new-token", text)
            self.assertEqual(status["status"], "configured")
            self.assertNotIn("new-token", str(status))
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
