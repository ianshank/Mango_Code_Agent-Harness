# Agentic SSD & NVIDIA Nemotron AI Platform (Mango Ecosystem)

**Version:** 2.5.0 (2026 Standards)
**Author:** Ian Cruickshank
**Governing Standard:** Agentic SSD Gate Harness Contract v2.1 (`harness/CONTRACT.md`)

A fail-closed **policy and attestation layer** for AI coding agents — bring your own agent, bring your own model. The live loop is planner → reasoner → verifier under the Agentic SSD Gate Harness Contract v2.1 (`harness/CONTRACT.md`). The default reasoner is NVIDIA NIM (`nvidia/llama-3.3-nemotron-super-49b-v1`); the client speaks the OpenAI `/chat/completions` wire protocol. LangGraph is an accepted-parked experiment (DEC-053), not the production orchestrator. Tests are gated by `verify-zero-skips` (0 unapproved skips) and coverage floors from `governance-policy.json` (INV-1..INV-17).

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
│   ├── workflows/                       # SDLC & critic orchestration workflows
│   │   ├── narrow-critic.md             # Read-only security and style critic
│   │   └── sdlc-orchestrator.md         # End-to-end SDLC orchestrator
│   ├── hooks/
│   │   ├── block_dangerous.sh           # PreToolUse guard blocking destructive commands
│   │   ├── loop_detection.sh            # Anti-loop edit cycle detector
│   │   ├── pre-nemotron-run.sh          # Fired by the orchestrator before each agent turn
│   │   ├── pre_completion_checklist.sh  # Pre-completion deterministic test validation
│   │   ├── save_state_before_compact.sh # Context compaction state persistence
│   │   └── session_start.sh             # Environment & credentials verification hook
│   ├── skills/                          # 17 reusable skills; the only skill root
│   │   ├── agent-memory-manager/        # Persistent memory and context bridging
│   │   ├── boundary-invariant-review/   # Cognitive/execution boundary review (INV-16)
│   │   ├── coverage-gate/               # Coverage threshold sourced from policy
│   │   ├── evidence-signing/            # Reusable HMAC evidence manifest skill
│   │   ├── gate-mutation-proof/         # Prove a gate catches the defect it names
│   │   ├── god-file-decomposer/          # Safely decompose oversized modules
│   │   ├── harness-engineering/         # Harness inspection & extension rules
│   │   ├── nemotron-reasoner/           # NVIDIA Nemotron AI operational cheatsheet
│   │   ├── openspec-peer-review/        # Architecture/SDLC/QA/Product peer review
│   │   ├── protected-path-attestation/  # Produces the per-file attestation block
│   │   ├── repo-invariant-review/       # Predicts concrete CI failures pre-push
│   │   ├── regression-pin-author/        # Pin regression reproductions into AQA
│   │   ├── shadow-channel-analysis/     # UC-4 agreement/latency/token reporting
│   │   ├── spec-authoring/              # Spec scaffolding and required sections
│   │   ├── standards-audit/             # Yearly external-standards audit with a falsification pass
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
│   ├── reports/                         # Hygiene, peer-review, test and standards-audit reports (2026-STANDARDS-AUDIT.md is current)
│   └── specs/                           # Formal traceable specifications (+ SPEC_TEMPLATE.md)
│
├── harness/                             # Enterprise Governance & Multi-Stack Harness
│   ├── api_server/                      # FastAPI Web Server & Orchestration Dashboard (:8080)
│   │   ├── main.py                      # REST endpoints (/api/orchestrate, /healthz, /readyz) & static file server
│   │   ├── messages.py                  # Per-role history wire models (tool_calls survive the round trip)
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
│   │   ├── context_policy.py            # Policy-sourced context-window budget / tool-group eviction (H4)
│   │   ├── mango_mas_orchestrator.py    # Backwards-compatible ReAct loop facade
│   │   ├── experimental/                # Parked, unwired capabilities (DEC-027): autonomous_healing.py, lats_optimizer.py
│   │   ├── mcp_server.py                # Model Context Protocol (MCP) STDIO server
│   │   ├── langgraph/                   # LangGraph StateGraph (parked, DEC-053; live loop is ExecutionLoop)
│   │   │   ├── state.py                 # 12-Channel partitioned typed state (Accumulator vs LWW)
│   │   │   ├── nodes.py                 # 10 active, gate, and reviewer nodes
│   │   │   ├── graph.py                 # StateGraph builder and conditional DAG routing
│   │   │   ├── policy.py                # GraphExecutionPolicy configuration
│   │   │   ├── decorators.py            # @with_authority & @budgeted runtime gates
│   │   │   └── ablation.py              # MCTS ablation & hypothetical state channels
│   │   ├── agent_prompts.py             # Persona prompts, guardrails & hook names
│   │   ├── tool_executors.py            # Tool executors + the shared PDP write authorization
│   │   ├── tool_dispatch.py             # Tool call argument normalization & dispatch
│   │   ├── tool_arg_validation.py       # Schema check of model-sent tool arguments before any executor runs
│   │   ├── tool_schemas.py              # OpenAI/Nemotron-compatible tool definitions
│   │   ├── cognitive_signal.py          # Versioned CognitiveSignal envelope + JSONL sink
│   │   ├── shadow_planner.py            # Observation-only shadow plan comparison channel
│   │   ├── meta_tools.py                # Meta-learning tools: what a record means, how the model writes one
│   │   ├── memory_store.py              # Store mechanics: file_lock, malformed recovery, FIFO, append_locked
│   │   ├── memory_view.py               # Readers: operator (unbounded) and reasoner prompt (policy-bounded, DEC-058)
│   │   ├── show_memory.py               # `make memory-show` CLI over both stores
│   │   ├── nemotron_bridge.py           # Zero-dependency Python Nemotron bridge
│   │   ├── write_policy.py              # Runtime write gate: protected_paths, .git, credentials
│   │   ├── agent_authority.py           # Per-role tool exposure derived from agent-policy.json
│   │   ├── authority_graph.py           # Authority reachability on two named surfaces; derived, never stored (DEC-065)
│   │   ├── authority_call_sites.py      # AST scan: no caller may hand the broker a `human_approved` it did not build
│   │   ├── code_safety.py               # Prohibited-symbol judgement over the tree generate_code already parsed
│   │   ├── graph_topology.py            # StateGraph nodes/edges from source via ast; imports no langgraph
│   │   ├── check_dedup.py               # Drift gate: shim vs copy detection (make check-dedup)
│   │   ├── check_py_compat.py           # Compat gate against the CI matrix floor, 3.10 today (make check-compat)
│   │   ├── ast_visitors.py              # AST visitor rules the compatibility gate applies
│   │   ├── governance/                  # Extracted fail-closed policy mechanisms
│   │   │   ├── broker.py                # ExecutionBroker — INV-8/9/10 on the live path
│   │   │   ├── execution_backend.py     # ExecutionBackend protocol, request, capabilities, result
│   │   │   ├── process_backend.py       # ProcessBackend adapter — containment, not isolation
│   │   │   ├── command_actions.py       # Command → declared policy action (fails closed)
│   │   │   ├── policy_decision.py       # In-process PDP; mirrors tool_broker_reference.py
│   │   │   ├── evidence_manifest.py     # EvidenceBuilder — HMAC-signed audit trails
│   │   │   ├── evidence_record.py       # INV-13 digest-of-digests + JSONL sink (does not import broker)
│   │   │   ├── capability_probe.py      # INV-13 AC-12 host inventory (stdlib, spawn-free)
│   │   │   ├── pretooluse_guard.py      # Native command-level PreToolUse guard
│   │   │   ├── verification.py          # VerificationRunner — earned verdict evaluation, tamper-refusing
│   │   │   ├── enforcement_digest.py    # Digest of the protected enforcement set the verdict is earned against
│   │   │   ├── indirect_exec.py         # make/pnpm/npx argument grading: no indirect shell via test_execute
│   │   │   └── check_traceability.py    # Requirement specification tracing
│   │   └── tests/                       # Python AQA Engine (count in §3, not restated here; coverage gate from policy)
│   │       ├── conftest.py              # Reusable Pytest fixtures
│   │       ├── regression/              # Dedicated AQA Regression Tier
│   │       │   ├── test_scripts_hook_shims.py        # AQA-001: Hook shim existence, bash shebang, dynamic paths
│   │       │   ├── test_scan_findings_windows_waiver.py # AQA-002: DEC-061 waiver liveness
│   │       │   ├── test_gaps_memory_integrity.py     # AQA-004: MEM-1 gaps.json no-stub invariant
│   │       │   ├── test_process_backend_isolation_regression.py # AQA-006: RecordingBackend probe isolation
│   │       │   ├── test_langgraph_regression.py      # 37 tests: StateGraph invariants, calling, reductions & fail-closed verdict
│   │       │   ├── test_cross_platform_regression.py # 34 tests: cross-platform path/env/secret invariants
│   │       │   ├── test_bridge_retry_regression.py   # Retry jitter & backoff invariants
│   │       │   └── test_orchestrator_dispatch_regression.py # Dispatch edge-cases & budget handling
│   │       ├── test_orchestrator_init.py       # Orchestrator initialization & prompt loading
│   │       ├── test_orchestrator_tools.py      # Write & command tool execution
│   │       ├── test_orchestrator_hooks.py      # Pre/post lifecycle hooks
│   │       ├── test_orchestrator_agent_loop.py # ReAct execution loop & budget limits
│   │       ├── test_evidence_manifest.py       # EvidenceBuilder signing & immutability
│   │       ├── test_evidence_record.py         # INV-13 AC-5…AC-8 broker evidence path
│   │       ├── test_capability_probe.py        # INV-13 AC-12 host inventory
│   │       ├── test_execution_backend.py       # protocol, ProcessBackend adapter, execution.routing
│   │       ├── test_governance_broker.py       # INV-8/9/10, in-process PDP, ProcessBackend
│   │       └── test_protected_path_liveness.py # Asserts protected_paths match real files
│   │
│   └── control-plane/                   # Policy bundles, digests & external verifier
│       ├── publish_policy_artifact.py   # Versioned, digest-pinned, attestable policy artifact
│       ├── policy-artifact.json         # Committed artifact; drift-gated by the test suite
│       └── tests/                       # Colocated control-plane suite (101 tests; R-TDH-26)
│
├── scripts/                             # Operational & CI hook shims
│   ├── verify-tier-a.sh                 # Tier-A lint & static verification hook shim
│   └── guard-forbidden-paths.sh         # Invariant protected-paths guard hook shim
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
- **Agent Memory (`<workspace>/.mango/memory/`):** the reasoner records what it could not determine (`knowledge_gap_log`) and what it believes on what evidence (`hypothesis_register`, revisable append-only per DEC-057). Both stores are read back into the next run's prompts under policy bounds — open gaps to the planner, open hypotheses (with the ids `revises` accepts) to the reasoner (DEC-058) — and an operator can read them with `make memory-show`. Every bound lives in `governance-policy.json` → `agent_memory`, read through `policy_loader.agent_memory_defaults` (a present policy missing a key fails closed; an absent policy yields the built-in default):

  | Key | Shipped | Bounds |
  |---|---|---|
  | `max_gaps` / `max_hypotheses` | 100 / 100 | retention per store (FIFO) |
  | `planner_gap_limit` | 10 | open gaps rendered into the planner prompt |
  | `reasoner_hypothesis_limit` | 10 | open hypotheses rendered into the reasoner prompt; `0` disables the block |
  | `reasoner_hypothesis_budget_tokens` | 1500 | estimated tokens for that whole block, measured with `orchestrator.context_chars_per_token`; the first entry that would overflow stops the render |

