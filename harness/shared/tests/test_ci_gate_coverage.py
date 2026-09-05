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

import re

import pytest

from harness.shared.tests import _ci_gate_helpers as _shared
from harness.shared.tests._ci_gate_helpers import (
    ROOT_MAKEFILE,
    _evidence_text,
    _make_prerequisites,
    _root_workflow_texts,
)

# pytest registers fixtures by scanning the module namespace, so binding the shared
# ones here is what makes them resolvable by name in this module (root_workflows is
# ci_reachable's dependency). Bound rather than imported: an import that only pytest
# reads trips F401, and a parameter of the same name then trips F811.
ci_reachable = _shared.ci_reachable
makefile = _shared.makefile
required_gates = _shared.required_gates
root_workflows = _shared.root_workflows

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
    "audit": "audit",  # dedicated workflow job; see the `audit` job in python-package.yml
}

# What each gate's recipe must still *do*. Reachability only proves the target
# name is wired into `ci`; without this, emptying `validate` (which would delete
# the only invocation of the protected-path gate) leaves every test green.
GATE_TO_EVIDENCE = {
    "cov": r"coverage_gate\.py",
    "lint": r"\$\(RUFF\)|ruff",
    "types": r"\$\(MYPY\)|mypy",
    "specs": r"validate_specs\.sh",
    "remotes": r"remotes\.py",
    "projections": r"check_projections",
    "traceability": r"check_traceability",
    "governance": r"validate_invariants\.py",
    "secrets": r"\$\(GITLEAKS\)|gitleaks",
    "audit": r"pip-audit",
}


# Gates with no root equivalent. Each needs a reason; adding an entry here is a
# deliberate, reviewable statement that the root pipeline does not run this gate.
KNOWN_GAPS: dict[str, str] = {}

# Root mechanisms that satisfy a gate only partially. Documented rather than
# asserted away, so the weaker coverage stays visible to a reviewer.
PARTIAL_COVERAGE: dict[str, str] = {
    "specs": (
        "`make specs` runs validate_specs.sh, which is three-tier. The *structural* "
        "tier always runs and does real work (required sections, a requirement ID "
        "on every normative MUST, no unfalsifiable acceptance language, no unfilled "
        "template scaffold). The *plan* tier always runs too (validate_plan.py: "
        "unfalsifiable acceptance, stage reachability, missing failure path, orphan "
        "requirement) but is scoped to plans git reports as modified, so a run that "
        "touches no spec examines nothing -- it says so on stdout rather than "
        "reporting a silent pass. The "
        "*strict* tier (`openspec validate`) does not: `openspec` is pinned "
        "nowhere, and REQUIRE_STRICT_SPEC_VALIDATOR=1 is set only in "
        "harness/{node,jvm}/.github/workflows/ci.yml -- adopter templates GitHub "
        "never executes -- so root CI silently takes the WARNING branch on every "
        "run. Installing an unpinned, unverified validator as a hard CI dependency "
        "is a product decision, not a gate fix, so the strict tier is declared "
        "absent here rather than advertised as enforced."
    ),
}


