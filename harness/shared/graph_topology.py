"""Recover a LangGraph ``StateGraph`` topology from module *source text*.

This module is the implementation half of R-GEA-6b: the assertion that
``peer_reviewer`` and ``security_reviewer`` are edgeless, and that DEC-052
records them so, cannot be written without an edge set to assert over, and the
edge set has to come from somewhere that does not import ``langgraph``. That is
this module. The assertion itself lives in
``harness/shared/tests/test_graph_topology_parked.py``, because per D-5 of
``docs/specs/graph-engineering-adoption.md`` a pure function over repository
state belongs on the test surface rather than behind a new CI target, and per
R-GEA-6 the gate stays parked with DEC-053 while the check does not.

It owns the *graph*: the ``Topology`` value object and its queries, what one
builder call declares, and the ``extract_topology`` entry point. Everything
about reading source — which builder a module binds, which calls are its, and
what node name an expression denotes — is ``graph_topology_source``, which this
module imports and re-exports from. Those two questions were one 528-line
module until the fail-closed scoping rule needed room the size budget did not
have; splitting them was the alternative to trimming the argument out of the
file, which is the move this repository keeps regretting.

Why this reads source rather than a compiled graph
--------------------------------------------------

The obvious implementation of a topology check is to call ``build_graph()``
and read ``compiled.nodes`` / ``compiled.builder.edges``. That implementation
cannot be written here without breaking an invariant. ``langgraph`` is an
optional extra (``pyproject.toml`` ``[project.optional-dependencies]``), so a
compiled-graph check has to be guarded by ``skipif`` on the import — and INV-2
forbids a skip that has not been approved by a decision record. A guarded check
is not a weaker check; it is a check that reports nothing on the leg where the
guard fires, which is indistinguishable from a passing one in a summary line.
R-GEA-6c states the rule this module implements: *derive nodes and edges from
module source via ``ast`` rather than from a compiled graph object, so the check
needs no ``skipif`` on an optional import and cannot become a skip in search of
a waiver.* Accordingly neither this module nor ``graph_topology_source``
imports anything from ``langgraph``, and
``test_topology_extraction_is_source_based`` asserts that neither ever will.

The second reason is that the topology under inspection is *parked*. DEC-053
accepted moving ``harness/shared/langgraph/`` under
``harness/shared/experimental/``, and its Phase E is blocked behind NS-2, so the
package sits at its original path for an indefinite period with the defect
DEC-052 recorded — ``peer_reviewer`` and ``security_reviewer`` registered with
no incoming edge, so the ``findings`` channel is empty on every run — live in
the tree. A source-level extractor can pin that state from the ordinary pytest
run (D-5's enforcement-surface rule: a pure function over repository state is a
test, not a gate) without adding a required check, a ``CONTRACT.md`` row, or a
protected-path attestation to a subsystem with a named sunset.

Why every failure raises instead of returning an empty topology
--------------------------------------------------------------

An extractor that returns ``Topology(nodes=(), edges=())`` when it does not
understand the source makes every downstream property *vacuously true*:
"``peer_reviewer`` has no incoming edge" holds trivially over a graph with no
edges, and "no write-capable node is reachable without a gate" holds trivially
over a graph with no nodes. That is the exact defect class this repository
keeps finding in its own gates — a check that passes because it inspected
nothing (DEC-024's shape; `check_traceability.py` reading 6 requirement IDs out
of 412). R-GEA-4 makes the rule explicit: *a derived node set or edge set that
comes back empty is a broken extractor, not a satisfied property, and MUST
raise rather than pass.* So `TopologyExtractionError` is raised for an
unreadable or unparseable file, for source with no ``StateGraph(...)``
assignment, for source that assigns more than one, for a call on the builder's
name from a scope nested inside the one that binds it, for source with no
``add_node`` call, for source with no edge, for any individual call whose
arguments this module cannot resolve to node names, and for any builder method
it does not model. The last two matter most: silently skipping one ``add_node``
whose argument is a variable, or one ``add_sequence`` whose whole chain this
module never read, drops nodes and edges from the graph while still returning a
plausible-looking topology -- worse than raising, because nothing about the
result would look wrong. ``graph_topology_source`` carries the same rule for
the facts it decides, and its docstring argues the builder-scoping half.
"""

from __future__ import annotations

import ast
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from harness.shared.graph_topology_source import (
    END_SENTINEL,
    START_SENTINEL,
    TopologyExtractionError,
    argument,
    branches,
    builder_calls,
    builder_variable,
    describe,
    parse_module,
    resolve,
)

logger = logging.getLogger(__name__)

#: ``StateGraph`` builder methods this module models. Every other method called
#: on the builder raises: see ``_collect_call`` for why an allow-list is the
#: only shape that fails closed here.
_ADD_NODE = "add_node"
_ADD_EDGE = "add_edge"
_ADD_CONDITIONAL_EDGES = "add_conditional_edges"
_ADD_SEQUENCE = "add_sequence"
_SET_ENTRY_POINT = "set_entry_point"
_SET_FINISH_POINT = "set_finish_point"

