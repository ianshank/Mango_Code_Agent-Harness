"""Unit tests for the source-level ``StateGraph`` topology extractor.

Two halves, and the second is the one that matters. The first exercises the
parser over small inline snippets written to ``tmp_path``, which is what keeps
the extractor honest about forms the real ``graph.py`` does not happen to use —
a renamed builder, a list-shaped ``path_map``, keyword arguments, the
``set_entry_point`` spelling. The second runs the extractor over the real
``harness/shared/langgraph/graph.py`` and pins what it recovers, because a
parser that passes its own fixtures and mis-reads the one file the repository
actually asserts over would be a test suite proving nothing.

Every fail-closed path gets its own case (R-GEA-4). That is deliberate
over-coverage of the error branches: an extractor's failure modes are exactly
where a vacuous pass comes from, so "it raised" is the assertion with the most
value per line here. ``test_topology_extraction_is_source_based`` (AC-GEA-11)
is the INV-2 half — it proves the extractor neither imports ``langgraph`` nor
changes its answer with the deselect environment set, which is what lets this
suite run unconditionally on every interpreter instead of behind a ``skipif``.
"""

from __future__ import annotations

import ast
import logging
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from harness.shared.graph_topology import (
    END_SENTINEL,
    START_SENTINEL,
    Topology,
    TopologyExtractionError,
    extract_topology,
)
from harness.shared.tests._helpers import REPO

GRAPH_SOURCE = REPO / "harness" / "shared" / "langgraph" / "graph.py"
EXTRACTOR_SOURCE = REPO / "harness" / "shared" / "graph_topology.py"

#: A miniature of ``graph.py``'s shape: a sentinel entry edge, a conditional
#: fan-out whose map mixes a string key with an ``END`` name, a terminal edge,
#: and a registered node nothing points at. ``builder.compile()`` is present so
#: the "ignore builder methods that are not topology" path is exercised by the
#: fixture every other test builds on rather than by a special case.
CANONICAL_SOURCE = """
    from langgraph.graph import END, START, StateGraph


    def build():
        builder = StateGraph(dict)
        builder.add_node("alpha", alpha_node)
        builder.add_node("beta", beta_node)
        builder.add_node("orphan", orphan_node)
        builder.add_edge(START, "alpha")
        builder.add_conditional_edges("alpha", route, {"beta": "beta", END: END})
        builder.add_edge("beta", END)
        return builder.compile()
"""


