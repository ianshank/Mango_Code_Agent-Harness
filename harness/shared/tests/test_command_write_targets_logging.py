"""DEBUG logging for harness/shared/governance/command_write_targets.py.

Split alongside the module (DEC-035): ``write_targets`` used to live inside
``command_actions`` with no logger of its own. The new module logs how many
paths it found — never command / program / path text — so a DEBUG session can
see the write gate fire without leaking model-supplied secrets into the log.
"""

from __future__ import annotations

import logging

import pytest

from harness.shared.governance.command_write_targets import (
    _REDIRECT_OPERATORS,
    _compile_redirect_regexes,
    write_targets,
)

pytestmark = pytest.mark.governance


class TestWriteTargetsLogging:
    def test_logs_path_count_at_debug_when_targets_exist(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_write_targets"):
            assert write_targets("echo x > out.txt") == ["out.txt"]
        assert any("write_targets: 1 path(s)" in r.message for r in caplog.records)
        assert any("program_basename_len=" in r.message for r in caplog.records)

    def test_does_not_log_when_no_targets(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_write_targets"):
            assert write_targets("ls -la") == []
        assert not any("write_targets:" in r.message for r in caplog.records)

    def test_log_line_omits_command_program_and_path_text(self, caplog: pytest.LogCaptureFixture) -> None:
        """Broker posture: never echo argv / program / path into DEBUG logs.

        Uses a clearly fake marker (not a secret-shaped token) so scanners stay
        quiet while still proving the payload cannot appear in the log line.
        """
        marker = "UNIQUE_CMD_MARKER_SHOULD_NOT_APPEAR_IN_LOGS"
        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_write_targets"):
            assert write_targets(f"echo {marker} > /tmp/out_should_not_log.txt") == ["/tmp/out_should_not_log.txt"]
        joined = " ".join(r.message for r in caplog.records)
        assert marker not in joined
        assert "echo" not in joined
        assert "out_should_not_log" not in joined
        assert "/tmp/" not in joined


class TestNoWhitespaceRedirectForms:
    """shlex leaves ``x>>out`` / ``x>|out`` as one token; the operator must be
    consumed in full so the broker sees ``out``, not ``>out`` / ``|out``."""

    @pytest.mark.parametrize(
        ("command", "target"),
        [
            pytest.param("echo x>>out.txt", "out.txt", id="append-no-ws"),
            pytest.param("echo x>|out.txt", "out.txt", id="clobber-no-ws"),
            pytest.param("echo x>out.txt", "out.txt", id="truncate-no-ws"),
        ],
    )
    def test_mid_token_redirect_yields_real_filename(self, command: str, target: str) -> None:
        assert write_targets(command) == [target]

    def test_operators_tuple_drives_mid_token_match(self) -> None:
        """Regression guard: presence regex is built from ``_REDIRECT_OPERATORS``,
        not a one-off single-``>`` pattern that truncates ``>>`` / ``>|``."""
        presence, _full, _prefix = _compile_redirect_regexes(_REDIRECT_OPERATORS)
        match = presence.search("x>>out.txt")
        assert match is not None
        assert match.group(0) == ">>"
        assert "x>>out.txt"[match.end() :] == "out.txt"
        clobber = presence.search("x>|out.txt")
        assert clobber is not None
        assert clobber.group(0) == ">|"
