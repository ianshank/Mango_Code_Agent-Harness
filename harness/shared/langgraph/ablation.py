"""Ablation tracking for LangGraph LATS optimizer.

This module provides an isolated structure for Monte Carlo Tree Search (MCTS)
hypotheticals, ensuring that Language Agent Tree Search (LATS) rollouts
do not mutate the primary MangoState channel.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

from harness.shared.langgraph.state import MangoState


@dataclass
class AblationNode:
    """A node in the MCTS ablation tree."""

    state_diff: dict[str, Any]
    score: float = 0.0
    visits: int = 0
    children: list["AblationNode"] = field(default_factory=list)
    parent: Optional["AblationNode"] = None
    action_description: str = ""

    def add_child(self, child: "AblationNode") -> None:
        child.parent = self
        self.children.append(child)


class AblationChannel:
    """Isolated channel for MCTS hypotheticals (INV-LG-5)."""

    def __init__(self, base_state: MangoState):
        self.base_state = base_state
        self.root = AblationNode(state_diff={})

    def apply_diff(self, node: AblationNode) -> MangoState:
        """Constructs a hypothetical state without mutating the primary base."""
        hypothetical = copy.deepcopy(self.base_state)
        # Traverse up to collect diffs
        path = []
        current: Optional[AblationNode] = node
        while current:
            path.append(current)
            current = current.parent

        for n in reversed(path):
            hypothetical.update(copy.deepcopy(n.state_diff))  # type: ignore[typeddict-item]

        return hypothetical
