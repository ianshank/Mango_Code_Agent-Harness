"""Tests for agent/skill harness wiring (Phase 1 modernization).

These guard against silent drift between:
  * the active Mango roles in .mango/agents/ and the canonical contracts
    in harness/shared/agents/ (reconciled by .mango/agents/README.md),
  * the skills declared in .mango/skills/ and their SKILL.md frontmatter,
  * the spec-driven workflow scaffolding (template + Makefile targets),
  * the governance policy's protected paths.

Everything is discovered dynamically from the filesystem/policy - no
hard-coded thresholds, digests, or role lists beyond the documented contract.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MANGO = REPO / ".mango"
ACTIVE_AGENTS = MANGO / "agents"
CANONICAL_AGENTS = REPO / "harness" / "shared" / "agents"
SKILLS = MANGO / "skills"
POLICY = REPO / "harness" / "shared" / "governance-policy.json"
SPEC_TEMPLATE = REPO / "docs" / "specs" / "SPEC_TEMPLATE.md"
MAKEFILE = REPO / "Makefile"
CLAUDE_MD = REPO / "CLAUDE.md"

# The three roles the orchestrator actually executes (planner -> reasoner -> verifier).
EXPECTED_ACTIVE_ROLES = {"planner", "nemotron-reasoner", "verifier"}


def _frontmatter(path: Path) -> dict[str, str]:
    """Parse the leading YAML-ish frontmatter block of a SKILL.md/agent .md."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    fields: dict[str, str] = {}
    key = None
    for line in match.group(1).splitlines():
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", line):
            key, _, value = line.partition(":")
            key = key.strip()
            fields[key] = value.strip()
        elif key and line.startswith((" ", "\t")):
            # Folded/continued scalar (description: > style).
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


