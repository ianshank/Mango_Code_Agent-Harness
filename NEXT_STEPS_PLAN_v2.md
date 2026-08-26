# Next-Steps Implementation Plan — Mango Code Agent Harness

**Author:** Directors of Product / SWE / SQE / Architecture
**Basis:** `harness/CONTRACT.md` v2.0 (INV-1..INV-7), `PROJECT-CHARTER.md` v2.0, `NEXT_STEPS.md` roadmap (v2.2.0 / v2.3.0), `docs/ROOT_OF_TRUST.md`, peer-review remediation matrix, and the post-PR-#4 hygiene state.
**Method:** Spec-driven development — every work item is a spec (R-* requirements, C-* citations) → implementation → full test suite + coverage gate → objective peer review → merge. Backwards-compatible, modular, reusable, dynamic code; no hard-coded values.

---

## 0. Current State (post PR #4)

PR [#4](https://github.com/ianshank/Mango_Code_Agent-Harness/pull/4) closed the immediate hygiene debt: ruff/mypy clean, 161 tests, coverage 86.99%, CI rewired to `make ci`, `validate_invariants` wired (0%→91%), `check-dedup` drift gate added, exception leak + hard-coded key removed. **One governance decision blocks merge:** the protected-paths invariant flags this PR's own `Makefile`/`.github` changes — needs an `ALLOW_GITHUB_CHANGES` escape-hatch policy or a policy update.

---

## Phase 0 — Consolidate Hygiene & Resolve the Governance Escape-Hatch (foundation)

Nothing else should land on `main` until the foundation is deterministic.

| ID | Work item | Spec / invariant | Verifiable exit criteria |
|---|---|---|---|
| 0.1 | Resolve PR #4 protected-path conflict | C-GOV-1, INV-6 | Decide escape-hatch policy: (a) set `ALLOW_GITHUB_CHANGES` in CI for reviewed infra PRs via a labeled path, or (b) update `protected_paths` to scope protected infra to `origin/main` diff only. Document in `CONTRACT.md`. |
| 0.2 | Dedup the 9 governance scripts by import | INV-3 (shared normalizer) | Replace `harness/node/scripts/*.py` + `harness/jvm/scripts/*.py` with thin shims importing `harness.shared.*`; `make check-dedup` stays green; single source of truth. |
| 0.3 | Raise `mango_mas_orchestrator.py` coverage 59%→≥85% | INV-5 | Add tests mocking the Nemotron bridge; mark live-API tests `@pytest.mark.live`; coverage gate ≥80% per-file. |
| 0.4 | Fix stale `protected_paths` (`scripts/*` → `harness/shared/*`) | INV-6 | `governance-policy.json` paths match the real layout; `make validate` passes on a clean tree. |
| 0.5 | Bump `ruff`/`mypy` pins to current | — | `requirements-dev.txt` updated; `make ci` green on 3.11/3.12. |

---

## Phase 1 — Spec-Driven Development Foundation

Make "spec-first" the enforced entry point for all subsequent work.

| ID | Work item | Spec / invariant | Exit criteria |
|---|---|---|---|
| 1.1 | Author `docs/specs/` template + `make spec` target | INV-5 | Spec must carry R-* requirements + C-* citations; `make spec` validates structure + traceability before code is allowed. |
| 1.2 | Wire `openspec-peer-review` skill into the planner→implementer→verifier loop | Charter v2.0 | A spec cannot reach implementation until Architect/SDLC/QA/Product personas sign off (skill already exists; wire the gate). |
| 1.3 | Add `repo-invariant-review` as a mandatory pre-PR step | INV-1..7 | Skill predicts concrete CI collisions (protected paths, 500-line budget, coverage) before push; `make pre-pr` enforces. |

---

## Phase 2 — v2.2.0 Roadmap (spec-driven)

### 2.1 NVIDIA NIM Multi-Model Routing & Token Budgeting
- **Spec:** `R-AI-ROUTING-1` (dynamic model fallback fast-reason→deep-synthesis), `R-AI-COST-1` (prompt cache), `R-AI-SEC-1` (key redaction, already INV-1).
- **Impl:** routing layer in `nemotron_bridge.py` (Python) + `nemotron-client.ts` (Node), model list sourced from env/config (no hard-coded model names), structured logging, jittered backoff + circuit-breaker reuse.
- **Cost:** local disk/memory prompt-cache adapter for repeated invariant-verification prompts; telemetry counters.
- **Tests:** routing fallback matrix, cache hit/miss, backoff/circuit-breaker transitions (3-state); coverage ≥85% on new modules.

### 2.2 NemotronClient as an MCP Server
- **Spec:** `R-MCP-1` — package `NemotronClient` as a standard STDIO/SSE MCP server for external IDEs/clients.
- **Impl:** thin MCP server wrapping the existing bridge; reuse `resolve_base_url()`/`resolve_api_key()` (no duplicated config). Consumes the connected MCP tooling pattern already used in this repo.
- **Tests:** contract tests for each exposed tool; auth via env only.

### 2.3 CI/CD Hardening
- Pin all actions to reviewed full SHAs (`PIN_FULL_COMMIT_SHA` → real SHAs) in the rewritten workflow.
- Wire `make pre-pr` into a local git `pre-push` hook installer (INV-4: install into Git's effective hooks path, never silent-overwrite).
- Add a `guard-probe` self-test that exits 2 on BLOCK (per remediation matrix).

> Pong engine enhancements (WebSocket multiplayer, audio customization, replay recording) are descoped from this governance-focused plan unless explicitly re-prioritized.

---

## Phase 3 — Advanced Agentic Governance (v2.3.0)

| ID | Work item | Spec | Exit criteria |
|---|---|---|---|
| 3.1 | Dynamic policy synthesis | `R-GOV-SYNTH-1` — `nemotron-reasoner` generates TLA+ state-machine invariants for new modules | Generated invariants pass `validate_invariants` + are traced via `check_traceability`. |
| 3.2 | Telemetry dashboard | `R-OBS-1` — OTel export bridge: token counts, API latency p50/p95/p99, circuit-breaker health | Dashboards render from exported spans; no secrets in telemetry (INV-1). |
| 3.3 | Reusable agent skills | `R-SKILL-1` — package governance validation pipeline + coverage gate as cross-project skills | Skills consumed from an independent repo; `skill_max_age_days=90` freshness enforced. |

---

## Phase 4 — Agents & Skills Modernization (cross-cutting; "bring up to date, create additionally needed")

This is the explicit ask. The repo currently has a split: `.mango/agents/` defines 3 roles (`planner`, `nemotron-reasoner`, `verifier`) while the canonical **7-role contracts** live in `harness/{shared,node,jvm}/agents/` (`implementer`, `orchestrator`, `peer-reviewer`, `release-auditor`, `security-reviewer`, `spec-analyst`, `test-eval`). They have drifted.

| ID | Work item | Exit criteria |
|---|---|---|
| 4.1 | Reconcile `.mango/agents` (3) with canonical 7-role contracts | Either promote the 7 roles into `.mango/agents/` or document the authoritative mapping; no silent drift. |
| 4.2 | Wire meta-tools (`knowledge_gap_log`, `hypothesis_register`) into `nemotron-reasoner`'s available tools | Agent `tools:` line includes the meta-tools (currently only `Bash, Read, Grep, Glob`); SKILL.md matches. |
| 4.3 | Create additional skills: `validation-runner`, `coverage-gate`, `spec-authoring` | Each SKILL.md carries `validator_version`, `compatibility`, `version`; passes `validate_governance_docs` freshness. |
| 4.4 | Update all SKILL.md + agent contracts to Charter v2.0 conformance | `skill_max_age_days=90` enforced; `repo-invariant-review` green on each. |

---

## Phase 5 — External Root of Trust (production readiness)

Per `ROOT_OF_TRUST.md`, the repository cannot be its own root of trust.

- Promote `harness/control-plane/verify_repository.py` + `required-workflow.example.yml` to an **independently administered** policy repository.
- That external layer pins `governance-policy.json`, `agent-policy.json`, `Makefile`, CI, and security-critical implementation **digests** before project-local gates run.
- Org required-workflow/ruleset protects governance paths (INV-6).
- High-risk agent authority + side-effect/approval evidence stored outside the mutable project repo (INV-7).

---

## Execution Model

- **Git worktrees:** one worktree per phase/feature branch so phases progress in parallel without clobbering `main`.
- **Spec-first loop:** spec → impl → tests (coverage gate) → `openspec-peer-review` + `repo-invariant-review` → merge. No code merges without a traced spec.
- **Subagents:** `planner` (decompose), `nemotron-reasoner` (deep architectural/security review), `verifier` (run `make ci` + report evidence), plus research subagents for MCP server packaging and OTel bridge.
- **MCPs:** GitHub connector for PR/branch automation; package `NemotronClient` as an MCP server (Phase 2.2); consume connected MCPs where relevant.
- **Determinism:** policy enforcement and release gates stay deterministic; search/critique/repair remain advisory (per project principle).

## Peer-Review Gate (before presenting/merging any phase)

1. `openspec-peer-review` — Architect / SDLC / QA / Product personas sign off.
2. `repo-invariant-review` — predicts concrete CI collisions (protected paths, 500-line budget, coverage, drift).
3. `make ci` green on 3.11/3.12 with coverage ≥80% (per-file) and 0 unapproved skips (INV-2).

---

## Sequencing & Dependencies

```
Phase 0 (consolidate + escape-hatch) ──► Phase 1 (spec-first foundation)
                                              │
                                              ├─► Phase 2 (v2.2.0: routing, MCP, CI SHA-pin)
                                              │        │
                                              │        └─► Phase 4 (agents/skills modernization)
                                              │
                                              └─► Phase 3 (v2.3.0: policy synthesis, telemetry, reusable skills)
                                                       │
                                                       └─► Phase 5 (external root of trust)
```

Phase 0 is the critical path — every later phase assumes a deterministic `make ci`, a single source of truth for the governance kernel, and a resolved protected-path policy.
