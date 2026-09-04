# Agentic SSD & NVIDIA Nemotron AI Platform (Mango Ecosystem)

**Version:** 2.4.0 (2026 Standards)
**Author:** Ian Cruickshank
**Governing Standard:** Agentic SSD Gate Harness Contract v2.1 (`harness/CONTRACT.md`)

A production-grade, deterministic AI & software engineering platform featuring the **Autonomous Mango Multi-Agent Ecosystem**, the **LangGraph Multi-Agent StateGraph Engine**, and the **NVIDIA Nemotron Ultra AI Reasoner**, backed by a multi-tier test matrix across Python + Node (0 unapproved skips per `verify-zero-skips`, coverage gate sourced from `governance-policy.json`) and fail-closed governance invariants (INV-1..INV-17).

---

## 1. Repository Layout

```text
├── .claude/                             # Claude Code project settings (the file it actually reads)
│   ├── hooks/session-start.sh           # Installs pinned dev dependencies on remote sessions
│   └── settings.json                    # SessionStart binding; the only live hook (see DEC-003)
│
├── .mango/                              # Mango Multi-Agent Ecosystem
│   ├── agents/
│   │   ├── nemotron-reasoner.md         # NVIDIA Nemotron Ultra reasoning subagent
│   │   ├── planner.md                   # Pre-implementation task planning subagent
│   │   └── verifier.md                  # Strict post-change verification subagent
│   ├── hooks/
│   │   ├── block_dangerous.sh           # PreToolUse guard blocking destructive commands
│   │   ├── loop_detection.sh            # Anti-loop edit cycle detector
│   │   ├── pre-nemotron-run.sh          # Fired by the orchestrator before each agent turn
│   │   ├── pre_completion_checklist.sh  # Pre-completion deterministic test validation
│   │   ├── save_state_before_compact.sh # Context compaction state persistence
│   │   └── session_start.sh             # Environment & credentials verification hook
│   ├── skills/                          # 14 reusable skills; the only skill root
│   │   ├── agent-memory-manager/        # Persistent memory and context bridging
│   │   ├── boundary-invariant-review/   # Cognitive/execution boundary review (INV-16)
│   │   ├── coverage-gate/               # Coverage threshold sourced from policy
│   │   ├── evidence-signing/            # Reusable HMAC evidence manifest skill
│   │   ├── gate-mutation-proof/         # Prove a gate catches the defect it names
│   │   ├── harness-engineering/         # Harness inspection & extension rules
│   │   ├── nemotron-reasoner/           # NVIDIA Nemotron AI operational cheatsheet
│   │   ├── openspec-peer-review/        # Architecture/SDLC/QA/Product peer review
│   │   ├── protected-path-attestation/  # Produces the per-file attestation block
│   │   ├── repo-invariant-review/       # Predicts concrete CI failures pre-push
│   │   ├── shadow-channel-analysis/     # UC-4 agreement/latency/token reporting
│   │   ├── spec-authoring/              # Spec scaffolding and required sections
│   │   ├── tech-debt-audit/             # Repeatable full-repo SDLC/SQE audit procedure
│   │   └── validation-runner/           # Single entry point for the validation matrix
│   └── settings.json                    # Mango agent lifecycle hook bindings
│
├── docs/
│   ├── architecture/
│   │   ├── c4_architecture.md           # C4 Level 1-4 Architecture & Threat Boundaries
│   │   └── god-file-refactoring-guide.md # Architecture & Decomposition Migration Guide
│   ├── rca/                             # Root-cause analyses (Nemotron E2E triage)
│   ├── releases/                        # Full release notes too long for CHANGELOG.md (v2.2.4)
│   ├── reports/                         # Historical hygiene, peer-review and test reports
│   └── specs/                           # 24 Formal Traceable Specifications (+ SPEC_TEMPLATE.md)
│
├── harness/                             # Enterprise Governance & Multi-Stack Harness
│   ├── api_server/                      # FastAPI Web Server & Orchestration Dashboard (:8080)
│   │   ├── main.py                      # REST endpoints (/api/orchestrate) & static file server
│   │   ├── static/                      # Interactive Web UI dashboard & telemetry view
│   │   └── tests/                       # API Server integration & authentication tests
│   │
│   ├── node/                            # Node/TypeScript Engine & AI Adapter
│   │   ├── src/
│   │   │   ├── ai/nemotron/             # NVIDIA Nemotron Ultra Client Adapter
│   │   │   │   ├── circuit-breaker.ts   # 3-State circuit breaker (CLOSED/OPEN/HALF_OPEN)
│   │   │   │   ├── cli.ts               # Standalone CLI runner with streaming & JSON output
│   │   │   │   ├── nemotron-client.ts   # Core client with SSE streaming & jittered backoff
│   │   │   │   ├── secret-masker.ts     # Invariant INV-1 credential redactor
│   │   │   │   └── types.ts             # Strict TypeScript contracts
│   │   ├── tests/                       # Multi-tier Vitest matrix
│   │   └── docs/specs/                  # Bidirectionally-traced formal specifications
│   │
│   ├── jvm/                             # Kotlin/Gradle governance-parity REFERENCE TEMPLATE —
│   │                                     # not wired into root CI/Makefile (INV-2/INV-3 partial;
│   │                                     # see harness/CONTRACT.md)
│   │
│   ├── shared/                          # Shared Policy Kernel & Governance Tools
│   │   ├── orchestrator/                # Decomposed MAS Orchestrator (loop, dispatch, hooks)
│   │   ├── mango_mas_orchestrator.py    # Backwards-compatible ReAct loop facade
│   │   ├── experimental/                # Parked, unwired capabilities (DEC-027): autonomous_healing.py, lats_optimizer.py
│   │   ├── mcp_server.py                # Model Context Protocol (MCP) STDIO server
│   │   ├── langgraph/                   # LangGraph Multi-Agent StateGraph Engine
│   │   │   ├── state.py                 # 12-Channel partitioned typed state (Accumulator vs LWW)
│   │   │   ├── nodes.py                 # 10 active, gate, and reviewer nodes
│   │   │   ├── graph.py                 # StateGraph builder and conditional DAG routing
│   │   │   ├── policy.py                # GraphExecutionPolicy configuration
│   │   │   ├── decorators.py            # @with_authority & @budgeted runtime gates
│   │   │   └── ablation.py              # MCTS ablation & hypothetical state channels
│   │   ├── agent_prompts.py             # Persona prompts, guardrails & hook names
│   │   ├── tool_executors.py            # Tool executors + the shared PDP write authorization
│   │   ├── tool_dispatch.py             # Tool call argument normalization & dispatch
│   │   ├── tool_schemas.py              # OpenAI/Nemotron-compatible tool definitions
│   │   ├── cognitive_signal.py          # Versioned CognitiveSignal envelope + JSONL sink
│   │   ├── shadow_planner.py            # Observation-only shadow plan comparison channel
│   │   ├── meta_tools.py                # Meta-learning, context state, and file_lock
│   │   ├── nemotron_bridge.py           # Zero-dependency Python Nemotron bridge
│   │   ├── write_policy.py              # Runtime write gate: protected_paths, .git, credentials
│   │   ├── agent_authority.py           # Per-role tool exposure derived from agent-policy.json
│   │   ├── check_dedup.py               # Drift gate: shim vs copy detection (make check-dedup)
│   │   ├── check_py_compat.py           # Python 3.9 compatibility gate (make check-compat)
│   │   ├── ast_visitors.py              # AST visitor rules for Python 3.9+ compatibility checks
│   │   ├── governance/                  # Extracted fail-closed policy mechanisms
│   │   │   ├── broker.py                # ExecutionBroker — INV-8/9/10 on the live path
│   │   │   ├── process_backend.py       # Decoupled subprocess execution & byte-capping
│   │   │   ├── command_actions.py       # Command → declared policy action (fails closed)
│   │   │   ├── policy_decision.py       # In-process PDP; mirrors tool_broker_reference.py
│   │   │   ├── evidence_manifest.py     # EvidenceBuilder — HMAC-signed audit trails
│   │   │   ├── pretooluse_guard.py      # Native command-level PreToolUse guard
│   │   │   ├── verification.py          # VerificationRunner — earned verdict evaluation
│   │   │   └── check_traceability.py    # Requirement specification tracing
│   │   └── tests/                       # Python AQA Engine (3,131 tests; coverage gate from policy)
│   │       ├── conftest.py              # Reusable Pytest fixtures
│   │       ├── regression/              # Dedicated AQA Regression Tier
│   │       │   ├── test_langgraph_regression.py      # 32 tests: StateGraph invariants, calling & reductions
│   │       │   ├── test_cross_platform_regression.py # 34 tests: cross-platform path/env/secret invariants
│   │       │   ├── test_bridge_retry_regression.py   # Retry jitter & backoff invariants
│   │       │   └── test_orchestrator_dispatch_regression.py # Dispatch edge-cases & budget handling
│   │       ├── test_orchestrator_init.py       # Orchestrator initialization & prompt loading
│   │       ├── test_orchestrator_tools.py      # Write & command tool execution
│   │       ├── test_orchestrator_hooks.py      # Pre/post lifecycle hooks
│   │       ├── test_orchestrator_agent_loop.py # ReAct execution loop & budget limits
│   │       ├── test_evidence_manifest.py       # EvidenceBuilder signing & immutability
│   │       ├── test_governance_broker.py       # 68 tests: INV-8/9/10, in-process PDP, ProcessBackend
│   │       └── test_protected_path_liveness.py # Asserts protected_paths match real files
│   │
│   └── control-plane/                   # Policy bundles, digests & external verifier
│       ├── publish_policy_artifact.py   # Versioned, digest-pinned, attestable policy artifact
│       ├── policy-artifact.json         # Committed artifact; drift-gated by the test suite
│       └── tests/                       # Colocated control-plane suite (101 tests; R-TDH-26)
│
├── .env.example                         # Environment configuration template
├── .gitignore                           # Git ignore rules protecting local secrets
├── .gitleaks.toml                       # Gitleaks security scan configuration
├── .dockerignore                        # Docker build context policy (excludes .mango)
├── Dockerfile                           # Multi-stage production container image
├── Makefile                             # Unified root Makefile for CI/CD targets
├── pyproject.toml                       # Python tool configuration (ruff, mypy, pytest) + [project.dependencies]
├── requirements.txt                     # Python runtime dependencies (fastapi/uvicorn/pydantic/httpx)
└── requirements-dev.txt                 # Dev/tooling deps (-r requirements.txt, plus pytest/ruff/mypy)
```