### 2.2 NVIDIA Nemotron Ultra AI Adapter (`harness/node/src/ai/nemotron/`)

- **Provider-Agnostic Client:** Full compatibility with OpenAI `/chat/completions` API wire protocol.
- **Resilience Engine:** Exponential backoff with full jitter on HTTP 429/5xx and 3-state Circuit Breaker (`CLOSED` → `OPEN` → `HALF_OPEN`).
- **Secret Sanitization (`INV-1`):** `SecretMasker` masks keys (`nvapi-sSeC...NcWq`) in all error strings and logs.
- **Dual Runtimes:** TypeScript client with native SSE streaming + zero-dependency Python bridge (`nemotron_bridge.py`).

### 2.3 Governance Kernel (`harness/shared/governance/`)

- **`ExecutionBroker`** (`broker.py`): the approved execution path INV-8 names, reached from the orchestrator's `run_command`. `execute_command` derives the action from the command (`command_actions.classify`), obtains an in-process policy verdict (`policy_decision.decide`, mirroring `tool_broker_reference.py` and pinned by `test_policy_decision.py`), runs `check_command()`, then executes via an `ExecutionBackend` (default `ProcessBackend`) with a pinned working directory, a timeout and a byte-capped output. `sandbox_available` defaults to probing the backend; an unavailable backend returns `BLOCKED` and never falls through (INV-9), and a denial is terminal (INV-10). **The default backend contains but does not isolate** — it confines neither the filesystem nor the network — so INV-13's sandbox digest is not yet satisfiable (DEC-010). Four of five INV-13 digests are recordable on the opt-in evidence path (`evidence_record.py`). An evidence-enabled keyless broker returns `BLOCKED` naming `AGENT_EVIDENCE_KEY` before spawn. `execution.routing` of `refuse` is BLOCKED before spawn and, when a key is present, still written to evidence.
- **`command_actions.py`**: classifies a command into a declared policy action. An allowlist, not a denylist: anything unmodelled resolves to an action no role holds, so an unrecognised command denies for every agent.
- **`policy_decision.py`**: the verdict, in process. Replaces a host subprocess that ran *before* the command guard, from a path inside the agent's workspace (DEC-009).
- **`write_policy.py`**: enforces `protected_paths` on the agent's write tool at tool-call granularity, plus any `.git` directory segment and any credential-bearing filename (`.env*`, `.netrc`, `.npmrc`, `.pypirc`, `id_[rd]sa`, `*.pem`) — three classes `validate_invariants` structurally cannot see, the last because `.env` is untracked and so matched no `protected_paths` pattern at all (DEC-007, DEC-042).
- **`read_policy.py`**: the read-side counterpart to `write_policy.py`. `command_actions.classify` already denies reading a credential through `run_command` (graded `secret_access`, an action no role holds); `read_policy.read_denial_reason` closes the same gap for the orchestrator's `read_file` handler, which reads the filesystem directly and so is invisible to that classifier. The pattern has one definition, in `write_policy`, re-exported here and composed by `command_actions` — three anchorings of one alternation rather than three that can drift (DEC-012, DEC-042).
- **`agent_authority.py`**: derives each active role's tool exposure from `agent-policy.json`. The verifier holds no `write_file` (DEC-008) or `apply_patch` (DEC-012) — both grade as the `write` action, which every canonical contract the verifier maps to already denied in prose — but does hold `read_file`.
- **`authority_graph.py` / `authority_call_sites.py`**: a **derived** view of that same chain — recomputed on every query from the functions the broker calls, and never stored, because a persisted copy of governance state is a cache whose staleness has a security consequence. It models the two grant surfaces separately, since they deliberately disagree (`planner` holds `spec_write` while executing as `orchestrator`, which lacks it), and a query that names neither surface raises rather than confidently answering the other question. Its second half machine-checks what was previously true only by construction: across all 114 first-party non-test modules there are 5 callers of `ExecutionBroker.execute_command` and **0** that could supply `policy_decision.decide`'s `human_approved` (DEC-065).
- **`code_safety.py`**: the `generate_code` write door's second question of one parse tree. `execute_generate_code` already ran `ast.parse` to answer *does it compile*; the same tree now answers *does this name a `synthesis.prohibited_imports` symbol*, and a match denies the write before any byte reaches disk. It resolves aliases, attribute targets and `__import__`, because that policy key's five entries span three shapes and an import-only checker would decide two of them while reporting success.
- **`graph_topology.py`**: recovers the LangGraph `StateGraph` node and edge sets from `graph.py`'s **source** via `ast`, importing nothing from `langgraph` — so the check needs no `skipif` on an optional extra and cannot become a skip hunting an INV-2 waiver. It is what lets an ordinary test pin `peer_reviewer` and `security_reviewer` as edgeless *and* pin that this is DEC-052's recorded state, while DEC-053's park keeps the topology **gate** unbuilt.
- **`EvidenceBuilder`** (`evidence_manifest.py`): HMAC-SHA256 signed audit trail builder. Signing key injected via constructor or `AGENT_EVIDENCE_KEY` env var. On the control-plane publisher, `export()` raises `ValueError` (fail-closed) when the key is absent. On the broker path the key is injected at construction; a keyless evidence-enabled broker never reaches `export()`. `export()` is non-destructive and deterministic. See `.mango/skills/evidence-signing/SKILL.md`.
- **`evidence_record.py`**: folds the loop-start enforcement snapshot into one digest-of-digests, names policy/backend/test digests, and appends signed JSONL. Does not import `broker` (C-AEI-5) and does not re-walk `enforcement_digests` (R-AEI-7). The entry cap is `policy_defaults.evidence_defaults` (C-AEI-2).
- **`check_dedup.py`**: CI drift gate — fails when per-stack governance scripts are full copies instead of thin shims delegating to `harness/shared`. Run via `make check-dedup`.
- **`check_py_compat.py`**: CI compatibility gate — fails when any source file uses syntax unavailable in the lowest interpreter the CI matrix declares (`datetime.UTC`, and PEP 604 unions / unannotated `AnnAssign` below 3.10). The floor is *resolved from the workflow matrix*, not written down here, so moving the matrix moves the gate; it is 3.10 today (`docs/specs/python-floor-310.md`). Run via `make check-compat`.

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

