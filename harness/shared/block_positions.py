"""Where a statement sits, and whether one point must have run before another.

The lowest question the approval-flag scan asks, and the one its first version
got wrong. ``authority_call_analysis`` answers *what does this name hold when
control reaches this point*; it cannot answer anything until it knows what
"this point" is, and that is a question about the shape of a source file rather
than about brokers, mappings, or approval. Nothing here knows what any of those
are, and nothing here reads a policy, a name, or a value.

**Position is one of the two halves the first version got wrong.** It read every
assignment in a body regardless of where the assignment sat, so a literal
written *after* a broker call laundered the value passed *to* it. A
:data:`Position` records the chain of blocks a statement sits in, and
:func:`runs_before` is the only rule that compares two of them -- dominance
rather than source order, because source order is execution order only inside
one block.

Split out of ``authority_call_analysis`` when the two together passed
``limits.size_budget_lines`` in ``governance-policy.json``. The seam is a real
one rather than a line count: this module holds no authority vocabulary, which
is why its name carries none. It imports ``ast`` and nothing else, so no import
of it can close the cycle the one-way split of the scan exists to forbid --
``test_authority_graph.py`` pins that shape rather than taking it on trust.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-2, C-GEA-1).
Standard library only.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

#: Where a statement sits: one ``(id(owner), field, index)`` step per nesting
#: level from the function body down. Two statements share a block when their
#: paths agree on every step but the last -- the only case in which source order
#: is also execution order. Without it a binding answers "what is this name
#: assigned *somewhere*" when the question is "what does it hold *here*".
Position = tuple[tuple[int, str, int], ...]

#: The AST field shapes holding a statement list. ``except`` handlers and
#: ``match`` cases are here because they are *not* ``ast.stmt``: read as
#: expression fields their assignments go unrecorded, so a name rebound only in
#: an ``except`` branch looks singly-bound and the resolver hands back the
#: ``try`` branch's literal as the value at the call.
BLOCK_KINDS = (ast.stmt, ast.excepthandler, ast.match_case)

#: Statements that open a binding scope of their own. Each gets a scope of its
#: own from the caller; a binding credited to the enclosing function is how a
#: forwarded mapping comes to look like a dict literal.
NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def runs_before(binding: Position, call: Position) -> bool:
    """Whether ``binding`` is guaranteed to have run by the time ``call`` runs.

    True only when the two paths agree on every enclosing block down to one
    they both sit *directly* in, and the binding comes first there. A binding
    nested deeper -- in an ``if``, a ``for``, a ``try`` -- is skipped on some
    path, and one later in a loop body reaches the call on the next iteration.
    With no position at all, a literal assigned *after* a broker call was read
    as the value passed *to* it.
    """
    for depth, (bound, called) in enumerate(zip(binding, call, strict=False)):
        if bound[:2] != called[:2]:
            return False
        if bound[2] != called[2]:
            return bound[2] < called[2] and depth == len(binding) - 1
    return False


def own_nodes(value: object) -> Iterator[ast.AST]:
    """Every node inside one non-block field, without entering a nested scope.

    A nested ``def`` gets its own scope from the caller, so walking into one
    here would attribute its bindings to the enclosing function -- and a binding
    attributed to the wrong scope is how a forwarded mapping comes to look like
    a dict literal. A ``lambda`` is skipped for the same reason and gets no
    scope at all, so a call inside one resolves no name and is reported.
    """
    stack = [item for item in (value if isinstance(value, list) else [value]) if isinstance(item, ast.AST)]
    while stack:
        node = stack.pop()
        if isinstance(node, (*NESTED_SCOPES, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


__all__ = [
    "BLOCK_KINDS",
    "NESTED_SCOPES",
    "Position",
    "own_nodes",
    "runs_before",
]
