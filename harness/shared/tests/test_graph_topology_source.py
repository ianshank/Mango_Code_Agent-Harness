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

``TestDanglingEndpoints`` is kept apart from ``TestFailsClosed`` because its
cases are a different *kind* of refusal. Every file in it parses, resolves and
models cleanly, and is refused only for what the assembled module says: its node
set and its edge set disagree. The per-call refusals above can each be decided
where the offending call is read, and the two emptiness guards decide each half
against nothing — a graph whose halves are both non-empty and inconsistent
passes all of them, which is why that class exists at all.
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


class TestDanglingEndpoints:
    """An edge endpoint no ``add_node`` call declares raises (R-GEA-4).

    The refusal the two emptiness guards cannot reach, and the only one this
    module decides over the whole file rather than one call. Each case below is
    a *readable* file — every argument resolves, every method is modelled, both
    halves come back non-empty — whose node set and edge set nonetheless
    disagree, which is the plausible partial answer no count can catch.
    """

    def test_an_edge_target_that_no_add_node_declares_raises(self, tmp_path: Path) -> None:
        """The reported defect: a typo in one edge used to read as a graph.

        This source returned ``nodes=('real',)`` with ``edges=(('__start__',
        'typo'), ('real', '__end__'))``. Nothing about that looks wrong, and it
        is not the graph the source describes: ``reachable_from('__start__')``
        reports ``'typo'``, a node no ``add_node`` call registers, so a
        reachability property is answered about a node that does not exist while
        the node the author meant is unreachable. The message assertions are
        part of the fix rather than decoration -- a refusal that does not say
        which endpoint of which edge is wrong leaves the reader to diff the
        graph by hand.
        """
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("real", real_node)
                builder.add_edge(START, "typo")
                builder.add_edge("real", END)
        """
        path = write_source(tmp_path, source)
        with pytest.raises(TopologyExtractionError) as raised:
            extract_topology(path)

        message = str(raised.value)
        assert str(path) in message, "the refusal does not name the file it refused"
        assert "'typo'" in message, "the refusal does not name the offending endpoint"
        assert "('__start__', 'typo')" in message, "the refusal does not name the edge the endpoint came from"
        # Read back out of the file rather than written down here, so the
        # assertion keeps pointing at the offending call if the fixture moves.
        lines = path.read_text(encoding="utf-8").splitlines()
        offending = lines.index('    builder.add_edge(START, "typo")') + 1
        assert f"add_edge declares at line {offending}" in message, (
            f"the refusal does not locate the call to fix (line {offending}): {message}"
        )

    def test_an_edge_source_that_no_add_node_declares_raises(self, tmp_path: Path) -> None:
        """Both ends of an edge are endpoints; only the target is the obvious one.

        A rule checking targets alone leaves ``add_edge("ghost", END)`` as a
        supported way to attach the exit sentinel to a node that was never
        registered, which is the same inconsistency wearing the other end.
        """
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("real", real_node)
                builder.add_edge(START, "real")
                builder.add_edge("ghost", END)
        """
        with pytest.raises(TopologyExtractionError, match="'ghost' as the source of the edge"):
            extract_topology(write_source(tmp_path, source))

    def test_a_conditional_branch_destination_that_no_add_node_declares_raises(self, tmp_path: Path) -> None:
        """A fan-out declares one edge per branch, and every one of them has endpoints.

        Not an edge case in this repository: ``graph.py`` declares six of its
        thirteen edges through two ``add_conditional_edges`` calls, so a rule
        that read only ``add_edge`` would leave the majority of the real graph's
        edges as the place a typo still passes.
        """
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("real", real_node)
                builder.add_edge(START, "real")
                builder.add_conditional_edges("real", route, {"done": END, "again": "typo"})
        """
        with pytest.raises(TopologyExtractionError, match="'typo' as the target of the edge"):
            extract_topology(write_source(tmp_path, source))

    def test_an_entry_or_finish_point_naming_no_declared_node_raises(self, tmp_path: Path) -> None:
        """The pre-sentinel spellings declare edges, so they carry endpoints too.

        ``set_entry_point("typo")`` is ``add_edge(START, "typo")`` under an older
        name. A rule attached to ``add_edge`` rather than to the collected edge
        list would leave both spellings as ways to write a dangling endpoint and
        keep the extractor green — the shape ``_collect_call``'s allow-list
        already exists to refuse.
        """
        for method, side in (("set_entry_point", "target"), ("set_finish_point", "source")):
            source = f"""
                from langgraph.graph import END, START, StateGraph


                def build():
                    builder = StateGraph(dict)
                    builder.add_node("real", real_node)
                    builder.add_edge(START, "real")
                    builder.add_edge("real", END)
                    builder.{method}("typo")
            """
            with pytest.raises(TopologyExtractionError, match=f"'typo' as the {side} of the edge"):
                extract_topology(write_source(tmp_path, source, name=f"{method}.py"))

    def test_an_edge_against_a_name_add_sequence_did_not_declare_raises(self, tmp_path: Path) -> None:
        """``add_sequence``'s own chain cannot dangle; an edge written against it can.

        Every element of the list is an ``add_node``, so each chain edge names
        endpoints the same call has just declared — the one edge-producing shape
        the rule is vacuous over, and worth saying out loud so nobody adds a
        redundant per-element check. What it is emphatically not vacuous over is
        the ordinary edge a reader writes against the chain and misspells, which
        is where the mistake actually lands.
        """
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_sequence([("beta", beta_node), ("gamma", gamma_node)])
                builder.add_edge(START, "beta")
                builder.add_edge("gama", END)
        """
        with pytest.raises(TopologyExtractionError, match="'gama' as the source of the edge"):
            extract_topology(write_source(tmp_path, source))

    def test_every_dangling_endpoint_is_named_not_only_the_first(self, tmp_path: Path) -> None:
        """One rename strands several edges, and a reader should see them in one run.

        The count is part of the claim. A refusal that names the first offender
        and stops tells the truth one third at a time: the reader fixes what it
        mentioned, re-runs, and meets the next one — which is the cost that gets
        a check routed around rather than used.
        """
        source = """
            from langgraph.graph import END, START, StateGraph


            def build():
                builder = StateGraph(dict)
                builder.add_node("kept", kept_node)
                builder.add_edge(START, "renamed")
                builder.add_edge("renamed", "kept")
                builder.add_edge("kept", END)
        """
        with pytest.raises(TopologyExtractionError) as raised:
            extract_topology(write_source(tmp_path, source))

        message = str(raised.value)
        assert "declares 2 edge endpoint(s)" in message, message
        assert "'renamed' as the target of the edge ('__start__', 'renamed')" in message, message
        assert "'renamed' as the source of the edge ('renamed', 'kept')" in message, message
        assert "the declared nodes are ('kept',)" in message, (
            f"the refusal does not quote the node set the endpoint was checked against: {message}"
        )


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
