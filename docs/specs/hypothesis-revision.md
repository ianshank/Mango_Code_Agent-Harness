# Spec: hypothesis-revision

> `hypothesis_register` gains an append-only revision path, so a belief the
> reasoner recorded can later be confirmed or retracted without editing the
> record. Surfacing the store back into a prompt is deferred (phase 2, below).

## Problem statement

Every hypothesis entry is written with `"status": "provisional"` at
`harness/shared/meta_tools.py` and nothing ever updates it. Both the function
docstring and the schema description promise that hypotheses "can be updated or
falsified later as evidence arrives"; no code path does so. The 2026 standards
audit recorded the meta-tools as write-only (finding M4); NS-17 closed that for
gaps by surfacing them to the planner and left hypotheses untouched.

Evidence, from the shipped store and schema on `main` @ `d1e13c5`:

```
$ git grep -n '"status": "provisional"' harness/shared/meta_tools.py
harness/shared/meta_tools.py:249:        "status": "provisional",
$ git grep -n 'status' harness/shared/meta_tools.py | grep -v provisional
(no matches: nothing reads or rewrites the field)
```

The reference `sequentialthinking` MCP server (Model Context Protocol servers
repository) models the same need as `isRevision` / `revisesThought` on a
thought record. Adopting that server here was assessed and rejected: it
performs no reasoning, would need an MCP client the harness does not have, and
every thought would spend one of `orchestrator.max_iterations`. The one idea
worth taking is the revision pointer, expressed on the tool this harness already
offers.

## Requirements

- R-HR-1: `hypothesis_register` MUST accept an optional `revises` argument
  naming a prior entry's id, and MUST record the revision as a *new* entry
  carrying that pointer; the prior entry's text MUST NOT be edited.
- R-HR-2: When `revises` names an entry present in the store, that entry MUST be
  marked `status: superseded` with `superseded_by` set to the new entry's id.
  `superseded` MUST NOT be a status the model can assert directly.
- R-HR-3: When `revises` names an entry the store does not hold (FIFO-trimmed
  under `agent_memory.max_hypotheses`, or mistyped), the new entry MUST still
  be recorded with its pointer and the result MUST say the prior entry was not
  found.
- R-HR-4: `hypothesis_register` MUST accept an optional `status` of
  `provisional` (default), `confirmed`, or `retracted`, and MUST refuse any
  other value with a `failed` tool outcome before writing, because
  `tool_arg_validation` does not model `enum`.
- R-HR-5: Both transports MUST forward the new fields: the orchestrator
  dispatcher's registry and, through it, the MCP server. An absent or empty
  field MUST reach the store as `None`.
- C-HR-1: The change MUST be additive. The three required arguments, the
  `additionalProperties: false` closure, the `read` action in
  `TOOL_REQUIRED_ACTION`, the retention bound, and every existing result string
  are unchanged. An entry written before this change is read back as-is.
- C-HR-2: No new prompt text. The store MUST NOT be surfaced into any role's
  prompt by this change; that is phase 2, gated on the context-window budget
  spec (`docs/reports/PLAYLIST-ASTRA-CONTEXT-BUDGET-PLAN-2026-09-06.md`).

## Acceptance criteria

- [ ] AC-1: a revision appends a new entry with `revises`, and the prior entry
      keeps its claim and gains `status: superseded` and `superseded_by` —
      `pytest -k test_hypothesis_revision_supersedes_prior_entry`
      · stage: `make test-python` (R-HR-1, R-HR-2)
- [ ] AC-2: a `revises` id absent from the store is recorded with the pointer and
      the result reports `not found` —
      `pytest -k test_hypothesis_revision_with_unknown_prior_is_recorded_and_reported`
      · stage: `make test-python` (R-HR-3)
- [ ] AC-3: an unknown `status` is refused with `tool_outcome(result) == FAILED`
      and the store on disk is still `[]` —
      `pytest -k test_hypothesis_register_refuses_unknown_status_and_writes_nothing`
      · stage: `make test-python` (R-HR-4)
- [ ] AC-4: no `status` writes `provisional`; `confirmed` and `retracted` are
      stored; an unrevised entry carries no `revises` key —
      `pytest -k test_hypothesis_status_defaults_to_provisional_and_accepts_settled_states`
      · stage: `make test-python` (R-HR-4, C-HR-1)
- [ ] AC-5: with `max_hypotheses=2` the prior entry is trimmed after the revision
      and the revision keeps its pointer —
      `pytest -k test_hypothesis_revision_survives_fifo_trim`
      · stage: `make test-python` (R-HR-3, C-HR-1)
