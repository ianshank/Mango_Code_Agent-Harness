"""Tests for validate_adoption: check_adoption and main CLI entry point."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.shared.validate_adoption import check_adoption, main


def _scaffold_minimal(root: Path) -> None:
    """Build the minimum tree that passes all adoption checks."""
    # CI workflow — no PIN_FULL_COMMIT_SHA placeholder
    ci = root / ".github" / "workflows" / "ci.yml"
    ci.parent.mkdir(parents=True, exist_ok=True)
    ci.write_text("name: ci\non: push\njobs: {}", encoding="utf-8")

    # Allowed remotes
    gov = root / ".governance"
    gov.mkdir(parents=True, exist_ok=True)
    (gov / "allowed-remotes.txt").write_text("https://github.com/org/repo.git", encoding="utf-8")

    # Policy
    policy_content = json.dumps({"schema_version": "2.0.0"})
    (gov / "policy.json").write_text(policy_content, encoding="utf-8")
    digest = hashlib.sha256(policy_content.encode()).hexdigest()

    # Root of trust
    (gov / "root-of-trust.json").write_text(
        json.dumps({"external_policy_ref": "https://example.com", "policy_sha256": digest}),
        encoding="utf-8",
    )


class TestCheckAdoption:
    """check_adoption returns a list of blockers; empty means ready."""

    def test_clean_passes(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        assert check_adoption(tmp_path) == []

    def test_missing_ci(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        (tmp_path / ".github" / "workflows" / "ci.yml").unlink()
        blockers = check_adoption(tmp_path)
        assert any("CI workflow missing" in b for b in blockers)

    def test_pinned_sha_placeholder(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        ci = tmp_path / ".github" / "workflows" / "ci.yml"
        ci.write_text("uses: actions/checkout@PIN_FULL_COMMIT_SHA", encoding="utf-8")
        blockers = check_adoption(tmp_path)
        assert any("not pinned" in b for b in blockers)

    def test_empty_allowed_remotes(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        (tmp_path / ".governance" / "allowed-remotes.txt").write_text("# comments only", encoding="utf-8")
        blockers = check_adoption(tmp_path)
        assert any("no approved destination" in b for b in blockers)

    def test_missing_root_of_trust(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        (tmp_path / ".governance" / "root-of-trust.json").unlink()
        blockers = check_adoption(tmp_path)
        assert any("root-of-trust.json missing" in b for b in blockers)

    def test_digest_mismatch(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        rot = tmp_path / ".governance" / "root-of-trust.json"
        data = json.loads(rot.read_text())
        data["policy_sha256"] = "a" * 64
        rot.write_text(json.dumps(data), encoding="utf-8")
        blockers = check_adoption(tmp_path)
        assert any("does not match" in b for b in blockers)

    def test_missing_pnpm_lock(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        blockers = check_adoption(tmp_path)
        assert any("pnpm-lock.yaml missing" in b for b in blockers)

    def test_pnpm_lock_present(self, tmp_path: Path) -> None:
        _scaffold_minimal(tmp_path)
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9", encoding="utf-8")
        blockers = check_adoption(tmp_path)
        assert not any("pnpm-lock" in b for b in blockers)


class TestAdoptionMain:
    """CLI entry point must exit 0 on pass, 1 on block."""

    def test_passes_cleanly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _scaffold_minimal(tmp_path)
        main(tmp_path)  # no SystemExit
        assert "passed" in capsys.readouterr().out

    def test_exits_1_on_failure(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)  # nothing scaffolded
        assert exc_info.value.code == 1
