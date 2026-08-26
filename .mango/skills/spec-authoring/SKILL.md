---
name: spec-authoring
description: >
  Author a spec-driven feature brief into docs/specs/ using the repo's spec
  template. Captures problem statement, acceptance criteria, invariants touched,
  and the validation matrix that proves done. Use before implementation begins,
  so the planner -> reasoner -> verifier loop has an objective, reviewable
  target instead of an ad-hoc prompt.
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# Spec Authoring Skill

Turns a feature brief into a reviewable spec under `docs/specs/`, following the
canonical template (`make spec NAME=<feature>` scaffolds it). A spec is the
contract the `verifier` role checks against — without one, "done" is undefined.

## When to use

- At the start of any non-trivial change (the planner role should produce or
  consume a spec before delegating to the reasoner).
- When a feature lacks acceptance criteria.
- Before `openspec-peer-review` — the peer review validates the spec, so the
  spec must exist and follow the template.

## How it runs

```bash
make spec NAME=my-feature   # scaffolds docs/specs/my-feature.md from template
```

Then fill the sections declared by `docs/specs/SPEC_TEMPLATE.md`.

## Required sections (must all be present)

- **Problem statement** — what is wrong or missing, with evidence (a failing
  test, a user report, a governance gap).
- **Acceptance criteria** — objective, testable, each tied to a specific
  validation stage. No criterion may be "looks right".
- **Invariants touched** — which of `INV-1..INV-7` (CONTRACT.md) this change
  affects, and how the invariants checker proves they still hold.
- **Validation matrix** — the exact `make ci` stages and coverage threshold that
  prove done, read from `governance-policy.json`.
- **Backward compatibility** — the deprecation/compat path for existing callers.

## Non-negotiables

- Every acceptance criterion must map to an executable check, not prose.
- No hard-coded values in the spec; thresholds reference the policy file.
- The spec is peer-reviewed via `openspec-peer-review` before implementation.