def write_source(tmp_path: Path, source: str, name: str = "graph_module.py") -> Path:
    """Write a dedented snippet to ``tmp_path`` and return its path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


@pytest.fixture
def canonical(tmp_path: Path) -> Topology:
    return extract_topology(write_source(tmp_path, CANONICAL_SOURCE))


class TestExtraction:
    """What the parser recovers from source it can read."""

    def test_nodes_are_recovered_in_declaration_order(self, canonical: Topology) -> None:
        assert canonical.nodes == ("alpha", "beta", "orphan")

    def test_edges_include_every_conditional_branch(self, canonical: Topology) -> None:
        assert canonical.edges == (
            (START_SENTINEL, "alpha"),
            ("alpha", "beta"),
            ("alpha", END_SENTINEL),
            ("beta", END_SENTINEL),
        )

    def test_the_builder_variable_is_discovered_not_assumed(self, tmp_path: Path) -> None:
        """A rename is a refactor with no behavioural content; it must not empty the graph."""
        renamed = CANONICAL_SOURCE.replace("builder", "state_graph_under_construction")
        topology = extract_topology(write_source(tmp_path, renamed))
        assert topology.builder_name == "state_graph_under_construction"
        assert topology.nodes == ("alpha", "beta", "orphan")

    def test_sentinels_resolve_from_names_attributes_and_literals(self, tmp_path: Path) -> None:
        """``START``, ``constants.END`` and ``"__end__"`` all name the same nodes."""
        source = """
            from langgraph import constants
            from langgraph.graph import START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_edge(START, "alpha")
                builder.add_conditional_edges("alpha", route, {constants.END: constants.END, "x": "__end__"})
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.edges == (
            (START_SENTINEL, "alpha"),
            ("alpha", END_SENTINEL),
            ("alpha", END_SENTINEL),
        )

    def test_keyword_arguments_are_read_like_positional_ones(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node(node="alpha")
                builder.add_edge(start_key=START, end_key="alpha")
                builder.add_conditional_edges("alpha", route, path_map={"done": END})
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.nodes == ("alpha",)
        assert topology.edges == ((START_SENTINEL, "alpha"), ("alpha", END_SENTINEL))

    def test_a_list_path_map_names_its_own_branches(self, tmp_path: Path) -> None:
        """LangGraph's shorthand for a map whose keys and values coincide."""
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_node("beta", beta_node)
                builder.add_conditional_edges("alpha", route, ["beta"])
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.edges == (("alpha", "beta"),)

    def test_entry_and_finish_points_are_edges_to_the_sentinels(self, tmp_path: Path) -> None:
        """The pre-``START`` spelling still declares topology, so it must not be dropped."""
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.set_entry_point("alpha")
                builder.set_finish_point("alpha")
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.edges == ((START_SENTINEL, "alpha"), ("alpha", END_SENTINEL))

    def test_calls_on_anything_but_the_builder_are_ignored(self, tmp_path: Path) -> None:
        """A same-named method on another object is not this graph's topology."""
        source = """
            from langgraph.graph import END, START, StateGraph


            def build(other):
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                other.add_node("not_ours", node)
                self.builder.add_edge("not_ours", END)
                print("add_edge")
                builder.add_edge(START, "alpha")
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.nodes == ("alpha",)
        assert topology.edges == ((START_SENTINEL, "alpha"),)

    def test_declaration_order_survives_nesting(self, tmp_path: Path) -> None:
        """``ast.walk`` is breadth-first; the recovered order is source order anyway."""
        source = """
            from langgraph.graph import END, START, StateGraph


            def build(flag):
                builder = StateGraph(dict)
                if flag:
                    builder.add_node("alpha", alpha_node)
                builder.add_node("beta", beta_node)
                builder.add_edge(START, "alpha")
                builder.add_edge("alpha", END)
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.nodes == ("alpha", "beta")

    def test_debug_logging_names_the_builder_and_the_counts(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The log line is the only account of what was read when an assertion fails."""
        with caplog.at_level(logging.DEBUG, logger="harness.shared.graph_topology"):
            extract_topology(write_source(tmp_path, CANONICAL_SOURCE))
        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "builder variable 'builder' discovered" in messages
        assert "3 node(s) and 4 edge(s)" in messages
        assert "conditional branch alpha --[beta]--> beta" in messages


class TestQueries:
    """The graph helpers, over a topology whose shape the fixture fixes."""

    def test_successors_and_predecessors(self, canonical: Topology) -> None:
        assert canonical.successors("alpha") == ("beta", END_SENTINEL)
        assert canonical.predecessors(END_SENTINEL) == ("alpha", "beta")
        assert canonical.successors("orphan") == ()

    def test_reachable_from_the_entry_sentinel_excludes_the_orphan(self, canonical: Topology) -> None:
        assert canonical.reachable_from(START_SENTINEL) == frozenset({"alpha", "beta", END_SENTINEL})

    def test_nodes_without_edges_finds_only_the_orphan(self, canonical: Topology) -> None:
        assert canonical.nodes_without_edges() == ("orphan",)

    def test_path_between_returns_the_witness(self, canonical: Topology) -> None:
        assert canonical.path_between(START_SENTINEL, END_SENTINEL) == [START_SENTINEL, "alpha", END_SENTINEL]

    def test_path_between_returns_none_when_there_is_no_route(self, canonical: Topology) -> None:
        assert canonical.path_between(START_SENTINEL, "orphan") is None
        assert canonical.path_between("beta", "alpha") is None

    def test_avoiding_a_node_removes_the_routes_through_it(self, canonical: Topology) -> None:
        """The primitive a gate check needs: delete the gate, ask if a path remains."""
        assert canonical.path_between(START_SENTINEL, "beta") == [START_SENTINEL, "alpha", "beta"]
        assert canonical.path_between(START_SENTINEL, "beta", avoiding=frozenset({"alpha"})) is None

    def test_avoiding_an_endpoint_answers_none(self, canonical: Topology) -> None:
        """Asking for a route that avoids X reads the same at either end."""
        assert canonical.path_between(START_SENTINEL, "beta", avoiding=frozenset({"beta"})) is None
        assert canonical.path_between(START_SENTINEL, "beta", avoiding=frozenset({START_SENTINEL})) is None

    def test_a_node_reaches_itself_by_the_zero_length_path(self, canonical: Topology) -> None:
        assert canonical.path_between("alpha", "alpha") == ["alpha"]

    def test_a_cycle_terminates_and_reports_the_shortest_path(self, tmp_path: Path) -> None:
        """``clarify → plan_gate → clarify`` is a real cycle in ``graph.py``."""
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("gate", gate_node)
                builder.add_node("clarify", clarify_node)
                builder.add_node("done", done_node)
                builder.add_edge(START, "gate")
                builder.add_edge("gate", "clarify")
                builder.add_edge("clarify", "gate")
                builder.add_edge("gate", "done")
                builder.add_edge("done", END)
        """
        topology = extract_topology(write_source(tmp_path, source))
        assert topology.reachable_from("gate") == frozenset({"gate", "clarify", "done", END_SENTINEL})
        assert topology.path_between(START_SENTINEL, "done") == [START_SENTINEL, "gate", "done"]


class TestFailsClosed:
    """Every way the extractor can fail to read a graph raises (R-GEA-4).

    None of these may return an empty ``Topology``: an empty node set makes
    "this node has no incoming edge" true of a node that no longer exists, and
    an empty edge set makes every reachability property true of nothing.
    """

    def test_a_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TopologyExtractionError, match="cannot be read"):
            extract_topology(tmp_path / "absent.py")

    def test_unparseable_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TopologyExtractionError, match="cannot be parsed"):
            extract_topology(write_source(tmp_path, "def build(:\n"))

    def test_source_with_no_state_graph_assignment_raises(self, tmp_path: Path) -> None:
        source = """
            def build(factories):
                builder = factories["state_graph"](dict)
                graphs["other"] = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
        """
        with pytest.raises(TopologyExtractionError, match="no assignment of a StateGraph"):
            extract_topology(write_source(tmp_path, source))

    def test_a_builder_with_no_nodes_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_edge(START, "alpha")
        """
        with pytest.raises(TopologyExtractionError, match="no add_node call"):
            extract_topology(write_source(tmp_path, source))

    def test_a_builder_with_no_edges_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                return builder.compile()
        """
        with pytest.raises(TopologyExtractionError, match="empty edge set"):
            extract_topology(write_source(tmp_path, source))

    def test_a_node_name_that_is_not_a_literal_raises(self, tmp_path: Path) -> None:
        """Dropping the declaration would leave a plausible-looking partial graph."""
        source = """
            from langgraph.graph import StateGraph


            def build(name):
                builder = StateGraph(dict)
                builder.add_node(name, alpha_node)
        """
        with pytest.raises(TopologyExtractionError, match="add_node name"):
            extract_topology(write_source(tmp_path, source))

    def test_add_node_without_arguments_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node()
        """
        with pytest.raises(TopologyExtractionError, match="no such argument"):
            extract_topology(write_source(tmp_path, source))

    def test_an_unresolvable_edge_target_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import START, StateGraph


            def build(target):
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_edge(START, target)
        """
        with pytest.raises(TopologyExtractionError, match="add_edge target"):
            extract_topology(write_source(tmp_path, source))

    def test_conditional_edges_without_a_path_map_raises(self, tmp_path: Path) -> None:
        """Its destinations are whatever the router returns; no parse can decide them."""
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_conditional_edges("alpha", route)
        """
        with pytest.raises(TopologyExtractionError, match="without a statically readable path_map"):
            extract_topology(write_source(tmp_path, source))

    def test_a_path_map_built_by_unpacking_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import StateGraph


            def build(extra):
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_conditional_edges("alpha", route, {**extra})
        """
        with pytest.raises(TopologyExtractionError, match=r"\*\* unpacking"):
            extract_topology(write_source(tmp_path, source))

    def test_a_path_map_destination_that_is_not_a_literal_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import StateGraph


            def build(destination):
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_conditional_edges("alpha", route, {"next": destination})
        """
        with pytest.raises(TopologyExtractionError, match="conditional branch destination"):
            extract_topology(write_source(tmp_path, source))


def expected_node_count() -> int:
    """``EXPECTED_NODE_COUNT`` read out of ``graph.py``'s source, not imported.

    Importing ``harness.shared.langgraph.graph`` to read the constant would put
    this suite back behind the optional ``langgraph`` dependency the extractor
    exists to avoid — the module imports ``langchain_core`` and its own node
    package at import time. Parsing keeps the whole file source-based, which is
    the property AC-GEA-11 asserts.
    """
    tree = ast.parse(GRAPH_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "EXPECTED_NODE_COUNT":
                # `ast.Constant.value` is `Any`-shaped (str | bytes | int | ... | None),
                # so `int(...)` on it does not typecheck and, worse, would coerce a
                # constant that had drifted to some other literal instead of saying so.
                # `bool` is excluded because it is a subclass of `int` and a node count
                # of `True` is drift, not a count -- the same guard `changelog_section_cap`
                # applies to a policy value.
                value = node.value.value
                if isinstance(value, bool) or not isinstance(value, int):
                    raise AssertionError(f"{GRAPH_SOURCE} declares EXPECTED_NODE_COUNT as {value!r}, not an int")
                return value
    raise AssertionError(f"{GRAPH_SOURCE} no longer declares EXPECTED_NODE_COUNT")


@pytest.fixture(scope="module")
def real_graph() -> Topology:
    return extract_topology(GRAPH_SOURCE)


class TestTheRealGraph:
    """The extractor against ``harness/shared/langgraph/graph.py`` itself."""

    def test_it_finds_exactly_the_nodes_graph_py_declares(self, real_graph: Topology) -> None:
        assert set(real_graph.nodes) == {
            "planner",
            "shadow_planner",
            "plan_gate",
            "clarify",
            "implementer",
            "peer_reviewer",
            "security_reviewer",
            "test_eval",
            "quality_gate",
            "escalate",
        }

    def test_the_node_count_matches_the_constant_graph_py_publishes(self, real_graph: Topology) -> None:
        """``EXPECTED_NODE_COUNT`` is graph.py's own claim; the parse is the check of it."""
        assert len(real_graph.nodes) == expected_node_count()
        assert len(set(real_graph.nodes)) == len(real_graph.nodes), "a node is declared twice"

    def test_the_documented_spine_is_present(self, real_graph: Topology) -> None:
        """The topology the module docstring draws, edge by edge."""
        for edge in (
            (START_SENTINEL, "planner"),
            ("planner", "shadow_planner"),
            ("shadow_planner", "plan_gate"),
            ("plan_gate", "implementer"),
            ("plan_gate", "clarify"),
            ("clarify", "plan_gate"),
            ("implementer", "test_eval"),
            ("test_eval", "quality_gate"),
            ("quality_gate", END_SENTINEL),
            ("escalate", END_SENTINEL),
        ):
            assert edge in real_graph.edges, f"{edge} is gone from graph.py"

    def test_the_run_starts_at_the_entry_sentinel_and_can_reach_the_exit(self, real_graph: Topology) -> None:
        assert real_graph.entry_sentinel == START_SENTINEL
        assert real_graph.exit_sentinel == END_SENTINEL
        assert real_graph.predecessors(START_SENTINEL) == ()
        assert real_graph.path_between(START_SENTINEL, END_SENTINEL) is not None

    def test_the_write_capable_node_is_only_reached_through_the_plan_gate(self, real_graph: Topology) -> None:
        """DEC-052's fix, expressed as reachability rather than as a routing unit test.

        ``implementer`` is the write-capable node; ``_route_plan_gate`` checks
        for a blocking error *before* the branch that reaches it. Deleting
        ``plan_gate`` from the graph must leave no other way in, or that check
        guards one route among several.
        """
        assert real_graph.path_between(START_SENTINEL, "implementer") is not None
        assert real_graph.path_between(START_SENTINEL, "implementer", avoiding=frozenset({"plan_gate"})) is None


