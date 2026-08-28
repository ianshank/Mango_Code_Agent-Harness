---
name: boundary-invariant-review
Reviewed: 2026-08-28
description: >
  Review a change against the one-directional cognitive/execution boundary —
  the cognitive plane proposes, the harness disposes. Checks that no
  CognitiveSignal field reaches a control path, that producer identity carries
  no authority, and that observation-mode code holds no tool schema. Use for
  any diff touching cognitive_signal.py, shadow_planner.py, a CognitiveSignalSink
  caller, or introducing a new cognitive-plane producer.
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# boundary-invariant-review

Constraints C-MMI-1/2/3 (`docs/specs/mangomas-integration-core.md`) and INV-16
(`harness/CONTRACT.md`) are **negative** invariants: they say what must never
happen. Negative invariants rot silently — the existing static scan pins the
module names that exist today and says nothing about the next cognitive-plane
producer someone adds. This skill is the review that asks the question the
other review skills do not: *does this diff give a cognitive-plane field
authority?*

Neither existing review skill covers it. `repo-invariant-review` predicts
mechanical CI collisions; `openspec-peer-review` runs four generic personas.

## 1. The one rule

The cognitive plane proposes; the harness disposes. Nothing crossing that
boundary may acquire the ability to act, and no value produced on the far side
may steer execution on this side.

## 2. When to run this

- Any diff touching `harness/shared/cognitive_signal.py` or
  `harness/shared/shadow_planner.py`.
- Any new caller of `CognitiveSignalSink`, or a new signal `producer_id` /
  `signal_type`.
- Any new observation-mode or shadow-mode execution path.
- Any change to the guarded block in
  `mango_mas_orchestrator.execute_sequential_thinking_loop`.
- Promotion of an observation-mode component to a controlling one — always,
  and see §6 first.

## 3. The four falsifiable checks

Each is answerable from the diff; none requires judgment about intent.

1. **No envelope field is read by a control path.** No `if`, `while`, ternary,
   comparison, or sort key consumes `confidence`, `producer_id`, or
   `producer_version`. `confidence` is untrusted metadata by contract
   (C-MMI-1); the moment it gates a branch, an unauthenticated producer picks
   that branch.
2. **No envelope field selects a resource.** No signal field chooses a model,
   tool, filesystem path, timeout, or endpoint.
3. **Observation call sites hold no tool authority.** Every `complete_chat`
   call on an observation path passes `tools=[]` and omits `tool_choice`.
   Watch the default: `execute_agent(..., tools=None)` falls back to
   `NEMOTRON_TOOLS`, which contains `write_file` and `run_command` — routing
   an observation pass through it re-arms full authority without changing a
   single tool literal.
4. **Observation modules import no orchestrator surface.** They receive frozen
   value objects. A module that holds the orchestrator instance holds
   `execute_agent`, `_execute_run_command`, `_run_hook`, and mutable
   conversation state, whatever its own code currently calls.

## 4. How to prove each

```bash
# Executable proof: the boundary suite (byte-identity, zero-authority,
# envelope invariance, containment).
python -m pytest -m governance -q

# Reviewer's manual pass over a diff — every hit needs a justification.
git diff origin/main...HEAD -- '*.py' | grep -nE '^\+.*(confidence|producer_id|producer_version)' 
git diff origin/main...HEAD -- '*.py' | grep -nE '^\+.*(NEMOTRON_TOOLS|META_TOOLS_SCHEMA|execute_agent|tool_choice)'
```

A grep hit is not automatically a violation — recording a field into a signal
payload is fine, branching on it is not. Read each hit and say which it is.

## 5. The containment check

Any new observation path must be **double-contained** (C-MMI-5): the module
itself never raises, and the caller wraps it and logs. Both, not either.

There is a live trap here: `mango_mas_orchestrator._run_hook` runs hooks with
`check=True` and re-raises on failure. Anything routed through the hook
mechanism is therefore **not** contained, and a failing observation hook would
abort the incumbent loop. Observation work belongs on the guarded in-process
path or out of band, never in a `post-<agent>-run` hook.

## 6. Non-negotiables

- A "small exception" letting one envelope field gate one branch is the whole
  boundary. There is no small version of this.
- Promotion of a shadow producer to a controlling one goes through a passing
  preregistered experiment and then the `governance-policy.json` change
  described in the spec's Open questions — never through a code path, and
  never as a side effect of a feature PR.
- Never widen a signal schema to carry a permission, capability, role grant,
  or path. The envelope is identity and telemetry only.
- If this review cannot reach a verdict from the diff, say BLOCKED and name
  the missing evidence. Do not pass on inspection alone.
