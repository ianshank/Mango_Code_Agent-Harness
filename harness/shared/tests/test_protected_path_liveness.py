"""Liveness tests for `protected_paths` — do the patterns match real files?

`validate_invariants` matches protected-path patterns with `fnmatch`, which is
anchored to the whole string. A pattern written for a repository layout that does
not exist here matches *nothing*, and does so silently: the gate reports PASS
because no modified file matched, not because nothing needed protecting.

That is exactly how four patterns came to be dead. `1eb2f7f` migrated
`protected_paths` from a single-stack layout to this repo's multi-stack one by
replacing the `scripts/*` entries, and left `.governance/**`, `agents/**`,
`docs/PROJECT-CHARTER.md` and `.github/CODEOWNERS` pointing at repo-root
locations that only exist in the single-stack layout.

The test that was supposed to catch this asserted only that a pattern *string*
appeared in the list:

    self.assertIn(".mango/hooks/**", policy["protected_paths"])

which passes whether or not the pattern protects a single file. This module
supersedes it. Every assertion here is made against the **set of tracked files a
pattern actually matches**, never against the pattern text, so narrowing a
pattern while keeping it plausible-looking fails the suite.

Everything is discovered from git and the policy — no hard-coded file lists
beyond the named control-surface census, which is the point of that test.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from harness.shared.validate_invariants import is_protected

REPO = Path(__file__).resolve().parents[3]
POLICY = REPO / "harness" / "shared" / "governance-policy.json"

pytestmark = pytest.mark.governance

# Patterns that must never be removed. The liveness checks below only catch a
# pattern that exists but matches nothing; **deleting** one was entirely invisible,
# so `Makefile`, `.mango/settings.json` and the push-control scripts could each be
# un-protected with the whole suite green. This is the floor.
CRITICAL_PATTERNS = {
    "Makefile": "defines every CI gate; editing it can disable all of them",
    "pyproject.toml": "lint, type and coverage gate configuration",
    ".github/workflows/**": "the only workflows GitHub actually executes",
    "**/.governance/**": "roots of trust, skip waivers, remote allowlists",
    "harness/shared/governance-policy.json": "the policy this list lives in",
    "harness/shared/validate_invariants.py": "the gate that enforces this list",
    "harness/shared/remotes.py": "push-destination control (INV-3)",
    "harness/shared/install_hooks.sh": "installs the git hooks",
    "harness/shared/pre_push_scan.sh": "the pre-push guard",
    ".mango/settings.json": "registers hooks that execute shell",
    ".claude/settings.json": "registers the hook Claude Code actually runs",
    ".mango/hooks/**": "hook scripts execute shell on tool use",
    ".claude/hooks/**": "executes shell on every session start",
    "CLAUDE.md": "the operating instructions every agent reads",
    ".gitleaks.toml": "the INV-1 scanner's config; an allowlist entry neuters the scan",
    "requirements-dev.txt": "pins the tool versions CI installs before running any gate",
    "harness/*/Makefile": "the per-stack targets ci_required_targets is written against",
    "harness/control-plane/regenerate_bundle_digests.py": "computes the digest-regen baseline",
    "harness/control-plane/tool_broker_reference.py": (
        "the policy decision point ExecutionBroker executes as a host subprocess, before "
        "the command guard runs; rewriting it to print ALLOW bypasses the verdict entirely"
    ),
    "harness/shared/write_policy.py": (
        "the runtime write gate; unprotected, an agent could widen what it is permitted "
        "to write by editing the module that decides"
    ),
    "harness/shared/mango_mas_orchestrator.py": (
        "the enforcement point for the write gate and the command guard; unprotected, an "
        "agent could remove the checks rather than evade them"
    ),
    "harness/shared/agent_authority.py": (
        "decides which tools each role receives and which canonical identity the broker "
        "evaluates; one write remapping EXECUTION_IDENTITY hands every role everything"
    ),
    "harness/shared/debug_dump.py": (
        "decides what is redacted before a history leaves over HTTP and what is stripped "
        "from every hook environment; unprotected, an agent could widen its own disclosure"
    ),
    "harness/shared/tests/test_protected_path_liveness.py": "this gate",
    "harness/shared/tests/*ci_gate*.py": (
        "the CI gate-coverage gates (coverage map, pipeline shape, required checks) and "
        "the Make/workflow parser they share; a glob since the R-TDH-22 split"
    ),
    "harness/shared/tests/test_coverage_policy_enforcement.py": (
        "owns the coverage-threshold classification; unprotected, it could be deleted "
        "outright with every gate still green"
    ),
    "**/conftest.py": (
        "every nested conftest is imported by the verifier's own `make test-python` run; "
        "the root one was protected by DEC-042 and the nested ones were not (audit B4)"
    ),
}

# Code-execution surfaces the verifier's `make test-python` run would honour if
# they existed, protected before they exist so the guard is armed rather than
# added after the first forgery. Reproduced by the 2026 standards audit (B4):
# `write_denial_reason("GNUmakefile")` was `None`, and GNU Make reads
# `GNUmakefile` and `makefile` before `Makefile`; pytest reads `pytest.ini`,
# `tox.ini` and `setup.cfg` in preference to `pyproject.toml`; the interpreter
# imports `sitecustomize`/`usercustomize` and `.pth` files at startup; and
# `setup.py` is executed by any legacy install. Each is dormant for the same
# reason as `.claude/settings.local.json` below: no such file is tracked, and
# the pattern is what stops an agent creating one.
ARMED_BEFORE_USE = "no such file is tracked; the pattern arms the guard before an agent creates one (audit B4)"

# Patterns that intentionally match nothing today. Each entry must say why, so
# that "this pattern is dead" is a reviewed statement rather than an accident.
#
# The first four are retained from the single-stack layout an adopter of this
# harness would have, and their `**/`-prefixed twins cover this repo's multi-stack
# one. Note `fnmatch`'s `**/` needs at least one character before the slash, so a
# twin covers only the nested case -- the pair is what covers both.
#
# They are retained because deleting a protected path reads as policy weakening,
# NOT because `validate_policy.py` backstops them: that validator runs with
# CWD=harness/node and reads `harness/node/.governance/policy.json`, never this
# file. Pointed at the shared policy it would in fact fail, since its critical
# list still names the pre-migration `scripts/*` paths.
DORMANT_PATTERNS = {
    ".governance/**": "single-stack layout; this repo has harness/<stack>/.governance/",
    "agents/**": "single-stack layout; this repo has harness/<stack>/agents/",
    "docs/PROJECT-CHARTER.md": "single-stack layout; this repo has harness/<stack>/docs/",
    "**/.github/CODEOWNERS": (
        "no nested CODEOWNERS exists yet; arms the guard when one is added "
        "(the root .github/CODEOWNERS now exists and is live, so only the nested pattern stays dormant)"
    ),
    ".claude/settings.local.json": (
        "no local override file exists yet; Claude Code reads it and it can declare hooks, "
        "so the guard is armed before one appears rather than after"
    ),
    ".mango/settings.local.json": "no local override file exists yet; arms the guard when one is added",
    "GNUmakefile": f"GNU Make reads it before Makefile; {ARMED_BEFORE_USE}",
    "makefile": f"GNU Make reads it before Makefile; {ARMED_BEFORE_USE}",
    "setup.py": f"executed by a legacy install; {ARMED_BEFORE_USE}",
    "setup.cfg": f"pytest reads it as configuration; {ARMED_BEFORE_USE}",
    "pytest.ini": f"pytest reads it in preference to pyproject.toml; {ARMED_BEFORE_USE}",
    "tox.ini": f"pytest reads it as configuration; {ARMED_BEFORE_USE}",
    "sitecustomize.py": f"imported by the interpreter at startup; {ARMED_BEFORE_USE}",
    "usercustomize.py": f"imported by the interpreter at startup; {ARMED_BEFORE_USE}",
    # The nested forms: the interpreter imports these from *any* sys.path entry,
    # a virtualenv's site-packages included, and the root-only pattern left
    # `.venv/lib/*/site-packages/sitecustomize.py` writable (Copilot review on
    # PR #86). `**/` needs a character before the slash, so the pair covers both.
    "**/sitecustomize.py": f"imported by the interpreter at startup from any sys.path entry; {ARMED_BEFORE_USE}",
    "**/usercustomize.py": f"imported by the interpreter at startup from any sys.path entry; {ARMED_BEFORE_USE}",
    # `*.pth`, not `**/*.pth`: fnmatch's `*` crosses `/`, so this one pattern
    # matches a root `extra.pth` and a nested `src/extra.pth` alike, while the
    # `**/` form needs a character before the slash and misses the root.
    "*.pth": f"executed by site at interpreter startup; {ARMED_BEFORE_USE}",
}

# One sentinel per reason the control surface is gated at all. If any of these
# stops being protected, an agent can change what agents are permitted to do
# without review -- which is the threat `infra-reviewed` exists to contain.
CONTROL_SURFACE = {
    "CLAUDE.md": "operating instructions every agent in this repo reads",
    "harness/CONTRACT.md": "the invariant contract the verifier checks against",
    "harness/shared/agent-policy.json": "the agent authority model",
    ".claude/settings.json": "registers hooks that run shell on every session",
    ".claude/hooks/session-start.sh": "executes on every session start",
    ".mango/skills/repo-invariant-review/SKILL.md": "a review skill that gates PRs",
    "harness/shared/governance-policy.json": "the policy this very list lives in",
    "harness/shared/validate_invariants.py": "the gate that enforces this list",
    "pyproject.toml": "lint, type and coverage gates can be weakened here",
    "harness/control-plane/publish_policy_artifact.py": "computes the policy drift baseline",
    "harness/control-plane/policy-artifact.json": "the committed drift baseline itself",
    # The runtime enforcement layer (code-quality-tech-debt-plan R-CQ-6). Its
    # siblings `write_policy.py` and `agent_authority.py` were protected from the
    # start; these were not, so an agent could rewrite the module that decides
    # whether its next write is allowed. The verdict depends on them too: the
    # verifier's verdict is a `make test-python` run, which imports the root
    # `conftest.py`, so an agent that edits that file grades its own work.
    "harness/shared/tool_executors.py": "performs every agent write, patch and read",
    "harness/shared/tool_dispatch.py": "coerces the arguments the write gate then checks",
    "harness/shared/tool_schemas.py": "declares which tools an agent is offered at all",
    "harness/shared/agent_prompts.py": "the wire prompts and the permitted hook names",
    "harness/shared/nemotron_bridge.py": "resolves the credential and the endpoint it is sent to",
    "harness/shared/orchestrator/loop.py": "enforces the per-task tool-call and iteration budgets",
    "harness/shared/orchestrator/dispatcher.py": "routes every tool call to its executor",
    "harness/shared/orchestrator/hook_runner.py": "executes hook shell on the host",
    "conftest.py": "imported by the verifier's own test run, and writes the INV-2 skip evidence",
    "harness/shared/tests/conftest.py": (
        "imported by the verifier's own test run; a nested conftest can monkeypatch the "
        "suite into passing exactly as the root one can (audit B4)"
    ),
}


def _tracked_files() -> list[str]:
    # `core.quotePath=false` matches validate_invariants: with git's default a
    # non-ASCII path comes back C-escaped and quoted, so it would be neither
    # discovered here nor matched by an anchored pattern there.
    out = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    files = _tracked_files()
    assert files, "git ls-files returned nothing; the liveness suite would be vacuous"
    return files


@pytest.fixture(scope="module")
def patterns() -> list[str]:
    return list(json.loads(POLICY.read_text(encoding="utf-8"))["protected_paths"])


def _matches(pattern: str, tracked: list[str]) -> list[str]:
    return [f for f in tracked if is_protected(f, [pattern])]


#: The four ways a pattern set and the tree it governs can disagree. Named
#: constants rather than bare strings so a caller filtering on a kind cannot
#: quietly filter on a typo and see no findings.
DEAD = "dead"
AWAKE = "awake"
STALE = "stale"
UNDECLARED = "undeclared"


class Finding(NamedTuple):
    kind: str
    pattern: str
    detail: str


def liveness_findings(
    patterns: list[str], tracked: list[str], dormant: dict[str, str]
) -> list[Finding]:
    """Findings from applying ``patterns`` to ``tracked`` -- whatever tree that is.

    This is the assertion the in-repo tests below make. They differ from a
    foreign tree's only in *which* policy and *which* file list they supply,
    which is the point: a pattern set written for one layout matches nothing in
    another, and matching nothing is indistinguishable from a clean pass unless
    something says so (R-PPP-5). Nothing here reads this repository -- no
    ``REPO``, no ``git`` -- so the same function decides for a harness governing
    a tree it did not ship with.

    A pattern intended to match nothing is not a finding, provided ``dormant``
    declares it *with a reason*; an empty reason is a finding, because "declared
    dormant" then carries no more information than deletion would.
    """
    findings: list[Finding] = []
    for pattern in patterns:
        if pattern in dormant or _matches(pattern, tracked):
            continue
        findings.append(
            Finding(DEAD, pattern, "matches no file in the tree it governs, so it protects nothing")
        )
    for pattern, reason in dormant.items():
        if pattern not in patterns:
            findings.append(
                Finding(STALE, pattern, "is declared dormant but is no longer in the pattern set")
            )
            continue
        if not str(reason).strip():
            findings.append(
                Finding(UNDECLARED, pattern, "is declared dormant with no reason given")
            )
        matched = _matches(pattern, tracked)
        if matched:
            findings.append(
                Finding(AWAKE, pattern, f"is declared dormant but matches {sorted(matched)[:3]}")
            )
    return findings


class TestPatternLiveness:
    def test_every_live_pattern_matches_at_least_one_tracked_file(self, patterns, tracked):
        """A pattern matching nothing protects nothing, however plausible it reads."""
        dead = sorted(
            f.pattern
            for f in liveness_findings(patterns, tracked, DORMANT_PATTERNS)
            if f.kind == DEAD
        )
        assert not dead, (
            "protected_paths patterns match no tracked file, so they protect nothing: "
            f"{dead}. Either fix the pattern or declare it in DORMANT_PATTERNS "
            "with a reason."
        )

    def test_dormant_patterns_are_still_dormant(self, patterns, tracked):
        """A dormant pattern that starts matching must be reclassified, not left declared dead."""
        awake = [
            f for f in liveness_findings(patterns, tracked, DORMANT_PATTERNS) if f.kind == AWAKE
        ]
        assert not awake, (
            "patterns declared dormant now match real files; remove them from "
            f"DORMANT_PATTERNS so the liveness gate covers them: {[(f.pattern, f.detail) for f in awake]}"
        )

    def test_every_dormant_pattern_carries_a_declared_reason(self, patterns, tracked):
        """"Dormant" without a reason says no more than deletion does (R-PPP-5)."""
        undeclared = sorted(
            f.pattern
            for f in liveness_findings(patterns, tracked, DORMANT_PATTERNS)
            if f.kind == UNDECLARED
        )
        assert not undeclared, f"dormant patterns declared with no reason: {undeclared}"

    @pytest.mark.parametrize("pattern", sorted(CRITICAL_PATTERNS))
    def test_critical_pattern_is_still_present(self, pattern, patterns):
        """Deleting a pattern was invisible: liveness only catches ones that stay
        but match nothing. This is the floor that makes removal detectable."""
        assert pattern in patterns, (
            f"protected_paths no longer contains {pattern!r} — "
            f"{CRITICAL_PATTERNS[pattern]}. Removing it silently un-protects real files."
        )

    def test_critical_patterns_are_not_declared_dormant(self):
        """A floor pattern waived as dormant would be present but unenforced."""
        waived = sorted(set(CRITICAL_PATTERNS) & set(DORMANT_PATTERNS))
        assert not waived, f"critical patterns declared dormant: {waived}"

    def test_dormant_declarations_all_reference_real_patterns(self, patterns, tracked):
        """Stale dormancy waivers must not outlive the patterns they excuse."""
        stale = sorted(
            f.pattern
            for f in liveness_findings(patterns, tracked, DORMANT_PATTERNS)
            if f.kind == STALE
        )
        assert not stale, (
            f"DORMANT_PATTERNS names patterns that are no longer in the policy: {stale}"
        )


class TestControlSurfaceIsGated:
    @pytest.mark.parametrize("relpath", sorted(CONTROL_SURFACE))
    def test_control_surface_file_is_protected(self, relpath, patterns, tracked):
        reason = CONTROL_SURFACE[relpath]
        assert relpath in tracked, (
            f"{relpath} is not tracked; the census entry is vacuous and must be updated"
        )
        assert is_protected(relpath, patterns), (
            f"{relpath} is not covered by protected_paths, so it can be changed with no "
            f"review gate. It matters because: {reason}"
        )


class TestDiscoveredSurfacesAreGated:
    """Discovered from the tree, so a new stack or hook cannot silently land unprotected."""

    def test_every_stack_ci_workflow_is_protected(self, patterns, tracked):
        workflows = [f for f in tracked if "/.github/workflows/" in f or f.startswith(".github/workflows/")]
        assert workflows, "no CI workflows discovered; this test would be vacuous"
        unprotected = sorted(f for f in workflows if not is_protected(f, patterns))
        assert not unprotected, (
            f"CI workflow(s) not covered by protected_paths: {unprotected}. A pattern "
            "narrowed to one stack leaves the others editable without review."
        )

    def test_every_executable_hook_is_protected(self, patterns, tracked):
        """Hooks run shell on session/tool events; all of them need the gate."""
        hooks = [f for f in tracked if "hooks/" in f and f.endswith(".sh")]
        assert hooks, "no hook scripts discovered; this test would be vacuous"
        unprotected = sorted(f for f in hooks if not is_protected(f, patterns))
        assert not unprotected, f"hook script(s) not covered by protected_paths: {unprotected}"

    def test_every_governance_directory_file_is_protected(self, patterns, tracked):
        """root-of-trust, skip-waivers and allowed-remotes live here."""
        governed = [f for f in tracked if "/.governance/" in f or f.startswith(".governance/")]
        assert governed, "no .governance files discovered; this test would be vacuous"
        unprotected = sorted(f for f in governed if not is_protected(f, patterns))
        assert not unprotected, (
            f"governance file(s) not covered by protected_paths: {unprotected}"
        )

    def test_every_agent_role_contract_is_protected(self, patterns, tracked):
        contracts = [f for f in tracked if "/agents/" in f or f.startswith(".mango/agents/")]
        assert contracts, "no agent role contracts discovered; this test would be vacuous"
        unprotected = sorted(f for f in contracts if not is_protected(f, patterns))
        assert not unprotected, (
            f"agent role contract(s) not covered by protected_paths: {unprotected}"
        )

    def test_every_skill_is_protected(self, patterns, tracked):
        """Skills encode the review procedures that gate PRs."""
        skills = [f for f in tracked if f.startswith(".mango/skills/")]
        assert skills, "no skills discovered; this test would be vacuous"
        unprotected = sorted(f for f in skills if not is_protected(f, patterns))
        assert not unprotected, f"skill file(s) not covered by protected_paths: {unprotected}"

    def test_every_project_charter_is_protected(self, patterns, tracked):
        charters = [f for f in tracked if f.endswith("docs/PROJECT-CHARTER.md")]
        assert charters, "no project charters discovered; this test would be vacuous"
        unprotected = sorted(f for f in charters if not is_protected(f, patterns))
        assert not unprotected, (
            f"project charter(s) not covered by protected_paths: {unprotected}"
        )

    def test_every_governance_validator_is_protected(self, patterns, tracked):
        """The scripts that enforce the gates must not be editable without review."""
        validators = [
            f
            for f in tracked
            if f.startswith("harness/shared/")
            and "/tests/" not in f
            and Path(f).name.startswith(("validate_", "check_", "verify_", "pretooluse_"))
        ]
        assert validators, "no governance validators discovered; this test would be vacuous"
        unprotected = sorted(f for f in validators if not is_protected(f, patterns))
        assert not unprotected, (
            f"governance validator(s) not covered by protected_paths: {unprotected}. "
            "An agent could weaken the gate that checks its own work."
        )


class TestPortableLiveness:
    """The same assertion, applied to a tree this repository did not ship.

    `harness/CONTRACT.md` records the failure this covers: *"a pattern written
    for a different repository layout matches nothing and protects nothing --
    silently."* The guard above already measures that for this repository. What
    it could not do is travel, because it reads `REPO` and `git ls-files`.
    `liveness_findings` is the same measurement with the tree passed in, so a
    harness governing a foreign checkout gets the finding instead of a clean
    pass (R-PPP-5, AC-PPP-6, DEC-PPP-003: generalised, not replaced).
    """

    #: A layout none of this repository's sixty patterns was written for. No
    #: `Makefile`, no `pyproject.toml`, no `.github/`, no `harness/` -- which is
    #: precisely the condition under which every pattern misses and the gate
    #: reports success today.
    FOREIGN_TREE = [
        "Cargo.toml",
        "README.md",
        "src/main.rs",
        "src/lib/mod.rs",
        "tests/integration.rs",
    ]

    def test_pattern_set_matching_nothing_is_a_finding(self, patterns, tracked):
        """A foreign tree produces findings; this repository's own tree stays quiet."""
        foreign = liveness_findings(patterns, self.FOREIGN_TREE, {})
        assert {f.kind for f in foreign} == {DEAD}, (
            "a pattern set that matches nothing in the tree it governs must produce "
            f"dead-pattern findings, got kinds {sorted({f.kind for f in foreign})}"
        )
        assert sorted(f.pattern for f in foreign) == sorted(patterns), (
            "every pattern misses this layout, so every pattern must be reported; "
            f"{len(patterns) - len(foreign)} were not"
        )

        own = liveness_findings(patterns, tracked, DORMANT_PATTERNS)
        assert not own, (
            "this repository's own pattern set against its own tree must stay quiet, "
            f"got {[(f.kind, f.pattern) for f in own]}"
        )
        assert len(DORMANT_PATTERNS) == 17, (
            "the seventeen declared dormant patterns are accepted unchanged by the "
            f"generalised assertion; the declaration now holds {len(DORMANT_PATTERNS)}. "
            "(Was 7: `.github/CODEOWNERS` was reclassified out of this set when a real "
            "root CODEOWNERS was added, per test_awake_patterns_reclassify's own contract; "
            "then 6; then 15 when audit B4 armed nine code-execution surfaces before use; "
            "then 17 when the nested sitecustomize/usercustomize forms were armed.)"
        )

    def test_a_pattern_that_does_match_the_foreign_tree_is_not_reported(self, patterns):
        """Otherwise the finding above would be an artefact of the fixture, not a measurement."""
        findings = liveness_findings([*patterns, "src/**"], self.FOREIGN_TREE, {})
        assert "src/**" not in {f.pattern for f in findings}

    def test_a_dormant_declaration_suppresses_the_finding_in_a_foreign_tree(self):
        """The dormancy escape hatch has to travel too, or a portable check is unusable."""
        declared = {"agents/**": "single-stack layout; this consumer has none"}
        assert not liveness_findings(["agents/**"], self.FOREIGN_TREE, declared)

    def test_a_dormant_declaration_without_a_reason_is_itself_a_finding(self):
        """"Intended to match nothing" must be a statement someone made (R-PPP-5)."""
        findings = liveness_findings(["agents/**"], self.FOREIGN_TREE, {"agents/**": "  "})
        assert [f.kind for f in findings] == [UNDECLARED]
