"""Regression tests for Windows-portability fixes (RCA-1 through RCA-11).

Anti-pattern guards:
- fnmatch.fnmatch (case-insensitive) is BANNED from production governance code.
- No hardcoded platform literals in production modules (only test-side guards).
"""

from __future__ import annotations

import re
import sys

import pytest

from harness.shared.tests._helpers import REPO
from harness.shared.validate_invariants import is_protected

pytestmark = pytest.mark.governance

_VALIDATE_SRC = (REPO / "harness" / "shared" / "validate_invariants.py").read_text(encoding="utf-8")
_DIGEST_SRC = (REPO / "harness" / "shared" / "governance" / "enforcement_digest.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Anti-pattern guards
# ---------------------------------------------------------------------------


class TestAntiPatternFnmatchBanned:
    """fnmatch.fnmatch (case-insensitive) must not appear in production governance code."""

    def test_fnmatch_call_not_in_validate_invariants(self) -> None:
        calls = re.findall(r"\bfnmatch\.fnmatch\s*\(", _VALIDATE_SRC)
        assert not calls, (
            f"validate_invariants.py calls fnmatch.fnmatch (case-insensitive): {calls}. "
            "Use fnmatch.fnmatchcase to preserve case-sensitive behaviour on all platforms."
        )

    def test_fnmatchcase_present_in_validate_invariants(self) -> None:
        assert "fnmatchcase" in _VALIDATE_SRC, (
            "validate_invariants.py no longer calls fnmatchcase -- RCA-2 fix was lost."
        )

    def test_fnmatch_call_not_in_enforcement_digest(self) -> None:
        calls = re.findall(r"\bfnmatch\.fnmatch\s*\(", _DIGEST_SRC)
        assert not calls, f"enforcement_digest.py calls fnmatch.fnmatch (case-insensitive): {calls}."

    def test_no_hardcoded_win32_literal_in_validate_invariants(self) -> None:
        """Production governance code must not hard-code platform strings."""
        assert '"win32"' not in _VALIDATE_SRC and "'win32'" not in _VALIDATE_SRC, (
            "validate_invariants.py contains a hard-coded 'win32' platform string. "
            "Production governance code must be platform-neutral."
        )


# ---------------------------------------------------------------------------
# RCA-2: is_protected case-sensitivity
# ---------------------------------------------------------------------------


class TestIsProtectedCaseSensitivity:
    """is_protected must be case-sensitive on all platforms (fnmatchcase)."""

    @pytest.mark.parametrize(
        ("filename", "patterns", "expected"),
        [
            ("Makefile", ["Makefile"], True),
            ("makefile", ["makefile"], True),
            ("conftest.py", ["conftest.py"], True),
            ("MAKEFILE", ["Makefile"], False),
            ("Makefile", ["makefile"], False),
            ("makefile", ["Makefile"], False),
            ("CONFTEST.PY", ["conftest.py"], False),
            (".github/workflows/python-package.yml", [".github/workflows/*.yml"], True),
            (".github/Workflows/python-package.yml", [".github/workflows/*.yml"], False),
            ("extra.pth", ["*.pth"], True),
            ("extra.PTH", ["*.pth"], False),
            ("Makefile", ["Makefile", "makefile"], True),
            ("makefile", ["Makefile", "makefile"], True),
            ("MakeFile", ["Makefile", "makefile"], False),
        ],
    )
    def test_is_protected_case_sensitivity(self, filename: str, patterns: list[str], expected: bool) -> None:
        result = is_protected(filename, patterns)
        assert result == expected, (
            f"is_protected({filename!r}, {patterns!r}) -> {result}, expected {expected}. "
            "Indicates fnmatch.fnmatch (case-insensitive) is used instead of fnmatchcase."
        )

    def test_deterministic_across_repeated_calls(self) -> None:
        patterns = ["Makefile", "makefile", "conftest.py"]
        for _ in range(5):
            assert is_protected("Makefile", patterns) is True
            assert is_protected("MAKEFILE", patterns) is False
            assert is_protected("makefile", patterns) is True


# ---------------------------------------------------------------------------
# RCA-8/DEC-059: asyncio self-pipe guard
# ---------------------------------------------------------------------------


class TestWindowsAsyncioSelfPipeGuard:
    """enable_socket pytestmark is Windows-conditional on the affected test modules."""

    def test_mcp_server_enable_socket_mark_windows_conditional(self) -> None:
        import harness.shared.tests.test_mcp_server as mod

        mark = getattr(mod, "pytestmark", None)
        if sys.platform == "win32":
            assert mark is not None, "pytestmark not set on Windows (DEC-059 guard missing)"
            assert mark.name == "enable_socket", f"Expected enable_socket, got {mark.name!r}"
        else:
            assert mark is None, f"enable_socket should be absent on non-Windows, got {mark!r}"

    def test_api_server_regression_enable_socket_mark_windows_conditional(self) -> None:
        import harness.shared.tests.regression.test_api_server_regression as mod

        mark = getattr(mod, "pytestmark", None)
        if sys.platform == "win32":
            assert mark is not None, "pytestmark not set on Windows (DEC-059 guard missing)"
            assert mark.name == "enable_socket", f"Expected enable_socket, got {mark.name!r}"
        else:
            assert mark is None, f"enable_socket should be absent on non-Windows, got {mark!r}"

    def test_enable_socket_guard_is_platform_conditional_in_source(self) -> None:
        src = (REPO / "harness" / "shared" / "tests" / "test_mcp_server.py").read_text(encoding="utf-8")
        if sys.platform == "win32":
            has_guard = 'sys.platform == "win32"' in src or "sys.platform == 'win32'" in src
            assert has_guard, (
                "test_mcp_server.py does not guard enable_socket with a sys.platform check. "
                "The guard must be conditional so Linux CI is unaffected."
            )


# ---------------------------------------------------------------------------
# RCA-1/DEC-057: AF_UNIX hasattr guard
# ---------------------------------------------------------------------------


class TestAFUnixGuard:
    """test_egress_floor.py guards AF_UNIX with hasattr, not a platform literal."""

    def test_af_unix_guard_uses_hasattr(self) -> None:
        src = (REPO / "harness" / "shared" / "tests" / "test_egress_floor.py").read_text(encoding="utf-8")
        has_guard = 'hasattr(socket, "AF_UNIX")' in src or "hasattr(socket, 'AF_UNIX')" in src
        assert has_guard, (
            "test_egress_floor.py has no hasattr(socket, 'AF_UNIX') guard (DEC-057). "
            "Required for Windows compatibility."
        )


# ---------------------------------------------------------------------------
# RCA-7/DEC-058: make-availability guards
# ---------------------------------------------------------------------------


class TestMakeAvailabilityGuards:
    """Tests that invoke GNU Make are guarded with shutil.which('make')."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "harness/shared/tests/regression/test_gate_truthfulness_e2e.py",
            "harness/shared/tests/test_makefile_contracts.py",
            "harness/shared/tests/regression/test_verdict_forgery_regression.py",
        ],
    )
    def test_make_guard_present(self, rel_path: str) -> None:
        src = (REPO / rel_path).read_text(encoding="utf-8")
        has_guard = 'shutil.which("make")' in src or "shutil.which('make')" in src
        assert has_guard, (
            f"{rel_path} has no shutil.which('make') guard. "
            "This test invokes GNU Make and must skip when it is unavailable (DEC-058)."
        )


# ---------------------------------------------------------------------------
# RCA-10: _dec_for_posix_only_probes replaces _sole_decision_id
# ---------------------------------------------------------------------------


class TestDecisionIdGuardInSkipWaiverScope:
    """test_skip_waiver_scope.py uses targeted DEC-026 guard, not sole-id assertion."""

    def test_sole_decision_id_removed(self) -> None:
        import ast as _ast

        src = (REPO / "harness" / "shared" / "tests" / "test_skip_waiver_scope.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        # Detect only code-level definitions and call expressions -- not docstring mentions
        found_def = any(
            isinstance(node, _ast.FunctionDef) and node.name == "_sole_decision_id" for node in _ast.walk(tree)
        )
        found_call = any(
            isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name) and node.func.id == "_sole_decision_id"
            for node in _ast.walk(tree)
        )
        assert not found_def and not found_call, (
            "test_skip_waiver_scope.py still defines or calls _sole_decision_id() in code "
            "(docstring mentions are OK). Replaced by _dec_for_posix_only_probes()."
        )

    def test_dec_for_posix_only_probes_present(self) -> None:
        src = (REPO / "harness" / "shared" / "tests" / "test_skip_waiver_scope.py").read_text(encoding="utf-8")
        assert "_dec_for_posix_only_probes" in src, "test_skip_waiver_scope.py is missing _dec_for_posix_only_probes()."

    def test_dec_026_checked_not_counted(self) -> None:
        src = (REPO / "harness" / "shared" / "tests" / "test_skip_waiver_scope.py").read_text(encoding="utf-8")
        assert '"DEC-026" in decisions' in src or "'DEC-026' in decisions" in src
        assert "len(decisions) == 1" not in src, (
            "len(decisions) == 1 assertion still present. Breaks when new DECs are added."
        )


# ---------------------------------------------------------------------------
# Security regression: case-insensitive path bypass
# ---------------------------------------------------------------------------


class TestCaseInsensitiveBypassCannotEludeGovernance:
    """is_protected must reject case-variant filenames even on case-insensitive FSes."""

    @pytest.mark.parametrize(
        ("filename", "pattern"),
        [
            ("CONFTEST.PY", "conftest.py"),
            ("MAKEFILE", "Makefile"),
            ("Makefile", "makefile"),
            (".GITHUB/WORKFLOWS/PYTHON-PACKAGE.YML", ".github/workflows/python-package.yml"),
        ],
    )
    def test_wrong_case_variant_is_not_protected(self, filename: str, pattern: str) -> None:
        assert not is_protected(filename, [pattern]), (
            f"is_protected({filename!r}, [{pattern!r}]) returned True. "
            "Case-variant filename bypassed governance -- security regression. "
            "Ensure fnmatchcase is used, not fnmatch."
        )
