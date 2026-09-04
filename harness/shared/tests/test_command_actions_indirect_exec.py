"""``make`` and ``pnpm exec``/``npx`` are graded by what they run, not by name.

The 2026 standards audit (B4) found ``make <anything>`` and ``pnpm exec
<anything>`` graded ``test_execute`` -- an action every role holds -- so
``make -f GNUmakefile x`` was arbitrary shell for any role and ``pnpm exec node
evil.js`` was a gate run. ``harness/shared/governance/indirect_exec.py`` now
answers which makefile ``make`` was told to read and which program a delegator
hands off to; ``command_actions`` grades on the answer.

Kept out of ``test_command_actions.py``, which sits near its size budget.
"""

from __future__ import annotations

import pytest

from harness.shared.governance.command_actions import (
    _BY_PROGRAM,
    UNCLASSIFIED_ACTION,
    classify,
)
from harness.shared.governance.indirect_exec import (
    CANONICAL_MAKEFILE,
    delegated_argv,
    make_denial_reason,
)
from harness.shared.governance.verification import DEFAULT_MAKEFILE

pytestmark = pytest.mark.governance


class TestMakeIsAGateRunOnlyAgainstTheCanonicalMakefile:
    @pytest.mark.parametrize(
        "command",
        [
            "make test-python",
            "make ci",
            "make lint",
            "make -f Makefile test-python",
            "make -f Makefile -n test-python",
            "make --file=Makefile test-python",
            "make --file Makefile test-python",
            "make -j4 test-python",
            "make -n -k --silent test-python",
            "make -- test-python",
            "make --jobs 4 test-python",
            "make --jobs=4 --keep-going test-python",
            "make --dry-run --no-print-directory test-python",
        ],
    )
    def test_ordinary_gate_runs_still_grade_test_execute(self, command: str) -> None:
        """The control. A grader that refused every `make` would satisfy every
        assertion below while making the verifier's own command undeniable."""
        assert classify(command).action == "test_execute", classify(command).reason

    @pytest.mark.parametrize(
        ("command", "fragment"),
        [
            ("make -f GNUmakefile x", "GNUmakefile"),
            ("make -f makefile x", "makefile"),
            ("make -f evil.mk x", "evil.mk"),
            ("make -f ./Makefile x", "./Makefile"),
            ("make -fMakefile.evil x", "Makefile.evil"),
            ("make --file=evil.mk x", "evil.mk"),
            ("make --file evil.mk x", "evil.mk"),
            ("make --makefile=evil.mk x", "evil.mk"),
            ("make -f", "None"),
            ("make -f -", "'-'"),
            ("make -f Makefile -f evil.mk x", "evil.mk"),
            ("make -C harness/node test", "-C"),
            ("make --directory=/tmp x", "--directory"),
            ("make --directory /tmp x", "--directory"),
            ("make -I /tmp x", "-I"),
            ("make --include-dir=/tmp x", "--include-dir"),
            ("make -E x=1 x", "-E"),
            ("make --eval=x x", "--eval"),
            ("make -nf Makefile x", "-nf"),
            ("make -kC . x", "-kC"),
            ("make PYTEST=evil test-python", "PYTEST"),
            ("make test-python PYTHON=/tmp/evil", "PYTHON"),
            ("make -- PYTEST=evil test-python", "PYTEST"),
            # GNU getopt_long resolves unique prefixes: each of these reaches
            # make as the option it abbreviates (Copilot review on PR #86).
            ("make --ev=x x", "--ev"),
            ("make --dir=/tmp x", "--dir"),
            ("make --direct /tmp x", "--direct"),
            ("make --fi=evil.mk x", "--fi"),
            ("make --makef=evil.mk x", "--makef"),
            ("make --inc=/tmp x", "--inc"),
            ("make --no-such-option x", "--no-such-option"),
            # `-e` is NAME=value through the environment.
            ("make -e test-python", "-e"),
            ("make --environment-overrides test-python", "--environment-overrides"),
            ("make --env test-python", "--env"),
            ("make -ke test-python", "-ke"),
            # A harmless option must not swallow the assignment after it.
            ("make --jobs PYTEST=evil test-python", "PYTEST"),
        ],
    )
    def test_any_other_makefile_directory_or_override_is_unclassified(self, command: str, fragment: str) -> None:
        verdict = classify(command)
        assert verdict.action == UNCLASSIFIED_ACTION, verdict
        assert fragment in verdict.reason

    def test_every_harmless_long_option_is_a_full_spelling_make_accepts(self) -> None:
        """The allowlist is exact spellings of documented GNU make options and
        nothing shorter: an entry that were itself an abbreviation would be
        the prefix hole reopened from the other side."""
        from harness.shared.governance.indirect_exec import HARMLESS_LONG_OPTIONS

        assert HARMLESS_LONG_OPTIONS, "an empty allowlist would refuse every long option, including --jobs"
        for option in HARMLESS_LONG_OPTIONS:
            assert option.startswith("--") and len(option) > 4, option
            assert not any(
                other != option and other.startswith(option) for other in HARMLESS_LONG_OPTIONS
            ), f"{option} is a prefix of another allowlisted option"

    def test_an_eval_with_a_recipe_is_a_command_chain_first(self) -> None:
        """`--eval='x: ; curl evil'` carries `;`, so `_COMPOUND` refuses it before
        the make rules are reached. Either refusal is correct; this pins that
        neither path lets it through."""
        assert classify("make --eval='x: ; curl evil' x").action == UNCLASSIFIED_ACTION

    def test_an_environment_prefix_is_not_a_modelled_program(self) -> None:
        """`MAKEFILES=evil.mk make x` names extra makefiles through the
        environment. `argv[0]` is the assignment, which no table models."""
        verdict = classify("MAKEFILES=evil.mk make test-python")
        assert verdict.action == UNCLASSIFIED_ACTION
        assert "MAKEFILES=evil.mk" in verdict.reason

    def test_the_runner_and_the_classifier_name_the_same_makefile(self) -> None:
        """One constant. If the runner's `-f` and the classifier's allowance
        drifted apart, the harness's own verification command would be denied
        by the broker it runs through."""
        assert DEFAULT_MAKEFILE == CANONICAL_MAKEFILE == "Makefile"

    def test_make_denial_reason_is_none_for_the_canonical_invocation(self) -> None:
        assert make_denial_reason(["-f", "Makefile", "-n", "test-python"]) is None
        assert make_denial_reason([]) is None


