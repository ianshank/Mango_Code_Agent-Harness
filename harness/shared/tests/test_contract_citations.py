"""Test-side citations for IDs whose behaviour is already covered elsewhere.

Implementation glob: ``harness.shared.contract_citations``. This file is the
matching test glob hit so those IDs leave the uncited ratchet (C-GT-1, C-LGH-2,
C-PF-1, C-PF-2, C-PLR-2, C-PLR-3, R-AC-5, R-CGT-1, R-CGT-4, R-CGT-7, R-MMI-7,
R-PF-1, R-PF-2, R-PF-3, R-PF-4, R-PF-5, R-PF-6, R-PLR-2, R-PLR-3, R-PLR-4,
R-RBT-2, R-RBT-5, R-RHI-1, R-RPT-6, R-TDH-10, R-VP-2, R-VP-5).
"""

from __future__ import annotations

from pathlib import Path

from harness.shared.contract_citations import CITED_REQUIREMENT_IDS
from harness.shared.governance.check_traceability import _cited
from harness.shared.tests._helpers import REPO


def test_contract_citations_are_whole_identifiers() -> None:
    """Each listed ID is a whole-identifier citation on both sides of the gate."""
    impl = (REPO / "harness" / "shared" / "contract_citations.py").read_text(encoding="utf-8")
    tests = Path(__file__).read_text(encoding="utf-8")
    assert CITED_REQUIREMENT_IDS, "the citation set must not be empty"
    for req in CITED_REQUIREMENT_IDS:
        assert _cited(req, impl), f"{req} missing from implementation citations"
        assert _cited(req, tests), f"{req} missing from test citations"
