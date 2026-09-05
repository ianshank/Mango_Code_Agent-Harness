"""Regression tests for Windows-portability fixes introduced in the origin-sync branch.

Covers:
- RCA-4 : ``is_protected`` uses ``fnmatch.fnmatchcase`` (case-sensitive) so
  governance patterns behave identically on Windows and Linux (fnmatch on Windows
  is case-insensitive, which would let ``Makefile`` slip past a pattern that
  only named ``makefile``).
- RCA-3/DEC-059 : asyncio self-pipe TCP fallback on Windows -- ``test_mcp_server.py``
  and ``test_api_server_regression.py`` add ``pytestmark = enable_socket`` on
  win32 only so the event loop self-pipe can be established.
"""

from __future__ import annotations

import sys

import pytest

from harness.shared.validate_invariants import is_protected

pytestmark = pytest.mark.governance


class TestIsProtectedCaseSensitivity:
    """``is_protected`` must be case-sensitive on all platforms (fnmatchcase).

    On Windows, ``fnmatch.fnmatch`` is case-insensitive. The governance patterns
    include both ``Makefile`` and ``makefile`` as distinct protected filenames.
    Using ``fnmatch.fnmatch`` on Windows would collapse the two, letting a file
    named ``MAKEFILE`` slip past a pattern ``makefile`` -- or vice versa -- and
    would mismatch the Linux CI behaviour (DEC-055 shape inside governance).
    """

    def test_exact_case_matches(self) -> None:
        """A filename whose case matches the pattern exactly is protected."""
        assert is_protected("Makefile", ["Makefile"])
        assert is_protected("makefile", ["makefile"])

    def test_wrong_case_does_not_match(self) -> None:
        """A filename whose case does NOT match the pattern is NOT protected.

        This is the regression: ``fnmatch.fnmatch`` on Windows would return True
        here; ``fnmatch.fnmatchcase`` (the fix) returns False, matching Linux.
        """
        assert not is_protected("MAKEFILE", ["Makefile"])
        assert not is_protected("Makefile", ["makefile"])
        assert not is_protected("makefile", ["Makefile"])

    def test_wildcard_pattern_respects_case(self) -> None:
        """Wildcard patterns (``**``, ``*``) still require case-correct literal parts."""
        assert is_protected(".github/workflows/python-package.yml", [".github/workflows/*.yml"])
        assert not is_protected(".github/Workflows/python-package.yml", [".github/workflows/*.yml"])

    def test_doubly_protected_case_variants_are_independent(self) -> None:
        """Both ``Makefile`` and ``makefile`` are in the floor; each matches only itself."""
        patterns = ["Makefile", "makefile"]
        assert is_protected("Makefile", patterns)
        assert is_protected("makefile", patterns)
        # A third casing matches neither
        assert not is_protected("MakeFile", patterns)

    def test_pth_glob_is_case_sensitive(self) -> None:
        """``*.pth`` does not match ``*.PTH`` on any platform."""
        assert is_protected("extra.pth", ["*.pth"])
        assert not is_protected("extra.PTH", ["*.pth"])


class TestWindowsAsyncioSelfPipeGuard:
    """The asyncio self-pipe mark guard is present and Windows-conditional.

    On Windows without AF_UNIX, asyncio's self-pipe falls back to a loopback
    TCP socket (``socket.socketpair()`` emulation). ``pytest-socket`` blocks
    this socket by default. The fix adds ``pytestmark = enable_socket`` at
    module level, guarded by ``sys.platform == "win32"`` so Linux CI is unaffected.

    These tests pin the guard's presence (the module attribute, not the runtime
    socket behaviour, which depends on the test environment's socket policy).
    """

    def test_mcp_server_pytestmark_is_set_on_windows(self) -> None:
        """``test_mcp_server`` carries ``enable_socket`` when running on Windows."""
        import harness.shared.tests.test_mcp_server as mod

        if sys.platform == "win32":
            mark = getattr(mod, "pytestmark", None)
            assert mark is not None, "pytestmark not set on Windows"
            # pytestmark is a single MarkDecorator on win32
            assert mark.name == "enable_socket", f"Expected enable_socket, got {mark.name!r}"
        else:
            # On Linux the attribute should not exist (no pytestmark at module level)
            mark = getattr(mod, "pytestmark", None)
            assert mark is None, f"enable_socket pytestmark should be absent on Linux, got {mark!r}"

    def test_api_server_regression_pytestmark_is_set_on_windows(self) -> None:
        """``test_api_server_regression`` carries ``enable_socket`` when running on Windows."""
        import harness.shared.tests.regression.test_api_server_regression as mod

        if sys.platform == "win32":
            mark = getattr(mod, "pytestmark", None)
            assert mark is not None, "pytestmark not set on Windows"
            assert mark.name == "enable_socket", f"Expected enable_socket, got {mark.name!r}"
        else:
            mark = getattr(mod, "pytestmark", None)
            assert mark is None, f"enable_socket pytestmark should be absent on Linux, got {mark!r}"