#: Builder methods that declare no topology, listed one at a time rather than
#: assumed: ``compile`` builds the runnable from what is already declared, so
#: reading it adds nothing and skipping it drops nothing. A method joins this
#: set only once a reader has decided it declares no node and no edge, which is
#: the whole difference between an allow-list and a skip-list.
_NO_TOPOLOGY = frozenset({"compile"})


@dataclass(frozen=True)
class Topology:
    """A directed graph recovered from one module's source text.

    ``nodes`` preserves declaration order and ``edges`` source order, so a
    failure message can quote the graph in the shape a reader will find it in
    the file. Frozen because callers assert over it: a helper that mutated the
    topology it was handed would make two assertions in the same test disagree
    about the same file.
    """

    source_path: Path
    builder_name: str
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    entry_sentinel: str = START_SENTINEL
    exit_sentinel: str = END_SENTINEL

    def successors(self, node: str) -> tuple[str, ...]:
        """Distinct destinations of edges leaving ``node``, in source order."""
        return tuple(dict.fromkeys(dst for src, dst in self.edges if src == node))

    def predecessors(self, node: str) -> tuple[str, ...]:
        """Distinct origins of edges entering ``node``, in source order."""
        return tuple(dict.fromkeys(src for src, dst in self.edges if dst == node))

    def reachable_from(self, node: str) -> frozenset[str]:
        """Every node reachable from ``node`` by one or more edges.

        ``node`` itself appears in the result only when a cycle returns to it,
        which is the definition a reachability property wants: asking whether a
        write-capable node is reachable from the entry sentinel must not be
        answered "yes" by the trivial zero-length path.
        """
        seen: set[str] = set()
        queue = deque(self.successors(node))
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self.successors(current))
        return frozenset(seen)

    def nodes_without_edges(self) -> tuple[str, ...]:
        """Declared nodes with neither an incoming nor an outgoing edge.

        This is the orphan-node query DEC-052's recorded defect is stated in:
        a node the graph registers and can never enter or leave, whose channel
        contributions are therefore empty on every run.
        """
        return tuple(node for node in self.nodes if not self.successors(node) and not self.predecessors(node))

    def path_between(
        self,
        src: str,
        dst: str,
        avoiding: frozenset[str] = frozenset(),
    ) -> list[str] | None:
        """A shortest path from ``src`` to ``dst``, or ``None`` if there is none.

        Returns the *witness* — the node names along the path, ``src`` first and
        ``dst`` last — rather than a boolean, because a reachability failure is
        only actionable when it names the route it found. ``avoiding`` removes
        nodes from the search, which is how "every path from the entry to a
        write-capable node traverses a gate" is decided: delete the gate and ask
        whether a path still exists; a returned witness is the counter-example
        and ``None`` is the proof.

        A node in ``avoiding`` is excluded even when it is ``src`` or ``dst``,
        so the question "can I get there without touching X" has the same answer
        whichever end X sits at. ``src == dst`` yields the zero-length path
        ``[src]``.
        """
        if src in avoiding or dst in avoiding:
            return None
        if src == dst:
            return [src]
        queue: deque[list[str]] = deque([[src]])
        seen = {src}
        while queue:
            path = queue.popleft()
            for following in self.successors(path[-1]):
                if following in seen or following in avoiding:
                    continue
                if following == dst:
                    return [*path, dst]
                seen.add(following)
                queue.append([*path, following])
        return None


