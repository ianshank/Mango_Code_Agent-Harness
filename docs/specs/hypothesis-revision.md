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
  carrying that pointer; **no field of the prior entry may be edited**, its
  `status` included.
- R-HR-2: When `revises` names an entry present in the store, that entry MUST
  gain the new entry's id in a `superseded_by` **list**, appended in order.
  Supersession is structural: the key's presence records it. `superseded` MUST
  NOT be a status a caller can assert, and MUST NOT appear in
  `HYPOTHESIS_STATUSES`. A scalar `superseded_by` written by an earlier build
  MUST be migrated into the list rather than discarded.
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
  field MUST reach the store as `None`, and a whitespace-only `revises` MUST be
  normalised in the store itself so the contract holds for every caller.
- R-HR-6: `confidence` MUST be held to the 0.0-1.0 range the schema advertises,
  refused with a `failed` outcome before any write, on the same grounds as
  R-HR-4: `tool_arg_validation` models neither `enum` nor `minimum`/`maximum`.
  The bound MUST reject non-finite values. `json.loads` accepts the `NaN` and
  `Infinity` literals by default, and both satisfy the schema's `number` type,
  so they reach the store through the ordinary tool path; the guard is written
  as a chained comparison because the equivalent-looking
  `confidence < MIN or confidence > MAX` accepts `NaN`.
- R-HR-7: Each refusal and each supersession MUST emit a log line carrying ids,
  statuses and counts only -- never `claim` or `reasoning` (2026 standards audit
  H6). Refusals MUST log at WARNING, because the dispatcher grades a `failed`
  outcome at DEBUG and the refusal would otherwise be invisible on both doors.
- C-HR-1: The change MUST be additive. The three required arguments, the
  `additionalProperties: false` closure, the `read` action in
  `TOOL_REQUIRED_ACTION`, the retention bound, and every existing result string
  are unchanged. An entry written before this change is read back as-is.
- C-HR-2: No new prompt text. The store MUST NOT be surfaced into any role's
  prompt by this change; that is phase 2, gated on the context-window budget
  spec (`docs/reports/PLAYLIST-ASTRA-CONTEXT-BUDGET-PLAN-2026-09-06.md`).
  **Superseded, not deleted, by `C-HS-1` of `docs/specs/hypothesis-surfacing.md`
  (DEC-058):** the invariant narrowed from "no prompt builder reads the store"
  to "no prompt builder reads the store through anything but the bounded
  reasoner formatter". The property it protected -- no unbounded prompt text
  from the store -- survives in that narrower, still-enforced form; the two
  pins below were rewritten rather than removed.

## Acceptance criteria

- [x] AC-1: a revision appends a new entry with `revises`, and the prior entry
      keeps claim, reasoning, confidence **and status**, gaining only
      `superseded_by: [<new id>]` —
      `pytest -k test_hypothesis_revision_supersedes_prior_entry`
      · stage: `make coverage` (R-HR-1, R-HR-2)
- [x] AC-10: an entry registered `confirmed` still reads `confirmed` after being
      revised — `pytest -k test_a_revised_entry_keeps_the_status_its_own_evidence_produced`
      · stage: `make coverage` (R-HR-1)
- [x] AC-11: two revisions of one entry both appear in its `superseded_by`, and
      the forward and backward views of the graph agree —
      `pytest -k test_two_revisions_of_one_entry_both_stay_linked`
      · stage: `make coverage` (R-HR-2)
- [x] AC-12: `status="superseded"` is refused and `superseded` is absent from
      `HYPOTHESIS_STATUSES` — `pytest -k test_superseded_is_not_a_model_settable_status`
      · stage: `make coverage` (R-HR-2)
- [x] AC-13: a confidence of -0.1, 1.1 or 42.0 is refused and nothing is written,
      while 0.0 and 1.0 are accepted —
      `pytest -k test_confidence_outside_the_advertised_range_is_refused` and
      `pytest -k test_confidence_at_the_range_boundaries_is_accepted`
      · stage: `make coverage` (R-HR-6)
- [x] AC-14: a supersession logs the ids but never the claim text, and a dangling
      pointer logs at INFO rather than WARNING —
      `pytest -k test_revision_logs_the_supersede_without_leaking_claim_text` and
      `pytest -k test_dangling_pointer_is_logged_as_retention_not_as_a_fault`
      · stage: `make coverage` (R-HR-7)
- [x] AC-15: the callback that links a revision sees the store as it currently
      is, so a revision cannot act on entries read before the lock —
      `pytest -k test_the_cross_record_update_sees_writes_from_earlier_calls`
      · stage: `make coverage` (R-HR-2)
- [x] AC-16: `NaN` and `±Infinity` confidences are refused and nothing is
      written — `pytest -k test_non_finite_confidence_is_refused`
      · stage: `make coverage` (R-HR-6)
