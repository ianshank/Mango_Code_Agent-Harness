---
name: agent-memory-manager
description: Manage and enforce persistent memory policies, retention, and knowledge gap storage for the Mango MAS orchestrator.
Reviewed: 2026-08-31
---

# Agent Memory Manager

Use this skill when managing the lifecycle of persistent memory or resolving knowledge gaps within the Agentic SSD & Nemotron AI Platform.

## Objectives

- Ensure that agentic reasoning traces and knowledge gaps are persistently stored (in JSON/Markdown format) inside the designated `memory/` directories.
- Enforce retention policies so that context lengths do not grow unbounded across sessions.

## Execution Rules

1. **Never use hard-coded absolute paths** — The memory directory is dynamically resolved at `<repo-root>/.mango/memory/` (from `__file__` in `meta_tools.py`) to remain workspace-agnostic.
2. **Fail-Closed Operations** — Reading or writing to the memory store MUST gracefully handle malformed JSON files by backing up the malformed file and resetting the store, raising a structured alert to the orchestrator `errors` channel (as per `INV-LG-3`).
3. **Spec-Driven Constraints** — Any modification to how memory is stored or retained MUST be preceded by a spec change referencing the `meta_tools.py` memory layer.
