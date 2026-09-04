"""The enforcement digest names what the verdict was earned against.

``harness/shared/governance/enforcement_digest.py`` walks a workspace and
digests every file ``protected_paths`` names. ``VerificationRunner`` compares
that set across the loop; these tests pin the set itself: what is in it, what
is deliberately not, and that the digest is the one the control plane pins the
policy bundle with.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.governance import enforcement_digest as module
from harness.shared.governance.enforcement_digest import (
    EnforcementDigestError,
    enforcement_digests,
    tampered_files,
)
from harness.shared.tests._helpers import CONTROL_PLANE, imported_module
from harness.shared.write_policy import ALWAYS_DENIED_SEGMENTS, policy_digest

pytestmark = pytest.mark.governance


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "Makefile").write_text("test-python:\n\ttrue\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("# root\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text("# nested\n", encoding="utf-8")
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "feature.py").write_text("print('hi')\n", encoding="utf-8")
    return tmp_path


class TestWhatIsDigested:
    def test_protected_files_are_digested_by_workspace_relative_posix_path(self, workspace: Path) -> None:
        digests = enforcement_digests(workspace)
        assert {"Makefile", "pyproject.toml", "conftest.py", "tests/conftest.py"} <= set(digests)
        assert digests["Makefile"] == policy_digest((workspace / "Makefile").read_bytes())

    def test_ordinary_files_are_not_in_the_set(self, workspace: Path) -> None:
        """The agent's own output must be free to change, or every run would be
        tampering and the check would be indistinguishable from an outage."""
        digests = enforcement_digests(workspace)
        assert "src/feature.py" not in digests
        assert "tests/test_x.py" not in digests

    def test_the_interpreters_startup_files_are_digested_wherever_they_live(self, workspace: Path) -> None:
        """The write door prunes nothing: `*.pth` and `**/sitecustomize.py`
        reach into a virtualenv's site-packages, which is where the interpreter
        the recipe starts loads them from. The digest used to prune `.venv`
        (reusing the CI gate's skip list), so a startup file could change there
        under both digest checks with the verdict still issued (Copilot review
        on PR #86). The set is now the write door's set."""
        site = workspace / ".venv" / "lib" / "python3.11" / "site-packages"
        site.mkdir(parents=True)
        (site / "extra.pth").write_text("import evil\n", encoding="utf-8")
        (site / "sitecustomize.py").write_text("x = 1\n", encoding="utf-8")
        (site / "usercustomize.py").write_text("y = 1\n", encoding="utf-8")
        shipped = workspace / "node_modules" / "pkg"
        shipped.mkdir(parents=True)
        (shipped / "conftest.py").write_text("# shipped with a package\n", encoding="utf-8")

        digests = enforcement_digests(workspace)

        assert {
            ".venv/lib/python3.11/site-packages/extra.pth",
            ".venv/lib/python3.11/site-packages/sitecustomize.py",
            ".venv/lib/python3.11/site-packages/usercustomize.py",
            "node_modules/pkg/conftest.py",
        } <= set(digests)

    @pytest.mark.parametrize("segment", sorted(ALWAYS_DENIED_SEGMENTS))
    def test_only_the_always_denied_segments_are_left_out(self, workspace: Path, segment: str) -> None:
        """`.git` is the one directory no agent write may target at all
        (`write_policy.ALWAYS_DENIED_SEGMENTS`), so it is the one the walk
        skips -- the same constant, not a second list."""
        inside = workspace / segment / "hooks"
        inside.mkdir(parents=True)
        (inside / "conftest.py").write_text("# not a recipe input\n", encoding="utf-8")
        assert not any(path.startswith(f"{segment}/") for path in enforcement_digests(workspace))

    def test_armed_patterns_catch_files_that_appear(self, workspace: Path) -> None:
        """The nine dormant patterns exist for this: a `GNUmakefile` or a
        `pytest.ini` that did not exist at loop start is a new recipe input."""
        before = enforcement_digests(workspace)
        for name in ("GNUmakefile", "makefile", "pytest.ini", "tox.ini", "setup.cfg", "setup.py",
                     "sitecustomize.py", "usercustomize.py", "extra.pth"):
            (workspace / name).write_text("x", encoding="utf-8")
        (workspace / "src" / "nested.pth").write_text("x", encoding="utf-8")
        after = enforcement_digests(workspace)
        appeared = set(after) - set(before)
        assert {"GNUmakefile", "makefile", "pytest.ini", "tox.ini", "setup.cfg", "setup.py",
                "sitecustomize.py", "usercustomize.py", "extra.pth", "src/nested.pth"} <= appeared

    def test_a_pinned_supplied_policy_widens_the_floor(
        self,
        workspace: Path,
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A supplied policy is unioned with the harness floor, exactly as the
        write door composes it (R-PPP-1), and only when pinned (R-PPP-3).
        Substituting it would let an adopter's protected surface change without
        appearing in the baseline (Copilot review on PR #86)."""
        from harness.shared import write_policy

        policy = workspace / "other-policy.json"
        raw = json.dumps({"protected_paths": ["src/**"]}).encode("utf-8")
        policy.write_bytes(raw)
        # The pin record must live outside the governed tree (INV-6), so it
        # gets its own temporary directory rather than a corner of ``workspace``.
        pins = tmp_path_factory.mktemp("pins") / "pins.json"
        pins.write_text(
            json.dumps(
                {"pinned_policies": {write_policy.pin_key(policy): write_policy.policy_digest(raw)}}
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv(write_policy.POLICY_PIN_RECORD_ENV, str(pins))

        digests = enforcement_digests(workspace, policy_path=policy)
        assert "src/feature.py" in digests, "the supplied pattern was not added"
        assert "Makefile" in digests, "the harness floor was substituted away"

    def test_an_unpinned_supplied_policy_is_refused(self, workspace: Path, tmp_path: Path) -> None:
        policy = tmp_path / "other-policy.json"
        policy.write_text(json.dumps({"protected_paths": ["src/**"]}), encoding="utf-8")
        with pytest.raises(EnforcementDigestError, match="not trusted"):
            enforcement_digests(workspace, policy_path=policy)

    def test_the_result_is_deterministic(self, workspace: Path) -> None:
        assert enforcement_digests(workspace) == enforcement_digests(workspace)


class TestItFailsClosed:
    def test_an_unreadable_policy_raises(
        self, workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`load_protected_patterns` exits for a CLI gate; here that would kill
        the orchestrator. It is converted, not swallowed."""
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(module, "DEFAULT_POLICY_PATH", broken)
        with pytest.raises(EnforcementDigestError, match="could not be read"):
            enforcement_digests(workspace)

    def test_a_policy_without_protected_paths_raises(self, workspace: Path, tmp_path: Path) -> None:
        policy = tmp_path / "keyless.json"
        policy.write_text(json.dumps({"limits": {}}), encoding="utf-8")
        with pytest.raises(EnforcementDigestError):
            enforcement_digests(workspace, policy_path=policy)

    def test_an_unreadable_protected_file_raises(self, workspace: Path) -> None:
        """A dangling symlink named like a protected file: listed by the walk,
        unreadable by content. Chosen over `chmod 000` because CI runs as root
        and reads through permission bits."""
        (workspace / "pytest.ini").symlink_to(workspace / "does-not-exist.ini")
        with pytest.raises(EnforcementDigestError, match="pytest.ini"):
            enforcement_digests(workspace)


class TestTamperedFiles:
    def test_changed_added_and_removed_are_all_reported_sorted(self) -> None:
        baseline = {"Makefile": "a", "conftest.py": "b", "pyproject.toml": "c"}
        current = {"Makefile": "a2", "pyproject.toml": "c", "GNUmakefile": "d"}
        assert tampered_files(baseline, current) == ["GNUmakefile", "Makefile", "conftest.py"]

    def test_identical_snapshots_report_nothing(self) -> None:
        snapshot = {"Makefile": "a"}
        assert tampered_files(snapshot, dict(snapshot)) == []


class TestTheDigestIsTheControlPlanesDigest:
    """DEC-019: the control plane carries its own two-line sha256 by design and
    imports nothing from the governed tree. This pins that the shared function
    the runner uses computes the same value, so a bundle digest and a baseline
    digest of one file can never disagree."""

    def test_all_three_agree_on_the_same_bytes(self, workspace: Path) -> None:
        target = workspace / "Makefile"
        expected = policy_digest(target.read_bytes())
        with imported_module(CONTROL_PLANE / "build_policy_bundle.py", "_bpb_digest_probe") as bundle:
            assert bundle.sha(target) == expected
        with imported_module(CONTROL_PLANE / "regenerate_bundle_digests.py", "_rbd_digest_probe") as regen:
            assert regen.digest(target) == expected
        assert enforcement_digests(workspace)["Makefile"] == expected
