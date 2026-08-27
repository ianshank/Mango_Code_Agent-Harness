# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.1.8  
**Status:** In Progress / Strategic Roadmap

---

## 0. Completed Milestones

### ✅ v2.1.8 — MangoMas Integration Core (Shadow Comparison Channel)

Delivers the boundary machinery from `docs/research/mangomas-v2-integration-use-cases.md`
(UC-1 + UC-4), spec-first at `docs/specs/mangomas-integration-core.md`. Peer-reviewed
(Architect/QA-SQE/SDLC+Product) before implementation and re-audited for hygiene/wiring
after. Framed explicitly as channel infrastructure validated with a same-model producer —
no UC-4 experiment evidence is claimed by this milestone.

- [x] `harness/shared/cognitive_signal.py` — versioned, fail-closed `CognitiveSignal`
      envelope; workspace-scoped locked JSONL sink with per-signal and whole-sink byte
      ceilings; `confidence` is untrusted metadata, never a control input (INV-16).
- [x] `harness/shared/shadow_planner.py` + a guarded orchestrator hook — observation-only
      shadow plan comparison behind `MANGO_SHADOW_PLANNER=1`; zero tool authority; bounded
      timeout; disabled behavior byte-identical to baseline (proven by test, not asserted).
- [x] `harness/control-plane/publish_policy_artifact.py` — versioned, digest-pinned policy
      artifact with fail-closed `check` and HMAC attestation whose signature transitively
      covers the artifact core; committed `policy-artifact.json` closes a real drift gap
      (`make digest-regen` only pinned the per-stack mirrors, never the authoritative
      `governance-policy.json`/`agent-policy.json`).
- [x] Two new skills: `boundary-invariant-review` (reviews whether a diff gives a
      cognitive-plane field authority) and `shadow-channel-analysis` (freezes the UC-4
      analysis method before any producer exists).
- [x] `.claude/` SessionStart hook installs pinned dev dependencies on remote sessions.
- [x] INV-16 (one-directional cognitive/execution boundary) added to `harness/CONTRACT.md`.
- [x] Hardening from a post-implementation gap analysis: the lock retry loop is bounded by
      a poll budget independent of clock behavior (a clock-source mutation previously hung
      the suite instead of failing it); sink rejections are uniformly `SignalValidationError`
      instead of leaking a raw `TypeError` on unserializable payloads.
- [x] Second-pass adversarial review: fixed a BLOCKER (`publish_policy_artifact.check_artifact`
      never verified its file manifest actually covered the governed policy files — a
      narrowed manifest defeated the drift gate entirely), a cross-Python-version timestamp
      acceptance gap (`Z`-suffix ISO timestamps parse on 3.11+ but not 3.10, and CI runs
      both), a silent-channel-death bug (`policy_id: ""` discarded every signal in a run),
      and hardened the shadow channel against hostile provider responses and a data-integrity
      gap in payload key handling. Full findings in `CHANGELOG.md` [2.1.8].
- [x] `.gitignore` — `.governance/vitest-results.json`/`.governance/coverage/` were anchored
      to a nonexistent repo-root `.governance/` (same class of bug as the `protected_paths`
      finding below) and never actually matched `harness/node/.governance/`; surfaced by
      running the Node suite and checking `git status`. Fixed to `**/.governance/...`.
- [x] Findings recorded for follow-up, not silently patched (each requires a protected-path
      change and `infra-reviewed`): 5 of 6 `.mango/hooks/` scripts never fire because
      `.mango/settings.json` isn't the file Claude Code reads; `protected_paths` pattern
      `.governance/**` matches no real directory (`fnmatch` full-string anchoring); the
      `specs` CI-required target has no `make ci` stage; `R-MMI-*` requirement IDs aren't
      covered by `check_traceability` (its globs are scoped to `harness/node/`);
      `harness/control-plane` is in `pyproject.toml`'s coverage `source` but not yet
      measured by `make coverage-python` (the Makefile's explicit `--cov=` flags take
      precedence over the static config) — needs `--cov=harness/control-plane` added to
      the protected `Makefile` line; `publish_policy_artifact.py` itself is independently
      confirmed clean under `mypy --strict`, so this is purely a wiring gap, not a quality
      one; the Dockerfile `COPY .mango/ /app/.mango/` appears to copy nothing, since
      `.dockerignore` excludes the entire `.mango/` tree from the build context — flagged,
      not fixed: no Docker daemon was available in this session to verify with a real build,
      and the runtime image never installs Python regardless, so `harness/shared`/
      `harness/control-plane` cannot execute in it today irrespective of this bug.

