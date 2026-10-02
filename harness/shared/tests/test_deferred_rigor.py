"""Every declined strictness option, with the number that justified declining.

A rule left unselected with no record is indistinguishable from a rule nobody
thought about. This file is the difference: each entry carries the finding
count measured at the time, and the reason the cost was judged not worth
paying. The tests keep the register honest -- an entry may not name a rule
that is now enabled, and every measured number must still be roughly right, so
a deferral cannot quietly become stale cover for a rule that got cheap.

The counts are re-measured live rather than asserted exactly: they drift as
code is added, and a test that fails on ordinary drift teaches people to
delete it. What must hold is the *reason* -- that the count is still large
enough for the decline to make sense.

Both halves are guarded, which they were not. The ruff half had the live
re-measurement and the not-secretly-enabled check; the mypy half had neither,
so its two numbers were asserted to *exist* and never to be true, and
`--strict` could have been added to `MYPY_FLAGS` with its entry here still
reading as a considered decision. Both now get the same two tests, and the
mypy measurement is taken over the Makefile's own `MYPY_TARGETS` rather than
a scope this file chooses, because what a reader needs to know is the cost of
actually enabling the flag.

Each entry also records which side of the tree its findings sit on. The
reasons argue from that -- "the gates' CLI contract" for `T20`, "fixture
parameters" for `ARG` -- so an inversion falsifies the reason even while the
count stays comfortably high. Counts drift; which side dominates does not.
"""

from __future__ import annotations

import functools
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on the 3.10 matrix leg
    import tomli as tomllib

import pytest

from harness.shared.tests._helpers import REPO, ruff_json, run_ruff

pytestmark = pytest.mark.slow


@dataclass(frozen=True)
class Deferral:
    rule: str
    measured: int
    reason: str
    # Below this count the decline stops being about cost and should be revisited.
    revisit_below: int
    # Which side of the tree the findings sit on, and the half the reason argues
    # from. Asserted rather than described: `T20`'s reason only holds while the
    # hits are in source, `ARG`'s only while they are in the suite.
    leans: Literal["source", "tests"]


# `measured` values re-taken 2026-10-02 on `main` under ruff 0.16.5 and mypy
# 2.3.1. The previous ruff numbers were taken 2026-09-02 and every one had
# drifted upward since, which is growth rather than a tool change -- the version
# is the same. The mypy numbers had never been re-taken at all and were ~1.7x
# and ~1.9x low, which is the gap this file now closes. `source`/`tests` splits
# classify a path as test code when it sits under `tests/`, is named `test_*.py`
# or is a `conftest.py`.
DEFERRED_RUFF_RULES = (
    Deferral(
        "T20",
        56,
        "All 50 source hits are deliberate stdout, and most are gate scripts printing their verdict "
        "line (`zero-skip: passed`, `projections: passed`) -- the gates' CLI contract, pinned by "
        "test_gate_logging.py. Three of the 25 files are not gates and are equally deliberate: "
        "`nemotron_bridge.py` prints a model response and latency banner, `show_memory.py` dumps the "
        "memory stores, `governance/remotes.py` prints BLOCKED to stderr. Converting any of it to "
        "logging would change operator-facing output for no governance gain.",
        revisit_below=5,
        leans="source",
    ),
    Deferral(
        "TRY400",
        31,
        "Every site is a `[FAIL] <verdict>` line for an *expected* validation failure, inside "
        "an except clause that already names narrow exception types. logging.exception would "
        "replace a one-line operator-facing verdict with a traceback whose content is already "
        "in the message, and would fight test_gate_logging.py's stdout pins.",
        revisit_below=3,
        leans="source",
    ),
    Deferral(
        "TRY003",
        265,
        "Long messages inside raise statements, 208 of them in source. Fixing them means inventing "
        "a comparable number of exception subclasses; the messages are already specific and the "
        "change buys no behaviour.",
        revisit_below=20,
        leans="source",
    ),
    Deferral(
        "S",
        5581,
        "Bandit. 5387 of the 5581 are assert-in-test (S101), and the 24 source hits are the "
        "subprocess calls that gate scripts exist to make. Enabling it needs blanket waivers, "
        "which CLAUDE.md forbids without decision-log entries.",
        revisit_below=100,
        leans="tests",
    ),
    Deferral(
        "PT",
        308,
        "pytest style, all but one of them in tests. Large mechanical churn across a suite this "
        "programme is already reshaping; the two changes would be impossible to review separately.",
        revisit_below=30,
        leans="tests",
    ),
    Deferral(
        "ARG",
        238,
        "Unused arguments. Six are in source; the other 232 are pytest fixture parameters requested "
        "for their side effects, which is the idiomatic way to use a fixture. (The recorded split "
        "used to read `1 + 39` against a measured 144, which never added up -- the arithmetic was "
        "wrong when it was written, not just stale.)",
        revisit_below=5,
        leans="tests",
    ),
    Deferral(
        "PLW1510",
        57,
        "subprocess.run without an explicit check=. Several sites deliberately tolerate a "
        "non-zero exit and inspect returncode themselves, so a blanket fix would change "
        "behaviour. Needs a site-by-site review, not a rule flip.",
        revisit_below=5,
        leans="tests",
    ),
    Deferral(
        "PTH",
        37,
        "os.path -> pathlib. Cosmetic in a codebase that already uses pathlib for new code; "
        "seven source sites, the rest tests.",
        revisit_below=5,
        leans="tests",
    ),
    Deferral(
        "SIM",
        67,
        "Simplifications. Six source sites, and several 'simplifications' would fold apart "
        "branches whose separation is deliberate for readability in the gates.",
        revisit_below=5,
        leans="tests",
    ),
)

