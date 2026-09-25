"""Threshold and path resolution for the ``AGENTS.md`` gate (`agents_doc_policy`).

Split from `test_agents_doc.py` when it reached
``limits.test_size_budget_lines``, along the seam the source already uses:
this file asks *what does the gate enforce*, its sibling asks *is this document
true*. The two grow for different reasons, which is the split `check_dedup` and
`god-file-decomposer` both point at.

The path rules below are the ones worth reading twice. Every other check here
makes a bad policy **fail**; an unconstrained path made a bad policy **pass**,
by pointing the audit at a tree that had nothing wrong with it because it had
nothing in it at all.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from harness.shared.agents_doc import subagent_findings
from harness.shared.agents_doc_policy import DEFAULT_MAX_LINES, load_config
from harness.shared.policy_loader import PolicyError
from harness.shared.tests._agents_doc_helpers import NUMERIC_KEYS, policy_block, write_policy
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance


# --- Configuration resolution ---------------------------------------------------


class TestConfigResolution:
    """R-ADOC-4, C-ADOC-1. Precedence: explicit argument > environment > policy > default.

    The order matters in one direction only: a run must never silently enforce a
    number nobody reviewed. `_Section.int` handles the policy half; these cover
    the three levels above it and the adopter path below.
    """

    def test_an_undeclared_block_takes_built_in_defaults(self, tmp_path: Path) -> None:
        """The DEC-043 hazard. `_section` marks any present *file* as backed, so
        without the `declared()` guard every adopter policy written before this
        block existed would raise on its first numeric key."""
        assert load_config(write_policy(tmp_path, None)).max_lines == DEFAULT_MAX_LINES

    def test_a_declared_block_overrides_the_default(self, tmp_path: Path) -> None:
        assert load_config(write_policy(tmp_path, policy_block(max_lines=42))).max_lines == 42

    def test_a_declared_block_missing_a_numeric_key_fails_closed(self, tmp_path: Path) -> None:
        """A substituted threshold lets a gate report success against a number
        the policy no longer states, and the substitute is always plausible."""
        with pytest.raises(PolicyError, match="min_scope_names"):
            load_config(write_policy(tmp_path, {"max_lines": 42}))

    def test_the_environment_overrides_the_policy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        assert load_config(write_policy(tmp_path, policy_block(max_lines=999))).max_lines == 7

    def test_a_non_numeric_environment_override_is_ignored_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The environment is the least reviewed level; a typo there must not be
        able to take a CI leg down. It is logged so the fallback is explicable."""
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "not-a-number")
        with caplog.at_level(logging.WARNING):
            assert load_config(write_policy(tmp_path, policy_block(max_lines=999))).max_lines == 999
        assert "not an integer" in caplog.text

    def test_an_explicit_argument_overrides_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        assert load_config(write_policy(tmp_path, policy_block(max_lines=999)), max_lines=3).max_lines == 3

    def test_a_non_integer_explicit_override_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyError, match="must be an integer"):
            load_config(write_policy(tmp_path, policy_block(max_lines=999)), max_lines="three")

    def test_a_list_key_of_the_wrong_shape_is_rejected(self, tmp_path: Path) -> None:
        block = policy_block(additional_directories="scripts")
        with pytest.raises(PolicyError, match="list of strings"):
            load_config(write_policy(tmp_path, block))

    def test_a_negative_threshold_is_rejected(self, tmp_path: Path) -> None:
        """A negative floor does not tighten a gate, it disables one:
        `min_documented_directories: -1` makes `present < floor` false for an
        empty tree, so the anti-vacuity check passes with no documents at all."""
        with pytest.raises(PolicyError, match="zero or greater"):
            load_config(write_policy(tmp_path, policy_block(min_documented_directories=-1)))

    def test_every_numeric_key_is_range_checked_not_just_one(self, tmp_path: Path) -> None:
        """Written against the dataclass, so a threshold added later is covered
        without anyone remembering to extend this test."""
        for key in NUMERIC_KEYS:
            with pytest.raises(PolicyError, match="zero or greater"):
                load_config(write_policy(tmp_path, policy_block(**{key: -1})))

    def test_an_override_reaches_an_undeclared_block(self, tmp_path: Path) -> None:
        """The undeclared-block branch returned early, which dropped the two
        levels above the policy: `--max-lines 5` against an adopter policy
        resolved to the built-in 150, so the documented precedence held only
        for deployments that had already adopted the block."""
        policy = write_policy(tmp_path, None)
        assert load_config(policy, max_lines=5).max_lines == 5

    def test_the_environment_reaches_an_undeclared_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "9")
        assert load_config(write_policy(tmp_path, None)).max_lines == 9

    def test_a_waiver_map_of_the_wrong_shape_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyError, match="object of string reasons"):
            load_config(write_policy(tmp_path, policy_block(waived_directories=["scripts"])))

    def test_this_repositorys_policy_declares_every_key_the_module_reads(self) -> None:
        """The live block, resolved the way a gate run resolves it. A key added
        to the module and forgotten in the policy fails here, not in CI."""
        assert load_config().filename == "AGENTS.md"


