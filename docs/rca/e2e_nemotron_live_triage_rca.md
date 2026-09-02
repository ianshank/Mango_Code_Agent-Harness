# Nemotron E2E Triage & Root Cause Analysis

> **Consolidated from** two documents (tech-debt hardening plan R-TDH-24):
> the earlier revision of this file (`docs/rca/e2e_nemotron_live_triage_rca.md`,
> document version 1.0.0, 2026-08-30 — the live and mock pass over the
> governance broker and MAS loop, Defects 1–10) and
> `docs/NEMOTRON_E2E_TRIAGE_AND_RCA.md` (`DOC-RCA-2026-NEMO-E2E`, target
> milestone v2.3.1 — the later pass over the LangGraph StateGraph, LATS and MCP
> server, RCA-001–006), now deleted. The two passes ran against different
> trees and found different defects, so every finding is kept and each pass
> keeps its own section, evidence block and numbering rather than being
> re-counted into one list. Where the two overlap — both exercised
> `test_nemotron_bridge_live.py` credential resolution and the LangGraph
> regression suite — the later pass (Part B) is the current statement; the
> suite totals in Part A (1,918 passed, 57 Vitest cases, coverage 98.02 %) are
> that pass's measurements and are superseded by the numbers the gates report
> today.

---

## Part A — Live & mock E2E pass (document 1.0.0, 2026-08-30): governance broker and MAS, Defects 1–10

**Document Version:** 1.0.0  
**Date:** 2026-08-30  
**Target Branch:** `feature/e2e-nemotron-live-triage-rca`  
**Authors:** Senior Leadership & Engineering Panel (SWE, SQE, Architecture, AI Scientist, QA, Tools)

---

### 1. Executive Summary

A comprehensive, end-to-end evaluation of the Mango Multi-Agent System (MAS) and Governance Execution Broker was conducted across both mocked and live environments. Testing spanned:
- **Live NVIDIA Nemotron NIM API** (`meta/llama-3.1-70b-instruct`, `nvidia/nemotron-4-340b-instruct`)
- **Python Nemotron Bridge** (`harness/shared/nemotron_bridge.py`)
- **TypeScript Node Client** (`harness/node/src/ai/nemotron/client.ts`)
- **Multi-Agent Orchestrator** (`harness/shared/mango_mas_orchestrator.py`)
- **Governance Broker & Command Actions** (`harness/shared/governance/`)
- **Neuro-Symbolic Sandbox E2E** (`test_neurosym_sandbox_e2e.py`)

During live adversarial stress testing, **10 distinct defects** were identified, triaged from multiple technical perspectives, resolved with backward-compatible 2026 engineering patterns, and fortified with dedicated automated regression suites.

---

### 2. Triaged Defects & Multi-Perspective Root Cause Analysis

#### Defect 1: Windows CRLF Cross-Platform Newline Mangling in File Tools

- **Severity:** High (Data Integrity & Test Determinism)
- **Component:** `harness/shared/tool_executors.py`, `harness/shared/tests/test_tool_executors.py`
- **Symptom:** Unit and integration tests on Windows failed with newline mismatch assertions (`\r\n` vs `\n`).
- **Multi-Perspective Root Cause:**
  - *SWE / Tools:* `Path.write_text()` translates `\n` to `\r\n` on Windows by default. When `execute_read_file` opened files with `newline=""`, the raw `\r\n` byte sequences were exposed, breaking patch offsets and deterministic hash contracts.
  - *SQE / QA:* Test fixtures created test files via string writes instead of binary byte writes, masking OS-dependent line translation in non-Windows CI while failing on Windows developer machines.
- **Remediation:**
  - Implemented `_write_preserving_newlines()` in `tool_executors.py` using `open(..., "w", encoding="utf-8", newline="")`.
  - Updated test fixtures to use `write_bytes(b"...")` to guarantee bit-for-bit parity across all operating systems.

---

#### Defect 2: Incomplete Credential Fallback in Live Pytest Discovery

