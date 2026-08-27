"""Deterministic coverage map: is every `ci_required_targets` gate actually run?

`governance-policy.json` declares `ci_required_targets` in the **per-stack**
Makefile vocabulary (`cov`, `types`, `secrets`, `audit`, `remotes`, ...), which
`harness/node/Makefile` and `harness/jvm/Makefile` implement under exactly those
names. The **root** Makefile deliberately uses a different vocabulary (`coverage`,
`lint`, `validate`, ...) because it gates a multi-stack repository rather than one
stack.

Those two vocabularies drifting apart is not hypothetical. `specs` sat in
`ci_required_targets` with no root stage at all, and the two existing meta-tests
that assert "CI invokes every required target" both read the *per-stack* `ci.yml`
and so could never have caught it.

This module closes that hole by requiring an explicit mapping: every required
gate names the root mechanism that satisfies it, and that mechanism must be
reachable from `make ci` by actual prerequisite resolution. A gate that nothing
covers must be declared in `KNOWN_GAPS` with a reason -- silence is not an option
in either direction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
POLICY = REPO / "harness" / "shared" / "governance-policy.json"
ROOT_MAKEFILE = REPO / "Makefile"
# GitHub only executes workflows in the repository-root `.github/workflows/`.
# harness/{node,jvm}/.github/workflows/ci.yml are adopter templates that never run,
# so they must never be read as evidence that a gate is enforced here.
ROOT_WORKFLOW_DIR = REPO / ".github" / "workflows"

pytestmark = pytest.mark.governance

# Maps each per-stack gate name to the root `make` target that satisfies it.
# The value must be a real root target reachable from `ci`; the test resolves
# prerequisites rather than trusting this table.
GATE_TO_ROOT_TARGET = {
    "cov": "coverage",
    "lint": "lint",
    "types": "lint",  # lint -> lint-python, which runs mypy
    "specs": "specs",
    "remotes": "remotes",
    "projections": "validate",  # validate runs check_projections.py
    "traceability": "validate",  # validate runs governance/check_traceability.py
    "governance": "validate",  # validate runs the governance validator set
    "secrets": "secrets",  # dedicated workflow job; see INV-1 note above
}

# Gates with no root equivalent. Each needs a reason; adding an entry here is a
# deliberate, reviewable statement that the root pipeline does not run this gate.
KNOWN_GAPS = {
    "audit": (
        "Dependency vulnerability scanning (osv-scanner) runs only in the per-stack "
        "CI workflows, which install it via `go install`. Wiring it into the root "
        "pipeline adds an external toolchain dependency and can turn CI red on a "
        "pre-existing advisory, so it is a deliberate follow-up rather than a "
        "silent omission."
    ),
}

# Root mechanisms that satisfy a gate only partially. Documented rather than
# asserted away, so the weaker coverage stays visible to a reviewer.
PARTIAL_COVERAGE: dict[str, str] = {}


def _expand_make_vars(makefile_text: str, line: str) -> str:
    """Substitute simple `NAME := value` / `NAME ?= value` definitions into `line`.

    Recipes reference paths through variables (`--cov=$(SHARED_SRC)`), so a literal
    string match would report a false gap. Only simple assignments are resolved,
    which is all this Makefile uses for the paths under test.
    """
    definitions = dict(
        re.findall(r"^([A-Z_][A-Z0-9_]*)\s*[:?]?=\s*(.+?)\s*$", makefile_text, re.M)
    )
    for _ in range(5):  # bounded: variables may reference other variables
        expanded = re.sub(
            r"\$\(([A-Z_][A-Z0-9_]*)\)", lambda m: definitions.get(m.group(1), m.group(0)), line
        )
        if expanded == line:
            break
        line = expanded
    return line


def _workflow_run_commands(workflow_text: str) -> str:
    """Concatenate the shell of every `run:` step, ignoring names and comments.

    Step names routinely quote the command they wrap ("Run secret scan gate
    (make secrets)"), so searching raw workflow text for an invocation gives false
    positives: the prose would keep satisfying an assertion after the step itself
    was deleted. Only executed shell counts as enforcement.

    Deliberately regex-based rather than YAML-parsed: PyYAML is not a declared
    dependency of this repo, and a governance gate must not rest on a transitive one.
    """
    commands: list[str] = []
    lines = workflow_text.splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)(?:-\s+)?run:\s*([|>][-+]?)?\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        indent, block_scalar, inline = match.group(1), match.group(2), match.group(3)
        index += 1
        if not block_scalar:
            commands.append(inline)
            continue
        base = len(indent)
        while index < len(lines):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= base:
                break
            commands.append(line)
            index += 1
    return "\n".join(commands)


def _make_prerequisites(makefile_text: str, target: str) -> list[str]:
    match = re.search(rf"^{re.escape(target)}:\s*(.*?)(?:##|$)", makefile_text, re.M)
    return match.group(1).split() if match else []


def _reachable_from(makefile_text: str, root: str) -> set[str]:
    """Transitively resolve `make` prerequisites, so nesting is followed, not assumed."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        target = stack.pop()
        if target in seen:
            continue
        seen.add(target)
        stack.extend(_make_prerequisites(makefile_text, target))
    return seen


@pytest.fixture(scope="module")
def makefile() -> str:
    return ROOT_MAKEFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def required_gates() -> list[str]:
    gates = list(json.loads(POLICY.read_text(encoding="utf-8"))["ci_required_targets"])
    assert gates, "policy declares no ci_required_targets; this suite would be vacuous"
    return gates


@pytest.fixture(scope="module")
def root_workflows() -> str:
    """Concatenated root workflows — the only ones GitHub actually executes."""
    files = sorted(ROOT_WORKFLOW_DIR.glob("*.yml")) + sorted(ROOT_WORKFLOW_DIR.glob("*.yaml"))
    assert files, "no workflows in the repository-root .github/workflows/"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


@pytest.fixture(scope="module")
def ci_reachable(makefile: str, root_workflows: str) -> set[str]:
    """Targets CI actually invokes: reachable from `make ci`, or run by a root job.

    INV-5 says "CI invokes every policy-required gate by Make target" — not that
    `make ci` must reach it. A gate deliberately kept out of the matrix (the
    interpreter-independent secret scan) is still enforced when a root job runs it.
    """
    reachable = _reachable_from(makefile, "ci")
    assert "ci" in reachable, "root Makefile has no `ci` target"
    for target in re.findall(
        r"\bmake\s+([a-zA-Z0-9_.-]+)", _workflow_run_commands(root_workflows)
    ):
        reachable |= _reachable_from(makefile, target)
    return reachable


class TestEveryRequiredGateIsAccountedFor:
    def test_every_required_gate_is_mapped_or_declared_a_gap(self, required_gates):
        """No gate may be silently unaccounted for — the failure mode `specs` hit."""
        unaccounted = sorted(
            g for g in required_gates if g not in GATE_TO_ROOT_TARGET and g not in KNOWN_GAPS
        )
        assert not unaccounted, (
            f"ci_required_targets entries with no root mapping and no declared gap: "
            f"{unaccounted}. Add a root target and map it in GATE_TO_ROOT_TARGET, or "
            "declare it in KNOWN_GAPS with a reason."
        )

    def test_mapped_gates_resolve_to_targets_reachable_from_ci(
        self, required_gates, ci_reachable, makefile
    ):
        """A mapping that points at a target `make ci` never reaches is not coverage."""
        broken = {}
        for gate in required_gates:
            target = GATE_TO_ROOT_TARGET.get(gate)
            if target is None:
                continue
            if not _make_prerequisites(makefile, target) and not re.search(
                rf"^{re.escape(target)}:", makefile, re.M
            ):
                broken[gate] = f"root target '{target}' does not exist"
            elif target not in ci_reachable:
                broken[gate] = f"root target '{target}' is not reachable from `make ci`"
        assert not broken, f"required gates mapped to unreachable root targets: {broken}"

    def test_no_stale_mappings(self, required_gates):
        """A mapping for a gate the policy no longer requires is dead weight."""
        stale = sorted(set(GATE_TO_ROOT_TARGET) - set(required_gates))
        assert not stale, f"GATE_TO_ROOT_TARGET maps gates the policy does not require: {stale}"

    def test_no_stale_gap_declarations(self, required_gates):
        """A gap waiver must not outlive the requirement it excuses."""
        stale = sorted(set(KNOWN_GAPS) - set(required_gates))
        assert not stale, f"KNOWN_GAPS declares gates the policy does not require: {stale}"

    def test_gaps_are_not_also_mapped(self):
        """A gate is either covered or a declared gap, never recorded as both."""
        both = sorted(set(KNOWN_GAPS) & set(GATE_TO_ROOT_TARGET))
        assert not both, f"gates declared as gaps but also mapped as covered: {both}"

    @pytest.mark.parametrize("gate", sorted(KNOWN_GAPS))
    def test_every_declared_gap_has_a_substantive_reason(self, gate):
        reason = KNOWN_GAPS[gate].strip()
        assert len(reason) > 40, f"KNOWN_GAPS['{gate}'] needs a real reason, not a placeholder"

    def test_partial_coverage_notes_describe_mapped_gates(self, required_gates):
        """Loops rather than parametrizes: an empty dict must not become a skipped test."""
        for gate in sorted(PARTIAL_COVERAGE):
            assert gate in GATE_TO_ROOT_TARGET, (
                f"PARTIAL_COVERAGE['{gate}'] describes a gate that is not mapped as covered"
            )
            assert gate in required_gates, (
                f"PARTIAL_COVERAGE['{gate}'] describes a gate the policy no longer requires"
            )


class TestRootPipelineShape:
    """Guards the structural invariants other tooling and docs depend on."""

    def test_ci_runs_the_specs_stage(self, ci_reachable):
        assert "specs" in ci_reachable, "`make ci` no longer runs the specs gate"

    def test_ci_runs_the_remotes_stage(self, ci_reachable):
        assert "remotes" in ci_reachable, "`make ci` no longer runs the remote allowlist gate"

    def test_specs_target_invokes_the_validator_through_bash(self, makefile):
        """validate_specs.sh is mode 644: a bare ./ invocation is a guaranteed red CI."""
        recipe = re.search(r"^specs:.*?\n((?:\t.*\n)+)", makefile, re.M)
        assert recipe, "root Makefile has no specs recipe"
        body = recipe.group(1)
        assert "validate_specs.sh" in body, "specs target does not invoke validate_specs.sh"
        assert re.search(r"\bbash\b\s+\S*validate_specs\.sh", body), (
            "validate_specs.sh must be invoked via `bash`; it is not executable, so a "
            "bare ./ invocation fails with 'Permission denied'"
        )

    def test_secret_scan_gate_fails_closed_and_scans_history(self, makefile, root_workflows):
        """INV-1: a missing tool must fail, and the history scan must not be vacuous."""
        recipe = re.search(r"^secrets:.*?\n((?:\t.*\n|\t@.*\n)+)", makefile, re.M)
        assert recipe, "root Makefile has no secrets recipe"
        body = recipe.group(1)
        assert "command -v" in body and "exit 1" in body, (
            "the secrets gate must fail closed when gitleaks is absent, never skip"
        )
        assert re.search(r"gitleaks\S*\s+dir\b", body) or "$(GITLEAKS) dir" in body, (
            "secrets gate does not scan the working tree"
        )
        assert re.search(r"gitleaks\S*\s+git\b", body) or "$(GITLEAKS) git" in body, (
            "secrets gate does not scan git history"
        )
        # Word-boundary match against executed shell only: plain `make secrets`, never
        # the `make secrets-install` step that fetches the tool and enforces nothing.
        assert re.search(r"\bmake\s+secrets\b(?!-)", _workflow_run_commands(root_workflows)), (
            "no root workflow invokes `make secrets`; INV-1 would have no live "
            "enforcement, since GitHub never runs harness/*/.github/workflows/"
        )
        assert "fetch-depth: 0" in root_workflows, (
            "the secret-scan job needs a full clone (fetch-depth: 0); the default "
            "shallow checkout makes the history scan vacuous"
        )

    def test_coverage_threshold_is_not_hardcoded(self, makefile):
        """COV_MIN must come from policy so the gate and policy cannot drift."""
        match = re.search(r"^COV_MIN\s*\?=\s*(.+)$", makefile, re.M)
        assert match, "root Makefile does not define COV_MIN"
        assert "governance-policy.json" in match.group(1), (
            "COV_MIN must be read from governance-policy.json, not hard-coded"
        )

    def test_coverage_measures_every_declared_source_root(self, makefile):
        """A source root in pyproject's coverage config that the gate never measures
        is configured-but-unmeasured — the state harness/control-plane was in."""
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        source_block = re.search(r"^source\s*=\s*\[(.*?)\]", pyproject, re.M | re.S)
        assert source_block, "pyproject declares no [tool.coverage.run] source"
        declared = re.findall(r'"([^"]+)"', source_block.group(1))
        assert declared, "coverage source list is empty"
        recipe = re.search(r"^coverage-python:.*?\n((?:\t.*\n)+)", makefile, re.M)
        assert recipe, "root Makefile has no coverage-python recipe"
        body = _expand_make_vars(makefile, recipe.group(1))
        unmeasured = sorted(s for s in declared if f"--cov={s}" not in body)
        assert not unmeasured, (
            f"coverage source root(s) declared in pyproject but never measured by the "
            f"gate: {unmeasured}. The Makefile's explicit --cov flags take precedence "
            "over the static config, so these read as covered while being ignored."
        )
