"""The agent control surface -- skills and hooks -- must stay true.

`test_agent_harness_wiring.py` already checks that skills exist, that their
frontmatter parses, and that the declared hooks are on disk. That leaves the
failures this file covers, all of which were present when it was written:

* Not one of the ten `SKILL.md` files carried a `Reviewed:` date, so the
  policy's `skill_max_age_days` applied to `GOVERNANCE_SKILL.md` alone and the
  skills could age indefinitely with no signal.
* Every skill was *mentioned* somewhere, but only three were reachable from an
  executable step. A skill nothing invokes is documentation; that is a fine
  thing to be, but it should be a decision rather than an accident.
* `.mango/settings.json` invoked hook scripts by bare path while every tracked
  `.sh` in the repository is mode 644 -- a guaranteed "Permission denied" the
  moment anyone woke them.
* Two hook scripts named files that do not exist (`PLAN.md`, `NOTES.md`), and
  one of them would have created an untracked `NOTES.md` at the repo root.

Age is deliberately *not* a blocking gate here: a clock-dependent assertion
turns unrelated PRs red at a date boundary. Presence blocks; staleness is for
the scheduled workflow to raise as an issue.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

SKILLS_DIR = REPO / ".mango" / "skills"
MANGO_SETTINGS = REPO / ".mango" / "settings.json"
CLAUDE_SETTINGS = REPO / ".claude" / "settings.json"
HOOK_DIRS = (REPO / ".mango" / "hooks", REPO / ".claude" / "hooks")

pytestmark = pytest.mark.governance

# Skills reachable from an executable step, and what reaches them.
WIRED_SKILLS = {
    "openspec-peer-review": "named by `make review`'s printed checklist",
    "repo-invariant-review": "named by `make review`'s printed checklist",
    "validation-runner": "named by `make review`'s printed checklist",
    "protected-path-attestation": "named by `make review`'s printed checklist",
}

# Skills that are documentation for a human or agent to read, not steps a gate
# runs. Each entry is a decision: it says why no enforcement path is expected.
STANDALONE_SKILLS = {
    "boundary-invariant-review": (
        "Reviews the cognitive/execution boundary (INV-16). The mechanical half is already "
        "enforced by test_shadow_planner.py's authority-surface assertions; what remains is "
        "judgement about whether a new signal field could reach a control path, which no gate "
        "can decide."
    ),
    "coverage-gate": (
        "Explains how to read and act on the coverage gate. The gate itself is enforced by "
        "coverage_gate.py in `make coverage-python`; the skill is the operator's guide to it, "
        "so wiring it into a target would just print prose during CI."
    ),
    "evidence-signing": (
        "Documents the HMAC evidence manifest contract described in harness/CONTRACT.md. The "
        "fail-closed behaviour is enforced by test_evidence_manifest.py; the skill covers key "
        "handling, which is an operational procedure rather than a build step."
    ),
    "harness-engineering": (
        "House rules for extending the harness itself -- shim budgets, the shared-kernel rule, "
        "protected paths. Every rule in it already has a mechanical gate (check_dedup, "
        "validate_invariants); the skill is the narrative that explains why they exist."
    ),
    "nemotron-reasoner": (
        "The operational cheatsheet for the reasoner role. It is loaded by the agent at runtime "
        "through .mango/agents/nemotron-reasoner.md rather than by a Make target, so there is no "
        "CI step that could invoke it."
    ),
    "shadow-channel-analysis": (
        "Reports agreement, latency and token deltas for the UC-4 shadow channel. It analyses "
        "signals emitted by an opt-in feature (MANGO_SHADOW_PLANNER) that is off by default, so "
        "a CI step would have nothing to read."
    ),
    "spec-authoring": (
        "Guides writing docs/specs/<feature>.md. The structural half is enforced by "
        "`make specs`; choosing the right acceptance criteria is the part that needs a human, "
        "which is what the skill is for."
    ),
}


def _skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()) if SKILLS_DIR.is_dir() else []


def _skill_names() -> list[str]:
    return [p.name for p in _skill_dirs()]


class TestSkillsAreDated:
    def test_the_scan_finds_skills(self) -> None:
        assert len(_skill_dirs()) >= 10

    @pytest.mark.parametrize("name", _skill_names())
    def test_skill_declares_a_reviewed_date(self, name: str) -> None:
        """`skill_max_age_days` in the policy could only ever apply to
        GOVERNANCE_SKILL.md, because nothing else carried the field it reads."""
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r"^Reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$", text, re.M)
        assert match, f"{name}/SKILL.md has no `Reviewed: YYYY-MM-DD` line in its frontmatter"
        reviewed = date.fromisoformat(match.group(1))
        # Compared against UTC, with a day of slack. These dates are stamped in
        # UTC, but `date.today()` is local: a runner behind UTC evaluating this
        # just after midnight would see "tomorrow" and fail a file nobody
        # touched. The assertion exists to catch a typo'd year, not to police
        # the hour, so a day of tolerance costs it nothing.
        today_utc = datetime.now(timezone.utc).date()
        assert reviewed <= today_utc + timedelta(days=1), (
            f"{name} claims a review date in the future: {reviewed} > {today_utc}"
        )

    @pytest.mark.parametrize("name", _skill_names())
    def test_reviewed_line_is_inside_the_frontmatter(self, name: str) -> None:
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1] if text.startswith("---") else ""
        assert "Reviewed:" in frontmatter, f"{name}: Reviewed must sit in the frontmatter block"


class TestEverySkillIsWiredOrDeclared:
    @pytest.mark.parametrize("name", _skill_names())
    def test_skill_is_either_reachable_or_declared_standalone(self, name: str) -> None:
        classified = name in WIRED_SKILLS or name in STANDALONE_SKILLS
        assert classified, (
            f"skill {name!r} is neither wired to an enforcement path nor declared standalone. "
            "Add it to WIRED_SKILLS with what invokes it, or to STANDALONE_SKILLS with why "
            "nothing does -- an unclassified skill is one nobody decided about."
        )

    @pytest.mark.parametrize("name", sorted(WIRED_SKILLS))
    def test_wired_skill_is_actually_named_by_make_review(self, name: str) -> None:
        """Claiming a skill is wired is cheap; this checks the claim."""
        assert name in (REPO / "Makefile").read_text(encoding="utf-8"), (
            f"{name} is listed as wired but the Makefile never names it"
        )

    @pytest.mark.parametrize("name", sorted(STANDALONE_SKILLS))
    def test_standalone_reason_is_substantive(self, name: str) -> None:
        assert len(STANDALONE_SKILLS[name].strip()) > 120

    def test_classifications_name_skills_that_exist(self) -> None:
        known = set(_skill_names())
        stale = (set(WIRED_SKILLS) | set(STANDALONE_SKILLS)) - known
        assert not stale, f"classification entries for skills that do not exist: {sorted(stale)}"


class TestMangoIsTheOnlySkillRoot:
    def test_no_skill_directory_exists_outside_dot_mango(self) -> None:
        """Skills live in `.mango/skills/`. That was a deliberate decision, and
        this makes it an invariant rather than a convention a later change can
        quietly undo by adding a second root somewhere else.

        `.github/skills/code-review/` was exactly that: fully orphaned, naming a
        different project ("Mango-Metrics-NLM"), and asserting a >80% coverage
        bar against a policy that declares 90.
        """
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=str(REPO), capture_output=True, text=True, timeout=60
        ).stdout.splitlines()
        roots = {
            path.rsplit("/skills/", 1)[0] + "/skills"
            for path in tracked
            if "/skills/" in path or path.startswith("skills/")
        }
        assert roots <= {".mango/skills"}, (
            f"skills found outside .mango/skills: {sorted(roots - {'.mango/skills'})}. "
            "Claude Code resolves one skill root; a second one is dead weight that reads "
            "as authoritative."
        )


class TestHookInvocationAndPaths:
    def test_mango_hooks_stay_dormant(self) -> None:
        """DEC-003: the .mango lifecycle hooks are declared but not mirrored
        into .claude/settings.json, which is the file Claude Code reads. Waking
        them changes tool-call behaviour for every session and is a human
        decision in its own reviewed change."""
        claude = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
        bound = {
            hook["command"]
            for event in claude.get("hooks", {}).values()
            for matcher in event
            for hook in matcher["hooks"]
        }
        assert not any(".mango/hooks" in command for command in bound), (
            "a .mango hook is now bound in .claude/settings.json, waking it. That reverses "
            "DEC-003 and needs its own reviewed change."
        )

    def test_every_declared_hook_command_is_routed_through_bash(self) -> None:
        """Every tracked .sh here is mode 644 by convention, so a bare-path
        command is a guaranteed Permission denied. The fix is the invocation,
        not chmod."""
        offenders = []
        for settings in (MANGO_SETTINGS, CLAUDE_SETTINGS):
            data = json.loads(settings.read_text(encoding="utf-8"))
            for event in data.get("hooks", {}).values():
                for matcher in event:
                    for hook in matcher["hooks"]:
                        if not hook["command"].startswith("bash "):
                            offenders.append(f"{settings.name}: {hook['command']}")
        assert not offenders, f"hook commands not routed through bash: {offenders}"

    def test_hook_scripts_share_one_mode_convention(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-s", ".mango/hooks", ".claude/hooks"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60,
        ).stdout.splitlines()
        modes = {line.split()[0] for line in tracked if line.strip()}
        assert modes == {"100644"}, (
            f"mixed hook file modes {sorted(modes)}. One convention, zero exceptions: the "
            "commands are routed through bash, so the executable bit is never consulted."
        )

    @pytest.mark.parametrize(
        "script",
        sorted(p for directory in HOOK_DIRS if directory.is_dir() for p in directory.glob("*.sh")),
        ids=lambda p: p.name,
    )
    def test_hook_references_only_paths_that_exist(self, script: Path) -> None:
        """`PLAN.md`, `NOTES.md` and `.mango/FAILURE_MEMORY.md` were all named by
        hooks and none existed. A hook that is wrong while dormant is a hook
        that fails the day someone wakes it."""
        # Full-line comments are stripped first: a comment that explains which
        # paths a hook *used* to name is documentation, not a reference, and
        # scanning it would make recording the fix impossible.
        text = "\n".join(
            line for line in script.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        # Whole tokens, not regex substrings: a substring match on
        # "$STATE_DIR/precompact-checkpoint.md" keeps finding shorter tails
        # ("precompact-checkpoint.md", then "checkpoint.md") whatever the
        # lookbehind excludes. Splitting on shell separators and testing each
        # token is both simpler and exact.
        tokens = re.split(r"[\s\"'`(){}|;,]+", text)
        candidates = {
            token.rstrip(".,;:")
            for token in tokens
            # "$" means the path is constructed at runtime -- a write target,
            # not a file the hook expects to already exist.
            if token.endswith(".md") and "$" not in token
        }
        missing = [
            name for name in candidates
            # Gitignored runtime artifacts are guarded by a conditional in the
            # script itself; they are allowed to be absent.
            if not (REPO / name).exists() and "FAILURE_MEMORY" not in name
        ]
        assert not missing, f"{script.name} references files that do not exist: {sorted(missing)}"

    def test_precompact_hook_writes_only_into_ignored_state(self) -> None:
        """Its previous target, $PROJECT_DIR/NOTES.md, was neither tracked nor
        ignored, so the hook would have left an untracked file showing in every
        subsequent `git status`."""
        text = (REPO / ".mango" / "hooks" / "save_state_before_compact.sh").read_text(encoding="utf-8")
        assert ".mango/.state" in text
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        assert ".mango/.state/" in ignore, "the hook's write target is not gitignored"


class TestSessionStartPreparesTheGates:
    HOOK = REPO / ".claude" / "hooks" / "session-start.sh"

    def test_hook_is_syntactically_valid(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(self.HOOK)], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr

    def test_every_tool_make_ci_needs_is_installed_by_the_hook(self) -> None:
        """CLAUDE.md calls `make pre-pr` non-negotiable, but the hook installed
        Python only -- so in a web session `make ci` could never complete, because
        test-node and verify-zero-skips have no node_modules."""
        text = self.HOOK.read_text(encoding="utf-8")
        assert "requirements-dev.txt" in text, "Python dev dependencies are not installed"
        assert "node-deps" in text, (
            "Node dependencies are not installed, so `make ci` cannot reach test-node"
        )

    def test_node_install_shares_the_ci_recipe(self) -> None:
        """One recipe, so the hook and CI cannot drift into installing
        different things."""
        assert "make node-deps" in self.HOOK.read_text(encoding="utf-8")

    def test_the_escape_hatch_exists(self) -> None:
        assert "MANGO_SKIP_NODE_DEPS" in self.HOOK.read_text(encoding="utf-8")

    def test_node_install_failure_does_not_fail_the_session(self) -> None:
        """A hook that aborts leaves the session worse off than a partial
        install: the Python gates were already usable at that point."""
        text = self.HOOK.read_text(encoding="utf-8")
        assert "Python gates are still usable" in text

    def test_gitleaks_is_the_one_declared_gap(self) -> None:
        """`make secrets` needs gitleaks, which the hook deliberately does not
        install (it shells out to `go install`). Declared here so the gap is a
        decision; CI installs it in its own job."""
        assert "gitleaks" not in self.HOOK.read_text(encoding="utf-8").lower()
        assert "secrets-install" in (REPO / "Makefile").read_text(encoding="utf-8")


class TestAgentContractsMatchThePolicy:
    """`agent-policy.json` declares which roles exist and what each may do;
    `harness/shared/agents/*.md` is the canonical contract for each. Nothing
    checked that the two agreed, so a role could be added to one and not the
    other -- an authority declaration with no contract, or a contract granting
    authority the policy never approved."""

    POLICY = REPO / "harness" / "shared" / "agent-policy.json"
    CANONICAL_AGENTS = REPO / "harness" / "shared" / "agents"

    def _policy_ids(self) -> set[str]:
        data = json.loads(self.POLICY.read_text(encoding="utf-8"))
        return {agent["id"] for agent in data["agents"]}

    def _contract_names(self) -> set[str]:
        return {p.stem for p in self.CANONICAL_AGENTS.glob("*.md")} - {"README"}

    def test_the_policy_declares_agents(self) -> None:
        assert len(self._policy_ids()) >= 5

    def test_every_policy_role_has_a_canonical_contract(self) -> None:
        missing = self._policy_ids() - self._contract_names()
        assert not missing, (
            f"agent-policy.json grants authority to roles with no contract in "
            f"harness/shared/agents/: {sorted(missing)}. A role that is permitted to act "
            "but has no written contract is unbounded authority."
        )

    def test_every_canonical_contract_has_a_policy_entry(self) -> None:
        extra = self._contract_names() - self._policy_ids()
        assert not extra, (
            f"contracts exist for roles agent-policy.json does not declare: {sorted(extra)}. "
            "Either the policy is missing an entry or the contract is dead weight that reads "
            "as authoritative."
        )

    def test_every_policy_role_declares_its_allowed_actions(self) -> None:
        data = json.loads(self.POLICY.read_text(encoding="utf-8"))
        silent = [a["id"] for a in data["agents"] if not a.get("allowed_actions")]
        assert not silent, (
            f"roles with no allowed_actions: {silent}. Under default_deny an empty list is "
            "indistinguishable from a forgotten one; say so explicitly."
        )


class TestProseNamesTestsThatExist:
    """Governance prose that names an enforcing test must name a real one.

    ``.mango/settings.json``'s ``$comment`` cited
    ``test_every_hook_references_only_existing_paths``, which never existed --
    the test is called ``test_hook_references_only_paths_that_exist``. A
    reader following that pointer to check the claim finds nothing and is left
    unable to tell whether the enforcement is missing or merely misnamed.

    This is the same defect the rest of this file guards against, one level up:
    a claim about the code that the code does not support.
    """

    # Files whose prose points at enforcing tests by name.
    PROSE_SOURCES = (
        REPO / ".mango" / "settings.json",
        REPO / "harness" / "CONTRACT.md",
    )

    def _declared_test_names(self) -> set[str]:
        names: set[str] = set()
        for source in self.PROSE_SOURCES:
            if source.is_file():
                names |= set(re.findall(r"\btest_[a-z0-9_]{6,}\b", source.read_text(encoding="utf-8")))
        return names

    def _defined_test_names(self) -> set[str]:
        defined: set[str] = set()
        for root in (REPO / "harness" / "shared" / "tests", REPO / "harness" / "api_server" / "tests"):
            for module in root.rglob("test_*.py"):
                defined.add(module.stem)
                defined |= set(re.findall(r"^\s*def (test_[a-z0-9_]+)", module.read_text(encoding="utf-8"), re.M))
        return defined

    def test_the_scan_finds_prose_references(self) -> None:
        """Guards the scan: no references found would make the check vacuous."""
        assert self._declared_test_names(), "no test names found in the governance prose"

    def test_every_named_test_exists(self) -> None:
        missing = sorted(self._declared_test_names() - self._defined_test_names())
        assert not missing, (
            f"governance prose names tests that do not exist: {missing}. Rename the "
            "reference or the test -- a pointer to nothing is worse than no pointer, "
            "because it reads as evidence the claim is enforced."
        )