- **Severity:** Medium (CI/CD Test Skipping)
- **Component:** `harness/shared/tests/test_nemotron_bridge_live.py`
- **Symptom:** Live tests were skipped during local developer runs even when `.env` contained valid API credentials.
- **Multi-Perspective Root Cause:**
  - *SWE / Architecture:* `test_nemotron_bridge_live.py` performed a direct `os.environ.get("NVIDIA_API_KEY")` check at import time instead of delegating to `nemotron_bridge.resolve_api_key()`.
  - *AI Scientist:* The bridge supports multi-tiered credential discovery (process env > local `.env` > parent directories), but the test skipped before the bridge could resolve the key.
- **Remediation:**
  - Updated `test_nemotron_bridge_live.py` to gate test execution on `resolve_api_key()`.

---

#### Defect 3: Scratch Workspace Agent Prompt Resolution Failure

- **Severity:** High (Orchestrator Resilience)
- **Component:** `harness/shared/mango_mas_orchestrator.py`
- **Symptom:** `MangoMASOrchestrator(workspace_dir=tmp_path)` failed to load agent instructions (`planner.md`, `nemotron-reasoner.md`, `verifier.md`) with `FileNotFoundError`.
- **Multi-Perspective Root Cause:**
  - *SWE / Architecture:* `load_agent_prompt()` constructed the agent path strictly relative to `workspace_dir / ".mango" / "agents"`. When testing against temporary or standalone directories, `.mango` did not exist.
  - *SQE:* Isolated sandbox runs and ephemeral workspace tests require access to canonical agent personas without mutating the scratch directory.
- **Remediation:**
  - Added fallback in `load_agent_prompt()` to resolve prompts from the harness repository root `.mango/agents` directory when the local workspace does not contain a `.mango` folder.

---

#### Defect 4: Cross-Drive Workspace Boundary Enforcement in Live MAS Loops

- **Severity:** High (Execution Containment)
- **Component:** `harness/shared/tests/test_mango_mas_live.py`
- **Symptom:** Multi-agent reasoning loop timed out after 10 iterations because the reasoner received workspace denial errors.
- **Multi-Perspective Root Cause:**
  - *SWE / Security:* The orchestrator was initialized with `workspace_dir=repo_root` (on `E:`), while the test task requested writing to `tmp_path` (on `C:`).
  - *Architecture:* The Governance Broker strictly enforces workspace confinement (`_resolve_in_workspace`). When the agent attempted to write to `C:\Users\...\dynamic_util.py`, the broker correctly denied the write. The agent was forced to retry until exceeding its iteration budget.
- **Remediation:**
  - Updated `test_mango_mas_live.py` to instantiate `MangoMASOrchestrator(workspace_dir=tmp_path)` and specify workspace-relative target filenames (`dynamic_util.py`).

---

#### Defect 5: Bit Bucket / Discard Stream (`/dev/null`, `nul`) Denials in Command Broker

- **Severity:** High (Tool Execution Safety & Standard Compatibility)
- **Component:** `harness/shared/governance/command_actions.py`, `harness/shared/governance/broker.py`
- **Symptom:** Commands redirecting stdout or stderr to `/dev/null` or `nul` were blocked with `BLOCKED: /dev/null is an absolute path, and a write target must be workspace-relative`.
- **Multi-Perspective Root Cause:**
  - *SWE / Security:* `write_targets(command)` in `command_actions.py` parsed every redirection target and forwarded `/dev/null` to `write_policy.py`.
  - *Architecture:* `write_policy.py` enforces fail-closed checks against absolute paths outside the workspace. Because `/dev/null` is an absolute path, standard discard idioms (e.g., `python -m py_compile ... > /dev/null 2>&1`) were flagged as unauthorized writes.
- **Remediation:**
  - Added `discard_targets = {"/dev/null", "nul", "NUL", "/dev/zero", "/dev/stdout", "/dev/stderr"}` in `command_actions.py` to filter out stream bit buckets from file write target evaluations.

---

#### Defect 6: Verifier Agent Verdict Clarity on Scratch Workspaces

