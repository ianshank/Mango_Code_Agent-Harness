"""Facts read out of a module's *source text* for the ``StateGraph`` extractor.

The half of ``graph_topology`` that decides things about source and nothing
about graphs: which builder a module binds, where that builder's name means
anything, which calls belong to it, and what node name a given expression
denotes. It never decides what a call *declares* — ``graph_topology`` does
that, and imports this module to do it. The split is one-directional, so the
two halves can be read and reasoned about in that order.

``TopologyExtractionError`` lives here rather than beside ``Topology`` because
both halves raise it and an exception belongs at the base of the layer it is
raised from; ``graph_topology`` re-exports it, so every existing importer is
unaffected.

Why every undecidable case raises
---------------------------------

R-GEA-4: *a derived node set or edge set that comes back empty is a broken
extractor, not a satisfied property, and MUST raise rather than pass.* The
reason is that a partial result is invisible. An extractor that drops one
``add_node`` whose argument is a variable still returns a plausible, non-empty
topology, and every property asserted over it — "``peer_reviewer`` has no
incoming edge", "no write-capable node is reachable without a gate" — is then
answered from a graph missing pieces, with nothing about the answer looking
wrong. So each function below either returns a decided fact or raises: there is
no "best effort" return value in this module.

Why the builder is discovered, scoped, and required to be unique
----------------------------------------------------------------

``harness/shared/langgraph/graph.py`` happens to spell it ``builder``. Matching
that name literally would mean a rename — a refactor with no behavioural
content — silently reduces the extracted graph to nothing, and by the paragraph
above, silently satisfies every property asserted over it. The builder is
therefore found by *what it is* (the target of an assignment whose value is a
``StateGraph(...)`` call) rather than by what it is called.

Discovering it is not enough, because a *name* means something only inside the
scope that binds it. Taking the first ``StateGraph(...)`` assignment and then
collecting every call on that bare name across the whole module produced
exactly the partial results this module exists to refuse: two functions each
building their own graph, both spelling the builder ``builder``, came back as
one merged topology carrying both node sets, and a second builder under a
different name came back as the first graph alone with the second silently
dropped. Neither result looks wrong. So ``builder_variable`` returns the scope
along with the name, ``builder_calls`` reads only that scope, and a module that
assigns more than one ``StateGraph(...)`` raises instead of choosing: one graph
per module is a contract this extractor can keep, and picking between two is a
guess dressed as an answer.

Why a call from a nested scope is refused rather than attributed
----------------------------------------------------------------

Within the binding scope, a *nested* scope that mentions the bare name is the
one case this module genuinely cannot decide. ``def wire(builder): ...`` may be
handed the very builder above it, in which case its calls are declarations that
must be read; a method or helper that rebinds ``builder`` to something else
entirely reads identically at this level, and its calls must not be read.
Telling them apart needs the call graph, which one module's source does not
contain. Both wrong answers are the silent kind — a dropped declaration or an
imported one — so ``builder_calls`` raises and names the line instead. This is
the same rule ``resolve`` follows for a node name it cannot decide, and unlike
``add_sequence`` (whose meaning *is* decidable, and is therefore read rather
than refused) there is no reading here that is right by construction.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: LangGraph's virtual entry and exit nodes. ``langgraph.constants`` defines
#: ``START = "__start__"`` and ``END = "__end__"``, and a compiled graph reports
#: its edges against those strings — so resolving the *names* to them here is
#: what makes a source-derived edge set comparable with a compiled one. The two
#: literals are duplicated from a library this module deliberately does not
#: import; ``graph.py``'s own ``except ImportError`` fallback duplicates them
#: for the same reason, and a test pins these values against the sets the real
#: graph produces.
START_SENTINEL = "__start__"
END_SENTINEL = "__end__"

#: Bare names that stand for a sentinel when they appear as an edge endpoint or
#: as a branch label. Both the ``from langgraph.graph import END`` spelling and
#: the attribute spelling (``constants.END``) resolve through this table.
_SENTINEL_NAMES = {"START": START_SENTINEL, "END": END_SENTINEL}

#: Nodes that open a binding scope. The ``builder`` one function assigns is not
#: the ``builder`` the next one assigns, so a builder's calls are read out of
#: the body that binds it rather than out of the module. Comprehensions and
#: lambdas open scopes too and are absent deliberately: neither can contain the
#: assignment statement this module looks for, so neither can bind a builder.
_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

#: One ``name = StateGraph(...)`` site: the name it binds, the line it is on,
#: and the scope node whose subtree is that name's whole meaning.
_Binding = tuple[str, int, ast.AST]


class TopologyExtractionError(RuntimeError):
    """The source could not be read as a ``StateGraph`` topology.

    Raised rather than returning a partial or empty ``Topology`` so that a
    broken extractor fails the caller instead of silently satisfying whatever
    property the caller was about to assert (R-GEA-4).
    """


def parse_module(source_path: Path) -> ast.Module:
    """Read and parse ``source_path``, converting both failure modes to ours."""
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TopologyExtractionError(f"{source_path}: cannot be read: {exc}") from exc
    try:
        return ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        raise TopologyExtractionError(f"{source_path}: cannot be parsed: {exc}") from exc


def _builder_bindings(node: ast.AST, scope: ast.AST, found: list[_Binding]) -> list[_Binding]:
    """Every ``name = StateGraph(...)`` under ``node``, each tagged with its binding scope.

    Descends with the enclosing scope in hand rather than reaching for
    ``ast.walk``, which flattens the tree and so discards the one fact that
    tells two same-named builders apart.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Assign) and isinstance(child.value, ast.Call):
            if _called_name(child.value.func) == "StateGraph":
                found += [(t.id, child.lineno, scope) for t in child.targets if isinstance(t, ast.Name)]
        _builder_bindings(child, child if isinstance(child, _SCOPES) else scope, found)
    return found


