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
- DEC-013 — A local bare `ruff` resolving to 0.15.8 (vs. the pinned 0.6.9 that `python -m ruff`/`make lint`/CI actually use) produced 3 false ruff findings during research; retracted, `main` was already clean under the pinned version, and `harness/__init__.py`/`harness/api_server/__init__.py` (added for namespace-package consistency, briefly reverted on the same false signal) are restored. Wiring `lint-node` into `ci` was tried and reverted for a separate, genuine reason: `make lint-node` currently crashes on a pre-existing `typescript`/`typescript-eslint` version incompatibility unrelated to this batch, so `ci`'s prerequisites stay untouched and this is a tracked follow-up instead. A root `audit` target (pip-audit + delegated Node osv-scanner) closes the `KNOWN_GAPS["audit"]` exception via a dedicated workflow job, mirroring `secrets`. `requirements.txt` splits runtime deps out of `requirements-dev.txt` and joins `protected_paths`. `governance/broker.py` and `check_dedup.py` share one non-raising JSON-parse classifier (`governance_json.py`); `policy_loader.py`, `coverage_gate.py`, and `validate_invariants.py` stay excluded, per `policy-single-source.md`'s standalone-stdlib decision and their own individually-pinned exception messages. A root `.governance/` was again considered and rejected, per DEC-005.

- DEC-014 — `make secrets`'s `gitleaks git` invocation (all three Makefiles) scanned every ref in the local clone, not just the checked-out branch; an unrelated concurrent branch's leaked key was failing PR #35's `secret-scan` even though its diff never touched that branch. `--log-opts="HEAD"` now scopes the scan to the current ref's own ancestry, matching INV-1's intent that a PR's gate be actionable by that PR's author.
- DEC-015 — GitHub Copilot's review of PR #35 found six real defects in the DEC-013/DEC-014 batch, all fixed here: `governance_json.py` now classifies a `UnicodeDecodeError` as `malformed` instead of letting it escape uncaught; `broker.py`'s `_load_json` again raises `FileNotFoundError`/`OSError`/`ValueError` per R-DH-5 instead of one collapsed `ValueError`, with new direct tests; `secrets` joins `pre-pr`'s prerequisites, matching README's claim that `pre-pr` runs both scanners; `pip-audit` is pinned (`PIP_AUDIT_VERSION`) like gitleaks/osv-scanner; a new `audit-matrix` CI job runs `audit-python` across 3.9/3.10/3.12 so a vulnerability specific to another supported interpreter cannot be missed; a new liveness test asserts nothing can guard the audit job behind an `if:`. Also fixed: DEC-013's summary here self-contradicted on whether the two `__init__.py` files ship — the stale sentence is removed.
- DEC-016 — DEC-015's `PIP_AUDIT_VERSION` pin (2.10.1) broke the new `audit-matrix` job's 3.9 leg immediately: `pip-audit` 2.10.0 raised its own floor to `Requires-Python >=3.10`, so 3.9 had no installable candidate. The 3.10/3.12 legs passed clean on the same commit, confirming the matrix design itself was sound. Capped at 2.9.0, the newest release still declaring `Requires-Python >=3.9`.

## Required behavior

1. Read `.governance/policy.json`, `.governance/agent-policy.json`, and the decision log before changing governed controls.
2. Do not grant a child agent authority its declared role does not independently possess.
3. Route external writes and production changes through the independent Tool Broker / PDP and required human approval.
4. Run the named governance gates and preserve their evidence; never convert missing security tooling into a pass.
