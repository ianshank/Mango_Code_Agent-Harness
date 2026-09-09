"""Reproduction: the migration-completeness gate blocked every new decision record.

``test_validate_governance_docs.TestValidateGovernanceDocs
.test_migration_completeness_every_legacy_id_present`` exists to prove NS-34's
migration left no pre-NS-34 pipe-log entry behind. It asserted **equality**
against a hard-coded ``{DEC-000 … DEC-056}``::

    expected = {f"DEC-{n:03d}" for n in range(57)}
    assert ids == expected

The migrated set is fixed, but the index it was compared against is not: it
grows with every decision the repository records after the migration. So the
first record added past DEC-056 failed a gate whose stated subject -- "every
*legacy* id is present" -- it did not violate. The defect reached ``main``
(``d1e13c5``) latent, because ``main`` held exactly the 57 migrated records and
nothing had been added since; DEC-057 was the first record to trip it, and the
failure named ``extra ['DEC-057']`` on a check about missing ones.

This is the unbounded-scope shape inverted. DEC-032, DEC-038 and DEC-039 each
found a gate that judged only the set it was handed without asking whether that
set was the set that exists; this one pinned the set that existed at authoring
time and rejected the set that exists now. Both fail for the same reason: the
boundary of what the gate governs was written as a literal.

The fix is the subset the docstring always described (``expected <= ids``).
These reproductions pin that semantics from both sides, so a revert to equality
fails here -- naming the defect -- rather than only in the gate it re-breaks.
"""

from __future__ import annotations

import json

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

#: The pre-NS-34 pipe-log range the migration had to carry over. Fixed by
#: history: DEC-056 was the last id the pipe log held when NS-34 ran, so this
#: literal is a fact about the past, not a bound on the present.
LEGACY_MIGRATED_IDS = frozenset(f"DEC-{n:03d}" for n in range(57))


def _index_ids() -> frozenset[str]:
    payload = json.loads((REPO / "docs" / "decisions" / "index.json").read_text(encoding="utf-8"))
    return frozenset(row["id"] for row in payload["decisions"])


def test_every_legacy_id_survived_the_migration() -> None:
    """The property the gate is actually for: nothing migrated was dropped."""
    missing = LEGACY_MIGRATED_IDS - _index_ids()
    assert not missing, f"NS-34 migration lost {sorted(missing)}"


def test_a_record_added_after_the_migration_does_not_fail_completeness() -> None:
    """The reproduction. Under the pre-fix equality assertion this configuration
    -- a real index carrying at least one post-migration record -- was exactly
    what failed, reporting the new id as ``extra`` on a missing-id check."""
    ids = _index_ids()
    post_migration = ids - LEGACY_MIGRATED_IDS
    assert post_migration, (
        "no decision record exists past the migrated set, so this reproduction "
        "cannot fail and proves nothing; it must be deleted or re-aimed rather "
        "than left as a false assurance (CONTRACT.md, Regression / AQA tier)"
    )
    assert LEGACY_MIGRATED_IDS <= ids, (
        f"completeness rejected an index carrying post-migration records {sorted(post_migration)}"
    )


def test_every_legacy_id_has_a_record_file() -> None:
    """Presence in the generated index is not presence on disk; the gate checks
    both, and a regenerated index could carry a row whose file was deleted."""
    decisions = REPO / "docs" / "decisions"
    absent = sorted(dec_id for dec_id in LEGACY_MIGRATED_IDS if not (decisions / f"{dec_id}.md").is_file())
    assert not absent, f"migrated decision record file(s) missing from disk: {absent}"