- **Severity:** Medium (LLM Agent Evaluation Invariant)
- **Component:** `harness/shared/agent_prompts.py` (`VERIFIER_PROMPT_TEMPLATE`)
- **Symptom:** When evaluating code in a standalone workspace without a `Makefile`, the verifier agent asked the user for the repository URL instead of reporting `PASS` or `FAIL`.
- **Multi-Perspective Root Cause:**
  - *AI Scientist / Prompt Engineering:* The verifier system prompt strongly emphasized executing repo-level make targets (`make validate`). In a scratch workspace lacking build files, the LLM defaulted to requesting context rather than inspecting the generated code files directly.
- **Remediation:**
  - Updated `VERIFIER_PROMPT_TEMPLATE` with explicit instructions: when running in scratch or standalone workspaces, verify the generated Python files directly and conclude with an unambiguous `VERDICT: PASS` or `VERDICT: FAIL`.

---

#### Defect 7: Unmodeled Python Script and Test Execution in Command Actions

- **Severity:** Critical (Agent Tool Autonomy & Test Verification)
- **Component:** `harness/shared/governance/command_actions.py`
- **Symptom:** Agent commands running `python <script.py>` or `python -m unittest <test.py>` were classified as `destructive` and blocked by the broker with `BLOCKED: action 'destructive' is not granted to implementer`.
- **Multi-Perspective Root Cause:**
  - *SWE / Security:* `command_actions.py` had entries for `pytest`, `make`, `ruff`, but lacked regex shapes recognizing `python script.py` and `python -m (pytest|unittest|py_compile|doctest)`. As a result, the default `UNCLASSIFIED_ACTION = "destructive"` triggered.
  - *SQE / QA:* In scratch workspaces where `pytest` is not invoked directly, agents rely on `python test.py` or `python -m unittest`.
- **Remediation:**
  - Added regex matchers to `_BY_SHAPE` in `command_actions.py` classifying `python [flags] script.py` and `python -m (pytest|unittest|py_compile|doctest)` as `test_execute`.
  - Maintained strict security: `python -c` remains classified as `UNCLASSIFIED_ACTION` to prevent unreviewed shell script injection.

---

#### Defect 8: Tool Discovery & Version Queries Blocked by Broker

- **Severity:** High (Agent Diagnostic Capability)
- **Component:** `harness/shared/governance/command_actions.py`
- **Symptom:** Agents probing environment tools using `python --version`, `py --version`, or `command -v python` were blocked as `destructive`.
- **Multi-Perspective Root Cause:**
  - *SWE / Architecture:* `command` was not present in `_BY_PROGRAM`, and `--version` / `-V` flags were not mapped to `read` actions.
- **Remediation:**
  - Added `"command": "read"` to `_BY_PROGRAM` (mirroring `which`).
  - Added `_BY_SHAPE` regex pattern mapping `python/py/node/pnpm/npm (--version|-V|-v|--help|-h)` to `read`.

---

#### Defect 9: Multi-Agent Prompt Chaining & Pipeline Alignment

- **Severity:** Medium (LLM Agent Reliability)
- **Component:** `harness/shared/agent_prompts.py`, `.mango/agents/nemotron-reasoner.md`, `.mango/agents/verifier.md`
- **Symptom:** Agents generated chained shell commands (`&&`, `;`, `|`) or attempted to read repo-level files (`governance-policy.json`) inside scratch directories.
- **Multi-Perspective Root Cause:**
  - *AI Scientist / Prompt Engineering:* The planner agent occasionally proposed `cat << EOF > file.py && python file.py`, which is rejected by security policy (`_COMPOUND`).
- **Remediation:**
  - Enforced strict prompt instructions forbidding compound shell commands and inline `python -c`.
  - Added rules to use `write_file` for new files and `run_command` for single standalone test executions.

---

#### Defect 10: Policy Bundle SHA256 Digest Staleness Post-Script Remediation

