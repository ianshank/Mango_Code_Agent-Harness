# Spec: reasoner-bridge-tool-parity

**Status:** Scaffolded (not implemented). Contract for NS-18.

> Scaffolded for NS-18. Land on `main` via parent/`make spec NAME=reasoner-bridge-tool-parity`
> norms if required. Implementation MUST NOT open until this spec is the contract
> the `verifier` role checks against.

## Problem statement

`.mango/agents/nemotron-reasoner.md` is loaded verbatim as the Nemotron system
prompt (`harness/shared/orchestrator/loop.py::load_agent_prompt` /
`execute_agent`), including Claude Code frontmatter tools (`Bash`, `Read`,
`Grep`, `Glob`) and mixed body instructions. The bridge advertises a different
set: `NEMOTRON_TOOLS` in `harness/shared/tool_schemas.py` (`write_file`,
`read_file`, `apply_patch`, `run_command`, plus `META_TOOLS_SCHEMA`). Only a
subset overlaps. Phase B already unified MCP and orchestrator dispatch on one
registry (R-SR-15); persona prose was left behind (audit M2 / NS-18).

Evidence (tip after #99, `b1722713...`):

- Frontmatter: `tools: Bash, Read, Grep, Glob, knowledge_gap_log, hypothesis_register`
- Body names both Claude tools and bridge tools (and `cat`)
- `_log_model_call` carries `run_id` but no prompt content digest
- `REASONER_PROMPT_TEMPLATE` hard-codes bridge tool names outside `NEMOTRON_TOOLS`

## Requirements

- R-RBT-1: The runtime system prompt for every active MAS role loaded via
  `load_agent_prompt` MUST include a tool paragraph generated from the same tool
  schema list passed to `complete_chat` for that turn (i.e. role-filtered
  `NEMOTRON_TOOLS` via `tools_for_role`, or an explicit `tools=` override), not
  from a hand-maintained name list in markdown.
- R-RBT-2: Persona markdown under `.mango/agents/` MUST remain the source of
  non-tool instructions (responsibilities, operating rules, canonical-role
  mapping). It MUST NOT be the source of the tool inventory paragraph injected
  into the Nemotron system prompt.
- R-RBT-3: No module outside `harness/shared/tool_schemas.py` (and
  `meta_tools.py` as composed into `NEMOTRON_TOOLS`) MAY maintain a hard-coded
  list of bridge tool names for prompt or parity purposes; formatters and tests
  MUST derive names from `NEMOTRON_TOOLS` / the active tools list.
- R-RBT-4: Every structured log event that already correlates agent model work by
  `run_id` for a turn that sent a system prompt (`model_call`, and the first
  assembly event if one is added) MUST include `prompt_sha` - the hex SHA-256 of
  the exact system prompt string bytes (UTF-8) - and MUST NOT include the prompt
  body.
- R-RBT-5: A unit (or gate) test MUST fail when any `.mango/agents/*.md` persona
  body names a tool-shaped identifier that is not in the bridge registry
  (`NEMOTRON_TOOLS` function names), so Claude Code vocabulary cannot re-enter
  instructional prose unnoticed.
- C-RBT-1: The change MUST NOT widen any role's permitted tool set relative to
  `agent_authority.tools_for_role` / `agent-policy.json`.
- C-RBT-2: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`
  (especially INV-8/9/10 broker and pretooluse posture; INV-5 gate wiring).
- C-RBT-3: YAML frontmatter, if retained for IDE consumers, MUST be stripped
  before the Nemotron system prompt is assembled so IDE-only tool names cannot
  reach the model.

## Acceptance criteria

- [ ] AC-1: For `nemotron-reasoner`, the composed system prompt's tool paragraph
      names exactly the function names in
      `tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)` (order may follow
      schema order) and contains none of `Bash`, `Read`, `Grep`, `Glob` as tool
      identifiers - verified by
      `pytest -k test_reasoner_system_prompt_tools_match_bridge`
      · stage: `make test-python` (R-RBT-1, C-RBT-3)
- [ ] AC-2: Mutating a temporary persona fixture to instruct use of a
      non-registry tool name (e.g. `Bash`) causes
      `pytest -k test_persona_tools_subset_of_nemotron_tools` to fail; restoring
      registry-only names passes - verified by that test's positive and negative
      cases · stage: `make test-python` (R-RBT-5)
- [ ] AC-3: A mocked `execute_agent` / `_log_model_call` path records
      `prompt_sha` equal to `hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()`
      on the `model_call` extra dict keyed by the same `run_id` - verified by
      `pytest -k test_model_call_logs_prompt_sha`
      · stage: `make test-python` (R-RBT-4)
- [ ] AC-4: `git grep -nE 'tools: *(Bash|Read|Grep|Glob)' -- .mango/agents/`
      returns nothing **or** those matches appear only inside YAML frontmatter
      that the runtime strip path covers; instructional body paragraphs contain
      no such tokens - verified by AC-2's scanner plus a focused strip unit test
      `pytest -k test_load_agent_prompt_strips_frontmatter`
      · stage: `make test-python` (R-RBT-2, C-RBT-3)
- [ ] AC-5: `REASONER_PROMPT_TEMPLATE` / `PLANNER_PROMPT_TEMPLATE` /
      `VERIFIER_PROMPT_TEMPLATE` do not embed a hard-coded inventory of bridge
      tool names; any necessary mention is generated from schemas or omitted in
      favour of the system tool paragraph - verified by
      `pytest -k test_agent_prompt_templates_have_no_hardcoded_tool_inventory`
      · stage: `make test-python` (R-RBT-3)
- [ ] AC-6: `make ci` passes end-to-end after the change, including protected-path
      attestation check when protected files are modified
      · stage: `make ci` (C-RBT-1, C-RBT-2)

At least one criterion (AC-2) names a non-success outcome: inventing a
non-bridge tool name in the persona fails the test suite.

## Steps

1. Land this spec under `docs/specs/reasoner-bridge-tool-parity.md` - produces
   the contract.
2. Add `format_tools_paragraph(tools) -> str` beside `NEMOTRON_TOOLS` - produces
   `harness/shared/tool_schemas.py` helper; consumes `NEMOTRON_TOOLS` entries.
3. Compose system prompt in the loop (strip frontmatter + append paragraph);
   log `prompt_sha` on `run_id` events - consumes helper; produces
   `harness/shared/orchestrator/loop.py` behaviour.
4. Rewrite active personas' non-tool prose; remove instructional non-bridge tool
   names - produces `.mango/agents/nemotron-reasoner.md` (and planner/verifier
   for the same load path).
5. Neutralize hard-coded inventories in `agent_prompts.py` templates - produces
   `harness/shared/agent_prompts.py`.
6. Add falsifying tests named by AC-1...AC-5 - produces
   `harness/shared/tests/test_reasoner_bridge_tool_parity.py` (name flexible).
7. Fill protected-path attestation; `infra-reviewed`; `make ci` - consumes
   attestation rows.

## Files touched

- `docs/specs/reasoner-bridge-tool-parity.md` *(this file; not protected)*
- `harness/shared/tool_schemas.py` *(protected)*
- `harness/shared/orchestrator/loop.py` *(protected)*
- `harness/shared/agent_prompts.py` *(protected)*
- `.mango/agents/nemotron-reasoner.md` *(protected)*
- `.mango/agents/planner.md` *(protected; same load path)*
- `.mango/agents/verifier.md` *(protected; same load path)*
- `harness/shared/tests/test_reasoner_bridge_tool_parity.py` *(new; confirm
  against `protected_paths` if colocated patterns apply)*

## Invariants touched

- INV-8 / INV-9 / INV-10: preserved - no change to broker, pretooluse, or
  executor authorization; only prompt prose and logging.
- INV-5: preserved - no Makefile / gate target removal; attestation skill still
  required for protected edits.
- INV-16: untouched - no cognitive/execution boundary change.

## Validation matrix

- `make test-python` - AC-1...AC-5 selectors
- `make ci` - ruff + mypy + pytest + coverage (≥ `governance-policy.json` →
  `coverage.lines`) + validate + attestation-check when protected paths change
- coverage target: from `governance-policy.json → coverage.lines` (do not
  hard-code)

## Backward compatibility

- Public orchestrator methods (`execute_agent`, `load_agent_prompt`,
  `execute_sequential_thinking_loop`) keep their signatures. `load_agent_prompt`
  may continue returning raw file text for callers that need the file; composition
  happens at system-message assembly inside `execute_agent` (preferred) so
  shadow-planner and other readers of the file are not surprised - **or**
  `load_agent_prompt` gains an optional `compose=True` defaulting to today's
  raw behaviour for one minor release. Prefer compose-at-use-site to avoid a
  behavioural flip for `planner_system_prompt=self.load_agent_prompt("planner")`
  in the shadow path: that path should receive the same composed prompt the
  live reasoner/planner loop would send.
- MCP transport unchanged (already registry-backed).
- Additive log field `prompt_sha` only.

## Open questions

1. Should Claude Code frontmatter `tools:` be deleted, left IDE-only (stripped
   at runtime), or rewritten to bridge names? Recommendation: strip at runtime
   + delete non-bridge names from frontmatter so the file cannot contradict the
   registry under either consumer.
2. Does shadow planner's `planner_system_prompt=` need the composed prompt in
   the same PR? Recommendation: yes - same helper, one call site pattern.
3. Is `agent_start` / one-shot `prompt_sha` at assembly required in addition to
   per-`model_call` logging? Done-when says "on run_id events"; `model_call`
   already has `run_id`. Prefer logging on every `model_call` (system is stable
   per agent turn) plus once at assembly for turns with zero model calls if that
   path exists.
