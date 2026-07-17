#!/usr/bin/env python3
"""Migrate selected legacy research material into the central research library."""

from __future__ import annotations

import argparse
import json

from research_library import migrate_legacy


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy material into data/research-library and convert it to reusable topic folders.")
    parser.add_argument("--apply", action="store_true", help="Move eligible files. Without this flag, only print the migration plan.")
    args = parser.parse_args()
    print(json.dumps(migrate_legacy(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
