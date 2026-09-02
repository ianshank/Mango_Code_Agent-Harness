"""Shared fixtures for harness/shared test suites.

Provides:
- ``api_key``: Resolves NVIDIA_API_KEY from env or .env files.
- ``project_root``: Absolute path to the harness project root.
- ``shared_dir``: Absolute path to harness/shared.
- ``tmp_git_repo``: Ephemeral Git repository for isolated testing.
- ``write_text_file``: Writes a fixture file, creating parent dirs.
- ``governance_workspace``: Temp dir with a minimal .governance/ skeleton.
- ``mock_make_available``: Patches ``shutil.which("make")`` for cross-platform tests.
- ``mock_subprocess_success``: Patches ``subprocess.run`` to return exit-0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.shared.nemotron_bridge import resolve_api_key

# The langgraph deselection and the skip-evidence hooks moved to the
# repository-root conftest.py (logic in _session_hooks.py): a hook registered
# here only sees items under harness/shared/tests, and the zero-skip gate has
# to see every suite (R-TDH-26). The two names stay importable from here for
# the tests that pin the wiring.
from harness.shared.tests._session_hooks import LANGGRAPH_DESELECT_ENV, LANGGRAPH_MARKER  # noqa: F401

# Reusable skip marker for tests that require POSIX features (bash, chmod, symlinks).
# These tests pass on CI (ubuntu-latest) but cannot pass on Windows.
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only: requires bash/chmod/symlinks not available on Windows (DEC-026)"
)


def write_text_file(path: Path, text: str) -> Path:
    """Write ``text`` to ``path``, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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


@pytest.fixture
def mock_workspace(tmp_path: Path) -> Path:
    """A temp workspace pre-populated with the agents the MAS loop expects."""
    agents = tmp_path / ".mango" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name in ("planner", "nemotron-reasoner", "verifier"):
        (agents / f"{name}.md").write_text(f"# {name}\nYou are the {name} agent.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mock_complete_chat(mocker):
    """Patch the Nemotron bridge inside the orchestrator; return the mock."""
    from harness.shared import mango_mas_orchestrator as orch_module
    return mocker.patch.object(orch_module, "complete_chat")


@pytest.fixture
def governance_workspace(tmp_path: Path) -> Path:
    """Return a temp directory pre-populated with a minimal ``.governance/`` skeleton.

    Contains:
    - ``.governance/policy.json`` — minimal governance-policy with all required keys
    - ``.governance/agent-policy.json`` — minimal agent-policy with all required roles
    - ``.governance/decision-log.md`` — empty log

    Use this fixture wherever tests construct throwaway governance trees to avoid
    copy-pasting the scaffold logic across test modules.
    """
    gov = tmp_path / ".governance"
    gov.mkdir(parents=True, exist_ok=True)

    gov_policy = {
        "target_contract": ["install", "lint", "test", "cov"],
        "pre_pr_order": ["lint", "cov"],
        "ci_required_targets": [
            "cov", "lint", "types", "secrets", "specs",
            "audit", "remotes", "projections", "traceability", "governance",
        ],
        "decision_id_pattern": "^(DEC-[0-9]+)$",
        "agent_defaults": {"deny_unclassified_side_effects": True},
        "protected_paths": [
            ".governance/**", ".github/workflows/**",
            "Makefile", "scripts/remotes.py", "scripts/verify_zero_skips.py",
        ],
        "charter_version": "2.0",
        "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
        "skill_max_age_days": 90,
        "external_root_of_trust_required": True,
    }
    (gov / "policy.json").write_text(json.dumps(gov_policy), encoding="utf-8")

    (gov / "decision-log.md").write_text("# Decision Log\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mock_make_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``shutil.which`` so that a ``"make"`` probe returns a dummy path.

    Prevents ``VerificationRunner`` and similar probes from failing on Windows
    (where GNU Make is typically absent) in tests that are not about Make
    availability itself.
    """
    import shutil

    original_which = shutil.which

    def _which_stub(cmd: str, mode: int = os.F_OK | os.X_OK, path: str | None = None) -> str | None:
        if cmd == "make":
            return "/usr/bin/make"
        return original_which(cmd, mode=mode, path=path)

    monkeypatch.setattr(shutil, "which", _which_stub)


@pytest.fixture
def mock_subprocess_success(monkeypatch: pytest.MonkeyPatch) -> Generator[MagicMock, None, None]:
    """Patch ``subprocess.run`` to return a zero-exit ``CompletedProcess``.

    Use in tests where external process invocation is a side-effect, not the
    system under test. Yields the mock so callers can inspect ``call_args``.
    """
    import subprocess as sp

    mock = MagicMock()
    mock.return_value = sp.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    with patch.object(sp, "run", mock):
        yield mock
