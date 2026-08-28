# Governance Skill

Reviewed: 2026-08-24

## Purpose

Apply the Agentic SSD gate contract, preserve the external root of trust, refuse governance weakening as a means to pass a gate, and require side-effect evidence for governed agent actions.

## Decisions since 2026-08-24

- DEC-000 — Projections are explicitly not applicable in the uninstantiated template; adopters must configure mappings or record a replacement decision.
- DEC-001 — Live smoke tests against remote NVIDIA NIM API are conditionally skipped when endpoints are rate-limited or unavailable.
- DEC-002 — `protected_paths` covers the agent control surface and carries root-relative twins for the multi-stack layout; more changes now require the `infra-reviewed` attestation, by design.
- DEC-003 — The unbound `.mango/hooks/` scripts remain dormant; only the `.claude/` SessionStart hook is live.
- DEC-004 — Unwired policy keys are classified with reviewed reasons instead of deleted; duplicated grammar/limits/tool-pin values are pinned by cross-check tests; coverage is enforced as separate lines and branches floors; the bundle's top-level digests are regenerated inside `digest-regen`.
- DEC-005 — The MAS orchestrator consults the PreToolUse guard in-process from the installed harness, never from `workspace_dir`, and guard unavailability denies. Agent-initiated `git push` is blocked as an accepted consequence: the repository root carries no remote allowlist and the guard fails closed.
- DEC-006 — The guard canonicalises its payload envelope across `tool_input` and `args` and denies a JSON object carrying neither; non-JSON input keeps its existing leg.

## Required behavior

1. Read `.governance/policy.json`, `.governance/agent-policy.json`, and the decision log before changing governed controls.
2. Do not grant a child agent authority its declared role does not independently possess.
3. Route external writes and production changes through the independent Tool Broker / PDP and required human approval.
4. Run the named governance gates and preserve their evidence; never convert missing security tooling into a pass.
