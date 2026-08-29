"""Shared fixtures for harness/shared test suites.

Provides:
- ``api_key``: Resolves NVIDIA_API_KEY from env or .env files.
- ``project_root``: Absolute path to the harness project root.
- ``shared_dir``: Absolute path to harness/shared.
- ``tmp_git_repo``: Ephemeral Git repository for isolated testing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.nemotron_bridge import resolve_api_key

# Reusable skip marker for tests that require POSIX features (bash, chmod, symlinks).
# These tests pass on CI (ubuntu-latest) but cannot pass on Windows.
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only: requires bash/chmod/symlinks not available on Windows"
)


# --- Fixtures ---
@pytest.fixture(autouse=True)
def _scrub_shadow_planner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: an ambient MANGO_SHADOW_PLANNER=1 in a dev
    shell or CI runner must not flip mocked orchestrator tests into making
    real bridge calls. Tests that exercise the flag set it explicitly."""
    for var in ("MANGO_SHADOW_PLANNER", "MANGO_SHADOW_MODEL", "MANGO_SHADOW_TIMEOUT_SEC", "MANGO_SIGNAL_DIR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def api_key() -> str:
    """Delegates to nemotron_bridge.resolve_api_key() — single source of truth."""
    return resolve_api_key()


@pytest.fixture
def project_root() -> Path:
    """Resolves the harness project root directory."""
    return Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture
def shared_dir() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Creates a temporary Git repository for isolated testing."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], capture_output=True, check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True, check=True)
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True, check=True)
    return tmp_path
