"""Coverage-gate import probe must not treat its own directory as the extra.

Defect reproduced here (present on ``main`` before the fix, DEC-032):

``python harness/shared/coverage_gate.py`` puts ``harness/shared/`` first on
``sys.path``. That directory already contains ``harness/shared/langgraph/``,
which shadowed the real optional package, so the probe reported the extra as
"importable" on a CI leg that had nothing installed. The 3.9 matrix leg then
ran the wrong coverage scope.

Confirmed by pointing the module that defines ``_importable`` at a temporary
directory that holds a same-named package: the probe must ignore that
directory (and only that directory), leave no imports behind, and still see
real stdlib modules.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from harness.shared import coverage_gate as cg
from harness.shared import coverage_scope as cs

pytestmark = pytest.mark.governance


def test_the_gates_own_directory_cannot_shadow_the_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduced: a same-named package beside the gate looked importable."""
    shadow = tmp_path / "gate_dir" / "shadowextra"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "graph.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "gate_dir"))
    importlib.invalidate_caches()
    assert cg._importable("shadowextra.graph") is True, (
        "sanity: visible when it is just another path entry"
    )

    # Patched on the module that *defines* `_importable`, which is where the
    # `__file__` it reads lives. That is `coverage_scope` since the scope concern
    # was split out; patching `cg.__file__` after the split left this regression
    # asserting nothing, because the function never reads it. Production
    # behaviour is unchanged either way -- both modules sit in harness/shared/,
    # so "the script's own directory" resolves to the same path (DEC-032).
    monkeypatch.setattr(cs, "__file__", str(tmp_path / "gate_dir" / "coverage_scope.py"))
    assert cg._importable("shadowextra.graph") is False
    assert "shadowextra" not in sys.modules, "the probe must not leave its imports behind"
    assert cg._importable("json.decoder") is True, (
        "removing the own directory must not hide real modules"
    )