def test_topology_extraction_is_source_based(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-GEA-11: the answer does not depend on ``langgraph`` being importable.

    Three claims, because the acceptance criterion is really about INV-2: a
    check whose result depends on an optional import is a check that has to be
    skipped somewhere, and a skipped check reports nothing while looking like a
    pass.

    1. The extractor's own source imports nothing from ``langgraph`` — the
       structural reason no ``skipif`` can ever be needed.
    2. The recovered node and edge sets are identical with the deselect
       environment variable set, and with ``import langgraph`` forced to fail.
    3. Renaming the builder binding raises rather than reporting an empty
       topology, so the "no ``langgraph``" path cannot degrade into a silent
       pass either (R-GEA-4).
    """
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(EXTRACTOR_SOURCE.read_text(encoding="utf-8")))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    imported |= {
        node.module.split(".")[0]
        for node in ast.walk(ast.parse(EXTRACTOR_SOURCE.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "langgraph" not in imported, (
        "graph_topology.py imports langgraph; a compiled-graph check needs a skipif on the optional extra, "
        "which INV-2 forbids (R-GEA-6c)"
    )

    baseline = extract_topology(GRAPH_SOURCE)
    monkeypatch.setenv("MANGO_CI_DESELECT_LANGGRAPH", "1")
    # ``None`` in ``sys.modules`` makes ``import langgraph`` raise ImportError
    # even on a leg where the extra *is* installed, so this half of the
    # assertion is not satisfied merely by the library being absent here. The
    # cast says that to the type checker, which types the mapping as
    # ``str -> ModuleType``.
    monkeypatch.setitem(sys.modules, "langgraph", cast(ModuleType, None))
    with pytest.raises(ImportError):
        import langgraph  # noqa: F401
    deselected = extract_topology(GRAPH_SOURCE)
    assert (deselected.nodes, deselected.edges) == (baseline.nodes, baseline.edges)

    unrecognisable = GRAPH_SOURCE.read_text(encoding="utf-8").replace(
        "builder = StateGraph(MangoState)", "container = _make_builder(MangoState)"
    )
    assert "container = _make_builder" in unrecognisable, "graph.py no longer spells its builder assignment that way"
    with pytest.raises(TopologyExtractionError, match="no assignment of a StateGraph"):
        extract_topology(write_source(tmp_path, unrecognisable, name="renamed_graph.py"))
