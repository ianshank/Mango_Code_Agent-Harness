"""Language Agent Tree Search (LATS) Optimization.

Implements MCTS refinement and scoring mechanisms for planning.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from harness.shared.langgraph.ablation import AblationChannel, AblationNode
from harness.shared.langgraph.state import MangoState


class LATSOptimizer:
    """Monte Carlo Tree Search algorithm for agent planning."""

    def __init__(self, exploration_weight: float = 1.414, max_budget: int = 10):
        self.exploration_weight = exploration_weight
        self.max_budget = max_budget

    def _ucb1(self, node: AblationNode, total_visits: int) -> float:
        if node.visits == 0:
            return float('inf')
        exploitation = node.score / node.visits
        exploration = self.exploration_weight * math.sqrt(math.log(total_visits) / node.visits)
        return exploitation + exploration

    def select(self, root: AblationNode) -> AblationNode:
        """Selects the best node using UCB1."""
        current = root
        while current.children:
            total_visits = sum(child.visits for child in current.children)
            if total_visits == 0:
                total_visits = 1
            current = max(current.children, key=lambda c: self._ucb1(c, total_visits))
        return current

    def backpropagate(self, node: AblationNode, score: float) -> None:
        """Backpropagates the evaluation score up the tree."""
        current: AblationNode | None = node
        while current:
            current.visits += 1
            current.score += score
            current = current.parent

    def refine_plan(
        self,
        base_state: MangoState,
        rollout_fn: Callable[[MangoState], list[dict[str, Any]]],
        eval_fn: Callable[[MangoState], float]
    ) -> MangoState:
        """Refines a plan using MCTS and returns the best state."""
        channel = AblationChannel(base_state)

        for _ in range(self.max_budget):
            leaf = self.select(channel.root)

            # Expand
            if leaf.visits > 0 or leaf == channel.root:
                hypothetical_state = channel.apply_diff(leaf)
                # rollout_fn generates possible next state diffs
                next_diffs = rollout_fn(hypothetical_state)
                for diff in next_diffs:
                    new_child = AblationNode(state_diff=diff)
                    leaf.add_child(new_child)
                if leaf.children:
                    leaf = leaf.children[0]

            # Evaluate
            hypothetical_state = channel.apply_diff(leaf)
            score = eval_fn(hypothetical_state)

            # Backpropagate
            self.backpropagate(leaf, score)

        # Pick the best child from root based on max visits (robustness) or max score
        if channel.root.children:
            best_node = max(channel.root.children, key=lambda c: c.score / c.visits if c.visits > 0 else 0.0)
            return channel.apply_diff(best_node)

        return base_state
