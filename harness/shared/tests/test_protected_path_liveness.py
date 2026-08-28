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
    "harness/shared/tests/test_protected_path_liveness.py": "this gate",
    "harness/shared/tests/test_ci_gate_coverage.py": "the CI gate-coverage gate",
}

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
    ".github/CODEOWNERS": "no CODEOWNERS exists yet; arms the guard when one is added",
    "**/.github/CODEOWNERS": "no nested CODEOWNERS exists yet; arms the guard when one is added",
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


class TestPatternLiveness:
    def test_every_live_pattern_matches_at_least_one_tracked_file(self, patterns, tracked):
        """A pattern matching nothing protects nothing, however plausible it reads."""
        dead = [
            p for p in patterns if p not in DORMANT_PATTERNS and not _matches(p, tracked)
        ]
        assert not dead, (
            "protected_paths patterns match no tracked file, so they protect nothing: "
            f"{sorted(dead)}. Either fix the pattern or declare it in DORMANT_PATTERNS "
            "with a reason."
        )

    def test_dormant_patterns_are_still_dormant(self, patterns, tracked):
        """A dormant pattern that starts matching must be reclassified, not left declared dead."""
        awake = {
            p: _matches(p, tracked)
            for p in DORMANT_PATTERNS
            if p in patterns and _matches(p, tracked)
        }
        assert not awake, (
            "patterns declared dormant now match real files; remove them from "
            f"DORMANT_PATTERNS so the liveness gate covers them: { {k: v[:3] for k, v in awake.items()} }"
        )

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

    def test_dormant_declarations_all_reference_real_patterns(self, patterns):
        """Stale dormancy waivers must not outlive the patterns they excuse."""
        stale = sorted(set(DORMANT_PATTERNS) - set(patterns))
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
