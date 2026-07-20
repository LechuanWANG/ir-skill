from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_index import lint_wiki


class WikiIndexTests(unittest.TestCase):
    def write_page(self, root: Path, relative: str, domain: str) -> None:
        page = root / relative
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f"---\ndomain: {domain}\nsources: []\n---\n\n# Test\n",
            encoding="utf-8",
        )

    def test_lints_entity_concept_and_analysis_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("index.md", "log.md", "schema.md"):
                (root / name).write_text(f"# {name}\n", encoding="utf-8")
            self.write_page(root, "wiki/entity/company/example/overview.md", "company")
            self.write_page(root, "wiki/concept/methodology/example/method.md", "macro")
            self.write_page(root, "wiki/analysis/screening/example/screen.md", "market")

            report = lint_wiki(root)

            self.assertEqual(report["broken_links"], [])
            self.assertEqual(report["missing_frontmatter"], [])
            self.assertEqual(report["missing_sources"], [])
            self.assertEqual(report["invalid_domain"], [])
            self.assertEqual(report["structure_errors"], [])
