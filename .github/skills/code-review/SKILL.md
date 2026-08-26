---
name: code-review
description: Objective peer review of work, gap analysis, and tech debt identification. Enforces code hygiene, dynamic/backwards compatible design, and best testing practices (AQA/SQE tasks).
---

# Code Review Skill

This skill provides guidelines and patterns for performing rigorous, objective peer code reviews within the Mango-Metrics-NLM ecosystem.

## Objectives
- **Gap Analysis & Code Hygiene:** Scan for missed edge cases, architectural gaps, and hygiene violations (Ruff, Mypy, Vitest, Eslint).
- **Tech Debt Identification:** Identify and document shortcuts, hardcoded values, and non-reusable patterns.
- **Dynamic & Backwards Compatible Design:** Ensure components are modular, reusable, and do not introduce breaking changes without explicit rationale.
- **Testing Best Practices:** Enforce a full test suite (Unit, Integration, Functional, E2E) with >80% coverage and zero skipped tests (INV-2).
- **Logging & Debugging:** Ensure adequate observability and debugging context is added to new or modified flows.

## Process
1. **Analyze Codebase Context:** Review the implementation against the PR description and any linked tickets.
2. **Hygiene & Lint Checks:** Execute local verification checks:
   ```bash
   make lint
   make test
   ```
3. **Traceability:** Verify that every new feature or test includes appropriate requirement tags (e.g. `R-FEATURE-X`).
4. **Agent Workflows:** Ensure hooks/loops (e.g., `pretooluse_guard.py`) and agent integrations (`mango_mas_orchestrator.py`) are properly wired and configured.

## Output
Generate a structured code review summary containing:
- **Gap Analysis:** What was missed or insufficiently handled.
- **Tech Debt & Code Hygiene:** Specific Ruff/Mypy/Lint violations or structural issues.
- **Testing Deficiencies:** Areas lacking coverage or missing required testing tiers.
- **Recommendations:** Actionable, specific fixes for the identified issues.
