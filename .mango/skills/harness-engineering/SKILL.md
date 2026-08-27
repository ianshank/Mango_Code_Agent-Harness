---
name: harness-engineering
description: Use when the user wants to inspect, extend, or debug this agent's own harness (hooks, subagents, CLAUDE.md rules) rather than application code. Also use when repeated agent mistakes should be turned into durable repo-level guardrails.
---

# Harness Engineering Skill

Harness = Instructions + Constraints + Feedback + Memory + Evaluation + Governance.

## When invoked
1. Treat this repository's `.mango/` directory as the source of truth for current
   harness behavior. Inspect `settings.json`, `hooks/`, `agents/`, and `CLAUDE.md`
   before proposing changes.
2. Prefer updating an existing hook/rule over adding a duplicate one.
3. Make new rules enforceable where practical (a hook, a lint rule, a test) rather than
   just prose in CLAUDE.md.
4. If a failure pattern recurs (e.g. the agent repeatedly ignores a constraint), record it
   in `.mango/FAILURE_MEMORY.md` with: what happened, why, and what check now prevents it.
5. After any harness change, state explicitly: what changed, why, and how to verify it
   (e.g. "trigger a Bash rm -rf call in a scratch dir and confirm the hook denies it").

## Reference model (from research)
- Control loop: keep it a simple while-loop (model -> tool -> observe -> repeat); avoid
  adding orchestration complexity unless task genuinely needs sub-agent delegation.
- Context management: cheap-first. Never rely on conversation history for correctness --
  durable state lives in files (PLAN.md, NOTES.md, FAILURE_MEMORY.md) that survive compaction.
- Verification: deterministic checks (tests, linters, type-checkers) always outrank
  LLM self-assessment. The Stop hook in this repo enforces this.
- Cost discipline: minimize "no-action turns" (turns with no file edit and no command).
  Batch related reads/searches instead of issuing them one at a time.

## Do not
- Do not copy generic harness templates blindly -- adapt to this repo's actual stack,
  package manager, and CI.
- Do not add manual-review-only gates when a deterministic check is possible.
