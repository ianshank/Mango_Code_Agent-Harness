---
name: validation-runner
description: >
  Run the full deterministic validation gate for this repository — ruff, mypy,
  pytest, coverage, check-dedup, and validate_invariants — and collect the
  evidence a release needs. Use before opening a PR, before tagging a release,
  or whenever a change must be shown gate-clean. Produces a structured PASS/FAIL
  verdict with per-stage results rather than running stages piecemeal.
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# Validation Runner Skill

Runs the canonical validation matrix declared by the root `Makefile` and
governance-policy.json, in one deterministic pass, and reports a structured
verdict. This is the single entry point the `verifier` role and the `pre-pr`
gate should call.

## When to use

- Before opening any PR (the `pre-pr` target calls this).
- Before tagging a release.
- After a speculative change, to confirm gates are still green.
- When asked "is the repo green right now?"

## What it runs (in order)

```bash
make ci   # ruff + mypy + pytest + coverage + check-dedup + validate_invariants
```

`make ci` is the source of truth; this skill does not re-declare the stages
(they live in the Makefile and governance-policy.json so they cannot drift).
The coverage threshold is read dynamically from
`governance-policy.json` → `coverage.lines` (currently 90).

## Verdict structure

Report exactly one of:

- **PASS** — every stage exited 0; coverage ≥ policy threshold; no
  untracked files in protected paths.
- **FAIL** — list the first failing stage, its exit code, and the first five
  offending lines. Do not run later stages to "rescue" a FAIL; report and stop.

Include per-stage: tool, exit code, pass/fail, and (for coverage) the total
percentage and the threshold it was measured against.

## Non-negotiables

- Never mark PASS on code inspection alone — execute the matrix.
- Never add test waivers or `xfail` to make a stage green; a waiver requires a
  decision-log entry (`INV-2`).
- For protected-path infra changes, run with `ALLOW_GITHUB_CHANGES=1` and
  record the per-change review attestation in the PR description.