DEFERRED_MYPY_FLAGS = (
    Deferral(
        "--strict",
        1272,
        "1025 of the 1272 are no-untyped-def and 1208 sit in the suite rather than in source, so "
        "strict mode here buys annotations, not correctness. The correctness-bearing subset was "
        "enabled instead and is what `MYPY_FLAGS` carries: --check-untyped-defs, 14 findings at "
        "the time, all 14 fixed. The 64 source findings are mostly type-arg on bare generics.",
        revisit_below=100,
        leans="tests",
    ),
    Deferral(
        "--disallow-untyped-defs",
        1025,
        "Every one of the 1025 is no-untyped-def and 1015 are in the suite -- this flag is the "
        "annotation half of --strict with none of its extras. Annotating the suite is a separate "
        "project with its own review, and only 10 of the findings are in source.",
        revisit_below=100,
        leans="tests",
    ),
)


def _selected_ruff_rules() -> list[str]:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    rules: list[str] = config["tool"]["ruff"]["lint"]["select"]
    return rules


def _enabled_rule_codes() -> set[str]:
    """Every rule code ruff actually resolves as enabled, e.g. {"E501", "BLE001"}.

    Asked of ruff rather than inferred from the select list: rule prefixes are
    not string prefixes of each other. Selecting ``A`` (flake8-builtins) does
    not enable ``ARG`` (flake8-unused-arguments), so a naive ``startswith``
    check reports ARG as enabled when it is not.
    """
    result = run_ruff(["check", "--show-settings", "pyproject.toml"], timeout=120)
    marker = "linter.rules.enabled = ["
    # Checked before splitting: if --show-settings ever changes shape, an
    # IndexError here would surface as an unrelated test error rather than
    # "this probe no longer understands ruff's output".
    assert marker in result.stdout, (
        "ruff --show-settings no longer contains "
        f"{marker!r}; this probe needs updating before its verdict means anything"
    )
    block = result.stdout.split(marker, 1)[1].split("\n]", 1)[0]
    codes = set(re.findall(r"\(([A-Z]+[0-9]+)\)", block))
    assert codes, "parsed ruff's enabled-rule block but found no rule codes in it"
    return codes


def _rule_family(code: str) -> str:
    """ "BLE001" -> "BLE". Splits on the first digit, which is how ruff codes
    are structured (letters identify the linter, digits the rule)."""
    match = re.match(r"([A-Z]+)", code)
    return match.group(1) if match else code


