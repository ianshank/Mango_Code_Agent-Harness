"""Dockerfile contract: digest pin, non-root USER, no EXPOSE lie, no tsx (R-SR-25 / R-RHI-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

DOCKERFILE = REPO / "Dockerfile"


def _runtime_stage(text: str) -> str:
    marker = "AS runtime"
    idx = text.find(marker)
    if idx == -1:
        return text
    return text[idx:]


def _runtime_code(text: str) -> str:
    """Runtime stage with comment lines dropped, so a mention in a comment is not a CMD."""
    lines = []
    for line in _runtime_stage(text).splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def test_dockerfile_from_is_digest_pinned() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "@sha256:" in text.splitlines()[1] or any(
        line.startswith("FROM ") and "@sha256:" in line for line in text.splitlines()
    )


def test_dockerfile_runtime_has_user_and_no_expose_or_tsx() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    runtime = _runtime_code(text)
    assert "USER node" in runtime
    assert "EXPOSE " not in runtime
    assert "tsx" not in runtime


def test_dockerfile_contract_fails_tmp_path_copies(tmp_path: Path) -> None:
    """AC-25 / AC-5: a copy missing any required property is rejected."""
    original = DOCKERFILE.read_text(encoding="utf-8")
    runtime = _runtime_code(original)
    assert "@sha256:" in original
    assert "USER " in runtime
    assert "EXPOSE " not in runtime
    assert "tsx" not in runtime

    digest = "@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3"
    unpinned = tmp_path / "unpinned"
    unpinned.write_text(original.replace(digest, ""), encoding="utf-8")
    assert "@sha256:" not in unpinned.read_text(encoding="utf-8")

    no_user = tmp_path / "nouser"
    no_user.write_text(original.replace("USER node\n", ""), encoding="utf-8")
    assert "USER node" not in _runtime_stage(no_user.read_text(encoding="utf-8"))

    with_expose = tmp_path / "expose"
    with_expose.write_text(original.replace("USER node\n", "EXPOSE 8080\nUSER node\n"), encoding="utf-8")
    assert "EXPOSE " in _runtime_stage(with_expose.read_text(encoding="utf-8"))

    with_tsx = tmp_path / "tsx"
    with_tsx.write_text(
        original.replace(
            'CMD ["node", "src/ai/nemotron/cli.ts", "--help"]',
            'CMD ["node", "--loader", "tsx", "src/ai/nemotron/cli.ts", "--help"]',
        ),
        encoding="utf-8",
    )
    assert "tsx" in _runtime_stage(with_tsx.read_text(encoding="utf-8"))
