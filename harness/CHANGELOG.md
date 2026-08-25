# Changelog

## v2.1.1 — Mango Multi-Agent Platform Migration

- **Mango Multi-Agent Migration (`.mango/`):**
  - Rebranded `.claude` multi-agent framework into `.mango` ecosystem.
  - Preserved all subagents (`nemotron-reasoner`, `planner`, `verifier`), skills (`nemotron-reasoner`, `harness-engineering`), and lifecycle hooks (`block_dangerous`, `loop_detection`, `pre_completion_checklist`, `session_start`).
  - Added dual environment variable fallback (`MANGO_PROJECT_DIR` with `CLAUDE_PROJECT_DIR` fallback) for backward-compatible hook and guard execution.
  - Updated `Dockerfile`, `.dockerignore`, `README.md`, `C4_ARCHITECTURE.md`, and test suites.

---

## v2.1.0 — NVIDIA Nemotron Ultra AI Integration & Pong 2026 Game Engine

- **NVIDIA Nemotron Ultra Client Adapter (`src/ai/nemotron/`):**
  - Implemented provider-agnostic `NemotronClient` with OpenAI-compatible `/chat/completions` protocol.
  - Added native Server-Sent Events (SSE) streaming yielding async iterable chunk streams.
  - Implemented exponential backoff with full jitter on HTTP 429/5xx and 3-state Circuit Breaker (`CLOSED`, `OPEN`, `HALF_OPEN`).
  - Added `SecretMasker` redacting raw credentials in logs, error traces, and telemetry.
  - Created standalone CLI runner (`npx tsx src/ai/nemotron/cli.ts`) and zero-dependency Python bridge (`nemotron_bridge.py`).
- **Mango Agent Ecosystem (`.mango/`):**
  - Added `nemotron-reasoner.md` subagent for deep architectural reasoning, formal constraint verification, and adversarial security audits.
  - Added `nemotron-reasoner/SKILL.md` operational cheatsheet for CLI, Python, and programmatic execution.
- **Pong 2026 Engine & Multi-Target Renderers (`src/pong/`):**
  - Implemented deterministic 2D vector physics with Continuous Collision Detection (CCD) and spin dynamics.
  - Implemented 6-state FSM (`MENU` → `GAME_OVER`), dynamic preset configuration (`classic`, `fast`, `arcade`, `tournament`), and predictive raycasting AI opponent.
  - Implemented procedural Web Audio API synthesizer, HTML5 Canvas 2D renderer, and ANSI terminal 2D renderer.
  - Built standalone responsive Web UI with Google Fonts typography, glassmorphism, live telemetry HUD, and on-screen touch D-Pad.
- **7-Tier Test Pyramid Expansion:**
  - Expanded test matrix to **80 total tests across 30 test suites** with 0 skips and 0 waivers.
  - Verified **>95% statement and line coverage** with 100% requirement traceability (15 requirements).

---

## v2.0.0 Resynthesis

- Reclassified CI from network-transfer prevention to repository conformance/evidence.
- Added external root-of-trust/control-plane contract.
- Replaced separate Node/JVM remote normalizers with one shared policy kernel.
- `make remotes` now validates configured Git push URLs; it no longer prints the allowlist as a vacuous pass.
- Preserved path case and significant non-default ports in remote canonicalization.
- Rebuilt PreToolUse guard to fail closed on malformed/unmodeled dangerous commands.
- Fixed `guard-probe` shell error handling.
- Rebuilt Git hook installation around Git's effective hooks path and refusal to overwrite unrelated hooks.
- Reworked JVM zero-skip: listener records evidence; a Gradle verification task performs the build-failing assertion.
- Reworked Node zero-skip around Vitest JSON results and exact waiver registry entries.
- Removed Vitest 4 `coverage.all`; explicit `coverage.include` retains uncovered-file coverage.
- Repaired invalid TypeScript pseudo-comment compiler options.
- Enabled strict Gradle dependency locking and made verification metadata absence fail closed.
- Expanded CI conformance to remotes, projections, traceability and governance.
- Added agent/sub-agent role, delegation, human-approval and side-effect evidence policy.
- Added C4 context/container/component diagrams in Mermaid, draw.io/Lucid, SVG and PNG.
- Added exact, decision-backed JVM skip waivers keyed to JUnit unique ID + display name; fabricated decision IDs fail.
- Made `guard-probe` propagate BLOCK as a non-zero status rather than printing BLOCK and succeeding.
- Made the JVM zero-skip Gradle task graph non-circular and wired `check` through the verifier.
- Added project charter + governance-skill freshness validation through one shared cross-stack implementation.
- Made strict spec validation mandatory in CI; local structural degraded mode remains explicit/noisy.
- Added concrete human-readable contracts for all seven governed agent/sub-agent roles.
- Changed human approval from a role-wide boolean to exact high-risk actions.
- Added independently deployable policy/agent-policy digest verification before project-local governance is trusted.
