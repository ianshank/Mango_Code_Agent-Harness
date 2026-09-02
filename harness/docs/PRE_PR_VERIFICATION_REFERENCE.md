# Pre-PR & AQA Verification Reference Guide (v2.1.9)

This document provides a reference architecture and checklist for developer and agent verification prior to opening Pull Requests on the Agentic SSD Harness platform.

---

## 1. Governance & Security Invariants

`harness/CONTRACT.md` is the authoritative definition of every invariant; this
table is a verification index onto it. Where the two disagree, the contract wins
— and the numbering below was previously wrong for INV-5 and INV-7, which is the
kind of drift a table like this creates if it is treated as a second source of
truth rather than an index.

| Invariant | Name | Description | Verification Command |
| :--- | :--- | :--- | :--- |
| **INV-1** | Secret Sanitization | Secret scan covers working tree and full history, failing closed when tooling is absent. | `make secrets-install && make secrets` (also a dedicated CI job) |
| **INV-2** | Zero Unapproved Skips | Skipped tests are failures without a live, decision-backed exemption. | `make verify-zero-skips` (Node) + `make verify-zero-skips-python` (Python, DEC-026/DEC-030 — run after `make coverage-python`, which writes the evidence) |
| **INV-3** | Remote Allowlist | One shared remote URL normalizer gates every push target. | `make remotes` |
| **INV-4** | Non-Destructive Hooks | Git hooks install into Git's effective hooks path and never silently overwrite. | `python harness/shared/validate_adoption.py` |
| **INV-5** | CI Gate Coverage | CI invokes every policy-required gate by Make target; meta-tests detect omissions. | `pytest harness/shared/tests/test_ci_gate_*.py` |
| **INV-6** | Root of Trust | The repository is not its own root of trust; policy digests are anchored externally. | `python harness/shared/validate_policy.py` |
| **INV-7** | Bounded Delegation | Agent delegation transfers no authority; every side effect carries actor/trace/policy evidence. | `pytest -m governance` |
| **INV-8** | Approved Execution Broker | Generated code executes only through the approved broker, **and that broker has a live caller**. | `pytest harness/shared/tests/test_invariant_liveness.py harness/shared/tests/test_governance_broker.py harness/shared/tests/regression/test_guard_reachability_regression.py` |
| **INV-9** | Deterministic Verdict | A candidate receives a deterministic policy verdict before execution or scoring, and an unavailable backend denies rather than falling back to the host. | `pytest harness/shared/tests/test_invariant_liveness.py harness/shared/tests/test_governance_broker.py` |
| **INV-10** | Terminal DENY | A DENY verdict is terminal; no model may override it. | `pytest harness/shared/tests/test_invariant_liveness.py harness/shared/tests/test_governance_broker.py` |
| **INV-11** | Critique Evidence | Every repair attempt carries a normalized critique and immutable evidence ID. | `pytest harness/shared/tests/test_evidence_manifest.py` |
| **INV-12** | Bounded Repair | Repair loops stop at budget and produce FAILED or BLOCKED, never synthetic success. | `pytest -m neurosym` |
| **INV-13** | Verified Digests | A "verified" result includes policy, test, sandbox, source, and tool-version digests. **Not currently satisfiable** — `ProcessBackend` contains but does not isolate, so no sandbox digest exists to record (DEC-010, `harness/CONTRACT.md`). | `pytest harness/shared/tests/test_evidence_manifest.py` |
| **INV-14** | Redacted Export | Exportable traces are redacted and approved before dataset export. | `pytest -k redact` |
| **INV-15** | LATS Disabled | LATS stays disabled until its cost-adjusted threshold is met. | `pytest -m neurosym` |
| **INV-16** | Cognitive Boundary | No `CognitiveSignal` field reaches a control path, selects a tool/model, or alters tool exposure. | `pytest -m governance` + static scan in `test_shadow_planner.py` |

Two invariants enforced by `validate_invariants.py` sit outside this numbering
and are checked on every `make validate`: the per-file **size budgets**
(`limits.size_budget_lines` for source modules, `limits.test_size_budget_lines`
for test modules; neither is a hard-coded number) and the **protected-path**
gate, whose patterns are proven live by `test_protected_path_liveness.py`.

---

## 1a. Debugging a failing gate

