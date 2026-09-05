"""Tests for the control-plane digest regenerator.

This script runs inside `make ci` (the `digest-regen` stage) yet had **zero** test
coverage, because its paths were module constants that could not be pointed at a
fixture. Every test here drives it against a temporary bundle, so the drift
behaviour is exercised without touching the repository's real one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO / "harness" / "control-plane" / "regenerate_bundle_digests.py"


def _load_module():
    """Load by path: `harness/control-plane` is not an importable package name."""
    spec = importlib.util.spec_from_file_location("regenerate_bundle_digests", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


regen = _load_module()


def _bundle(tmp_path: Path, profiles: dict) -> Path:
    path = tmp_path / "policy-bundle.example.json"
    path.write_text(json.dumps({"profiles": profiles}, indent=2) + "\n", encoding="utf-8")
    return path


def _stack(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


class TestDigest:
    def test_digest_matches_sha256_of_bytes(self, tmp_path: Path):
        target = tmp_path / "f.txt"
        target.write_bytes(b"governance")
        assert regen.digest(target) == hashlib.sha256(b"governance").hexdigest()

    def test_digest_is_content_sensitive(self, tmp_path: Path):
        target = tmp_path / "f.txt"
        target.write_text("a")
        first = regen.digest(target)
        target.write_text("b")
        assert regen.digest(target) != first


class TestRegenerate:
    def test_recomputes_digest_from_actual_file_content(self, tmp_path: Path):
        root = _stack(tmp_path, "node", {"policy.json": "content-v2"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"policy.json": "stale" * 16}}})
        bundle, dropped = regen.regenerate(bundle_path, {"node": root})
        expected = hashlib.sha256(b"content-v2").hexdigest()
        assert bundle["profiles"]["node"]["protected_files"]["policy.json"] == expected
        assert dropped == {}

    def test_reports_dropped_entries_instead_of_silently_removing_them(self, tmp_path: Path):
        """The regression this module exists for: drops used to produce no output."""
        root = _stack(tmp_path, "node", {"kept.json": "x"})
        bundle_path = _bundle(
            tmp_path,
            {"node": {"protected_files": {"kept.json": "old", "vanished.json": "old"}}},
        )
        bundle, dropped = regen.regenerate(bundle_path, {"node": root})
        assert dropped == {"node": ["vanished.json"]}
        assert "vanished.json" not in bundle["profiles"]["node"]["protected_files"]
        assert "kept.json" in bundle["profiles"]["node"]["protected_files"]

    def test_drop_is_logged_at_warning(self, tmp_path: Path, capsys):
        """Asserted on real stderr, not caplog: the gate logger deliberately does
        not propagate to root, so caplog's root handler would never see it."""
        root = _stack(tmp_path, "node", {"kept.json": "x"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"kept.json": "o", "gone.json": "o"}}})
        regen.regenerate(bundle_path, {"node": root})
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "gone.json" in captured.err
        assert "gone.json" not in captured.out

    def test_does_not_write_the_bundle(self, tmp_path: Path):
        """regenerate() is read-only; main() decides whether to persist."""
        root = _stack(tmp_path, "node", {"a.json": "new"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"a.json": "old"}}})
        before = bundle_path.read_text(encoding="utf-8")
        regen.regenerate(bundle_path, {"node": root})
        assert bundle_path.read_text(encoding="utf-8") == before

    def test_handles_multiple_stacks_independently(self, tmp_path: Path):
        node = _stack(tmp_path, "node", {"p.json": "n"})
        jvm = _stack(tmp_path, "jvm", {"p.json": "j"})
        bundle_path = _bundle(
            tmp_path,
            {
                "node": {"protected_files": {"p.json": "old"}},
                "jvm": {"protected_files": {"p.json": "old"}},
            },
        )
        bundle, _ = regen.regenerate(bundle_path, {"node": node, "jvm": jvm})
        node_digest = bundle["profiles"]["node"]["protected_files"]["p.json"]
        jvm_digest = bundle["profiles"]["jvm"]["protected_files"]["p.json"]
        assert node_digest == hashlib.sha256(b"n").hexdigest()
        assert jvm_digest == hashlib.sha256(b"j").hexdigest()
        assert node_digest != jvm_digest

    def test_missing_profile_is_tolerated(self, tmp_path: Path):
        """A bundle without a declared stack must not crash the regenerator."""
        root = _stack(tmp_path, "node", {"a.json": "x"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"a.json": "old"}}})
        bundle, dropped = regen.regenerate(bundle_path, {"node": root, "absent": tmp_path / "nope"})
        assert dropped == {}
        assert bundle["profiles"]["node"]["protected_files"]["a.json"]

    def test_warns_when_a_profile_resolves_to_nothing(self, tmp_path: Path, capsys):
        root = _stack(tmp_path, "node", {})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"gone.json": "old"}}})
        regen.regenerate(bundle_path, {"node": root})
        assert "no resolvable protected files" in capsys.readouterr().out


