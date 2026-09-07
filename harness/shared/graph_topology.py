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
a waiver.* Accordingly this module imports **nothing** from ``langgraph``, and
``test_topology_extraction_is_source_based`` asserts that it never will.

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
assignment, for source with no ``add_node`` call, for source with no edge, for
any individual call whose arguments this module cannot resolve to node names,
and for any builder method it does not model. The last two matter most:
silently skipping one ``add_node`` whose argument is a variable, or one
``add_sequence`` whose whole chain this module never read, drops nodes and
edges from the graph while still returning a plausible-looking topology --
worse than raising, because nothing about the result would look wrong.

Why the builder variable is discovered rather than assumed
----------------------------------------------------------

``harness/shared/langgraph/graph.py`` happens to spell it ``builder``. Matching
that name literally would mean a rename — a refactor with no behavioural
content — silently reduces the extracted graph to nothing, and by the paragraph
above, silently satisfies every property asserted over it. The builder is
therefore found by *what it is* (the target of an assignment whose value is a
``StateGraph(...)`` call) rather than by what it is called.
"""

from __future__ import annotations

import ast
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: LangGraph's virtual entry and exit nodes. ``langgraph.constants`` defines
#: ``START = "__start__"`` and ``END = "__end__"``, and a compiled graph reports
#: its edges against those strings — so resolving the *names* to them here is
#: what makes a source-derived edge set comparable with a compiled one. The two
#: literals are duplicated from a library this module deliberately does not
#: import; ``graph.py``'s own ``except ImportError`` fallback duplicates them
#: for the same reason, and a test pins this module's values against the sets
#: the real graph produces.
START_SENTINEL = "__start__"
END_SENTINEL = "__end__"

#: Bare names that stand for a sentinel when they appear as an edge endpoint or
#: as a branch label. Both the ``from langgraph.graph import END`` spelling and
#: the attribute spelling (``constants.END``) resolve through this table.
_SENTINEL_NAMES = {"START": START_SENTINEL, "END": END_SENTINEL}

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


class TopologyExtractionError(RuntimeError):
    """The source could not be read as a ``StateGraph`` topology.

    Raised rather than returning a partial or empty ``Topology`` so that a
    broken extractor fails the caller instead of silently satisfying whatever
    property the caller was about to assert (R-GEA-4).
    """


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
    tree = _parse(source_path)
    builder_name = _builder_variable(tree, source_path)
    nodes, edges = _collect_topology(tree, builder_name, source_path)
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


def _parse(source_path: Path) -> ast.Module:
    """Read and parse ``source_path``, converting both failure modes to ours."""
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TopologyExtractionError(f"{source_path}: cannot be read: {exc}") from exc
    try:
        return ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        raise TopologyExtractionError(f"{source_path}: cannot be parsed: {exc}") from exc


def _builder_variable(tree: ast.Module, source_path: Path) -> str:
    """The name bound to a ``StateGraph(...)`` call, wherever it is assigned.

    Discovered rather than assumed: see the module docstring's last section for
    what hard-coding ``builder`` would cost.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _called_name(node.value.func) != "StateGraph":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                logger.debug(
                    "graph_topology: builder variable %r discovered at %s:%d",
                    target.id,
                    source_path,
                    node.lineno,
                )
                return target.id
    raise TopologyExtractionError(
        f"{source_path}: no assignment of a StateGraph(...) call was found, so there is no builder whose "
        "topology calls could be collected"
    )


