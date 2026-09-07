"""The two properties of the parked LangGraph topology that a *test* enforces.

D-5 and D-6 of `docs/specs/graph-engineering-adoption.md` settle which
enforcement surface these belong on, and the answer is this file rather than a
`make` target. A check that is a pure function over repository state costs
nothing new in the ordinary pytest run and inherits INV-2's zero-skip
discipline; a CI gate would cost a `ci_required_targets` entry, a
`harness/CONTRACT.md` row, a `test_ci_gate_coverage.py` update and three
protected-path attestations — spent on a subsystem DEC-053 has already decided
to sunset. So: the defect is made visible here, and no gate is added there.

The two tests are the two halves of that resolution.

`test_orphan_reviewers_match_the_recorded_decision` (AC-GEA-9b) pins DEC-052's
recorded state: `peer_reviewer` and `security_reviewer` are registered with no
incoming edge, so the `findings` channel is empty on every run. The existing
behavioural suite cannot catch this — `test_langgraph_graph.py` asserts the node
*set*, which both orphans satisfy, so it pins the defect rather than finding it.
This test fails in both directions, which is the point of pairing it with the
decision record: wiring a reviewer in without amending DEC-052 fails it, and
deleting a reviewer node fails it too.

`test_topology_gate_is_parked_with_langgraph` (AC-GEA-9) pins the *absence* of a
CI gate to DEC-053's `accepted` status, so the park is enforced rather than
merely minuted. It deliberately does not fail because a topology test exists:
the test suite is the sanctioned surface, and confusing the two is exactly the
conflation D-5's rebuttal took apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness.shared.graph_topology import Topology, extract_topology
from harness.shared.tests._ci_gate_helpers import (
    _evidence_text,
    _expand_make_vars,
    _make_targets,
    _reachable_from,
)
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

GRAPH_SOURCE = REPO / "harness" / "shared" / "langgraph" / "graph.py"
DECISIONS = REPO / "docs" / "decisions"
DEC_052 = DECISIONS / "DEC-052.md"
DEC_053 = DECISIONS / "DEC-053.md"
MAKEFILE = REPO / "Makefile"
POLICY = REPO / "harness" / "shared" / "governance-policy.json"

#: The two nodes DEC-052 records as registered-but-unreachable.
ORPHAN_REVIEWERS = ("peer_reviewer", "security_reviewer")

#: The wording DEC-052 uses for their state. Matched as a phrase inside one
#: sentence rather than anywhere in the record, because "the record mentions
#: both names somewhere" would stay true of a record that had been rewritten to
#: say the opposite.
RECORDED_STATE = "no incoming edge"

#: What a StateGraph topology *gate* would be called. Applied to `make` target
#: names and to `ci_required_targets` entries; `test_the_target_detector_is_not
#: _vacuous` proves it would actually match one.
TOPOLOGY_TARGET = re.compile(r"topolog|state-?graph", re.IGNORECASE)

#: The extractor invoked as a command — the shape a gate would take. Deliberately
#: not a bare search for `graph_topology`: a recipe naming
#: `test_graph_topology.py` is a *test* being run, which D-5 permits and this
#: file is itself an instance of.
TOPOLOGY_GATE_COMMAND = re.compile(r"-m\s+harness\.shared\.graph_topology|harness/shared/graph_topology\.py")


@pytest.fixture(scope="module")
def topology() -> Topology:
    """The real graph, read from source so no optional import gates this suite."""
    return extract_topology(GRAPH_SOURCE)


@pytest.fixture(scope="module")
def makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def frontmatter_value(record: Path, key: str) -> str:
    """One scalar from a decision record's YAML frontmatter."""
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", record.read_text(encoding="utf-8"), re.M)
    assert match, f"{record} has no `{key}:` line; the decision-record format changed"
    return match.group(1).strip().strip("\"'")


def recorded_sentences(record: Path, phrase: str) -> list[str]:
    """Sentences of ``record`` containing ``phrase``, in document order."""
    text = record.read_text(encoding="utf-8")
    return [sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if phrase in sentence]


def test_orphan_reviewers_match_the_recorded_decision(topology: Topology) -> None:
    """AC-GEA-9b, satisfying R-GEA-6b: the reviewers are edgeless, and DEC-052 says so.

    Both directions are load-bearing. Asserting only that they are edgeless
    would let someone delete them and keep the suite green, which silently
    resolves a defect the decision record still describes; asserting only that
    the record says so would let someone wire them in and leave the record
    stale. The pair is what makes the record and the code move together.
    """
    for reviewer in ORPHAN_REVIEWERS:
        assert reviewer in topology.nodes, (
            f"`{reviewer}` is no longer declared in {GRAPH_SOURCE}. DEC-052 records it as registered with "
            f"{RECORDED_STATE}; deleting the node changes that recorded state, so the deletion must amend "
            "docs/decisions/DEC-052.md in the same change."
        )

    for reviewer in ORPHAN_REVIEWERS:
        incoming, outgoing = topology.predecessors(reviewer), topology.successors(reviewer)
        assert not incoming and not outgoing, (
            f"`{reviewer}` has been wired into the graph (incoming: {incoming or 'none'}, "
            f"outgoing: {outgoing or 'none'}) without amending docs/decisions/DEC-052.md, which records it as "
            f"registered with {RECORDED_STATE}. Wiring a reviewer in is an expansion of the graph and belongs "
            "with the in-or-out decision NS-31 owns; amend DEC-052 in the same change."
        )

    orphans = topology.nodes_without_edges()
    assert set(ORPHAN_REVIEWERS) <= set(orphans), (
        f"nodes_without_edges() reports {orphans}, which disagrees with the per-node edge assertions above; "
        "the extractor, not the graph, is what changed."
    )

    assert frontmatter_value(DEC_052, "status") == "accepted", (
        "docs/decisions/DEC-052.md is no longer `accepted`, so it no longer records the state this test pins. "
        "A superseding record must restate the orphan reviewers' status, and this test must point at it."
    )
    sentences = recorded_sentences(DEC_052, RECORDED_STATE)
    assert sentences, (
        f"docs/decisions/DEC-052.md no longer contains a sentence recording {RECORDED_STATE!r}. The graph still "
        f"leaves {' and '.join(ORPHAN_REVIEWERS)} edgeless, so removing the record leaves the defect undocumented."
    )
    naming_both = [s for s in sentences if all(reviewer in s for reviewer in ORPHAN_REVIEWERS)]
    assert naming_both, (
        f"no single sentence of docs/decisions/DEC-052.md records both {' and '.join(ORPHAN_REVIEWERS)} as having "
        f"{RECORDED_STATE}; the sentences that mention it are: {sentences}. If a reviewer was wired in, amend the "
        "record; if the record was rewritten, this test must be updated with it."
    )


