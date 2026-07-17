#!/usr/bin/env python3
"""Prepare task-local source text and archive Agent-authored research documents."""

from __future__ import annotations

import argparse
import json

from research_library import archive_staged_task, cleanup_low_reuse_query_artifacts, migrate_legacy_layout, refresh_pdf_text_archives, write_files_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage task staging and semantic research archival.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive_parser = subparsers.add_parser("archive", help="Apply the Agent-authored archive-plan.json and only perform validated file operations.")
    archive_parser.add_argument("--task", required=True, help="Task staging folder below data/research-library/staging/")
    archive_parser.add_argument("--apply", action="store_true", help="Write archive documents and clear covered intermediate files.")

    legacy_parser = subparsers.add_parser("migrate-layout", help="Move existing date-folder material into reusable topic folders.")
    legacy_parser.add_argument("--apply", action="store_true", help="Move files and write extracted text. Without this flag, print a plan.")

    cleanup_parser = subparsers.add_parser("clean-query-artifacts", help="Remove daily market-query exports that belong in SQLite rather than the source archive.")
    cleanup_parser.add_argument("--apply", action="store_true", help="Delete identified low-reuse query files and remove their catalog entries.")

    refresh_pdf_parser = subparsers.add_parser("refresh-pdf-text", help="Replace legacy automated PDF text with Agent visual-transcription cards.")
    refresh_pdf_parser.add_argument("--apply", action="store_true", help="Rewrite matching PDF text archives. Without this flag, print a plan.")

    subparsers.add_parser("rebuild-files-index", help="Rebuild files/INDEX.md, the agent-facing entry point for authorized research reuse.")
    args = parser.parse_args()
    if args.command == "archive":
        result = archive_staged_task(args.task, apply=args.apply)
    elif args.command == "refresh-pdf-text":
        result = refresh_pdf_text_archives(apply=args.apply)
    elif args.command == "clean-query-artifacts":
        result = cleanup_low_reuse_query_artifacts(apply=args.apply)
    elif args.command == "rebuild-files-index":
        result = write_files_index()
    else:
        result = migrate_legacy_layout(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
