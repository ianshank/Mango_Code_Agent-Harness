"""Policy-driven context-window budgeting for model-facing chat histories.

Pure helpers: no I/O, no policy file reads, no loop imports. Callers supply
``budget_tokens`` and ``chars_per_token`` resolved through
``policy_loader.orchestrator_defaults`` (spec:
``docs/specs/context-window-budget.md``, audit H4).

Eviction is atomic over tool-call groups so providers never see orphaned
``role:tool`` turns or ``tool_calls`` without matching results.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any, TypedDict


class ContextPolicyStats(TypedDict):
    """Structured fields for ``event=context_policy`` logging."""

    tokens_before: int
    tokens_after: int
    groups_preserved: int
    messages_evicted: int


def estimate_tokens(messages: Sequence[Mapping[str, Any]], chars_per_token: float) -> int:
    """Estimate prompt tokens from character length / ``chars_per_token``.

    ``chars_per_token`` must come from policy (or a test fixture), never a
    hard-coded application literal at the call site.
    """
    if chars_per_token <= 0:
        raise ValueError(f"chars_per_token must be positive, got {chars_per_token!r}")
    total_chars = sum(_message_chars(message) for message in messages)
    return max(0, ceil(total_chars / chars_per_token))


def measure_tokens(
    messages: Sequence[Mapping[str, Any]],
    *,
    usage: Mapping[str, Any] | None = None,
    chars_per_token: float,
) -> int:
    """Prefer provider ``usage.prompt_tokens`` when present; else estimate."""
    if usage is not None:
        prompt = usage.get("prompt_tokens")
        if isinstance(prompt, (int, float)) and not isinstance(prompt, bool) and int(prompt) >= 0:
            return int(prompt)
    return estimate_tokens(messages, chars_per_token)


def identify_tool_call_groups(history: Sequence[Mapping[str, Any]]) -> list[tuple[int, ...]]:
    """Return index tuples for each assistant+tool group (atomic keep/drop units).

    Each group is the assistant message that declares ``tool_calls`` plus every
    subsequent ``role=tool`` message whose ``tool_call_id`` matches one of those
    ids, in encounter order, while scanning contiguous tool results. An incomplete
    group includes the matching results encountered before the first interruption.
    """
    groups: list[tuple[int, ...]] = []
    n = len(history)
    i = 0
    while i < n:
        message = history[i]
        tool_calls = message.get("tool_calls") if isinstance(message, Mapping) else None
        if message.get("role") == "assistant" and isinstance(tool_calls, list) and tool_calls:
            ids = {_tool_call_id(tc) for tc in tool_calls}
            ids.discard(None)
            indices = [i]
            j = i + 1
            pending = set(ids)
            while j < n and pending:
                nxt = history[j]
                if nxt.get("role") == "tool":
                    call_id = nxt.get("tool_call_id")
                    if call_id in pending:
                        indices.append(j)
                        pending.discard(call_id)
                        j += 1
                        continue
                break
            groups.append(tuple(indices))
            i = j
            continue
        i += 1
    return groups


def apply_context_policy(
    history: Sequence[Mapping[str, Any]],
    budget_tokens: int,
    *,
    chars_per_token: float,
) -> tuple[list[dict[str, Any]], ContextPolicyStats]:
    """Return a budgeted copy of ``history`` and eviction stats.

    Oldest tool-call groups are dropped first until *estimated* size of the
    current message list is within ``budget_tokens`` or no evictable groups
    remain. Provider ``usage.prompt_tokens`` is intentionally not used here:
    it describes a prior request and must not gate eviction of a grown
    history (use :func:`measure_tokens` when you have usage for *this* list).
    The input is never mutated. Non-group messages (system / user / plain
    assistant) are retained in v1.
    """
    if budget_tokens < 0:
        raise ValueError(f"budget_tokens must be non-negative, got {budget_tokens!r}")

    messages: list[dict[str, Any]] = [dict(m) for m in history]
    tokens_before = estimate_tokens(messages, chars_per_token)
    evicted = 0

    while True:
        size = estimate_tokens(messages, chars_per_token)
        if size <= budget_tokens:
            break
        groups = identify_tool_call_groups(messages)
        if not groups:
            break
        drop = set(groups[0])
        evicted += len(drop)
        messages = [m for idx, m in enumerate(messages) if idx not in drop]

    tokens_after = estimate_tokens(messages, chars_per_token)
    stats: ContextPolicyStats = {
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "groups_preserved": len(identify_tool_call_groups(messages)),
        "messages_evicted": evicted,
    }
    return messages, stats


def history_tool_links_are_consistent(messages: Sequence[Mapping[str, Any]]) -> bool:
    """True when every tool_calls id has a result and no tool result is orphaned."""
    pending: set[str] = set()
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                for tc in tool_calls:
                    call_id = _tool_call_id(tc)
                    if call_id is not None:
                        pending.add(call_id)
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                return False
            pending.discard(call_id)
    return not pending


def _tool_call_id(tool_call: Any) -> str | None:
    if not isinstance(tool_call, Mapping):
        return None
    call_id = tool_call.get("id")
    return call_id if isinstance(call_id, str) else None


def _message_chars(message: Mapping[str, Any]) -> int:
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif content is not None:
        parts.append(str(content))
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, Mapping):
                continue
            fn = tc.get("function")
            if isinstance(fn, Mapping):
                name = fn.get("name")
                args = fn.get("arguments")
                if isinstance(name, str):
                    parts.append(name)
                if isinstance(args, str):
                    parts.append(args)
                elif args is not None:
                    parts.append(str(args))
            call_id = tc.get("id")
            if isinstance(call_id, str):
                parts.append(call_id)
    call_id = message.get("tool_call_id")
    if isinstance(call_id, str):
        parts.append(call_id)
    role = message.get("role")
    if isinstance(role, str):
        parts.append(role)
    return sum(len(p) for p in parts)


__all__ = [
    "ContextPolicyStats",
    "apply_context_policy",
    "estimate_tokens",
    "history_tool_links_are_consistent",
    "identify_tool_call_groups",
    "measure_tokens",
]
