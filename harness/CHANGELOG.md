# Changelog

## v2.1.5 — .mango Architecture, Continuous Learning & Persona Topology

- **Continuous Learning Meta-Tools (`data_agent` synthesis):**
  - Synthesized continuous learning concepts from the `data_agent` project.
  - Implemented `knowledge_gap_log` and `hypothesis_register` meta-tools to allow agents to persist provisional beliefs and knowledge gaps directly into `.mango/memory/` as JSON.
  - Wired meta-tools directly into the `mango_mas_orchestrator.py` recursive ReAct loop.
- **Persona Topology (`FORGE` synthesis):**
  - Delegated monolithic orchestrator tasks into discrete Personas defined per-directory.
  - Created `harness/api_server/Agent.md` (Web Presenter persona) and `harness/node/Agent.md` (Node Bridge persona).
  - Updated `nemotron-reasoner` to automatically adopt relevant personas based on the directory context.
- **Governance & E2E Validation (`Agents-main` synthesis):**
  - Ported `repo-invariant-review` and `openspec-peer-review` skills from the upstream `Agents-main` repository.
  - Created a hardened `validate_invariants.py` hook and `.mango/hooks/pre-nemotron-run.sh` to enforce constraints programmatically before agent mutations.
  - Executed extensive cross-stack SDLC and QA code review, resolving over 600 `ruff` lint violations, fixing critical `mypy` typing drifts in `nemotron_bridge.py`, and updating cross-stack dependency graphs.
  - Ran unmocked E2E validations with Nemotron proving correct JSON tool calling.
- **SDLC Objective Peer Review & Code Hygiene Enhancements:**
  - Hardened `mango_mas_orchestrator.py` by removing hardcoded timeout/model values and extracting configurable parameters.
  - Wired `.mango/hooks` directly into the ReAct orchestrator loop, exposing generic shell environments for pre/post invocation logic.
  - Repaired `test_validators.py` timezone drift issues that broke local test execution environments.
  - Re-attained 85% AQA Python Test Coverage for `harness/shared` and validated zero E501/trailing-whitespace violations in `meta_tools.py` and `mango_mas_orchestrator.py`.

## v2.1.4 — Python AQA Framework, Code Hygiene & CI Wiring

- **Python AQA Test Engine (`harness/shared/tests/`):**
  - Implemented full `pytest` test suite: **133 tests, 98.44% coverage** across 10 governance scripts.
  - Achieved in-process coverage via `runpy.run_path()` executor, eliminating subprocess coverage gaps.
  - Added `conftest.py` with reusable fixtures (`project_root`, `api_key`, `tmp_git_repo`).
  - Test suites: `test_validators.py`, `test_remotes.py`, `test_nemotron_bridge.py`, `test_verify_zero_skips.py`, `test_pretooluse_guard.py`.
- **Code Hygiene Remediation:**
  - Resolved all `ruff` lint violations in test code (unused imports, duplicate import blocks, unsorted imports).
  - Added `[tool.ruff]` and `[tool.mypy]` configuration to `pyproject.toml`.
  - Created `__init__.py` package markers for `harness/shared` and `tests/` — resolves mypy module resolution.
  - Fixed non-deterministic `datetime.now()` (added UTC timezone) and implicit `Optional` type hints.
  - Governance validator scripts excluded from ruff style enforcement via `per-file-ignores` (intentionally compact).
- **DevOps & Infrastructure:**
  - Created root `Makefile` with parameterized targets: `lint`, `test`, `coverage`, `validate`, `ci`, `pre-pr`, `clean`.
  - Updated `.gitignore` and `.dockerignore` with Python artifact exclusions (`.coverage`, `.pytest_cache`, etc.).
  - Updated `.gitleaks.toml` allowlist with Python test files containing mock API keys.
- **Documentation:**
  - Updated C4 Architecture (Level 2) with Python AQA Engine container and `runpy` execution strategy.
  - Updated `TEST-REPORT.md` with Python test suite metrics.
  - Updated `NEXT_STEPS.md` — fixed deprecated model reference, added completed milestones.

---

## v2.1.2 — Nemotron Live Integration Smoke Tests & Model Migration

- **Model Migration:**
  - Migrated default model from deprecated `nvidia/llama-3.1-nemotron-70b-instruct` (HTTP 404) to `nvidia/llama-3.3-nemotron-super-49b-v1`.
  - Updated TypeScript client, Python bridge, CLI help text, `.env.example`, and specification.
- **Live Smoke Test Tier (`tests/ai/smoke/`):**
  - Added shared test fixtures (`_fixtures.ts`) with `.env` resolution, cost-conscious client factory, and `assertNoSecretLeakage()` post-test assertion.
  - Added `nemotron-live.test.ts`: Live API completion, streaming SSE, error sanitization, and timeout validation.
  - Added `cli-live.test.ts`: CLI subprocess validation (`--json`, `--stream`, `--help`).
  - Added `mango-agent-live.test.ts`: .mango agent delegation tests exercising planner, nemotron-reasoner, and verifier system prompts against the live API.
  - Added `test_nemotron_bridge_live.py`: Python bridge live validation with wire parity contract test.
  - All live tests gated behind `NVIDIA_API_KEY` — auto-skipped in CI.
- **ESLint TypeScript Parser:**
  - Configured `typescript-eslint` parser in `eslint.config.js` to fix `interface` reserved keyword errors.
  - Updated `knip.json` schema to v6 and removed stale `ignoreDependencies`.
- **Specification Update:**
  - Updated nemotron spec to v1.1.0 with smoke test tier in acceptance criteria matrix.

---

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
