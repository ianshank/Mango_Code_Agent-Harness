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
            "verification_timeout_sec": 11,
            "tool_timeout_sec": 5,
            "max_command_bytes": 4096,
            "max_healing_retries": 3,
            "max_output_bytes": 1234,
        }
        p.write_text(json.dumps({"orchestrator": declared}), encoding="utf-8")
        assert orchestrator_defaults(p) == declared

    def test_a_partial_section_no_longer_fills_defaults(self, tmp_path: Path) -> None:
        """Replaces `test_partial_section_fills_defaults`, which asserted the
        defect R-CQ-8 removes: it pinned that a present policy declaring only
        `nemotron.max_retries` silently resolved `max_tokens` to the built-in
        4096. That is the behaviour, not a test artefact — so the test had to
        change with it rather than be relaxed around it.

        Filling from built-ins is still correct when *no policy file exists*;
        `TestAPresentPolicyMissingAKeyFailsClosed` holds both halves.
        """
        p = tmp_path / "policy.json"
        p.write_text(json.dumps({"nemotron": {"max_retries": 2}}), encoding="utf-8")
        with pytest.raises(PolicyError, match="max_tokens|temperature|top_p|timeout_ms"):
            nemotron_defaults(p)

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
        # A complete block: since R-CQ-8 a present policy must state every key
        # this accessor reads, so a one-key fixture would raise on the *missing*
        # keys before reaching the type check this test is about.
        p.write_text(
            json.dumps(
                {
                    "nemotron": {
                        "temperature": 1,
                        "top_p": 0.7,
                        "max_tokens": 4096,
                        "timeout_ms": 30000,
                        "max_retries": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
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
            "the record does not name the resolved value, so it cannot answer 'which thresholds is this run enforcing'"
        )

    def test_nothing_is_logged_at_the_default_level(self, caplog) -> None:
        """DEBUG-only, so wiring this in changes nothing for existing callers."""
        with caplog.at_level(logging.INFO, logger="harness.shared.policy_loader"):
            policy_loader.orchestrator_defaults()
        assert not caplog.records, "policy resolution is noisy at INFO"

    def test_an_absent_policy_says_so_rather_than_naming_a_file_it_did_not_read(self, tmp_path, caplog) -> None:
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


class TestAPresentPolicyMissingAKeyFailsClosed:
    """R-CQ-8. A key that is gone is not a key that was never adopted.

    `_int_value(section, key, default)` answered the built-in literal for both
    cases, so a policy that lost `orchestrator.max_iterations` returned 10 and
    the loop ran on; one that lost `coverage.lines` returned 90 while the file a
    reviewer had been pointed at said nothing about coverage. The substituted
    value is always a *plausible* one, which is exactly what makes the failure
    silent. `policy.ts:58-69` has thrown for this since it shipped; the two
    stacks disagreed about whether a governance policy may be incomplete.
    """

    #: Every accessor, the block it reads, and one key that must not be
    #: defaultable. Parametrised rather than spot-checked because the defect was
    #: in the shared helper: fixing one accessor and not the rest would leave
    #: the same hole behind a passing test.
    ACCESSORS = [
        pytest.param("orchestrator_defaults", "orchestrator", "max_iterations", id="orchestrator"),
        pytest.param("nemotron_defaults", "nemotron", "temperature", id="nemotron"),
        pytest.param("langgraph_defaults", "langgraph", "recursion_limit", id="langgraph"),
        pytest.param("coverage_defaults", "coverage", "lines", id="coverage"),
        pytest.param("agent_defaults", "agent_defaults", "max_delegation_depth", id="agent"),
        pytest.param("lats_defaults", "lats", "max_budget", id="lats"),
    ]

    def _policy(self, tmp_path: Path, block: str, body: dict) -> Path:
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({block: body}), encoding="utf-8")
        return path

    @pytest.mark.parametrize(("accessor", "block", "key"), ACCESSORS)
    def test_present_policy_missing_key_raises(self, tmp_path: Path, accessor: str, block: str, key: str) -> None:
        """The AC's named case: a policy that exists and omits one key."""
        path = self._policy(tmp_path, block, {})
        with pytest.raises(PolicyError) as excinfo:
            getattr(policy_loader, accessor)(path)
        message = str(excinfo.value)
        assert key in message, "the error must name the key that is missing"
        # The path, not the phrase "present policy". The message used to say
        # that and name no file; naming the file is what makes the error
        # actionable, and asserting on the phrase would have pinned the weaker
        # wording in place. Reported by a review bot on this PR.
        assert str(path) in message, "the error must name the policy it is about"

    @pytest.mark.parametrize(("accessor", "block", "key"), ACCESSORS)
    def test_an_absent_policy_still_yields_the_built_in(
        self, tmp_path: Path, accessor: str, block: str, key: str
    ) -> None:
        """Control, and the reason this is not simply `raise if key is missing`.

        The adopter path is a supported deployment: a stack that has not adopted
        `governance-policy.json` gets the built-in defaults and a working
        harness. A fix that failed closed on *absence* too would break every
        adopter to close a hole that only exists when a file is present.
        """
        resolved = getattr(policy_loader, accessor)(tmp_path / "nothing-here.json")
        assert key in resolved

    def test_a_present_policy_missing_the_whole_block_also_raises(self, tmp_path: Path) -> None:
        """A missing block is every key missing at once, and is graded the same."""
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"unrelated": {}}), encoding="utf-8")
        with pytest.raises(PolicyError):
            orchestrator_defaults(path)

    def test_the_repository_policy_states_every_key_it_is_asked_for(self) -> None:
        """The gate this change puts under the repository's own policy.

        If `governance-policy.json` ever loses a key some accessor reads, every
        caller now raises instead of quietly running on a literal — so this
        asserts the policy is complete, and fails here rather than in whichever
        gate happened to load first.
        """
        for param in self.ACCESSORS:
            accessor, _block, key = (str(value) for value in param.values)
            assert key in getattr(policy_loader, accessor)()

    def test_an_optional_key_is_still_optional(self, tmp_path: Path) -> None:
        """`coverage.optional_extras` documents its own absence as meaningful.

        "This deployment declares no optional extras" is a statement; "this
        policy no longer says what the line floor is" is a hole. `_Section`
        separates them with `.optional`, and collapsing the two would either
        break every policy without extras or reopen the defect.
        """
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"coverage": {"lines": 90, "branches": 80}}), encoding="utf-8")
        assert coverage_optional_extras(path) == {}
        assert coverage_defaults(path) == {"lines": 90, "branches": 80}


