"""Every policy reader must tell absence apart from an unusable policy path.

Three modules read ``governance-policy.json`` and all three say the same thing
in their docstrings: no policy file is the adopter path, and a present-but-
malformed policy fails closed. All three implemented that with a bare
``Path.is_file()``, which cannot express it.

``is_file()`` answers False for a path with nothing at it *and* for a path
holding a directory, a dangling symlink, a FIFO or a device node -- and, worse,
it swallows OSError, so it also answers False when the policy is present and
merely inaccessible: a parent directory without execute permission, a path
component that turned out to be a file, a symlink loop. ``exists()`` and
``is_symlink()`` swallow the same errors. None of the ``Path`` predicates can
express the question; only the errno can, which is why the readers probe with
``stat``/``lstat``.

The consequence is not theoretical. A container mount whose source is missing
leaves a directory; a moved target leaves a dangling symlink; a bad path
component raises NotADirectoryError. Each one sent every reader down the
adopter branch, so all thresholds and the decision-ID grammar silently fell
back to built-in defaults and the run went green -- the gate reporting success
precisely because it had stopped reading the policy that governs it.

This module pins the distinction behaviourally for each reader, and adds a
source-level gate so a fourth reader cannot reintroduce the shape.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from harness.shared import policy_loader
from harness.shared.tests._helpers import REPO, SHARED, imported_module


def _supports(kind: str) -> bool:
    """Whether this platform can create the artefact a case needs.

    Probed rather than assumed: os.mkfifo is absent on Windows, and symlink
    creation there needs a privilege the process may not hold. The probe runs
    once, so an unsupported case is skipped by name rather than erroring inside
    every test that wanted it -- and a case that *can* be built is never
    skipped, so this cannot quietly hollow the suite out on the platforms CI
    actually runs.
    """
    with tempfile.TemporaryDirectory() as raw:
        probe = Path(raw) / "probe"
        try:
            if kind == "fifo":
                if not hasattr(os, "mkfifo"):
                    return False
                os.mkfifo(probe)
            elif kind == "dangling_symlink":
                probe.symlink_to(Path(raw) / "absent")
            else:
                return True
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


# Kinds of "something is at this path, but it is not a usable policy file".
# Each is a real deployment failure: a directory is what a container mount
# leaves when its source is missing, a dangling symlink is what a moved target
# leaves, and NotADirectoryError is what a path component that became a file
# raises -- the last one reachable through none of the Path predicates.
UNUSABLE_KINDS = [
    pytest.param("directory"),
    pytest.param(
        "dangling_symlink",
        marks=pytest.mark.skipif(not _supports("dangling_symlink"), reason="platform cannot create symlinks"),
    ),
    pytest.param(
        "fifo",
        marks=pytest.mark.skipif(not _supports("fifo"), reason="platform has no os.mkfifo"),
    ),
    pytest.param(
        "not_a_directory",
        marks=pytest.mark.skipif(
            sys.platform == "win32",
            reason="NTFS path resolution through a file raises FileNotFoundError, not NotADirectoryError",
        ),
    ),
]


def _make_unusable(path: Path, kind: str) -> Path:
    """Build the artefact and return the path the reader should be handed."""
    if kind == "directory":
        path.mkdir()
        return path
    if kind == "dangling_symlink":
        path.symlink_to(path.parent / "target-that-does-not-exist.json")
        return path
    if kind == "fifo":
        mkfifo = getattr(os, "mkfifo", None)
        if mkfifo is not None:
            mkfifo(path)
        return path
    if kind == "not_a_directory":
        # A parent component that is a regular file: stat() raises
        # NotADirectoryError, while is_file(), exists() and is_symlink() all
        # answer False and would report this as absence.
        path.write_text("not a directory", encoding="utf-8")
        return path / "governance-policy.json"
    raise AssertionError(f"unknown kind {kind!r}")  # pragma: no cover


def _reader_load_policy(path: Path) -> object:
    return policy_loader.load_policy(path)


# Both standalone readers resolve their policy path at module scope, so the
# probe rebinds that global. It goes through ``__dict__`` rather than plain
# attribute assignment because a freshly imported ModuleType declares no such
# attribute and mypy rejects the assignment under --check-untyped-defs; the
# builtin setattr would satisfy mypy and trip ruff's B010 instead. Writing the
# module dict is what "set a module global" actually means, and says so.
def _reader_check_projections(path: Path) -> object:
    with imported_module(SHARED / "check_projections.py", "cp_probe") as module:
        module.__dict__["POLICY_PATH"] = path
        return module.decision_id_regex()


def _reader_verify_zero_skips(path: Path) -> object:
    target = SHARED / "governance" / "verify_zero_skips.py"
    with imported_module(target, "vzs_probe") as module:
        module.__dict__["_POLICY_PATH"] = path
        return module._decision_id_regex()


# (name, callable, the exception type that reader raises when it fails closed).
# A new module that reads the governance policy belongs here; the source gate
# below is what makes forgetting it visible.
READERS: tuple[tuple[str, Callable[[Path], object], type[BaseException]], ...] = (
    ("policy_loader.load_policy", _reader_load_policy, policy_loader.PolicyError),
    ("check_projections.decision_id_regex", _reader_check_projections, SystemExit),
    ("verify_zero_skips._decision_id_regex", _reader_verify_zero_skips, SystemExit),
)

_READER_IDS = [name for name, _, _ in READERS]


@pytest.mark.parametrize(("name", "reader", "error"), READERS, ids=_READER_IDS)
class TestPolicyPathFailsClosed:
    @pytest.mark.parametrize("kind", UNUSABLE_KINDS)
    def test_an_unusable_policy_path_stops_the_run(
        self,
        name: str,
        reader: Callable[[Path], object],
        error: type[BaseException],
        kind: str,
        tmp_path: Path,
    ) -> None:
        policy = _make_unusable(tmp_path / "governance-policy.json", kind)
        with pytest.raises(error) as exc:
            reader(policy)
        # A bare raise would not distinguish this fix from an unrelated crash.
        assert "refusing to fall back" in str(exc.value) or "not readable" in str(exc.value), (
            f"{name} raised for {kind}, but not with a reason: {exc.value!r}"
        )

    def test_a_genuinely_absent_policy_is_still_the_adopter_path(
        self,
        name: str,
        reader: Callable[[Path], object],
        error: type[BaseException],
        tmp_path: Path,
    ) -> None:
        """The fix must not turn the supported adopter case into a failure."""
        assert reader(tmp_path / "governance-policy.json") is not None

    def test_a_real_policy_file_is_read(
        self,
        name: str,
        reader: Callable[[Path], object],
        error: type[BaseException],
        tmp_path: Path,
    ) -> None:
        """And the guard must not reject the ordinary case it stands in front of."""
        policy = tmp_path / "governance-policy.json"
        policy.write_text('{"decision_id_pattern": "^(DEC-[0-9]+)$"}', encoding="utf-8")
        assert reader(policy) is not None

    @pytest.mark.skipif(not _supports("dangling_symlink"), reason="platform cannot create symlinks")
    def test_a_symlink_to_a_real_policy_is_followed(
        self,
        name: str,
        reader: Callable[[Path], object],
        error: type[BaseException],
        tmp_path: Path,
    ) -> None:
        """Rejecting every symlink would be a fail-*closed* bug of its own.

        The guard must reject a symlink whose target is gone and accept one
        whose target is a real file, which is why it probes with both stat and
        lstat rather than either alone.
        """
        real = tmp_path / "real-policy.json"
        real.write_text('{"decision_id_pattern": "^(DEC-[0-9]+)$"}', encoding="utf-8")
        link = tmp_path / "governance-policy.json"
        link.symlink_to(real)
        assert reader(link) is not None


class TestGuardsProbeErrnoNotPredicates:
    """The Path predicates cannot express the question, and this says why.

    If a future refactor swaps the stat probe back for ``is_file()``, these
    facts about the stdlib are what makes that a regression rather than a
    style choice -- so they are asserted, not left in a comment.
    """

    def test_the_path_predicates_report_an_unreachable_path_as_absent(self, tmp_path: Path) -> None:
        blocker = tmp_path / "a-regular-file"
        blocker.write_text("not a directory", encoding="utf-8")
        unreachable = blocker / "governance-policy.json"

        assert unreachable.is_file() is False
        assert unreachable.exists() is False
        assert unreachable.is_symlink() is False
        # Windows raises FileNotFoundError (WinError 3); POSIX raises NotADirectoryError.
        # Both correctly signal "unreachable", but the errno differs.
        with pytest.raises((NotADirectoryError, FileNotFoundError)):
            unreachable.stat()

    def test_stat_distinguishes_the_cases_the_predicates_collapse(self, tmp_path: Path) -> None:
        directory = tmp_path / "as-a-directory"
        directory.mkdir()
        assert not stat.S_ISREG(directory.stat().st_mode)

        regular = tmp_path / "as-a-file"
        regular.write_text("{}", encoding="utf-8")
        assert stat.S_ISREG(regular.stat().st_mode)


# `if not <name containing POLICY_PATH>.is_file():` -- the shape being banned.
_BANNED_GUARD = re.compile(r"if not (\w*POLICY_PATH)\.is_file\(\)")


def _offending_lines(source: str) -> list[int]:
    """1-indexed lines where a policy path is guarded by is_file()."""
    return [index + 1 for index, line in enumerate(source.splitlines()) if _BANNED_GUARD.search(line)]


class TestNoReaderReintroducesTheShape:
    """A source gate, because the behavioural tests only cover the readers
    someone remembered to register in READERS.

    It bans the shape outright rather than looking for a compensating call
    nearby. An earlier version required an ``is_symlink()`` within a few lines,
    which a guard checking *only* ``is_symlink()`` would have satisfied while
    still failing open on a directory. There is no correct way to answer this
    question with ``is_file()``, so the rule is simply that a policy path is
    never guarded by it.
    """

    def _sources(self) -> list[Path]:
        return sorted(
            p
            for p in (REPO / "harness").rglob("*.py")
            if "/tests/" not in p.as_posix() and "__pycache__" not in p.as_posix()
        )

    def test_no_policy_path_is_guarded_by_is_file(self) -> None:
        offenders = [
            f"{source.relative_to(REPO)}:{line}"
            for source in self._sources()
            for line in _offending_lines(source.read_text(encoding="utf-8"))
        ]
        assert not offenders, (
            f"policy-path guards written with is_file(): {offenders}. is_file() is "
            "False both for an absent path and for a present-but-unusable one, and it "
            "swallows OSError so it is also False for a present-but-inaccessible one. "
            "Probe with stat()/lstat() and branch on the errno instead -- see "
            "policy_loader.policy_file_is_absent -- then add a case to READERS above."
        )

    def test_the_gate_detects_the_shape_it_bans(self) -> None:
        """A positive control. A pattern that matched nothing would leave the
        test above passing vacuously forever, and nothing would say so."""
        offending = "\n".join(
            (
                "POLICY_PATH = Path('governance-policy.json')",
                "def read():",
                "    if not POLICY_PATH.is_file():",
                "        return FALLBACK",
            )
        )
        assert _offending_lines(offending) == [3]

    def test_the_gate_accepts_the_shape_it_wants(self) -> None:
        """And the inverse control: the fixed form must not be flagged."""
        accepted = "\n".join(
            (
                "def read():",
                "    try:",
                "        info = POLICY_PATH.stat()",
                "    except FileNotFoundError:",
                "        return FALLBACK",
            )
        )
        assert _offending_lines(accepted) == []


class TestPolicyFileIsAbsentErrorBranches:
    def test_stat_oserror_raises_policy_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = Path("governance-policy.json")

        def mock_stat(self):
            raise PermissionError("Access denied")

        monkeypatch.setattr(Path, "stat", mock_stat)
        with pytest.raises(policy_loader.PolicyError, match="is not readable"):
            policy_loader.policy_file_is_absent(p)

    def test_stat_filenotfound_lstat_oserror_raises_policy_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = Path("governance-policy.json")

        def mock_stat(self):
            raise FileNotFoundError("Target not found")

        def mock_lstat(self):
            raise PermissionError("Symlink access denied")

        monkeypatch.setattr(Path, "stat", mock_stat)
        monkeypatch.setattr(Path, "lstat", mock_lstat)
        with pytest.raises(policy_loader.PolicyError, match="is not readable"):
            policy_loader.policy_file_is_absent(p)

    def test_stat_filenotfound_lstat_success_raises_dangling_symlink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = Path("governance-policy.json")

        def mock_stat(self):
            raise FileNotFoundError("Target not found")

        def mock_lstat(self):
            return os.stat_result((stat.S_IFLNK, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        monkeypatch.setattr(Path, "stat", mock_stat)
        monkeypatch.setattr(Path, "lstat", mock_lstat)
        with pytest.raises(policy_loader.PolicyError, match="symlink whose target does not exist"):
            policy_loader.policy_file_is_absent(p)
