"""Every shared and control-plane module must import without acting.

The rule this file establishes did not exist before, and its absence is
visible in the history: an earlier PR in this programme made two control-plane
CLIs importable by hand, and a third -- ``validate_adoption.py`` -- survived
untouched, still reading files, printing, and raising ``SystemExit`` at import.
Fixing instances does not prevent the next one; a rule does.

Why it matters concretely:

* ``SystemExit`` is a ``BaseException``. A shim that guards its delegation with
  ``except ImportError`` cannot catch one raised during ``import``, so the
  failure escapes as an opaque exit rather than the shim's own diagnostic.
* Printing at import corrupts the stdout of every gate that imports the module
  -- and several gates' stdout is a machine-read CLI contract pinned by
  ``test_gate_logging.py``.
* Reading CWD-relative paths at import makes a module's behaviour depend on
  where the interpreter happened to start, which is why the scan below runs
  each import from a *poisoned* working directory rather than the repo root.

Marked ``slow``: it spawns one subprocess per module. That is the point -- an
in-process import would be masked by whatever the test session already loaded.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.tests._helpers import CONTROL_PLANE, REPO, SHARED

pytestmark = pytest.mark.slow

# Modules that still act at import, each with the reason it is not fixed here.
#
# Empty, and meant to stay that way. The three entries this registry was born
# with (``tool_broker_reference.py``, ``verify_repository.py`` and
# ``check_projections.py``) were waived only because the policy-single-source
# change that fixes them was open and unmerged; once it landed,
# ``test_every_waiver_is_still_necessary`` failed on all three and the entries
# came out. That is the whole design: a waiver that cannot outlive its defect.
#
# Adding an entry here removes a module from the purity gate, so an entry earns
# its place only by naming the specific defect and why it is not being fixed in
# the same change -- not "later".
KNOWN_IMPORT_SIDE_EFFECTS: dict[str, str] = {}

# Two probes, because the two roots are importable in different ways.
#
# ``harness/shared`` is a real package, so its modules are imported by dotted
# name -- which is how production imports them, and the only way relative
# imports such as ``from .pretooluse_guard import ...`` resolve. Loading those
# by path would fail on the probe's own missing package context and report a
# defect that is not there.
#
# ``harness/control-plane`` has a hyphen and therefore is not a legal package
# name; its tools can only ever be loaded by path, which is also how the
# repository's own tests load them.
_DOTTED_PROBE = "import importlib, sys; importlib.import_module(sys.argv[1])\n"
_PATH_PROBE = (
    "import importlib.util as u, sys\n"
    "spec = u.spec_from_file_location('import_purity_probe', sys.argv[1])\n"
    "module = u.module_from_spec(spec)\n"
    "sys.modules['import_purity_probe'] = module\n"
    "spec.loader.exec_module(module)\n"
)


def _probe_for(path: Path) -> tuple[str, str]:
    """Return (probe source, argument) appropriate to how ``path`` is imported."""
    if SHARED in path.parents or path.parent == SHARED:
        relative = path.relative_to(REPO).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        return _DOTTED_PROBE, ".".join(parts)
    return _PATH_PROBE, str(path)


def _modules() -> list[Path]:
    found = [
        path
        for root in (SHARED, CONTROL_PLANE)
        for path in root.rglob("*.py")
        if "tests" not in path.parts and "__pycache__" not in path.parts
    ]
    return sorted(found)


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _import_in_subprocess(path: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Import ``path`` from a clean interpreter rooted at ``cwd``.

    A subprocess, not ``importlib.reload``: by the time this suite runs, most
    of these modules are already in ``sys.modules``, and a reload re-executes
    module scope with the package context already established -- which is
    exactly the state that hides a CWD-relative read.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO) + (os.pathsep + existing if existing else "")
    # A module must not depend on the debug-dump or shadow flags at import.
    for flag in ("MANGO_DEBUG_DUMP", "MANGO_SHADOW_PLANNER"):
        env.pop(flag, None)
    probe, argument = _probe_for(path)
    return subprocess.run(
        [sys.executable, "-c", probe, argument],
        cwd=str(cwd), capture_output=True, text=True, timeout=120, env=env,
    )


@pytest.fixture
def poisoned_cwd(tmp_path: Path) -> Path:
    """An empty directory that is not the repo root.

    Running the import from here turns a CWD-relative read at module scope
    into a failure instead of a silent success, which is what made
    ``validate_adoption.py``'s behaviour depend on where it was started.
    """
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    return workdir


class TestImportPurity:
    def test_the_scan_finds_the_modules(self) -> None:
        """Guards the scan: a glob that stopped matching would make every
        check below pass while examining nothing."""
        assert len(_modules()) > 25

    @pytest.mark.parametrize("module", _modules(), ids=_rel)
    def test_module_imports_cleanly(self, module: Path, poisoned_cwd: Path) -> None:
        if _rel(module) in KNOWN_IMPORT_SIDE_EFFECTS:
            pytest.skip(f"declared: {KNOWN_IMPORT_SIDE_EFFECTS[_rel(module)]}")
        result = _import_in_subprocess(module, poisoned_cwd)
        assert result.returncode == 0, (
            f"{_rel(module)} failed to import from a directory that is not the repo root "
            f"(exit {result.returncode}). Module scope must not read CWD-relative paths, "
            f"parse arguments, or exit.\n{result.stderr}"
        )

    @pytest.mark.parametrize("module", _modules(), ids=_rel)
    def test_module_prints_nothing_on_import(self, module: Path, poisoned_cwd: Path) -> None:
        if _rel(module) in KNOWN_IMPORT_SIDE_EFFECTS:
            pytest.skip(f"declared: {KNOWN_IMPORT_SIDE_EFFECTS[_rel(module)]}")
        result = _import_in_subprocess(module, poisoned_cwd)
        assert result.stdout == "", (
            f"{_rel(module)} printed to stdout at import: {result.stdout!r}. Several gates' "
            "stdout is a machine-read contract; a module that prints at import corrupts it."
        )

    @pytest.mark.parametrize("module", _modules(), ids=_rel)
    def test_module_writes_nothing_on_import(self, module: Path, poisoned_cwd: Path) -> None:
        if _rel(module) in KNOWN_IMPORT_SIDE_EFFECTS:
            pytest.skip(f"declared: {KNOWN_IMPORT_SIDE_EFFECTS[_rel(module)]}")
        _import_in_subprocess(module, poisoned_cwd)
        created = [p.name for p in poisoned_cwd.iterdir() if p.name != "__pycache__"]
        assert not created, f"{_rel(module)} created {created} at import"


class TestWaiversStayHonest:
    def test_every_waiver_names_a_real_module(self) -> None:
        known = {_rel(path) for path in _modules()}
        assert not set(KNOWN_IMPORT_SIDE_EFFECTS) - known, (
            "a waiver names a module that no longer exists; delete it, or it will "
            "silently exempt a future file with the same path"
        )

    @pytest.mark.parametrize("waived", sorted(KNOWN_IMPORT_SIDE_EFFECTS))
    def test_every_waiver_is_still_necessary(self, waived: str, poisoned_cwd: Path) -> None:
        """The waiver self-destructs. Once the module imports cleanly, this
        fails and the entry must be deleted -- so a declaration cannot outlive
        the defect it describes and go on exempting a regression."""
        result = _import_in_subprocess(REPO / waived, poisoned_cwd)
        assert result.returncode != 0 or result.stdout != "", (
            f"{waived} now imports cleanly. Remove its KNOWN_IMPORT_SIDE_EFFECTS entry "
            "so the module is covered by the gate again."
        )

    @pytest.mark.parametrize("waived", sorted(KNOWN_IMPORT_SIDE_EFFECTS))
    def test_every_waiver_has_a_substantive_reason(self, waived: str) -> None:
        assert len(KNOWN_IMPORT_SIDE_EFFECTS[waived].strip()) > 80
