"""Regression: roadmap/docs consumed as UTF-8 must stay valid UTF-8 on disk.

A PowerShell ``Out-File -Encoding utf8`` rewrite of ``NEXT_STEPS.md`` during
merge union produced a Latin-1/mojibake file. ``test_documentation_truth`` and
``test_ci_gate_required_checks`` then failed with ``UnicodeDecodeError`` on
every Windows run. Pin that the files those gates read decode as UTF-8.
"""

from __future__ import annotations

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

_MUST_BE_UTF8 = (
    "NEXT_STEPS.md",
    "CHANGELOG.md",
    "README.md",
    "Makefile",
    "docs/architecture/c4_architecture.md",
)


@pytest.mark.parametrize("rel", list(_MUST_BE_UTF8))
def test_governed_doc_decodes_as_utf8(rel: str) -> None:
    path = REPO / rel
    assert path.is_file(), f"missing {rel}"
    raw = path.read_bytes()
    raw.decode("utf-8")  # raises UnicodeDecodeError on mojibake/Latin-1
    # Reject UTF-16 LE BOM left by some Windows writers.
    assert not raw.startswith(b"\xff\xfe"), f"{rel} looks UTF-16 LE, not UTF-8"