- [x] AC-17: a revision made under `max_hypotheses=0` reports its pointer and
      does **not** claim anything was kept —
      `pytest -k test_a_revision_under_disabled_retention_still_reports_its_pointer`
      · stage: `make coverage` (R-HR-3)
- [x] AC-18: `make memory-show` renders a revised entry with its own status and
      both ends of the revision graph, and no prompt builder imports the reader —
      `pytest -k test_the_revision_graph_is_legible_from_both_ends` and
      `pytest -k test_the_reader_is_not_wired_into_any_prompt_or_gate`
      · stage: `make coverage` (R-HR-1, C-HR-2)
- [x] AC-19: no field of a prior entry changes except its successor list, over a
      whole-record byte comparison —
      `pytest -k test_no_field_of_a_prior_entry_changes_except_its_successor_list`
      · stage: `make coverage` (R-HR-1, R-HR-2)
- [x] AC-20: the cross-record update runs with the store lock held, and a
      raising callback writes nothing and frees the lock —
      `pytest -k test_the_cross_record_update_runs_while_the_store_lock_is_held` and
      `pytest -k test_a_raising_before_append_writes_nothing_and_frees_the_lock`
      · stage: `make coverage` (R-HR-2)
- [x] AC-21: a store whose directory has been removed is recreated rather than
      raising, at the primitive and through the tool —
      `pytest -k test_a_store_whose_directory_vanishes_is_recreated_not_raised` and
      `pytest -k test_a_whole_workspace_removed_mid_run_does_not_break_the_tool`
      · stage: `make coverage` (R-HR-3)
- [x] AC-2: a `revises` id absent from the store is recorded with the pointer and
      the result reports `not found` —
      `pytest -k test_hypothesis_revision_with_unknown_prior_is_recorded_and_reported`
      · stage: `make coverage` (R-HR-3)
- [x] AC-3: an unknown `status` is refused with `tool_outcome(result) == FAILED`
      and the store on disk is still `[]` —
      `pytest -k test_hypothesis_register_refuses_unknown_status_and_writes_nothing`
      · stage: `make coverage` (R-HR-4)
- [x] AC-4: no `status` writes `provisional`; `confirmed` and `retracted` are
      stored; an unrevised entry carries no `revises` key —
      `pytest -k test_hypothesis_status_defaults_to_provisional_and_accepts_settled_states`
      · stage: `make coverage` (R-HR-4, C-HR-1)
- [x] AC-5: with `max_hypotheses=2` the prior entry is trimmed after the revision
      and the revision keeps its pointer —
      `pytest -k test_hypothesis_revision_survives_fifo_trim`
      · stage: `make coverage` (R-HR-3, C-HR-1)
- [x] AC-6: the dispatcher forwards `revises` and `status`, and maps `""` to
      `None` — `pytest -k test_hypothesis_register_forwards_revision_fields`
      · stage: `make coverage` (R-HR-5)
- [x] AC-7: the MCP door accepts the two optional fields and returns the
      not-found note — `pytest -k test_mcp_server_execute_tool_success`
      · stage: `make coverage` (R-HR-5). Every stage in this document is
      `make coverage` for one reason, worth stating because two other targets
      look like the obvious citation and neither is honest. `make test-mcp` and
      `make test-python` both exist and both run these tests, but `ci` and
      `ci-python` invoke *neither* — they reach `coverage`, whose
      `coverage-python` recipe sweeps the same `$(SHARED_TESTS)/` path list.
      Citing a target CI never invokes is the INV-5 gate-truthfulness shape,
      so the criteria name the gate that actually runs on every PR.
- [x] AC-8: the pre-existing pins pass unmodified: `required` still names three
      properties and `additionalProperties` is still `False` —
      `pytest -k "TestRequiredFieldsAreDeclaredProperties or TestAdditionalPropertiesIsClosed"`; the persona still lists the tool
      — `pytest -k test_reasoner_frontmatter_tools_list_includes_meta_tools`;
      declaration, action map and registry remain equal sets —
      `pytest -k test_every_declared_tool_has_a_handler`
      · stage: `make coverage` (C-HR-1)
- [x] AC-9: no prompt-building module reaches the hypothesis store through an
      unbounded reader (narrowed by DEC-058 from "references the store at all";
      the bounded `format_hypotheses_for_reasoner` is the one permitted path) —
      `pytest -k test_prompt_builders_read_hypotheses_only_through_the_bounded_formatter`
      · stage: `make coverage` (C-HR-2, as superseded by C-HS-1)

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

- `harness/shared/meta_tools.py` (R-HR-1 … R-HR-7)
- `harness/shared/memory_store.py` — new; the generic store mechanics (lock,
  recovery, retention, `append_locked`) split out when the revision path pushed
  `meta_tools.py` past `limits.size_budget_lines`. `MEMORY_DIR` and the path
  helpers stay behind deliberately (DEC-057)
