"""Error records for LangGraph nodes, and the classification that grades them.

``INV-LG-3`` asks that a node's exception be *contained* in the ``errors``
channel rather than crashing the graph, and it is honoured: every node wraps
its side effects in ``try/except`` and appends a record. What was missing is a
*consumer*. Until this module, nothing read the channel: ``_route_plan_gate``
and ``_route_quality_gate`` decided on ``gate_status`` and ``revision_count``
alone, and ``quality_gate_node`` consulted ``errors`` only when
``test_results`` was empty — which, because ``evaluation_node`` always appends
a row, is no path through the compiled graph. A denied planner therefore
produced a ``VERIFIED`` verdict over an empty plan
(``docs/specs/langgraph-fail-open-hardening.md``, problem 1).

Containment and consequence are different properties. This module supplies the
second without weakening the first: nothing here raises, and a record is still
just a dict appended to an accumulator channel.

**Two planes, two gradings.** Failing the gate on *any* error would break
INV-16, which requires an observation-mode producer's failure to leave the
incumbent path unaffected. So each record carries its own ``blocking`` flag,
decided once here rather than re-derived by each reader:

* **control plane** — ``planner``, ``implementer``, ``test_eval`` and the
  gates. Their errors are terminal for the run (R-LGH-1).
* **observation plane** — :data:`OBSERVATION_NODES`. Their errors are recorded
  and ignored by the gate, which is what INV-16 asks for.

An unrecognised node name grades as *blocking*: a node this module has never
heard of is not evidence that its failure is safe to ignore (R-LGH-6).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: Nodes whose failures must not decide the control path (INV-16). Naming the
#: observation plane rather than the control plane is deliberate: the default
#: for an unlisted name is "blocking", so forgetting to classify a new node
#: fails closed instead of silently exempting it.
OBSERVATION_NODES = frozenset({"shadow_planner", "peer_reviewer", "security_reviewer"})

#: Suffix the node *functions* carry that the graph's node *names* do not.
#: ``decorators.py`` records ``fn.__name__`` ("shadow_planner_node") while
#: ``nodes.py`` records the graph name ("shadow_planner"); both must classify
#: identically, so classification normalises and storage does not.
_NODE_SUFFIX = "_node"


def graph_node_name(name: str) -> str:
    """Normalise a node function name to the graph node name it registers as.

    ``"shadow_planner_node"`` and ``"shadow_planner"`` both answer
    ``"shadow_planner"``, so a record written by a decorator and one written by
    the node body grade the same way.
    """
    if name.endswith(_NODE_SUFFIX):
        return name[: -len(_NODE_SUFFIX)]
    return name


def is_blocking_node(name: str) -> bool:
    """Whether an error from ``name`` is terminal for the control path."""
    return graph_node_name(name) not in OBSERVATION_NODES


def error_record(node: str, error: object, traceback_text: str = "") -> dict[str, Any]:
    """Build one ``errors``-channel record.

    ``node`` is stored as given — the existing regression suite pins the exact
    strings nodes record — while ``blocking`` is derived from its normalised
    form, so the two producers agree without either changing what it stores.
    """
    return {
        "node": node,
        "error": str(error),
        "traceback": traceback_text,
        "blocking": is_blocking_node(node),
    }


def blocking_error(errors: Iterable[Any] | None) -> dict[str, Any] | None:
    """The first record that blocks the control path, or ``None`` if none does.

    A record without a ``blocking`` key — written before this module existed,
    or by an adopter — is graded from its node name rather than assumed safe,
    and an entry that is not a dict at all grades as blocking: neither absence
    of a flag nor a malformed record is evidence that a failure was harmless.
    """
    for entry in errors or ():
        if not isinstance(entry, dict):
            return error_record("", entry)
        node = entry.get("node", "")
        if entry.get("blocking", is_blocking_node(node if isinstance(node, str) else "")):
            return entry
    return None


__all__ = [
    "OBSERVATION_NODES",
    "blocking_error",
    "error_record",
    "graph_node_name",
    "is_blocking_node",
]
