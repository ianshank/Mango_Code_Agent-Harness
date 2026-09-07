# Spec: python-floor-310

> Scaffolded by `make spec NAME=python-floor-310`. Child spec required by
> `docs/specs/reflection-hardening-increment.md` R-RHI-1 / Step 1, superseding
> DEC-028 before the floor bump lands. Implemented in the same PR as this
> scaffold (the increment document's Step 1 and Step 2 landed together, since
> the spec's only consumer is the bump itself and splitting them across two
> PRs would leave the first with no code to review against).

## Problem statement

DEC-028 (2026-09-02) accepted keeping the Python 3.9 floor because, at the
time, `langgraph` was optional and every runtime dependency still supported
3.9. Neither holds any more:

- `langgraph>=0.2` (`requirements-langgraph.txt`) already declares
  `Requires-Python: >=3.10`; the 3.9 CI leg could never install it, so
  `pyproject.toml`'s own `mcp` dependency and `requirements.txt` carried a
  `python_version >= "3.10"` fork, and `.github/workflows/python-package.yml`
  set `MANGO_CI_DESELECT_LANGGRAPH=1` on the 3.9 leg so `conftest.py` would
  deselect the `langgraph`-marked suites there instead of reporting a hard
  failure — the exact "skip instead of fail" shape `tech-debt-hardening-plan`
  R-TDH-4 forbids everywhere else.
- 3.9 reached end-of-life 2025-10-06 (upstream CPython schedule); no
  currently-supported CPython release remains on that floor.
- `requirements-lock.txt` regenerates with `uv pip compile --python-version 3.9`,
  which forces every dependency resolvable on 3.9 to carry a
  `python_full_version` marker fork even though the CI matrix's actual legs
  (3.9/3.10/3.12) mostly agree on one resolution — dead specificity that
  exists only because the lock command targets a floor nothing in the matrix
  needs any more once 3.9 is dropped.
- `harness/shared/check_py_compat.py` carries a PEP 604 (`X | Y`) union
  minimum-version check that is inert once the floor itself is 3.10 (PEP 604
  is native there); the check's own docstring cites the 3.9 floor as the
  reason it exists.
- `.github/rulesets/main.json`'s required-check list names
  `dependency-audit (3.9)`, and the audit job carries a
  `continue-on-error: true` on that leg specifically — a required check
  that is simultaneously permitted to fail is a contradiction the ruleset
  should not encode.

Evidence for each claim above: `requirements-langgraph.txt` (`langgraph`
version pin), `docs/decisions/DEC-028.md` (superseded status, this change),
`.github/workflows/python-package.yml` HEAD~1 (`MANGO_CI_DESELECT_LANGGRAPH`
keyed off `matrix.python-version == '3.9'`), `requirements-lock.txt` HEAD~1
header comment (`--python-version 3.9`).

## Requirements

- R-PF-1: `pyproject.toml`'s `[project].requires-python` MUST read `>=3.10`.
- R-PF-2: No dependency file (`pyproject.toml`, `requirements.txt`,
  `requirements-langgraph.txt`) MAY carry a `python_version` /
  `python_full_version` marker whose sole purpose is forking behavior between
  3.9 and 3.10 (a marker forking on a *later* boundary, e.g. 3.11 vs 3.12, is
  unaffected and MAY remain).
- R-PF-3: `requirements-lock.txt` MUST be regenerated with
  `uv pip compile --universal --generate-hashes --python-version 3.10 -o requirements-lock.txt requirements-dev.txt requirements-langgraph.txt`,
  verified by the lock's own header comment.
- R-PF-4: `.github/workflows/python-package.yml`'s `build` matrix MUST drop
  the `3.9` leg and MUST NOT set `MANGO_CI_DESELECT_LANGGRAPH` on any leg,
  since every remaining leg satisfies langgraph's own floor
  (`harness/shared/tests/test_workflow_contracts.py::TestNoLegDeselectsLangGraph`).
  The `audit` job's 3.9 `continue-on-error` carve-out MUST be removed in the
  same change.
- R-PF-5: `.github/rulesets/main.json`'s `required_status_checks` MUST NOT
  name `build (3.9)` or `dependency-audit (3.9)`.
- R-PF-6: `harness/shared/check_py_compat.py`'s PEP 604 minimum-version
  check and its docstring MUST be updated to state that the check is
  currently inert at the 3.10 floor, rather than silently left describing
  3.9 behavior that no longer exists.
- C-PF-1: No requirement above may re-home the 3.9 carve-out to a different
  guard (e.g. moving the deselect logic to a *different* env var still keyed
  off a 3.9-shaped condition) — every carve-out this spec names must be
  deleted, not relocated (carries `reflection-hardening-increment.md`
  C-RHI-1).
- C-PF-2: `DEC-028` MUST be marked `superseded` by the new decision entry
  this spec's implementation records, per this document's own precondition.

## Acceptance criteria

- [x] AC-1: `python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['requires-python'])"`
      prints `>=3.10` · stage: `make ci` (R-PF-1)
