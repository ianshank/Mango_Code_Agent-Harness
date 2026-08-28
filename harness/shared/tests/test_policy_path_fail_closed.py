"""Every policy reader must tell absence apart from an unusable policy path.

Three modules read ``governance-policy.json`` and all three say the same thing
in their docstrings: no policy file is the adopter path, and a present-but-
malformed policy fails closed. All three implemented that with a bare
``Path.is_file()``, which cannot express it -- ``is_file()`` answers False both
for a path with nothing at it and for a path holding a directory, a dangling
symlink, a FIFO or a device node.

The consequence is not theoretical. A bad volume mount, a half-extracted
archive or a symlink to a file that moved leaves the policy path present and
unreadable; each reader would then take the adopter branch, drop every
threshold and the decision-ID grammar to built-in defaults, and let the run go
green -- the gate reporting success precisely because it stopped reading the
policy that governs it.

This module pins the distinction behaviourally for each reader, and adds a
source-level gate so a fourth reader cannot reintroduce the shape.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import pytest

from harness.shared import policy_loader
from harness.shared.tests._helpers import REPO, SHARED, imported_module

# Kinds of "something is there, but it is not a policy file". Each is a real
# deployment failure, not a hypothetical: a directory is what a container mount
# leaves when the source file is missing, and a dangling symlink is what a
# moved or unextracted target leaves behind.
UNUSABLE_KINDS = ("directory", "dangling_symlink", "fifo")


def _make_unusable(path: Path, kind: str) -> None:
    if kind == "directory":
        path.mkdir()
    elif kind == "dangling_symlink":
        path.symlink_to(path.parent / "target-that-does-not-exist.json")
    elif kind == "fifo":
        import os

        os.mkfifo(path)
    else:  # pragma: no cover - guarded by the parametrize list
        raise AssertionError(f"unknown kind {kind!r}")


def _reader_load_policy(path: Path) -> object:
    return policy_loader.load_policy(path)


# Both readers resolve their policy path at module scope, so the probe has to
# rebind that global. It goes through ``__dict__`` rather than plain attribute
# assignment because a freshly imported ModuleType declares no such attribute
# and mypy rejects the assignment under --check-untyped-defs; the builtin
# setattr would satisfy mypy and trip ruff's B010 instead. Writing the module
# dict is what "set a module global" actually means, and says so.
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
        self, name: str, reader: Callable[[Path], object], error: type[BaseException],
        kind: str, tmp_path: Path,
    ) -> None:
        policy = tmp_path / "governance-policy.json"
        _make_unusable(policy, kind)
        with pytest.raises(error) as exc:
            reader(policy)
        assert "not a regular file" in str(exc.value), (
            f"{name} raised, but not with the reason: {exc.value!r}"
        )

    def test_a_genuinely_absent_policy_is_still_the_adopter_path(
        self, name: str, reader: Callable[[Path], object], error: type[BaseException],
        tmp_path: Path,
    ) -> None:
        """The fix must not turn the supported adopter case into a failure."""
        result = reader(tmp_path / "governance-policy.json")
        assert result is not None, f"{name} returned nothing for an absent policy"

    def test_a_real_policy_file_is_read(
        self, name: str, reader: Callable[[Path], object], error: type[BaseException],
        tmp_path: Path,
    ) -> None:
        """And the guard must not reject the ordinary case it stands in front of."""
        policy = tmp_path / "governance-policy.json"
        policy.write_text('{"decision_id_pattern": "^(DEC-[0-9]+)$"}', encoding="utf-8")
        assert reader(policy) is not None


class TestNoReaderReintroducesTheShape:
    """A source gate, because the behavioural tests above only cover the readers
    someone remembered to register. This one fails on the *shape* -- a policy
    path guarded by ``is_file()`` with nothing distinguishing absence from an
    unusable path -- so a fourth reader is caught the day it is written."""

    # `if not <name containing POLICY_PATH>.is_file():`
    GUARD = re.compile(r"if not (\w*POLICY_PATH)\.is_file\(\):")
    # Lines to look ahead for the distinguishing check.
    LOOKAHEAD = 8

    def _sources(self) -> list[Path]:
        return sorted(
            p for p in (REPO / "harness").rglob("*.py")
            if "/tests/" not in p.as_posix() and "__pycache__" not in p.as_posix()
        )

    def test_every_policy_path_guard_distinguishes_absence(self) -> None:
        offenders = []
        for source in self._sources():
            lines = source.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if not self.GUARD.search(line):
                    continue
                window = "\n".join(lines[index : index + self.LOOKAHEAD])
                if "is_symlink()" not in window:
                    offenders.append(f"{source.relative_to(REPO)}:{index + 1}")
        assert not offenders, (
            "policy-path guards that cannot tell an absent policy from an unusable "
            f"one (no is_symlink()/exists() check within {self.LOOKAHEAD} lines): "
            f"{offenders}. is_file() is False for both, so the adopter branch would "
            "swallow a broken deployment and the run would go green on built-in "
            "defaults. Add the guard, and a case to READERS above."
        )

    def test_the_gate_can_see_the_guards_it_checks(self) -> None:
        """A regex that matched nothing would pass the test above vacuously."""
        found = sum(
            len(self.GUARD.findall(source.read_text(encoding="utf-8")))
            for source in self._sources()
        )
        assert found >= len(READERS) - 1, (
            f"the guard pattern matched {found} site(s); it should find the "
            "module-level POLICY_PATH guards, so the check above is not vacuous"
        )
