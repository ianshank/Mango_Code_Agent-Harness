# E2E Nemotron Integration: Edge Case Triage & Root Cause Analysis (RCA)

**Document ID:** `DOC-RCA-2026-NEMO-E2E`  
**Target Milestone:** `v2.3.1`  
**Execution Context:** Mango Multi-Agent System (MAS), LangGraph 12-Channel StateGraph, LATS MCTS Optimizer, and MCP Server.

---

## 1. Executive Summary

An end-to-end (E2E) evaluation across all operational scenarios and boundary conditions was conducted for the **NVIDIA Nemotron Ultra** integration across the Mango MAS harness. Testing exercised the entire stack from low-level HTTP transport and secret sanitization to multi-agent ReAct orchestration, LATS MCTS tree search, MCP STDIO protocol servers, and the 12-channel StateGraph engine.

Six critical defects and systemic architectural edge cases were triaged, isolated, and remediated with full regression and Acceptance Quality Assurance (AQA) coverage.

---

## 2. E2E Scenario & Boundary Condition Matrix

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

## 3. Root Cause Analysis (RCA) for Discovered Defects

### RCA-001: `sys.path` Namespace Poisoning & Third-Party Library Shadowing

- **Defect ID:** `DEF-NEMO-001`
- **Severity:** High (Test Suite Flakiness / Module Import Corruption)
- **Symptom:** Regression tests failed with `RuntimeError: langgraph library is required to build StateGraph` whenever executed after live bridge tests.
- **Root Cause:** `test_nemotron_bridge_live.py` executed `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` and `test_bootstrap_fallbacks.py` executed raw `sys.path.insert(0, str(SHARED))`. Because `harness/shared` contains a subdirectory named `langgraph/`, prepending `harness/shared` to `sys.path[0]` caused Python's import resolver to load the local submodule instead of the installed 3rd-party `langgraph` package, corrupting `sys.modules` and clearing `StateGraph`.
- **Remediation:** Converted `test_nemotron_bridge_live.py` to use canonical absolute imports (`from harness.shared.nemotron_bridge import ...`) and updated `test_bootstrap_fallbacks.py` to use `monkeypatch.syspath_prepend()` with automatic teardown cleanup.

---

### RCA-002: LATS MCTS Negative Reward Selection Boundary

- **Defect ID:** `DEF-NEMO-002`
- **Severity:** Medium (Algorithmic Suboptimality under Failure Penalties)
- **Symptom:** In MCTS planning rollouts where all candidate solutions produced negative scores (e.g. failing test penalties $-0.9$ vs $-0.1$), `_best_leaf` could fail to select the optimal leaf.
- **Root Cause:** `LATSOptimizer._best_leaf` initialized `best_avg = 0.0` rather than `float('-inf')`, and only inspected unexpanded leaves (`not node.children`), discarding visited internal nodes that had superior empirical performance.
- **Remediation:** Initialized `best_avg = float('-inf')` and updated search to evaluate all visited nodes ($visits > 0$) across the ablation tree.

---

### RCA-003: Multi-Tool Turn Budget Exhaustion & Lifecycle Telemetry

- **Defect ID:** `DEF-NEMO-003`
- **Severity:** Medium (Governance Enforcement & Telemetry Accuracy)
- **Symptom:** When Nemotron generated multiple tool calls in a single turn exceeding the remaining budget (e.g., requesting 2 tool calls with budget limit 1), turn execution was interrupted without firing lifecycle hooks with explicit `budget_exceeded` status.
- **Root Cause:** Budget check lacked dedicated hook notification before raising runtime termination.
- **Remediation:** Orchestrator ReAct loop now fires `post-{agent}-run` hook with `status="budget_exceeded"` and ensures atomic rejection before any partial tool side-effects occur.

---

### RCA-004: MCP Tool Argument Unicode & Stdio Safety

- **Defect ID:** `DEF-NEMO-004`
- **Severity:** Low (Cross-Platform / Internationalization)
- **Symptom:** Multi-byte UTF-8 paths (e.g., `café.py`) or international characters in tool payloads could risk encoding mismatches across platform stdio pipes.
- **Root Cause:** Implicit default encoding in string serialization without strict UTF-8 guarantees.
- **Remediation:** Guaranteed explicit UTF-8 normalization in tool executors and pinned with regression tests in `TestMCPUnicodeAndErrorIsolationRegression`.

---

### RCA-005: Quality Gate Stub Bypass in StateGraph

- **Defect ID:** `DEF-NEMO-005`
- **Severity:** High (Autonomous Self-Healing Loop Inactive)
- **Symptom:** LangGraph StateGraph always exited to `END` on the first turn with `VERIFIED`, even when test evaluation reported failing test suites.
- **Root Cause:** `quality_gate_node` in `harness/shared/langgraph/nodes.py` contained a Phase 1 stub returning hardcoded `"quality_gate": "pass"` and `"verdict": "VERIFIED"`.
- **Remediation:** Replaced stub with full evaluation logic inspecting `test_results` and `errors`. When tests fail, `quality_gate_node` emits `quality_gate: "fail"`, routing the graph to `implementer_node` for revision.

---

### RCA-006: Accumulator Channel History Collision in Quality Evaluation

- **Defect ID:** `DEF-NEMO-006`
- **Severity:** High (Infinite Loop / Graph Recursion Limit Exhaustion)
- **Symptom:** During multi-turn self-healing, after an initial failure was corrected by a subsequent revision, `quality_gate_node` still saw the previous failure and looped until hitting `GraphRecursionError: Recursion limit of 25 reached`.
- **Root Cause:** `test_results` is an accumulator channel (`operator.add`) storing full audit history. `quality_gate_node` checked `any(r["failed"] > 0 for r in test_results)`, which permanently flagged historical failures across all past turns.
- **Remediation:** Refined `quality_gate_node` to evaluate the **latest** revision's test result (`test_results[-1]`), confirming the current state of code quality while preserving historical audit logging.

---

## 4. Verification & Validation Evidence

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
