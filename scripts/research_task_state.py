#!/usr/bin/env python3
"""Manage compact-resilient research task state without constraining its Markdown form."""

from __future__ import annotations

import argparse
import json
from typing import Any

from research_library import (
    RESEARCH_TASK_STATUSES,
    checkpoint_research_task,
    cleanup_research_task_states,
    complete_research_task,
    finish_research_task,
    init_research_task,
    list_research_tasks,
    load_research_task,
)


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage flexible research recovery state in task staging folders.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create lifecycle metadata and a minimally titled free-form Markdown state file.")
    init_parser.add_argument("--task", required=True, help="Task folder name below data/research-library/staging/.")
    init_parser.add_argument("--title", help="Human-readable research title; defaults to the task name.")
    init_parser.add_argument("--retention-days", type=int, default=7, help="Days to keep recovery state after completion or abandonment.")

    checkpoint_parser = subparsers.add_parser("checkpoint", help="Validate the Agent-written Markdown and advance its revision.")
    checkpoint_parser.add_argument("--task", required=True)
    checkpoint_parser.add_argument("--status", choices=("active", "blocked"), help="Optionally update the non-terminal lifecycle status.")

    status_parser = subparsers.add_parser("status", help="Read one task's validated lifecycle metadata.")
    status_parser.add_argument("--task", required=True)

    list_parser = subparsers.add_parser("list", help="List task metadata without choosing or merging a task automatically.")
    list_parser.add_argument("--status", action="append", choices=sorted(RESEARCH_TASK_STATUSES), dest="statuses")

    validate_parser = subparsers.add_parser("validate", help="Check lifecycle metadata and require non-empty Markdown without enforcing headings or fields.")
    validate_parser.add_argument("--task", required=True)

    complete_parser = subparsers.add_parser("complete", help="Archive all raw sources, then finish a task and start its recovery retention window.")
    complete_parser.add_argument("--task", required=True)

    abandon_parser = subparsers.add_parser("abandon", help="Abandon a task and start its recovery retention window.")
    abandon_parser.add_argument("--task", required=True)

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove due terminal state and working files; preserve research data and archives.")
    cleanup_parser.add_argument("--task", help="Limit cleanup to one task; defaults to all due terminal tasks.")
    cleanup_parser.add_argument("--apply", action="store_true", help="Apply the displayed cleanup. Without this flag, only preview it.")

    args = parser.parse_args()
    if args.command == "init":
        result = init_research_task(args.task, title=args.title, retention_days=args.retention_days)
    elif args.command == "checkpoint":
        result = checkpoint_research_task(args.task, status=args.status)
    elif args.command == "status":
        result = load_research_task(args.task, require_state=False)
    elif args.command == "validate":
        result = load_research_task(args.task)
    elif args.command == "list":
        result = {"tasks": list_research_tasks(statuses=args.statuses)}
    elif args.command == "complete":
        result = complete_research_task(args.task)
    elif args.command == "abandon":
        result = finish_research_task(args.task, status="abandoned")
    else:
        result = cleanup_research_task_states(task_id=args.task, apply=args.apply)
    print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
