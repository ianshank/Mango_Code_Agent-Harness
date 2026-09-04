"""Tests for agent/skill harness wiring (Phase 1 modernization).

These guard against silent drift between:
  * the active Mango roles in .mango/agents/ and the canonical contracts
    in harness/shared/agents/ (reconciled by .mango/agents/README.md),
  * the skills declared in .mango/skills/ and their SKILL.md frontmatter,
  * the spec-driven workflow scaffolding (template + Makefile targets).

Whether the governance policy's protected paths actually cover real files is
checked by `test_protected_path_liveness.py`, which asserts on matched file sets
rather than on pattern strings.

Everything is discovered dynamically from the filesystem/policy - no
hard-coded thresholds, digests, or role lists beyond the documented contract.
"""
from __future__ import annotations

import json
import re
import typing
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MANGO = REPO / ".mango"
ACTIVE_AGENTS = MANGO / "agents"
CANONICAL_AGENTS = REPO / "harness" / "shared" / "agents"
SKILLS = MANGO / "skills"
SPEC_TEMPLATE = REPO / "docs" / "specs" / "SPEC_TEMPLATE.md"
MAKEFILE = REPO / "Makefile"
CLAUDE_MD = REPO / "CLAUDE.md"

# The three roles the orchestrator actually executes (planner -> reasoner -> verifier).
EXPECTED_ACTIVE_ROLES = {"planner", "nemotron-reasoner", "verifier"}

#: Persona frontmatter names Claude Code's tool vocabulary (`Read`, `Bash`, ...);
#: `agent_authority.TOOL_REQUIRED_ACTION` names the tool-bridge vocabulary
#: (`read_file`, `run_command`, ...). The two sets are disjoint apart from the
#: meta-tools, so without this join a persona could be granted anything at all
#: and no gate would notice. Declared here rather than in `agent_authority.py`
#: because it is knowledge about the *documentation* surface, not about
#: execution: nothing at runtime reads a persona's frontmatter. Each entry maps
#: to the bridge tool whose authority the Claude Code tool actually confers.
CLAUDE_CODE_TOOL_ALIASES: dict[str, str] = {
    "Read": "read_file",
    "Grep": "read_file",
    "Glob": "read_file",
    "Bash": "run_command",
    "Write": "write_file",
    "Edit": "apply_patch",
}


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

    def test_reasoner_frontmatter_tools_list_includes_meta_tools(self):
        """Stricter than test_reasoner_documents_meta_tools above: that test is
        satisfied by a prose mention anywhere in the file, which is exactly
        how this gap went unnoticed for a documented period (docs/reports/SDLC_HYGIENE_REPORT.md,
        2026-08-26) even though the body already referenced both tools -- the
        structured `tools:` frontmatter field itself only listed
        `Bash, Read, Grep, Glob`. This asserts on the parsed field specifically."""
        fields = _frontmatter(ACTIVE_AGENTS / "nemotron-reasoner.md")
        declared_tools = {t.strip() for t in fields.get("tools", "").split(",")}
        for tool in ("knowledge_gap_log", "hypothesis_register"):
            self.assertIn(
                tool,
                declared_tools,
                f"nemotron-reasoner.md's frontmatter `tools:` field does not list {tool}, "
                "even though the prose body instructs using it",
            )

    def test_meta_tools_are_actually_wired_into_the_orchestrator(self):
        """Documentation must match code: the schema is offered and dispatched.

        Asserted against the composed list and the live dispatch registry, not
        against the orchestrator's source text. The previous version searched the
        file for the strings `META_TOOLS_SCHEMA`, `knowledge_gap_log` and
        `hypothesis_register` -- which this very docstring would satisfy, and
        which a comment saying "meta tools are not wired here" would satisfy
        equally. It also broke the moment the schema moved to `tool_schemas.py`,
        for a reason unrelated to whether the tools are wired.
        """
        import tempfile

        from harness.shared import mango_mas_orchestrator as orch

        tools: list[dict[str, typing.Any]] = orch.NEMOTRON_TOOLS
        offered = {t["function"]["name"] for t in tools}
        with tempfile.TemporaryDirectory() as tmp:
            dispatched = set(orch.MangoMASOrchestrator(workspace_dir=Path(tmp)).dispatcher.tool_handlers)
        for tool in ("knowledge_gap_log", "hypothesis_register"):
            self.assertIn(tool, offered, f"orchestrator does not offer meta-tool {tool}")
            self.assertIn(tool, dispatched, f"orchestrator does not dispatch meta-tool {tool}")