---

## 2. Key Subsystems

### 2.1 Mango Multi-Agent Ecosystem (`.mango/`)

- **`nemotron-reasoner` Subagent:** Dispatches complex chain-of-thought analysis, mathematical proofs, and adversarial security audits to NVIDIA Nemotron Ultra (`nvidia/llama-3.3-nemotron-super-49b-v1`).
- **`planner` Subagent:** Decomposes non-trivial tasks into sequentially verifiable steps before code changes begin.
- **`verifier` Subagent:** Executes deterministic tests, linters, and typecheckers before marking tasks complete.
- **Fail-Closed Hooks:** Intercepts dangerous bash commands (`rm -rf /`, raw disk writes), detects edit loops, and enforces test verification on stop.

### 2.2 NVIDIA Nemotron Ultra AI Adapter (`harness/node/src/ai/nemotron/`)

- **Provider-Agnostic Client:** Full compatibility with OpenAI `/chat/completions` API wire protocol.
- **Resilience Engine:** Exponential backoff with full jitter on HTTP 429/5xx and 3-state Circuit Breaker (`CLOSED` → `OPEN` → `HALF_OPEN`).
- **Secret Sanitization (`INV-1`):** `SecretMasker` masks keys (`nvapi-sSeC...NcWq`) in all error strings and logs.
- **Dual Runtimes:** TypeScript client with native SSE streaming + zero-dependency Python bridge (`nemotron_bridge.py`).

