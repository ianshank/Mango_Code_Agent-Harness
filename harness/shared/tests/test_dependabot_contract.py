"""Dependabot contract: docker ecosystem and cooldown (R-SR-25 / R-RHI-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.tests._workflow_paths import DEPENDABOT

pytestmark = pytest.mark.governance


def _docker_block(text: str) -> str:
    marker = 'package-ecosystem: "docker"'
    idx = text.find(marker)
    assert idx != -1, "dependabot.yml has no docker ecosystem"
    rest = text[idx:]
    nxt = rest.find("\n  - package-ecosystem:", 1)
    return rest if nxt == -1 else rest[:nxt]


def test_dependabot_docker_ecosystem_has_cooldown() -> None:
    text = DEPENDABOT.read_text(encoding="utf-8")
    block = _docker_block(text)
    assert "cooldown:" in block
    assert "default-days:" in block


def test_dependabot_contract_fails_when_cooldown_removed(tmp_path: Path) -> None:
    """AC-25: a copy of the docker entry without cooldown is rejected."""
    text = DEPENDABOT.read_text(encoding="utf-8")
    stripped = text.replace("    cooldown:\n      default-days: 7\n", "")
    copy = tmp_path / "dependabot.yml"
    copy.write_text(stripped, encoding="utf-8")
    assert "cooldown:" not in _docker_block(copy.read_text(encoding="utf-8"))
    assert "cooldown:" in _docker_block(text)
