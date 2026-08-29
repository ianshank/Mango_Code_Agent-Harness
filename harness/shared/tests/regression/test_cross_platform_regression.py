"""Regressions for cross-platform defects discovered during E2E validation.

Defects reproduced here (all present on ``main`` before this change):

1. ``_reject_unsafe_relpath("/etc/passwd")`` silently passed on Windows because
   ``Path("/etc/passwd").is_absolute()`` returns ``False`` without a drive letter.
   A path traversal could exfiltrate sha256 digests of host files via the
   deny-reason message, making ``check`` a hash oracle for files outside the
   repo.  (**DEF-024**, Security)

2. ``git_modified_files`` used ``subprocess.check_output(text=True)``, which on
   Windows decodes via ``locale.getpreferredencoding()`` (typically cp1252).
   Git outputs UTF-8, so any non-ASCII filename (``café-ci.yml``) was decoded as
   two mojibake characters (``Ã©``).  The path then didn't match any
   fnmatch-anchored protected-path pattern, and the gate was silently bypassed.
   (**DEF-003**, Data Integrity / Security)

3. ``resolve_environment()`` in ``nemotron_bridge.py`` short-circuits before
   reading ``.env`` only when *every* mapped env var is populated in the process
   environment.  Tests that set only ``NEMOTRON_DEFAULT_MODEL`` and
   ``NEMOTRON_MAX_RETRIES=0`` still fell through to the ``.env`` file, which
   contained ``NEMOTRON_MAX_RETRIES=3``, causing the test to see 3 retries
   instead of 0.  (**DEF-014**, Test Isolation)

4. ``Path(rel).stat()`` on a path segment that traverses a *file* (not a
   directory) raises ``NotADirectoryError`` on POSIX but ``FileNotFoundError``
   on Windows.  Tests asserting only the former failed on Windows.
   (**DEF-027**, Cross-Platform Compatibility)

Spec: this change does not alter spec compliance — it *pins* existing compliance
across platforms.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import unicodedata
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─── Module loading for hyphenated control-plane directory ────────────────────

_PPA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "control-plane"
    / "publish_policy_artifact.py"
)


def _load_ppa():
    """Load the publish_policy_artifact module from the hyphenated control-plane
    directory via importlib (not importable as a regular package)."""
    spec = importlib.util.spec_from_file_location("publish_policy_artifact", _PPA_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ppa = _load_ppa()


# ─── DEF-024: Path safety guard POSIX-absolute bypass ────────────────────────


class TestPathSafetyGuardRejectsPosixAbsolutePaths:
    """A POSIX absolute path like ``/etc/passwd`` must be rejected regardless of
    the platform on which the guard runs.

    Before the fix, ``Path("/etc/passwd").is_absolute()`` returned ``False`` on
    Windows (no drive letter), and the ``..``-check also passed, so the path
    was silently accepted.
    """

    def test_posix_absolute_path_is_rejected(self) -> None:
        """``/etc/passwd`` is an absolute path on every platform; the guard must
        call ``_deny``, not silently resolve it relative to the repo root."""
        with pytest.raises(ppa.PolicyArtifactError, match="unsafe file path"):
            ppa._reject_unsafe_relpath("/etc/passwd")

    def test_posix_traversal_with_dot_dot_is_rejected(self) -> None:
        """Regression guard: the ``..`` check predates this defect and must stay
        operational so the two checks compose correctly."""
        with pytest.raises(ppa.PolicyArtifactError, match="unsafe file path"):
            ppa._reject_unsafe_relpath("../../etc/shadow")

    def test_windows_absolute_path_is_rejected(self) -> None:
        """``C:\\Windows\\system32\\config`` must also be caught by the guard,
        regardless of whether ``Path.is_absolute()`` sees the drive letter."""
        with pytest.raises(ppa.PolicyArtifactError, match="unsafe file path"):
            ppa._reject_unsafe_relpath("C:\\Windows\\system32\\config\\SAM")

    def test_clean_relative_path_is_accepted(self) -> None:
        """The guard must not reject well-formed relative paths, or it would
        break every legitimate artifact manifest."""
        # Should not raise — function returns None on success.
        result = ppa._reject_unsafe_relpath("harness/shared/governance-policy.json")
        assert result is None, "clean relative path should be silently accepted"


# ─── DEF-003: Git subprocess encoding corrupts non-ASCII paths ───────────────


class TestGitSubprocessEncodingPreservesUnicode:
    """``subprocess.check_output(..., text=True)`` uses the locale encoding
    (cp1252 on Windows), not UTF-8.  Git always outputs UTF-8, so non-ASCII
    filenames are corrupted.

    This regression pins the fix: ``encoding="utf-8"`` is now passed explicitly.
    """

    @pytest.fixture
    def unicode_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Create a temp git repo with a non-ASCII filename."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=repo, capture_output=True, check=True,
        )
        # Create a file with a non-ASCII name (NFC-composed é = U+00E9).
        target = repo / ".github" / "workflows"
        target.mkdir(parents=True)
        (target / "caf\u00e9-ci.yml").write_text("name: CI\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_BASE_REF", "")
        monkeypatch.delenv("ALLOW_GITHUB_CHANGES", raising=False)
        return repo

    def test_non_ascii_filename_survives_git_round_trip(self, unicode_repo: Path) -> None:
        """The filename ``café-ci.yml`` must come back from git with an intact
        ``é`` (U+00E9), not as ``Ã©`` (cp1252 mojibake of the UTF-8 bytes
        ``\\xc3\\xa9``)."""
        from harness.shared.validate_invariants import git_modified_files

        modified = git_modified_files(unicode_repo)
        # Normalize to NFC so NFD-returning platforms (macOS HFS+) also pass.
        normalized = {unicodedata.normalize("NFC", f) for f in modified}
        expected = unicodedata.normalize("NFC", "caf\u00e9-ci.yml")
        assert any(f.endswith(expected) for f in normalized), (
            f"Non-ASCII path corrupted by subprocess encoding: got {modified}"
        )


# ─── DEF-014: .env file leaks retry config into test environment ─────────────


class TestEnvFileDoesNotOverrideExplicitRetryConfig:
    """`resolve_environment()` reads `.env` when not every env var is set in the
    process environment.  A workspace `.env` containing ``NEMOTRON_MAX_RETRIES=3``
    overwrote a test's explicit ``NEMOTRON_MAX_RETRIES=0``, causing retry tests
    to observe 3 attempts instead of 0.

    The fix: supply *every* mapped env var in ``patch.dict`` so the short-circuit
    fires before `.env` is consulted.
    """

    def test_resolve_environment_short_circuits_when_all_keys_supplied(self) -> None:
        """When every env var in ``_ENV_VAR_KEYS`` is present, the function must
        return without touching the filesystem."""
        from harness.shared.nemotron_bridge import resolve_environment

        full_env = {
            "NVIDIA_API_KEY": "test-key",
            "NVIDIA_BASE_URL": "https://example.com/v1",
            "NEMOTRON_DEFAULT_MODEL": "dummy-model",
            "NEMOTRON_TIMEOUT_MS": "30000",
            "NEMOTRON_MAX_RETRIES": "0",
        }
        with patch.dict(os.environ, full_env, clear=False):
            result = resolve_environment()

        assert result["max_retries"] == "0", (
            "resolve_environment() returned a non-zero max_retries despite "
            "NEMOTRON_MAX_RETRIES=0 — the .env file likely overwrote it"
        )
        assert result["api_key"] == "test-key"

    def test_partial_env_still_reads_dotenv_for_missing_keys(self, tmp_path: Path) -> None:
        """Supplying only the API key and model should still read the `.env`
        file for the remaining keys — the short-circuit must not fire."""
        from harness.shared.nemotron_bridge import resolve_environment

        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEMOTRON_MAX_RETRIES=5\nNEMOTRON_TIMEOUT_MS=60000\n",
            encoding="utf-8",
        )
        partial_env = {
            "NVIDIA_API_KEY": "test-key",
            "NEMOTRON_DEFAULT_MODEL": "dummy-model",
        }
        # Patch Path(__file__) traversal to find our temp .env
        with patch.dict(os.environ, partial_env, clear=True):
            with patch("harness.shared.nemotron_bridge.Path") as mock_path_cls:
                mock_current = MagicMock()
                mock_current.resolve.return_value = mock_current
                mock_current.parent = tmp_path
                mock_path_cls.return_value = mock_current
                result = resolve_environment()

        assert result["max_retries"] == "5", (
            ".env was not consulted despite partial env — short-circuit fired too early"
        )


# ─── DEF-027: NotADirectoryError vs FileNotFoundError on Windows ─────────────


class TestPathThroughFileRaisesOSErrorOnAllPlatforms:
    """``stat()`` on a path that traverses a regular file (e.g.,
    ``/tmp/a-regular-file/child``) raises ``NotADirectoryError`` on POSIX but
    ``FileNotFoundError`` on Windows.

    Both are ``OSError`` subclasses.  Code that catches only
    ``NotADirectoryError`` silently mishandles the Windows case.
    """

    def test_stat_through_file_raises_oserror(self, tmp_path: Path) -> None:
        """The specific subclass varies, but it is always an ``OSError``."""
        blocker = tmp_path / "a-regular-file"
        blocker.write_text("not a directory", encoding="utf-8")
        child = blocker / "unreachable.json"

        with pytest.raises(OSError):
            child.stat()

    def test_both_platform_exceptions_are_oserror_subclasses(self) -> None:
        """Pin the relationship so a future refactor that catches ``OSError``
        as a base can rely on this."""
        assert issubclass(NotADirectoryError, OSError)
        assert issubclass(FileNotFoundError, OSError)

    def test_is_file_returns_false_for_path_through_file(self, tmp_path: Path) -> None:
        """``Path.is_file()`` absorbs the ``OSError`` and returns ``False`` on
        both platforms — which is the problem the ``stat()``-based guard was
        built to avoid."""
        blocker = tmp_path / "a-regular-file"
        blocker.write_text("not a directory", encoding="utf-8")
        child = blocker / "unreachable.json"

        # This is the *defect*: is_file() makes unreachable look identical to absent.
        assert child.is_file() is False
        assert child.exists() is False


# ─── EC-002: UNC path bypass in _reject_unsafe_relpath ───────────────────────

class TestUNCPathIsRejectedByArtifactGuard:
    """Windows UNC paths (``\\\\server\\share``) bypass ``Path.is_absolute()`` on
    Linux because they lack a drive letter. The guard must check for a backslash
    prefix explicitly."""

    def test_unc_path_is_rejected(self) -> None:
        with pytest.raises(ppa.PolicyArtifactError, match="unsafe file path"):
            ppa._reject_unsafe_relpath("\\\\server\\share\\payload.json")

    def test_forward_slash_unc_variant_is_rejected(self) -> None:
        """Some tools normalise UNC paths with forward slashes."""
        with pytest.raises(ppa.PolicyArtifactError, match="unsafe file path"):
            ppa._reject_unsafe_relpath("//server/share/payload.json")


# ─── EC-003: mask_secret empty-key guard ─────────────────────────────────────

class TestMaskSecretEdgeCases:
    """``mask_secret("")`` returns ``<UNSET>`` — but if it is used with
    ``str.replace("", ...)`` the result is garbled (insertion between every
    character). The bridge must not call ``.replace(key, ...)`` when key is
    empty."""

    def test_mask_secret_empty_returns_unset(self) -> None:
        from harness.shared.nemotron_bridge import mask_secret
        assert mask_secret("") == "<UNSET>"

    def test_mask_secret_short_key_returns_stars(self) -> None:
        from harness.shared.nemotron_bridge import mask_secret
        assert mask_secret("abc123") == "****"

    def test_mask_secret_long_key_shows_prefix_suffix(self) -> None:
        from harness.shared.nemotron_bridge import mask_secret
        key = "nvapi-abcdefghijklmnop"
        masked = mask_secret(key)
        assert masked.startswith("nvapi-abcd")
        assert masked.endswith("mnop")
        assert "..." in masked

    def test_mask_secret_whitespace_only(self) -> None:
        from harness.shared.nemotron_bridge import mask_secret
        # strip() produces "", len("") <= 10 → returns "****"
        assert mask_secret("   ") == "****"


# ─── EC-004: .env parser quoted-value stripping ──────────────────────────────

class TestEnvFileQuotedValueStripping:
    """``.env`` files commonly use ``KEY="value"`` or ``KEY='value'`` format.
    The parser must strip matching surrounding quotes from values."""

    def test_double_quoted_value_is_unquoted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text('NVIDIA_API_KEY="nvapi-test-key-double"\n', encoding="utf-8")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.delenv("NEMOTRON_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("NEMOTRON_TIMEOUT_MS", raising=False)
        monkeypatch.delenv("NEMOTRON_MAX_RETRIES", raising=False)

        import harness.shared.nemotron_bridge as nb
        # Patch __file__ resolution to use tmp_path
        with unittest.mock.patch.object(
            Path, "resolve", return_value=tmp_path / "nemotron_bridge.py"
        ):
            result = nb.resolve_environment()
        assert result["api_key"] == "nvapi-test-key-double", \
            f"Expected unquoted value, got {result['api_key']!r}"

    def test_single_quoted_value_is_unquoted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NVIDIA_API_KEY='nvapi-test-key-single'\n", encoding="utf-8")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.delenv("NEMOTRON_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("NEMOTRON_TIMEOUT_MS", raising=False)
        monkeypatch.delenv("NEMOTRON_MAX_RETRIES", raising=False)

        import harness.shared.nemotron_bridge as nb
        with unittest.mock.patch.object(
            Path, "resolve", return_value=tmp_path / "nemotron_bridge.py"
        ):
            result = nb.resolve_environment()
        assert result["api_key"] == "nvapi-test-key-single"

    def test_unquoted_value_is_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NVIDIA_API_KEY=nvapi-plain\n", encoding="utf-8")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.delenv("NEMOTRON_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("NEMOTRON_TIMEOUT_MS", raising=False)
        monkeypatch.delenv("NEMOTRON_MAX_RETRIES", raising=False)

        import harness.shared.nemotron_bridge as nb
        with unittest.mock.patch.object(
            Path, "resolve", return_value=tmp_path / "nemotron_bridge.py"
        ):
            result = nb.resolve_environment()
        assert result["api_key"] == "nvapi-plain"

    def test_mismatched_quotes_are_preserved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If quotes don't match (e.g., ``"val'``), they must not be stripped."""
        env_file = tmp_path / ".env"
        env_file.write_text("NVIDIA_API_KEY=\"nvapi-mismatched'\n", encoding="utf-8")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.delenv("NEMOTRON_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("NEMOTRON_TIMEOUT_MS", raising=False)
        monkeypatch.delenv("NEMOTRON_MAX_RETRIES", raising=False)

        import harness.shared.nemotron_bridge as nb
        with unittest.mock.patch.object(
            Path, "resolve", return_value=tmp_path / "nemotron_bridge.py"
        ):
            result = nb.resolve_environment()
        # Mismatched quotes should be preserved (not stripped)
        assert result["api_key"] == "\"nvapi-mismatched'"


# ─── EC-007: validate_specs.py unit tests (0% → >80%) ────────────────────────

class TestValidateSpecsPythonNative:
    """``validate_specs.py`` was at 0% coverage because the only tests called
    ``bash validate_specs.sh``. These tests exercise the Python-native module
    directly, with no bash dependency."""

    def test_valid_spec_passes(self) -> None:
        from harness.shared.validate_specs import validate_spec
        content = (
            "# My Spec\n"
            "## Requirements\n"
            "- R-001: The system MUST do something.\n"
            "## Acceptance criteria\n"
            "- [ ] AC-1: Passes verification.\n"
        )
        assert validate_spec(content, "good-spec.md") is True

    def test_missing_requirements_header_fails(self) -> None:
        from harness.shared.validate_specs import validate_spec
        content = "# My Spec\n## Acceptance criteria\n- [ ] AC-1: Passes.\n"
        assert validate_spec(content, "bad-spec.md") is False

    def test_missing_acceptance_criteria_header_fails(self) -> None:
        from harness.shared.validate_specs import validate_spec
        content = "# My Spec\n## Requirements\n- R-001: The system MUST do something.\n"
        assert validate_spec(content, "bad-spec.md") is False

    def test_normative_must_without_req_id_fails(self) -> None:
        from harness.shared.validate_specs import validate_spec
        content = (
            "# My Spec\n"
            "## Requirements\n"
            "- The system MUST do something.\n"
            "## Acceptance criteria\n"
            "- [ ] AC-1: Passes.\n"
        )
        assert validate_spec(content, "bad-spec.md") is False

    def test_unfalsifiable_language_fails(self) -> None:
        from harness.shared.validate_specs import validate_spec
        content = (
            "# My Spec\n"
            "## Requirements\n"
            "- R-1: The system MUST run.\n"
            "## Acceptance criteria\n"
            "- It works correctly.\n"
        )
        assert validate_spec(content, "bad-spec.md") is False

    def test_main_returns_zero_on_valid_dir(self, tmp_path: Path) -> None:
        from harness.shared.validate_specs import main
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec_file = specs_dir / "test-spec.md"
        spec_file.write_text(
            "# Test\n## Requirements\n- R-1: The system MUST work.\n## Acceptance criteria\n- [ ] AC-1: Tested.\n",
            encoding="utf-8",
        )
        assert main(specs_dir) == 0

    def test_main_returns_one_on_invalid_spec(self, tmp_path: Path) -> None:
        from harness.shared.validate_specs import main
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        spec_file = specs_dir / "bad-spec.md"
        spec_file.write_text("# No required headers\n", encoding="utf-8")
        assert main(specs_dir) == 1

    def test_main_returns_zero_on_empty_dir(self, tmp_path: Path) -> None:
        from harness.shared.validate_specs import main
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        assert main(specs_dir) == 0

    def test_main_returns_zero_on_missing_dir(self, tmp_path: Path) -> None:
        """A missing specs directory is treated as 'no specs to validate' → pass."""
        from harness.shared.validate_specs import main
        missing = tmp_path / "nonexistent"
        assert main(missing) == 0


# ─── EC-008: nemotron_bridge error paths ─────────────────────────────────────

class TestNemotronBridgeErrorPaths:
    """Cover missed lines in nemotron_bridge.py: _int_from_env ValueError,
    missing model error, and tools/tool_choice payload construction."""

    def test_int_from_env_garbage_returns_default(self) -> None:
        from harness.shared.nemotron_bridge import _int_from_env
        result = _int_from_env("not_a_number", 42, "TEST_VAR")
        assert result == 42

    def test_int_from_env_empty_returns_default(self) -> None:
        from harness.shared.nemotron_bridge import _int_from_env
        assert _int_from_env("", 99, "TEST_VAR") == 99

    def test_int_from_env_valid_int(self) -> None:
        from harness.shared.nemotron_bridge import _int_from_env
        assert _int_from_env("7", 0, "TEST_VAR") == 7

    def test_complete_chat_missing_model_raises(self) -> None:
        import harness.shared.nemotron_bridge as nb
        # Clear NEMOTRON_DEFAULT_MODEL and patch resolve_environment to prevent
        # .env file discovery from supplying a model.
        fake_env = {
            "api_key": "nvapi-test-key-long-enough",
            "base_url": "https://test.example.com",
            "default_model": "",
            "timeout_ms": "5000",
            "max_retries": "0",
        }
        with unittest.mock.patch.object(nb, "resolve_environment", return_value=fake_env):
            with pytest.raises(ValueError, match="Target model is not configured"):
                nb.complete_chat([{"role": "user", "content": "hi"}])

    def test_complete_chat_invalid_url_scheme_raises(self) -> None:
        import harness.shared.nemotron_bridge as nb
        with unittest.mock.patch.dict(os.environ, {
            "NVIDIA_API_KEY": "nvapi-test",
            "NVIDIA_BASE_URL": "ftp://bad.example.com",
            "NEMOTRON_DEFAULT_MODEL": "test-model",
            "NEMOTRON_TIMEOUT_MS": "5000",
            "NEMOTRON_MAX_RETRIES": "0",
        }):
            with pytest.raises(ValueError, match="Invalid URL scheme"):
                nb.complete_chat([{"role": "user", "content": "hi"}])
