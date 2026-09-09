# Agentic SSD Governance Harness

This package is a resynthesis of the original Node/JVM governance harness after adversarial peer review. It separates **execution-time policy enforcement** from **repository conformance evidence**, centralizes security-critical policy logic, and adds first-class agent/sub-agent governance.

## Package layout

- `shared/` — byte-identical policy kernel, canonical agent policy, schemas and adversarial self-tests.
  - `shared/mango_mas_orchestrator.py` — Orchestrator for the Mango Multi-Agent System (with JSON logging).
  - `shared/context_policy.py` — Policy-sourced context-window budgeting (group-atomic tool-call eviction) applied by `ExecutionLoop` before each `complete_chat` (audit H4; `docs/specs/context-window-budget.md`).
  - `shared/mcp_server.py` — Model Context Protocol (MCP) server for local tool execution and workspace context provisioning.
  - `shared/experimental/lats_optimizer.py` — Language Agent Tree Search (LATS) module for Monte-Carlo MCTS planning and rollout execution; parked under `experimental/` until a runtime path is specified (DEC-027, INV-15).
  - `shared/meta_tools.py` — Meta-learning and context state tools for autonomous synthesis.
  - `shared/governance/` — Extracted policy evaluation **and execution** mechanisms: traceability, zero-skips, guards, the `ExecutionBroker` that INV-8 names, and the in-process policy decision point.
  - `shared/authority_graph.py`, `shared/authority_call_sites.py`, `shared/graph_topology.py` — derived views over the authorization chain and the parked `StateGraph`. Recomputed per query and never persisted, because a stored copy of governance state is a cache whose staleness has a security consequence; the dependency runs one way, so nothing under `shared/governance/` (nor `write_policy.py`, `read_policy.py`, `agent_authority.py`) may import them, and a test decides that by `ast` rather than by grep. None of the three adds a CI target: per DEC-065 a pure function over repository state belongs in the ordinary pytest run, where INV-2's zero-skip discipline already governs it (`ci_required_targets` is unchanged at ten, and `CONTRACT.md` gains no invariant).
  - `shared/code_safety.py` — the same judgement on the live write path rather than the test surface: `execute_generate_code` puts the AST it already parsed to this module and refuses a file naming a `synthesis.prohibited_imports` symbol before any byte lands.
  - `shared/tests/` — **Python AQA Engine** executing governance rules in-process.
- `node/` — Node/TypeScript adapter and full 7-tier test matrix.
- `jvm/` — JVM/Gradle/Kotlin adapter.
- `control-plane/` — verifier, policy bundle, required-workflow example and reference PDP intended for an independently protected governance repository/service.
- `docs/` — **`BENCHMARK_REPORT.md`**, `AGENT_GOVERNANCE.md`, `ROOT_OF_TRUST.md` and `PRE_PR_VERIFICATION_REFERENCE.md`. The C4 model lives at the repository's `docs/architecture/c4_architecture.md`. Reports are under `docs/reports/`: `2026-COUNCIL-STRATEGY-REVIEW.md`, `2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md`, `2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md`, `2026-STANDARDS-AUDIT.md` (the current coding-standards audit and its remediation roadmap), `PEER-REVIEW-REMEDIATION.md`, `ROADMAP-PEER-REVIEW.md`, `ROADMAP-PEER-REVIEW-2026-09-05.md`, `PLAYLIST-ASTRA-CONTEXT-BUDGET-PLAN-2026-09-06.md`, `CONTEXT-WINDOW-BUDGET-PEER-REVIEW-2026-09-06.md`, `CONTEXT-WINDOW-BUDGET-GAP-PEER-REVIEW-2026-09-06.md`, `SDLC_HYGIENE_AND_GAP_ANALYSIS.md`, `SDLC_HYGIENE_REPORT.md` and `TEST-REPORT.md`; this list is checked against the directory by `test_documentation_claims.py`.

## Trust boundary

The project repository is **not its own root of trust**. CI verifies conformance and emits evidence. Network/write/destructive authority belongs to an external policy enforcement point whose policy version is pinned independently. Native pre-push and agent PreToolUse guards provide fast local enforcement but are not described as impossible to bypass. A local in-process decision point and execution broker apply the same authority model on the agent's live tool-call path; they fail closed, contain rather than isolate, and do not replace the external enforcement point (see `harness/CONTRACT.md`, authority model layer 2).

## Template adoption

The raw pack intentionally fails `validate_adoption.py` until the adopter supplies reviewed action SHAs, approved remotes, an external root-of-trust declaration, and stack lock/verification state. CI additionally requires a strict spec validator. Missing security tooling is never interpreted as a clean pass.

## Self-test

Run `python3 shared/tests/test_harness.py`. The suite validates the cross-stack contract, golden remote vectors, fail-closed guard behavior, external digest verification, action-specific agent approvals, exact zero-skip waivers, supply-chain declarations, strict CI spec posture, and byte identity of the shared policy kernel.
