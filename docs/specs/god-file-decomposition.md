# Spec: God File Decomposition & Modularization

## Problem statement

Static analysis and architecture review identified multiple "god files" in `harness/shared/` and `harness/shared/tests/`. The largest production offender, `harness/shared/mango_mas_orchestrator.py` (501 lines), couples 7 distinct responsibilities into a single monolithic class. The corresponding test file `test_mango_mas_orchestrator.py` (629 lines, 50 test functions across 13 classes) suffers from dense coupling and monolithic test fixture management. Other modules (`governance/broker.py` and `check_py_compat.py`) contain embedded helper classes/visitors that reduce maintainability and test isolation.

## Requirements (R-*)

- R-GFD-1: The orchestrator prompt definitions (`PLANNER_PROMPT_TEMPLATE`, `REASONER_PROMPT_TEMPLATE`, `VERIFIER_PROMPT_TEMPLATE`, `AUTONOMOUS_AGENT_GUARDRAIL`, `TASK_LOG_PREVIEW_CHARS`) MUST be extracted into a dedicated `harness/shared/agent_prompts.py` module.
- R-GFD-2: Tool argument coercion (`_normalize_tool_arguments`), hypothesis defaults (`DEFAULT_HYPOTHESIS_CONFIDENCE`), and dispatch abstractions MUST be extracted into a dedicated `harness/shared/tool_dispatch.py` module.
- R-GFD-3: Workspace file writing with confinement guards (`_execute_write_file`) and broker command execution (`_execute_run_command`) MUST be extracted into standalone, testable functions in `harness/shared/tool_executors.py`.
- R-GFD-4: AST visitor helpers in `check_py_compat.py` (`find_pep604`, `find_datetime_utc`, `has_future_annotations`, `find_pep604_assignments`, etc.) MUST be extracted into `harness/shared/ast_visitors.py`.
- R-GFD-5: Subprocess management in `governance/broker.py` (`ProcessBackend` and output capping `_cap`) MUST be extracted into `harness/shared/governance/process_backend.py`.
- R-GFD-6: Monolithic test suite `test_mango_mas_orchestrator.py` MUST be decomposed into four focused test suites (`test_orchestrator_init.py`, `test_orchestrator_tools.py`, `test_orchestrator_hooks.py`, `test_orchestrator_agent_loop.py`) with shared fixtures in `tests/_orchestrator_helpers.py`.
- R-GFD-7: All extracted symbols MUST be re-exported in their original parent modules to preserve 100% backward compatibility for all external callers and tests.
- R-GFD-8: The total test suite MUST maintain 100% pass rate with zero new skips and ≥90% coverage threshold enforced by `coverage_gate.py`.

## Citations (C-*)

- C-GFD-1: `harness/CONTRACT.md` (INV-1 through INV-16, core authority model, fail-closed policy enforcement).
- C-GFD-2: `governance-policy.json` (Coverage lines ≥90%, branches ≥85%, per-file line minimums).
- C-GFD-3: `.mango/agents/` (Role contracts for planner, nemotron-reasoner, verifier).
- C-GFD-4: `docs/specs/orchestrator-tool-registry.md` (Tool registry dispatch and schema contracts).
- C-GFD-5: `docs/specs/agent-containment.md` (Fail-closed execution broker and write containment).

## Acceptance criteria

- [ ] AC-1: `harness/shared/agent_prompts.py`, `tool_dispatch.py`, `tool_executors.py`, `ast_visitors.py`, and `governance/process_backend.py` created and fully typed with docstrings.
- [ ] AC-2: `mango_mas_orchestrator.py` line count reduced by at least 40% (under 300 lines) with all public and internal interfaces re-exported.
- [ ] AC-3: `test_mango_mas_orchestrator.py` successfully decomposed into 4 cohesive test suites, passing with zero failures.
- [ ] AC-4: `python -m ruff check harness/shared/` passes with 0 errors.
- [ ] AC-5: `python -m pytest harness/shared/tests/ harness/api_server/tests/ -m "not live"` passes with 100% pass rate.
- [ ] AC-6: `test_import_purity.py` and `test_import_direction.py` verify no circular dependencies or side effects at import.

## Invariants touched

- INV-8: Approved execution broker dispatch remains intact in `tool_executors.py` and `governance/broker.py`.
- INV-10: Terminal DENY verdicts cannot be overridden; policy decision pipeline remains unchanged.
- INV-16: One-directional cognitive/execution boundary preserved.

## Validation matrix

- `make lint` — ruff verification across all extracted and modified modules.
- `make test-python` — full pytest execution including regression tier.
- `make coverage-python` — coverage gate enforcement (≥90% lines, ≥85% branches).
- `make validate` — mechanical invariants and protected paths validation.

## Backward compatibility

All extracted constants, functions, and classes are explicitly re-exported via `__all__` or direct module-level imports in their legacy locations. Legacy callers importing from `harness.shared.mango_mas_orchestrator`, `harness.shared.governance.broker`, or `harness.shared.check_py_compat` experience zero breaking changes.

## Open questions

None. Extraction boundaries are strictly cohesive and preserve existing public interfaces.
