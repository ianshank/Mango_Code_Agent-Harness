---
name: agent-memory-manager
description: Manage and enforce persistent memory policies, retention, and knowledge gap storage for the Mango MAS orchestrator.
Reviewed: 2026-09-06
---

# Agent Memory Manager

Use this skill when managing the lifecycle of persistent memory or resolving knowledge gaps within the Agentic SSD & Nemotron AI Platform.

## Objectives

- Ensure that agentic reasoning traces and knowledge gaps are persistently stored (in JSON/Markdown format) inside the designated `memory/` directories.
- Enforce retention policies so that context lengths do not grow unbounded across sessions.

## Execution Rules

1. **Never use hard-coded absolute paths** — the store is resolved at call time by
   `meta_tools.resolve_memory_dir(workspace_dir)`. When a caller supplies a
   workspace the store is `<workspace>/.mango/memory/`; `workspace_dir=None`
   keeps the pre-NS-17 install-root `MEMORY_DIR` for out-of-workspace callers
   and existing monkeypatches. Two workspaces never share a store. Reading the
   install path from `__file__` is the M4 defect NS-17 fixed, not the contract.
2. **Fail-Closed Operations** — Reading or writing to the memory store MUST gracefully handle malformed JSON files by backing up the malformed file and resetting the store, raising a structured alert to the orchestrator `errors` channel (as per `INV-LG-3`). A backup that itself fails raises rather than resetting: the only surviving copy is preserved over the store's cleanliness.
3. **Spec-Driven Constraints** — Any modification to how memory is stored or retained MUST be preceded by a spec change referencing the `meta_tools.py` memory layer.
4. **Bounds come from policy, never from a literal** — retention is
   `agent_memory.max_gaps` / `agent_memory.max_hypotheses` and planner exposure
   is `agent_memory.planner_gap_limit`, all read through
   `policy_loader.agent_memory_defaults(policy_path)`. A bound of `0` disables
   retention and the tool result says so rather than claiming a successful write.

## Record shapes

Both stores are **append-only JSON lists**, written under an advisory
`file_lock` and replaced atomically, then FIFO-trimmed to the policy bound.

`gaps.json` — `id`, `timestamp`, `question`, `what_needed`, `proposed_approach`.
Surfaced to the **planner** prompt by `format_gaps_for_planner`, most recent
first, truncated to `planner_gap_limit`.

`hypotheses.json` — `id`, `timestamp`, `claim`, `reasoning`, `confidence`,
`status`, and on a revision `revises`; on the entry that was revised,
`superseded_by` (a **list** of successor ids). **Nothing reads this store into
a prompt** (DEC-057 phase 2).

## Hypothesis lifecycle (DEC-057)

A belief is corrected by **appending**, never by editing what was written.

`status` is the model's own verdict and is the complete vocabulary:

| Status | Meaning |
|---|---|
| `provisional` (default) | recorded, not yet settled |
| `confirmed` | evidence supported the claim |
| `retracted` | evidence falsified the claim |

**Supersession is structural, not a status.** There is no `superseded` status:
the presence of `superseded_by` on an entry is what records that a later entry
revised it. This is the point most likely to be got wrong when extending the
layer, and it was got wrong once already — writing `status: "superseded"` onto
the prior entry destroyed the verdict its own evidence had produced, turning an
append-only store into a lossy one.

Rules to enforce when auditing or extending this layer:

- A revision is a new entry carrying `revises: <prior id>`. The prior entry
  keeps **every** field it was written with — `claim`, `reasoning`,
  `confidence` and `status` — and gains only its successor's id in
  `superseded_by`. Nothing about it is overwritten.
- `superseded_by` is a list, appended in order, because revision fans out: one
  belief revised two different ways on two pieces of evidence is two real
  revisions, and a scalar would record only the later. A scalar left by an
  older build is migrated into a list, never discarded.
- `superseded` is not a settable status: it is absent from
  `HYPOTHESIS_STATUSES`, so a call asserting it is refused like any other
  unknown value.
- A status outside the three settable values, or a `confidence` outside the
  advertised 0.0–1.0, is refused with a `failed` tool outcome **before the
  store is touched** — not even the empty store file is created — because
  `tool_arg_validation` models `type` but neither `enum` nor `minimum`/`maximum`.
  Both refusals log at WARNING: the dispatcher grades a `failed` outcome at
  DEBUG, so a model looping on a bad argument would otherwise be invisible.
- A `revises` id the store no longer holds (FIFO-trimmed, or mistyped) is
  recorded anyway with its pointer, and the result reports that the prior entry
  was not found. Retention bounds are allowed to break a chain; losing the new
  belief because its ancestor aged out would be worse.
- Cross-record updates run inside the store lock, via `append_locked`'s
  `before_append` hook in `harness/shared/memory_store.py`. Reading the entries
  first and mutating them afterwards loses one of two concurrent revisions.

## Related

- `docs/specs/hypothesis-revision.md` — the revision contract (R-HR-1…5, C-HR-1…2).
- `docs/decisions/DEC-057.md` — why revision is append-only, why the
  sequential-thinking MCP server was not adopted, and why surfacing the
  hypothesis store into a prompt is deferred.
