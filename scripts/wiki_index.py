#!/usr/bin/env python3
"""Lint helpers for the optional IR Skill LLM Wiki."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Sequence
from urllib.parse import urlsplit


CORE_FILES = {"index.md", "log.md", "schema.md"}
DOMAINS = ("company", "industry", "market", "macro")
WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^)]*)?\)")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")


def markdown_pages(wiki_dir: Path) -> list[Path]:
    pages_root = wiki_dir / "wiki"
    if not pages_root.is_dir():
        return []
    return sorted(
        page
        for domain in DOMAINS
        for page in (pages_root / domain).rglob("*.md")
        if page.is_file()
    )


def core_documents(wiki_dir: Path) -> list[Path]:
    return sorted(
        wiki_dir / filename for filename in CORE_FILES if (wiki_dir / filename).is_file()
    )


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5 :]


def has_frontmatter_key(frontmatter: str, field: str) -> bool:
    return re.search(rf"^{re.escape(field)}:\s*(?:$|[^#])", frontmatter, re.MULTILINE) is not None


def frontmatter_value(frontmatter: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*([^#\n]+)", frontmatter, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip().strip("'\"")
    return value or None


def extract_wiki_links(text: str) -> set[str]:
    return {match.group(1).strip() for match in WIKI_LINK_RE.finditer(linkable_text(text))}


def extract_markdown_links(text: str) -> set[str]:
    return {
        match.group(1).strip().strip("<>")
        for match in MARKDOWN_LINK_RE.finditer(linkable_text(text))
    }


def linkable_text(text: str) -> str:
    without_fences = CODE_FENCE_RE.sub("", text)
    return INLINE_CODE_RE.sub("", without_fences)


def link_to_candidates(link: str) -> list[str]:
    normalized = link.strip().strip("/")
    if not normalized:
        return []
    filename = normalized if normalized.endswith(".md") else f"{normalized}.md"
    candidates = [filename]
    if filename.startswith("wiki/"):
        return candidates
    if any(filename.startswith(f"{domain}/") for domain in DOMAINS):
        candidates.append(f"wiki/{filename}")
        return candidates
    candidates.extend(f"wiki/{domain}/{filename}" for domain in DOMAINS)
    return candidates


def resolve_markdown_link(source: Path, link: str) -> str | None:
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc or not parsed.path or not parsed.path.endswith(".md"):
        return None
    if parsed.path.startswith("/"):
        candidate = posixpath.normpath(parsed.path.lstrip("/"))
    else:
        candidate = posixpath.normpath(posixpath.join(source.parent.as_posix(), parsed.path))
    if candidate == "." or candidate.startswith("../"):
        return None
    return candidate


def structure_errors(wiki_dir: Path) -> list[str]:
    errors: list[str] = []
    pages_root = wiki_dir / "wiki"
    if not pages_root.is_dir():
        errors.append("missing wiki/")
    else:
        for path in sorted(pages_root.iterdir()):
            if path.is_dir() and path.name not in DOMAINS:
                errors.append(f"unexpected wiki directory: {path.relative_to(wiki_dir).as_posix()}")

    for domain in DOMAINS:
        pages_dir = pages_root / domain
        if not pages_dir.is_dir():
            errors.append(f"missing wiki/{domain}/")
            continue
        for subject_dir in sorted(pages_dir.iterdir()):
            if subject_dir.name.startswith("."):
                continue
            if not subject_dir.is_dir():
                errors.append(
                    f"flat wiki page: {subject_dir.relative_to(wiki_dir).as_posix()}"
                )
                continue
            for item in sorted(subject_dir.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    errors.append(
                        "nested wiki directory: "
                        f"{item.relative_to(wiki_dir).as_posix()}"
                    )
                elif item.suffix != ".md":
                    errors.append(
                        "non-markdown wiki file: "
                        f"{item.relative_to(wiki_dir).as_posix()}"
                    )

    for legacy_dir in ("companies", "industries"):
        if (wiki_dir / "wiki" / legacy_dir).exists():
            errors.append(f"legacy wiki/{legacy_dir}/")
    for legacy_dir in ("entities", "concepts", "sources"):
        if (wiki_dir / legacy_dir).exists():
            errors.append(f"legacy {legacy_dir}/")
    for legacy_page in (wiki_dir / "wiki").glob("*.md"):
        errors.append(f"legacy flat wiki page: {legacy_page.relative_to(wiki_dir).as_posix()}")
    return errors


def lint_wiki(wiki_dir: Path) -> dict[str, list[str]]:
    pages = markdown_pages(wiki_dir)
    documents = [*core_documents(wiki_dir), *pages]
    document_names = {path.relative_to(wiki_dir).as_posix() for path in documents}
    broken_links: list[str] = []
    missing_frontmatter: list[str] = []
    missing_sources: list[str] = []
    invalid_domain: list[str] = []

    for path in documents:
        relative = path.relative_to(wiki_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        frontmatter, _body = split_frontmatter(text)
        if relative.startswith("wiki/"):
            if frontmatter is None:
                missing_frontmatter.append(relative)
            else:
                if not has_frontmatter_key(frontmatter, "sources"):
                    missing_sources.append(relative)
                domain = frontmatter_value(frontmatter, "domain")
                expected_domain = PurePosixPath(relative).parts[1]
                if domain != expected_domain:
                    invalid_domain.append(
                        f"{relative} -> {domain or 'missing'} (expected {expected_domain})"
                    )

        for link in extract_wiki_links(text):
            candidates = link_to_candidates(link)
            if not any(candidate in document_names for candidate in candidates):
                broken_links.append(f"{relative} -> {link}")

        source = path.relative_to(wiki_dir)
        for link in extract_markdown_links(text):
            candidate = resolve_markdown_link(source, link)
            if candidate is None:
                continue
            if candidate not in document_names:
                broken_links.append(f"{relative} -> {link}")

    return {
        "pages": sorted(path.relative_to(wiki_dir).as_posix() for path in pages),
        "broken_links": sorted(broken_links),
        "missing_frontmatter": sorted(missing_frontmatter),
        "missing_sources": sorted(missing_sources),
        "invalid_domain": sorted(invalid_domain),
        "structure_errors": sorted(structure_errors(wiki_dir)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint the Investment LLM Wiki.")
    parser.add_argument("--wiki-dir", type=Path, default=Path("docs/investment-llm-wiki"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = lint_wiki(args.wiki_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    issue_keys = (
        "broken_links",
        "missing_frontmatter",
        "missing_sources",
        "invalid_domain",
        "structure_errors",
    )
    return 1 if any(report[key] for key in issue_keys) else 0


if __name__ == "__main__":
    raise SystemExit(main())