## 3. Test Matrix & Governance

The platform enforces the **Agentic SSD Gate Harness Contract v2.1** with **zero unapproved test skips** (`INV-2`).

The Node AI suite still uses an eight-directory layout under `harness/node/tests/ai/` (unit, integration, functional, e2e, journey, smoke, security, sanity). Python is selected by path and pytest markers (`governance`, `security`, `neurosym`, `langgraph`, `live`), not by that pyramid. The Pong demo those tier labels used to name was removed (`docs/specs/remove-pong-demo.md`).

- **Suite size:** do not transcribe a headcount here. `pytest --collect-only` (Python) and `pnpm vitest run` (Node) are the measurement; a carried-forward figure is a claim, not a measurement (DEC-024).
- **Coverage floors:** `governance-policy.json` → `coverage` (lines, statements, branches, functions, per-file). Python applies lines and branches (plus per-file lines) via `coverage_gate.py`; Node applies the same keys via vitest. The measured *set* is bounded — `coverage_scope.check_measured_set` fails closed if the report and the on-disk first-party sources disagree. Zero-statement `__init__.py` files are skipped by `check_per_file` rather than waived. The CI matrix is `["3.10", "3.12", "3.14"]` (DEC-064).
- **Windows Platform Parity:** DEC-061 (make-guards), DEC-062 (asyncio), DEC-063 (AF_UNIX). Linux CI has no unapproved skips where `make` and `AF_UNIX` are available; Windows expected skips live in `harness/shared/tests/skip-waivers.json`, not as a number copied into this file.
- **Requirements Traceability:** `python harness/shared/governance/check_traceability.py --workspace .` prints the discovered count, the uncited ratchet and the headroom. Before DEC-065 the gate ran from `harness/node` and read 6 IDs disjoint from the root corpus. The backlog is bounded rather than waived: `traceability.min_discovered_requirement_ids` is an anti-vacuity floor, and `traceability.max_uncited_contract_requirement_ids` may only be lowered. Per-stack configs declare no `scope` and are unaffected. Live numbers are what the command prints — do not restate them here.
- **Governance Drift Gate:** `check_dedup.py` — fails CI when per-stack scripts copy instead of delegate to `harness/shared`
- **Compatibility Gate:** `check_py_compat.py` — fails CI if any source uses syntax newer than the lowest interpreter in the CI matrix, resolved from the workflow rather than hard-coded; that is **3.10** since `docs/specs/python-floor-310.md` moved the floor and the matrix became `["3.10", "3.12", "3.14"]`

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
corepack enable       # activates the pnpm version pinned by packageManager in harness/node/package.json
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
make lint            # ruff + mypy + check_py_compat (compat gate at the CI matrix floor)
make test            # Full test suite (Pytest + Vitest + Zero-Skips)
make test-regression # Run regression/AQA tier only (reproductions + rollback pins + portability)
make test-governance # Governance-specific tests in isolation (broker, evidence, invariants)
make test-neurosym   # Neuro-symbolic synthesis tests (pytest -m neurosym)
make validate        # Governance invariants (adoption, policy, remotes, traceability)
make verify-skip-waivers  # Validate skip-waivers.json schema (pure Python, runs on Windows; DEC-061/062)
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

