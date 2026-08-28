# Spec: gate-reach

> PR B of the v3 remediation program; **requires the `infra-reviewed` label**.
> It edits `pyproject.toml`, `Makefile`, `.github/workflows/python-package.yml`,
> `harness/CONTRACT.md`, `harness/shared/validate_adoption.py` and three other
> protected validators. Per-file attestation is in the PR description per
> `harness/CONTRACT.md`.

## Problem statement

Declared configuration and enforced configuration had drifted, in both
directions, and nothing in CI could see it. Measured on `main` before this
change:

1. **`validate_adoption.py` ran its whole gate at import** — 45 lines of
   module-level code that read files, printed, and raised `SystemExit`.
   `SystemExit` is a `BaseException`, so a shim guarding delegation with
   `except ImportError` cannot catch one. Two sibling control-plane CLIs were
   made importable by hand in an earlier PR of this programme; this one
   survived because **fixing instances is not a rule**.
2. **Bare `pytest` failed.** `addopts` lacked `-m "not live"` and
   `TestLiveOrchestrator` carried `@pytest.mark.live` without the `skipif` its
   sibling in `test_mango_mas_live.py` has, so the documented entry point
   disagreed with `make test-python` and died on
   "NVIDIA_API_KEY is not configured".
3. **Three `per-file-ignores` patterns suppressed nothing at all** —
   including `scratch/*.py`, for a gitignored directory that does not exist —
   plus a dozen unused codes inside otherwise-live patterns. Ruff has no
   unused-ignore check for config-level ignores, so this only ever grew.
   (The earlier audit put the figure at five dead patterns; measured with
   `ruff --isolated`, the correct number is three — a normal run applies the
   very ignores under test and reports all eleven as dead.)
4. **20 `noqa` directives were inert**, 13 of them the `BLE001` comments
   documenting deliberate fail-closed boundaries. The reasoning existed; the
   enforcement did not.
5. **`make review` named two of the three review skills** CLAUDE.md calls
   non-negotiable, so following the printed checklist skipped a mandated step.
6. **The Node install was duplicated inline** in the workflow rather than
   sharing a Make target with local runs and the session hook.
7. **`--check-untyped-defs` was off**, hiding 14 real findings — including
   seven `re.search(...).group()` calls that would raise `AttributeError`
   instead of failing with a message if their pattern ever stopped matching.

## Requirements

- R-GR-1: `validate_adoption.py` MUST perform no work at import: all logic
  under `main(root)` behind a `__main__` guard, preserving the per-stack
  `runpy` shims' exact CLI, exit codes and stdout.
- R-GR-2: `test_import_purity.py` MUST assert, per module under
  `harness/shared` and `harness/control-plane`, that importing it from a
  working directory that is not the repo root exits 0, prints nothing, and
  writes nothing. Modules still acting at import MUST be declared with a
  reason, and the declaration MUST self-destruct once the module is fixed.
- R-GR-3: Bare `pytest` MUST pass. `addopts` MUST deselect `live`, **and**
  every `live`-marked suite MUST also carry `skipif`, so neither mechanism is
  a single point of failure.
- R-GR-4: The regression tier MUST have a dedicated entry point
  (`make test-regression`) and MUST remain reachable from `make ci`, pinned by
  a test rather than by convention.
- R-GR-5: Node dependencies MUST install through one shared target
  (`make node-deps`, `--frozen-lockfile`) used by CI and by local runs.
- R-GR-6: Lint expansion MUST be measured, not speculative: every rule enabled
  after running it against the tree, every rule declined recorded with its
  finding count and reason in `test_deferred_rigor.py`.
- R-GR-7: Every `per-file-ignores` pattern MUST still match a file and every
  code in it MUST still suppress a real finding, verified with an isolated
  ruff run.
- R-GR-8: Every literal path in `.gitleaks.toml`'s allowlist MUST still exist.
- R-GR-9: `make review` MUST name all three skills CLAUDE.md mandates.
- R-GR-10: A prerequisite-set test MUST pin that `ci` and `ci-python` differ
  only by the Node gates, activating when `ci-python` arrives.
- C-GR-1: `make ci`'s prerequisite list is unchanged; every addition is a new
  target or a new workflow step, so INV-5 holds.
- C-GR-2: No behaviour change to any gate's stdout contract.

## Acceptance criteria

- [x] AC-1: `ALLOW_GITHUB_CHANGES=1 make ci` passes end to end.
- [x] AC-2: Bare `python -m pytest` passes — 1021 tests, was 2 failures.
- [x] AC-3: `test_import_purity.py` proves purity for every non-declared
  module, and fails when `validate_adoption.py` is reverted (verified).
- [x] AC-4: `test_lint_config_liveness.py` fails when a dead pattern is
  reintroduced (verified with a temporary `scratch/*.py` entry).
- [x] AC-5: `test_deferred_rigor.py` fails when a deferred rule is enabled
  (verified by temporarily selecting `ARG` and `DTZ`).
- [x] AC-6: `ruff check .` clean with the expanded set; `mypy
  --check-untyped-defs` clean; `check_py_compat` passes for 3.9.
- [x] AC-7: `make test-regression` and `make node-deps` both run green.

## Invariants touched

- INV-1: untouched — the secrets job is unchanged.
- INV-2: untouched — no skip is added. `addopts` changes *selection*, not
  skipping; the live suites remain runnable with `pytest -m live`.
- INV-5: preserved and strengthened — `ci`'s prerequisite list is byte-identical;
  the new targets are additive and `test_makefile_contracts.py` pins that the
  regression tier stays reachable from `ci`.
- INV-6: engaged — nine protected files are modified, each attested in the PR.

## Validation matrix

- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — full CI + review checklist + cold typecheck
- `make test-regression` — the tier on its own
- Negative probes: revert `validate_adoption.py`; add a `scratch/*.py` ignore;
  select a deferred rule. Each must fail its gate.

## Backward compatibility

- `validate_adoption.py`'s CLI is unchanged: same flags, same exit codes, same
  stdout, same CWD-relative resolution. Verified through both the shared entry
  point and the per-stack shim.
- `addopts` gaining `-m "not live"` changes only the default selection. `pytest
  -m live` still runs them; `make test-python` already passed the same flag.
- Pruned `per-file-ignores` entries suppressed nothing, so nothing that passed
  before can fail now. The expanded rule set is clean at the time of the change.
- `MYPY_FLAGS` is `?=`, so a caller can override it without editing the Makefile.
- `make ci` behaves identically; `test-regression` and `node-deps` are additive.

## Open questions

None. Three decisions worth recording, all changed by measurement rather than
assumed from the plan:

1. **`RUF100` is enabled, which the plan had ruled out.** The plan's reasoning
   was that it would delete the documented `BLE001` justifications. Measured:
   with `BLE` selected those 13 directives become *used*, and `RUF100` drops
   from 20 findings to 7 genuinely dead ones. Enabled together, `RUF100`
   protects the justifications instead of threatening them.
2. **`--check-untyped-defs` is enabled, which the plan did not consider.** The
   plan proposed triaging `union-attr`/`arg-type` under `--strict`; measured,
   those are test-only, while `--check-untyped-defs` costs 14 fixes and buys a
   permanent gate over exactly that class of defect.
3. **`TRY400` is declined**, though the plan listed it for enabling. All 11
   sites are `[FAIL] <verdict>` lines for expected validation failures inside
   except clauses that already name narrow types; `logging.exception` would
   replace a one-line operator-facing verdict with a redundant traceback and
   fight `test_gate_logging.py`'s stdout pins.
