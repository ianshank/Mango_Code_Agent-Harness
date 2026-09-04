"""A present policy that lost a key must stop the gate, not feed it a literal.

One reproduction per defect that reached ``main`` (DEC-043, R-CQ-8). Every case
below was confirmed **failing against ``origin/main``** before the fix landed;
the commands are in the module's own test at the bottom, and the PR body records
the run. A test in this directory that cannot fail is worse than no test.

The defect is one line repeated in three readers: ``section.get(key, default)``.
It cannot distinguish *this adopter has no policy file, so use the built-in*
from *the policy governing this run no longer states this*, and it answered the
literal for both. The Node reader has thrown for the second case since it
shipped (``policy.ts:58-69``), so the two stacks disagreed about whether a
governance policy may be incomplete.

What makes it a regression worth pinning rather than a tidy-up: **the
substituted value is always a plausible one**. Nothing looks wrong afterwards.
A policy that lost ``coverage.lines`` still reported ``[PASS] Coverage lines:
… >= 90.00%``, and the 90 came from this repository's source rather than from
the file a reviewer was pointed at.

These drive the *public* accessors -- the ones gates actually call -- rather
than the private helpers, so a refactor that moves the check elsewhere still
has to keep the behaviour.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared import policy_loader, validate_invariants
from harness.shared.policy_loader import PolicyError

pytestmark = pytest.mark.governance

#: Every accessor a gate or the runtime calls, the block it reads, and one key
#: whose absence must stop the run. Parametrised because the defect was in the
#: shared helper: fixing one accessor and not the rest would leave the hole
#: behind a passing test.
POLICY_ACCESSORS = [
    pytest.param("orchestrator_defaults", "orchestrator", "max_iterations", id="orchestrator"),
    pytest.param("nemotron_defaults", "nemotron", "temperature", id="nemotron"),
    pytest.param("langgraph_defaults", "langgraph", "recursion_limit", id="langgraph"),
    pytest.param("coverage_defaults", "coverage", "lines", id="coverage"),
    pytest.param("agent_defaults", "agent_defaults", "max_delegation_depth", id="agent-defaults"),
    pytest.param("lats_defaults", "lats", "max_budget", id="lats"),
]


def _policy(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "governance-policy.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


class TestAPresentPolicyMissingAKeyStopsTheRun:
    """Defect 1: the readers substituted a built-in for a key that was gone."""

    @pytest.mark.parametrize(("accessor", "block", "key"), POLICY_ACCESSORS)
    def test_a_missing_key_raises_rather_than_defaulting(
        self, tmp_path: Path, accessor: str, block: str, key: str
    ) -> None:
        path = _policy(tmp_path, {block: {}})
        with pytest.raises(PolicyError) as excinfo:
            getattr(policy_loader, accessor)(path)
        assert key in str(excinfo.value), "the error must name the key, or it cannot be fixed"

    @pytest.mark.parametrize(("accessor", "block", "key"), POLICY_ACCESSORS)
    def test_an_absent_policy_is_still_the_adopter_path(
        self, tmp_path: Path, accessor: str, block: str, key: str
    ) -> None:
        """The control that keeps the fix from being a different defect.

        Absence is a supported deployment: a stack that has not adopted
        ``governance-policy.json`` gets built-in defaults and a working harness.
        Failing closed on absence too would break every adopter to close a hole
        that only exists when a file is present.
        """
        assert key in getattr(policy_loader, accessor)(tmp_path / "no-policy-here.json")


class TestTheProtectedPathGateCannotPassOverAnEmptySet:
    """Defect 2, and the worst of them.

    ``load_protected_patterns`` fell back to ``[".github/**"]``. One pattern
    still matched something, so the run printed ``[PASS] Protected Paths`` while
    the enforcement layer, the agent control surface and the runtime enforcement
    modules -- the three groups ``harness/CONTRACT.md`` documents -- were all
    unprotected. A gate whose report cannot be told apart from a real pass is
    worse than no gate, because it is trusted.
    """

    def test_a_policy_without_protected_paths_exits_non_zero(self, tmp_path: Path) -> None:
        path = _policy(tmp_path, {"limits": {"size_budget_lines": 500}})
        with pytest.raises(SystemExit) as exc:
            validate_invariants.load_protected_patterns(path)
        assert exc.value.code == 1

    def test_an_explicitly_empty_list_is_honoured(self, tmp_path: Path) -> None:
        """``"protected_paths": []`` is a decision someone wrote down; a missing
        key is a decision nobody made. Failing closed on both would make the
        empty case unexpressible for an adopter standing the harness up."""
        assert validate_invariants.load_protected_patterns(_policy(tmp_path, {"protected_paths": []})) == []


class TestABudgetOverrideCannotSwitchAGateOff:
    """Defect 3: ``MAX_FILE_LINES`` and friends were returned verbatim.

    Anyone able to set an environment variable could raise a budget past every
    real file and the gate went on printing its PASS line. Tightening stays
    available, because a stricter local run is a real use and cannot weaken what
    the policy states.
    """

    @pytest.mark.parametrize(
        ("accessor", "env_var", "stated"),
        [
            pytest.param("size_budget_lines", "MAX_FILE_LINES", 500, id="source"),
            pytest.param("test_size_budget_lines", "MAX_TEST_FILE_LINES", 700, id="test"),
        ],
    )
    def test_a_loosening_override_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        accessor: str,
        env_var: str,
        stated: int,
    ) -> None:
        path = _policy(
            tmp_path,
            {"protected_paths": [], "limits": {"size_budget_lines": 500, "test_size_budget_lines": 700}},
        )
        monkeypatch.setenv(env_var, "9999")
        assert getattr(validate_invariants, accessor)(path) == stated

    def test_a_tightening_override_still_applies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _policy(
            tmp_path,
            {"protected_paths": [], "limits": {"size_budget_lines": 500, "test_size_budget_lines": 700}},
        )
        monkeypatch.setenv("MAX_FILE_LINES", "80")
        assert validate_invariants.size_budget_lines(path) == 80

    def test_the_shim_budget_override_is_refused_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.shared import check_dedup

        (tmp_path / "harness" / "shared").mkdir(parents=True)
        (tmp_path / "harness" / "shared" / "governance-policy.json").write_text(
            json.dumps({"dedup": {"max_shim_lines": 12}}), encoding="utf-8"
        )
        monkeypatch.setenv("MAX_SHIM_LINES", "9999")
        assert check_dedup.load_config(tmp_path).max_shim_lines == 12


class TestAGatesExitStaysInsideTheRunItGates:
    """Defect 4: ``verify_zero_skips`` resolved its grammar at import.

    ``_decision_id_regex`` raises ``SystemExit`` on a malformed policy, which is
    right for a gate and fatal for an import: any importer inherited that exit
    as its own crash, with no call in the traceback that had asked for the
    grammar, and a shim guarding its delegation with ``except ImportError``
    cannot catch a ``BaseException``.

    Reproduced by staging the module beside a malformed policy, because
    ``_POLICY_PATH`` derives from ``__file__`` -- setting it after the import
    tests nothing, which the first version of this check did and which is
    recorded in the PR body rather than quietly fixed.
    """

    MODULE = Path(__file__).resolve().parents[3] / "shared" / "governance" / "verify_zero_skips.py"

    def test_importing_under_a_malformed_policy_does_not_exit(self, tmp_path: Path) -> None:
        import shutil

        governance = tmp_path / "shared" / "governance"
        governance.mkdir(parents=True)
        shutil.copy2(self.MODULE, governance / "verify_zero_skips.py")
        (tmp_path / "shared" / "governance-policy.json").write_text("{ not json", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util, sys;"
                    "spec = importlib.util.spec_from_file_location('vzs', sys.argv[1]);"
                    "m = importlib.util.module_from_spec(spec);"
                    "spec.loader.exec_module(m);"
                    "sys.exit(0)"
                ),
                str(governance / "verify_zero_skips.py"),
            ],
            capture_output=True, text=True, cwd=str(governance), check=False,
        )
        assert result.returncode == 0, result.stderr


class TestTheReproductionsAddressTheShippedReaders:
    """Guards the tier itself.

    Every assertion above runs against a public accessor a gate calls. If one
    were renamed or removed, these would error rather than silently stop
    covering the defect -- which is the failure mode a regression directory
    exists to prevent.
    """

    @pytest.mark.parametrize(("accessor", "_block", "_key"), POLICY_ACCESSORS)
    def test_every_named_policy_accessor_exists(self, accessor: str, _block: str, _key: str) -> None:
        assert callable(getattr(policy_loader, accessor))

    @pytest.mark.parametrize(
        "accessor", ["load_protected_patterns", "size_budget_lines", "test_size_budget_lines"]
    )
    def test_every_named_invariant_accessor_exists(self, accessor: str) -> None:
        assert callable(getattr(validate_invariants, accessor))
