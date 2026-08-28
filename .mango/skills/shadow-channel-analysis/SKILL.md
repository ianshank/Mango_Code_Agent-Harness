---
name: shadow-channel-analysis
Reviewed: 2026-08-28
description: >
  Analyze the cognitive-signal JSONL sink produced by the shadow planner channel
  and report plan agreement, wall-clock ratio, and token ratio against the
  preregistered UC-4 kill criteria. Use when MANGO_SHADOW_PLANNER has been
  enabled over a run set and a shadow producer must be judged, or when auditing
  sink health. Reports a measured verdict against thresholds fixed before the
  data was seen — never a post-hoc narrative.
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# shadow-channel-analysis

`docs/specs/mangomas-integration-core.md` names this as the first deliverable
of the UC-4 experiment step: *"an agreement/latency/token reporter over
`cognitive-signals.jsonl`"*. The kill criteria are **preregistered** in
`docs/research/mangomas-v2-integration-use-cases.md` (UC-4).

That preregistration is the whole point. An experiment whose analysis
procedure is written after the data is seen is not preregistered — it is a
narrative. This skill freezes the method now, before any real producer exists.

## 1. When to use

- After a run set executed with `MANGO_SHADOW_PLANNER=1`.
- Before any claim about a shadow producer's quality is made anywhere.
- When auditing sink health (size, pairing integrity, validity).

## 2. Preconditions — refuse to proceed without these

- The flag was set for the **whole** run set. A partial run set silently
  biases every ratio; report the gap instead of analyzing.
- Sink located at `$MANGO_SIGNAL_DIR` or
  `<workspace>/.mango/memory/signals/cognitive-signals.jsonl`.
- **Every line re-validated through `cognitive_signal.validate_signal_dict`
  before analysis.** A hand-edited sink is not evidence. Report the count of
  invalid lines; do not silently skip them.

## 3. Pairing procedure

1. Group signals by `run_id`.
2. Within a run, the `plan.shadow` signal's `parent_signal_id` MUST equal the
   `plan.incumbent` signal's `signal_id`.
3. Discard unpaired signals — and **report the discard count and rate**.
   Silently dropping unpaired records is how agreement rates get inflated: a
   shadow pass that failed and wrote nothing looks identical to one that never
   ran.

## 4. The three measurable criteria

Thresholds are cited from the research doc, never chosen here:

| Criterion | Source of threshold | Data |
|---|---|---|
| Plan agreement on gate-relevant steps | research doc UC-4 | `payload.plan` / `payload.plan_sha256` |
| Wall-clock ratio (shadow ÷ incumbent) | research doc UC-4 | `payload.elapsed_ms` on both signals |
| Token ratio (shadow ÷ incumbent) | research doc UC-4 | `payload.usage` on the shadow signal |

Report each as a measured value against its threshold, plus the sample size.
An agreement rate over fewer runs than the research doc's stated sample is a
preliminary reading and must be labeled as one.

Note the current asymmetry: incumbent signals carry `elapsed_ms` but no token
usage (the incumbent path's provider response is not captured). Report the
token criterion as **BLOCKED on incumbent instrumentation** rather than
computing a one-sided number.

## 5. The criterion this skill cannot measure

Mutation score / defect recurrence requires promoted plans and a mutation run.
Report it **BLOCKED**, never "N/A" and never silently omitted. A verdict that
quietly drops a preregistered criterion is not a verdict.

## 6. Sink hygiene

Report line count and file size on every run. The sink is append-only and
gitignored under `.mango/memory/`; `CognitiveSignalSink` enforces a per-signal
size ceiling but the file itself is operator-pruned. Prune only after export.

## 7. Non-negotiables

- `confidence` is untrusted metadata (C-MMI-1) and must never enter a score,
  weight, or ranking — not even as a tiebreak.
- A positive result is a **proposal**. Promotion requires the protected
  `governance-policy.json` change described in the spec's Open questions, with
  human review — never a code path, never this skill's output alone.
- **A negative result is the modal expected outcome** (the scaling literature
  cited in the research doc predicts it for tool-heavy sequential work).
  Reporting "the harness stays single-agent" is a successful outcome of the
  experiment, not a failure of it. Do not search for a framing that rescues
  the producer.
