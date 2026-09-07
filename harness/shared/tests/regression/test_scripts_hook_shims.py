"""AQA-001: Regression pin for scripts/ hook shims introduced in HOOK-1 fix.

Verifies:
- scripts/verify-tier-a.sh exists
- scripts/guard-forbidden-paths.sh exists
- Neither file contains any hard-coded paths (Windows drive letters, home dirs, CI env paths)
- Both files reference the Makefile / validate_invariants.py dynamically
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
VERIFY_SHIM = SCRIPTS_DIR / "verify-tier-a.sh"
GUARD_SHIM = SCRIPTS_DIR / "guard-forbidden-paths.sh"

# Hard-coded path patterns that are forbidden in the shims
_HARDCODED_PATTERNS = [
    re.compile(r"[A-Za-z]:\\"),  # Windows absolute: C:\...
    re.compile(r"/home/[^${}]"),  # bare /home/username
    re.compile(r"/Users/[^${}]"),  # bare /Users/username
    re.compile(r"/root/[^${}]"),  # bare /root/...
    re.compile(r"E:\\\\Coding_Projects"),  # literal project path
    re.compile(r"harness_TEST", re.IGNORECASE),  # literal repo name
]


@pytest.mark.parametrize("shim", [VERIFY_SHIM, GUARD_SHIM])
def test_hook_shim_exists(shim: Path) -> None:
    """Both hook shims must exist on disk (HOOK-1 defect fix)."""
    assert shim.exists(), (
        f"Hook shim {shim.name} not found at {shim}. "
        "The .mango/agents/hooks.json references scripts/ shims that must exist."
    )
    assert shim.is_file(), f"{shim} exists but is not a regular file"


@pytest.mark.parametrize("shim", [VERIFY_SHIM, GUARD_SHIM])
def test_hook_shim_has_bash_shebang(shim: Path) -> None:
    """Shims must have a valid bash shebang — bare sh is not reliable cross-distro."""
    if not shim.exists():
        pytest.skip(f"{shim.name} does not exist (HOOK-1 not yet fixed)")
    first_line = shim.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!/"), f"{shim.name}: first line must be a shebang, got {first_line!r}"
    assert "bash" in first_line or "env" in first_line, (
        f"{shim.name}: shebang should invoke bash via /usr/bin/env or direct path, got {first_line!r}"
    )


@pytest.mark.parametrize("shim", [VERIFY_SHIM, GUARD_SHIM])
def test_hook_shim_has_no_hardcoded_paths(shim: Path) -> None:
    """Shims must not contain any hard-coded absolute paths (DRY / portability)."""
    if not shim.exists():
        pytest.skip(f"{shim.name} does not exist (HOOK-1 not yet fixed)")
    content = shim.read_text(encoding="utf-8")
    for pattern in _HARDCODED_PATTERNS:
        match = pattern.search(content)
        assert match is None, (
            f"{shim.name} contains a hard-coded path matching {pattern.pattern!r}: "
            f"...{content[max(0, match.start() - 20) : match.end() + 20]}..."
        )


def test_verify_tier_a_delegates_to_makefile() -> None:
    """verify-tier-a.sh must invoke `make` (delegates to Makefile, not ad-hoc commands)."""
    if not VERIFY_SHIM.exists():
        pytest.skip("verify-tier-a.sh does not exist (HOOK-1 not yet fixed)")
    content = VERIFY_SHIM.read_text(encoding="utf-8")
    assert "make" in content, (
        "verify-tier-a.sh must delegate to the Makefile (contains `make`). "
        "Hard-coding specific tool invocations would duplicate the CI definition."
    )


def test_guard_shim_uses_validate_invariants() -> None:
    """guard-forbidden-paths.sh must reference validate_invariants (uses canonical API)."""
    if not GUARD_SHIM.exists():
        pytest.skip("guard-forbidden-paths.sh does not exist (HOOK-1 not yet fixed)")
    content = GUARD_SHIM.read_text(encoding="utf-8")
    assert "validate_invariants" in content, (
        "guard-forbidden-paths.sh must use validate_invariants for protected-path checking. "
        "Duplicating the protected-path logic would create drift."
    )
    assert "is_protected" in content, "guard-forbidden-paths.sh must call is_protected() from validate_invariants."


def test_guard_shim_uses_dynamic_repo_root() -> None:
    """guard-forbidden-paths.sh must resolve REPO_ROOT dynamically, not hardcoded."""
    if not GUARD_SHIM.exists():
        pytest.skip("guard-forbidden-paths.sh does not exist (HOOK-1 not yet fixed)")
    content = GUARD_SHIM.read_text(encoding="utf-8")
    assert "git rev-parse --show-toplevel" in content or "REPO_ROOT" in content, (
        "guard-forbidden-paths.sh must resolve the repo root dynamically via `git rev-parse`."
    )