def _ruff_split(rule: str) -> tuple[int, int]:
    """`(source, tests)` findings for one rule, by the same path rule as mypy's."""
    source = tests = 0
    for finding in ruff_json(["check", ".", "--select", rule, "--no-cache"]):
        path = finding["filename"].replace("\\", "/")
        name = path.rsplit("/", 1)[-1]
        if "/tests/" in path or name.startswith("test_") or name == "conftest.py":
            tests += 1
        else:
            source += 1
    return source, tests


def _ruff_count(rule: str) -> int:
    """Findings for one rule. Raises rather than returning 0 on a failed run.

    This is the load-bearing case for that distinction: a silent 0 here reads
    as "the rule got cheap", and the caller turns that into "enable it, or
    rewrite the reason" -- a tool failure reported as a policy conclusion.
    """
    return len(ruff_json(["check", ".", "--select", rule, "--no-cache"]))


#: `NAME := value` / `NAME ?= value`, which is every assignment this file needs.
#: Recipe lines are tab-indented so `^` never reaches them.
_MAKE_ASSIGNMENT = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*[:?]?=\s*(.*)$", re.M)
#: mypy's closing line. `Success:` means zero and is handled by the caller.
_MYPY_TOTAL = re.compile(r"^Found (\d+) errors? in \d+ files?", re.M)
#: A path is test code when it sits under `tests/`, is named `test_*.py`, or is
#: a `conftest.py`. The same rule the recorded splits are stated against.
_MYPY_FINDING = re.compile(r"^(\S+?):\d+: error:", re.M)


def _makefile_variables() -> dict[str, str]:
    """The Makefile's simple assignments, with `$(NAME)` references expanded.

    Read rather than restated so a target or flag added to the Makefile cannot
    leave this register measuring something the repository no longer typechecks
    -- which is the same reason `test_check_untyped_defs_is_wired_into_the_lint_targets`
    reads it instead of trusting a literal.
    """
    raw = dict(_MAKE_ASSIGNMENT.findall((REPO / "Makefile").read_text(encoding="utf-8")))
    resolved: dict[str, str] = {}
    for name, value in raw.items():
        for _ in range(4):  # references in this file are one level deep; cap the walk
            expanded = re.sub(r"\$\((\w+)\)", lambda m: raw.get(m.group(1), m.group(0)), value)
            if expanded == value:
                break
            value = expanded
        resolved[name] = value.strip()
    return resolved


def _mypy_strictness_in_effect() -> set[str]:
    """Strictness this repository actually typechecks with, as flag names.

    Both routes, because a flag reaching mypy by either one makes a deferral
    here stale cover: the `MYPY_FLAGS` the Makefile passes on the command line,
    and `[tool.mypy]` in `pyproject.toml`, where `strict = true` would enable
    the same thing without appearing on any command line at all.
    """
    flags = set(_makefile_variables().get("MYPY_FLAGS", "").split())
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    for key, value in config.get("tool", {}).get("mypy", {}).items():
        if value is True:
            flags.add("--" + key.replace("_", "-"))
    return flags


@functools.cache
def _mypy_findings(flag: str) -> tuple[int, int, int]:
    """`(total, source, tests)` errors over the Makefile's own targets, plus `flag`.

    Cold and into a throwaway cache directory. `make lint-cold` is what CI runs,
    and mypy keys its cache on the options it ran with, so a `--strict` run
    sharing the default directory would make the next ordinary typecheck
    recompute everything -- a measurement that slows down the thing it measures.

    Raises rather than returning 0 when mypy itself fails, for the reason
    `_ruff_count` gives: a silent 0 reads as "the flag got cheap", and the
    caller turns that into a policy conclusion.
    """
    targets = _makefile_variables()["MYPY_TARGETS"].split()
    with tempfile.TemporaryDirectory() as cache:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                *targets,
                "--explicit-package-bases",
                flag,
                "--no-incremental",
                "--cache-dir",
                cache,
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=900,
        )
    if result.returncode >= 2:  # 0 clean, 1 errors found, 2+ mypy could not run
        raise AssertionError(
            f"mypy invocation failed (exit {result.returncode}) for {flag}\nstderr:\n{result.stderr.strip()[:2000]}"
        )
    if "Success: no issues found" in result.stdout:
        return 0, 0, 0
    match = _MYPY_TOTAL.search(result.stdout)
    assert match is not None, (
        f"mypy printed no recognisable summary for {flag}; this probe needs updating "
        f"before its verdict means anything. stdout ends: {result.stdout[-300:]!r}"
    )
    tests = 0
    paths = _MYPY_FINDING.findall(result.stdout)
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if "/tests/" in path or name.startswith("test_") or name == "conftest.py":
            tests += 1
    total = int(match.group(1))
    # The per-line count and the summary must agree, or the split below is a
    # fraction of something other than the total it is reported against.
    assert len(paths) == total, (
        f"mypy reported {total} errors for {flag} but {len(paths)} parseable error lines; "
        "the output shape changed and this probe can no longer split it"
    )
    return total, total - tests, tests


