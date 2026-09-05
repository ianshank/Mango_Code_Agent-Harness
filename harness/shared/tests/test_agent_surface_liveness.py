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
import os
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO
from harness.shared.tests.conftest import POSIX_ONLY

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
    "gate-mutation-proof": (
        "The procedure for proving a gate catches the defect it names: mutate, assert fail, "
        "restore, assert pass. It cannot be wired into a target, because the mutation is a "
        "deliberate edit to source a human or agent makes and then undoes -- a `make` recipe "
        "that mutated the tree is a recipe that can leave it mutated. Its output is evidence "
        "pasted into a PR (NS-20, C-CQ-3)."
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
    "tech-debt-audit": (
        "A periodic, broad-scope audit (drift vs. main, god-file watch list, hardcoded-value "
        "and dead-code sweep, doc/decision-log sync) invoked on request or on a cadence, not a "
        "per-PR mechanical step. `make review`'s checklist already names the four skills this "
        "one composes for the per-PR case; wiring a full drift-and-doc-sync pass into every "
        "PR's checklist would apply the wrong cadence to what it does."
    ),
    "agent-memory-manager": (
        "Provides guidelines for persisting memory and managing context retention. "
        "It acts as a protocol specification for agents to read and write persistent data, "
        "rather than an automated CI step."
    ),
    "standards-audit": (
        "A yearly (or baseline-moving) external-standards audit: gates executed in a clean "
        "environment, six review lenses, GitHub API cross-checks, then an adversarial "
        "falsification pass over the draft. Its mechanical residue is already a gate -- "
        "test_spec_selectors_collect.py catches the vacuous-selector class it found by hand -- "
        "and the rest is judgement about a report, which no per-PR target should run."
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
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=60,
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
            line for line in script.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
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
            name
            for name in candidates
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

    @POSIX_ONLY
    def test_hook_is_syntactically_valid(self) -> None:
        result = subprocess.run(["bash", "-n", str(self.HOOK)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr

    def test_every_tool_make_ci_needs_is_installed_by_the_hook(self) -> None:
        """CLAUDE.md calls `make pre-pr` non-negotiable, but the hook installed
        Python only -- so in a web session `make ci` could never complete, because
        test-node and verify-zero-skips have no node_modules."""
        text = self.HOOK.read_text(encoding="utf-8")
        assert "requirements-lock.txt" in text, "Python dependencies are not installed"
        assert "node-deps" in text, "Node dependencies are not installed, so `make ci` cannot reach test-node"

    def test_the_python_install_is_the_ci_recipe(self) -> None:
        """The hook installed `requirements-dev.txt` unhashed with whatever pip
        resolved that day, while every CI leg installs the hashed lock -- so a
        web session ran gates against a dependency set CI never saw, and when
        the install aborted it left mypy and pytest missing with nothing said
        (2026 standards audit, §2). Same recipe, same artefacts, same hashes."""
        text = self.HOOK.read_text(encoding="utf-8")
        assert "python -m pip install --quiet --require-hashes -r requirements-lock.txt" in text, (
            "the hook does not install the hashed lock with --require-hashes"
        )
        assert "python -m pip install --quiet -e . --no-deps" in text, (
            "the editable install must not re-resolve the ranges over the lock (--no-deps)"
        )
        assert not re.search(r"pip install .*-r requirements-dev\.txt", text), (
            "the hook still installs requirements-dev.txt directly, which is unhashed and unlocked"
        )

    @POSIX_ONLY
    @pytest.mark.parametrize(
        ("failing_step", "named_command"),
        [
            pytest.param("--require-hashes", "--require-hashes -r requirements-lock.txt", id="the-lock-install"),
            pytest.param("-e .", "-e . --no-deps", id="the-editable-install"),
        ],
    )
    def test_a_failed_install_is_named_and_fails_the_hook(
        self, tmp_path: Path, failing_step: str, named_command: str
    ) -> None:
        """Driven with a fake `python` whose one install step fails.

        Under plain `set -e` the abort was silent: pip's own error went to a
        stderr nobody surfaced and the hook simply stopped. The line the hook
        prints has to name the command that failed so the next `make ci` failure
        is read as "the session never got its tools", not as a real red gate.
        """
        result = self._run_with_fake_python(tmp_path, failing_step=failing_step)
        assert result.returncode != 0, "a failed install must not leave the hook reporting success"
        assert f"session-start: FAILED — 'python -m pip install {named_command}' exited non-zero" in result.stderr, (
            f"the failure line does not name the step that failed:\n{result.stderr}"
        )

    @POSIX_ONLY
    def test_a_successful_install_is_silent_about_failure(self, tmp_path: Path) -> None:
        """The control: with every step succeeding the hook exits 0 and prints no FAILED line."""
        result = self._run_with_fake_python(tmp_path, failing_step=None)
        assert result.returncode == 0, result.stderr
        assert "FAILED" not in result.stderr + result.stdout

    def _run_with_fake_python(self, tmp_path: Path, *, failing_step: str | None) -> subprocess.CompletedProcess[str]:
        """Run the hook as a managed remote against a throwaway project with a fake interpreter.

        The fake `python` succeeds on every invocation except the one whose
        arguments contain ``failing_step``; ``MANGO_SKIP_NODE_DEPS=1`` stops the
        hook before it reaches the Node install, which is not under test here.
        """
        project = tmp_path / "project"
        project.mkdir()
        (project / "requirements-lock.txt").write_text("# probe lock\n", encoding="utf-8")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_python = bin_dir / "python"
        refuse = ""
        if failing_step:
            refuse = f'case "$*" in *"{failing_step}"*) echo "fake pip: refusing" >&2; exit 1 ;; esac\n'
        fake_python.write_text(f"#!/bin/bash\n{refuse}exit 0\n", encoding="utf-8")
        fake_python.chmod(0o755)
        env = dict(os.environ)
        env.update(
            {
                "CLAUDE_CODE_REMOTE": "true",
                "CLAUDE_PROJECT_DIR": str(project),
                "MANGO_SKIP_NODE_DEPS": "1",
                "PATH": os.pathsep.join([str(bin_dir), env.get("PATH", "")]),
            }
        )
        return subprocess.run(
            ["bash", str(self.HOOK)], capture_output=True, text=True, env=env, timeout=60, cwd=tmp_path
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


class TestSkillsNameRealTargets:
    """R-GT-6: a skill that tells an agent to run a target that does not exist.

    `test_wired_skill_is_actually_named_by_make_review` checks the other
    direction -- that a skill name appears in the Makefile. Nothing checked that
    the `make` commands a SKILL.md instructs an agent to run are real targets,
    so a rename on either side, or a typo, produces a skill whose documented
    procedure fails at the first step. Measured when this was written: all eight
    distinct targets named across the thirteen skills exist, so this is a gate
    against regression rather than a fix for a live defect.
    """

    #: Backticked spans and fenced lines are scanned separately because three
    #: targets (`coverage`, `test-governance`, `pre-pr`) appear only inside
    #: fenced blocks, and prose contains phrases like "to make a stage green"
    #: that a bare `make \w+` scan reads as a target. Anchoring each form --
    #: span-initial for inline, line-initial for fenced -- excludes the prose
    #: without an exception list.
    INLINE = re.compile(r"`make\s+([a-z][a-z0-9_.-]*)")
    FENCED = re.compile(r"^\s*make\s+([a-z][a-z0-9_.-]*)", re.M)

    def _referenced_targets(self, skill: Path) -> set[str]:
        text = skill.read_text(encoding="utf-8")
        found: set[str] = set()
        in_fence = False
        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                found.update(self.FENCED.findall(line))
            else:
                found.update(self.INLINE.findall(line))
        return found

    def test_the_scan_finds_references(self) -> None:
        """Guards the scan: zero references would make the check below vacuous."""
        total = {t for skill in _skill_dirs() for t in self._referenced_targets(skill / "SKILL.md")}
        assert len(total) > 3, (
            f"only found {sorted(total)} make targets across the skills; the scanner has "
            "stopped matching and the check below would pass on anything"
        )

    @pytest.mark.parametrize("skill", _skill_dirs(), ids=lambda p: p.name)
    def test_every_make_target_a_skill_names_exists(self, skill: Path) -> None:
        from harness.shared.tests._ci_gate_helpers import _make_targets

        defined = _make_targets((REPO / "Makefile").read_text(encoding="utf-8"))
        referenced = self._referenced_targets(skill / "SKILL.md")
        missing = sorted(referenced - defined)
        assert not missing, (
            f"{skill.name}/SKILL.md tells an agent to run make target(s) that do not exist: "
            f"{missing}. The documented procedure fails at that step."
        )


class TestHookNamespacePartition:
    """R-GT-8: every hook script belongs to a namespace, and the live ones exist.

    `.mango/hooks/` holds three disjoint kinds of script: `pre-nemotron-run.sh`
    (pre-turn gate), the `post-*-run` recorders `ExecutionLoop` fires at turn
    end (NS-21), and five that `.mango/settings.json` registers and DEC-003
    keeps dormant. Nothing asserted the partition, so a new script belonged to
    neither and no test said so; and nothing asserted the live ones exist,
    because `HookRunner.run_hook` no-ops when the file is missing -- correct
    behaviour, but it means deleting or renaming a script leaves the whole
    suite green while the hook silently stops running.
    """

    MANGO_HOOKS = REPO / ".mango" / "hooks"

    def _scripts(self) -> list[Path]:
        return sorted(self.MANGO_HOOKS.glob("*.sh"))

    def _settings_registered(self) -> set[str]:
        """Stems named by a `.mango/settings.json` hook command.

        Scoped to that file specifically: DEC-003 turns on whether these are
        registered where Claude Code cannot see them, so counting a `.claude/`
        registration here would legitimise exactly the change
        `test_mango_hooks_stay_dormant` forbids.
        """
        text = MANGO_SETTINGS.read_text(encoding="utf-8")
        return {Path(name).stem for name in re.findall(r"\.mango/hooks/([\w.\-]+\.sh)", text)}

    def test_the_live_pre_run_hook_exists_on_disk(self) -> None:
        """`run_hook` no-ops on a missing file, so only this notices a deletion."""
        from harness.shared.agent_prompts import PRE_RUN_HOOK

        hook = self.MANGO_HOOKS / f"{PRE_RUN_HOOK}.sh"
        assert hook.is_file(), (
            f"{hook.relative_to(REPO)} is missing. ExecutionLoop fires {PRE_RUN_HOOK!r} at the "
            "top of every agent turn and HookRunner.run_hook no-ops when the script is absent, "
            "so the governance validation it runs would silently stop happening."
        )
        assert "validate_invariants.py" in hook.read_text(encoding="utf-8"), (
            f"{hook.name} no longer runs validate_invariants.py; it is the pre-turn gate in name only"
        )

    def test_every_post_run_hook_exists_on_disk(self) -> None:
        """NS-21: every permitted post-*-run name has a tracked script, or observation is gone."""
        from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES

        post_names = sorted(name for name in PERMITTED_HOOK_NAMES if name.startswith("post-") and name.endswith("-run"))
        assert post_names, "PERMITTED_HOOK_NAMES has no post-*-run entries"
        missing = [name for name in post_names if not (self.MANGO_HOOKS / f"{name}.sh").is_file()]
        assert not missing, (
            f"post-run hooks missing on disk: {missing}. ExecutionLoop fires these at turn end and "
            "HookRunner.run_hook no-ops when the script is absent, so the NS-21 JSONL record would "
            "silently stop appearing."
        )
        recorder = self.MANGO_HOOKS / "lib" / "record_post_run.sh"
        assert recorder.is_file(), (
            f"{recorder.relative_to(REPO)} is missing; the thin post-*-run entrypoints need the shared recorder body"
        )

    def test_post_run_hooks_are_not_settings_registered(self) -> None:
        """Orchestrator post-run hooks must not wake via .mango/settings.json (DEC-003)."""
        from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES

        registered = self._settings_registered()
        post_scripts = {
            script.stem
            for script in self._scripts()
            if script.stem.startswith("post-") and script.stem.endswith("-run")
        }
        assert post_scripts, "no post-*-run scripts on disk; partition pin is vacuous"
        assert post_scripts <= PERMITTED_HOOK_NAMES
        overlap = post_scripts & registered
        assert not overlap, f"orchestrator post-run hooks must not appear in .mango/settings.json: {sorted(overlap)}"

    def test_every_hook_script_belongs_to_a_namespace(self) -> None:
        """Either the orchestrator may fire it, or a settings file registers it."""
        from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES

        registered = self._settings_registered()
        orphans = [
            script.name
            for script in self._scripts()
            if script.stem not in PERMITTED_HOOK_NAMES and script.stem not in registered
        ]
        assert not orphans, (
            f"scripts in .mango/hooks/ that neither the orchestrator may fire nor "
            f".mango/settings.json registers: {orphans}. A script in neither namespace runs "
            "nowhere and is reviewed by nobody -- register it, name it after a permitted hook, "
            "or delete it."
        )

    def test_the_partition_is_not_vacuous(self) -> None:
        """Both namespaces must be non-empty, or the union above proves nothing."""
        from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES

        scripts = {script.stem for script in self._scripts()}
        assert scripts, ".mango/hooks/ contains no scripts; the partition check is vacuous"
        assert scripts & PERMITTED_HOOK_NAMES, "no hook script is a name the orchestrator may fire"
        assert scripts & self._settings_registered(), "no hook script is registered by .mango/settings.json"
