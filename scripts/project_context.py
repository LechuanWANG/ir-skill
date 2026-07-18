#!/usr/bin/env python3
"""Resolve project-scoped paths without writing user state into the Skill package."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_DIR_ENV = "IR_SKILL_PROJECT_DIR"
SKILL_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ProjectPaths:
    """Canonical locations for user-owned IR Skill state within one project."""

    root: Path
    env_path: Path
    report_root: Path
    library_root: Path
    library_files: Path
    staging_root: Path
    database_path: Path
    settings_root: Path
    trash_root: Path
    wiki_root: Path
    wiki_raw_root: Path


def resolve_project_root(
    project_dir: Path | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Use an explicit path, then the project environment variable, then the cwd."""

    source = os.environ if environ is None else environ
    candidate = project_dir or source.get(PROJECT_DIR_ENV, "").strip() or cwd or Path.cwd()
    root = Path(candidate).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project directory does not exist or is not a directory: {root}")
    return root


def project_paths(
    project_dir: Path | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> ProjectPaths:
    """Return all paths owned by the selected user project."""

    root = resolve_project_root(project_dir, environ=environ, cwd=cwd)
    library_root = root / "data" / "research-library"
    wiki_root = root / "docs" / "investment-llm-wiki"
    return ProjectPaths(
        root=root,
        env_path=root / ".env",
        report_root=root / "report",
        library_root=library_root,
        library_files=library_root / "files",
        staging_root=library_root / "staging",
        database_path=library_root / "database" / "investment_research.sqlite",
        settings_root=library_root / "settings",
        trash_root=library_root / "trash",
        wiki_root=wiki_root,
        wiki_raw_root=wiki_root / "raw",
    )


def ensure_project_layout(paths: ProjectPaths) -> None:
    """Create the non-secret directories needed for IR research in one project."""

    for path in (
        paths.report_root,
        paths.library_files,
        paths.staging_root,
        paths.database_path.parent,
        paths.settings_root,
        paths.trash_root,
        paths.wiki_raw_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
