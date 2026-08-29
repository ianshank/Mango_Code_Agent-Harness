"""An invariant whose enforcement mechanism has no caller enforces nothing.

``harness/CONTRACT.md`` warns about this shape for path patterns: *"a pattern
written for a repository layout that does not exist matches nothing and protects
nothing -- silently."* ``test_protected_path_liveness.py`` turned that insight
into a gate. The same failure exists one layer up and had no gate at all:
``INV-8`` required generated code to execute through an approved execution
broker, and ``ExecutionBroker`` had **zero production callers** while
``execute_command`` ended at ``FAILED: Execution engine not fully implemented``.
The invariant was published as an unqualified MUST and enforced by nothing.

This gate asserts on **resolved imports**, parsed from the AST rather than
grepped: a text scan is satisfied by the symbol appearing in a comment, which is
precisely the false assurance being guarded against.

Spec: ``docs/specs/agent-containment.md`` (C-AC-3).
"""

from __future__ import annotations

import ast
import itertools
import re
from pathlib import Path

import pytest

from harness.shared.tests._helpers import CONTROL_PLANE, HARNESS, REPO, SHARED

pytestmark = pytest.mark.governance

CONTRACT = HARNESS / "CONTRACT.md"

#: Invariant -> (module that defines the mechanism, symbol that must be reached).
#: Only invariants whose enforcement is a concrete Python symbol appear here.
#: Claiming to check one that is enforced elsewhere -- INV-2 is a Vitest/JUnit
#: gate, INV-4 is a shell installer -- would be the same false assurance in a
#: different place.
INVARIANT_MECHANISMS = {
    "INV-8": ("harness.shared.governance.broker", "ExecutionBroker"),
    "INV-9": ("harness.shared.governance.broker", "ExecutionBroker"),
    "INV-16": ("harness.shared.cognitive_signal", "CognitiveSignalSink"),
    "INV-17": ("harness.shared.plan_rules", "check_plan"),
}

#: Invariant -> the gate that fully enforces every clause of it. Each reason names
#: a selector that can be run. A reason naming a check that does not exist, or
#: claiming coverage a check does not provide, is the false assurance this module
#: exists to catch -- so each entry below was confirmed by running it.
ENFORCED_ELSEWHERE = {
    "INV-1": (
        "make secrets refuses to run without gitleaks or .gitleaks.toml, and scans "
        "both the working tree and full history. The third clause -- a config that "
        "declares no ruleset scans nothing, because --config replaces the built-in "
        "rules rather than extending them -- is covered by "
        "test_lint_config_liveness.TestGitleaksActuallyScans::test_the_config_declares_a_ruleset, "
        "which parses the TOML rather than grepping it."
    ),
    "INV-4": (
        "test_harness.py::test_hook_installer_uses_effective_path_and_refuses_foreign_overwrite "
        "covers both clauses in one test: it sets core.hooksPath to a non-default "
        "directory and asserts the hook lands there, then replaces the hook with "
        "foreign content and asserts a second install exits non-zero rather than "
        "overwriting it silently."
    ),
    "INV-6": (
        "test_harness.py::test_external_root_of_trust_verifies_protected_digests runs "
        "control-plane/verify_repository.py against a root-of-trust.json holding the "
        "expected policy digest, so the digest genuinely lives outside the governed "
        "tree. validate_policy.py additionally fails closed unless "
        "external_root_of_trust_required is true."
    ),
    "INV-15": (
        "test_neurosym_synthesis.py::test_inv15_lats_disabled_by_default asserts "
        "lats_enabled is False by identity, so any truthy value fails. The module "
        "carries the neurosym marker, which the default -m 'not live' does not "
        "deselect, so it runs in make ci via the coverage suite."
    ),
}

