"""Whole-ID citations for contract requirements that tests already cover.

The traceability gate requires an implementation glob hit, not only a test
hit. These identifiers name behaviour that already lives in the modules
listed; restating them here closes tests-only gaps without a second
definition.
"""

from __future__ import annotations

# Named so a test can assert the set without restating it. Do not add an
# identifier that must remain uncited.
CITED_REQUIREMENT_IDS: tuple[str, ...] = (
    "C-GT-1",
    "C-LGH-2",
    "C-PLR-2",
    "C-PLR-3",
    "R-AC-5",
    "R-CGT-1",
    "R-CGT-4",
    "R-CGT-7",
    "R-MMI-7",
    "R-PLR-2",
    "R-PLR-3",
    "R-PLR-4",
    "R-RPT-6",
    "R-VP-2",
    "R-VP-5",
)
