# Agentic SSD Governance Harness v2.0

This package is a resynthesis of the original Node/JVM governance harness after adversarial peer review. It separates **execution-time policy enforcement** from **repository conformance evidence**, centralizes security-critical policy logic, and adds first-class agent/sub-agent governance.

## Package layout

- `shared/` — byte-identical policy kernel, canonical agent policy, schemas and adversarial self-tests.
  - `shared/mango_mas_orchestrator.py` — Orchestrator for the Mango Multi-Agent System (with JSON logging).
  - `shared/mcp_server.py` — Model Context Protocol (MCP) server for local tool execution and workspace context provisioning.
  - `shared/experimental/lats_optimizer.py` — Language Agent Tree Search (LATS) module for Monte-Carlo MCTS planning and rollout execution; parked under `experimental/` until a runtime path is specified (DEC-027, INV-15).
  - `shared/meta_tools.py` — Meta-learning and context state tools for autonomous synthesis.
  - `shared/governance/` — Extracted policy evaluation **and execution** mechanisms: traceability, zero-skips, guards, the `ExecutionBroker` that INV-8 names, and the in-process policy decision point.
  - `shared/tests/` — **Python AQA Engine** executing governance rules in-process.
- `node/` — Node/TypeScript adapter and full 7-tier test matrix.
- `jvm/` — JVM/Gradle/Kotlin adapter.
- `control-plane/` — verifier, policy bundle, required-workflow example and reference PDP intended for an independently protected governance repository/service.
- `docs/` — **`BENCHMARK_REPORT.md`**, `AGENT_GOVERNANCE.md`, `ROOT_OF_TRUST.md` and `PRE_PR_VERIFICATION_REFERENCE.md`. The C4 model lives at the repository's `docs/architecture/c4_architecture.md`; historical reports (`TEST-REPORT.md`, `PEER-REVIEW-REMEDIATION.md`) are under `docs/reports/`.

## Trust boundary

The project repository is **not its own root of trust**. CI verifies conformance and emits evidence. Network/write/destructive authority belongs to an external policy enforcement point whose policy version is pinned independently. Native pre-push and agent PreToolUse guards provide fast local enforcement but are not described as impossible to bypass. A local in-process decision point and execution broker apply the same authority model on the agent's live tool-call path; they fail closed, contain rather than isolate, and do not replace the external enforcement point (see `harness/CONTRACT.md`, authority model layer 2).

## Template adoption

The raw pack intentionally fails `validate_adoption.py` until the adopter supplies reviewed action SHAs, approved remotes, an external root-of-trust declaration, and stack lock/verification state. CI additionally requires a strict spec validator. Missing security tooling is never interpreted as a clean pass.

## Self-test

Run `python3 shared/tests/test_harness.py`. The suite validates the cross-stack contract, golden remote vectors, fail-closed guard behavior, external digest verification, action-specific agent approvals, exact zero-skip waivers, supply-chain declarations, strict CI spec posture, and byte identity of the shared policy kernel.