class TestMain:
    def test_persists_recomputed_digests_and_returns_zero(self, tmp_path: Path):
        root = _stack(tmp_path, "node", {"p.json": "fresh"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"p.json": "stale"}}})
        assert regen.main(bundle_path, {"node": root}) == 0
        written = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert written["profiles"]["node"]["protected_files"]["p.json"] == (hashlib.sha256(b"fresh").hexdigest())

    def test_output_is_idempotent_on_a_second_run(self, tmp_path: Path):
        """The digest-regen gate pairs this with `git diff --exit-code`, so a
        second run over unchanged files must produce byte-identical output."""
        root = _stack(tmp_path, "node", {"p.json": "stable"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"p.json": "old"}}})
        regen.main(bundle_path, {"node": root})
        first = bundle_path.read_text(encoding="utf-8")
        regen.main(bundle_path, {"node": root})
        assert bundle_path.read_text(encoding="utf-8") == first

    def test_written_file_ends_with_a_single_newline(self, tmp_path: Path):
        root = _stack(tmp_path, "node", {"p.json": "x"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"p.json": "o"}}})
        regen.main(bundle_path, {"node": root})
        text = bundle_path.read_text(encoding="utf-8")
        assert text.endswith("}\n") and not text.endswith("\n\n")

    def test_drops_are_surfaced_on_stderr_not_stdout(self, tmp_path: Path, capsys):
        """stdout carries the stable summary; warnings must not pollute it."""
        root = _stack(tmp_path, "node", {"kept.json": "x"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"kept.json": "o", "gone.json": "o"}}})
        regen.main(bundle_path, {"node": root})
        captured = capsys.readouterr()
        assert "gone.json" in captured.err
        assert "gone.json" not in captured.out
        assert "[PASS] Regenerated digests" in captured.out

    def test_main_tolerates_a_stack_absent_from_the_bundle(self, tmp_path: Path, capsys):
        """main() iterates stack_roots; a stack the bundle does not declare must
        report zero rather than raising KeyError, matching regenerate()."""
        root = _stack(tmp_path, "node", {"p.json": "x"})
        bundle_path = _bundle(tmp_path, {"node": {"protected_files": {"p.json": "o"}}})
        assert regen.main(bundle_path, {"node": root, "absent": tmp_path / "nope"}) == 0
        assert "absent: 0 protected file digests" in capsys.readouterr().out

    def test_defaults_point_at_the_real_repository_bundle(self):
        """The zero-argument form the Makefile uses must still resolve correctly."""
        assert regen.BUNDLE.is_file()
        assert set(regen.STACK_ROOTS) == {"node", "jvm"}
        for root in regen.STACK_ROOTS.values():
            assert root.is_dir()


class TestRepositoryBundleIsCurrent:
    def test_committed_bundle_matches_regenerated_digests(self):
        """Mirrors the `digest-regen` CI stage: the committed bundle must already
        be current, so a stale digest fails here as well as in the Make target."""
        bundle, dropped = regen.regenerate()
        committed = json.loads(regen.BUNDLE.read_text(encoding="utf-8"))
        assert dropped == {}, f"committed bundle references missing files: {dropped}"
        assert bundle == committed, "policy-bundle.example.json is stale; run `make digest-regen` and commit"
