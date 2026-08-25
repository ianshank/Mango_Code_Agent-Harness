# Governance Skill

Reviewed: 2026-08-24

## Purpose

Apply the Agentic SSD gate contract, preserve the external root of trust, refuse governance weakening as a means to pass a gate, and require side-effect evidence for governed agent actions.

## Decisions since 2026-08-24

- DEC-000 — Projections are explicitly not applicable in the uninstantiated template; adopters must configure mappings or record a replacement decision.

## Required behavior

1. Read `.governance/policy.json`, `.governance/agent-policy.json`, and the decision log before changing governed controls.
2. Do not grant a child agent authority its declared role does not independently possess.
3. Route external writes and production changes through the independent Tool Broker / PDP and required human approval.
4. Run the named governance gates and preserve their evidence; never convert missing security tooling into a pass.
