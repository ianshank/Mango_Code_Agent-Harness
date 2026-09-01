"""LangGraph node decorators for authority and budget enforcement.

These decorators wrap existing ``agent_authority`` and ``tool_budget`` modules
to provide a clean interface for LangGraph node functions.  They import
**downward** into the existing governance layer — nothing in the governance
layer imports from this module.

Usage::

    @with_authority("nemotron-reasoner", may_write=True)
    def implementer_node(state: MangoState, config: RunnableConfig) -> dict:
        ...

    @budgeted("tool_budget_used")
    def any_node(state: MangoState) -> dict:
        ...
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def with_authority(role: str, *, may_write: bool = False) -> Callable:
    """Decorator that enforces role-based authority checks on a node function.

    Reads the agent's allowed actions from ``agent-policy.json`` via the
    existing ``agent_authority.tools_for_role`` function.  If the role does
    not hold the required authority, the node returns an error in the
    ``errors`` channel instead of executing.

    Parameters
    ----------
    role:
        The agent role ID as defined in ``agent-policy.json``.
    may_write:
        If ``True``, the node is allowed to perform write operations.
        If ``False`` (default), the node is read-only.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                from harness.shared.agent_authority import allowed_actions

                actions = allowed_actions(role)
                required_action = "write" if may_write else "read"
                if required_action not in actions:
                    logger.warning(
                        "Node %s: role %r does not hold %s authority",
                        fn.__name__, role, required_action,
                    )
                    return {
                        "errors": [
                            {
                                "node": fn.__name__,
                                "error": f"role {role!r} lacks {required_action} authority",
                                "traceback": "",
                            }
                        ]
                    }
            except Exception as exc:  # noqa: BLE001
                logger.error("Authority check failed for %s: %s", fn.__name__, exc)
                return {
                    "errors": [
                        {
                            "node": fn.__name__,
                            "error": f"authority check failed: {exc}",
                            "traceback": "",
                        }
                    ]
                }

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def budgeted(budget_key: str = "tool_budget_used") -> Callable:
    """Decorator that tracks tool budget consumption in state.

    Reads the current budget from state[budget_key] and increments it.
    If the budget is exhausted, returns an error instead of executing.

    Parameters
    ----------
    budget_key:
        The state channel key tracking cumulative tool budget usage.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict, *args: Any, **kwargs: Any) -> Any:
            try:
                from harness.shared.policy_loader import max_tool_calls_per_task

                budget_limit = max_tool_calls_per_task()
                current = state.get(budget_key, 0)

                if current >= budget_limit:
                    logger.warning(
                        "Node %s: tool budget exhausted (%d/%d)",
                        fn.__name__, current, budget_limit,
                    )
                    return {
                        "errors": [
                            {
                                "node": fn.__name__,
                                "error": f"tool budget exhausted ({current}/{budget_limit})",
                                "traceback": "",
                            }
                        ]
                    }
            except Exception as exc:  # noqa: BLE001
                logger.error("Budget check failed for %s: %s", fn.__name__, exc)
                return {
                    "errors": [
                        {
                            "node": fn.__name__,
                            "error": f"budget check failed: {exc}",
                            "traceback": "",
                        }
                    ]
                }

            result = fn(state, *args, **kwargs)

            # Increment budget counter in the result
            if isinstance(result, dict) and budget_key not in result:
                current = state.get(budget_key, 0)
                result[budget_key] = current + 1

            return result
        return wrapper
    return decorator


__all__ = ["budgeted", "with_authority"]
