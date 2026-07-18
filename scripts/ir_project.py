#!/usr/bin/env python3
"""Initialize and inspect project-local IR Skill state using the current Python."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path
from typing import Sequence

from market_data_store import ensure_database
from project_context import PROJECT_DIR_ENV, ensure_project_layout, project_paths


# TuShare requests use the bundled HTTP transport, not the tushare Python package.
RUNTIME_REQUIREMENTS = ("pandas",)


def _runtime_status() -> list[dict[str, object]]:
    status: list[dict[str, object]] = []
    for package in RUNTIME_REQUIREMENTS:
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            status.append({"package": package, "available": False, "version": None})
        else:
            status.append({"package": package, "available": True, "version": version})
    return status


def _payload(paths, *, initialized: bool) -> dict[str, object]:
    return {
        "status": "initialized" if initialized else "ready" if paths.database_path.is_file() else "not_initialized",
        "project_dir": str(paths.root),
        "project_env_var": PROJECT_DIR_ENV,
        "data_root": str(paths.library_root),
        "database_path": str(paths.database_path),
        "env_path": str(paths.env_path),
        "report_root": str(paths.report_root),
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "dependencies": _runtime_status(),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize project-local IR storage and inspect the current Python runtime."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("init", "Create the project-local research layout and SQLite database"),
        ("status", "Show the selected project's IR storage and runtime status"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--project-dir", type=Path, required=True)
        if command == "init":
            command_parser.add_argument(
                "--import-db",
                type=Path,
                help="Copy an existing SQLite cache into an empty project database location",
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = project_paths(args.project_dir)
        if args.command == "status":
            print(json.dumps(_payload(paths, initialized=False), ensure_ascii=False, indent=2))
            return 0

        ensure_project_layout(paths)
        imported = False
        if args.import_db is not None:
            source = Path(args.import_db).expanduser().resolve()
            if not source.is_file():
                raise ValueError(f"Database to import does not exist: {source}")
            if paths.database_path.exists():
                raise ValueError(f"Project database already exists: {paths.database_path}")
            shutil.copy2(source, paths.database_path)
            imported = True
        if not imported:
            ensure_database(paths.database_path)
        payload = _payload(paths, initialized=True)
        payload["database_imported"] = imported
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
