"""Keep the bundled Agent Skills valid and discoverable.

The skills in ``skills/`` are part of the project's build knowledge: they
record how the Windows bundle is assembled and why the launcher must not use
VBScript.  A malformed ``SKILL.md`` silently stops a skill from loading, so it
is worth failing CI over.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

REQUIRED = {
    "windows-python-app-packaging",
    "karaoke-video-pipeline",
    "agent-skill-authoring",
}


def _skill_dirs() -> list[Path]:
    if not SKILLS.is_dir():
        return []
    return sorted(p for p in SKILLS.iterdir() if p.is_dir() and not p.name.startswith("."))


def test_expected_skills_are_present():
    found = {p.name for p in _skill_dirs()}
    assert REQUIRED <= found, f"missing skills: {REQUIRED - found}"


def test_every_skill_has_frontmatter_matching_its_folder():
    for folder in _skill_dirs():
        skill_md = folder / "SKILL.md"
        assert skill_md.is_file(), f"{folder.name} has no SKILL.md"

        text = skill_md.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{folder.name}: SKILL.md must start with frontmatter"

        frontmatter = text.split("---", 2)[1]
        fields = {}
        for line in frontmatter.splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()

        assert fields.get("name") == folder.name, (
            f"{folder.name}: name field must equal the folder name, got {fields.get('name')!r}"
        )
        assert fields.get("description"), f"{folder.name}: description is required"
        assert len(fields["description"]) <= 1024, f"{folder.name}: description too long"


@pytest.mark.skipif(shutil.which("skills-ref") is None, reason="skills-ref not installed")
def test_skills_pass_the_reference_validator():
    for folder in _skill_dirs():
        result = subprocess.run(
            ["skills-ref", "validate", str(folder)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{folder.name} failed validation:\n{result.stdout}{result.stderr}"
        )