- `harness/shared/memory_view.py` — new; rendering the stores for a human
  (`load_hypotheses`, `format_hypotheses_for_review`, `successors_of`). The
  third layer of the same split; nothing in the agent loop imports it (C-HR-2)
- `harness/shared/show_memory.py` — new; the `make memory-show` CLI over that
  view, so the trail DEC-057 justifies the change by is actually readable
- `Makefile` — **protected**; adds the `memory-show` target
- `harness/shared/tests/test_show_memory.py` — new (AC-18)
- `harness/shared/tests/test_hypothesis_revision.py` — new; the revision suite,
  split from `test_meta_tools.py` at `limits.test_size_budget_lines`
- `harness/shared/tests/test_constant_triage.py` — the three lock-timing rows
  follow the constants to `memory_store` and cite DEC-057, which names them there
- `harness/shared/orchestrator/dispatcher.py` — **protected** (R-HR-5)
- `.mango/agents/nemotron-reasoner.md` — **protected** (R-HR-1, R-HR-4)
- `harness/shared/tests/test_meta_tools.py` (AC-1 … AC-5, AC-10 … AC-13)
- `harness/shared/tests/test_orchestrator_tools.py` (AC-6)
- `harness/shared/tests/test_mcp_server.py` (AC-7)
- `harness/shared/tests/test_orchestrator_agent_loop.py` — the loop's
  `hypothesis_register` fake gains the keyword-only parameters (C-HR-1)
- `harness/shared/tests/test_validate_governance_docs.py` — the equality pin
  that blocked every new decision record becomes a subset check
- `harness/shared/tests/regression/test_decision_index_completeness_regression.py`
  — new; the reproduction for that defect, per `harness/CONTRACT.md`'s
  Regression / AQA tier
- `.mango/skills/agent-memory-manager/SKILL.md` — the memory-layer skill gains
  the record shapes and the hypothesis lifecycle, and drops a stale claim that
  the store is resolved from `__file__` (superseded by NS-17)
- `.mango/skills/harness-engineering/SKILL.md`, `.mango/agents/README.md`,
  `docs/architecture/c4_architecture.md`, `docs/reports/2026-STANDARDS-AUDIT.md`
  (M4 marked remediated-in-part), `NEXT_STEPS.md` (phase 2 parked row)
- `.github/dependabot.yml` — adds the `docker` ecosystem; the root `Dockerfile`'s
  base image had no upgrade signal from any job
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

- `make coverage` — AC-1 … AC-6, AC-8 … AC-21 (the suite plus the coverage floors)
- `make coverage` — AC-7 (the MCP suite runs in the same sweep)
- `make specs` — the plan gate over this document (INV-17)
- `make coverage` — per-file floor from `governance-policy.json → coverage.lines`
- `ALLOW_GITHUB_CHANGES=1 make validate` — protected paths, with the attestation
- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — the full gate

## Backward compatibility

Additive, with two deliberate exceptions stated rather than hidden. Positional
callers of `hypothesis_register(claim, reasoning, confidence, workspace_dir,
policy_path)` are unchanged; the new arguments are keyword-only. Entries written
before this change carry no `revises` key and read back unchanged, and an entry
carrying a scalar `superseded_by` from an earlier build of this branch is
migrated into a list rather than dropped.

The exceptions: a `confidence` outside 0.0-1.0 was previously written verbatim
and is now refused (R-HR-6) — no legitimate caller sends one, and the schema
always advertised the range; and `meta_tools`' store mechanics now live in
`memory_store`, re-exported under their original names so
`meta_tools.file_lock`, `meta_tools._read_json_safe`, `meta_tools.MEMORY_DIR`
and the rest resolve exactly as before for callers and monkeypatches alike. The success string gains a `Status:` clause; the
retention-disabled and lock-timeout strings are untouched. The schema's
`required` list and `additionalProperties: false` are unchanged, so a model
that never sends the new fields sees the same tool.

## Open questions

None blocking. Phase 2 (surface open hypotheses to the reasoner the way gaps
reach the planner) is deliberately not scheduled here: it is new prompt text on
every run and needs its own exposure limit under `agent_memory`.

One premise of that deferral changed while this branch was open and is recorded
rather than quietly left stale: `orchestrator.context_budget_tokens` landed with
audit H4 (PR #110), so the token bound phase 2 was waiting for now exists. What
remains is not a number to guess here -- it is how many hypotheses a prompt may
carry and how that interacts with `context_policy`'s tool-call group eviction,
which is a decision and a spec of its own. `C-HR-2` and
`test_the_reader_is_not_wired_into_any_prompt_or_gate` keep the store out of
every prompt until then. DEC-057 records the deferral and this correction.

That decision and spec have since been made: `docs/specs/hypothesis-surfacing.md`
and DEC-058 surface the open hypotheses to the reasoner prompt under two
`agent_memory` bounds, and `C-HR-2` is superseded by `C-HS-1` as noted above.
