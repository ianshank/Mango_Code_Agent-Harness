"""Every control-plane script has a colocated test module, and the runners collect it.

tech-debt-hardening-plan R-TDH-26 / AC-26. The control-plane scripts were tested
from harness/shared/tests, where a reader of harness/control-plane/ could not see
that a script had tests at all, and where a new script could land untested with
every gate green. This meta-test closes both directions: each script maps to a
`test_<script>.py` here that names it, each test module here maps to a script
(or is this file), and the pytest and coverage configuration collect the
directory. The Make recipes are pinned by harness/shared/tests/
test_makefile_contracts.py, which already owns recipe assertions.
"""

from __future__ import annotations

import re

import pytest

from harness.shared.tests._helpers import CONTROL_PLANE, REPO

pytestmark = pytest.mark.governance

TESTS_DIR = CONTROL_PLANE / "tests"
TESTS_RELPATH = TESTS_DIR.relative_to(REPO).as_posix()
PYPROJECT = REPO / "pyproject.toml"
LAYOUT_MODULE = "test_control_plane_layout.py"


def _scripts() -> list[str]:
    stems = sorted(p.stem for p in CONTROL_PLANE.glob("*.py"))
    assert stems, "no control-plane scripts found; this meta-test would be vacuous"
    return stems


def _test_modules() -> list[str]:
    names = sorted(p.name for p in TESTS_DIR.glob("test_*.py"))
    assert names, "no colocated test modules found; this meta-test would be vacuous"
    return names


def test_each_script_has_a_colocated_test_module_that_names_it() -> None:
    # A loop, not a parametrize over a glob: an empty glob would register as a skip.
    for stem in _scripts():
        module = TESTS_DIR / f"test_{stem}.py"
        assert module.is_file(), f"harness/control-plane/{stem}.py has no {module.relative_to(REPO)}"
        assert f"{stem}.py" in module.read_text(encoding="utf-8"), (
            f"{module.name} does not reference {stem}.py; a module that never loads its script tests nothing"
        )


def test_each_test_module_maps_to_a_script() -> None:
    scripts = set(_scripts())
    for name in _test_modules():
        if name == LAYOUT_MODULE:
            continue
        stem = re.sub(r"^test_", "", name[: -len(".py")])
        assert stem in scripts, (
            f"{name} maps to no control-plane script; name it test_<script>.py or move it to harness/shared/tests"
        )


def test_pyproject_collects_and_omits_this_directory() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    testpaths = re.search(r"^testpaths\s*=\s*\[(.*?)\]", text, re.M | re.S)
    assert testpaths, "pyproject declares no testpaths"
    assert TESTS_RELPATH in re.findall(r'"([^"]+)"', testpaths.group(1)), (
        f"{TESTS_RELPATH} is not in pytest testpaths; a bare `pytest` would not collect it"
    )
    run_table = re.search(r"^\[tool\.coverage\.run\]\s*$(.*?)(?=^\[)", text, re.M | re.S)
    assert run_table, "pyproject declares no [tool.coverage.run] table"
    omit = re.search(r"^omit\s*=\s*\[(.*?)\]", run_table.group(1), re.M | re.S)
    assert omit and f"{TESTS_RELPATH}/*" in re.findall(r'"([^"]+)"', omit.group(1)), (
        f"{TESTS_RELPATH}/* is not omitted from coverage; test modules would count as measured source"
    )
