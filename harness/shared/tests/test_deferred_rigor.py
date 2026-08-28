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
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on the 3.9/3.10 matrix legs
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


DEFERRED_RUFF_RULES = (
    Deferral(
        "T20", 30,
        "All 30 source hits are gate scripts printing their verdict line (`zero-skip: passed`, "
        "`projections: passed`). That stdout is the gates' CLI contract, pinned by "
        "test_gate_logging.py; converting it to logging would break the contract for no "
        "governance gain.",
        revisit_below=5,
    ),
    Deferral(
        "TRY400", 11,
        "Every site is a `[FAIL] <verdict>` line for an *expected* validation failure, inside "
        "an except clause that already names narrow exception types. logging.exception would "
        "replace a one-line operator-facing verdict with a traceback whose content is already "
        "in the message, and would fight test_gate_logging.py's stdout pins.",
        revisit_below=3,
    ),
    Deferral(
        "TRY003", 90,
        "Long messages inside raise statements. Fixing them means inventing 90 exception "
        "subclasses; the messages are already specific and the change buys no behaviour.",
        revisit_below=20,
    ),
    Deferral(
        "S", 1118,
        "Bandit. 1100+ are assert-in-test (S101), and the remaining source hits are the "
        "subprocess calls that gate scripts exist to make. Enabling it needs blanket waivers, "
        "which CLAUDE.md forbids without decision-log entries.",
        revisit_below=100,
    ),
    Deferral(
        "PT", 134,
        "pytest style, entirely in tests. Large mechanical churn across a suite this programme "
        "is already reshaping; the two changes would be impossible to review separately.",
        revisit_below=30,
    ),
    Deferral(
        "ARG", 40,
        "Unused arguments. Exactly one is in source; the other 39 are pytest fixture parameters "
        "requested for their side effects, which is the idiomatic way to use a fixture.",
        revisit_below=5,
    ),
    Deferral(
        "PLW1510", 31,
        "subprocess.run without an explicit check=. Several sites deliberately tolerate a "
        "non-zero exit and inspect returncode themselves, so a blanket fix would change "
        "behaviour. Needs a site-by-site review, not a rule flip.",
        revisit_below=5,
    ),
    Deferral(
        "PTH", 30,
        "os.path -> pathlib. Cosmetic in a codebase that already uses pathlib for new code; "
        "three source sites, the rest tests.",
        revisit_below=5,
    ),
    Deferral(
        "SIM", 25,
        "Simplifications. Four source sites, and several 'simplifications' would fold apart "
        "branches whose separation is deliberate for readability in the gates.",
        revisit_below=5,
    ),
)

DEFERRED_MYPY_FLAGS = (
    Deferral(
        "--strict", 604,
        "533 of the 604 are no-untyped-def on test functions. Strict mode here buys annotations, "
        "not correctness. The correctness-bearing subset (--check-untyped-defs, 14 findings) was "
        "enabled instead, and all 14 were fixed.",
        revisit_below=100,
    ),
    Deferral(
        "--disallow-untyped-defs", 533,
        "The same 533 test-function annotations, without even the strict-mode extras. Annotating "
        "the suite is a separate project with its own review.",
        revisit_below=100,
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
    """"BLE001" -> "BLE". Splits on the first digit, which is how ruff codes
    are structured (letters identify the linter, digits the rule)."""
    match = re.match(r"([A-Z]+)", code)
    return match.group(1) if match else code


def _ruff_count(rule: str) -> int:
    """Findings for one rule. Raises rather than returning 0 on a failed run.

    This is the load-bearing case for that distinction: a silent 0 here reads
    as "the rule got cheap", and the caller turns that into "enable it, or
    rewrite the reason" -- a tool failure reported as a policy conclusion.
    """
    return len(ruff_json(["check", ".", "--select", rule, "--no-cache"]))


class TestDeferralsAreHonest:
    @pytest.mark.parametrize("deferral", DEFERRED_RUFF_RULES, ids=lambda d: d.rule)
    def test_deferred_rule_is_not_secretly_enabled(self, deferral: Deferral) -> None:
        """An entry naming an enabled rule is stale cover: it reads as a
        considered decision while describing something that already happened."""
        assert deferral.rule not in _selected_ruff_rules(), (
            f"{deferral.rule} is in the ruff select set but still recorded as deferred. "
            "Delete the entry."
        )
        # And catch it being enabled through a broader selector -- selecting
        # "TRY" would enable "TRY400" without naming it.
        enabled = _enabled_rule_codes()
        matching = {
            code for code in enabled
            if code == deferral.rule
            or (code.startswith(deferral.rule) and _rule_family(code) == _rule_family(deferral.rule + "0"))
        }
        assert not matching, (
            f"{deferral.rule} is enabled via a broader selector ({sorted(matching)[:3]}); "
            "delete its deferral entry."
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

    @pytest.mark.parametrize(
        "deferral", DEFERRED_RUFF_RULES + DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule
    )
    def test_every_deferral_has_a_substantive_reason(self, deferral: Deferral) -> None:
        assert len(deferral.reason.strip()) > 100, (
            f"{deferral.rule} needs a reason someone can disagree with, not a placeholder"
        )

    @pytest.mark.parametrize(
        "deferral", DEFERRED_RUFF_RULES + DEFERRED_MYPY_FLAGS, ids=lambda d: d.rule
    )
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
            f"{rule} was removed from the ruff select set. It was enabled deliberately: "
            f"{self.HARD_WON[rule]}."
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
