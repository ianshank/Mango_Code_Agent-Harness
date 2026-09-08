"""Scope, classification and anti-vacuity tests for the traceability gate.

The defect these pin (R-GEA-1) is not "the gate failed"; it is that the gate
*passed* for a reason unrelated to what it claims to check. `check_traceability`
resolved its config and every glob against the process CWD, `make validate` runs
it from `harness/node`, and so it read 6 requirement IDs while `docs/specs/` held
412 sharing not one member with them — and printed
`traceability: passed (6 requirements)`.

Three properties are asserted here, and each fails closed:

* the run resolves against an explicit workspace, and a repository-scoped run
  clears the policy's discovered-ID floor, so pointing the gate at the wrong tree
  raises instead of passing (R-GEA-1, R-GEA-4);
* a document is graded strict unless it declares otherwise, and an unrecognised
  declaration raises rather than falling into the permissive branch, so a typo
  cannot silently exempt a contract spec from citation (R-GEA-1b);
* the contract-spec citation backlog stays at or under the policy ratchet, which
  may only be lowered.

The class-logic cases are built as temp workspaces rather than read from real
specs: a test that depends on today's spec corpus asserts the corpus, not the
grading rule, and goes red for edits that have nothing to do with either.

Every threshold is read from `governance-policy.json`; none is restated here.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# The package re-exports `check_traceability` as a *function*, shadowing the
# submodule name, so `from ... import check_traceability` yields the callable.
# Import the module explicitly to reach its internals.
ct = importlib.import_module("harness.shared.governance.check_traceability")

REPO_ROOT = Path(__file__).resolve().parents[3]
NODE_STACK = REPO_ROOT / "harness" / "node"

#: The highest value `traceability.max_uncited_contract_requirement_ids` has ever been
#: accepted at (DEC-065). This is deliberately a *second, independent* copy of that
#: number rather than a read of the policy, and that duplication is the whole control:
#: with enforcement and its own test both reading the policy, raising the policy from
#: 222 to 223 while adding another uncited requirement stayed green, so "may only be
#: lowered" was prose that nothing checked. Lowering the policy is a one-file edit and
#: passes freely; raising it above this line fails, and raising this line is a visible
#: edit to an accepted decision's recorded high-water mark rather than a threshold tweak.
#: Found by review on PR #120.
ACCEPTED_RATCHET_CEILING = 203

pytestmark = pytest.mark.governance


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    """The `traceability` section of `governance-policy.json`, read once."""
    section: dict[str, Any] = ct._traceability_policy()
    return section


@pytest.fixture(scope="module")
def marker(policy: dict[str, Any]) -> str:
    return str(policy["spec_class_marker"])


@pytest.fixture(scope="module")
def program_plan_class(policy: dict[str, Any]) -> str:
    return str(policy["program_plan_class"])


def _workspace(
    root: Path,
    *,
    specs: dict[str, str],
    scope: str | None = None,
    impl: str = "",
    tests: str = "",
) -> Path:
    """Build a self-contained workspace and return its root.

    ``scope`` is omitted from the config entirely when ``None`` so the fixture can
    express a *legacy* per-stack config — the shape every existing
    ``.governance/traceability.json`` has — rather than one that opts out by
    declaring a value.
    """
    (root / ".governance").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "specs").mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    for name, text in specs.items():
        (root / "docs" / "specs" / name).write_text(text, encoding="utf-8")
    (root / "src" / "impl.py").write_text(impl, encoding="utf-8")
    (root / "tests" / "test_impl.py").write_text(tests, encoding="utf-8")

    config: dict[str, Any] = {
        "spec_globs": ["docs/specs/**/*.md"],
        "implementation_globs": ["src/**/*.py"],
        "test_globs": ["tests/**/*.py"],
    }
    if scope is not None:
        config["scope"] = scope
    (root / ct.TRACEABILITY_CONFIG).write_text(json.dumps(config), encoding="utf-8")
    return root


def _many_ids(count: int, prefix: str = "R-FIXTURE") -> str:
    """A spec body declaring ``count`` distinct requirement IDs."""
    return "\n".join(f"- {prefix}-{index}: fixture requirement" for index in range(count))


# --------------------------------------------------------------------------- #
# AC-GEA-1 — the workspace is explicit, and an empty corpus fails closed.
# --------------------------------------------------------------------------- #


def test_traceability_workspace_scope(tmp_path: Path, policy: dict[str, Any]) -> None:
    """R-GEA-1: the run resolves against ``--workspace``, not the process CWD.

    The repository-scoped run reads the real ``docs/specs/`` corpus and clears the
    policy's anti-vacuity floor; a workspace holding no spec files raises rather
    than reporting a satisfied property (R-GEA-4).
    """
    floor = int(policy["min_discovered_requirement_ids"])

    result = ct.analyse_traceability(REPO_ROOT, policy)
    assert result.scope == ct.REPOSITORY_SCOPE, "the root config must declare a repository scope"
    assert len(result.discovered) >= floor, (
        f"repository-scoped run discovered {len(result.discovered)} requirement ID(s), "
        f"below the policy floor of {floor}: the globs are pointed at the wrong tree"
    )
    # The measurement is workspace-relative, not CWD-relative: the same call from
    # inside the Node stack must read a different, far smaller corpus.
    node_result = ct.analyse_traceability(NODE_STACK, policy)
    assert len(node_result.discovered) < len(result.discovered)
    assert not (node_result.discovered & result.discovered), (
        "the two corpora were disjoint when the defect was measured; if they now "
        "intersect this assertion is stale rather than wrong"
    )

    empty = _workspace(tmp_path / "empty", specs={})
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(empty)
    assert "no spec files matched" in str(excinfo.value)


def test_workspace_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backwards compatibility: no ``--workspace`` behaves exactly as before.

    The per-stack shims call ``check_traceability()`` with no argument during the
    DEC-056 shim window, so the default has to stay the process CWD.
    """
    root = _workspace(
        tmp_path,
        specs={"s.md": "R-ONE is required"},
        impl="# covers R-ONE",
        tests="# tests R-ONE",
    )
    monkeypatch.chdir(root)
    ct.check_traceability()
    assert "traceability: passed (1 requirements)" in capsys.readouterr().out