- [x] AC-2: `git grep -n 'python_version.*3\.10\|python_full_version.*3\.10' pyproject.toml requirements.txt requirements-langgraph.txt`
      returns nothing (today, before this change: three forked markers) ·
      stage: `make ci` (R-PF-2)
- [x] AC-3: `head -2 requirements-lock.txt` names `--python-version 3.10` ·
      stage: `make lock-check` (R-PF-3)
- [x] AC-4 (rejection case): `pytest harness/shared/tests/test_workflow_contracts.py -k TestNoLegDeselectsLangGraph`
      fails if `MANGO_CI_DESELECT_LANGGRAPH` is (re)introduced as an actual
      env assignment on the `build` or `build-full` job, and passes on the
      tree as shipped · stage: `make test-python` (R-PF-4)
- [x] AC-5: `python3 -c "import json; ck=json.load(open('.github/rulesets/main.json'))['rules'][0]['parameters']['required_status_checks']; names=[c['context'] for c in ck]; assert 'build (3.9)' not in names and 'dependency-audit (3.9)' not in names"`
      exits 0 · stage: `make ci` (R-PF-5)
- [x] AC-6: `docs/decisions/DEC-028.md` frontmatter reads
      `status: superseded`, `superseded_by: "DEC-060"` · stage: `make specs`
      (C-PF-2)
- [x] AC-7: `python3 harness/shared/check_py_compat.py --json` exits 0 and
      reports `"min_version": "3.10"` derived from the matrix (not a
      hard-coded 3.9); no code change to the check itself was required
      beyond removing a now-unused `# type: ignore` — its `PEP604_MIN =
      (3, 10)` constant already only flags a construct when the *resolved
      matrix minimum* is older than that, so raising the matrix floor to
      exactly 3.10 makes the pep604 branch permanently inert without any
      edit, which is the derivation-not-hardcoding property R-PF-6 requires
      · stage: `make ci` (R-PF-6). No requirement in this document re-homes
      a carve-out to a different guard — each one named in the Problem
      statement is deleted outright by AC-1/AC-2/AC-3/AC-4/AC-5, not moved
      (C-PF-1, `reflection-hardening-increment.md` C-RHI-1).

## Steps

1. Bump `pyproject.toml`'s `requires-python`, drop the three forked markers —
   produces a 3.10-only dependency graph; consumes nothing.
2. Regenerate `requirements-lock.txt` at `--python-version 3.10` — consumes
   step 1's `pyproject.toml`/`requirements*.txt`.
3. Drop the 3.9 leg from `.github/workflows/python-package.yml` and
   `.github/rulesets/main.json`; remove `MANGO_CI_DESELECT_LANGGRAPH`'s
   3.9-keyed assignment and the audit job's `continue-on-error` — consumes
   step 2's lock file (the workflow installs from it).
4. Update `check_py_compat.py`'s docstring/check to reflect the new floor;
   record `DEC-060` superseding `DEC-028` — consumes nothing new.

## Files touched

- `pyproject.toml` (P), `requirements.txt` (P), `requirements-langgraph.txt`
  (P), `requirements-dev.txt` (P), `requirements-lock.txt`,
  `.github/workflows/python-package.yml` (P), `.github/rulesets/main.json`,
  `harness/shared/check_py_compat.py` (P), `docs/decisions/DEC-060.md` (new),
  `docs/decisions/DEC-028.md`, `docs/decisions/index.json`,
  `docs/decisions/index.md`, `harness/node/.governance/decision-log.md`,
  `harness/shared/tests/_workflow_paths.py`,
  `harness/shared/tests/test_workflow_contracts.py`,
  `harness/shared/tests/test_dependency_lock_contracts.py`, `NEXT_STEPS.md`.

## Invariants touched

- INV-2 (no unwaived skip): the 3.9 leg was the one place a skip-shaped
  deselect existed by design; removing the leg removes the carve-out rather
  than widening it. `verify-zero-skips-python` still runs clean once the
  leg is gone, since no leg deselects `langgraph` any more.

## Validation matrix

- `make ci` — ruff + mypy (`warn_unused_ignores = true`, 2.x release) +
  pytest + coverage (≥ `governance-policy.json → coverage.lines`) +
  check-dedup + validate_invariants, run on 3.10/3.12/3.14.
- `make lock-check` — `requirements-lock.txt` hashes match
  `requirements-dev.txt` + `requirements-langgraph.txt` under `uv pip compile
  --python-version 3.10`.

## Backward compatibility

Breaking for any adopter fork still running CPython 3.9: the published
package's `requires-python` now rejects that interpreter at install time
(`pip install` fails closed with a clear version error, rather than
installing and failing at import time). No runtime behavior changes for
3.10+ callers. `DEC-060` records the rationale and the superseded `DEC-028`
entry for anyone auditing why the floor moved.

## Open questions

None outstanding — `DEC-060` resolves the precondition this spec exists to
satisfy before `reflection-hardening-increment.md` Step 2 (the workflow/lock/
ruleset bump) can land.
