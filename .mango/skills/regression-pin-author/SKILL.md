---
name: regression-pin-author
description: |
  Guides the authoring of standalone defect reproduction test modules in the
  regression tier (harness/shared/tests/regression/) and pins them in
  test_regression_tier_pin.py per CONTRACT.md requirements.

  Use when:
  - Triage identifies a defect that reached main or broke an invariant
  - Adding an AQA reproduction test to guarantee no regression
  - Registering a new reproduction in REQUIRED_REGRESSION_MODULES

  Do NOT use for:
  - Writing generic unit tests (place those in harness/shared/tests/)
  - Adding flaky live network tests to the regression tier
---

# Regression-Pin Author Skill

## Purpose & Scope

`CONTRACT.md` mandates that every defect that reached `main` or broke an
invariant must have exactly one standalone reproduction in
`harness/shared/tests/regression/`. This ensures bugs cannot silently regress.

## Authoring Standards

### 1. Structure of a Reproduction Module

A regression pin module must:

1. Reside in `harness/shared/tests/regression/test_<defect_name>_regression.py`.

2. Include dynamic `REPO` bootstrapping to allow single-click IDE test execution:

   ```python
   import sys
   from pathlib import Path

   # Ensure repository root is on sys.path so direct execution or IDE runners succeed
   _REPO = Path(__file__).resolve().parents[4]
   if str(_REPO) not in sys.path:
       sys.path.insert(0, str(_REPO))
   ```

3. Define at least one reproduction function (e.g. `test_<repro_name>`).

4. End with an entrypoint runner:

   ```python
   if __name__ == "__main__":
       raise SystemExit(pytest.main([__file__, "-v"]))
   ```

### 2. Registration in Regression Tier Pin

Register the module in [`test_regression_tier_pin.py`](file:///e:/Coding_Projects/Harness_TEST/harness/shared/tests/regression/test_regression_tier_pin.py):

```python
REQUIRED_REGRESSION_MODULES = {
    ...
    "test_<defect_name>_regression.py": "test_<repro_name>",
}
```

### 3. Verification Gate

1. Direct execution: `python harness/shared/tests/regression/test_<defect_name>_regression.py`
2. Pin enforcement: `python harness/shared/tests/regression/test_regression_tier_pin.py`
3. Linter: `python -m ruff check harness/shared/tests/regression/test_<defect_name>_regression.py`
4. Typechecker: `python -m mypy harness/shared/tests/regression/test_<defect_name>_regression.py --explicit-package-bases --check-untyped-defs`