def test_specs_without_requirement_ids_fail_closed(tmp_path: Path) -> None:
    """R-GEA-4: an empty ID set is a broken extractor, not a satisfied property."""
    root = _workspace(tmp_path, specs={"s.md": "prose with no identifiers"})
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(root)
    assert "specs contain no requirement IDs" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# AC-GEA-1c — the strict class is the default and an unknown class raises.
# --------------------------------------------------------------------------- #


def test_spec_class_defaults_to_the_strict_branch(
    tmp_path: Path,
    policy: dict[str, Any],
    marker: str,
    program_plan_class: str,
) -> None:
    """R-GEA-1b: declared nothing is strict; ``program-plan`` is counted, not required.

    Built on temp workspaces on purpose — the grading rule is what is under test,
    not the class any real document happens to declare today.
    """
    default_class = str(policy["default_spec_class"])

    undeclared = _workspace(
        tmp_path / "undeclared",
        specs={"contract.md": "R-STRICT-1 is required"},
    )
    result = ct.analyse_traceability(undeclared, policy)
    assert set(result.ids_by_class) == {default_class}
    assert "R-STRICT-1" in result.gaps, "a document declaring no class must be graded strict"
    assert result.gaps["R-STRICT-1"] == ["implementation", "tests"]
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(undeclared)
    assert str(excinfo.value).startswith("traceability: requirement IDs missing implementation and/or test citation: ")

    plan = _workspace(
        tmp_path / "plan",
        specs={"roadmap.md": f"> **{marker}** {program_plan_class}\n\n- R-PLANNED-1 is scheduled"},
    )
    plan_result = ct.analyse_traceability(plan, policy)
    assert set(plan_result.ids_by_class) == {program_plan_class}
    assert "R-PLANNED-1" in plan_result.discovered, "a program plan's IDs are still discovered and reported"
    assert "R-PLANNED-1" in plan_result.plan_only_gaps
    assert plan_result.gaps == {}, "a roadmap item has nothing to cite until it is done"
    ct.check_traceability(plan)  # no SystemExit

    unknown = _workspace(
        tmp_path / "unknown",
        specs={"typo.md": f"> **{marker}** program_plan\n\n- R-TYPO-1 is required"},
    )
    with pytest.raises(SystemExit) as excinfo:
        ct.analyse_traceability(unknown, policy)
    message = str(excinfo.value)
    assert "unrecognised spec class" in message
    assert "program_plan" in message, "the failure must name the value it rejected"


def test_a_marker_with_no_class_is_rejected_not_read_as_undeclared(
    tmp_path: Path, policy: dict[str, Any], marker: str
) -> None:
    """A malformed declaration is a defect, and the permissive read of it is silence."""
    root = _workspace(tmp_path, specs={"blank.md": f"> **{marker}**\n\n- R-BLANK-1 is required"})
    with pytest.raises(SystemExit) as excinfo:
        ct.analyse_traceability(root, policy)
    assert "unrecognised spec class" in str(excinfo.value)


