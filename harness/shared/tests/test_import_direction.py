"""The first-party import graph is acyclic, and the verdict vocabulary sits under it.

Spec: ``docs/specs/verdict-propagation.md`` (C-VP-2, AC-13).

An earlier draft of this change justified a module's placement with a cycle that
did not exist. Measuring settled it -- and measuring is worth keeping, because the
edges that *would* close a cycle are exactly the ones a later milestone adds: a
repair loop importing the orchestrator, or a verdict module importing the thing
that constructs it.

Acyclicity alone is not enough. A layer map additionally catches "wrong direction,
not yet cyclic", which is the state a graph passes through on its way to a cycle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.tests._helpers import CONTROL_PLANE, HARNESS, REPO, SHARED
from harness.shared.tests.test_invariant_liveness import _imports

pytestmark = pytest.mark.governance

#: Lower may not import higher. Modules absent from the map are unconstrained by
#: the layer rule but still bound by acyclicity.
LAYERS = {
    "harness.shared.governance.verdict": 0,
    "harness.shared.tool_budget": 0,
    # One step above the vocabulary since R-TDH-14: it compares against
    # `BROKER_BLOCKED` instead of restating the string, and imports nothing else.
    "harness.shared.tool_result_format": 1,
    "harness.shared.governance.verification": 2,
    "harness.shared.mango_mas_orchestrator": 4,
    "harness.api_server.main": 5,
}


def _modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in (SHARED, CONTROL_PLANE, HARNESS / "api_server"):
        for path in root.rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            found[".".join(path.relative_to(REPO).with_suffix("").parts)] = path
    return found


def _graph() -> dict[str, set[str]]:
    """First-party edges only; a package `__init__` re-export is not an edge."""
    names = _modules()
    edges: dict[str, set[str]] = {name: set() for name in names}
    for name, path in names.items():
        for module, _symbol in _imports(path):
            if module in names and module != name:
                edges[name].add(module)
            elif f"{module}.__init__" in names:
                edges[name].add(f"{module}.__init__")
    return edges


class TestTheScanWorks:
    """Positive controls. Without these, a moved directory makes every assertion
    below vacuously true -- which is the failure `test_invariant_liveness` guards
    against by the same means."""

    def test_the_scan_finds_the_modules(self) -> None:
        assert len(_modules()) >= 40

    def test_the_scan_finds_the_edges(self) -> None:
        assert sum(len(v) for v in _graph().values()) >= 40

    def test_a_known_edge_is_present(self) -> None:
        assert "harness.shared.governance.broker" in _graph()["harness.shared.mango_mas_orchestrator"]


class TestTheGraphIsAcyclic:
    def test_no_cycle(self) -> None:
        graph = _graph()
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(node: str) -> list[str] | None:
            state[node] = 1
            stack.append(node)
            for nxt in sorted(graph.get(node, ())):
                if state.get(nxt) == 1:
                    return stack[stack.index(nxt) :] + [nxt]
                if state.get(nxt) is None:
                    found = visit(nxt)
                    if found:
                        return found
            stack.pop()
            state[node] = 2
            return None

        for node in sorted(graph):
            if state.get(node) is None:
                cycle = visit(node)
                assert cycle is None, "import cycle: " + " -> ".join(cycle or [])


class TestLayering:
    def test_the_verdict_vocabulary_imports_nothing_first_party(self) -> None:
        """C-VP-2. It is the bottom of the graph, so `api_server.main` can name a
        verdict field without pulling the governance package in behind it."""
        assert _graph()["harness.shared.governance.verdict"] == set()

    def test_every_edge_goes_downward(self) -> None:
        graph = _graph()
        for source, targets in graph.items():
            if source not in LAYERS:
                continue
            for target in targets:
                if target not in LAYERS:
                    continue
                assert LAYERS[target] < LAYERS[source], (
                    f"{source} (layer {LAYERS[source]}) imports {target} (layer {LAYERS[target]}); "
                    "an edge that does not go downward is a cycle that has not closed yet"
                )
