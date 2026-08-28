# Agentic SSD & NVIDIA Nemotron AI Platform (Mango Ecosystem)

**Version:** 2.1.9 (2026 Standards)
**Author:** Ian Cruickshank
**Governing Standard:** Agentic SSD Gate Harness Contract v2.1 (`harness/CONTRACT.md`)

A production-grade, deterministic AI & software engineering platform featuring the **Autonomous Mango Multi-Agent Ecosystem** and the **NVIDIA Nemotron Ultra AI Reasoner**, backed by a multi-tier test matrix across Python + Node (0 unapproved skips per `verify-zero-skips`, coverage gate sourced from `governance-policy.json`) and fail-closed governance invariants (INV-1..INV-16).

---

## 1. Repository Layout

```text
├── .agents/                             # Native Antigravity Agent Skill Registry
│   └── skills/
│       └── nemotron-reasoner/SKILL.md   # NVIDIA Nemotron AI operational skill
│
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
│   ├── skills/                          # 10 reusable skills; see .mango/skills/
│   │   ├── boundary-invariant-review/   # Cognitive/execution boundary review (INV-16)
│   │   ├── coverage-gate/               # Coverage threshold sourced from policy
│   │   ├── evidence-signing/            # Reusable HMAC evidence manifest skill
│   │   ├── harness-engineering/         # Harness inspection & extension rules
│   │   ├── nemotron-reasoner/           # NVIDIA Nemotron AI operational cheatsheet
│   │   ├── openspec-peer-review/        # Architecture/SDLC/QA/Product peer review
│   │   ├── repo-invariant-review/       # Predicts concrete CI failures pre-push
│   │   ├── shadow-channel-analysis/     # UC-4 agreement/latency/token reporting
│   │   ├── spec-authoring/              # Spec scaffolding and required sections
│   │   └── validation-runner/           # Single entry point for the validation matrix
│   └── settings.json                    # Mango agent lifecycle hook bindings
│
├── harness/                             # Enterprise Governance & Multi-Stack Harness
│   ├── node/                            # Node/TypeScript Engine & AI Adapter
│   │   ├── src/
│   │   │   ├── ai/nemotron/             # NVIDIA Nemotron Ultra Client Adapter
│   │   │   │   ├── circuit-breaker.ts   # 3-State circuit breaker (CLOSED/OPEN/HALF_OPEN)
│   │   │   │   ├── cli.ts               # Standalone CLI runner with streaming & JSON output
│   │   │   │   ├── nemotron-client.ts   # Core client with SSE streaming & jittered backoff
│   │   │   │   ├── secret-masker.ts     # Invariant INV-1 credential redactor
│   │   │   │   └── types.ts             # Strict TypeScript contracts
│   │   ├── tests/                       # Multi-tier Vitest matrix
│   │   │   └── ai/                      # Nemotron AI tests across 7 tiers
│   │   └── docs/specs/                  # Bidirectionally-traced formal specifications
│   │
│   ├── shared/                          # Shared Policy Kernel & Governance Tools
│   │   ├── mango_mas_orchestrator.py    # Multi-Agent System Orchestrator
│   │   ├── cognitive_signal.py          # Versioned CognitiveSignal envelope + JSONL sink
│   │   ├── shadow_planner.py            # Observation-only shadow plan comparison channel
│   │   ├── meta_tools.py                # Meta-learning, context state, and file_lock
│   │   ├── nemotron_bridge.py           # Zero-dependency Python Nemotron bridge
│   │   ├── schemas/                     # JSON Schema docs (agent policy, evidence, signals)
│   │   ├── check_dedup.py               # Drift gate: shim vs copy detection (make check-dedup)
│   │   ├── check_py_compat.py           # Python 3.9 compatibility gate (make check-compat)
│   │   ├── governance/                  # Extracted fail-closed policy mechanisms
│   │   │   ├── broker.py                # ExecutionBroker — INV-8/INV-9 enforcement
│   │   │   ├── evidence_manifest.py     # EvidenceBuilder — HMAC-signed audit trails
│   │   │   ├── pretooluse_guard.py      # Native command-level PreToolUse guard
│   │   │   └── check_traceability.py    # Requirement specification tracing
│   │   └── tests/                       # Python AQA Engine (659 tests; coverage gate from policy)
│   │       ├── conftest.py              # Reusable Pytest fixtures
│   │       ├── test_evidence_manifest.py # 17 tests: EvidenceBuilder signing & immutability
│   │       ├── test_governance_broker.py # 11 tests: INV-8/INV-9, PDP, BLOCKED semantics
│   │       ├── test_harness.py          # Adversarial governance self-tests
│   │       ├── test_protected_path_liveness.py # Asserts protected_paths match real files, not just strings
│   │       ├── test_ci_gate_coverage.py # INV-5: every ci_required_target is reachable from `make ci`
│   │       └── test_validation_scripts_extra.py # 21 tests covering the governance validation scripts
│   │
│   └── control-plane/                   # Policy bundles, digests & external verifier
│       ├── publish_policy_artifact.py   # Versioned, digest-pinned, attestable policy artifact
│       └── policy-artifact.json         # Committed artifact; drift-gated by the test suite
│
├── .env.example                         # Environment configuration template
├── .gitignore                           # Git ignore rules protecting local secrets
├── .gitleaks.toml                       # Gitleaks security scan configuration
├── .dockerignore                        # Docker build context policy (excludes .mango)
├── Dockerfile                           # Multi-stage production container image
├── Makefile                             # Unified root Makefile for CI/CD targets
├── pyproject.toml                       # Python tool configuration (ruff, mypy, pytest)
└── requirements-dev.txt                 # Python development dependencies
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

- **`ExecutionBroker`** (`broker.py`): Fail-closed execution gate enforcing INV-8 (pretooluse_guard) and INV-9 (no host-process fallback). Returns `BLOCKED` when sandbox is unavailable — never falls back to direct host execution. PDP policy verdicts configurable; `check_command()` is the inner guard.
- **`EvidenceBuilder`** (`evidence_manifest.py`): HMAC-SHA256 signed audit trail builder. Signing key injected via constructor or `AGENT_EVIDENCE_KEY` env var. Raises `ValueError` (fail-closed) when key is absent. `export()` is non-destructive and deterministic. See `.mango/skills/evidence-signing/SKILL.md`.
- **`check_dedup.py`**: CI drift gate — fails when per-stack governance scripts are full copies instead of thin shims delegating to `harness/shared`. Run via `make check-dedup`.
- **`check_py_compat.py`**: CI compatibility gate — fails when any source file uses syntax unavailable in Python 3.9 (PEP 604 unions, `datetime.UTC`, unannotated `AnnAssign`). Run via `make check-compat`.

**Required environment variable:**

| Variable             | Purpose                                                                         |
|----------------------|---------------------------------------------------------------------------------|
| `AGENT_EVIDENCE_KEY` | HMAC signing key for `EvidenceBuilder`. Never hard-code. Set in secret store. |

---

## 3. 7-Tier Test Matrix & Governance

The platform enforces the **Agentic SSD Gate Harness Contract v2.0** with **zero unapproved test skips** (`INV-2`):

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

- **Total Automated Tests:** **425+ automated tests** (95 Vitest + 330+ Pytest tests across 7 tiers)
- **Node Code Coverage (V8):** **≥90% Statements | ≥80% Branches | ≥90% Functions | ≥90% Lines**
- **Python AQA Coverage:** **≥90% total** across `harness/shared` and `harness/api_server`
- **Requirements Traceability:** **15 / 15 specifications** traced bidirectionally (`check_traceability.py`)
- **Governance Drift Gate:** `check_dedup.py` — fails CI when per-stack scripts copy instead of delegate to `harness/shared`
- **Compatibility Gate:** `check_py_compat.py` — fails CI if any source uses syntax newer than Python 3.9

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

| Variable | Effect |
|---|---|
| `MANGO_SHADOW_PLANNER` | Exactly `1` enables the observation-only shadow plan comparison; any other value is off. |
| `MANGO_SHADOW_MODEL` | Alternate model for the shadow pass (defaults to the orchestrator model). |
| `MANGO_SHADOW_TIMEOUT_SEC` | Shadow-pass timeout; capped at the orchestrator API timeout. |
| `MANGO_SIGNAL_DIR` | Overrides the signal sink directory (default `<workspace>/.mango/memory/signals/`). |

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

# 2. Run Node/Vitest test matrix
cd harness/node
pnpm vitest run
pnpm exec tsc --noEmit
pnpm exec knip
cd ../..

# 3. Run Python AQA Engine & Governance Validators
make ci              # Full pipeline: lint → coverage → test-node → zero-skips → validate → dedup → digest-regen
make lint            # ruff + mypy + check_py_compat (Python 3.9 compat gate)
make test            # Full test suite (Pytest + Vitest + Zero-Skips)
make test-governance # Governance-specific tests in isolation (broker, evidence, invariants)
make test-neurosym   # Neuro-symbolic synthesis tests (pytest -m neurosym)
make validate        # Governance invariants (adoption, policy, remotes, traceability)
make check-dedup     # Drift gate: per-stack scripts must delegate to harness/shared
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
make pre-pr          # Full pre-submission validation pipeline
```

### 5.4 Secret Sanitization & Security Scanning

- **Invariant `INV-1` Enforcement:** Never output raw API tokens or credentials in logs or test assertions. Use `SecretMasker` and the native Python regex masks.
- **Pre-Push Allowlist (`remotes.py`):** Push targets are strictly validated against `.governance/allowed-remotes.txt` to prevent code leakage to unauthorized repositories.
- **Automated Gitleaks & OSV Scanners:** Run `gitleaks` and `osv-scanner` locally and in CI to catch hardcoded secrets or compromised third-party dependencies before code review.
