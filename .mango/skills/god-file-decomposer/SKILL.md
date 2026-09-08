---
name: god-file-decomposer
Reviewed: 2026-09-08
description: |
  Identifies, plans, and executes the decomposition of monolithic "god files"
  that approach or exceed the repository size budgets (500 lines for production
  files, 700 lines for test files under validate_invariants.py).

  Use when:
  - Any production module exceeds 450 lines (approaching 500-line ceiling)
  - Any test module exceeds 600 lines (approaching 700-line ceiling)
  - Refactoring tightly coupled components into cohesive sub-modules

  Do NOT use for:
  - Bypassing size budgets with artificial line concatenation or minification
  - Breaking public API contracts or module export surfaces
---

# God-File Decomposer Skill

## Purpose & Scope

Repository invariants strictly forbid production files over 500 lines and test
files over 700 lines (`validate_invariants.py`). This skill establishes an
automated, safe, non-breaking workflow to decompose approaching files.

## Workflow

### 1. Telemetry & Target Identification

Scan repository files and sort by line count:

```bash
python -c "
from pathlib import Path
for p in sorted(Path('harness').glob('**/*.py')):
    lines = len(p.read_text(encoding='utf-8').splitlines())
    if ('tests' in str(p) and lines > 600) or ('tests' not in str(p) and lines > 450):
        print(f'{lines:4d} lines: {p}')
"
```

### 2. Decomposition Strategy

1. **Identify Cohesive Sub-Domains:**
   - Group by data models / dataclasses.
   - Group by error types and reason constants.
   - Group by dispatch / execution handlers vs. public facades.

2. **Extract to Sibling Modules:**
   - Create sibling module (e.g. `nodes_executors.py` or `test_mcp_server_dispatch.py`).
   - Preserve all imports and type annotations.

3. **Maintain Facade Re-Exports:**
   - In original file, re-export all moved symbols using `from .child import ... as ...` or `__all__`.
   - Ensure zero breakage for existing callers and external consumers.

4. **Verification Gate:**
   - Verify size budget: `python harness/shared/validate_invariants.py`
   - Run full unit & regression suite: `make test-python` or `python -m pytest <affected>`
   - Verify lint & type safety: `make lint` (ruff check, ruff format --check, mypy,
     vulture) and then `make lint-cold`, the no-cache typecheck CI runs. The cold
     pass is not optional here: mypy's incremental cache is keyed on module paths,
     so moving symbols between modules is exactly the change a warm cache can hide.

## Safety Invariants

- Zero breaking changes to public package interfaces (`__all__` parity).
- No hardcoded paths or platform-specific separators.
- Strict BOM-free UTF-8 encoding.
