# Pre-PR & AQA Verification Reference Guide (v2.1.6)

This document provides a reference architecture and checklist for developer and agent verification prior to opening Pull Requests on the Agentic SSD Harness platform.

---

## 1. Governance & Security Invariants

| Invariant | Name | Description | Verification Command |
| :--- | :--- | :--- | :--- |
| **INV-1** | Secret Sanitization | All logs, exceptions, and traces must redact API tokens. | `pytest -k test_secret` / `vitest run tests/ai/security` |
| **INV-2** | Zero Unapproved Skips | No tests may be skipped without an unexpired waiver in `skip-waivers.json`. | `python harness/shared/governance/verify_zero_skips.py` |
| **INV-3** | Remote Allowlist | Only whitelisted remotes in `allowed-remotes.txt` are push targets. | `python harness/shared/governance/remotes.py` |
| **INV-4** | Non-Destructive Hooks | Git hooks must verify environments non-destructively. | `python harness/shared/validate_adoption.py` |
| **INV-5** | Size Budget | All code files must remain under 500 lines. | `python harness/shared/validate_invariants.py` |
| **INV-6** | Root of Trust | Governance policy files must match cryptographic digest anchors. | `python harness/shared/validate_policy.py` |
| **INV-7** | Traceability | All requirements must be bidirectionally linked. | `python harness/shared/governance/check_traceability.py` |

---

## 2. 7-Tier Test Matrix Coverage

```text
                 ▲
                / \     Tier 7: Sanity & Stress Tests (Resilience & Concurrency)
               /---\    Tier 6: Security & Secret Sanitization Tests (INV-1 Leak Check)
              /-----\   Tier 5: User Journey Tests (Multi-Agent Delegation Workflows)
             /-------\  Tier 4: E2E Tests (CLI Terminal & Autonomous Autoplay)
            /---------\ Tier 3: Functional Tests (Match Progression & Multi-Turn Chats)
           /-----------\Tier 2: Integration Tests (SSE Streaming & Engine Events)
          /-------------\Tier 1: Unit Tests (Vector Math, Physics, Config, SecretMasker)
```

### Coverage Thresholds

- **Python (Pytest):** threshold is read dynamically from `harness/shared/governance-policy.json`
  (`coverage.lines`, currently **90%**) into `Makefile`'s `COV_MIN`, so the gate and the policy
  cannot silently drift; enforced as `--cov-fail-under=$(COV_MIN)` and aggregate-only (per-file
  is a documented follow-up — `harness/CONTRACT.md`). Never hard-code this percentage elsewhere;
  read it from the policy file.
- **Node (Vitest):** >= 90% lines, 90% statements, 80% branches, 90% functions enforced per file.
- **Policy artifact drift** (`harness/control-plane/policy-artifact.json`): not a coverage metric,
  but gated the same way — `test_committed_artifact_matches_working_tree` fails the pytest stage
  if `governance-policy.json` or `agent-policy.json` changes without regenerating the artifact.

---

## 3. Pre-PR Execution Steps

Run the following pipeline locally before opening or merging a PR:

```bash
# 1. Format and Lint Node Stack
cd harness/node
pnpm exec prettier --write .
pnpm exec knip
pnpm exec tsc --noEmit
pnpm exec vitest run --reporter=default --reporter=json --outputFile.json=.governance/vitest-results.json

# 2. Python Linting, Typecheck & Tests
cd ../..
python -m ruff check harness/shared/ harness/shared/tests/ harness/api_server/
python -m mypy harness/shared harness/api_server --explicit-package-bases
python -m pytest harness/shared/tests/ harness/api_server/tests/ -m "not live" --cov=harness/shared --cov=harness/api_server --cov-fail-under=80

# 3. Governance Invariant Validators
python harness/shared/governance/verify_zero_skips.py --vitest-json harness/node/.governance/vitest-results.json --decision-log harness/node/.governance/decision-log.md --waivers harness/node/.governance/skip-waivers.json
python -c "import subprocess, sys; scripts = ['validate_governance_docs.py', 'validate_policy.py', 'validate_adoption.py', 'validate_agent_policy.py', 'check_projections.py', 'governance/check_traceability.py', 'validate_invariants.py']; [subprocess.check_call([sys.executable, f'../shared/{s}'], cwd='harness/node') for s in scripts]"
```

---

## 4. Agent Skills & MCP Integration Reference

- **`.agents/skills/nemotron-reasoner/SKILL.md`**: Native Antigravity skill executing `harness/shared/nemotron_bridge.py`.
- **`.mango/skills/`**: Ecosystem skills including `harness-engineering`, `repo-invariant-review`, and `openspec-peer-review`.
- **Context7 MCP**: [Planned] Upstash Context7 MCP integration via `CONTEXT7_API_KEY` for live documentation queries.
