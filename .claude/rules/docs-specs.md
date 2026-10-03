---
description: The contract every file under docs/specs/ must satisfy before make specs will pass.
paths:
  - "docs/specs/**/*.md"
---

# Writing a spec

A spec is the contract the verifier checks against, so `make specs` holds every
file here to a shape. `harness/shared/validate_specs.sh` runs three tiers over
this tree, and `harness/shared/plan_rules.py` carries the rules.

Scaffold rather than starting blank:

```
make spec NAME=<feature>
```

That copies `docs/specs/SPEC_TEMPLATE.md`, which is the only file here exempt
from the checks below.

## Required

- `## Requirements` and `## Acceptance criteria` headings must both be present.
- Requirement identifiers follow `decision_id_pattern` in
  `harness/shared/governance-policy.json` and are traced both ways by
  `harness/shared/governance/check_traceability.py` against
  `.governance/traceability.json`.

## Refused

- Unfalsifiable criteria: the words *works correctly*, *as expected* and
  *appropriately* are rejected outright. Write the observation that would show
  the criterion was not met.
- Unfilled template markers: `R-EXAMPLE-`, `C-EXAMPLE-`, `<feature name>`.
- Criteria that defer to a human judgement instead of stating a check.

## Why there is no AGENTS.md here

`docs/` refuses loose files at its root, `docs/reports/` is a closed index keyed
off `harness/README.md`, and every `docs/specs/**/*.md` is under the contract
above — so a document describing the directory would itself have to pass the
spec gate. This rule file does the same job without fighting three gates
(DEC-070).