### 4.4 Windows IDE Setup (Pylance / Antigravity IDE)

A `pyrightconfig.json` is committed at the repo root. It sets `extraPaths = ["."]` so
that Pylance resolves `harness.*` imports without a `pip install -e .`. This mirrors the
`pythonpath = ["."]` entry in `pyproject.toml`'s `[tool.pytest.ini_options]`.

```json
// pyrightconfig.json (root)
{
  "extraPaths": ["."],
  "venvPath": ".",
  "venv": ".venv"
}
```

Expected Windows skips are the DEC-061/DEC-062/DEC-063 rows in
`harness/shared/tests/skip-waivers.json` (make absent, asyncio TCP fallback,
AF_UNIX). Linux CI has no unapproved skips where those primitives exist.
A number copied into this file is a claim, not a measurement (DEC-024).

---

## 5. Utilizing This Platform for Code Development

This platform is engineered as an **Agentic Software Security & Development (SSD) Harness**. It provides a hardened foundation for building deterministic, AI-orchestrated, and highly compliant software systems.

### 5.1 Multi-Agent Autonomous Development Workflow

The `.mango/` ecosystem enables specialized subagent collaboration during development:

1. **Planning (`planner.md`):** Before executing large features or refactors, invoke the Planner subagent to generate sequentially ordered implementation plans with explicit verification criteria.
2. **Deep Reasoning & Auditing (`nemotron-reasoner.md`):** Delegate architectural analysis, mathematical invariant verification, and adversarial threat modeling to NVIDIA Nemotron Ultra (`nvidia/llama-3.3-nemotron-super-49b-v1`).
3. **Automated Verification (`verifier.md`):** Ensure every code change is validated through deterministic test runners (`pytest`, `vitest`), typecheckers (`mypy`, `tsc`), and linters (`ruff`, `eslint`) before marking work complete.

