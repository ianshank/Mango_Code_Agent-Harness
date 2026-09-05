"""Tests for neuro-symbolic synthesis policy gates (INV-9..INV-15)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

POLICY_PATH = Path(__file__).resolve().parents[1] / "governance-policy.json"


@pytest.fixture
def synthesis_policy() -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    synth: dict[str, Any] = dict(policy.get("synthesis", {}))
    return synth


@pytest.mark.neurosym
def test_synthesis_policy_present(synthesis_policy: dict) -> None:
    """Synthesis policy section must be defined in governance-policy.json."""
    assert synthesis_policy, "synthesis policy section missing from governance-policy.json"


@pytest.mark.neurosym
def test_inv12_max_repair_cycles(synthesis_policy: dict) -> None:
    """INV-12: Repair loops must stop at a bounded budget."""
    cycles = synthesis_policy.get("max_repair_cycles")
    assert isinstance(cycles, int) and cycles > 0, "max_repair_cycles must be a positive integer"
    assert cycles <= 10, "max_repair_cycles must be bounded"


@pytest.mark.neurosym
def test_inv15_lats_disabled_by_default(synthesis_policy: dict) -> None:
    """INV-15: LATS must remain disabled by default until cost-adjusted threshold is met."""
    assert synthesis_policy.get("lats_enabled") is False, "lats_enabled must be false by default"


@pytest.mark.neurosym
def test_inv11_critique_schema_version(synthesis_policy: dict) -> None:
    """INV-11: Critique schema version must be pinned."""
    assert synthesis_policy.get("critique_schema_version") == "1.0"


@pytest.mark.neurosym
def test_prohibited_synthesis_imports(synthesis_policy: dict) -> None:
    """Synthesis candidates must not import dangerous modules without sandbox mediation."""
    prohibited = synthesis_policy.get("prohibited_imports", [])
    for pkg in ("os.system", "subprocess", "shutil.rmtree"):
        assert pkg in prohibited, f"Prohibited import {pkg} must be declared"