### 2.3 Governance Kernel (`harness/shared/governance/`)

- **`ExecutionBroker`** (`broker.py`): the approved execution path INV-8 names, reached from the orchestrator's `run_command`. `execute_command` derives the action from the command (`command_actions.classify`), obtains an in-process policy verdict (`policy_decision.decide`, mirroring `tool_broker_reference.py` and pinned by `test_policy_decision.py`), runs `check_command()`, then executes via `ProcessBackend` with a pinned working directory, a timeout and a byte-capped output. `sandbox_available` defaults to probing the backend; an unavailable backend returns `BLOCKED` and never falls through (INV-9), and a denial is terminal (INV-10). **The backend contains but does not isolate** — it confines neither the filesystem nor the network — so INV-13's sandbox digest is not yet satisfiable (DEC-010).
- **`command_actions.py`**: classifies a command into a declared policy action. An allowlist, not a denylist: anything unmodelled resolves to an action no role holds, so an unrecognised command denies for every agent.
- **`policy_decision.py`**: the verdict, in process. Replaces a host subprocess that ran *before* the command guard, from a path inside the agent's workspace (DEC-009).
- **`write_policy.py`**: enforces `protected_paths` on the agent's write tool at tool-call granularity, plus any `.git` directory segment and any credential-bearing filename (`.env*`, `.netrc`, `.npmrc`, `.pypirc`, `id_[rd]sa`, `*.pem`) — three classes `validate_invariants` structurally cannot see, the last because `.env` is untracked and so matched no `protected_paths` pattern at all (DEC-007, DEC-042).
- **`read_policy.py`**: the read-side counterpart to `write_policy.py`. `command_actions.classify` already denies reading a credential through `run_command` (graded `secret_access`, an action no role holds); `read_policy.read_denial_reason` closes the same gap for the orchestrator's `read_file` handler, which reads the filesystem directly and so is invisible to that classifier. The pattern has one definition, in `write_policy`, re-exported here and composed by `command_actions` — three anchorings of one alternation rather than three that can drift (DEC-012, DEC-042).
- **`agent_authority.py`**: derives each active role's tool exposure from `agent-policy.json`. The verifier holds no `write_file` (DEC-008) or `apply_patch` (DEC-012) — both grade as the `write` action, which every canonical contract the verifier maps to already denied in prose — but does hold `read_file`.
- **`EvidenceBuilder`** (`evidence_manifest.py`): HMAC-SHA256 signed audit trail builder. Signing key injected via constructor or `AGENT_EVIDENCE_KEY` env var. Raises `ValueError` (fail-closed) when key is absent. `export()` is non-destructive and deterministic. See `.mango/skills/evidence-signing/SKILL.md`.
- **`check_dedup.py`**: CI drift gate — fails when per-stack governance scripts are full copies instead of thin shims delegating to `harness/shared`. Run via `make check-dedup`.
- **`check_py_compat.py`**: CI compatibility gate — fails when any source file uses syntax unavailable in Python 3.9 (PEP 604 unions, `datetime.UTC`, unannotated `AnnAssign`). Run via `make check-compat`.