class TestDeferralsAreHonest:
    @pytest.mark.parametrize("deferral", DEFERRED_RUFF_RULES, ids=lambda d: d.rule)
    def test_deferred_rule_is_not_secretly_enabled(self, deferral: Deferral) -> None:
        """An entry naming an enabled rule is stale cover: it reads as a
        considered decision while describing something that already happened."""
        assert deferral.rule not in _selected_ruff_rules(), (
            f"{deferral.rule} is in the ruff select set but still recorded as deferred. Delete the entry."
        )
        # And catch it being enabled through a broader selector -- selecting
        # "TRY" would enable "TRY400" without naming it.
        enabled = _enabled_rule_codes()
        matching = {
            code
            for code in enabled
            if code == deferral.rule
            or (code.startswith(deferral.rule) and _rule_family(code) == _rule_family(deferral.rule + "0"))
        }
        assert not matching, (
            f"{deferral.rule} is enabled via a broader selector ({sorted(matching)[:3]}); delete its deferral entry."
        )

    @pytest.mark.parametrize("deferral", DEFERRED_RUFF_RULES, ids=lambda d: d.rule)
    def test_deferral_is_still_expensive_enough_to_defer(self, deferral: Deferral) -> None:
        """If a rule got cheap, the recorded reason no longer applies and the
        decision deserves to be made again rather than inherited."""
        actual = _ruff_count(deferral.rule)
        assert actual >= deferral.revisit_below, (
            f"{deferral.rule} now reports {actual} findings (recorded {deferral.measured}, "
            f"revisit below {deferral.revisit_below}). The cost that justified deferring it is "
            "gone -- enable it, or rewrite the reason."
        )

    @pytest.mark.parametrize("deferral", DEFERRED_RUFF_RULES + DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule)
    def test_the_side_the_reason_argues_from_still_dominates(self, deferral: Deferral) -> None:
        """A count staying high is not the same as the reason staying true.
        `T20` is deferred because its hits are the gates' own stdout contract and
        `ARG` because its hits are fixture parameters; if either inverted, the
        count would be untouched and the recorded argument would be wrong."""
        if deferral.rule.startswith("--"):
            _, source, tests = _mypy_findings(deferral.rule)
        else:
            source, tests = _ruff_split(deferral.rule)
        dominant = "source" if source > tests else "tests"
        assert dominant == deferral.leans, (
            f"{deferral.rule} findings now lean {dominant} ({source} source, {tests} tests), "
            f"but its reason argues from {deferral.leans}. Re-read the reason before trusting it."
        )

    def test_the_makefile_targets_resolve_to_real_directories(self) -> None:
        """The positive control for the expander. An unexpanded `$(SHARED_SRC)`
        would make mypy exit 2 and every measurement below an assertion about a
        tool failure rather than about this repository."""
        targets = _makefile_variables()["MYPY_TARGETS"].split()
        assert targets, "MYPY_TARGETS resolved to nothing; the expander is broken"
        for target in targets:
            assert "$" not in target, f"{target} left a Makefile variable unexpanded"
            assert (REPO / target).is_dir(), f"{target} is not a directory in this checkout"

    def test_a_failed_mypy_invocation_raises_rather_than_reporting_zero(self) -> None:
        """The same distinction `_ruff_count` documents, asserted here because
        the mypy half is the one whose numbers went unchecked: a silent 0 reads
        as "the flag got cheap", and the caller turns that into "enable it"."""
        with pytest.raises(AssertionError, match="mypy invocation failed"):
            _mypy_findings("--no-such-mypy-flag")

    @pytest.mark.parametrize("deferral", DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule)
    def test_deferred_flag_is_not_secretly_enabled(self, deferral: Deferral) -> None:
        """The ruff half had this check and the mypy half did not, so `--strict`
        could have been added to `MYPY_FLAGS` with its entry here still reading
        as a considered decision."""
        in_effect = _mypy_strictness_in_effect()
        assert deferral.rule not in in_effect, (
            f"{deferral.rule} is already in effect (MYPY_FLAGS or [tool.mypy]) but still "
            "recorded as deferred. Delete the entry."
        )
        if deferral.rule != "--strict":
            # `--strict` turns on `disallow_untyped_defs` among others, so
            # enabling it makes every entry here stale cover without naming one.
            assert "--strict" not in in_effect, (
                f"--strict is in effect, which enables {deferral.rule} without naming it; delete that entry too."
            )

    @pytest.mark.parametrize("deferral", DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule)
    def test_deferred_flag_is_still_expensive_enough_to_defer(self, deferral: Deferral) -> None:
        """The other half the mypy entries were missing: their numbers were
        asserted to exist and never to be true, and both had roughly doubled
        unnoticed. Measured over the Makefile's `MYPY_TARGETS`, which is what
        enabling the flag would actually cost."""
        total, _, _ = _mypy_findings(deferral.rule)
        assert total >= deferral.revisit_below, (
            f"{deferral.rule} now reports {total} errors (recorded {deferral.measured}, "
            f"revisit below {deferral.revisit_below}). The cost that justified deferring it is "
            "gone -- enable it, or rewrite the reason."
        )

    @pytest.mark.parametrize("deferral", DEFERRED_RUFF_RULES + DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule)
    def test_every_deferral_has_a_substantive_reason(self, deferral: Deferral) -> None:
        assert len(deferral.reason.strip()) > 100, (
            f"{deferral.rule} needs a reason someone can disagree with, not a placeholder"
        )

    @pytest.mark.parametrize("deferral", DEFERRED_RUFF_RULES + DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule)
    def test_every_deferral_carries_a_measured_number(self, deferral: Deferral) -> None:
        """'Too expensive' with no number is an opinion. The count is what makes
        the trade-off reviewable."""
        assert deferral.measured > 0
        assert deferral.revisit_below < deferral.measured

    def test_the_register_is_not_empty(self) -> None:
        assert DEFERRED_RUFF_RULES and DEFERRED_MYPY_FLAGS


class TestEnabledRulesStayEnabled:
    """The other half: rules bought with real fixes must not be quietly dropped."""

    HARD_WON = {
        "BLE": "makes 27 documented fail-closed justifications enforced rather than prose",
        "RUF100": "keeps every noqa in the tree load-bearing; safe only because BLE is on",
    }

    @pytest.mark.parametrize("rule", sorted(HARD_WON))
    def test_rule_is_still_selected(self, rule: str) -> None:
        assert rule in _selected_ruff_rules(), (
            f"{rule} was removed from the ruff select set. It was enabled deliberately: {self.HARD_WON[rule]}."
        )

    def test_check_untyped_defs_is_wired_into_the_lint_targets(self) -> None:
        makefile = (REPO / "Makefile").read_text(encoding="utf-8")
        assert "--check-untyped-defs" in makefile, (
            "mypy's --check-untyped-defs was dropped from the Makefile. It is the "
            "correctness-bearing subset of --strict and cost 14 fixes to enable."
        )
        for target in ("lint-python:", "lint-cold:"):
            assert "$(MYPY_FLAGS)" in makefile.split(target, 1)[1].split("\n.PHONY", 1)[0], (
                f"{target} does not pass MYPY_FLAGS, so it typechecks more loosely than intended"
            )