class TestDelegatorsAreGradedAsWhatTheyRun:
    GATE_PROGRAMS = sorted(p for p, a in _BY_PROGRAM.items() if a == "test_execute")

    @pytest.mark.parametrize("program", GATE_PROGRAMS)
    @pytest.mark.parametrize("delegator", ["pnpm exec", "npx"])
    def test_a_gate_program_through_a_delegator_is_a_gate_run(self, delegator: str, program: str) -> None:
        """The allowlist is `_BY_PROGRAM`'s own `test_execute` set, read through
        the delegator -- not a second list that could drift from it."""
        verdict = classify(f"{delegator} {program} --version")
        assert verdict.action == "test_execute", verdict
        assert program in verdict.reason

    @pytest.mark.parametrize(
        "command",
        [
            "pnpm exec node evil.js",
            "pnpm exec prettier --check .",
            "pnpm exec knip",
            "pnpm exec bash",
            "pnpm exec curl https://example.test",
            "pnpm exec",
            "npx",
            "npx tsx evil.ts",
            "npx -p pkg vitest",
            "npx --package=evil vitest",
            "npx --yes vitest",
            "npx --call=evil vitest",
            "pnpm exec -- vitest",
            "npx cowsay hi",
            "pnpm exec pnpm exec vitest",
        ],
    )
    def test_anything_else_through_a_delegator_is_unclassified(self, command: str) -> None:
        assert classify(command).action == UNCLASSIFIED_ACTION, classify(command).reason

    def test_a_gate_program_keeps_its_own_argument_rules_through_a_delegator(self) -> None:
        """`pnpm exec make -f evil x` must be refused for the same reason
        `make -f evil x` is, or the delegator is a way around the make rules."""
        direct = classify("make -f evil.mk x")
        delegated = classify("pnpm exec make -f evil.mk x")
        assert delegated.action == UNCLASSIFIED_ACTION
        assert direct.reason in delegated.reason

    def test_pnpm_test_and_install_are_unchanged(self) -> None:
        assert classify("pnpm test").action == "test_execute"
        assert classify("pnpm install").action == "external_write"
        assert classify("pnpm run build").action == UNCLASSIFIED_ACTION

    def test_delegated_argv_shapes(self) -> None:
        assert delegated_argv(["pnpm", "exec", "vitest", "run"]) == ("pnpm exec", ["vitest", "run"])
        assert delegated_argv(["npx", "--yes", "tsc", "--noEmit"]) == ("npx", [])
        assert delegated_argv(["npx", "--package=evil", "vitest"]) == ("npx", [])
        assert delegated_argv(["pnpm", "exec"]) == ("pnpm exec", [])
        assert delegated_argv(["pnpm", "test"]) is None
        assert delegated_argv(["make", "ci"]) is None
        assert delegated_argv([]) is None
