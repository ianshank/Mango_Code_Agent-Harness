"""Every way the extractor refuses a file, and the proof it reads only source.

Sibling of ``test_graph_topology.py``, split from it when ``graph_topology``
split into a graph half and a ``graph_topology_source`` half. That file keeps
what the parser *recovers*; this one keeps what it *refuses* — one case per
fail-closed path — plus the AC-GEA-11 proof that the answer never depends on
``langgraph`` being importable.

The refusals get deliberate over-coverage (R-GEA-4). An extractor's failure
modes are exactly where a vacuous pass comes from: a check that inspected
nothing and a check that found nothing wrong are the same green line in a
summary, so "it raised, with this message" is the assertion with the most value
per line here. Each case goes through ``extract_topology`` rather than the
helper it exercises, because the refusal only matters if it reaches the caller.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from harness.shared.graph_topology import TopologyExtractionError, extract_topology
from harness.shared.tests._helpers import REPO
from harness.shared.tests.test_graph_topology import GRAPH_SOURCE, write_source

#: Both halves of the extractor. ``graph_topology`` delegates every ``ast``
#: decision to ``graph_topology_source``, so an import of ``langgraph`` in
#: either one would put the check back behind the optional extra that R-GEA-6c
#: exists to avoid — asserting over only the half that used to hold the parser
#: would be a check whose input set had quietly shrunk.
EXTRACTOR_SOURCES = (
    REPO / "harness" / "shared" / "graph_topology.py",
    REPO / "harness" / "shared" / "graph_topology_source.py",
)


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

    def test_two_builders_in_one_module_raise(self, tmp_path: Path) -> None:
        """Two graphs are two graphs; the first ``StateGraph(...)`` is not evidence about both.

        Taking the first assignment's target and then collecting every call on
        that bare name across the module merged two same-named builders into one
        topology carrying both node sets, and returned the first graph alone
        when the second was spelled differently -- each a plausible, non-empty
        result no emptiness guard can reject, which is the exact shape R-GEA-4
        forbids. The refusal names the file and both builders, because a reader
        who cannot see which two graphs collided cannot act on it.
        """
        for second in ("builder", "other"):
            source = f"""
                from langgraph.graph import START, StateGraph


                def build_one():
                    builder = StateGraph(dict)
                    builder.add_node("one", one_node)
                    builder.add_edge(START, "one")


                def build_two():
                    {second} = StateGraph(dict)
                    {second}.add_node("two", two_node)
                    {second}.add_edge(START, "two")
            """
            path = write_source(tmp_path, source, name=f"two_{second}.py")
            expected = (
                rf"found 2 StateGraph builders \('builder' at line \d+, {second!r} at line \d+\); "
                r"refusing to merge ambiguous lexical scopes"
            )
            with pytest.raises(TopologyExtractionError, match=expected) as raised:
                extract_topology(path)
            assert str(path) in str(raised.value), f"the {second} refusal does not name the file it refused"

    def test_a_builder_call_from_a_nested_scope_raises(self, tmp_path: Path) -> None:
        """The one attribution a single module's source cannot make.

        A nested ``def`` may have been handed the builder above it, in which
        case its calls are declarations that must be read, or it may rebind the
        name to something else entirely, in which case they must not be. Both
        wrong answers are the silent kind -- a dropped declaration or an
        imported one -- and telling them apart needs the call graph. So it
        raises and names the line. A nested scope that never mentions the name
        is not ambiguous at all, and is passed over without comment.
        """
        harmless = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)

                def label(node):
                    return node.upper()

                builder.add_node("alpha", alpha_node)
                builder.add_edge(START, "alpha")
                builder.add_edge("alpha", END)
        """
        topology = extract_topology(write_source(tmp_path, harmless, name="harmless.py"))
        assert topology.nodes == ("alpha",), "a nested scope that never names the builder is not a refusal"

        ambiguous = harmless.replace("return node.upper()", 'builder.add_node("ghost", ghost_node)')
        with pytest.raises(TopologyExtractionError, match="scope nested in the one that binds the builder"):
            extract_topology(write_source(tmp_path, ambiguous, name="ambiguous.py"))

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

    def test_an_unmodelled_builder_method_raises(self, tmp_path: Path) -> None:
        """The general shape: a topology-declaring call this module does not read.

        ``set_conditional_entry_point`` declares an edge from the entry sentinel
        and is in neither the modelled set nor the known-inert one. Skipping it
        — what an unknown method used to get — would drop that edge and return a
        graph in which the entry reaches nothing, with nothing about the result
        looking wrong. An allow-list is the only shape that fails closed here; a
        skip-list's missing entry is by definition the one nobody wrote down.
        """
        source = """
            from langgraph.graph import END, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("alpha", alpha_node)
                builder.add_edge("alpha", END)
                builder.set_conditional_entry_point(route, {"alpha": "alpha"})
        """
        with pytest.raises(TopologyExtractionError, match="'set_conditional_entry_point' is not modelled"):
            extract_topology(write_source(tmp_path, source))

    def test_a_sequence_of_bare_callables_raises(self, tmp_path: Path) -> None:
        """LangGraph names such a node from ``__name__`` at runtime.

        A decorator or a ``functools.partial`` makes that anything, so the name
        is not decidable from this module's source — the same rule an
        unresolvable ``add_node`` argument already follows.
        """
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_sequence([beta_node, gamma_node])
        """
        with pytest.raises(TopologyExtractionError, match="add_sequence node name"):
            extract_topology(write_source(tmp_path, source))

    def test_a_sequence_that_is_not_a_literal_raises(self, tmp_path: Path) -> None:
        source = """
            from langgraph.graph import StateGraph


            def build(steps):
                builder = StateGraph(dict)
                builder.add_sequence(steps)
        """
        with pytest.raises(TopologyExtractionError, match="add_sequence was called without"):
            extract_topology(write_source(tmp_path, source))

    def test_an_empty_sequence_raises(self, tmp_path: Path) -> None:
        """LangGraph itself rejects it; extracting nothing from it would not."""
        source = """
            from langgraph.graph import StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_sequence([])
        """
        with pytest.raises(TopologyExtractionError, match="non-empty sequence"):
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


def test_topology_extraction_is_source_based(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-GEA-11: the answer does not depend on ``langgraph`` being importable.

    Three claims, because the acceptance criterion is really about INV-2: a
    check whose result depends on an optional import is a check that has to be
    skipped somewhere, and a skipped check reports nothing while looking like a
    pass.

    1. Neither half of the extractor imports anything from ``langgraph`` — the
       structural reason no ``skipif`` can ever be needed.
    2. The recovered node and edge sets are identical with the deselect
       environment variable set, and with ``import langgraph`` forced to fail.
    3. Renaming the builder binding raises rather than reporting an empty
       topology, so the "no ``langgraph``" path cannot degrade into a silent
       pass either (R-GEA-4).
    """
    for module in EXTRACTOR_SOURCES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        imported |= {
            node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "langgraph" not in imported, (
            f"{module.name} imports langgraph; a compiled-graph check needs a skipif on the optional extra, "
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
