# Agentic SSD & NVIDIA Nemotron AI Platform (Mango Ecosystem)

**Version:** 2.1.6 (2026 Standards)  
**Author:** Ian Cruickshank  
**Governing Standard:** Agentic SSD Gate Harness Contract v2.0 (`harness/CONTRACT.md`)

A production-grade, deterministic AI & software engineering platform featuring the **Autonomous Mango Multi-Agent Ecosystem**, the **NVIDIA Nemotron Ultra AI Reasoner**, and the **Deterministic Pong 2026 Simulation Engine**, backed by a full **7-tier test matrix** (243+ tests passing, 0 unapproved skips, >85% coverage) and fail-closed governance invariants.

---

## 1. Repository Layout

```
├── .agents/                             # Native Antigravity Agent Skill Registry
│   └── skills/
│       └── nemotron-reasoner/SKILL.md   # NVIDIA Nemotron AI operational skill
│
├── .mango/                              # Mango Multi-Agent Ecosystem
│   ├── agents/
│   │   ├── nemotron-reasoner.md         # NVIDIA Nemotron Ultra reasoning subagent
│   │   ├── planner.md                   # Pre-implementation task planning subagent
│   │   └── verifier.md                  # Strict post-change verification subagent
│   ├── hooks/
│   │   ├── block_dangerous.sh           # PreToolUse guard blocking destructive commands
│   │   ├── loop_detection.sh            # Anti-loop edit cycle detector
│   │   ├── pre_completion_checklist.sh  # Pre-completion deterministic test validation
│   │   ├── save_state_before_compact.sh # Context compaction state persistence
│   │   └── session_start.sh             # Environment & credentials verification hook
│   ├── skills/
│   │   ├── nemotron-reasoner/SKILL.md   # NVIDIA Nemotron AI operational cheatsheet
│   │   └── harness-engineering/SKILL.md # Harness inspection & extension rules
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
│   │   │   └── pong/                    # Deterministic Pong 2026 Engine
│   │   │       ├── ai/ai-opponent.ts    # Raycasting trajectory predictive AI
│   │   │       ├── audio/               # Web Audio procedural oscillator & null driver
│   │   │       ├── core/                # Continuous collision detection (CCD) & FSM
│   │   │       ├── input/               # Decoupled keyboard & action polling
│   │   │       ├── loop/game-loop.ts    # Fixed-timestep accumulator loop
│   │   │       ├── render/              # High-DPI Canvas 2D & ANSI Terminal renderers
│   │   │       └── web/index.html       # Standalone 2026 Web UI with Telemetry HUD
│   │   ├── tests/                       # 7-Tier Vitest Matrix (80 tests passing)
│   │   │   ├── ai/                      # 18 Nemotron AI tests across 7 tiers
│   │   │   └── pong/                    # 62 Pong engine tests across 7 tiers
│   │   └── docs/specs/                  # 15 Bidirectionally-traced formal specifications
│   │
│   ├── shared/                          # Shared Policy Kernel & Governance Tools
│   │   ├── mango_mas_orchestrator.py    # Multi-Agent System Orchestrator
│   │   ├── meta_tools.py                # Meta-learning and context state tools
│   │   ├── nemotron_bridge.py           # Zero-dependency Python Nemotron bridge
│   │   ├── governance/                  # Extracted fail-closed policy mechanisms
│   │   │   ├── pretooluse_guard.py      # Native command-level PreToolUse guard
│   │   │   └── check_traceability.py    # Requirement specification tracing
│   │   └── tests/                       # Python AQA Engine (133 Tests / 98.44% Coverage)
│   │       ├── conftest.py              # Reusable Pytest fixtures
│   │       └── test_harness.py          # Adversarial governance self-tests
│   │
│   └── control-plane/                   # Policy bundles, digests & external verifier
│
├── .env.example                         # Environment configuration template
├── .gitignore                           # Git ignore rules protecting local secrets
├── .gitleaks.toml                       # Gitleaks security scan configuration
├── .dockerignore                        # Docker build context policy (includes .mango)
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

### 2.3 Deterministic Pong 2026 Engine (`harness/node/src/pong/`)
- **Physics & Math:** Pure 2D vector mathematics with Continuous Collision Detection (CCD) and dynamic paddle spin deflection.
- **Predictive AI:** Multi-tier AI featuring raycasted bounce trajectory estimation and adaptive edge targeting.
- **Multi-Target Rendering:** High-DPI HTML5 Canvas 2D with CRT glow & particle bursts, plus text-mode ANSI Terminal renderer.
- **Procedural Audio:** Web Audio API procedural oscillator synthesis without external audio files.

---

## 3. 7-Tier Test Matrix & Governance

The platform enforces the **Agentic SSD Gate Harness Contract v2.0** with **zero test skips** (`INV-2`):

```
                 ▲
                / \     Tier 7: Sanity & Stress Tests (Resilience & Concurrency)
               /---\    Tier 6: Security & Secret Sanitization Tests (INV-1 Leak Check)
              /-----\   Tier 5: User Journey Tests (Multi-Agent Delegation Workflows)
             /-------\  Tier 4: E2E Tests (CLI Terminal & Autonomous Autoplay)
            /---------\ Tier 3: Functional Tests (Match Progression & Multi-Turn Chats)
           /-----------\Tier 2: Integration Tests (SSE Streaming & Engine Events)
          /-------------\Tier 1: Unit Tests (Vector Math, Physics, Config, SecretMasker)