def test_a_contract_spec_outranks_a_roadmap_that_mentions_the_same_id(
    tmp_path: Path, policy: dict[str, Any], marker: str, program_plan_class: str
) -> None:
    """The permissive class must not be reachable by naming an ID in a roadmap.

    Otherwise the exemption is available to anyone who writes the ID into a
    program plan, which is the class distinction's own bypass.
    """
    root = _workspace(
        tmp_path,
        specs={
            "contract.md": "- R-SHARED-1 is required",
            "roadmap.md": f"> **{marker}** {program_plan_class}\n\n- R-SHARED-1 is also scheduled",
        },
    )
    result = ct.analyse_traceability(root, policy)
    assert "R-SHARED-1" in result.gaps
    assert "R-SHARED-1" not in result.plan_only_gaps


# --------------------------------------------------------------------------- #
# AC-GEA-1b — the ratchet, and the floor that stops it passing vacuously.
# --------------------------------------------------------------------------- #


def test_traceability_gaps_are_cited_or_recorded(
    tmp_path: Path, policy: dict[str, Any], marker: str, program_plan_class: str
) -> None:
    """The contract-spec backlog is at or under the ratchet, which may only be lowered.

    The mechanism is proven on fixtures *before* the real corpus is measured. A
    suite that asserts the live backlog first stops there when the backlog is over
    the ratchet, and then the ratchet's own machinery — the message, the delta, the
    passing path — is untested exactly when it matters most.
    """
    ratchet = int(policy["max_uncited_contract_requirement_ids"])
    floor = int(policy["min_discovered_requirement_ids"])

    over = _workspace(
        tmp_path / "over",
        specs={"contract.md": _many_ids(floor + 1)},
        scope=ct.REPOSITORY_SCOPE,
    )
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(over)
    message = str(excinfo.value)
    assert "may only be lowered" in message
    assert f"exceeding the ratchet of {ratchet}" in message
    assert f"by {floor + 1 - ratchet}" in message, "the delta says how far the backlog has to fall"
    assert "R-FIXTURE-0: absent from implementation and tests" in message

    under = _workspace(
        tmp_path / "under",
        specs={
            "contract.md": _many_ids(floor + 1),
            "roadmap.md": f"> **{marker}** {program_plan_class}\n\n{_many_ids(1, 'R-ROADMAP')}",
        },
        scope=ct.REPOSITORY_SCOPE,
        impl=_many_ids(floor + 1),
        tests=_many_ids(floor + 1),
    )
    ct.check_traceability(under)  # no SystemExit

    result = ct.analyse_traceability(REPO_ROOT, policy)
    assert result.plan_only_gaps, (
        "no program-plan-only gaps were found; the class distinction would be "
        "vacuous and this suite would prove nothing about it"
    )
    assert len(result.gaps) <= ratchet, (
        f"{len(result.gaps)} contract-spec requirement ID(s) are uncited against a "
        f"ratchet of {ratchet}. Cite them, or record an accepted exemption — the "
        f"ratchet in governance-policy.json may only be lowered, never raised."
    )


def test_the_repository_floor_rejects_a_gate_pointed_at_the_wrong_tree(tmp_path: Path, policy: dict[str, Any]) -> None:
    """R-GEA-4 / AC-GEA-1: the failure mode was "found the wrong two files".

    Both emptiness guards passed while the gate read 6 IDs of a 412-ID corpus. Only
    a floor on the discovered count catches that, and it applies exactly where a
    config claims to cover the repository.
    """
    floor = int(policy["min_discovered_requirement_ids"])
    root = _workspace(
        tmp_path,
        specs={"s.md": _many_ids(floor - 1)},
        scope=ct.REPOSITORY_SCOPE,
        impl=_many_ids(floor - 1),
        tests=_many_ids(floor - 1),
    )
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(root)
    message = str(excinfo.value)
    assert f"below the floor of {floor}" in message
    assert "min_discovered_requirement_ids" in message
    assert str(root.resolve()) in message, "the failure must name the workspace it read"