class TestEveryRequiredGateIsAccountedFor:
    def test_every_required_gate_is_mapped_or_declared_a_gap(self, required_gates):
        """No gate may be silently unaccounted for — the failure mode `specs` hit."""
        unaccounted = sorted(g for g in required_gates if g not in GATE_TO_ROOT_TARGET and g not in KNOWN_GAPS)
        assert not unaccounted, (
            f"ci_required_targets entries with no root mapping and no declared gap: "
            f"{unaccounted}. Add a root target and map it in GATE_TO_ROOT_TARGET, or "
            "declare it in KNOWN_GAPS with a reason."
        )

    def test_mapped_gates_resolve_to_targets_reachable_from_ci(self, required_gates, ci_reachable, makefile):
        """A mapping that points at a target `make ci` never reaches is not coverage."""
        broken = {}
        for gate in required_gates:
            target = GATE_TO_ROOT_TARGET.get(gate)
            if target is None:
                continue
            if not _make_prerequisites(makefile, target) and not re.search(rf"^{re.escape(target)}:", makefile, re.M):
                broken[gate] = f"root target '{target}' does not exist"
            elif target not in ci_reachable:
                broken[gate] = f"root target '{target}' is not reachable from `make ci`"
        assert not broken, f"required gates mapped to unreachable root targets: {broken}"

    @pytest.mark.parametrize("gate", sorted(GATE_TO_EVIDENCE))
    def test_mapped_gate_recipe_still_does_its_work(self, gate, makefile, required_gates):
        """Reachability is not enforcement: prove the recipe still runs something.

        Emptying `validate` deletes the only invocation of the protected-path gate
        while leaving its name wired into `ci` — reachability alone stays green.
        """
        assert gate in required_gates, f"GATE_TO_EVIDENCE covers a gate the policy dropped: {gate}"
        target = GATE_TO_ROOT_TARGET[gate]
        evidence = _evidence_text(makefile, target)
        assert re.search(GATE_TO_EVIDENCE[gate], evidence), (
            f"gate '{gate}' maps to target '{target}', but nothing in that target's "
            f"recipe (or its prerequisites') matches {GATE_TO_EVIDENCE[gate]!r}. The "
            "target name is wired in but the work is gone."
        )

    def test_evidence_map_covers_every_mapped_gate(self):
        """A mapped gate with no evidence rule is unverified substance."""
        unverified = sorted(set(GATE_TO_ROOT_TARGET) - set(GATE_TO_EVIDENCE))
        assert not unverified, f"mapped gates with no evidence assertion: {unverified}"

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

    def test_every_declared_gap_has_a_substantive_reason(self):
        # A loop, not a parametrize: an empty KNOWN_GAPS is the healthy state,
        # and parametrizing over it produced a "got empty parameter set" skip
        # that the Python zero-skip gate would have to waive (R-TDH-19).
        for gate, reason in sorted(KNOWN_GAPS.items()):
            assert len(reason.strip()) > 40, f"KNOWN_GAPS['{gate}'] needs a real reason, not a placeholder"

    def test_partial_coverage_notes_describe_mapped_gates(self, required_gates):
        """Loops rather than parametrizes: an empty dict must not become a skipped test."""
        for gate in sorted(PARTIAL_COVERAGE):
            assert gate in GATE_TO_ROOT_TARGET, (
                f"PARTIAL_COVERAGE['{gate}'] describes a gate that is not mapped as covered"
            )
            assert gate in required_gates, f"PARTIAL_COVERAGE['{gate}'] describes a gate the policy no longer requires"
            assert len(PARTIAL_COVERAGE[gate].strip()) > 40, (
                f"PARTIAL_COVERAGE['{gate}'] needs a real reason, not a placeholder"
            )

    def test_specs_strict_tier_waiver_is_removed_once_the_root_pipeline_enforces_it(self):
        """Falsifiable in the direction that matters: the waiver must not outlive the gap.

        A stale "we don't enforce this" note is worse than none -- it tells a
        reviewer to stop looking. Once anything in the root pipeline sets
        REQUIRE_STRICT_SPEC_VALIDATOR=1, the strict tier *is* enforced and this
        entry has to go, so the assertion is written to fail at that moment.
        """
        enforced_at_root = any(
            "REQUIRE_STRICT_SPEC_VALIDATOR=1" in text
            for text in [*_root_workflow_texts(), ROOT_MAKEFILE.read_text(encoding="utf-8")]
        )
        assert enforced_at_root == ("specs" not in PARTIAL_COVERAGE), (
            "the root pipeline now sets REQUIRE_STRICT_SPEC_VALIDATOR=1; drop the PARTIAL_COVERAGE['specs'] waiver"
            if enforced_at_root
            else "the strict spec tier is unenforced at root but no longer declared in PARTIAL_COVERAGE['specs']"
        )
