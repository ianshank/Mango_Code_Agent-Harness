# Agentic SSD Governance Harness v2.0

This package is a resynthesis of the original Node/JVM governance harness after adversarial peer review. It separates **execution-time policy enforcement** from **repository conformance evidence**, centralizes security-critical policy logic, and adds first-class agent/sub-agent governance.

## Package layout

- `shared/` — byte-identical policy kernel, canonical agent policy, schemas and adversarial self-tests.
  - `shared/mango_mas_orchestrator.py` — Orchestrator for the Mango Multi-Agent System.
  - `shared/tests/` — **Python AQA Engine** (138 Tests / 85.37% Coverage) executing governance rules in-process.
- `node/` — Node/TypeScript adapter and full 7-tier test matrix.
- `jvm/` — JVM/Gradle/Kotlin adapter.
- `control-plane/` — verifier, policy bundle, required-workflow example and reference PDP intended for an independently protected governance repository/service.
- `diagrams/` — C4 Mermaid, Lucid-importable draw.io, SVG and PNG renders.
- `docs/` — **`BENCHMARK_REPORT.md`**, **`C4_ARCHITECTURE.md`**, and other architectural documentation.

## Trust boundary

The project repository is **not its own root of trust**. CI verifies conformance and emits evidence. Network/write/destructive authority belongs to an external policy enforcement point whose policy version is pinned independently. Native pre-push and agent PreToolUse guards provide fast local enforcement but are not described as impossible to bypass.

## Template adoption

The raw pack intentionally fails `validate_adoption.py` until the adopter supplies reviewed action SHAs, approved remotes, an external root-of-trust declaration, and stack lock/verification state. CI additionally requires a strict spec validator. Missing security tooling is never interpreted as a clean pass.

## Self-test

Run `python3 shared/tests/test_harness.py`. The suite validates the cross-stack contract, golden remote vectors, fail-closed guard behavior, external digest verification, action-specific agent approvals, exact zero-skip waivers, supply-chain declarations, strict CI spec posture, and byte identity of the shared policy kernel.