def test_the_repository_run_reports_the_count_and_the_headroom(
    tmp_path: Path, policy: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Lowering the ratchet has to be obvious from the passing run, not archaeology."""
    floor = int(policy["min_discovered_requirement_ids"])
    ratchet = int(policy["max_uncited_contract_requirement_ids"])
    body = _many_ids(floor + 1)
    root = _workspace(
        tmp_path,
        specs={"s.md": body},
        scope=ct.REPOSITORY_SCOPE,
        impl=body,
        tests=body,
    )
    ct.check_traceability(root)
    out = capsys.readouterr().out
    assert f"traceability: passed ({floor + 1} requirements;" in out
    assert f"0 uncited contract ID(s) against a ratchet of {ratchet}" in out
    assert f"headroom {ratchet}" in out
    assert "lower traceability.max_uncited_contract_requirement_ids to 0" in out


# --------------------------------------------------------------------------- #
# Backwards compatibility: legacy configs declare no scope and are unchanged.
# --------------------------------------------------------------------------- #


def test_a_legacy_config_without_a_scope_key_is_not_subject_to_the_floor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """This is the half that keeps the change backwards compatible.

    Every existing per-stack `.governance/traceability.json` declares no scope. If
    the floor applied to them they would all fail on their first run, which is the
    outcome that gets a gate switched off.
    """
    body = "R-LEGACY-1 is required"
    root = _workspace(tmp_path, specs={"s.md": body}, impl=body, tests=body)
    ct.check_traceability(root)
    assert "traceability: passed (1 requirements)" in capsys.readouterr().out


def test_the_node_stack_invocation_still_passes_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """`make validate` runs the gate from `harness/node`; that call must not move.

    Its config is untouched by this change, and leaving it untouched is what proves
    the workspace flag is additive. The count is asserted against the config's own
    corpus rather than a literal, so this stays a compatibility check and does not
    become a second pin on the Node stack's spec content.
    """
    ct.check_traceability(NODE_STACK)
    out = capsys.readouterr().out
    expected = len(ct.analyse_traceability(NODE_STACK, ct._traceability_policy()).discovered)
    assert f"traceability: passed ({expected} requirements)" in out


def test_main_accepts_the_workspace_flag_and_ignores_unknown_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Existing callers pass flags this entry point never read; they still must not
    become a usage error that replaces the gate's verdict with argparse's."""
    body = "R-CLI-1 is required"
    root = _workspace(tmp_path, specs={"s.md": body}, impl=body, tests=body)
    ct.main(["--workspace", str(root), "--req-files", "docs/reqs.md"])
    assert "traceability: passed (1 requirements)" in capsys.readouterr().out

    monkeypatch.chdir(root)
    ct.main([])
    assert "traceability: passed (1 requirements)" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The policy read itself fails closed, and diagnostics never fail the gate.
# --------------------------------------------------------------------------- #


def test_a_policy_without_a_traceability_section_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gate that silently defaults its own thresholds is not a configured gate."""
    stub = tmp_path / "governance-policy.json"
    stub.write_text(json.dumps({"schema_version": "1"}), encoding="utf-8")
    monkeypatch.setattr(ct, "POLICY_PATH", stub)
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(tmp_path)
    assert "declares no `traceability` policy section" in str(excinfo.value)


def test_a_missing_policy_key_names_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed on a key rather than substituting a default for it."""
    stub = tmp_path / "governance-policy.json"
    stub.write_text(json.dumps({"traceability": {}}), encoding="utf-8")
    monkeypatch.setattr(ct, "POLICY_PATH", stub)
    root = _workspace(tmp_path / "ws", specs={"s.md": "R-KEY-1"})
    with pytest.raises(SystemExit) as excinfo:
        ct.check_traceability(root)
    assert "traceability.default_spec_class is not declared" in str(excinfo.value)


@pytest.fixture
def debug_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Raise the gate logger to DEBUG for one test and put it back afterwards.

    The logger is module-scoped and shared, so leaving it at DEBUG would spray
    diagnostics through every later test in the process — the same
    leaks-into-the-next-test defect that made `run_script` use `monkeypatch` for
    its chdir rather than a bare `os.chdir`.
    """
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    reloaded = ct._gate_logger()
    previous_level = reloaded.level
    previous_handlers = [(handler, handler.level) for handler in reloaded.handlers]
    reloaded.setLevel("DEBUG")
    for handler, _ in previous_handlers:
        handler.setLevel("DEBUG")
    try:
        yield
    finally:
        reloaded.setLevel(previous_level)
        for handler, level in previous_handlers:
            handler.setLevel(level)


def test_debug_diagnostics_name_the_workspace_scope_and_classes(
    tmp_path: Path,
    policy: dict[str, Any],
    marker: str,
    program_plan_class: str,
    debug_logging: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The docstring promises these; a glob scoped to one stack is found by reading them."""
    root = _workspace(
        tmp_path,
        specs={"roadmap.md": f"> **{marker}** {program_plan_class}\n\n- R-DEBUG-1 is scheduled"},
        scope=ct.REPOSITORY_SCOPE,
    )
    ct.analyse_traceability(root, policy)
    err = capsys.readouterr().err
    assert str(root.resolve()) in err
    assert str(ct.TRACEABILITY_CONFIG) in err
    assert f"scope {ct.REPOSITORY_SCOPE!r}" in err
    assert f"per-class ID counts: {{{program_plan_class!r}: 1}}" in err
    assert "spec_globs" in err and "matched" in err


def test_the_logger_degrades_instead_of_failing_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Diagnostics must never be able to fail a gate, so an import problem is a no-op."""
    import builtins

    real_import = builtins.__import__

    def explode(name: str, *args: object, **kwargs: object) -> object:
        if "json_logging" in name:
            raise ImportError("simulated missing shared package")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", explode)
    degraded = ct._gate_logger()
    assert isinstance(degraded, logging.Logger)
    assert degraded.propagate is False
    degraded.debug("must not raise")


def test_the_ratchet_may_only_be_lowered(policy: dict[str, Any]) -> None:
    """The configured ratchet may never exceed the accepted high-water mark (C-GEA-4).

    Without this, `max_uncited_contract_requirement_ids` is a configurable ceiling and
    not a ratchet: the gate and every test that exercises it read the same policy key,
    so raising the key alongside a new uncited requirement keeps the suite green and the
    backlog grows behind a number that moved to accommodate it. DEC-065 claims the value
    "may only be lowered"; this is what makes that claim enforceable rather than stated.
    """
    configured = int(ct._policy_value(policy, "max_uncited_contract_requirement_ids"))
    assert configured <= ACCEPTED_RATCHET_CEILING, (
        f"traceability.max_uncited_contract_requirement_ids is {configured}, above the accepted "
        f"high-water mark of {ACCEPTED_RATCHET_CEILING} recorded here and in DEC-065. The ratchet "
        "may only be lowered as citations land. Raising it means accepting a larger backlog, which "
        "is a decision to record, not a threshold to edit."
    )


def test_the_ceiling_is_not_slack(policy: dict[str, Any]) -> None:
    """A ceiling far above the configured value would make the guard above unfalsifiable.

    The two numbers are meant to move together downward. If the policy is lowered and this
    ceiling is not, the guard still passes but stops constraining anything real, which is
    the stale-waiver shape C-GEA-4 is about — so the drift itself is the finding.
    """
    configured = int(ct._policy_value(policy, "max_uncited_contract_requirement_ids"))
    assert ACCEPTED_RATCHET_CEILING - configured <= 0, (
        f"the accepted ceiling ({ACCEPTED_RATCHET_CEILING}) now sits above the configured ratchet "
        f"({configured}); lower ACCEPTED_RATCHET_CEILING to match, so the guard keeps constraining "
        "the value it is meant to constrain."
    )


class TestCitationIsWholeIdentifier:
    """A longer requirement ID must not satisfy a shorter one (R-GEA-1, R-GEA-4).

    Discovery has always been anchored (`REQ` is `\\b([CR]-[A-Za-z0-9_-]+)\\b`)
    while the citation half used a plain `in`, so the two halves of this gate
    disagreed about what an identifier is and the citation half was the lenient
    one. Measured consequence before the fix: `C-GEA-4` scored as cited by tests
    solely because `AC-GEA-4` appears in them. A pass condition satisfiable by a
    *different* requirement is the defect class this module was rewritten to fix,
    reappearing inside the fix. Found by audit on PR #120.
    """

    def test_a_longer_id_does_not_satisfy_a_shorter_one(self) -> None:
        assert ct._cited("C-GEA-4", "see C-GEA-4 here")
        assert not ct._cited("C-GEA-4", "see AC-GEA-4 here")

    def test_a_suffixed_id_does_not_satisfy_its_prefix(self) -> None:
        """`R-GEA-1b` is a distinct requirement from `R-GEA-1`."""
        assert not ct._cited("R-GEA-1", "R-GEA-1b is cited here")
        assert ct._cited("R-GEA-1b", "R-GEA-1b is cited here")

    def test_ordinary_punctuation_still_counts_as_a_citation(self) -> None:
        """The rule must not be so strict that real citations stop counting."""
        for text in ("R-GEA-6, and more", "`R-GEA-6`", "(R-GEA-6)", "R-GEA-6.", "R-GEA-6\n"):
            assert ct._cited("R-GEA-6", text), text

    def test_absences_uses_the_anchored_match(self) -> None:
        """The behaviour above reaches the verdict, not just the helper."""
        absent = ct._absences(["C-GEA-4"], "AC-GEA-4 in implementation", "AC-GEA-4 in tests")
        assert absent == {"C-GEA-4": ["implementation", "tests"]}
        assert ct._absences(["C-GEA-4"], "C-GEA-4 here", "C-GEA-4 there") == {}