# --- Path-valued keys stay inside the checkout ----------------------------------


class TestPolicyPathsStayInTheCheckout:
    """R-ADOC-6, and the one failure mode a gate must never have.

    `contains()` already refuses a path a *document* names outside its own
    directory. That was the leaf. The root is the configuration: nothing
    constrained the keys that say *where to look*, so a policy could redirect
    the audit instead of failing it. Pointing `subagent_directory` at an empty
    directory elsewhere made `subagent_findings` return no findings at all --
    a green frontmatter gate over a tree it had never opened.
    """

    @pytest.mark.parametrize(
        "key,value",
        [
            ("subagent_directory", "/etc"),
            ("subagent_directory", "../../../etc"),
            ("subagent_directory", "C:/Windows"),
            ("subagent_directory", "..\\etc"),
            ("subagent_directory", "   "),
        ],
    )
    def test_an_escaping_directory_is_refused(self, tmp_path: Path, key: str, value: str) -> None:
        with pytest.raises(PolicyError, match="inside the checkout"):
            load_config(write_policy(tmp_path, policy_block(**{key: value})))

    def test_an_escaping_additional_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyError, match="inside the checkout"):
            load_config(write_policy(tmp_path, policy_block(additional_directories=["/tmp"])))

    def test_an_escaping_waiver_key_is_refused(self, tmp_path: Path) -> None:
        """A waiver naming an outside directory would exempt nothing that exists
        here, so the exemption reads as granted while covering no real path."""
        with pytest.raises(PolicyError, match="inside the checkout"):
            load_config(write_policy(tmp_path, policy_block(waived_directories={"../elsewhere": "x" * 60})))

    @pytest.mark.parametrize("value", ["/etc/passwd", "../AGENTS.md", "docs/AGENTS.md", ".", ".."])
    def test_a_filename_that_is_not_a_bare_name_is_refused(self, tmp_path: Path, value: str) -> None:
        with pytest.raises(PolicyError, match="bare file name"):
            load_config(write_policy(tmp_path, policy_block(filename=value)))

    def test_the_companion_filename_is_held_to_the_same_rule(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyError, match="bare file name"):
            load_config(write_policy(tmp_path, policy_block(companion_filename="a/b.md")))

    def test_a_nested_adopter_layout_still_loads(self, tmp_path: Path) -> None:
        """The rule constrains the location, not the shape. An adopter keeping
        its subagents somewhere else is a layout, not an escape."""
        config = load_config(
            write_policy(
                tmp_path,
                policy_block(subagent_directory="tools/agents", additional_directories=["src/core"]),
            )
        )
        assert config.subagent_directory == "tools/agents"
        assert config.additional_directories == ("src/core",)

    def test_the_gate_reports_nothing_when_pointed_at_an_empty_tree(self, tmp_path: Path) -> None:
        """The positive control for the rule above: this is what an accepted
        escape bought. Constructed directly, because the policy now refuses it.
        """
        empty = tmp_path / "elsewhere"
        empty.mkdir()
        redirected = load_config(write_policy(tmp_path, policy_block()))
        object.__setattr__(redirected, "subagent_directory", str(empty))
        assert subagent_findings(REPO, redirected) == []
        assert list((REPO / ".claude" / "agents").glob("*.md")), "the real directory must not be empty"

    def test_the_committed_policy_keeps_every_path_inside_the_tree(self) -> None:
        """The live block, resolved as a gate run resolves it."""
        config = load_config()
        for value in (config.subagent_directory, *config.additional_directories, *config.waived_directories):
            assert (REPO / value).is_dir(), f"{value} is configured but is not a directory in this checkout"
