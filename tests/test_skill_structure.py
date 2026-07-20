from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_skills import ROUTED_SKILLS, SHARED_DISCIPLINE, SKILL_ROOT, validate


class SkillStructureTests(unittest.TestCase):
    def test_all_skill_entrypoints_and_links_are_valid(self) -> None:
        self.assertEqual(validate(SKILL_ROOT), [])

    def test_root_skill_routes_every_specialist_skill(self) -> None:
        root_skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for route in (*ROUTED_SKILLS, SHARED_DISCIPLINE):
            self.assertIn(route, root_skill)
