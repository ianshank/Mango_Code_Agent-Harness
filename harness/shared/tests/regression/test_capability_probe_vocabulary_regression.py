"""AQA-007: Host-inventory probe vocabulary is not BackendCapabilities (Arch-1).

``capability_probe`` reports whether a primitive *exists* on the host
(``enforced`` / ``absent`` / ``undetermined``). ``ProcessBackend.capability_probe``
and ``IsolationState`` report whether isolation was *applied*
(``enforced`` / ``unenforced`` / ``undetermined``).

``ProcessBackend._dimension`` treats ``host == "enforced"`` as applied isolation.
Passing host-probe-shaped JSON into ``ProcessBackend(capability_probe=...)``
would therefore report filesystem isolation as applied when only an LSM name
list existed.

This pin:
1. The two vocabularies share only ``enforced`` and ``undetermined``.
2. A host-shaped ``filesystem_isolation: enforced`` on the backend seam lies.
3. Real probe JSON (different field names) does not set isolation to enforced.
4. ``capability_probe.py`` is not on the spawn allowlist.

Spec: INV-13 AC-12 / AC-13, R-AEI-10, R-AEI-12.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import get_args

import pytest

# Ensure repository root is on sys.path so direct execution or IDE runners succeed
_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.shared.governance import capability_probe  # noqa: E402
from harness.shared.governance.execution_backend import IsolationState  # noqa: E402
from harness.shared.governance.process_backend import ProcessBackend  # noqa: E402

pytestmark = pytest.mark.governance

_BACKEND_TEST = _REPO / "harness" / "shared" / "tests" / "test_execution_backend.py"


def _assigned_frozenset_strings(path: Path, name: str) -> frozenset[str]:
    """String members of a module-level ``frozenset({...})`` assignment."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        call = node.value
        if not isinstance(call, ast.Call) or not call.args:
            continue
        arg = call.args[0]
        if not isinstance(arg, ast.Set):
            continue
        values = [elt.value for elt in arg.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        return frozenset(values)
    raise AssertionError(f"{name} frozenset assignment not found in {path}")


def test_host_inventory_json_must_not_be_passed_as_backend_capabilities() -> None:
    """Reproduction: mixing the two vocabularies reports isolation as applied."""
    probe_states = capability_probe.LEGAL_STATES
    isolation_states = set(get_args(IsolationState))
    assert probe_states & isolation_states == {"enforced", "undetermined"}
    assert "absent" in probe_states - isolation_states
    assert "unenforced" in isolation_states - probe_states

    lying = ProcessBackend(capability_probe={"filesystem_isolation": "enforced"})
    assert lying.capabilities().filesystem_isolation == "enforced"

    host = capability_probe.probe(platform="win32")
    for name in capability_probe._FIELDS:
        assert name not in {"filesystem_isolation", "network_isolation", "process_isolation"}
        assert host[name]["state"] == "absent"
    honest = ProcessBackend(capability_probe=host)
    assert honest.capabilities().filesystem_isolation == "unenforced"
    assert honest.capabilities().network_isolation == "unenforced"
    assert honest.capabilities().process_isolation == "unenforced"

    allowlist = _assigned_frozenset_strings(_BACKEND_TEST, "_SPAWN_ALLOWLIST")
    assert "capability_probe.py" not in allowlist
    assert "process_backend.py" in allowlist


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
