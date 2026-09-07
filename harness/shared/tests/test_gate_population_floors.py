"""Anti-vacuity population floors for `check_dedup` and `check_py_compat` (R-AEI-3, AC-4).

Both gates exited 0 against an empty directory and printed
`[PASS] 0 per-stack script(s) delegate...` / `[PASS] 0 file(s) compatible with Python
(undeclared).` — a verdict a reader cannot tell apart from a real pass, and exactly what
a gate pointed at the wrong root also prints. `check_traceability`'s
`traceability.min_discovered_requirement_ids` already fails closed on that shape; these
tests pin the same idiom on the two drift gates, sourced from a new top-level `gates`
block in `governance-policy.json` and read through `policy_loader.gate_floors`.

Each gate is exercised at three populations — empty, one below the declared floor, and
exactly at it — and then the *same tree* is run twice against two policies that differ
only in the floor, which is what makes "the number comes from the policy file" a claim
the suite can fail rather than one the reader has to take on trust.

**The boundary this suite also documents.** The built-in default is 0, so a tree with no
policy file at all (the adopter path) keeps the pre-change behaviour, including on an
empty tree. That is not a preference: `test_check_dedup.py` and `test_check_py_compat.py`
each run their gate over an empty fixture repo with no policy and assert exit 0
(`test_cli_survives_a_bogus_log_level`), so a non-zero built-in floor would turn two
existing tests red. The floor is therefore something a deployment declares, and this
repository declares it — `test_the_shipped_policy_declares_a_live_floor` is what keeps
that declaration from being quietly zeroed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared import check_dedup as cd
from harness.shared import check_py_compat as cc
from harness.shared import policy_loader
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

POLICY_RELPATH = Path("harness") / "shared" / "governance-policy.json"

WORKFLOW = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9"]
    steps:
      - uses: actions/checkout@v4
"""

LEGACY_SAFE = """\
from typing import Optional


def f(x: Optional[str] = None) -> Optional[int]:
    return None
"""

