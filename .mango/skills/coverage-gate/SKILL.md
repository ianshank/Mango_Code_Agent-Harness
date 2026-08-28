---
name: coverage-gate
description: >
  Enforce and report the test-coverage policy gate. Reads the threshold
  dynamically from harness/shared/governance-policy.json (coverage.lines) so the
  gate and the policy never silently drift, then runs pytest --cov and reports
  per-module coverage with missing lines. Use before a PR when coverage may be
  borderline, or to find the modules that most need additional tests.
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# Coverage Gate Skill

Enforces the coverage policy declared in
`harness/shared/governance-policy.json`. The threshold is read dynamically —
never hard-code a percentage here.

## When to use

- Before a PR when the change adds untested code paths.
- When investigating a coverage drop.
- When planning where to add tests for maximum gate impact.

## How it runs

```bash
# thresholds come from governance-policy.json -> coverage.lines and coverage.branches,
# applied as two separate floors by coverage_gate.py (branch = true makes pytest-cov's
# single total a blended number, so --cov-fail-under would mislabel what 'lines' gates)
python -m pytest harness/shared/tests/ harness/api_server/tests/ \
  -m "not live" \
  --cov=harness/shared --cov=harness/api_server --cov=harness/control-plane \
  --cov-report=term-missing --cov-report=json
python harness/shared/coverage_gate.py
```

The gate fails closed if either floor is missed, or if the coverage report or
policy is missing or malformed.

## Report

- Total coverage percentage and the policy threshold it was measured against.
- Modules below the threshold, sorted by missing-line count, with the missing
  line ranges (these are the highest-leverage places to add tests).
- Whether the per-file policy (`coverage.per_file`) is on; if so, flag any file
  under threshold. (A true per-file gate is a documented follow-up; today the
  total gate is enforced.)

## Non-negotiables

- Never lower the threshold to make a change pass. If a drop is legitimate
  (dead code removed, etc.), raise it in a separate, attested change.
- Never exclude modules from coverage to game the number.
- Report the threshold source (`governance-policy.json` → `coverage.lines`)
  in every verdict so a reviewer can verify it was not hard-coded.