def builder_variable(tree: ast.Module, source_path: Path) -> tuple[str, ast.AST]:
    """The one builder ``tree`` binds, and the scope its calls may be read from.

    Discovered rather than assumed, and refused rather than chosen: see the
    module docstring for what hard-coding ``builder`` would cost and why a
    module holding two builders raises instead of picking one. The refusal
    names both, because a reader who cannot see which two graphs collided has
    nothing to act on.
    """
    found = sorted(_builder_bindings(tree, tree, []), key=lambda binding: binding[1])
    if not found:
        raise TopologyExtractionError(
            f"{source_path}: no assignment of a StateGraph(...) call was found, so there is no builder whose "
            "topology calls could be collected"
        )
    if len(found) > 1:
        competing = ", ".join(f"{name!r} at line {lineno}" for name, lineno, _ in found)
        raise TopologyExtractionError(
            f"{source_path}: found {len(found)} StateGraph builders ({competing}); refusing to merge ambiguous "
            "lexical scopes -- one graph per module is the contract, and merging or dropping either looks whole"
        )
    name, lineno, scope = found[0]
    logger.debug("graph_topology: builder variable %r discovered at %s:%d", name, source_path, lineno)
    return name, scope


def _called_name(func: ast.expr) -> str | None:
    """The trailing identifier of a call target: ``f`` and ``mod.f`` both give ``f``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _receives(call: ast.Call, name: str) -> str | None:
    """The method ``call`` invokes on the bare name ``name``, or ``None``.

    ``other.add_node(...)``, ``self.builder.add_edge(...)`` and a bare
    ``print("add_edge")`` all answer ``None``: only ``name.method(...)`` is a
    call on this builder.
    """
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    return func.attr if func.value.id == name else None


def builder_calls(scope: ast.AST, name: str, source_path: Path) -> list[tuple[ast.Call, str]]:
    """Every ``(call, method)`` on ``name`` in ``scope``'s own body, in source order.

    Sorted by source position rather than taken in ``ast.walk`` order: walk is
    breadth-first, so a call nested inside an ``if`` would be visited after
    shallower calls written below it and the recovered order would stop matching
    the file. Declaration order is not load-bearing for any graph property, but
    it is what a failure message quotes back to a reader.

    A scope nested inside ``scope`` is refused rather than read or skipped; the
    module docstring's last section is why.
    """
    found: list[tuple[ast.Call, str]] = []
    _collect_calls(scope, name, source_path, found)
    found.sort(key=lambda item: (item[0].lineno, item[0].col_offset))
    return found


def _collect_calls(node: ast.AST, name: str, source_path: Path, found: list[tuple[ast.Call, str]]) -> None:
    """Append ``name``'s calls under ``node``, stopping at every nested scope."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES):
            for nested in ast.walk(child):
                if isinstance(nested, ast.Call) and _receives(nested, name) is not None:
                    raise TopologyExtractionError(
                        f"{source_path}:{nested.lineno}: {name!r} is called inside a scope nested in the one "
                        "that binds the builder, where it may be that builder or a rebinding of its name; one "
                        "module's source cannot tell which. Declare the topology in the builder's own scope."
                    )
            continue
        if isinstance(child, ast.Call):
            method = _receives(child, name)
            if method is not None:
                found.append((child, method))
        _collect_calls(child, name, source_path, found)


def argument(call: ast.Call, index: int, keyword: str) -> ast.expr | None:
    """The positional argument at ``index``, else the keyword of that name."""
    if len(call.args) > index:
        return call.args[index]
    for passed in call.keywords:
        if passed.arg == keyword:
            return passed.value
    return None


def resolve(expr: ast.expr | None, source_path: Path, call: ast.Call, role: str) -> str:
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
        f"(got {describe(expr)}); resolve it here rather than dropping the declaration"
    )


def branches(mapping: ast.expr | None, source_path: Path, call: ast.Call) -> list[tuple[str, str]]:
    """``(branch label, destination node)`` for one ``add_conditional_edges`` map.

    A dict maps the router's return value to a node, and a list is LangGraph's
    shorthand for a map whose keys and values coincide. A conditional edge with
    *no* map is refused: the destinations are then whatever the router returns
    at runtime, which no single-module parse can decide, and accepting it would
    contribute zero edges for a call that plainly declares some.
    """
    if isinstance(mapping, ast.Dict):
        found: list[tuple[str, str]] = []
        for key, value in zip(mapping.keys, mapping.values, strict=True):
            if key is None:
                raise TopologyExtractionError(
                    f"{source_path}:{call.lineno}: add_conditional_edges path_map uses ** unpacking, whose "
                    "branches cannot be read from this module alone"
                )
            found.append(
                (
                    resolve(key, source_path, call, "conditional branch label"),
                    resolve(value, source_path, call, "conditional branch destination"),
                )
            )
        return found
    if isinstance(mapping, (ast.List, ast.Tuple)):
        names = [resolve(element, source_path, call, "conditional branch destination") for element in mapping.elts]
        return [(name, name) for name in names]
    raise TopologyExtractionError(
        f"{source_path}:{call.lineno}: add_conditional_edges was called without a statically readable path_map "
        f"(got {describe(mapping)}); its destinations would be decided by the router at runtime"
    )


def describe(expr: ast.expr | None) -> str:
    """A short, stable description of an unresolvable node for an error message."""
    if expr is None:
        return "no such argument"
    return type(expr).__name__


__all__ = [
    "END_SENTINEL",
    "START_SENTINEL",
    "TopologyExtractionError",
    "argument",
    "branches",
    "builder_calls",
    "builder_variable",
    "describe",
    "parse_module",
    "resolve",
]