#: Invariant -> what is enforced, and what is not. Same idiom as
#: test_ci_gate_coverage.py's PARTIAL_COVERAGE: a partially-covered control stays
#: visible as partial rather than being rounded up to enforced. An invariant is
#: not atomic -- several here have clauses with different enforcement status, and
#: recording one verdict for the whole would be exactly the overclaim this gate
#: is meant to prevent.
PARTIALLY_ENFORCED = {
    "INV-2": (
        "COVERED: the Node half -- governance/verify_zero_skips.py reads the Vitest "
        "JSON and fails on any skip lacking a live decision-backed waiver, wired as "
        "make verify-zero-skips. NOT COVERED: the JVM half this invariant also names "
        "('JVM listener records evidence and Gradle performs the failing assertion'). "
        "The root Makefile defines no JVM_DIR; harness/jvm/Makefile is an adopter "
        "template invoked only by its own workflow, which GitHub never runs."
    ),
    "INV-3": (
        "COVERED: remotes.py is the single normalizer, invoked at root by make "
        "remotes and reused by the PreToolUse guard and the pre-push scan. NOT "
        "COVERED: the JVM leg of 'used by Node, JVM, PreToolUse, pre-push and CI' -- "
        "no root target runs anything under harness/jvm, so the claim that the JVM "
        "stack shares this normalizer is untested here."
    ),
    "INV-5": (
        "COVERED: test_ci_gate_coverage.py maps every ci_required_targets entry to a "
        "root target make ci actually reaches, and detects raw reconstructions. NOT "
        "COVERED: by that gate's own declarations -- audit sits in KNOWN_GAPS with no "
        "root equivalent, and specs sits in PARTIAL_COVERAGE because the strict tier "
        "never runs at root. INV-5 says CI invokes *every* policy-required gate; two "
        "are declared exceptions."
    ),
    "INV-7": (
        "COVERED: the delegation clause -- validate_agent_policy.py fails closed "
        "unless default_deny is true, every role's delegation_depth is within "
        "max_delegation_depth, each role's approval-gated actions are a subset of "
        "its allowed actions, and no role may self-modify policy. NOT COVERED: the "
        "evidence clause, 'every side effect has actor/trace/policy evidence'. "
        "test_policy_consistency.DECLARED_NOT_YET_ENFORCED already records that "
        "evidence_manifest.py is live but nothing cross-checks its coverage against "
        "agent_defaults.evidence_required_for."
    ),
    "INV-10": (
        "COVERED: that a DENY is produced for the right reasons -- "
        "test_governance_broker.py asserts denial for an unknown agent identity, a "
        "role lacking the action, and an approval-gated action without approval. NOT "
        "COVERED: terminality itself, 'a model cannot override it'. Nothing exercises "
        "a candidate being revived after DENY, because the repair loop that could "
        "attempt it does not exist (see INV-11/INV-12). The clause is currently true "
        "only for want of a mechanism to violate it, which is not the same as tested."
    ),
}

#: Invariants nothing enforces, each with a reason. The contract line for each
#: must carry one of ACCEPTED_STATUS_PHRASES, so the published text and this
#: classification cannot disagree.
#:
#: This dict was empty until the completeness test below existed, and its comment
#: read "Empty, and it should stay that way." That was never a measurement: the
#: parametrization ran over INVARIANT_MECHANISMS and the only set difference was
#: dict-minus-contract, so an invariant in neither dict was simply never examined.
#: It was empty because nothing looked, not because nothing was unenforced.
DORMANT_INVARIANTS: dict[str, str] = {
    "INV-11": (
        "Requires a normalized critique and immutable evidence ID for every repair "
        "attempt. There are no repair attempts: no critique.py, no repair_loop.py, "
        "and no occurrence of 'repair' or 'critique' in the orchestrator. The only "
        "thing touching it asserts synthesis.critique_schema_version == '1.0' -- a "
        "string in a JSON file no production path reads. Lands with openspec "
        "Milestone 5; DEC-NS-002, which proposes that schema, is still BLOCKING."
    ),
    "INV-12": (
        "Requires repair loops to stop at the configured budget and produce FAILED "
        "or BLOCKED. There is no repair loop to bound. max_repair_cycles is asserted "
        "to be a bounded positive integer, which checks the policy value's shape and "
        "not any loop's behaviour. Lands with openspec Milestone 5."
    ),
    "INV-13": (
        "Requires a verified result to carry policy, test, sandbox, source and "
        "tool-version digests. The contract already states this is not currently "
        "satisfiable: ProcessBackend contains but does not isolate -- it confines "
        "neither the filesystem nor the network -- so there is no sandbox digest to "
        "record, and no result claims INV-13 (DEC-010). Isolation is a later "
        "capability profile that cannot be exercised on this repository's runners."
    ),
    "INV-14": (
        "Requires exportable traces to be redacted and marked approved training "
        "candidates before dataset export. No dataset export path exists, so there "
        "is nothing to redact or mark. Lands with openspec Milestone 6, which "
        "defines the export workflow."
    ),
}