def _called_name(func: ast.expr) -> str | None:
    """The trailing identifier of a call target: ``f`` and ``mod.f`` both give ``f``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _collect_topology(
    tree: ast.Module,
    builder_name: str,
    source_path: Path,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Every node and edge declared through ``builder_name`` in ``tree``.

    Sorted by source position rather than taken in ``ast.walk`` order: walk is
    breadth-first, so a call nested inside an ``if`` would be visited after
    shallower calls written below it and the recovered order would stop matching
    the file. Declaration order is not load-bearing for any graph property, but
    it is what a failure message quotes back to a reader.
    """
    nodes: list[str] = []
    edges: list[tuple[str, str]] = []
    calls: list[tuple[ast.Call, str]] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            continue
        if func.value.id != builder_name:
            continue
        calls.append((call, func.attr))
    calls.sort(key=lambda item: (item[0].lineno, item[0].col_offset))
    for call, method in calls:
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
        nodes.append(_resolve(_argument(call, 0, "node"), source_path, call, "add_node name"))
    elif method == _ADD_EDGE:
        src = _resolve(_argument(call, 0, "start_key"), source_path, call, "add_edge source")
        dst = _resolve(_argument(call, 1, "end_key"), source_path, call, "add_edge target")
        edges.append((src, dst))
    elif method == _ADD_CONDITIONAL_EDGES:
        src = _resolve(_argument(call, 0, "source"), source_path, call, "add_conditional_edges source")
        for label, dst in _branches(_argument(call, 2, "path_map"), source_path, call):
            logger.debug("graph_topology: conditional branch %s --[%s]--> %s", src, label, dst)
            edges.append((src, dst))
    elif method == _ADD_SEQUENCE:
        _collect_sequence(call, source_path, nodes, edges)
    elif method == _SET_ENTRY_POINT:
        edges.append((START_SENTINEL, _resolve(_argument(call, 0, "key"), source_path, call, "set_entry_point")))
    elif method == _SET_FINISH_POINT:
        edges.append((_resolve(_argument(call, 0, "key"), source_path, call, "set_finish_point"), END_SENTINEL))
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
    elements = _argument(call, 0, "nodes")
    if not isinstance(elements, (ast.List, ast.Tuple)) or not elements.elts:
        raise TopologyExtractionError(
            f"{source_path}:{call.lineno}: add_sequence was called without a statically readable, non-empty "
            f"sequence (got {_describe(elements)}); the chain it declares would be decided at runtime"
        )
    previous: str | None = None
    for element in elements.elts:
        # `(name, node)` is a 2-tuple and nothing else: LangGraph reads any
        # other element as the node itself and names it from the object.
        named = element.elts[0] if isinstance(element, ast.Tuple) and len(element.elts) == 2 else element
        name = _resolve(named, source_path, call, "add_sequence node name")
        nodes.append(name)
        if previous is not None:
            logger.debug("graph_topology: sequence edge %s --> %s", previous, name)
            edges.append((previous, name))
        previous = name


def _argument(call: ast.Call, index: int, keyword: str) -> ast.expr | None:
    """The positional argument at ``index``, else the keyword of that name."""
    if len(call.args) > index:
        return call.args[index]
    for passed in call.keywords:
        if passed.arg == keyword:
            return passed.value
    return None


def _resolve(expr: ast.expr | None, source_path: Path, call: ast.Call, role: str) -> str:
    """The node name ``expr`` denotes, raising when it denotes none statically.

    Accepts a string literal, a bare ``START`` / ``END`` name, and the attribute
    spelling of either. Anything else — a variable, an f-string, a call — is a
    node name this module cannot decide from one module's source, and it raises
    rather than dropping the edge, because a dropped edge is invisible in the
    result while a raise is not.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name) and expr.id in _SENTINEL_NAMES:
        return _SENTINEL_NAMES[expr.id]
    if isinstance(expr, ast.Attribute) and expr.attr in _SENTINEL_NAMES:
        return _SENTINEL_NAMES[expr.attr]
    raise TopologyExtractionError(
        f"{source_path}:{call.lineno}: cannot statically resolve the {role} to a node name "
        f"(got {_describe(expr)}); resolve it here rather than dropping the declaration"
    )


def _branches(mapping: ast.expr | None, source_path: Path, call: ast.Call) -> list[tuple[str, str]]:
    """``(branch label, destination node)`` for one ``add_conditional_edges`` map.

    A dict maps the router's return value to a node, and a list is LangGraph's
    shorthand for a map whose keys and values coincide. A conditional edge with
    *no* map is refused: the destinations are then whatever the router returns
    at runtime, which no single-module parse can decide, and accepting it would
    contribute zero edges for a call that plainly declares some.
    """
    if isinstance(mapping, ast.Dict):
        branches: list[tuple[str, str]] = []
        for key, value in zip(mapping.keys, mapping.values, strict=True):
            if key is None:
                raise TopologyExtractionError(
                    f"{source_path}:{call.lineno}: add_conditional_edges path_map uses ** unpacking, whose "
                    "branches cannot be read from this module alone"
                )
            branches.append(
                (
                    _resolve(key, source_path, call, "conditional branch label"),
                    _resolve(value, source_path, call, "conditional branch destination"),
                )
            )
        return branches
    if isinstance(mapping, (ast.List, ast.Tuple)):
        names = [_resolve(element, source_path, call, "conditional branch destination") for element in mapping.elts]
        return [(name, name) for name in names]
    raise TopologyExtractionError(
        f"{source_path}:{call.lineno}: add_conditional_edges was called without a statically readable path_map "
        f"(got {_describe(mapping)}); its destinations would be decided by the router at runtime"
    )


def _describe(expr: ast.expr | None) -> str:
    """A short, stable description of an unresolvable node for an error message."""
    if expr is None:
        return "no such argument"
    return type(expr).__name__


__all__ = [
    "END_SENTINEL",
    "START_SENTINEL",
    "Topology",
    "TopologyExtractionError",
    "extract_topology",
]
