---
name: agent-memory-manager
description: Manage and enforce persistent memory policies, retention, and knowledge gap storage for the Mango MAS orchestrator.
Reviewed: 2026-09-05
---

# Agent Memory Manager

Use this skill when managing the lifecycle of persistent memory or resolving knowledge gaps within the Agentic SSD & Nemotron AI Platform.

> **NS-17 simplified baseline (2026-09-05):** `resolve_memory_dir(workspace_dir)`,
> `_fifo_trim`, `format_gaps_for_planner`, and `policy_path` threading are **absent**
> from `meta_tools.py` on this branch. Memory is stored at a fixed path derived from
> `__file__` (`MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / ".mango" / "memory"`).
> The planner prompt template takes only `{task}`; there is no `{open_gaps}` injection.
> `test_ns17_rollback_regression.py` pins this state.

## Objectives

- Ensure that agentic reasoning traces and knowledge gaps are persistently stored (in JSON/Markdown format) inside the designated `memory/` directories.
- Provide deterministic, file-locked reads and writes to prevent data loss on concurrent agent turns.

## Execution Rules

1. **Never use hard-coded absolute paths** — The memory directory is resolved at `<repo-root>/.mango/memory/` (from `__file__` in `meta_tools.py`) to remain workspace-agnostic.
2. **Fail-Closed Operations** — Reading or writing to the memory store MUST gracefully handle malformed JSON files by backing up the malformed file and resetting the store, raising a structured alert to the orchestrator `errors` channel (as per `INV-LG-3`).
3. **Spec-Driven Constraints** — Any modification to how memory is stored or retained MUST be preceded by a spec change referencing the `meta_tools.py` memory layer.
4. **No workspace_dir or policy_path parameters** — `knowledge_gap_log` and `hypothesis_register` take only the three required string arguments. If NS-17 (workspace scoping + retention) is re-implemented, update this skill and add tests before removing `test_ns17_rollback_regression.py` guards.