def extract_topology(source_path: Path) -> Topology:
    """Parse ``source_path`` and return the ``StateGraph`` topology it declares.

    Raises ``TopologyExtractionError`` for anything it cannot read — see the
    module docstring for why an empty result is never returned in its place.
    """
    tree = parse_module(source_path)
    builder_name, scope = builder_variable(tree, source_path)
    nodes, edges = _collect_topology(scope, builder_name, source_path)
    if not nodes:
        raise TopologyExtractionError(
            f"{source_path}: builder {builder_name!r} has no add_node call; an empty node set is a broken "
            "extractor, not a graph with no nodes"
        )
    if not edges:
        raise TopologyExtractionError(
            f"{source_path}: builder {builder_name!r} declares {len(nodes)} node(s) and no edge; an empty edge "
            "set makes every reachability property vacuously true"
        )
    logger.debug(
        "graph_topology: %s declares %d node(s) and %d edge(s) through builder %r",
        source_path,
        len(nodes),
        len(edges),
        builder_name,
    )
    return Topology(
        source_path=source_path,
        builder_name=builder_name,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def _collect_topology(
    scope: ast.AST,
    builder_name: str,
    source_path: Path,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Every node and edge declared through ``builder_name`` inside ``scope``.

    ``scope`` is the body that binds the builder, not the whole tree, and the
    selection of calls belonging to it is ``builder_calls``' job rather than
    this one's: a bare name is only a builder inside the scope that binds it,
    and deciding that is a fact about source, not about graphs.
    """
    nodes: list[str] = []
    edges: list[tuple[str, str]] = []
    for call, method in builder_calls(scope, builder_name, source_path):
        _collect_call(call, method, source_path, nodes, edges)
    return nodes, edges


def _collect_call(
    call: ast.Call,
    method: str,
    source_path: Path,
    nodes: list[str],
    edges: list[tuple[str, str]],
) -> None:
    """Append whatever one builder call declares to ``nodes`` / ``edges``.

    **The defect this prevents is a topology-declaring call that is skipped.**
    An unmodelled method used to be ignored on the reasoning that "an unknown
    method is not evidence of an edge". It is evidence of a *declaration this
    module did not read*: ``add_sequence`` beside one ordinary edge returned a
    plausible non-empty topology missing every node and edge the sequence
    declared, leaving a reachability property over the result quietly wrong
    instead of loudly absent -- the partial result R-GEA-4 forbids, and the one
    shape no emptiness guard can catch. So the method set is an allow-list that
    raises on anything outside it. A skip-list cannot fail closed, because the
    entry needing to be added is the one nobody knew to write down:
    ``set_conditional_entry_point`` declares topology, is in neither set above,
    and now raises instead of vanishing.
    """
    if method == _ADD_NODE:
        nodes.append(resolve(argument(call, 0, "node"), source_path, call, "add_node name"))
    elif method == _ADD_EDGE:
        src = resolve(argument(call, 0, "start_key"), source_path, call, "add_edge source")
        dst = resolve(argument(call, 1, "end_key"), source_path, call, "add_edge target")
        edges.append((src, dst))
    elif method == _ADD_CONDITIONAL_EDGES:
        src = resolve(argument(call, 0, "source"), source_path, call, "add_conditional_edges source")
        for label, dst in branches(argument(call, 2, "path_map"), source_path, call):
            logger.debug("graph_topology: conditional branch %s --[%s]--> %s", src, label, dst)
            edges.append((src, dst))
    elif method == _ADD_SEQUENCE:
        _collect_sequence(call, source_path, nodes, edges)
    elif method == _SET_ENTRY_POINT:
        edges.append((START_SENTINEL, resolve(argument(call, 0, "key"), source_path, call, "set_entry_point")))
    elif method == _SET_FINISH_POINT:
        edges.append((resolve(argument(call, 0, "key"), source_path, call, "set_finish_point"), END_SENTINEL))
    elif method not in _NO_TOPOLOGY:
        raise TopologyExtractionError(
            f"{source_path}:{call.lineno}: builder method {method!r} is not modelled by this extractor; "
            "an unmodelled call that declares topology would be dropped from the result, leaving a graph "
            "that looks complete and is not"
        )


def _collect_sequence(call: ast.Call, source_path: Path, nodes: list[str], edges: list[tuple[str, str]]) -> None:
    """Expand ``add_sequence([...])`` into the nodes and chain edges it declares.

    Extracted rather than refused because the semantics are unambiguous: the
    method is ``add_node`` per element plus ``add_edge`` between consecutive
    ones, so reading it rewrites into two calls this module already models
    rather than inventing a notion of an edge. Refusing would have been safe
    but would fail on a graph nothing is wrong with, and a check that fires on
    correct source gets switched off. An element is either ``("name", node)``
    or a bare callable whose node name LangGraph takes from ``__name__`` at
    runtime -- which a decorator or a ``functools.partial`` can make anything.
    The second raises, on the rule an unresolvable ``add_node`` argument
    already follows: a name this module cannot decide is not one it may guess.
    """
    elements = argument(call, 0, "nodes")
    if not isinstance(elements, (ast.List, ast.Tuple)) or not elements.elts:
        raise TopologyExtractionError(
            f"{source_path}:{call.lineno}: add_sequence was called without a statically readable, non-empty "
            f"sequence (got {describe(elements)}); the chain it declares would be decided at runtime"
        )
    previous: str | None = None
    for element in elements.elts:
        # `(name, node)` is a 2-tuple and nothing else: LangGraph reads any
        # other element as the node itself and names it from the object.
        named = element.elts[0] if isinstance(element, ast.Tuple) and len(element.elts) == 2 else element
        name = resolve(named, source_path, call, "add_sequence node name")
        nodes.append(name)
        if previous is not None:
            logger.debug("graph_topology: sequence edge %s --> %s", previous, name)
            edges.append((previous, name))
        previous = name


__all__ = [
    "END_SENTINEL",
    "START_SENTINEL",
    "Topology",
    "TopologyExtractionError",
    "extract_topology",
]