**Required environment variable:**

| Variable             | Purpose                                                                       |
| -------------------- | ----------------------------------------------------------------------------- |
| `AGENT_EVIDENCE_KEY` | HMAC signing key for `EvidenceBuilder`. Never hard-code. Set in secret store. |

`debug_dump.CREDENTIAL_ENV_VARS` covers `NVIDIA_API_KEY`, `API_SERVER_KEY`,
`AGENT_EVIDENCE_KEY` and `CONTEXT7_API_KEY`, and `credential_env_names()` also
sweeps any variable whose *name* marks it as a credential. Those values are
redacted from returned histories and stripped from every hook subprocess
environment, so a hook author should not expect `MY_TOKEN` to be visible.

---

## 3. 7-Tier Test Matrix & Governance

The platform enforces the **Agentic SSD Gate Harness Contract v2.1** with **zero unapproved test skips** (`INV-2`):

```text
                 ▲
                / \     Tier 7: Sanity & Stress Tests (Resilience & Concurrency)
               /---\    Tier 6: Security & Secret Sanitization Tests (INV-1 Leak Check)
              /-----\   Tier 5: User Journey Tests (Multi-Agent Delegation Workflows)
             /-------\  Tier 4: E2E Tests (CLI Terminal & Autonomous Autoplay)
            /---------\ Tier 3: Functional Tests (Match Progression & Multi-Turn Chats)
           /-----------\Tier 2: Integration Tests (SSE Streaming & Engine Events)
          /-------------\Tier 1: Unit Tests (Vector Math, Physics, Config, SecretMasker)
```

