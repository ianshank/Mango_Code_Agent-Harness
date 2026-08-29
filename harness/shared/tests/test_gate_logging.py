"""Tests for the shared gate-logging helper.

The property that matters is a boundary one: governance gates print their verdict
to **stdout**, and both CI and this suite match on those exact strings. Diagnostics
therefore go to **stderr**, so raising verbosity can never alter what a gate
reports. These tests pin that separation, not the wording of any message.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.json_logging import (
    DEFAULT_GATE_LOG_LEVEL,
    LOG_LEVEL_ENV_VAR,
    configure_gate_logging,
    resolve_log_level,
)

REPO = Path(__file__).resolve().parents[3]


class TestResolveLogLevel:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("DEBUG", logging.DEBUG),
            ("debug", logging.DEBUG),
            ("  WarNing  ", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("10", logging.DEBUG),
            ("30", logging.WARNING),
        ],
    )
    def test_accepts_names_case_insensitively_and_numeric_strings(self, raw, expected):
        assert resolve_log_level(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_empty_falls_back_to_the_documented_default(self, raw, monkeypatch):
        monkeypatch.delenv(LOG_LEVEL_ENV_VAR, raising=False)
        assert resolve_log_level(raw) == logging.getLevelName(DEFAULT_GATE_LOG_LEVEL)

    @pytest.mark.parametrize("raw", ["NONSENSE", "verbose", "TRACE", "!!"])
    def test_unusable_value_degrades_instead_of_raising(self, raw):
        """Misconfigured verbosity must never be able to fail a governance gate."""
        assert resolve_log_level(raw) == logging.getLevelName(DEFAULT_GATE_LOG_LEVEL)

    def test_reads_the_environment_when_no_argument_is_given(self, monkeypatch):
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "ERROR")
        assert resolve_log_level() == logging.ERROR

    def test_threshold_is_not_hardcoded_to_a_single_level(self, monkeypatch):
        """The level is operator-controlled; the module only owns the fallback."""
        for name, expected in (("DEBUG", logging.DEBUG), ("CRITICAL", logging.CRITICAL)):
            monkeypatch.setenv(LOG_LEVEL_ENV_VAR, name)
            assert resolve_log_level() == expected


class TestConfigureGateLogging:
    def test_diagnostics_go_to_stderr_never_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "DEBUG")
        logger = configure_gate_logging("test.gate.stderr")
        print("gate: passed")  # the stdout contract a gate must preserve
        logger.debug("inspected 3 files")
        captured = capsys.readouterr()
        assert captured.out == "gate: passed\n", "diagnostics leaked into the stdout contract"
        assert "inspected 3 files" in captured.err

    def test_repeated_calls_do_not_stack_handlers(self, monkeypatch):
        """A module imported twice in one session must not double every line."""
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "INFO")
        name = "test.gate.idempotent"
        first = configure_gate_logging(name)
        count = len(first.handlers)
        for _ in range(3):
            configure_gate_logging(name)
        assert len(first.handlers) == count == 1

    def test_level_is_applied_to_logger_and_handlers(self, monkeypatch):
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "WARNING")
        logger = configure_gate_logging("test.gate.level")
        assert logger.level == logging.WARNING
        assert all(h.level == logging.WARNING for h in logger.handlers)

    def test_below_threshold_records_are_suppressed(self, monkeypatch, capsys):
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "WARNING")
        logger = configure_gate_logging("test.gate.suppressed")
        logger.debug("should not appear")
        logger.warning("should appear")
        captured = capsys.readouterr()
        assert "should not appear" not in captured.err
        assert "should appear" in captured.err

    def test_does_not_propagate_to_root(self, monkeypatch, capsys):
        """A stray basicConfig() elsewhere must not be able to redirect gate
        diagnostics onto stdout and corrupt a verdict."""
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "DEBUG")
        logger = configure_gate_logging("test.gate.noprop")
        assert logger.propagate is False
        root = logging.getLogger()
        stray = logging.StreamHandler(sys.stdout)
        root.addHandler(stray)
        try:
            logger.debug("diagnostic")
            assert "diagnostic" not in capsys.readouterr().out
        finally:
            root.removeHandler(stray)

    def test_stream_is_resolved_lazily_not_bound_at_construction(self, monkeypatch, capsys):
        """Configured once, then captured: a handler bound at construction would
        write to the original stderr and be invisible here."""
        monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "INFO")
        logger = configure_gate_logging("test.gate.lazy")
        logger.info("first")
        assert "first" in capsys.readouterr().err
        logger.info("second")
        assert "second" in capsys.readouterr().err


class TestRealGateStdoutContract:
    """End-to-end: raising verbosity must not change a real gate's stdout."""

    def _run(self, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
        import os

        env = {**os.environ, **env_extra}
        return subprocess.run(
            [sys.executable, "../shared/governance/check_traceability.py"],
            cwd=REPO / "harness" / "node",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_stdout_is_byte_identical_across_log_levels(self):
        quiet = self._run({LOG_LEVEL_ENV_VAR: "CRITICAL"})
        loud = self._run({LOG_LEVEL_ENV_VAR: "DEBUG"})
        assert quiet.returncode == loud.returncode == 0
        assert quiet.stdout == loud.stdout, (
            "verbosity changed a gate's stdout; the verdict channel is not isolated"
        )
        assert "traceability: passed" in quiet.stdout

    def test_debug_adds_diagnostics_on_stderr_only(self):
        loud = self._run({LOG_LEVEL_ENV_VAR: "DEBUG"})
        assert "glob" in loud.stderr, "DEBUG produced no glob diagnostics"
        assert "glob" not in loud.stdout


class TestFallbackLoggerDoesNotLeakToStdout:
    """When the shared helper is unimportable, the fallback must still not
    propagate: `setup_json_logging` attaches a ROOT handler on **stdout**, so a
    propagating fallback would put diagnostics into the verdict channel."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "harness/shared/governance/check_traceability.py",
            "harness/shared/governance/pretooluse_guard.py",
            "harness/control-plane/regenerate_bundle_digests.py",
        ],
    )
    def test_gate_fallback_logger_does_not_propagate(self, module_path, monkeypatch):
        import builtins
        import importlib.util

        real_import = builtins.__import__

        def explode(name, *args, **kwargs):
            if "json_logging" in name:
                raise ImportError("simulated missing shared package")
            return real_import(name, *args, **kwargs)

        spec = importlib.util.spec_from_file_location(
            f"probe_{Path(module_path).stem}", REPO / module_path
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setattr(builtins, "__import__", explode)
        spec.loader.exec_module(module)  # module-level _gate_logger() takes the fallback
        monkeypatch.setattr(builtins, "__import__", real_import)

        assert module.logger.propagate is False, (
            f"{module_path} fallback logger propagates to root; a root handler on "
            "stdout would leak diagnostics into the gate's verdict channel"
        )
        assert module.logger.handlers, f"{module_path} fallback logger has no handler"
