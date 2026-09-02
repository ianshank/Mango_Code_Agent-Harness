"""Fixtures for the colocated control-plane tests (tech-debt-hardening-plan R-TDH-26).

`harness/control-plane` is not an importable package (the hyphen), so these
tests load the scripts by path -- see `harness.shared.tests._helpers`. Session
hooks (skip evidence, langgraph deselection) come from the repository-root
conftest.py and are deliberately not re-registered here.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """The repository root, the same value harness/shared/tests/conftest.py provides."""
    return Path(__file__).resolve().parents[3]
