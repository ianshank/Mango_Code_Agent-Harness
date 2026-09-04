"""Tests for policy_loader: precedence, fail-closed semantics, and the
orchestrator/bridge wiring that makes governance-policy.json the single source
of operational values (spec: policy-single-source)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from harness.shared import policy_loader
from harness.shared.policy_loader import (
    PolicyError,
    agent_defaults,
    coverage_defaults,
    coverage_optional_extras,
    load_policy,
    max_tool_calls_per_task,
    nemotron_defaults,
    orchestrator_defaults,
)


class TestLoadPolicy:
    def test_absent_policy_is_adopter_path(self, tmp_path: Path) -> None:
        assert load_policy(tmp_path / "nope.json") == {}

    def test_malformed_policy_fails_closed(self, tmp_path: Path) -> None:
        bad = tmp_path / "policy.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(PolicyError):
            load_policy(bad)

    def test_non_object_policy_fails_closed(self, tmp_path: Path) -> None:
        bad = tmp_path / "policy.json"
        bad.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(PolicyError):
            load_policy(bad)

    def test_default_path_is_the_repo_policy(self) -> None:
        assert load_policy()["policy_id"] == "agentic-ssd-governance"


class TestSectionAccessors:
    def test_orchestrator_values_come_from_policy(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        # Every key the accessor returns is set to a distinct non-default value,
        # so exact equality proves each one is *read* rather than filled in. A
        # new key added to the accessor and not to this literal fails here, which
        # is the point: an accessor nobody pinned is a threshold nobody sources.
        declared = {
            "max_iterations": 3,
            "api_timeout_sec": 7,
            "tool_timeout_sec": 5,
            "max_command_bytes": 4096,
            "max_healing_retries": 3,
            "max_output_bytes": 1234,
        }
        p.write_text(json.dumps({"orchestrator": declared}), encoding="utf-8")
        assert orchestrator_defaults(p) == declared

    def test_partial_section_fills_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"nemotron": {"max_retries": 2}}), encoding="utf-8")
        values = nemotron_defaults(p)
        assert values["max_retries"] == 2
        assert values["max_tokens"] == 4096

    def test_wrong_type_fails_closed(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"orchestrator": {"max_iterations": "ten"}}), encoding="utf-8")
        with pytest.raises(PolicyError):
            orchestrator_defaults(p)

    def test_bool_is_not_an_integer(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"agent_defaults": {"max_tool_calls_per_task": True}}), encoding="utf-8")
        with pytest.raises(PolicyError):
            max_tool_calls_per_task(p)

    def test_non_object_section_fails_closed(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"nemotron": [1]}), encoding="utf-8")
        with pytest.raises(PolicyError):
            nemotron_defaults(p)

    def test_coverage_values_come_from_policy(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"coverage": {"lines": 77, "branches": 66}}), encoding="utf-8")
        assert coverage_defaults(p) == {"lines": 77, "branches": 66}

    def test_coverage_non_object_section_fails_closed(self, tmp_path: Path) -> None:
        """A GraphPolicy caller must see PolicyError here, not an AttributeError
        from treating a non-dict section as one -- the exact shape GitHub Copilot's
        review of PR #53 found: `coverage`/`agent_defaults` present but not an
        object was reaching `.get()` unvalidated before this accessor existed."""
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"coverage": "not-an-object"}), encoding="utf-8")
        with pytest.raises(PolicyError):
            coverage_defaults(p)

    def test_coverage_optional_extras_come_from_policy(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        spec = {"import_name": "x", "deselect_env": "X_OFF", "path_prefixes": ["a/", "b/"]}
        p.write_text(json.dumps({"coverage": {"optional_extras": {"x": spec}}}), encoding="utf-8")
        assert coverage_optional_extras(p) == {
            "x": {"import_name": "x", "deselect_env": "X_OFF", "path_prefixes": ("a/", "b/")}
        }

    def test_coverage_optional_extras_absent_is_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"coverage": {"lines": 1, "branches": 1}}), encoding="utf-8")
        assert coverage_optional_extras(p) == {}

    @pytest.mark.parametrize(
        "extras",
        [
            [1],
            {"x": 3},
            {"x": {"import_name": "", "deselect_env": "E", "path_prefixes": ["a/"]}},
            {"x": {"import_name": "x", "deselect_env": None, "path_prefixes": ["a/"]}},
            {"x": {"import_name": "x", "deselect_env": "E", "path_prefixes": []}},
            {"x": {"import_name": "x", "deselect_env": "E", "path_prefixes": ["a/", 2]}},
        ],
    )
    def test_coverage_optional_extras_malformed_fail_closed(self, tmp_path: Path, extras: object) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"coverage": {"optional_extras": extras}}), encoding="utf-8")
        with pytest.raises(PolicyError):
            coverage_optional_extras(p)

    def test_agent_defaults_values_come_from_policy(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(
            json.dumps({"agent_defaults": {"max_delegation_depth": 5, "max_parallel_subagents": 9}}),
            encoding="utf-8",
        )
        assert agent_defaults(p) == {"max_delegation_depth": 5, "max_parallel_subagents": 9}

    def test_agent_defaults_non_object_section_fails_closed(self, tmp_path: Path) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"agent_defaults": [1, 2]}), encoding="utf-8")
        with pytest.raises(PolicyError):
            agent_defaults(p)


class TestFloatValues:
    """``_float_value`` (policy_loader.py line 111) guards the one float the policy
    carries, ``nemotron.temperature``. ``bool`` is an ``int`` subclass, so without
    the explicit check ``true`` would silently become a temperature of 1.0."""

    @pytest.mark.parametrize("bad", [True, "0.2", None, [0.2]])
    def test_a_non_number_temperature_fails_closed(self, tmp_path: Path, bad: object) -> None:
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"nemotron": {"temperature": bad}}), encoding="utf-8")
        with pytest.raises(PolicyError, match="nemotron.temperature must be a number"):
            nemotron_defaults(p)

    def test_an_integer_temperature_is_accepted_as_a_float(self, tmp_path: Path) -> None:
        """The control: an int is a number and is normalised to float, so the
        rejection above is about type, not about the absence of a decimal point."""
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"nemotron": {"temperature": 1}}), encoding="utf-8")
        value = nemotron_defaults(p)["temperature"]
        assert value == 1.0 and isinstance(value, float)


class TestRepoPolicyIsWired:
    """In this repository the policy file exists, so the wired readers must
    surface its values — these keys previously had zero code readers."""

    def test_orchestrator_reads_policy_block(self) -> None:
        repo_policy = json.loads(policy_loader.POLICY_PATH.read_text(encoding="utf-8"))
        assert orchestrator_defaults() == repo_policy["orchestrator"]

    def test_nemotron_reads_policy_block(self) -> None:
        repo_policy = json.loads(policy_loader.POLICY_PATH.read_text(encoding="utf-8"))
        assert nemotron_defaults() == repo_policy["nemotron"]

    def test_tool_budget_reads_agent_defaults(self) -> None:
        repo_policy = json.loads(policy_loader.POLICY_PATH.read_text(encoding="utf-8"))
        assert max_tool_calls_per_task() == repo_policy["agent_defaults"]["max_tool_calls_per_task"]

    def test_coverage_defaults_reads_policy_block(self) -> None:
        repo_policy = json.loads(policy_loader.POLICY_PATH.read_text(encoding="utf-8"))
        values = coverage_defaults()
        assert values["lines"] == repo_policy["coverage"]["lines"]
        assert values["branches"] == repo_policy["coverage"]["branches"]

    def test_coverage_optional_extras_reads_policy_block(self) -> None:
        repo_policy = json.loads(policy_loader.POLICY_PATH.read_text(encoding="utf-8"))
        declared = repo_policy["coverage"]["optional_extras"]
        extras = coverage_optional_extras()
        assert set(extras) == set(declared)
        for name, spec in declared.items():
            assert extras[name]["deselect_env"] == spec["deselect_env"]
            assert extras[name]["path_prefixes"] == tuple(spec["path_prefixes"])

    def test_agent_defaults_reads_policy_block(self) -> None:
        repo_policy = json.loads(policy_loader.POLICY_PATH.read_text(encoding="utf-8"))
        values = agent_defaults()
        assert values["max_delegation_depth"] == repo_policy["agent_defaults"]["max_delegation_depth"]
        assert values["max_parallel_subagents"] == repo_policy["agent_defaults"]["max_parallel_subagents"]


class TestPolicyResolutionLogging:
    """R-GT-4: which policy did this run read, and what did it resolve?

    Every threshold in the system resolves through this module and nothing
    recorded either answer, so under `LOG_LEVEL=DEBUG` the question was
    unanswerable -- while every gate depends on it. `ExecutionLoop` already
    logged its own resolution at DEBUG; this is the same pattern at the source.
    """

    def test_resolution_names_the_key_the_value_and_the_source(self, caplog) -> None:
        with caplog.at_level(logging.DEBUG, logger="harness.shared.policy_loader"):
            resolved = policy_loader.orchestrator_defaults()
        assert caplog.records, "resolving a policy block emitted no DEBUG record"
        message = caplog.records[-1].getMessage()
        assert "orchestrator" in message
        assert str(policy_loader.POLICY_PATH) in message, "the record does not name the file it read"
        assert f"max_iterations={resolved['max_iterations']!r}" in message, (
            "the record does not name the resolved value, so it cannot answer "
            "'which thresholds is this run enforcing'"
        )

    def test_nothing_is_logged_at_the_default_level(self, caplog) -> None:
        """DEBUG-only, so wiring this in changes nothing for existing callers."""
        with caplog.at_level(logging.INFO, logger="harness.shared.policy_loader"):
            policy_loader.orchestrator_defaults()
        assert not caplog.records, "policy resolution is noisy at INFO"

    def test_an_absent_policy_says_so_rather_than_naming_a_file_it_did_not_read(
        self, tmp_path, caplog
    ) -> None:
        """The adopter path resolves built-in defaults; the log must not imply a read."""
        missing = tmp_path / "no-such-policy.json"
        with caplog.at_level(logging.DEBUG, logger="harness.shared.policy_loader"):
            policy_loader.orchestrator_defaults(missing)
        message = caplog.records[-1].getMessage()
        assert "absent" in message and "built-in defaults" in message

    @pytest.mark.parametrize(
        "accessor",
        ["orchestrator_defaults", "nemotron_defaults", "langgraph_defaults", "coverage_defaults"],
    )
    def test_every_block_accessor_records_its_resolution(self, accessor: str, caplog) -> None:
        """One instrumented accessor and three silent ones is the drift to prevent."""
        with caplog.at_level(logging.DEBUG, logger="harness.shared.policy_loader"):
            getattr(policy_loader, accessor)()
        assert caplog.records, f"{accessor} resolved silently"


class TestLimitsAreTyped:
    """R-GT-5: an undeclared key is a static error, not a runtime KeyError.

    The runtime behaviour is unchanged -- a TypedDict is a dict -- so this
    asserts the contract that makes `python -m mypy` able to see the typo:
    the declared key set matches what the accessor actually returns. A key
    added to one and not the other is the drift that would make the type
    annotation a lie while every test still passed.
    """

    @pytest.mark.parametrize(
        ("accessor", "typed"),
        [
            ("orchestrator_defaults", "OrchestratorLimits"),
            ("nemotron_defaults", "NemotronDefaults"),
            ("langgraph_defaults", "LangGraphDefaults"),
            ("coverage_defaults", "CoverageThresholds"),
        ],
    )
    def test_the_declared_keys_are_the_returned_keys(self, accessor: str, typed: str) -> None:
        declared = set(getattr(policy_loader, typed).__annotations__)
        returned = set(getattr(policy_loader, accessor)())
        assert declared == returned, (
            f"{typed} declares {sorted(declared)} but {accessor}() returns {sorted(returned)}; "
            "the annotation no longer describes the value, so mypy is checking a fiction"
        )

    def test_the_blocks_are_still_plain_dicts_at_runtime(self) -> None:
        """Backward compatibility: adopters reading the block dynamically are unaffected."""
        assert isinstance(policy_loader.orchestrator_defaults(), dict)
