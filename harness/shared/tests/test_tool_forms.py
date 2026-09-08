"""Tests for harness/shared/governance/tool_forms.py.

Two defects are pinned here, and each has a mutation case: reverting the fix
under it must turn a named test red, per the ``gate-mutation-proof`` skill.

* DEC-067: ``ruff format .`` was graded ``test_execute`` by program name and
  rewrote protected files in place through the broker.
* DEC-013: the interpreter-invoked forms ``CLAUDE.md`` mandates graded to an
  action no role holds, while the bare forms it forbids ran.

Spec: ``docs/specs/attested-execution-isolation.md`` (R-AEI-1).
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from harness.shared.governance.broker import ExecutionBroker
from harness.shared.governance.command_actions import (
    UNCLASSIFIED_ACTION,
    classify,
    write_targets,
)
from harness.shared.governance.tool_forms import TOOL_FORMS, classify_argv
from harness.shared.governance.verdict import BROKER_BLOCKED
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

#: Roles are read from the authority model rather than restated, so a role that
#: gains or loses an action cannot leave these assertions asserting nothing.
_AGENT_POLICY = json.loads((REPO / "harness" / "shared" / "agent-policy.json").read_text(encoding="utf-8"))


def _actions_for(agent_id: str) -> frozenset[str]:
    for agent in _AGENT_POLICY["agents"]:
        if agent["id"] == agent_id:
            return frozenset(agent["allowed_actions"])
    raise AssertionError(f"{agent_id} is not declared in agent-policy.json")


class TestInterpreterFormsAreModelled:
    """DEC-013: the mandated form must run, and it must not outrank the bare one."""

    @pytest.mark.parametrize(
        "command",
        ["python -m ruff check .", "python -m mypy harness", "python3.12 -m ruff check src"],
    )
    def test_mandated_interpreter_forms_reach_an_action_the_implementer_holds(self, command: str) -> None:
        """R-AEI-1: CLAUDE.md mandates these forms, so they must be executable."""
        assert classify(command).action in _actions_for("implementer")

    def test_the_unmodelled_default_is_held_by_no_role(self) -> None:
        """The premise every denial here rests on."""
        for agent in _AGENT_POLICY["agents"]:
            assert UNCLASSIFIED_ACTION not in agent["allowed_actions"]

    def test_an_unmodelled_module_is_not_guessed_at(self) -> None:
        """`python -m <anything>` must not become executable as a side effect."""
        assert classify("python -m definitely_not_modelled run").action == UNCLASSIFIED_ACTION

    def test_a_script_argument_is_not_read_as_a_module(self) -> None:
        """`python script.py -m ruff` passes `-m` to the script, not the interpreter."""
        assert classify_argv(["python", "script.py", "-m", "ruff"], UNCLASSIFIED_ACTION) is None


class TestRewritingFormsCannotPassAsGateRuns:
    """DEC-067: an in-place formatter presents no redirect for the write policy."""

    @pytest.mark.parametrize(
        "command",
        [
            "ruff format .",
            "ruff check --fix .",
            "ruff check --fix-only src",
            "eslint --fix src",
            "python -m ruff format .",
            "ruff format",
        ],
    )
    def test_an_unbounded_rewrite_is_unmodelled(self, command: str) -> None:
        """R-AEI-1: no enumerable target set means no write the policy can check."""
        assert classify(command).action == UNCLASSIFIED_ACTION

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("ruff format a.py", ["a.py"]),
            ("ruff check --fix src/mod.py", ["src/mod.py"]),
            ("python -m ruff format src/x.py", ["src/x.py"]),
        ],
    )
    def test_a_bounded_rewrite_is_a_write_over_the_files_it_names(self, command: str, expected: list[str]) -> None:
        """The write policy can only refuse targets it is told about."""
        assert classify(command).action == "write"
        assert write_targets(command) == expected

    def test_a_bounded_rewrite_is_denied_to_a_role_without_write(self) -> None:
        """The orchestrator plans and delegates; it does not edit the tree."""
        assert "write" not in _actions_for("orchestrator")
        assert ExecutionBroker().authorize_action("orchestrator", classify("ruff format a.py").action)

    @pytest.mark.parametrize(
        "command",
        ["ruff format --check .", "ruff format --diff .", "ruff check .", "eslint src", "mypy harness"],
    )
    def test_inspecting_forms_keep_their_existing_action(self, command: str) -> None:
        """Backward compatibility: this table only ever narrows."""
        assert classify(command).action == "test_execute"

    def test_a_flag_with_its_own_action_outranks_the_form(self) -> None:
        """`mypy --install-types` shells out to pip whatever else it is asked."""
        assert classify("mypy --install-types harness").action == "external_write"


class TestRewriteIsRefusedEndToEnd:
    """The reproduction DEC-067 records, run through the real broker."""

    def test_a_formatter_cannot_rewrite_a_protected_file_through_the_broker(self) -> None:
        """R-AEI-1: SUCCESS here means the protected-path write policy was bypassed."""
        workspace = pathlib.Path(tempfile.mkdtemp(prefix="tool-forms-ws-"))
        target = workspace / "harness" / "shared" / "governance" / "broker.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        original = "x   =    1\ndef  f( a ):\n     return   a\n"
        target.write_text(original, encoding="utf-8")

        result = ExecutionBroker().execute_command(
            "ruff format .", {"agent_id": "implementer"}, cwd=workspace, timeout=60
        )

        assert result.status == BROKER_BLOCKED, result.reason
        assert target.read_text(encoding="utf-8") == original


class TestTableIsWellFormed:
    def test_every_neutralising_flag_belongs_to_a_tool_that_can_mutate(self) -> None:
        """A neutralising flag on a tool with no mutating form asserts nothing."""
        for name, form in TOOL_FORMS.items():
            if form.neutralising_flags:
                assert form.mutating_subcommands or form.mutating_flags, name

    def test_every_declared_action_exists_in_the_authority_model(self) -> None:
        """A typo here would grade a command to an action the PDP cannot decide."""
        declared = {form.default_action for form in TOOL_FORMS.values()}
        declared |= {a for form in TOOL_FORMS.values() for a in form.flag_actions.values()}
        known = {a for agent in _AGENT_POLICY["agents"] for a in agent["allowed_actions"]}
        known |= set(_AGENT_POLICY["high_risk_actions"])
        assert declared <= known, declared - known


class TestNeutralisingFlagsWereProbedNotAssumed:
    """Copilot review on PR #122: `--statistics` was listed as neutralising.

    It is not. Every row below was probed against the real binary on a file
    whose md5 was compared before and after, because a neutralising flag that
    does not actually neutralise reopens exactly the bypass this module closes.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "ruff check --fix --statistics .",
            "ruff check --fix-only .",
            "ruff check --fix --unsafe-fixes .",
        ],
    )
    def test_a_flag_that_does_not_stop_the_rewrite_is_not_neutralising(self, command: str) -> None:
        """Probed REWRITTEN: the file changed on disk, so these must not inspect."""
        assert classify(command).action == UNCLASSIFIED_ACTION

    def test_a_non_neutralising_flag_still_yields_write_over_named_files(self) -> None:
        """Bounded, so the write policy gets the target rather than a blanket denial."""
        assert classify("ruff check --fix --statistics a.py").action == "write"
        assert write_targets("ruff check --fix --statistics a.py") == ["a.py"]

    @pytest.mark.parametrize(
        "command",
        [
            "ruff check --fix --diff .",
            "ruff check --fix --no-fix .",
            "ruff format --check .",
            "ruff format --diff .",
        ],
    )
    def test_a_flag_that_does_stop_the_rewrite_is_neutralising(self, command: str) -> None:
        """Probed UNCHANGED: the file was byte-identical after the run."""
        assert classify(command).action == "test_execute"

    def test_statistics_is_not_in_any_neutralising_set(self) -> None:
        """Pins the finding itself, so re-adding it anywhere turns this red."""
        for name, form in TOOL_FORMS.items():
            assert "--statistics" not in form.neutralising_flags, name