- **Severity:** High (Governance Integrity & Invariants)
- **Component:** `harness/control-plane/policy-bundle.example.json`
- **Symptom:** `test_build_policy_bundle.py` and `test_external_root_of_trust_verifies_protected_digests` failed because script digests differed from committed bundle.
- **Multi-Perspective Root Cause:**
  - *Architecture / Security:* `verify_zero_skips.py` was updated in the Node stack, changing its SHA256 digest. The repository bundle enforces cryptographic integrity.
- **Remediation:**
  - Executed `regenerate_bundle_digests.py` to synchronize SHA256 digests across all protected stack scripts.

---

### 3. Automated Quality Assurance (AQA) & Verification Matrix

#### 3.1 New Regression Test Suite
A dedicated test module was created at `harness/shared/tests/regression/test_e2e_nemotron_triage_regression.py` covering:
- `TestNewlinePreservationRegression`: Pure LF and explicit CRLF read/write binary roundtrips.
- `TestOrchestratorAgentPromptFallback`: Canonical prompt resolution in scratch workspaces.
- `TestCommandBrokerDiscardStreamFiltering`: Parameterized validation of `/dev/null`, `nul`, `2>/dev/null`, and `/dev/zero` redirection.
- `TestApiKeyResolutionRegression`: Environment variable and missing `.env` credential fallbacks.

#### 3.2 Test Execution Results
- **Full Non-Live Python Suite:** 1,918 passed (0 failed).
- **Node.js Vitest Suite:** 19 files, 57 passed (0 failed, zero skips passed).
- **Multi-Domain MAS Live Suite (`test_mango_mas_live.py`):** 3 passed:
  - `test_mango_mas_sequential_thinking_e2e` PASSED
  - `test_mango_mas_multi_file_app_synthesis_e2e` PASSED
  - `test_mango_mas_math_symbolic_reasoning_e2e` PASSED
- **Python Nemotron Live Integration Suite (`test_nemotron_bridge_live.py`):** 3 passed.
- **Neuro-Symbolic Sandbox Live E2E Suite (`test_neurosym_sandbox_e2e.py`):** 3 passed.
- **Strict Code Hygiene & Typing:**
  - `ruff check .`: 0 errors
  - `mypy`: 0 errors across 138 source files
  - `check_py_compat.py`: 158 files Python 3.9 compliant
  - `coverage_gate.py`: 98.02% lines, 95.01% branches (meets 90%/80% floors)
  - `validate_invariants.py`: Invariants passed

---

### 4. Invariant & Governance Compliance

| Invariant ID | Contract Requirement | Verification Result |
| :--- | :--- | :--- |
| **INV-1** | Deterministic Quality Gates | Passed (100% CI compliance across Python & Node) |
| **INV-2** | Zero Unattested Skips | Passed |
| **INV-4** | Secret & API Key Sanitization | Passed (`mask_secret` verified; zero leaks in telemetry) |
| **INV-8** | PreToolUse Governance Broker | Passed (Write target confinement & discard stream parity) |
| **INV-16** | Cross-Platform Execution Parity | Passed (Deterministic newline & path handling on Windows & POSIX) |

---

### 5. Conclusion & Release Readiness

All 10 triaged issues have been resolved with modular, backwards-compatible, type-checked implementations. The harness is fully certified for live production usage with NVIDIA Nemotron Ultra models.

---

## Part B — StateGraph, LATS & MCP E2E pass (`DOC-RCA-2026-NEMO-E2E`, target v2.3.1): RCA-001–006

**Document ID:** `DOC-RCA-2026-NEMO-E2E`  
**Target Milestone:** `v2.3.1`  
**Execution Context:** Mango Multi-Agent System (MAS), LangGraph 12-Channel StateGraph, LATS MCTS Optimizer, and MCP Server.

---

### 1. Executive Summary

An end-to-end (E2E) evaluation across all operational scenarios and boundary conditions was conducted for the **NVIDIA Nemotron Ultra** integration across the Mango MAS harness. Testing exercised the entire stack from low-level HTTP transport and secret sanitization to multi-agent ReAct orchestration, LATS MCTS tree search, MCP STDIO protocol servers, and the 12-channel StateGraph engine.

