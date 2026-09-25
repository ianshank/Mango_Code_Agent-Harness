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
from pathlib import Path, PureWindowsPath

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
            ("subagent_directory", "C:foo"),
            ("subagent_directory", "c:windows"),
        ],
    )
    def test_an_escaping_directory_is_refused(self, tmp_path: Path, key: str, value: str) -> None:
        with pytest.raises(PolicyError, match="inside the checkout"):
            load_config(write_policy(tmp_path, policy_block(**{key: value})))

    def test_a_drive_relative_windows_path_is_refused(self, tmp_path: Path) -> None:
        """`PureWindowsPath('C:foo')` has a drive but is **not** absolute, so it
        passed every other arm of the predicate. Joined to a checkout it
        resolves against drive C's working directory, which is outside the
        repository by construction -- the containment rule with the one case
        that reads like a relative path and is not."""
        assert not PureWindowsPath("C:foo").is_absolute(), "the premise of this test has changed"
        assert PureWindowsPath("C:foo").drive == "C:"
        with pytest.raises(PolicyError, match="inside the checkout"):
            load_config(write_policy(tmp_path, policy_block(subagent_directory="C:foo")))

    def test_an_ordinary_relative_path_is_not_mistaken_for_a_drive(self, tmp_path: Path) -> None:
        """The negative control for the rule above: tightening on a drive must
        not start refusing the relative directories an adopter legitimately
        names."""
        config = load_config(write_policy(tmp_path, policy_block(subagent_directory="tools/agents")))
        assert config.subagent_directory == "tools/agents"

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

    def test_a_redirect_that_bypasses_the_load_check_is_still_caught(self, tmp_path: Path) -> None:
        """Defence in depth, and the reason there are two layers.

        This originally asserted the *hole*: pointed at an empty directory
        elsewhere, `subagent_findings` returned `[]` and the frontmatter audit
        reported success over a tree it had never opened. The load-time rule
        closed the policy route, and the resolution-time rule in
        `subagent_findings` now closes the constructed one too — so a config
        that reaches the consumer redirected is reported rather than obeyed.
        """
        empty = tmp_path / "elsewhere"
        empty.mkdir()
        redirected = load_config(write_policy(tmp_path, policy_block()))
        object.__setattr__(redirected, "subagent_directory", str(empty))
        assert "resolves outside the checkout" in "".join(subagent_findings(REPO, redirected))
        assert list((REPO / ".claude" / "agents").glob("*.md")), "the real directory must not be empty"

    def test_the_committed_policy_keeps_every_path_inside_the_tree(self) -> None:
        """The live block, resolved as a gate run resolves it."""
        config = load_config()
        for value in (config.subagent_directory, *config.additional_directories, *config.waived_directories):
            assert (REPO / value).is_dir(), f"{value} is configured but is not a directory in this checkout"


class TestAnOverrideMayOnlyTighten:
    """C-ADOC-1 / R-CQ-8, the rule `validate_invariants._policy_limit` and
    `check_dedup` already apply and this loader did not.

    `MAX_FILE_LINES=9999` was once returned verbatim, which switched the size
    gate off while it still printed `[PASS]`. The same hole was open here in
    two places at once: `--max-lines 999` against a policy of 150, and
    `AGENTS_DOC_MIN_DOCUMENTED_DIRECTORIES=0` against a floor of 20.
    """

    def test_an_explicit_override_cannot_raise_a_cap(self, tmp_path: Path) -> None:
        policy = write_policy(tmp_path, policy_block(max_lines=150))
        assert load_config(policy, max_lines=999).max_lines == 150

    def test_an_explicit_override_can_still_lower_a_cap(self, tmp_path: Path) -> None:
        """The negative control: tightening is the whole point of the override."""
        policy = write_policy(tmp_path, policy_block(max_lines=150))
        assert load_config(policy, max_lines=40).max_lines == 40

    def test_an_environment_override_cannot_lower_a_floor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTS_DOC_MIN_DOCUMENTED_DIRECTORIES", "0")
        policy = write_policy(tmp_path, policy_block(min_documented_directories=20))
        assert load_config(policy).min_documented_directories == 20

    def test_an_environment_override_can_still_raise_a_floor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTS_DOC_MIN_DOCUMENTED_DIRECTORIES", "30")
        policy = write_policy(tmp_path, policy_block(min_documented_directories=20))
        assert load_config(policy).min_documented_directories == 30

    def test_min_source_files_tightens_downward_despite_its_name(self, tmp_path: Path) -> None:
        """The key a prefix rule would get wrong. `min_source_files` is how many
        sources *earn* a directory a document, so raising it requires fewer
        documents -- looser, despite the `min_` name. A rule that read the name
        would have let this one key be relaxed silently."""
        policy = write_policy(tmp_path, policy_block(min_source_files=3))
        assert load_config(policy, min_source_files=9).min_source_files == 3
        assert load_config(policy, min_source_files=2).min_source_files == 2

    def test_an_explicit_override_is_judged_against_the_policy_not_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression the tighten-only rule introduced, and the reason the
        two levels are not chained.

        Applying the environment first and then judging the explicit value
        against the *result* broke the documented precedence: with policy 150
        and `AGENTS_DOC_MAX_LINES=7`, an explicit 8 tightens the policy but
        loses to the 7 it was compared against. Only the highest-priority
        override that was supplied is consulted, and it answers to the policy.
        """
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        policy = write_policy(tmp_path, policy_block(max_lines=150))
        assert load_config(policy, max_lines=8).max_lines == 8

    def test_an_explicit_override_that_loosens_is_still_refused_with_an_environment_value_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restoring the precedence must not restore the hole: the explicit value
        answers to the policy, so a loosening one falls back to the policy rather
        than to the environment."""
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        policy = write_policy(tmp_path, policy_block(max_lines=150))
        assert load_config(policy, max_lines=200).max_lines == 150

    def test_the_environment_still_applies_when_no_explicit_override_is_given(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        assert load_config(write_policy(tmp_path, policy_block(max_lines=150))).max_lines == 7

    def test_a_refused_override_says_so(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Silently ignoring an override would be its own trap."""
        policy = write_policy(tmp_path, policy_block(max_lines=150))
        with caplog.at_level(logging.WARNING):
            load_config(policy, max_lines=999)
        assert "may only tighten" in caplog.text


class TestMalformedScalarsAreRefused:
    """C-ADOC-1. `str()` turned `subagent_directory: null` into the literal
    `"None"`, which names no directory -- so `subagent_findings` saw a missing
    one and reported nothing. A malformed policy value silently switched the
    frontmatter audit off instead of failing closed."""

    @pytest.mark.parametrize("value", [None, 42, ["a"], {"a": "b"}, True])
    def test_a_non_string_scalar_is_rejected(self, tmp_path: Path, value: object) -> None:
        with pytest.raises(PolicyError, match="must be a string"):
            load_config(write_policy(tmp_path, policy_block(subagent_directory=value)))

    def test_the_coercion_that_used_to_happen_is_gone(self, tmp_path: Path) -> None:
        """Pins the exact shape: `None` must never reach the config as `"None"`."""
        with pytest.raises(PolicyError):
            config = load_config(write_policy(tmp_path, policy_block(filename=None)))
            assert config.filename != "None"
