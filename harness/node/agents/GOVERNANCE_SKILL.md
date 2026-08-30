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
- DEC-007 — `protected_paths` is enforced at tool-call time by the write gate, not only by CI; `.git/**` is denied explicitly because git never lists it; the PDP, the write gate and the orchestrator become protected paths.
- DEC-008 — Role tool exposure is derived from `agent-policy.json` (union of canonical contracts minus approval-gated actions), so the verifier no longer holds `write_file`; hook environments are stripped of credentials.
- DEC-009 — The policy decision point runs in process; the reference PDP is retained as the external contract and pinned by an agreement test. The `exists()` fail-open is removed.
- DEC-010 — A command's action is derived from the command and fails closed to an action no role holds; the broker's process backend contains cwd, runtime and output size, and explicitly does not isolate.
- DEC-011 — `run_command` routes through `ExecutionBroker`, so INV-8 is enforced on the live path. Active roles execute as the narrowest canonical contract; `pip install` and other external actions are denied for the reasoner. `test_invariant_liveness.py` ships with no waivers.
- DEC-012 — `read_file` and `apply_patch` join the tool surface behind a new `read_policy.py`, the read-side counterpart to `write_policy.py`; both compose one shared credential-filename pattern with `command_actions.classify` so the shell-command door and the direct-file door cannot drift apart. `apply_patch` reuses `write_denial_reason` unchanged and grades as the same `write` action as `write_file`, so the verifier still holds no write-shaped tool.

## Required behavior

1. Read `.governance/policy.json`, `.governance/agent-policy.json`, and the decision log before changing governed controls.
2. Do not grant a child agent authority its declared role does not independently possess.
3. Route external writes and production changes through the independent Tool Broker / PDP and required human approval.
4. Run the named governance gates and preserve their evidence; never convert missing security tooling into a pass.
