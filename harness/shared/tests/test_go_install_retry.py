"""Transient GOPROXY failures must not fail a required dependency-audit job."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from harness.shared.tests._helpers import REPO

SCRIPT = REPO / "harness" / "shared" / "go_install_retry.sh"


def _fake_go(tmp_path: Path, succeed_on: int) -> tuple[Path, Path]:
    """A `go` that fails until attempt ``succeed_on`` (1-based); 0 never succeeds."""
    counter = tmp_path / "n"
    counter.write_text("0", encoding="utf-8")
    fake = tmp_path / "go"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'n=$(cat "$COUNTER")\n'
        "n=$((n + 1))\n"
        'echo "$n" > "$COUNTER"\n'
        f'if [ "{succeed_on}" -eq 0 ] || [ "$n" -lt {succeed_on} ]; then\n'
        '  echo "stream error: INTERNAL_ERROR" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake, counter


def _run(tmp_path: Path, attempts: str = "4") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    env["COUNTER"] = str(tmp_path / "n")
    env["GO_INSTALL_ATTEMPTS"] = attempts
    env["GO_INSTALL_RETRY_SECONDS"] = "0"
    return subprocess.run(
        ["bash", str(SCRIPT), "example.com/mod@v1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_go_install_retry_passes_after_transient_failures(tmp_path: Path) -> None:
    _fake_go(tmp_path, succeed_on=3)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "n").read_text(encoding="utf-8").strip() == "3"


def test_go_install_retry_fails_closed_after_budget(tmp_path: Path) -> None:
    _fake_go(tmp_path, succeed_on=0)
    result = _run(tmp_path, attempts="3")
    assert result.returncode == 1
    assert (tmp_path / "n").read_text(encoding="utf-8").strip() == "3"
    assert "failed after 3" in result.stderr