### 5.2 Tests and traceability

When introducing new features or modules:

- **Write the test that names the defect.** Node AI tests still live under the eight directories in `harness/node/tests/ai/`; Python uses path (`harness/shared/tests/regression/` for AQA reproductions) and markers. Do not invent a pyramid row that the code does not have.
- **Fail-Closed Zero Skips (`INV-2`):** Tests cannot be arbitrarily skipped. A Python waiver must be declared in `harness/shared/tests/skip-waivers.json` citing an approved decision from `docs/decisions/` (Node: `harness/node/.governance/skip-waivers.json`; thin ID index still at `harness/node/.governance/decision-log.md` for `--decision-log`). There is no root `.governance/skip-waivers.json`.
- **Bidirectional Traceability:** Add requirement tags (e.g. `R-FEATURE-1`, `C-SEC-1`) to code *and* test docstrings; `python harness/shared/governance/check_traceability.py --workspace .` reads every ID in `docs/specs/` and reports each uncited one with the side it is missing from. A repository-scoped run is not required to reach zero — it must clear `traceability.min_discovered_requirement_ids` and stay at or below `traceability.max_uncited_contract_requirement_ids`, a ratchet that may only be lowered. A document whose IDs name scheduled work declares `Spec class: program-plan`; a document declaring nothing is graded strictly, so the permissive class is never the default.

### 5.3 Local Development & Gate Validation

Use the unified root `Makefile` to enforce enterprise quality gates locally prior to committing:

```bash
make lint            # Static analysis, formatting checks, strict typing, compat gate
make coverage        # Coverage floors from governance-policy.json (not a literal here)
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
- **Pre-Push Allowlist (`remotes.py`):** Agent-initiated `git push` is blocked because the repository root has **no** `.governance/allowed-remotes.txt` (DEC-005; the absence is the control). Per-stack allowlists live at `harness/node/.governance/allowed-remotes.txt` and `harness/jvm/.governance/allowed-remotes.txt`. Do not create a root allowlist without a superseding DEC (DEC-056 names the intended replacement and has not landed).
- **Automated Gitleaks, pip-audit & OSV Scanners:** `make secrets` (gitleaks; INV-1) and `make audit` (`pip-audit` against `requirements.txt` + delegated Node `osv-scanner`) run locally and in dedicated CI jobs (`secret-scan`, `dependency-audit`) to catch hardcoded secrets and compromised third-party dependencies before code review; `make pre-pr` runs both. `.github/dependabot.yml` opens weekly update PRs for the `pip` and `npm` ecosystems.
