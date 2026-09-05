"""How `validate_invariants` *reads* its policy, as distinct from what it checks.

Split out of ``test_validate_invariants.py`` when that module reached 712 lines
against the 700-line ``limits.test_size_budget_lines`` -- caught by the gate
itself, running against this repository, which is the outcome the budget exists
for. The seam is the concern, not the line count (DEC-035): that module tests
protected paths, secrets and size budgets; this one tests policy resolution --
what happens when the file is absent, incomplete, or states a value of the
wrong type.

Everything here is R-CQ-8 / DEC-043. The through-line: a gate that substitutes a
plausible value for one the policy no longer states, or coerces one the strict
reader would refuse, reports PASS against a threshold nobody wrote down.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from harness.shared import validate_invariants as vi

# `invariants_repo` is a fixture and arrives from `conftest.py` without an
# import; `invariants_policy_path` is an ordinary function and is imported.
# Both used to live in `test_validate_invariants.py` and were reached from here
# by importing across test modules -- which works, but reads as a redefinition
# to ruff at every use site and encodes "which module came first" as though it
# were a fact about the tests. `conftest.py` is the mechanism pytest provides.
from harness.shared.tests.conftest import _write_lines, invariants_policy_path

# --- R-CQ-8: a present policy that has lost a key must stop the gate ---


class TestAPresentPolicyMissingAKeyFailsClosed:
    """The gate must not report PASS against a threshold the policy stopped stating.

    Both readers here defaulted: `load_protected_patterns` fell back to
    `[".github/**"]` and `_policy_limit` to its built-in budget. Neither
    fallback is reachable from a malformed policy -- the JSON parses fine. What
    reaches them is a policy that is *valid and incomplete*, which is what a bad
    merge, a partial template or an over-eager edit produces, and the fallback
    then reports success over a set it is no longer checking.
    """

    def test_missing_protected_paths_fails_closed(self, tmp_path: Path):
        """The worst of the two: one surviving pattern, and a PASS over the rest.

        `[".github/**"]` still matches something, so the run printed
        `[PASS] Protected Paths` while the enforcement layer, the agent control
        surface and the runtime gates were all unprotected.
        """
        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"limits": {"size_budget_lines": 500}}), encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            vi.load_protected_patterns(policy)
        assert exc.value.code == 1

    def test_an_empty_protected_paths_list_is_a_statement_not_a_hole(self, tmp_path: Path):
        """Control. `"protected_paths": []` says "this adopter protects nothing
        yet", which is a decision someone wrote down; a missing key says nothing
        was decided. Failing closed on both would make the empty case
        unexpressible."""
        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"protected_paths": []}), encoding="utf-8")
        assert vi.load_protected_patterns(policy) == []

    @pytest.mark.parametrize(
        ("accessor", "key"),
        [
            pytest.param("size_budget_lines", "size_budget_lines", id="source"),
            pytest.param("test_size_budget_lines", "test_size_budget_lines", id="test"),
        ],
    )
    def test_a_missing_limit_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accessor: str, key: str
    ):
        monkeypatch.delenv(vi.SIZE_BUDGET_ENV, raising=False)
        monkeypatch.delenv(vi.TEST_SIZE_BUDGET_ENV, raising=False)
        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"limits": {}, "protected_paths": []}), encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            getattr(vi, accessor)(policy)
        assert exc.value.code == 1

    def test_an_absent_policy_is_still_the_adopter_path(self, tmp_path: Path, monkeypatch):
        """Control: absence is supported, and must not be collapsed into the above."""
        monkeypatch.delenv(vi.SIZE_BUDGET_ENV, raising=False)
        assert vi.size_budget_lines(tmp_path / "nothing.json") == vi.SIZE_BUDGET_LINES


class TestTheEnvOverrideTightensOnly:
    """`MAX_FILE_LINES=9999` used to be returned verbatim.

    Anyone able to set an environment variable could therefore switch the size
    gate off while it went on printing `[PASS] Size Budget` -- and a gate whose
    report is indistinguishable from a real pass is worse than no gate, because
    it is trusted. Tightening is still allowed: a stricter local run is a real
    use, and it cannot weaken what the policy states (R-CQ-8).
    """

    def test_env_override_tightens_only(self, invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
        policy = invariants_policy_path(invariants_repo)
        monkeypatch.setenv(vi.SIZE_BUDGET_ENV, "9999")
        assert vi.size_budget_lines(policy) == 500, "an override must not raise the budget"
        monkeypatch.setenv(vi.SIZE_BUDGET_ENV, "120")
        assert vi.size_budget_lines(policy) == 120, "an override must still tighten it"

    def test_env_override_equal_to_the_policy_is_not_a_change(
        self, invariants_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The boundary: `>=` not `>`, so an equal value is a no-op either way
        and the rule has no off-by-one to argue about."""
        monkeypatch.setenv(vi.SIZE_BUDGET_ENV, "500")
        assert vi.size_budget_lines(invariants_policy_path(invariants_repo)) == 500

    def test_the_test_budget_override_tightens_only_too(self, invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
        policy = invariants_policy_path(invariants_repo)
        monkeypatch.setenv(vi.TEST_SIZE_BUDGET_ENV, "9999")
        assert vi.test_size_budget_lines(policy) == 700
        monkeypatch.setenv(vi.TEST_SIZE_BUDGET_ENV, "300")
        assert vi.test_size_budget_lines(policy) == 300

    def test_an_ignored_override_says_so(self, invariants_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
        """Silently ignoring it is its own trap: the caller believes the budget
        moved and reads the PASS as meaning something it does not."""
        monkeypatch.setenv(vi.SIZE_BUDGET_ENV, "9999")
        with caplog.at_level(logging.WARNING, logger=vi.logger.name):
            vi.size_budget_lines(invariants_policy_path(invariants_repo))
        assert "only tighten" in caplog.text and "9999" in caplog.text

    def test_the_gate_still_fails_on_a_real_violation_under_a_loosening_override(
        self, invariants_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """End to end: the point of the rule is that this cannot be switched off."""
        _write_lines(invariants_repo / "huge.py", 600)
        monkeypatch.setenv(vi.SIZE_BUDGET_ENV, "9999")
        assert vi.check_size_budget(invariants_repo, policy_path=invariants_policy_path(invariants_repo)) is False


class TestAPolicyValueOfTheWrongTypeIsRefusedNotCoerced:
    """Two readers of one policy must agree about what is valid.

    `policy_loader._Section.int` type-checks; this module used `int(value)`,
    which accepts `"9999"` and `True` (a `bool` is an `int`, and `int(True)` is
    1). So a policy could state a budget as a string, have this gate enforce it,
    and have the strict reader refuse the identical file — the drift this branch
    exists to remove, reintroduced by a coercion.

    `protected_paths` is the sharper one: `list("Makefile")` is eleven
    single-character patterns matching no path at all, so a policy stating a
    bare string produced `[PASS] Protected Paths` over nothing. That is the same
    fail-open as the `[".github/**"]` default, reached by a different mistake.

    Both reported by a review bot on this PR.
    """

    def _policy(self, tmp_path: Path, body: dict) -> Path:
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    @pytest.mark.parametrize(
        ("stated", "note"),
        [
            pytest.param("9999", "a string coerces to a number", id="string"),
            pytest.param(True, "a bool is an int and coerces to 1", id="bool"),
            pytest.param(500.5, "a float truncates silently", id="float"),
            pytest.param(None, "null is not a budget", id="null"),
        ],
    )
    def test_a_non_integer_budget_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stated: object, note: str
    ):
        monkeypatch.delenv(vi.SIZE_BUDGET_ENV, raising=False)
        policy = self._policy(tmp_path, {"protected_paths": [], "limits": {"size_budget_lines": stated}})
        with pytest.raises(SystemExit) as exc:
            vi.size_budget_lines(policy)
        assert exc.value.code == 1, note

    def test_an_integer_budget_is_still_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Control: the type check must not refuse the valid case."""
        monkeypatch.delenv(vi.SIZE_BUDGET_ENV, raising=False)
        policy = self._policy(tmp_path, {"protected_paths": [], "limits": {"size_budget_lines": 500}})
        assert vi.size_budget_lines(policy) == 500

    @pytest.mark.parametrize(
        ("stated", "note"),
        [
            pytest.param("Makefile", "a string iterates into characters", id="string"),
            pytest.param({"a": 1}, "a mapping iterates into keys", id="mapping"),
            pytest.param(["ok", 7], "a non-string member is not a pattern", id="mixed-list"),
        ],
    )
    def test_a_malformed_protected_paths_fails_closed(self, tmp_path: Path, stated: object, note: str):
        with pytest.raises(SystemExit) as exc:
            vi.load_protected_patterns(self._policy(tmp_path, {"protected_paths": stated}))
        assert exc.value.code == 1, note

    def test_the_string_case_would_otherwise_have_protected_nothing(self, tmp_path: Path):
        """Names the consequence, so a future relaxation has to argue with it:
        `list("Makefile")` matches no path, and the gate would have reported
        PASS over every protected file in the repository."""
        import fnmatch

        assert not any(fnmatch.fnmatch("Makefile", ch) for ch in list("Makefile"))
