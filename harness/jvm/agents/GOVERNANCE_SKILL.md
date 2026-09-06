# Governance Skill

Reviewed: 2026-09-05

## Purpose

Apply the Agentic SSD gate contract, preserve the external root of trust, refuse governance weakening as a means to pass a gate, and require side-effect evidence for governed agent actions.

## Decisions since 2026-08-24

Source of truth: repository-root [`docs/decisions/`](../../../docs/decisions/) (see [`index.md`](../../../docs/decisions/index.md)). The jvm stack does not keep a divergent decision log.

## Required behavior

1. Read `.governance/policy.json`, `.governance/agent-policy.json`, and `docs/decisions/` before changing governed controls.
2. Do not grant a child agent authority its declared role does not independently possess.
3. Route external writes and production changes through the independent Tool Broker / PDP and required human approval.
4. Run the named governance gates and preserve their evidence; never convert missing security tooling into a pass.
