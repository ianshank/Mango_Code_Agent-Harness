"""The real skip-waiver registry must approve today's skips and nothing wider.

`test_verify_zero_skips.py` proves the matcher behaves correctly against
synthetic registries. Nothing read the registry this repository actually ships,
so its rows could widen without any test noticing -- and seven of its eight rows
paired a module-wide `unique_id_glob` with `test: "*"`, which approves every
skip anyone adds to that module later, provided the reason mentions the decision
id. The reusable `POSIX_ONLY` marker's reason ends in `(DEC-026)`, so that
condition was already satisfied by construction.

These tests bound the registry from the side nothing else covers: a skip added
where no skip condition exists is refused (gate-truthfulness R-GT-7).

The other side -- that every skip the suite really produces stays approved --
is deliberately NOT asserted here. `make verify-zero-skips-python` already does
exactly that, and does it in the only order that is honest: the evidence file
is gitignored and written at session finish, so a test reading it mid-session
sees either nothing (a fresh clone, where the assertion would fail for a reason
unrelated to the registry) or the previous run's file (where it would pass on
stale evidence). A gate that can pass on last run's output is the failure this
file exists to prevent, so the pipeline stage keeps that job.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

WAIVERS = REPO / "harness" / "shared" / "tests" / "skip-waivers.json"
DECISION_LOG = REPO / "harness" / "node" / ".governance" / "decision-log.md"
VERIFIER = REPO / "harness" / "shared" / "governance" / "verify_zero_skips.py"


#: The decision every row in the shipped registry cites. Read from the registry
#: rather than restated, so a future registry citing a different decision does
#: not silently make these probes test nothing.
def _registry() -> dict:
    data: dict = json.loads(WAIVERS.read_text(encoding="utf-8"))
    return data


def _decision_ids() -> set[str]:
    return {row["decision_id"] for row in _registry()["waivers"]}


def _dec_for_posix_only_probes() -> str:
    """The decision id the POSIX_ONLY waivers cite, for the probes that test them.

    These probes are about the DEC-026 POSIX waivers specifically:
    ``test_shadow_planner.py::TestContainment`` carries ``POSIX_ONLY`` (DEC-026),
    while ``TestHelpers`` and ``test_langgraph_nodes.py::TestAnything`` do not.
    Using the literal id makes the probe's scope explicit rather than coupling it
    to a ``_sole_decision_id()`` guard that breaks when new DECs are added.
    The registry is free to grow new decisions; these probes are about DEC-026 rows.
    """
    decisions = _decision_ids()
    assert "DEC-026" in decisions, (
        f"DEC-026 is no longer in the registry; these probes pin DEC-026 rows. "
        f"Update them if the POSIX-only waivers moved to a different DEC. "
        f"Current ids: {sorted(decisions)}"
    )
    return "DEC-026"


def _verify(events: Path) -> subprocess.CompletedProcess:
    """Run the real gate against the real registry and a supplied evidence file."""
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--junit-events",
            str(events),
            "--decision-log",
            str(DECISION_LOG),
            "--waivers",
            str(WAIVERS),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


class TestTheShippedRegistryIsParseable:
    def test_every_row_addresses_something_and_cites_a_decision(self) -> None:
        rows = _registry()["waivers"]
        assert rows, "the shipped waiver registry is empty; these probes would prove nothing"
        for row in rows:
            address = row.get("unique_id") or row.get("unique_id_glob")
            assert address, f"waiver row without an address: {row}"
            assert row.get("decision_id"), f"waiver row without a decision id: {row}"


class TestWaiversAreNodeScoped:
    """A waiver must approve the skips that exist, not a module's whole future."""

    @pytest.mark.parametrize(
        ("node_id", "why"),
        [
            (
                "harness/shared/tests/test_shadow_planner.py::TestHelpers::test_a_new_skip",
                "TestHelpers carries no skip condition; the module-wide waiver used to cover it",
            ),
            (
                "harness/shared/tests/test_langgraph_nodes.py::TestAnything::test_a_new_skip",
                (
                    "test_langgraph_nodes.py carries no skip condition; the test_langgraph_*.py "
                    "glob used to cover all five modules to approve four skips in one class"
                ),
            ),
        ],
    )
    def test_a_skip_where_no_condition_exists_is_refused(self, node_id: str, why: str, tmp_path: Path) -> None:
        """The mutation the narrowing exists to catch.

        Both node ids sit inside a module the registry waives, and both carry a
        reason bearing the registry's own decision id -- which is all the
        pre-narrowing rows required.
        """
        decision = _dec_for_posix_only_probes()
        events = tmp_path / "skips.tsv"
        events.write_text(
            f"{node_id}\ttest_a_new_skip\tconvenient reason ({decision})\n",
            encoding="utf-8",
        )
        result = _verify(events)
        assert result.returncode != 0, (
            f"the registry still approves a skip at {node_id}, where {why}. A waiver that "
            "pre-approves skips nobody has written is not a waiver."
        )
        assert "unapproved" in (result.stdout + result.stderr).lower()

    def test_a_skip_where_the_condition_lives_is_still_approved(self, tmp_path: Path) -> None:
        """The converse, so the narrowing cannot have simply broken the gate."""
        decision = _dec_for_posix_only_probes()
        events = tmp_path / "skips.tsv"
        events.write_text(
            f"harness/shared/tests/test_shadow_planner.py::TestContainment::test_x\ttest_x\tPOSIX-only ({decision})\n",
            encoding="utf-8",
        )
        result = _verify(events)
        assert result.returncode == 0, (
            f"the narrowing dropped a class that really does carry a POSIX_ONLY skip: {result.stdout}{result.stderr}"
        )