### ✅ v2.1.6 — Live Smoke Test Resilience & Native Agent Skill Binding

- [x] Implemented resilient handling for live NIM API rate limits (429) and model deprecation (404/410) with graceful skip triggers.
- [x] Bound `nemotron_bridge.py` as a native Antigravity / Agent Skill (`.agents/skills/nemotron-reasoner/SKILL.md`).
- [x] Configured Upstash Context7 MCP environment template integration.
- [x] Refactored `nemotron_bridge.py` with structured `logging` module, `--debug` flags, and full type annotations.
- [x] Verified full 7-tier test pyramid compliance across 243+ tests and 85%+ coverage gates.

### ✅ v2.1.4 — Governance Kernel Extraction & MAS Orchestrator

- [x] Extracted policy evaluation mechanisms into `harness/shared/governance/`.
- [x] Implemented `mango_mas_orchestrator.py` with fail-closed PreToolUse guards.
- [x] Implemented `meta_tools.py` for meta-learning and knowledge gaps tracking.
- [x] Updated C4 architecture, documentation, and root Makefile to align with governance boundaries.

### ✅ v2.1.3 — Python AQA Framework & Code Hygiene

- [x] Implemented full Python AQA suite: 133 tests, 98.44% coverage across `harness/shared`.
- [x] Created root `Makefile` with `lint`, `test`, `coverage`, `validate`, `ci` targets.

---

## 1. Near-Term Milestones (v2.2.0)

### 1.1 Optimize Language Agent Tree Search (LATS)

- [ ] **MCTS Refinement:** Refine the Monte Carlo Tree Search components in the reasoning layer.
- [ ] **Ablation Studies:** Measure the efficacy of LATS implementations against standard chain-of-thought methods.
- [ ] **Trace Logging:** Formalize the trace logging formats for LATS pathways.

### 1.2 Autonomous Healing Integration

- [ ] **Merge Experimental Branch:** Merge and stabilize the experimental Autonomous Healing branch.
- [ ] **Test-Driven Healing:** Wire the healing routines to automatically trigger upon test suite failures (`vitest` and `pytest`).
- [ ] **Policy Enforcement:** Gate autonomous healing behind the `.governance/` policy invariants to prevent out-of-bounds structural modifications.

### 1.3 Multi-Agent Memory Maturation

- [ ] **Persistent Storage:** Extend `meta_tools.py` for persistent JSON/Markdown storage for knowledge gap logs.
- [ ] **Retention Policies:** Establish retention policies and periodic context summarization protocols for the agent `memory/` directory.

---

## 2. Infrastructure & DevSecOps Milestones (v2.3.0)

### 2.1 NVIDIA NIM Multi-Model Routing & Token Budgeting

- [ ] **Dynamic Model Fallback:** Implement multi-tier routing (e.g. fast reasoning → deep synthesis).
- [ ] **Prompt Cache & Cost Tracking:** Add local disk/memory prompt-cache adapter to minimize repeated token costs on invariant verification prompts.
- [ ] **Model Context Protocol (MCP) Server:** Package `NemotronClient` as an independent standard STDIO/SSE MCP server for seamless integration with external AI IDEs and clients.

### 2.2 Pong Engine Enhancements

- [ ] **WebSocket Multiplayer Protocol:** Add real-time deterministic rollback netcode (GGPO-style) for client-to-client PvP over WebSockets.
- [ ] **Audio Customization:** Expose interactive sound effect waveform customization (sine/square/triangle/sawtooth) in the Web UI.
- [ ] **Game State Recording & Replay:** Implement binary snapshot encoding to record full matches for automated test regression playback.