#: Wordings accepted as an honest status marker on a dormant invariant's contract
#: line. INV-13 says "Not currently satisfiable" and spells out why; rewording it
#: to match a single literal would cost that explanation, so the set is declared
#: rather than the phrase hard-coded.
ACCEPTED_STATUS_PHRASES = ("not yet enforced", "not currently satisfiable")

#: Every invariant this module has an opinion about, in any category.
_ALL_CLASSIFIED = (
    set(INVARIANT_MECHANISMS)
    | set(ENFORCED_ELSEWHERE)
    | set(PARTIALLY_ENFORCED)
    | set(DORMANT_INVARIANTS)
)


def _first_party_modules() -> list[Path]:
    """Non-test first-party Python, i.e. the code that can hold a live caller."""
    found: list[Path] = []
    for root in (SHARED, CONTROL_PLANE, HARNESS / "api_server"):
        for path in root.rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


def _imports(path: Path) -> set[tuple[str, str]]:
    """(module, name) pairs a file imports. AST, not text: a symbol named in a
    comment or a docstring is not a caller."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - the compat gate would have failed first
        return set()

    package = ".".join(path.relative_to(REPO).with_suffix("").parts)
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # relative import: resolve against this file's package
                parent = package.rsplit(".", node.level)[0]
                module = f"{parent}.{module}" if module else parent
            for alias in node.names:
                pairs.add((module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pairs.add((alias.name, ""))
    return pairs


def _live_callers(module: str, symbol: str) -> list[str]:
    """Modules that import ``symbol``, excluding the one that defines it and its
    own package re-exports -- a package `__init__` that re-exports a symbol is not
    a caller, it is the same layer."""
    defining = module.replace(".", "/")
    callers = []
    for path in _first_party_modules():
        rel = str(path.relative_to(REPO).with_suffix(""))
        if rel == defining or rel.endswith("/__init__"):
            continue
        if (module, symbol) in _imports(path):
            callers.append(rel)
    return callers


def _declared_invariants() -> set[str]:
    return set(re.findall(r"\*\*(INV-\d+):\*\*", CONTRACT.read_text(encoding="utf-8")))


class TestTheScanWorks:
    """Positive controls. Without these, a CONTRACT.md reformat or a moved
    directory would make every assertion below vacuously true."""

    def test_the_contract_declares_invariants(self) -> None:
        """A floor only, to catch a CONTRACT.md reformat that breaks the scan.

        It is deliberately not a completeness claim: an invariant added with no
        classification passes this and is caught by
        TestEveryInvariantIsClassified instead.
        """
        assert len(_declared_invariants()) >= 17

    def test_the_module_scan_finds_first_party_code(self) -> None:
        assert len(_first_party_modules()) >= 30

    def test_the_import_parser_resolves_a_known_import(self) -> None:
        pairs = _imports(SHARED / "mango_mas_orchestrator.py")
        assert ("harness.shared.governance.broker", "ExecutionBroker") in pairs


class TestEveryDeclaredMechanismIsReached:
    @pytest.mark.parametrize(("invariant", "target"), sorted(INVARIANT_MECHANISMS.items()))
    def test_mechanism_has_a_live_caller(self, invariant: str, target: tuple[str, str]) -> None:
        module, symbol = target
        if invariant in DORMANT_INVARIANTS:
            pytest.skip(f"{invariant} is declared dormant")  # pragma: no cover - dict is empty
        callers = _live_callers(module, symbol)
        assert callers, (
            f"{invariant} names {module}.{symbol} as its enforcement mechanism, and no non-test module "
            f"imports it. An invariant whose mechanism has no caller enforces nothing."
        )

    def test_every_named_invariant_is_one_the_contract_declares(self) -> None:
        unknown = _ALL_CLASSIFIED - _declared_invariants()
        assert not unknown, f"{unknown} are not declared in harness/CONTRACT.md"


class TestEveryInvariantIsClassified:
    """The direction the gate was missing.

    ``test_every_named_invariant_is_one_the_contract_declares`` computed
    dict-minus-contract. The reverse -- contract-minus-dicts -- was never
    computed, so 13 of 17 declared invariants sat in no dict and were never
    examined. That is how INV-11, INV-12 and INV-14 came to be published as
    unqualified MUSTs over capability that does not exist, three lines from
    INV-13, which names *this module* as the gate that should have caught it.

    Same shape as ``test_ci_gate_coverage.py``: every required item is mapped, or
    declared a gap with a reason. Silence is not an option in either direction.
    """

    def test_every_declared_invariant_is_classified(self) -> None:
        unclassified = _declared_invariants() - _ALL_CLASSIFIED
        assert not unclassified, (
            f"{sorted(unclassified)} are declared in harness/CONTRACT.md but classified nowhere. "
            "Add each to INVARIANT_MECHANISMS (an importable symbol with a live caller), "
            "ENFORCED_ELSEWHERE (a named gate covering every clause), PARTIALLY_ENFORCED "
            "(what is covered and what is not), or DORMANT_INVARIANTS (nothing enforces it). "
            "An invariant in none of them is one nobody decided about."
        )

    def test_no_invariant_is_classified_twice(self) -> None:
        """An invariant cannot be both waived and claimed enforced."""
        dicts = {
            "INVARIANT_MECHANISMS": set(INVARIANT_MECHANISMS),
            "ENFORCED_ELSEWHERE": set(ENFORCED_ELSEWHERE),
            "PARTIALLY_ENFORCED": set(PARTIALLY_ENFORCED),
            "DORMANT_INVARIANTS": set(DORMANT_INVARIANTS),
        }
        for left, right in itertools.combinations(sorted(dicts), 2):
            overlap = dicts[left] & dicts[right]
            assert not overlap, f"{sorted(overlap)} appear in both {left} and {right}"

    @pytest.mark.parametrize("name", ["ENFORCED_ELSEWHERE", "PARTIALLY_ENFORCED"])
    def test_each_reason_is_substantive(self, name: str) -> None:
        for invariant, reason in {
            "ENFORCED_ELSEWHERE": ENFORCED_ELSEWHERE,
            "PARTIALLY_ENFORCED": PARTIALLY_ENFORCED,
        }[name].items():
            assert len(reason.strip()) > 80, f"{name}[{invariant!r}] needs a real reason"

    @pytest.mark.parametrize("invariant", sorted(PARTIALLY_ENFORCED))
    def test_a_partial_reason_states_both_halves(self, invariant: str) -> None:
        """A partial recorded without naming the uncovered half is an enforced
        claim wearing a hedge -- the overclaim this category exists to prevent."""
        reason = PARTIALLY_ENFORCED[invariant]
        # Anchored, not a substring test: "NOT COVERED:" *contains* "COVERED:", so
        # `"COVERED:" in reason` is satisfied by the negative marker alone and a
        # reason stating only the uncovered half would pass. Found by mutation.
        assert reason.startswith("COVERED:"), (
            f"PARTIALLY_ENFORCED[{invariant!r}] must open with the covered half"
        )
        assert "NOT COVERED:" in reason, (
            f"PARTIALLY_ENFORCED[{invariant!r}] must name the uncovered half"
        )


class TestWaiversStayHonest:
    def test_a_waiver_would_have_to_name_a_real_invariant(self) -> None:
        assert set(DORMANT_INVARIANTS) <= _declared_invariants()

    def test_a_waiver_would_have_to_carry_a_substantive_reason(self) -> None:
        for invariant, reason in DORMANT_INVARIANTS.items():
            assert len(reason.strip()) > 80, f"{invariant} is waived without a substantive reason"

    def test_a_waived_invariant_may_not_also_be_claimed_enforced(self) -> None:
        """Without this, a waiver leaves ``CONTRACT.md`` asserting enforcement to
        every reader while the gate quietly records that there is none."""
        text = CONTRACT.read_text(encoding="utf-8")
        for invariant in DORMANT_INVARIANTS:
            marker = re.search(rf"\*\*{invariant}:\*\*[^\n]*", text)
            line = marker.group(0).lower() if marker else ""
            assert marker and any(p in line for p in ACCEPTED_STATUS_PHRASES), (
                f"{invariant} is waived here but published as an unqualified requirement in CONTRACT.md"
            )