class TestTheErrorNamesThePolicyItIsAbout:
    """An error that says "a file is at fault" without saying which one.

    The first version read "missing from a present policy at this path" and
    then named no path — the least useful shape an error can take. Every
    accessor takes an optional `policy_path` and the tests use `tmp_path`
    fixtures, so "which policy?" is a real question at the moment it is read.
    Reported by a review bot on this PR.
    """

    def test_the_message_contains_the_policy_path(self, tmp_path: Path) -> None:
        path = tmp_path / "governance-policy.json"
        path.write_text(json.dumps({"orchestrator": {}}), encoding="utf-8")
        with pytest.raises(PolicyError) as excinfo:
            orchestrator_defaults(path)
        assert str(path) in str(excinfo.value)

    def test_two_policies_produce_distinguishable_errors(self, tmp_path: Path) -> None:
        """The property that makes it worth naming: with two policies in play,
        an unnamed one leaves the reader guessing which is at fault."""
        messages = []
        for name in ("first", "second"):
            path = tmp_path / f"{name}.json"
            path.write_text(json.dumps({"coverage": {}}), encoding="utf-8")
            with pytest.raises(PolicyError) as excinfo:
                coverage_defaults(path)
            messages.append(str(excinfo.value))
        assert messages[0] != messages[1]
        assert "first.json" in messages[0] and "second.json" in messages[1]

    def test_the_default_path_is_named_too(self) -> None:
        """The accessor called with no argument still resolves a real file, and
        the error must name that one rather than fall silent."""
        from harness.shared import policy_loader

        section = policy_loader._section("orchestrator")
        with pytest.raises(PolicyError, match=r"governance-policy\.json"):
            section.int("a-key-no-policy-states", 1)
