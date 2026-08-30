# God File Decomposition & Architecture Modularization Guide

**Document Version:** 1.0.0  
**Target Release:** v2.2.0  
**Status:** Approved Architecture Reference  
**Audience:** SWE, SQE, AI Scientist, Hardware/Robotics Engineers, System Architects

---

## 1. Architectural Motivation & Invariants

This refactoring decomposes monolithic modules across `harness/shared/` and its test suites to enforce strict Single Responsibility Principle (SRP), clean cognitive/execution boundaries (INV-16), and fail-closed security invariants (INV-1 through INV-16).

```text
+-------------------------------------------------------------------------------+
|                             MangoMAS Architecture                            |
+-------------------------------------------------------------------------------+
                                      |
         +----------------------------+---------------------------+
         |                                                        |
         v                                                        v
+-----------------------------+                         +-----------------------------+
|    Cognitive Plane (LATS)   |                         |     Execution Plane         |
|  - Planner Prompt / Agent   |                         |  - Tool Executors           |
|  - Meta Tools (Hypothesis)  |                         |  - PreToolUse Guards        |
|  - Shadow Comparison        |                         |  - Process Backend          |
+-----------------------------+                         +-----------------------------+
                 \                                     /
                  \                                   /
                   v                                 v
                 +-------------------------------------+
                 |      Execution Broker / PDP         |
                 |  - Policy Decision (Fail-Closed)    |
                 |  - Confinement & Write Policy       |
                 |  - Dynamic Policy Budgets           |
                 +-------------------------------------+
```

---

## 2. Component Decomposition Map

### 2.1 `harness/shared/mango_mas_orchestrator.py` (501 Lines -> ~200 Lines)

The orchestrator previously mixed prompt templates, tool argument coercion, file I/O operations, command execution, and ReAct loop state.

| Responsibility | Extracted Target Module | Key Symbols |
| :--- | :--- | :--- |
| Prompt Templates | `harness/shared/agent_prompts.py` | `PLANNER_PROMPT_TEMPLATE`, `REASONER_PROMPT_TEMPLATE`, `VERIFIER_PROMPT_TEMPLATE`, `AUTONOMOUS_AGENT_GUARDRAIL`, `TASK_LOG_PREVIEW_CHARS` |
| Tool Argument Normalization & Routing | `harness/shared/tool_dispatch.py` | `_normalize_tool_arguments`, `DEFAULT_HYPOTHESIS_CONFIDENCE`, `ToolDispatchRegistry` |
| Local Tool Execution (Filesystem / Process) | `harness/shared/tool_executors.py` | `execute_write_file`, `execute_read_file`, `execute_apply_patch`, `execute_run_command` |
| Core ReAct Loop & Lifecycle Hooks | `harness/shared/mango_mas_orchestrator.py` | `MangoMASOrchestrator`, `execute_agent`, `execute_loop`, `_run_hook` |

### 2.2 `harness/shared/governance/broker.py` (356 Lines -> ~180 Lines)

| Responsibility | Extracted Target Module | Key Symbols |
| :--- | :--- | :--- |
| Subprocess Execution & Stream Capping | `harness/shared/governance/process_backend.py` | `ProcessBackend`, `ExecutionResult`, `_cap` |
| Policy Decision & Sandboxed Broker | `harness/shared/governance/broker.py` | `ExecutionBroker`, `verify_sandbox`, `execute_command` |

### 2.3 `harness/shared/check_py_compat.py` (338 Lines -> ~200 Lines)

| Responsibility | Extracted Target Module | Key Symbols |
| :--- | :--- | :--- |
| Pure AST Syntax Inspection | `harness/shared/ast_visitors.py` | `has_future_annotations`, `find_pep604`, `find_datetime_utc`, `find_pep604_assignments` |
| CLI Runner & Report Generation | `harness/shared/check_py_compat.py` | `run`, `build_parser`, `main`, `CompatReport` |

---

## 3. Test Suite Modularization Map

The 629-line monolithic `test_mango_mas_orchestrator.py` is divided into 4 modular test modules sharing centralized fixtures in `harness/shared/tests/_orchestrator_helpers.py`:

```text
harness/shared/tests/
  ├── _orchestrator_helpers.py       <-- Centralized mocks: _resp, _tool_call, mock_workspace
  ├── test_orchestrator_init.py       <-- TestInit, TestLoadAgentPrompt
  ├── test_orchestrator_tools.py      <-- TestExecuteWriteFile, TestExecuteRunCommand, TestToolRegistry
  ├── test_orchestrator_hooks.py      <-- TestRunHook, TestHookEnvironmentIsStrippedOfCredentials
  └── test_orchestrator_agent_loop.py <-- TestExecuteAgent, TestSequentialThinkingLoop, TestPolicySourcedLimits
```

---

## 4. Backwards Compatibility & Migration Protocol

To guarantee zero breakage across downstream adopters and external test runners:

1. **Re-export Pattern**:

   ```python
   # In harness/shared/mango_mas_orchestrator.py:
   from harness.shared.agent_prompts import (
       AUTONOMOUS_AGENT_GUARDRAIL,
       PLANNER_PROMPT_TEMPLATE,
       REASONER_PROMPT_TEMPLATE,
       TASK_LOG_PREVIEW_CHARS,
       VERIFIER_PROMPT_TEMPLATE,
   )
   from harness.shared.tool_dispatch import (
       DEFAULT_HYPOTHESIS_CONFIDENCE,
       _normalize_tool_arguments,
   )
   from harness.shared.tool_executors import (
       execute_run_command,
       execute_write_file,
   )

   __all__ = [
       "MangoMASOrchestrator",
       "PLANNER_PROMPT_TEMPLATE",
       "REASONER_PROMPT_TEMPLATE",
       "VERIFIER_PROMPT_TEMPLATE",
       "AUTONOMOUS_AGENT_GUARDRAIL",
       "NEMOTRON_TOOLS",
       "_normalize_tool_arguments",
   ]
   ```

2. **Zero Circular Dependencies**:
   - `agent_prompts.py`: 0 internal imports.
   - `tool_dispatch.py`: standard library (`json`, `logging`, `typing`) only.
   - `tool_executors.py`: imports from `agent_authority`, `debug_dump`, `write_policy`, `tool_result_format`.
   - `mango_mas_orchestrator.py`: imports from the above.

---

## 5. Verification & Quality Gates

Run all quality checks prior to committing:

```bash
# 1. Static Linting & Formatting
python -m ruff check harness/shared/ --output-format=concise

# 2. Spec Validation
python harness/shared/validate_specs.py

# 3. Import Purity & Directional Dependency Verification
python -m pytest harness/shared/tests/test_import_purity.py harness/shared/tests/test_import_direction.py -v

# 4. Full Non-Live Test Suite Execution
python -m pytest harness/shared/tests/ harness/api_server/tests/ -m "not live" -q
```