Six critical defects and systemic architectural edge cases were triaged, isolated, and remediated with full regression and Acceptance Quality Assurance (AQA) coverage.

---

### 2. E2E Scenario & Boundary Condition Matrix

| Scenario / Subsystem | Tested Interactions & Edge Cases | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **1. Wire Protocol & Transport** | Single/multi-turn messages, rate limits (HTTP 429), server errors (500, 502, 503, 504), connection timeouts, non-JSON response bodies, `Retry-After` header parsing, exponential jittered backoff. | `test_bridge_retry_regression.py`, `test_nemotron_api_aqa.py` | **PASS** |
| **2. Secret Sanitization & Privacy** | `mask_secret` prefix/suffix retention, zero-leakage in stdout, debug dumps, and HTTP responses for `NVIDIA_API_KEY`, `API_SERVER_KEY`, and `AGENT_EVIDENCE_KEY`. | `test_nemotron_api_aqa.py`, `test_api_server_regression.py` | **PASS** |
| **3. ReAct Multi-Agent Loop** | Planner $\to$ Reasoner $\to$ Verifier sequential thinking loop, multi-file code and test generation, tool budget tracking across turns. | `test_orchestrator_agent_loop.py`, `test_mango_mas_tools.py` | **PASS** |
| **4. LATS MCTS Optimization** | State branching, ablation diff isolation, UCB1 exploration vs exploitation, all-negative reward evaluation, deep tree backpropagation. | `test_lats_optimizer.py`, `test_e2e_nemotron_triage_regression.py` | **PASS** |
| **5. Model Context Protocol (MCP)** | STDIO JSON-RPC transport, role-based tool authorization, policy failure fail-closed, UTF-8/Unicode parameter encoding. | `test_mcp_server.py`, `test_e2e_nemotron_triage_regression.py` | **PASS** |
| **6. LangGraph StateGraph** | 12-channel state immutability, list accumulation (`operator.add`) vs LWW semantics, plan gate divergence boundary (0.35), quality gate routing. | `test_langgraph_regression.py`, `test_langgraph_nodes.py` | **PASS** |
| **7. Autonomous Healing** | Test failure diagnosis capture in `errors` channel, dynamic re-prompting with failure traceback, multi-turn revision recovery. | `test_e2e_nemotron_triage_regression.py` | **PASS** |

---

### 3. Root Cause Analysis (RCA) for Discovered Defects

#### RCA-001: `sys.path` Namespace Poisoning & Third-Party Library Shadowing

- **Defect ID:** `DEF-NEMO-001`
- **Severity:** High (Test Suite Flakiness / Module Import Corruption)
- **Symptom:** Regression tests failed with `RuntimeError: langgraph library is required to build StateGraph` whenever executed after live bridge tests.
- **Root Cause:** `test_nemotron_bridge_live.py` executed `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` and `test_bootstrap_fallbacks.py` executed raw `sys.path.insert(0, str(SHARED))`. Because `harness/shared` contains a subdirectory named `langgraph/`, prepending `harness/shared` to `sys.path[0]` caused Python's import resolver to load the local submodule instead of the installed 3rd-party `langgraph` package, corrupting `sys.modules` and clearing `StateGraph`.
- **Remediation:** Converted `test_nemotron_bridge_live.py` to use canonical absolute imports (`from harness.shared.nemotron_bridge import ...`) and updated `test_bootstrap_fallbacks.py` to use `monkeypatch.syspath_prepend()` with automatic teardown cleanup.

---

#### RCA-002: LATS MCTS Negative Reward Selection Boundary

- **Defect ID:** `DEF-NEMO-002`
- **Severity:** Medium (Algorithmic Suboptimality under Failure Penalties)
- **Symptom:** In MCTS planning rollouts where all candidate solutions produced negative scores (e.g. failing test penalties $-0.9$ vs $-0.1$), `_best_leaf` could fail to select the optimal leaf.
- **Root Cause:** `LATSOptimizer._best_leaf` initialized `best_avg = 0.0` rather than `float('-inf')`, and only inspected unexpanded leaves (`not node.children`), discarding visited internal nodes that had superior empirical performance.
- **Remediation:** Initialized `best_avg = float('-inf')` and updated search to evaluate all visited nodes ($visits > 0$) across the ablation tree.