- **Total Automated Tests:** **3,107 automated tests** (123 Vitest + 2,984 Pytest across 7 tiers), measured 2026-09-03 by `pnpm exec vitest run` and `pytest --collect-only`
- **Node Code Coverage (V8):** **≥90% Statements | ≥80% Branches | ≥90% Functions | ≥90% Lines**
- **Python AQA Coverage:** **99.29% Lines | 97.80% Branches** across `harness/shared`, `harness/api_server`, and `harness/control-plane`, over a measured set of 76 files with all 73 gated files meeting the per-file floor and **none waived**. Measured 2026-09-03 on the `langgraph`-installed configuration — the one `build-full` runs. The 3.9 matrix leg cannot install `langgraph` (it declares `Requires-Python >=3.10`) and reports its own aggregate there; its figure is not restated here, because a number this file cannot reproduce is a claim rather than a measurement. The per-file waiver for those modules needs *both* `MANGO_CI_DESELECT_LANGGRAPH` and a failing import (DEC-028), so setting the variable on a host where the extra is present waives nothing — verified by running exactly that. The measured *set* is bounded too — `coverage_scope.check_measured_set` fails closed if the report and the on-disk first-party sources disagree, so an `omit` entry cannot drop a file from the per-file floor
- **Requirements Traceability:** **6 / 6 requirements** traced bidirectionally (`check_traceability.py`); its globs resolve relative to `harness/node`, so root `docs/specs/` IDs are not yet reached
- **Governance Drift Gate:** `check_dedup.py` — fails CI when per-stack scripts copy instead of delegate to `harness/shared`
- **Compatibility Gate:** `check_py_compat.py` — fails CI if any source uses syntax newer than Python 3.9 across all repository sources

---

## 4. Quick Start Guide

### 4.1 Configuration

Copy the template and set your NVIDIA API key:

```bash
cp .env.example .env
# Edit .env and set: NVIDIA_API_KEY=nvapi-your-key-here
```

Optional environment variables for the shadow planner comparison channel
(`docs/specs/mangomas-integration-core.md`; all off/unset by default):

| Variable                   | Effect                                                                                   |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| `MANGO_SHADOW_PLANNER`     | Exactly `1` enables the observation-only shadow plan comparison; any other value is off. |
| `MANGO_SHADOW_MODEL`       | Alternate model for the shadow pass (defaults to the orchestrator model).                |
| `MANGO_SHADOW_TIMEOUT_SEC` | Shadow-pass timeout; capped at the orchestrator API timeout.                             |
| `MANGO_SIGNAL_DIR`         | Overrides the signal sink directory (default `<workspace>/.mango/memory/signals/`).      |

### 4.2 Querying NVIDIA Nemotron Ultra

```bash
# Via TypeScript CLI (Node)
cd harness/node
npx tsx src/ai/nemotron/cli.ts --prompt "Audit the circuit breaker states in src/ai/nemotron/circuit-breaker.ts" --stream

# Via Python Bridge
python harness/shared/nemotron_bridge.py --prompt "Audit INV-1 secret scan rules"
```

### 4.3 Running Automated Verification

```bash
# 1. Install dependencies
cd harness/node
pnpm install
cd ../..
pip install -r requirements-dev.txt
make install         # One-time: install the pre-push remote-allowlist hook
make audit-install    # One-time: install pip-audit + the Node stack's pinned osv-scanner

# 2. Run Node/Vitest test matrix
cd harness/node
pnpm vitest run
pnpm exec tsc --noEmit
pnpm exec knip
cd ../..

# 3. Run Python AQA Engine & Governance Validators
make ci              # Full pipeline: lint → lint-node → lock-check → coverage → zero-skips-python → test-node → zero-skips → specs → remotes → validate → dedup → digest-regen
make lint            # ruff + mypy + check_py_compat (Python 3.9 compat gate)
make test            # Full test suite (Pytest + Vitest + Zero-Skips)
make test-governance # Governance-specific tests in isolation (broker, evidence, invariants)
make test-neurosym   # Neuro-symbolic synthesis tests (pytest -m neurosym)
make validate        # Governance invariants (adoption, policy, remotes, traceability)
make check-dedup     # Drift gate: per-stack scripts must delegate to harness/shared
make lint-node       # ESLint + Prettier + Knip (a `ci` prerequisite; never `ci-python`, whose legs have no pnpm)
make audit           # Dependency vulnerability scan (pip-audit + delegated Node osv-scanner)
make secrets-allowlist-check # Every .gitleaks.toml allowlist entry must still suppress a real finding (runs in secret-scan)
make attestation     # Print the protected-path attestation table for this branch (derived, never transcribed)
make attestation-check FILE=pr-body.md # Verify a written table against the set the gate enforces (runs in build-full)
make digest-regen    # Regenerate protected-file digests after policy changes

# 4. Run root adversarial harness self-tests
python harness/shared/tests/test_harness.py
```