SHARED_MODULE = """\
def compute(a, b):
    total = 0
    for i in range(a, b):
        total += i
    return total
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _policy(root: Path, **gates: int) -> Path:
    """Write a policy declaring only the `gates` block the gate under test reads."""
    return _write(root / POLICY_RELPATH, json.dumps({"gates": gates}))


def _dedup_tree(root: Path, scripts: int, floor: int | None = None) -> Path:
    """A repo with `scripts` per-stack shims, each delegating to a shared module."""
    (root / "harness" / "shared").mkdir(parents=True, exist_ok=True)
    (root / "harness" / "node" / "scripts").mkdir(parents=True, exist_ok=True)
    for i in range(scripts):
        _write(root / "harness" / "shared" / f"mod{i}.py", SHARED_MODULE)
        _write(
            root / "harness" / "node" / "scripts" / f"mod{i}.py",
            f"from harness.shared.mod{i} import compute  # noqa: F401\n",
        )
    if floor is not None:
        _policy(root, dedup_min_scripts=floor, py_compat_min_files=0)
    return root


def _py_compat_tree(root: Path, files: int, floor: int | None = None) -> Path:
    """A repo declaring a 3.9 matrix and holding `files` legacy-safe modules."""
    _write(root / ".github" / "workflows" / "ci.yml", WORKFLOW)
    (root / "harness" / "shared").mkdir(parents=True, exist_ok=True)
    for i in range(files):
        _write(root / "pkg" / f"mod{i}.py", LEGACY_SAFE)
    if floor is not None:
        _policy(root, dedup_min_scripts=0, py_compat_min_files=floor)
    return root


# --- AC-4: an empty population is refused ----------------------------------------


def test_gate_refuses_empty_population_dedup(tmp_path: Path) -> None:
    """`check_dedup` printed `[PASS] 0 per-stack script(s)` on an empty tree."""
    root = _dedup_tree(tmp_path / "repo", scripts=0, floor=1)
    assert cd.main(["--repo-root", str(root)]) == 1


def test_gate_refuses_empty_population_py_compat(tmp_path: Path) -> None:
    """`check_py_compat` printed `[PASS] 0 file(s) compatible` on an empty tree."""
    root = _py_compat_tree(tmp_path / "repo", files=0, floor=1)
    assert cc.main(["--repo-root", str(root)]) == 1


def test_gate_refuses_empty_population_with_no_workflow_matrix(tmp_path: Path) -> None:
    """The bare empty directory from the bug report: no matrix, no files, a floor.

    `resolve_min_version` returns None here, so `run` returns before scanning
    anything and the compatibility checks never execute. The floor still applies,
    because it is a statement about the population and not about the checks.
    """
    root = tmp_path / "repo"
    _policy(root, dedup_min_scripts=1, py_compat_min_files=1)
    assert cc.main(["--repo-root", str(root)]) == 1
    assert cd.main(["--repo-root", str(root)]) == 1


# --- AC-4: one below the floor fails, exactly at the floor passes ------------------


def test_dedup_population_one_below_the_floor_fails(tmp_path: Path) -> None:
    root = _dedup_tree(tmp_path / "repo", scripts=2, floor=3)
    assert cd.main(["--repo-root", str(root)]) == 1


def test_dedup_population_at_the_floor_passes(tmp_path: Path) -> None:
    root = _dedup_tree(tmp_path / "repo", scripts=3, floor=3)
    assert cd.main(["--repo-root", str(root)]) == 0


def test_py_compat_population_one_below_the_floor_fails(tmp_path: Path) -> None:
    root = _py_compat_tree(tmp_path / "repo", files=2, floor=3)
    assert cc.main(["--repo-root", str(root)]) == 1


def test_py_compat_population_at_the_floor_passes(tmp_path: Path) -> None:
    root = _py_compat_tree(tmp_path / "repo", files=3, floor=3)
    assert cc.main(["--repo-root", str(root)]) == 0


def test_dedup_floor_failure_is_not_a_drift_failure(tmp_path: Path) -> None:
    """The refusal must be the floor's, not a shim that failed to delegate.

    Without this, a tree that happened to contain drifted scripts would satisfy the
    two tests above for the wrong reason.
    """
    root = _dedup_tree(tmp_path / "repo", scripts=2, floor=3)
    report = cd.run(cd.load_config(root))
    assert report.ok, f"fixture is not clean: {report.failures}"
    assert len(report.checked) == 2
    assert cd.main(["--repo-root", str(root)]) == 1


def test_py_compat_floor_failure_is_not_a_compatibility_failure(tmp_path: Path) -> None:
    """As above: the fixture must be compatible, so only the floor can refuse it."""
    root = _py_compat_tree(tmp_path / "repo", files=2, floor=3)
    report = cc.run(root, cc.resolve_min_version(root))
    assert report.ok, f"fixture is not compatible: {report.violations}"
    assert cc.main(["--repo-root", str(root)]) == 1


# --- AC-4: the floor is read from the policy, not compiled into the gate -----------


def test_dedup_floor_comes_from_the_policy_file(tmp_path: Path) -> None:
    """One tree, two policies differing only in the floor, two verdicts."""
    root = _dedup_tree(tmp_path / "repo", scripts=2)

    _policy(root, dedup_min_scripts=2, py_compat_min_files=0)
    assert cd.main(["--repo-root", str(root)]) == 0

    _policy(root, dedup_min_scripts=3, py_compat_min_files=0)
    assert cd.main(["--repo-root", str(root)]) == 1


def test_py_compat_floor_comes_from_the_policy_file(tmp_path: Path) -> None:
    root = _py_compat_tree(tmp_path / "repo", files=2)

    _policy(root, dedup_min_scripts=0, py_compat_min_files=2)
    assert cc.main(["--repo-root", str(root)]) == 0

    _policy(root, dedup_min_scripts=0, py_compat_min_files=3)
    assert cc.main(["--repo-root", str(root)]) == 1


def test_each_gate_reads_only_its_own_floor(tmp_path: Path) -> None:
    """A floor high enough to fail the *other* gate must not fail this one."""
    root = _dedup_tree(tmp_path / "repo", scripts=2)
    _policy(root, dedup_min_scripts=2, py_compat_min_files=9999)
    assert cd.main(["--repo-root", str(root)]) == 0

    root = _py_compat_tree(tmp_path / "other", files=2)
    _policy(root, dedup_min_scripts=9999, py_compat_min_files=2)
    assert cc.main(["--repo-root", str(root)]) == 0


def test_the_refusal_names_the_policy_key(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """An operator who cannot find the knob cannot raise or review it."""
    root = _dedup_tree(tmp_path / "repo", scripts=0, floor=1)
    with caplog.at_level("ERROR", logger=cd.logger.name):
        assert cd.main(["--repo-root", str(root)]) == 1
    assert "gates.dedup_min_scripts" in caplog.text

    caplog.clear()
    root = _py_compat_tree(tmp_path / "other", files=0, floor=1)
    with caplog.at_level("ERROR", logger=cc.logger.name):
        assert cc.main(["--repo-root", str(root)]) == 1
    assert "gates.py_compat_min_files" in caplog.text


# --- the accessor: adopter path, and fail-closed on a policy that carries the block ---


def test_absent_policy_yields_built_in_defaults(tmp_path: Path) -> None:
    """The adopter path: no policy file, no declared floor, built-in defaults."""
    assert policy_loader.gate_floors(tmp_path / "does-not-exist.json") == {
        "dedup_min_scripts": 0,
        "py_compat_min_files": 0,
    }


def test_both_gates_still_run_without_a_policy_file(tmp_path: Path) -> None:
    """Constraint: an adopter with no policy keeps the behaviour they have today."""
    root = _dedup_tree(tmp_path / "repo", scripts=1)
    assert not (root / POLICY_RELPATH).exists()
    assert cd.main(["--repo-root", str(root)]) == 0

    root = _py_compat_tree(tmp_path / "other", files=1)
    assert not (root / POLICY_RELPATH).exists()
    assert cc.main(["--repo-root", str(root)]) == 0


def test_a_present_block_missing_a_key_is_a_policy_error(tmp_path: Path) -> None:
    """DEC-043: a policy that carries the block and drops a key never substitutes."""
    path = _write(tmp_path / "policy.json", json.dumps({"gates": {"dedup_min_scripts": 3}}))
    with pytest.raises(policy_loader.PolicyError) as exc:
        policy_loader.gate_floors(path)
    assert "py_compat_min_files" in str(exc.value)


def test_a_wrongly_typed_floor_is_a_policy_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "policy.json",
        json.dumps({"gates": {"dedup_min_scripts": "20", "py_compat_min_files": 298}}),
    )
    with pytest.raises(policy_loader.PolicyError):
        policy_loader.gate_floors(path)


def test_a_non_object_gates_block_is_a_policy_error(tmp_path: Path) -> None:
    path = _write(tmp_path / "policy.json", json.dumps({"gates": []}))
    with pytest.raises(policy_loader.PolicyError):
        policy_loader.gate_floors(path)


@pytest.mark.parametrize("gate", ["dedup", "py_compat"])
def test_a_malformed_floor_refuses_the_gate_rather_than_raising(tmp_path: Path, gate: str) -> None:
    """A PolicyError must reach the operator as a gate refusal, not a traceback."""
    root = tmp_path / gate
    _write(root / POLICY_RELPATH, json.dumps({"gates": {"dedup_min_scripts": 1}}))
    main = cd.main if gate == "dedup" else cc.main
    assert main(["--repo-root", str(root)]) == 1


# --- the shipped policy: the declaration must stay live ---------------------------


def test_the_shipped_policy_declares_a_live_floor() -> None:
    """Zeroing this repository's floors would restore the vacuous pass silently."""
    floors = policy_loader.gate_floors()
    assert floors["dedup_min_scripts"] > 0
    assert floors["py_compat_min_files"] > 0


def test_the_real_repository_clears_its_own_floors() -> None:
    """The floor is a ratchet: it must hold against the tree it governs, today."""
    floors = policy_loader.gate_floors()

    report = cd.run(cd.load_config(REPO))
    assert len(report.checked) >= floors["dedup_min_scripts"], (
        f"check_dedup checks {len(report.checked)} script(s), below the declared floor "
        f"of {floors['dedup_min_scripts']}; raise the population or review the floor"
    )

    discovered = sum(1 for _ in cc.iter_python_files(REPO, cc.load_skip_dirs(REPO)))
    assert discovered >= floors["py_compat_min_files"], (
        f"check_py_compat discovers {discovered} file(s), below the declared floor "
        f"of {floors['py_compat_min_files']}; raise the population or review the floor"
    )
