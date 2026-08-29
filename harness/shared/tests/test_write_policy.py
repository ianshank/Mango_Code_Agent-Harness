"""Tests for harness/shared/write_policy.py -- the runtime write gate.

Spec: ``docs/specs/agent-containment.md`` (R-AC-6, R-AC-7).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.write_policy import (
    ALWAYS_DENIED_PREFIXES,
    ALWAYS_DENIED_SEGMENTS,
    DEFAULT_POLICY_PATH,
    write_denial_reason,
)

pytestmark = pytest.mark.governance

#: One representative per reason the control surface is gated. If any of these
#: stops being denied at runtime, an agent can edit what it is permitted to do
#: inside a single task, and the CI gate only notices on the next commit.
CONTROL_SURFACE = [
    ".mango/hooks/pre-nemotron-run.sh",
    ".mango/hooks/post-verifier-run.sh",
    ".mango/agents/nemotron-reasoner.md",
    ".claude/settings.json",
    "harness/shared/governance/pretooluse_guard.py",
    "harness/shared/pretooluse_guard.py",
    "harness/shared/governance-policy.json",
    "harness/shared/agent-policy.json",
    "harness/CONTRACT.md",
    "CLAUDE.md",
    "Makefile",
    "pyproject.toml",
    "harness/shared/mango_mas_orchestrator.py",
    "harness/shared/write_policy.py",
    "harness/control-plane/tool_broker_reference.py",
]

#: Ordinary agent output. A gate that denies these has stopped being a gate and
#: started being an outage.
ORDINARY_WORK = [
    "src/feature.py",
    "tests/test_feature.py",
    "docs/notes.md",
    "README.md",
    "harness/shared/nemotron_bridge.py",
]


@pytest.mark.parametrize("relpath", CONTROL_SURFACE)
def test_control_surface_is_denied(relpath: str) -> None:
    assert write_denial_reason(relpath) is not None, f"{relpath} is writable by an agent at runtime"


@pytest.mark.parametrize("relpath", ORDINARY_WORK)
def test_ordinary_work_is_allowed(relpath: str) -> None:
    assert write_denial_reason(relpath) is None, f"{relpath} is denied; the gate is too wide"


@pytest.mark.parametrize("relpath", [".git/config", ".git/hooks/pre-commit", ".git/objects/ab/cdef"])
def test_git_directory_is_denied(relpath: str) -> None:
    """``validate_invariants`` enumerates staged, modified and untracked files, and
    git reports nothing under ``.git``. So ``protected_paths`` structurally cannot
    cover it, while a hook or a ``core.fsmonitor`` entry written there runs on the
    host at the next index refresh."""
    reason = write_denial_reason(relpath)
    assert reason is not None and "git directory" in reason


def test_dot_prefixed_paths_are_not_mangled() -> None:
    """Regression for a defect in this module's first draft.

    Normalisation used ``lstrip("./")``, which strips a character *set* rather
    than a prefix: ``.mango/hooks/x.sh`` became ``mango/hooks/x.sh`` and
    ``.git/config`` became ``git/config``. Neither matches any pattern, so the
    entire control surface read as unprotected while the gate reported success.
    Verified by writing to real files before the fix landed.
    """
    for dotted in (".mango/hooks/pre-nemotron-run.sh", ".claude/settings.json", ".git/config"):
        assert write_denial_reason(dotted) is not None, f"{dotted} lost its leading dot in normalisation"


@pytest.mark.parametrize(
    ("given", "equivalent"),
    [("./harness/shared/governance-policy.json", "harness/shared/governance-policy.json"),
     ("harness/shared/../shared/governance-policy.json", "harness/shared/governance-policy.json")],
)
def test_equivalent_paths_reach_the_same_verdict(given: str, equivalent: str) -> None:
    """A gate that can be evaded by spelling the path differently is not a gate."""
    assert (write_denial_reason(given) is None) == (write_denial_reason(equivalent) is None)


class TestFailsClosed:
    """An unreadable policy denies. Three separate gates in this repository have
    previously degraded to a built-in default on a malformed policy, which is a
    control that relaxes itself exactly when its configuration is broken."""

    def test_malformed_policy_denies(self, tmp_path: Path) -> None:
        bad = tmp_path / "policy.json"
        bad.write_text("{ not json", encoding="utf-8")
        reason = write_denial_reason("src/feature.py", policy_path=bad)
        assert reason is not None and "could not be read" in reason

    def test_absent_policy_denies(self, tmp_path: Path) -> None:
        reason = write_denial_reason("src/feature.py", policy_path=tmp_path / "missing.json")
        assert reason is not None and "could not be read" in reason

    def test_a_broken_policy_does_not_kill_the_process(self, tmp_path: Path) -> None:
        """``load_protected_patterns`` fails closed with ``sys.exit(1)``, which is
        right for a CLI gate and fatal on a tool-call path: an unreadable policy
        would end the agent run rather than refuse one write. ``SystemExit`` is not
        an ``Exception``, so it has to be caught by name."""
        bad = tmp_path / "policy.json"
        bad.write_text("[]", encoding="utf-8")
        try:
            reason = write_denial_reason("src/feature.py", policy_path=bad)
        except SystemExit:  # pragma: no cover - the assertion below is the report
            pytest.fail("SystemExit escaped the write gate and would end the agent run")
        assert reason is not None

    def test_a_policy_without_protected_paths_still_denies_the_git_directory(self, tmp_path: Path) -> None:
        empty = tmp_path / "policy.json"
        empty.write_text(json.dumps({"protected_paths": []}), encoding="utf-8")
        assert write_denial_reason(".git/config", policy_path=empty) is not None
        assert write_denial_reason("src/feature.py", policy_path=empty) is None


def test_policy_path_travels_with_the_installed_harness() -> None:
    """Resolved next to the module, not out of the tree the agent is working in."""
    assert DEFAULT_POLICY_PATH.is_file()
    assert DEFAULT_POLICY_PATH.name == "governance-policy.json"


def test_always_denied_segments_are_declared_not_inlined() -> None:
    assert ".git" in ALWAYS_DENIED_SEGMENTS
    # The prefix form is retained for callers that imported the previous name.
    assert ".git/" in ALWAYS_DENIED_PREFIXES


class TestGitDirectoryIsMatchedBySegment:
    """Regression for a prefix-matching defect in this module's second draft.

    The check was ``candidate.startswith(".git/")``, which allows
    ``sub/.git/hooks/pre-commit``: a nested repository or a submodule is still a
    git directory, and a hook written into one executes on the host exactly the
    same way. Found by probing the function rather than by reading it.
    """

    @pytest.mark.parametrize(
        "nested",
        ["sub/.git/config", "deep/a/b/.git/hooks/pre-commit", "vendor/lib/.git/config"],
    )
    def test_a_nested_git_directory_is_denied(self, nested: str) -> None:
        assert write_denial_reason(nested) is not None, f"{nested} escaped the git-directory check"

    @pytest.mark.parametrize("lookalike", [".gitignore", "src/.gitkeep", "docs/gitops.md"])
    def test_files_that_merely_share_the_prefix_are_not_denied_for_that_reason(self, lookalike: str) -> None:
        """A segment match must not swallow `.gitignore`. `.gitleaks.toml` is
        excluded from this list because it *is* protected, for a different and
        legitimate reason."""
        reason = write_denial_reason(lookalike) or ""
        assert "git directory" not in reason, f"{lookalike} was denied as a git directory"


class TestPathShapesTheCallerAlreadyRejects:
    """The orchestrator rejects these via ``is_relative_to(workspace)`` before
    calling here. Repeating the check keeps the helper safe for any other caller:
    a helper that only holds when its caller already checked is one waiting to be
    misused."""

    @pytest.mark.parametrize("absolute", ["/etc/passwd", "/tmp/evil.sh"])
    def test_absolute_paths_are_denied(self, absolute: str) -> None:
        reason = write_denial_reason(absolute)
        assert reason is not None and "absolute" in reason

    @pytest.mark.parametrize("escaping", ["../escape.py", "../../etc/passwd"])
    def test_paths_that_climb_out_are_denied(self, escaping: str) -> None:
        reason = write_denial_reason(escaping)
        assert reason is not None and "climbs out" in reason

    def test_interior_dot_dot_that_resolves_back_inside_is_allowed(self) -> None:
        """`a/../b.py` is `b.py`. Denying it would deny ordinary work."""
        assert write_denial_reason("a/../b.py") is None