class AgentSurfaceTruthTests(unittest.TestCase):
    """R-GT-6: two claims on the agent surface that presence checks cannot see.

    The tests above assert that names *appear* in the right files. A persona can
    declare an authority its role exists to withhold, and the mapping table can
    have its rows permuted, without changing which names appear anywhere -- so
    every existing check stays green through both. These assert the pairings.
    """

    def _declared_tools(self, role: str) -> set[str]:
        """The persona's frontmatter `tools:` field, as a set of tokens."""
        fields = _frontmatter(ACTIVE_AGENTS / f"{role}.md")
        return {token.strip() for token in fields.get("tools", "").split(",") if token.strip()}

    def test_no_persona_declares_an_authority_its_role_withholds(self):
        """A persona is a grant, and the authority model is what bounds it.

        The verifier is the case that matters: `agent_authority.py` exists to
        withhold `write` from it, and until now nothing compared the persona's
        own `tools:` line against that. `write_file` could be added to
        `verifier.md` with the whole suite green.
        """
        from harness.shared.agent_authority import TOOL_REQUIRED_ACTION, tool_is_permitted

        violations = []
        for role in sorted(EXPECTED_ACTIVE_ROLES):
            for token in sorted(self._declared_tools(role)):
                bridge = CLAUDE_CODE_TOOL_ALIASES.get(token, token)
                # Tools outside the authority model (documentation-only names)
                # are not judged here; the model is the only source of truth we
                # have, and inventing a verdict for a name it does not know
                # would be the hard-coding this repository forbids.
                if bridge not in TOOL_REQUIRED_ACTION:
                    continue
                if not tool_is_permitted(role, bridge):
                    violations.append(
                        f"{role}.md declares `{token}`"
                        + (f" (-> {bridge})" if bridge != token else "")
                        + f", requiring `{TOOL_REQUIRED_ACTION[bridge]}`, which the role does not hold"
                    )
        self.assertEqual(
            [],
            violations,
            "persona frontmatter grants authority the policy withholds: " + "; ".join(violations),
        )

    def test_every_role_still_declares_the_tools_it_needs(self):
        """The converse, so the gate above cannot be satisfied by an empty list.

        A persona whose `tools:` field was emptied would violate nothing, and
        the check above would pass on it -- vacuously.
        """
        for role in sorted(EXPECTED_ACTIVE_ROLES):
            self.assertTrue(
                self._declared_tools(role),
                f"{role}.md declares no tools at all; the authority check above would pass vacuously",
            )

    def _authoritative_mapping(self) -> dict[str, set[str]]:
        """Parse the `## Authoritative mapping` table into role -> contracts.

        Scoped to the first contiguous table after that heading, on purpose: a
        second `Derived exposure` table follows under no heading of its own and
        names the same three roles in its first column, so both a plain
        heading-to-heading split and an unscoped row scan would let a swap
        between the two tables satisfy this.
        """
        text = (ACTIVE_AGENTS / "README.md").read_text(encoding="utf-8")
        section = text.split("## Authoritative mapping", 1)
        self.assertEqual(len(section), 2, ".mango/agents/README.md has no '## Authoritative mapping' heading")

        mapping: dict[str, set[str]] = {}
        started = False
        for line in section[1].splitlines():
            stripped = line.strip()
            is_row = stripped.startswith("|") and stripped.endswith("|")
            if not is_row:
                if started:
                    break  # end of the first table; anything below is a different one
                continue
            started = True
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) < 2 or all(re.fullmatch(r"-+", cell) for cell in cells):
                continue  # separator row
            role_match = re.search(r"`([^`]+)`", cells[0])
            if role_match is None:
                continue  # header row
            contracts = {name.removesuffix(".md") for name in re.findall(r"`([^`]+)`", cells[1])}
            mapping[role_match.group(1)] = contracts
        return mapping

    def test_the_mapping_table_matches_the_authority_model_row_by_row(self):
        """A swapped row keeps every string in the file and breaks the contract.

        `test_mapping_readme_*` assert that each role name and each canonical
        contract name appears somewhere in the document. Exchanging the planner
        and verifier rows changes no name's presence, so both stay green while
        the table tells a reader the exact opposite of what the code does.
        """
        from harness.shared.agent_authority import ACTIVE_TO_CANONICAL

        documented = self._authoritative_mapping()
        expected = {role: set(contracts) for role, contracts in ACTIVE_TO_CANONICAL.items()}
        self.assertEqual(
            expected,
            documented,
            "the authoritative mapping table disagrees with agent_authority.ACTIVE_TO_CANONICAL; "
            "a reader following the table would attribute the wrong contracts to a role",
        )

    def test_the_mapping_parser_found_every_active_role(self):
        """Guards the parse itself: a table this cannot read must not read empty.

        Set equality against an empty dict would fail loudly, but a partial
        parse that happened to match a partial model would not -- so pin the
        row count against the roles that exist.
        """
        self.assertEqual(
            EXPECTED_ACTIVE_ROLES,
            set(self._authoritative_mapping()),
            "the mapping table parser did not recover exactly the active roles; "
            "the table's format changed and the comparison above is no longer meaningful",
        )


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
        """The coverage gate must run coverage_gate.py, whose thresholds come from
        governance-policy.json with no numeric default (COV_MIN's replacement)."""
        text = MAKEFILE.read_text(encoding="utf-8")
        match = re.search(r"^coverage-python:.*?\n((?:\t[^\n]*\n)+)", text, re.MULTILINE)
        self.assertIsNotNone(match, "Makefile has no coverage-python recipe")
        self.assertIn("coverage_gate.py", match.group(1) if match else "")
        gate = (MAKEFILE.parent / "harness" / "shared" / "coverage_gate.py").read_text(encoding="utf-8")
        self.assertIn("governance-policy.json", gate)


class InstructionWiringTests(unittest.TestCase):
    def test_claude_md_exists_and_wires_the_loop_and_review(self):
        self.assertTrue(CLAUDE_MD.is_file(), "missing root CLAUDE.md agent instructions")
        text = CLAUDE_MD.read_text(encoding="utf-8")
        for role in sorted(EXPECTED_ACTIVE_ROLES):
            self.assertIn(role, text, f"CLAUDE.md does not wire the {role} role")
        for skill in ("openspec-peer-review", "repo-invariant-review"):
            self.assertIn(skill, text, f"CLAUDE.md does not mandate the {skill} skill")
        self.assertIn("make pre-pr", text, "CLAUDE.md does not mandate the pre-pr gate")

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
