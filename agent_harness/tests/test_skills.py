from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_harness.runtime.skills import load_skills, make_skill_tool, skills_section


class SkillTests(unittest.TestCase):
    def test_discovery_body_and_scoped_resource_reading(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            skill_dir = Path(root) / "skills" / "example"
            references = skill_dir / "references"
            references.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: example\ndescription: Example skill.\n---\n\n# Body\n",
                encoding="utf-8",
            )
            (references / "details.md").write_text("# Details\n", encoding="utf-8")

            skills = load_skills(str(Path(root) / "skills"))
            self.assertIn("example", skills_section(skills))
            read_skill = make_skill_tool(skills)

            body = read_skill.invoke({"name": "example"})
            self.assertIn("# Body", body)
            resource = read_skill.invoke({"name": "example", "resource": "references/details.md"})
            self.assertIn("# Details", resource)

            with self.assertRaises(PermissionError):
                read_skill.invoke({"name": "example", "resource": "../outside.md"})


if __name__ == "__main__":
    unittest.main()