Every gate prints its verdict to **stdout** and its diagnostics to **stderr**, so
raising verbosity can never change what a gate reports. Set `LOG_LEVEL` to see
what a gate actually inspected:

```bash
LOG_LEVEL=DEBUG make validate            # all governance validators, verbose
cd harness/node && LOG_LEVEL=DEBUG python ../shared/governance/check_traceability.py
```

`LOG_LEVEL` accepts level names (case-insensitive) and numeric levels; an
unusable value degrades to the default rather than failing the gate — verbosity
misconfiguration must never turn a passing gate red. The helper is
`harness/shared/json_logging.configure_gate_logging`, shared by every stack via
the existing re-export shims.

Worked example — the traceability gate at `DEBUG` reports which globs matched
which files, which is the fastest way to spot a glob scoped to one stack that is
silently checking nothing outside it:

```
DEBUG: spec_globs glob 'docs/specs/**/*.md' matched 2 file(s)
DEBUG: discovered 6 requirement ID(s): ['C-AI-SEC-1', 'C-GOV-1', 'R-AI-NEMO-1', 'R-AI-NEMO-2', 'R-AI-RES-3', 'R-GOV-2']
```

Those are the real numbers. This example previously read `3 file(s)` and
`15 requirement ID(s)`, which no run produces — and the sentence above says this
output is the fastest way to spot a glob silently checking nothing outside one
stack. That is exactly what it is doing: `check_traceability` runs with
`cd harness/node`, so the nine specs under the repository-root `docs/specs/` are
traced by nothing. Invented numbers hid the finding the example exists to
surface.

On failure it also names *which side* each requirement is missing from
(`absent from implementation and tests`), rather than only that something is
missing.

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

- **Python (Pytest):** thresholds are read dynamically from `harness/shared/governance-policy.json`
  by `harness/shared/coverage_gate.py`, which applies `coverage.lines` and `coverage.branches`
  as two separate floors (with `branch = true`, pytest-cov's single total is a blended
  statements+branches number, so a single `--cov-fail-under` would mislabel what the lines
  floor gates), plus the `lines` floor **per measured file** whenever `coverage.per_file` is true, which it currently is — one untested module turns CI red regardless of aggregate headroom (`coverage_gate.check_per_file`). Never restate the number here or anywhere else: quoting it
  recreates the drift the dynamic lookup exists to prevent. Measured roots are `harness/shared`,
  `harness/api_server` and `harness/control-plane`; `test_ci_gate_coverage.py` fails if a root
  declared in `pyproject.toml` is not actually passed to the gate.
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
python -m pytest harness/shared/tests/ harness/api_server/tests/ -m "not live" \
  --cov=harness/shared --cov=harness/api_server --cov=harness/control-plane \
  --cov-report=term-missing --cov-report=json
python harness/shared/coverage_gate.py   # lines and branches floors from governance-policy.json

# 3. Spec, Remote Allowlist & Secret Scan Gates
make specs      # bash validate_specs.sh — `bash` is required: the script is mode 644
make remotes    # every configured push URL against the governance allowlist
# `secrets` is intentionally NOT part of `make ci`: the scan is interpreter-independent,
# so the root workflow runs it once in a dedicated job rather than on all three matrix
# legs. Run it locally when you have the pinned tool:
make secrets-install && make secrets

# 4. Governance Invariant Validators
python harness/shared/governance/verify_zero_skips.py --vitest-json harness/node/.governance/vitest-results.json --decision-log harness/node/.governance/decision-log.md --waivers harness/node/.governance/skip-waivers.json
python -c "import subprocess, sys; scripts = ['validate_governance_docs.py', 'validate_policy.py', 'validate_adoption.py', 'validate_agent_policy.py', 'check_projections.py', 'governance/check_traceability.py', 'validate_invariants.py']; [subprocess.check_call([sys.executable, f'../shared/{s}'], cwd='harness/node') for s in scripts]"
```

---

## 4. Agent Skills & MCP Integration Reference

- **`.mango/skills/nemotron-reasoner/SKILL.md`**: Native Antigravity skill executing `harness/shared/nemotron_bridge.py`.
- **`.mango/skills/`**: Ecosystem skills including `harness-engineering`, `repo-invariant-review`, and `openspec-peer-review`.
- **Context7 MCP**: [Planned] Upstash Context7 MCP integration via `CONTEXT7_API_KEY` for live documentation queries.
