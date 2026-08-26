# Spec: <feature name>

> Scaffolded by `make spec NAME=<feature>`. Fill every section; a spec is the
> contract the `verifier` role checks against. Without one, "done" is undefined.

## Problem statement

What is wrong or missing? Attach evidence — a failing test, a user report, a
governance gap, or a charter gap. No evidence, no spec.

## Acceptance criteria

Objective, testable, each tied to a specific validation stage. No criterion may
be "looks right" or "reads well".

- [ ] AC-1: <observable, executable check> — verified by `make <stage>`
- [ ] AC-2: ...

## Invariants touched

Which of `INV-1..INV-7` (see `harness/CONTRACT.md`) does this change affect, and
how does the invariants checker prove they still hold?

- INV-?: <how it is preserved / verified>

## Validation matrix

The exact stages that prove done. Thresholds are read from
`harness/shared/governance-policy.json` — do not hard-code values here.

- `make ci` — ruff + mypy + pytest + coverage (≥ `coverage.lines`) + check-dedup + validate_invariants
- coverage target: <total percentage> from `governance-policy.json → coverage.lines`

## Backward compatibility

The deprecation / compatibility path for existing callers. If this is a breaking
change, name the migration and the release that removes the old path.

## Open questions

Unresolved decisions. Each should block implementation until answered and
recorded in the decision log.