```

- **Total Automated Tests:** **213 / 213 passing** (80 Vitest + 133 Pytest tests)
- **Node Code Coverage (V8):** **95.9% Statements \| 85.4% Branches \| 94.48% Functions \| 96.46% Lines**
- **Python AQA Coverage:** **98.44% Statements** (504/512 covered)
- **Requirements Traceability:** **15 / 15 specifications** traced bidirectionally (`check_traceability.py`)

---

## 4. Quick Start Guide

### 4.1 Configuration
Copy the template and set your NVIDIA API key:
```bash
cp .env.example .env
# Edit .env and set: NVIDIA_API_KEY=nvapi-your-key-here
```

### 4.2 Running the Pong Game
```bash
cd harness/node

# Launch standalone terminal CLI game (autoplay tournament)
npx tsx src/pong/cli/pong-cli.ts --autoplay --ticks 100 --difficulty hard

# Open the Web Canvas UI
# Simply open harness/node/src/pong/web/index.html in any browser
```

### 4.3 Querying NVIDIA Nemotron Ultra
```bash
# Via TypeScript CLI (Node)
cd harness/node
npx tsx src/ai/nemotron/cli.ts --prompt "Analyze state machine transitions in src/pong/core/state-machine.ts" --stream

# Via Python Bridge
python harness/shared/nemotron_bridge.py --prompt "Audit INV-1 secret scan rules"
```

### 4.4 Running Automated Verification
```bash
# 1. Install dependencies
cd harness/node
pnpm install
cd ../..
pip install -r requirements-dev.txt

# 2. Run Node/Vitest test matrix (80 tests)
cd harness/node
pnpm vitest run
pnpm exec tsc --noEmit
pnpm exec knip
cd ../..

# 3. Run Python AQA Engine & Governance Validators
make ci         # Runs lint -> coverage -> test-node -> zero-skips -> validate
make lint       # Runs ruff and mypy on all Python sources
make test       # Runs full test suite (Pytest + Vitest + Zero-Skips)
make validate   # Runs all 6 governance execution invariants

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
make lint       # Static analysis, formatting checks, and strict typing
make coverage   # Enforce >=80% code coverage threshold
make test-node  # Execute TypeScript/Node engine tests
make validate   # Execute all 6 governance invariants (adoption, policy, remotes, traceability)
make pre-pr     # Full pre-submission validation pipeline
```

### 5.4 Secret Sanitization & Security Scanning
- **Invariant `INV-1` Enforcement:** Never output raw API tokens or credentials in logs or test assertions. Use `SecretMasker` and the native Python regex masks.
- **Pre-Push Allowlist (`remotes.py`):** Push targets are strictly validated against `.governance/allowed-remotes.txt` to prevent code leakage to unauthorized repositories.
- **Automated Gitleaks & OSV Scanners:** Run `gitleaks` and `osv-scanner` locally and in CI to catch hardcoded secrets or compromised third-party dependencies before code review.
