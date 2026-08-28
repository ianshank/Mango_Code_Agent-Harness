"""Declared tooling configuration must still apply to something real.

Suppressions and allowlists are write-only in practice: nothing tells you when
one stops being needed, so they accumulate until nobody dares touch them.
Measured before this file was written, the ruff config carried three
per-file-ignore patterns that suppressed nothing at all -- including
``scratch/*.py``, for a gitignored directory that does not exist -- plus a
dozen individually unused codes inside patterns that were otherwise live.

Ruff has no unused-ignore check (``RUF100`` covers inline ``# noqa``, not
config-level per-file-ignores), so a one-time prune would simply rot again.
These tests make the prune stick.

Deliberately *not* enabling ``RUF100``: it would delete the documented
fail-closed justifications carried by the ``# noqa: BLE001`` comments, which
are reasoning, not noise.

Marked ``slow``: each check shells out to ruff over the whole tree.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys

import pytest
import tomllib

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.slow

PYPROJECT = REPO / "pyproject.toml"
GITLEAKS = REPO / ".gitleaks.toml"


def _config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _per_file_ignores() -> dict[str, list[str]]:
    ignores: dict[str, list[str]] = _config()["tool"]["ruff"]["lint"]["per-file-ignores"]
    return ignores


def _isolated_findings(codes: list[str]) -> list[tuple[str, str]]:
    """Findings ruff reports with the project config ignored.

    ``--isolated`` is the whole trick: running ruff normally applies the very
    per-file-ignores under test, so every pattern would look dead. Line length
    and target version are restated because isolation drops those too.
    """
    ruff_cfg = _config()["tool"]["ruff"]
    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", ".", "--isolated", "--no-cache",
            "--line-length", str(ruff_cfg["line-length"]),
            "--target-version", ruff_cfg["target-version"],
            "--select", ",".join(codes),
            "--output-format", "json",
        ],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    rows = json.loads(result.stdout or "[]")
    prefix = str(REPO) + "/"
    return [(row["filename"].replace(prefix, ""), row["code"]) for row in rows]


@pytest.fixture(scope="module")
def findings() -> list[tuple[str, str]]:
    codes = sorted({code for codes in _per_file_ignores().values() for code in codes})
    return _isolated_findings(codes)


class TestPerFileIgnoresAreLive:
    def test_the_probe_finds_something(self, findings: list[tuple[str, str]]) -> None:
        """Guards the measurement: if the isolated run reported nothing, every
        pattern below would look dead and the suite would fail confusingly."""
        assert findings, "the isolated ruff run produced no findings; the probe is broken"

    @pytest.mark.parametrize("pattern", sorted(_per_file_ignores()))
    def test_pattern_matches_at_least_one_file(self, pattern: str) -> None:
        matched = [
            path for path in REPO.rglob("*.py")
            if "__pycache__" not in path.parts
            and fnmatch.fnmatch(path.relative_to(REPO).as_posix(), pattern)
        ]
        assert matched, (
            f"per-file-ignores pattern {pattern!r} matches no file. Delete it: a pattern "
            "for files that do not exist silently exempts whatever is added there later."
        )

    @pytest.mark.parametrize("pattern", sorted(_per_file_ignores()))
    def test_every_code_still_suppresses_something(
        self, pattern: str, findings: list[tuple[str, str]]
    ) -> None:
        declared = set(_per_file_ignores()[pattern])
        firing = {
            code for path, code in findings
            if code in declared and fnmatch.fnmatch(path, pattern)
        }
        assert declared == firing, (
            f"per-file-ignores[{pattern!r}] declares {sorted(declared - firing)} which suppress "
            "nothing. Remove them, or the config claims a rule is needed where it is not -- "
            "and the day it is genuinely needed, nobody can tell the difference."
        )


class TestGitleaksAllowlistIsLive:
    """An allowlist entry that outlives its file is a widening blind spot: the
    path stays exempt, and whatever is created there later is exempt too."""

    def _paths(self) -> list[str]:
        text = GITLEAKS.read_text(encoding="utf-8")
        block = text.split("paths = [", 1)[1].split("]", 1)[0]
        return [line.strip().strip("',").replace("\\", "") for line in block.splitlines() if line.strip()]

    def test_the_allowlist_is_parsed(self) -> None:
        assert len(self._paths()) > 3, "failed to parse .gitleaks.toml paths"

    def test_every_literal_path_entry_still_exists(self) -> None:
        missing = [
            entry for entry in self._paths()
            # Skip genuine regexes (wildcards); only literal file paths are checkable.
            if ".*" not in entry and not (REPO / entry).exists()
        ]
        assert not missing, (
            f"gitleaks allowlist exempts paths that no longer exist: {missing}. Remove them, "
            "or a future file at the same path is scanned by nobody."
        )
