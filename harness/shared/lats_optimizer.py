"""Language Agent Tree Search (LATS) Optimization.

Implements MCTS refinement and scoring mechanisms for planning.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from harness.shared.langgraph.ablation import AblationChannel, AblationNode
from harness.shared.langgraph.state import MangoState
from harness.shared.policy_loader import lats_defaults


class LATSOptimizer:
    """Monte Carlo Tree Search algorithm for agent planning."""

    def __init__(self, exploration_weight: float | None = None, max_budget: int | None = None):
        defaults = lats_defaults()
        self.exploration_weight = (
            exploration_weight if exploration_weight is not None else defaults["exploration_weight"]
        )
        self.max_budget = max_budget if max_budget is not None else defaults["max_budget"]

    def _ucb1(self, node: AblationNode, total_visits: int) -> float:
        if node.visits == 0:
            return float('inf')
        exploitation = float(node.score / node.visits)
        exploration = self.exploration_weight * math.sqrt(math.log(total_visits) / node.visits)
        return float(exploitation + exploration)

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

    def _best_leaf(self, root: AblationNode) -> AblationNode | None:
        """Return the highest-scoring leaf across the full tree (depth-first)."""
        best: AblationNode | None = None
        best_avg = 0.0
        stack = [root]
        while stack:
            node = stack.pop()
            if not node.children:
                if node is not root and node.visits > 0:
                    avg = node.score / node.visits
                    if best is None or avg > best_avg:
                        best = node
                        best_avg = avg
            else:
                stack.extend(node.children)
        return best

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

        # Pick the highest-scoring leaf across the entire tree so that
        # multi-step rollouts are not discarded in favour of only the first step.
        best_leaf = self._best_leaf(channel.root)
        if best_leaf is not None:
            return channel.apply_diff(best_leaf)

        return base_state
