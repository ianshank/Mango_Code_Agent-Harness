---
name: repo-invariant-review
Reviewed: 2026-08-28
description: >
  Check a change against this repository's mechanically enforced invariants — protected
  paths, the policy-sourced size budgets (`limits.size_budget_lines`,
  `limits.test_size_budget_lines`), testing thresholds, and architectural drift.
  Use before opening a PR, when reviewing someone else's change or proposal, or whenever a
  plan proposes touching core models, the orchestrator, or agent personas.
  Predicts concrete CI failures rather than offering style opinions.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# repo-invariant-review — predict CI collisions before you push

Generic peer review asks whether a change is *good*. This asks a narrower and more
falsifiable question: **would this change collide with a rule this repo already enforces?**

Every check maps to a gate that exists in CI, so a finding predicts a specific job failing —
never a matter of taste.

## 1. Preconditions (input contract)

- A git repository or local filesystem path.
- Python 3.10+, stdlib only. No network, no external dependencies.
- Run from the repo root so the checks can read the repo's own sources of truth.

## 2. Procedure (the E2E steps)

```bash
make validate   # `python harness/shared/validate_invariants.py` is denied from inside
                # the loop: a bare `python <script>.py` is unmodelled by
                # command_actions.classify, so it resolves to an action no role holds.
```

1. **Run** it against the branch before pushing.
2. **Read** each finding: `BLOCKING` predicts a red CI job.
3. **Act** on the `remedy` line — each names the specific fix, not a general direction.

## 3. What it checks, and what each predicts

| Check | Predicts a failure in | Typical remedy |
|---|---|---|
| `coverage` (a separate gate, `coverage_gate.py`, not this validator) | `governance-policy.json` → `coverage.lines` and `coverage.branches`, plus the per-file lines floor when `coverage.per_file` is true | write unit tests |
| `protected_paths` | The enforcement layer (Makefile, workflows, validators, roots of trust), the agent control surface (CLAUDE.md, agent-policy, skills, hooks), and the runtime enforcement layer -- the modules that execute and gate a tool call (`tool_executors.py`, `orchestrator/**`, `nemotron_bridge.py`, `tool_schemas.py`, `agent_prompts.py`, `tool_dispatch.py`, root `conftest.py`; DEC-042) | land the change with the `infra-reviewed` human attestation, or use `knowledge_gap_log` |
| `size_budget` | `governance-policy.json` → `limits.size_budget_lines` (per-file ceiling on non-test Python) | split the module |
| `no_hardcoded_secrets` | CI secret scan | move strings to `.env.example` and read from `os.environ` |

## 4. Limits worth knowing

- It predicts *collisions*, not correctness. A change can pass every check here and still be
  wrong; run the full verification gate as well.