---

#### RCA-003: Multi-Tool Turn Budget Exhaustion & Lifecycle Telemetry

- **Defect ID:** `DEF-NEMO-003`
- **Severity:** Medium (Governance Enforcement & Telemetry Accuracy)
- **Symptom:** When Nemotron generated multiple tool calls in a single turn exceeding the remaining budget (e.g., requesting 2 tool calls with budget limit 1), turn execution was interrupted without firing lifecycle hooks with explicit `budget_exceeded` status.
- **Root Cause:** Budget check lacked dedicated hook notification before raising runtime termination.
- **Remediation:** Orchestrator ReAct loop now fires `post-{agent}-run` hook with `status="budget_exceeded"` and ensures atomic rejection before any partial tool side-effects occur.

---

#### RCA-004: MCP Tool Argument Unicode & Stdio Safety

- **Defect ID:** `DEF-NEMO-004`
- **Severity:** Low (Cross-Platform / Internationalization)
- **Symptom:** Multi-byte UTF-8 paths (e.g., `café.py`) or international characters in tool payloads could risk encoding mismatches across platform stdio pipes.
- **Root Cause:** Implicit default encoding in string serialization without strict UTF-8 guarantees.
- **Remediation:** Guaranteed explicit UTF-8 normalization in tool executors and pinned with regression tests in `TestMCPUnicodeAndErrorIsolationRegression`.

---

#### RCA-005: Quality Gate Stub Bypass in StateGraph

- **Defect ID:** `DEF-NEMO-005`
- **Severity:** High (Autonomous Self-Healing Loop Inactive)
- **Symptom:** LangGraph StateGraph always exited to `END` on the first turn with `VERIFIED`, even when test evaluation reported failing test suites.
- **Root Cause:** `quality_gate_node` in `harness/shared/langgraph/nodes.py` contained a Phase 1 stub returning hardcoded `"quality_gate": "pass"` and `"verdict": "VERIFIED"`.
- **Remediation:** Replaced stub with full evaluation logic inspecting `test_results` and `errors`. When tests fail, `quality_gate_node` emits `quality_gate: "fail"`, routing the graph to `implementer_node` for revision.

---

#### RCA-006: Accumulator Channel History Collision in Quality Evaluation

- **Defect ID:** `DEF-NEMO-006`
- **Severity:** High (Infinite Loop / Graph Recursion Limit Exhaustion)
- **Symptom:** During multi-turn self-healing, after an initial failure was corrected by a subsequent revision, `quality_gate_node` still saw the previous failure and looped until hitting `GraphRecursionError: Recursion limit of 25 reached`.
- **Root Cause:** `test_results` is an accumulator channel (`operator.add`) storing full audit history. `quality_gate_node` checked `any(r["failed"] > 0 for r in test_results)`, which permanently flagged historical failures across all past turns.
- **Remediation:** Refined `quality_gate_node` to evaluate the **latest** revision's test result (`test_results[-1]`), confirming the current state of code quality while preserving historical audit logging.

---

### 4. Verification & Validation Evidence

All regression and AQA suites were executed and verified clean:

```text
harness/shared/tests/regression/test_e2e_nemotron_triage_regression.py ... 16 passed
harness/shared/tests/regression/test_langgraph_regression.py ............ 32 passed
harness/shared/tests/regression/test_bridge_retry_regression.py ........ 14 passed
harness/shared/tests/regression/test_nemotron_api_aqa.py ................ 4 passed
harness/shared/tests/regression/test_cross_platform_regression.py ....... 34 passed
harness/shared/tests/test_mcp_server.py ................................ 21 passed
harness/shared/tests/test_lats_optimizer.py ............................  9 passed
harness/shared/tests/test_ablation.py ..................................  5 passed
======================= 100% GREEN (Zero Regressions) =======================
```