---

## 5. Utilizing This Platform for Code Development

This platform is engineered as an **Agentic Software Security & Development (SSD) Harness**. It provides a hardened foundation for building deterministic, AI-orchestrated, and highly compliant software systems.

### 5.1 Multi-Agent Autonomous Development Workflow

The `.mango/` ecosystem enables specialized subagent collaboration during development:

1. **Planning (`planner.md`):** Before executing large features or refactors, invoke the Planner subagent to generate sequentially ordered implementation plans with explicit verification criteria.
2. **Deep Reasoning & Auditing (`nemotron-reasoner.md`):** Delegate architectural analysis, mathematical invariant verification, and adversarial threat modeling to NVIDIA Nemotron Ultra (`nvidia/llama-3.3-nemotron-super-49b-v1`).
3. **Automated Verification (`verifier.md`):** Ensure every code change is validated through deterministic test runners (`pytest`, `vitest`), typecheckers (`mypy`, `tsc`), and linters (`ruff`, `eslint`) before marking work complete.

### 5.2 Test-Driven Development (TDD) via the 7-Tier Pyramid

When introducing new features or modules:

- **Write Tests Across All 7 Tiers:** Ensure coverage spans Unit, Integration, Functional, E2E, User Journey, Security, and Stress/Sanity tiers.
- **Fail-Closed Zero Skips (`INV-2`):** Tests cannot be arbitrarily skipped. Any temporary waiver must be formally declared in `.governance/skip-waivers.json` citing an approved decision from `decision-log.md`.
- **Bidirectional Traceability:** Add requirement tags (e.g. `R-FEATURE-1`, `C-SEC-1`) to code and test docstrings, ensuring `python harness/shared/check_traceability.py` validates 100% requirement coverage.

### 5.3 Local Development & Gate Validation

Use the unified root `Makefile` to enforce enterprise quality gates locally prior to committing:

```bash
make lint            # Static analysis, formatting checks, strict typing, compat gate
make coverage        # Enforce ≥90% total coverage
make test-node       # Execute TypeScript/Node engine tests
make test-governance # Governance broker, evidence, invariant tests
make validate        # All governance invariants (adoption, policy, remotes, traceability)
make check-dedup     # Shim drift detection
make lint-node       # ESLint + Prettier + Knip (a `ci` prerequisite; never `ci-python`, whose legs have no pnpm)
make audit           # Dependency vulnerability scan (pip-audit + delegated Node osv-scanner)
make secrets-allowlist-check # Every .gitleaks.toml allowlist entry must still suppress a real finding (runs in secret-scan)
make attestation     # Print the protected-path attestation table for this branch (derived, never transcribed)
make attestation-check FILE=pr-body.md # Verify a written table against the set the gate enforces (runs in build-full)
make pre-pr          # Full pre-submission validation pipeline (now includes audit)
```

### 5.4 Secret Sanitization & Security Scanning

- **Invariant `INV-1` Enforcement:** Never output raw API tokens or credentials in logs or test assertions. Use `SecretMasker` and the native Python regex masks.
- **Pre-Push Allowlist (`remotes.py`):** Push targets are strictly validated against `.governance/allowed-remotes.txt` to prevent code leakage to unauthorized repositories.
- **Automated Gitleaks, pip-audit & OSV Scanners:** `make secrets` (gitleaks; INV-1) and `make audit` (`pip-audit` against `requirements.txt` + delegated Node `osv-scanner`) run locally and in dedicated CI jobs (`secret-scan`, `dependency-audit`) to catch hardcoded secrets and compromised third-party dependencies before code review; `make pre-pr` runs both. `.github/dependabot.yml` opens weekly update PRs for the `pip` and `npm` ecosystems.
