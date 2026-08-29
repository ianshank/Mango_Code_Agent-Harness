# Spec: <feature name>

> Scaffolded by `make spec NAME=<feature>`. Fill every section; a spec is the
> contract the `verifier` role checks against. Without one, "done" is undefined.

## Problem statement

What is wrong or missing? Attach evidence — a failing test, a user report, a
governance gap, or a charter gap. No evidence, no spec.

## Requirements

Normative statements of what the change delivers. Every MUST-bullet carries a
requirement ID (`R-<AREA>-<n>` functional, `C-<AREA>-<n>` constraint) so it can
be traced to implementation and tests.

- R-EXAMPLE-1: The feature MUST <observable behavior>, sourced from
  `<config/policy location>` rather than a literal value.
- C-EXAMPLE-1: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`.

## Acceptance criteria

Objective, testable, each tied to a specific validation stage. No criterion may
be "looks right" or "reads well".

- [ ] AC-1: <observable, executable check> — verified by `pytest -k <selector>`
      · stage: `make <stage>` (R-EXAMPLE-1)
- [ ] AC-2: ...

At least one criterion must name a non-success outcome — what this change
rejects, denies, or fails closed on. A plan that only describes success has not
said what going wrong looks like.

## Steps

The ordered work, each step declaring what it reads and what it leaves behind, so
a step that consumes an artifact nothing produces is visible before implementation
starts.

1. <step> — produces `<path>`
2. <step> — consumes `<path>`; produces `<path>`

## Files touched

Every path this change adds or modifies. A path matching `protected_paths` in
`governance-policy.json` needs the `infra-reviewed` attestation; listing them here
is how that is known before the PR is opened rather than when CI goes red.

- `<path>`

## Invariants touched

Which of `INV-1..INV-17` (see `harness/CONTRACT.md`) does this change affect, and
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
