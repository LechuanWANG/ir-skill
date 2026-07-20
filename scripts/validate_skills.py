#!/usr/bin/env python3
"""Validate IR Skill entrypoints, frontmatter, and local Markdown links."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FRONTMATTER_KEYS = ("name", "description")
ROUTED_SKILLS = (
    "skills/ir-long-term-trading/SKILL.md",
    "skills/ir-medium-term-catalyst/SKILL.md",
    "skills/ir-short-term-trading/SKILL.md",
    "skills/ir-deep-review/SKILL.md",
)
SHARED_DISCIPLINE = "skills/shared/research-discipline.md"
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def skill_files(root: Path) -> list[Path]:
    return [root / "SKILL.md", *sorted((root / "skills").glob("*/SKILL.md"))]


def frontmatter_errors(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return [f"{path.relative_to(SKILL_ROOT)}: missing opening frontmatter delimiter"]
    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        return [f"{path.relative_to(SKILL_ROOT)}: missing closing frontmatter delimiter"]
    fields = {
        key.strip(): value.strip()
        for line in lines[1:closing_index]
        if ":" in line
        for key, value in [line.split(":", 1)]
    }
    return [
        f"{path.relative_to(SKILL_ROOT)}: missing frontmatter field '{key}'"
        for key in REQUIRED_FRONTMATTER_KEYS
        if not fields.get(key)
    ]


def markdown_links(path: Path) -> Iterable[tuple[str, Path]]:
    text = path.read_text(encoding="utf-8")
    for target in LINK_PATTERN.findall(text):
        target = target.strip().split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        yield target, (path.parent / target).resolve()


def link_errors(path: Path) -> list[str]:
    errors: list[str] = []
    for target, resolved in markdown_links(path):
        if not resolved.is_file():
            errors.append(f"{path.relative_to(SKILL_ROOT)}: unresolved link '{target}'")
    return errors


def validate(root: Path = SKILL_ROOT) -> list[str]:
    errors: list[str] = []
    files = skill_files(root)
    for path in files:
        if not path.is_file():
            errors.append(f"missing Skill entrypoint: {path.relative_to(root)}")
            continue
        errors.extend(frontmatter_errors(path))
        errors.extend(link_errors(path))

    root_skill = root / "SKILL.md"
    if root_skill.is_file():
        root_text = root_skill.read_text(encoding="utf-8")
        for route in ROUTED_SKILLS:
            if route not in root_text:
                errors.append(f"SKILL.md: missing route to '{route}'")
        if SHARED_DISCIPLINE not in root_text:
            errors.append(f"SKILL.md: missing shared discipline route '{SHARED_DISCIPLINE}'")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Skill frontmatter and local Markdown links.")
    parser.add_argument("--root", type=Path, default=SKILL_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = validate(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(skill_files(root))} Skill entrypoints.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
