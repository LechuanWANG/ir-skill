#!/usr/bin/env python3
"""Lint helpers for the Investment LLM Wiki."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence


CORE_FILES = {"index.md", "log.md", "schema.md"}
WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def markdown_pages(wiki_dir: Path) -> list[Path]:
    return sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5 :]


def extract_wiki_links(text: str) -> set[str]:
    return {match.group(1).strip() for match in WIKI_LINK_RE.finditer(text)}


def link_to_candidates(link: str) -> list[str]:
    normalized = link.strip().strip("/")
    if not normalized:
        return []
    if normalized.endswith(".md"):
        return [normalized]
    return [f"{normalized}.md", f"{normalized}/index.md"]


def lint_wiki(wiki_dir: Path) -> dict[str, list[str]]:
    pages = markdown_pages(wiki_dir)
    page_names = {path.relative_to(wiki_dir).as_posix() for path in pages}
    short_names = {path.name for path in pages}
    broken_links: list[str] = []
    missing_frontmatter: list[str] = []
    missing_sources: list[str] = []

    for path in pages:
        relative = path.relative_to(wiki_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        frontmatter, _body = split_frontmatter(text)
        if path.name not in CORE_FILES:
            if frontmatter is None:
                missing_frontmatter.append(relative)
            elif "sources:" not in frontmatter:
                missing_sources.append(relative)

        for link in extract_wiki_links(text):
            candidates = link_to_candidates(link)
            if not any(candidate in page_names or Path(candidate).name in short_names for candidate in candidates):
                broken_links.append(f"{relative} -> {link}")

    return {
        "pages": sorted(page_names),
        "broken_links": sorted(broken_links),
        "missing_frontmatter": sorted(missing_frontmatter),
        "missing_sources": sorted(missing_sources),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint the Investment LLM Wiki.")
    parser.add_argument("--wiki-dir", type=Path, default=Path("docs/investment-llm-wiki"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = lint_wiki(args.wiki_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["broken_links"] or report["missing_frontmatter"] or report["missing_sources"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