- [ ] AC-6: the dispatcher forwards `revises` and `status`, and maps `""` to
      `None` — `pytest -k test_hypothesis_register_forwards_revision_fields`
      · stage: `make test-python` (R-HR-5)
- [ ] AC-7: the MCP door accepts the two optional fields and returns the
      not-found note — `pytest -k test_mcp_server_execute_tool_success`
      · stage: `make test-mcp` (R-HR-5)
- [ ] AC-8: the pre-existing pins pass unmodified: `required` still names three
      properties and `additionalProperties` is still `False` —
      `pytest -k TestSchemaInternalConsistency`; the persona still lists the tool
      — `pytest -k test_reasoner_frontmatter_tools_list_includes_meta_tools`;
      declaration, action map and registry remain equal sets —
      `pytest -k test_every_declared_tool_has_a_handler`
      · stage: `make test-python` (C-HR-1)
- [ ] AC-9: neither `harness/shared/agent_prompts.py` nor
      `harness/shared/orchestrator/loop.py` references the hypothesis store —
      `pytest -k test_hypothesis_store_is_not_surfaced_in_prompts`
      · stage: `make test-python` (C-HR-2)

## Steps

1. Extend the store — produces the status constants, the `revises` / `status`
   keyword arguments and the supersede transition in
   `harness/shared/meta_tools.py` (R-HR-1, R-HR-2, R-HR-3, R-HR-4)
2. Extend the schema — consumes step 1; produces the two optional properties on
   `META_TOOLS_SCHEMA` in `harness/shared/meta_tools.py` (R-HR-5, C-HR-1)
3. Forward through the registry — consumes step 2; produces the two keyword
   arguments in `harness/shared/orchestrator/dispatcher.py`; the MCP server
   serves the same registry and needs no edit (R-HR-5)
4. Tell the model — produces the one-line edit to
   `.mango/agents/nemotron-reasoner.md` (R-HR-1, R-HR-4)
5. Pin it — produces the tests named in AC-1 … AC-7 (all)
6. Record it — produces `docs/decisions/DEC-057.md` and the regenerated
   `docs/decisions/index.{md,json}` via `make decision-index` (C-HR-2)

## Files touched

- `harness/shared/meta_tools.py` (R-HR-1, R-HR-2, R-HR-3, R-HR-4, R-HR-5)
- `harness/shared/orchestrator/dispatcher.py` — **protected** (R-HR-5)
- `.mango/agents/nemotron-reasoner.md` — **protected** (R-HR-1, R-HR-4)
- `harness/shared/tests/test_meta_tools.py` (AC-1 … AC-5)
- `harness/shared/tests/test_orchestrator_tools.py` (AC-6)
- `harness/shared/tests/test_mcp_server.py` (AC-7)
- `docs/decisions/DEC-057.md`, `docs/decisions/index.md`,
  `docs/decisions/index.json`, `harness/node/.governance/decision-log.md` (C-HR-2)
- `docs/specs/hypothesis-revision.md` — this document
- `CHANGELOG.md`

The two protected paths carry the `infra-reviewed` attestation in the pull
request description, produced by `make attestation`.

## Invariants touched

- INV-7: unchanged. The tool keeps the `read` action; no role gains or loses
  authority, which `test_every_declared_tool_has_a_required_action` pins.
- INV-16: unchanged. The store is memory the model writes and nothing reads on a
  control path; `confidence` and `status` select no tool and alter no exposure
  (C-HR-2 keeps it that way).
- INV-17: this document is subject to it; `validate_plan.py` grades these
  criteria under `make specs`.

## Validation matrix

- `make test-python` — AC-1 … AC-6, AC-8, AC-9
- `make test-mcp` — AC-7
- `make specs` — the plan gate over this document (INV-17)
- `make coverage` — per-file floor from `governance-policy.json → coverage.lines`
- `ALLOW_GITHUB_CHANGES=1 make validate` — protected paths, with the attestation
- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — the full gate

## Backward compatibility

Additive. Positional callers of `hypothesis_register(claim, reasoning,
confidence, workspace_dir, policy_path)` are unchanged; the new arguments are
keyword-only. Entries written before this change carry no `revises` key and
read back unchanged. The success string gains a `Status:` clause; the
retention-disabled and lock-timeout strings are untouched. The schema's
`required` list and `additionalProperties: false` are unchanged, so a model
that never sends the new fields sees the same tool.

## Open questions

None blocking. Phase 2 (surface open hypotheses to the reasoner the way gaps
reach the planner) is deliberately not scheduled here: it is new prompt text on
every run and needs a policy limit under `agent_memory`, and the context-window
budget program merged on 2026-09-06 has not yet landed the token bound it
should be written against. DEC-057 records the deferral.
