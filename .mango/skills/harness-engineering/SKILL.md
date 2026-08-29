---
name: harness-engineering
Reviewed: 2026-08-28
description: Use when the user wants to inspect, extend, or debug this agent's own harness (hooks, subagents, CLAUDE.md rules) rather than application code. Also use when repeated agent mistakes should be turned into durable repo-level guardrails.
---

# Harness Engineering Skill

Harness = Instructions + Constraints + Feedback + Memory + Evaluation + Governance.

## When invoked
1. Treat this repository's `.mango/` directory as the source of truth for current
   harness behavior. Inspect `settings.json`, `hooks/`, `agents/`, and `CLAUDE.md`
   before proposing changes.
2. **An agent cannot land a harness change.** `.mango/**`, `.claude/**`, `CLAUDE.md`,
   `pyproject.toml`, the `Makefile` and both policies are protected paths, and
   `write_policy.write_denial_reason` refuses them at tool-call time (DEC-007) — not
   at CI time, where the earlier gate lived. Propose the change, record what is
   needed with `knowledge_gap_log`, and let a human land it with the
   `infra-reviewed` attestation.
3. Prefer updating an existing hook/rule over adding a duplicate one.
4. Make new rules enforceable where practical. Of the three classic options, only
   one is reachable from inside the loop: a **test** (tests are writable, except
   `test_protected_path_liveness.py`, `test_ci_gate_coverage.py` and
   `test_coverage_policy_enforcement.py`, which are protected). A hook or a lint
   rule is a protected-path change.
5. If a failure pattern recurs, record it with `knowledge_gap_log` rather than in a
   file. `.mango/FAILURE_MEMORY.md` does not exist and is gitignored.
6. After any harness change, state what changed, why, and how to verify it — with a
   deterministic check, not by provoking the guard. Triggering `rm -rf` in a scratch
   directory proves nothing here twice over: the `.mango` PreToolUse hook is dormant
   (DEC-003) and never fires, and `rm` classifies as `destructive`, which no role
   holds, so the **broker** denies it before any hook could be consulted. Verify with
   `pytest harness/shared/tests/test_write_policy.py test_command_actions.py` and
   `make validate`.

## Reference model (from research)
- Control loop: keep it a simple while-loop (model -> tool -> observe -> repeat); avoid
  adding orchestration complexity unless task genuinely needs sub-agent delegation.
- Context management: cheap-first. Never rely on conversation history for correctness --
  durable state lives outside the conversation. In this repository that means the
  meta-tools (`knowledge_gap_log`, `hypothesis_register`, writing to `.mango/memory/`)
  and the `CognitiveSignal` sink — not `PLAN.md`/`NOTES.md`/`FAILURE_MEMORY.md`, none
  of which exist.
- Verification: deterministic checks (tests, linters, type-checkers) always outrank
  LLM self-assessment. Note what enforces it: `make ci` and the gates it chains, plus
  the runtime controls in the orchestrator. The `pre_completion_checklist.sh` Stop hook
  is **dormant** under DEC-003 and enforces nothing, pinned by
  `test_mango_hooks_stay_dormant`.
- Cost discipline: minimize "no-action turns" (turns with no file edit and no command).
  Batch related reads/searches instead of issuing them one at a time.

## Do not
- Do not copy generic harness templates blindly -- adapt to this repo's actual stack,
  package manager, and CI.
- Do not add manual-review-only gates when a deterministic check is possible.