class ActiveAgentTests(unittest.TestCase):
    def test_expected_active_roles_present(self):
        found = {p.stem for p in ACTIVE_AGENTS.glob("*.md")} - {"README"}
        self.assertEqual(
            found,
            EXPECTED_ACTIVE_ROLES,
            "active Mango roles drifted from the executed planner->reasoner->verifier loop",
        )

    def test_mapping_readme_exists_and_covers_every_active_role(self):
        readme = ACTIVE_AGENTS / "README.md"
        self.assertTrue(readme.is_file(), "missing .mango/agents/README.md mapping")
        text = readme.read_text(encoding="utf-8")
        for role in sorted(EXPECTED_ACTIVE_ROLES):
            self.assertIn(role, text, f"mapping README does not document active role {role}")

    def test_mapping_readme_references_every_canonical_contract(self):
        """Every canonical role contract must be accounted for in the mapping."""
        readme = (ACTIVE_AGENTS / "README.md").read_text(encoding="utf-8")
        canonical = {p.stem for p in CANONICAL_AGENTS.glob("*.md")} - {"README"}
        self.assertTrue(canonical, "no canonical contracts discovered")
        for role in sorted(canonical):
            self.assertIn(
                role,
                readme,
                f"canonical contract '{role}' is not reconciled in .mango/agents/README.md",
            )

    def test_active_roles_declare_their_canonical_role(self):
        for role in sorted(EXPECTED_ACTIVE_ROLES):
            text = (ACTIVE_AGENTS / f"{role}.md").read_text(encoding="utf-8")
            self.assertIn(
                "## Canonical role",
                text,
                f"{role}.md does not declare its canonical role mapping",
            )

    def test_reasoner_documents_meta_tools(self):
        """The implementer role must document the meta-tools the orchestrator wires in."""
        text = (ACTIVE_AGENTS / "nemotron-reasoner.md").read_text(encoding="utf-8")
        for tool in ("knowledge_gap_log", "hypothesis_register"):
            self.assertIn(tool, text, f"reasoner role does not document meta-tool {tool}")

    def test_meta_tools_are_actually_wired_into_the_orchestrator(self):
        """Documentation must match code: the schema is appended to the tool list."""
        src = (REPO / "harness" / "shared" / "mango_mas_orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("META_TOOLS_SCHEMA", src, "orchestrator does not wire META_TOOLS_SCHEMA")
        for tool in ("knowledge_gap_log", "hypothesis_register"):
            self.assertIn(tool, src, f"orchestrator does not dispatch meta-tool {tool}")


class SkillTests(unittest.TestCase):
    def test_every_skill_dir_has_a_skill_md(self):
        skill_dirs = [d for d in SKILLS.iterdir() if d.is_dir()]
        self.assertTrue(skill_dirs, "no skills discovered")
        for d in sorted(skill_dirs):
            self.assertTrue((d / "SKILL.md").is_file(), f"skill {d.name} is missing SKILL.md")

    def test_skill_frontmatter_name_matches_directory(self):
        for d in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
            fm = _frontmatter(d / "SKILL.md")
            self.assertIn("name", fm, f"skill {d.name} has no 'name' in frontmatter")
            self.assertEqual(
                fm["name"],
                d.name,
                f"skill {d.name} frontmatter name '{fm.get('name')}' does not match directory",
            )

    def test_skill_frontmatter_has_nonempty_description(self):
        for d in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
            fm = _frontmatter(d / "SKILL.md")
            desc = fm.get("description", "").lstrip(">").strip()
            self.assertTrue(desc, f"skill {d.name} has an empty description")

    def test_phase1_skills_present(self):
        """The gate/spec skills introduced in Phase 1 must exist."""
        for name in ("validation-runner", "coverage-gate", "spec-authoring"):
            self.assertTrue((SKILLS / name / "SKILL.md").is_file(), f"missing skill {name}")

    def test_coverage_gate_skill_does_not_hardcode_threshold(self):
        """The coverage skill must reference the policy, not a literal percentage."""
        text = (SKILLS / "coverage-gate" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("governance-policy.json", text)
        self.assertIn("coverage.lines", text)


class SpecWorkflowTests(unittest.TestCase):
    def test_spec_template_exists_with_required_sections(self):
        self.assertTrue(SPEC_TEMPLATE.is_file(), "missing docs/specs/SPEC_TEMPLATE.md")
        text = SPEC_TEMPLATE.read_text(encoding="utf-8")
        for heading in (
            "Problem statement",
            "Acceptance criteria",
            "Invariants touched",
            "Validation matrix",
            "Backward compatibility",
        ):
            self.assertIn(heading, text, f"spec template missing required section: {heading}")

    def test_makefile_exposes_spec_and_review_targets(self):
        text = MAKEFILE.read_text(encoding="utf-8")
        for target in ("spec:", "review:", "pre-pr:"):
            self.assertIn(f"\n{target}", text, f"Makefile missing target {target}")

    def test_pre_pr_runs_ci_and_review(self):
        text = MAKEFILE.read_text(encoding="utf-8")
        match = re.search(r"^pre-pr:\s*(.*?)(?:##|$)", text, re.MULTILINE)
        self.assertIsNotNone(match, "could not parse pre-pr prerequisites")
        prereqs = (match.group(1) if match else "").split()
        self.assertIn("ci", prereqs, "pre-pr must run the full ci gate")
        self.assertIn("review", prereqs, "pre-pr must run the review gate")

    def test_coverage_threshold_is_sourced_from_policy_not_hardcoded(self):
        """COV_MIN must be derived from governance-policy.json (no literal drift)."""
        text = MAKEFILE.read_text(encoding="utf-8")
        match = re.search(r"^COV_MIN\s*\?=\s*(.+)$", text, re.MULTILINE)
        self.assertIsNotNone(match, "Makefile does not define COV_MIN")
        self.assertIn(
            "governance-policy.json",
            match.group(1) if match else "",
            "COV_MIN must be read from governance-policy.json",
        )


class InstructionWiringTests(unittest.TestCase):
    def test_claude_md_exists_and_wires_the_loop_and_review(self):
        self.assertTrue(CLAUDE_MD.is_file(), "missing root CLAUDE.md agent instructions")
        text = CLAUDE_MD.read_text(encoding="utf-8")
        for role in sorted(EXPECTED_ACTIVE_ROLES):
            self.assertIn(role, text, f"CLAUDE.md does not wire the {role} role")
        for skill in ("openspec-peer-review", "repo-invariant-review"):
            self.assertIn(skill, text, f"CLAUDE.md does not mandate the {skill} skill")
        self.assertIn("make pre-pr", text, "CLAUDE.md does not mandate the pre-pr gate")

    def test_hooks_are_protected_by_policy(self):
        """Hooks execute shell on tool use; they must be protected paths."""
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertIn(
            ".mango/hooks/**",
            policy.get("protected_paths", []),
            "executable hooks are not covered by protected_paths",
        )

    def test_declared_hooks_exist_on_disk(self):
        """Every hook command referenced by settings.json must exist and be valid."""
        settings = json.loads((MANGO / "settings.json").read_text(encoding="utf-8"))
        referenced: set[str] = set()
        for entries in settings.get("hooks", {}).values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    match = re.search(r"\.mango/hooks/([\w.\-]+)", cmd)
                    if match:
                        referenced.add(match.group(1))
        self.assertTrue(referenced, "no hooks referenced by settings.json")
        for name in sorted(referenced):
            self.assertTrue(
                (MANGO / "hooks" / name).is_file(),
                f"settings.json references missing hook {name}",
            )

    def test_completion_checklist_covers_the_current_gates(self):
        text = (MANGO / "hooks" / "pre_completion_checklist.sh").read_text(encoding="utf-8")
        self.assertIn("governance-policy.json", text, "checklist does not reference the policy")
        self.assertIn("pre-pr", text, "checklist does not reference the pre-PR gate")


if __name__ == "__main__":
    unittest.main()