def test_topology_gate_is_parked_with_langgraph(makefile_text: str) -> None:
    """AC-GEA-9: no StateGraph topology *target* while DEC-053's park stands.

    R-GEA-6 forbids the gate, not the check. The assertions below therefore look
    only at `make` target names, `ci_required_targets` entries, and recipes that
    execute the extractor as a command — never at whether a topology *test*
    exists. This module is itself such a test, and it must pass.

    The pairing is the enforcement: if DEC-053 stops being `accepted` the park is
    lifted, and a topology gate becomes a legitimate thing to add — so this test
    checks that the record names its successor and stops asserting, which is the
    "AC-GEA-9's test is updated in the same change that supersedes it" clause of
    the spec's backward-compatibility section. That branch is an early return
    rather than a skip: INV-2 counts skips, and a check that quietly does
    nothing is the failure mode this whole spec is about.
    """
    assert frontmatter_value(DEC_053, "status") == "accepted", (
        "DEC-053 no longer parks the LangGraph topology gate; replace or revise this assertion in the "
        "same change that supersedes the decision."
    )

    targets = _make_targets(makefile_text)
    assert "ci" in targets, "the root Makefile has no `ci` target; the parser, not the Makefile, is what changed"
    ci_reachable = _reachable_from(makefile_text, "ci")
    assert {"lint", "coverage", "validate"} <= ci_reachable, (
        f"`make ci` no longer reaches lint/coverage/validate ({sorted(ci_reachable)}); this test would be vacuous"
    )

    wired = sorted(target for target in ci_reachable if TOPOLOGY_TARGET.search(target))
    assert not wired, (
        f"`make ci` reaches {wired}, a StateGraph topology gate, while docs/decisions/DEC-053.md is still "
        "`accepted`. R-GEA-6 parks the gate with the subsystem: supersede DEC-053 first, or keep the check in "
        "the test suite where D-5 puts it."
    )

    required = json.loads(POLICY.read_text(encoding="utf-8"))["ci_required_targets"]
    assert required, "governance-policy.json declares no ci_required_targets; this assertion would be vacuous"
    listed = sorted(target for target in required if TOPOLOGY_TARGET.search(target))
    assert not listed, (
        f"governance-policy.json lists {listed} in ci_required_targets while DEC-053's park stands; per D-5 this "
        "spec adds no ci_required_target at all."
    )

    recipes = _expand_make_vars(makefile_text, _evidence_text(makefile_text, "ci"))
    invocation = TOPOLOGY_GATE_COMMAND.search(recipes)
    found = invocation.group(0) if invocation else ""
    assert invocation is None, (
        f"a recipe reachable from `make ci` runs the topology extractor as a gate ({found!r}) while DEC-053's "
        "park stands; the extractor's enforcement surface is the pytest run, not a make target."
    )

    # The other half of D-5: the test surface *is* live. If the shared test
    # directory ever stopped being run from `make ci`, "no gate" would stop
    # meaning "checked elsewhere" and start meaning "not checked at all".
    assert "harness/shared/tests" in recipes, (
        "no recipe reachable from `make ci` runs harness/shared/tests; with no gate and no test run, the "
        "topology would be unchecked rather than checked on a different surface."
    )


def test_the_target_detector_is_not_vacuous() -> None:
    """A pattern that matches no plausible gate name would pass forever.

    The same failure the spec's problem statement describes for
    `check_traceability.py`: a check whose input set is empty reports success.
    Here the input set is "target names that look like a topology gate", so the
    detector is exercised against names such a gate would plausibly carry.
    """
    for plausible in ("check-topology", "topology-gate", "verify-stategraph", "validate-state-graph"):
        assert TOPOLOGY_TARGET.search(plausible), f"{plausible} would not be detected as a topology gate"
    for unrelated in ("lint", "coverage", "test-langgraph", "validate"):
        assert not TOPOLOGY_TARGET.search(unrelated), f"{unrelated} would be misreported as a topology gate"
    assert TOPOLOGY_GATE_COMMAND.search("\t$(PYTHON) -m harness.shared.graph_topology --check")
    assert not TOPOLOGY_GATE_COMMAND.search("\t$(PYTEST) harness/shared/tests/test_graph_topology.py"), (
        "running the topology *test* must not read as a gate; that conflation is what D-5 resolved"
    )
