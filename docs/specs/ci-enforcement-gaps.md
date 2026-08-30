# Spec: ci-enforcement-gaps

> Tech-debt reduction program, paired with `docs/specs/dependency-hygiene.md`.
> Requires the `infra-reviewed` label: it edits `Makefile` and `harness/CONTRACT.md`,
> both protected paths. Every protected file touched is attested in the PR
> description per `harness/CONTRACT.md`.

## Problem statement

Several things look enforced or documented but are not, found by a direct
tech-debt audit rather than a failing test:

- `harness/node/.github/workflows/ci.yml` and `harness/jvm/.github/workflows/ci.yml`
  look like live secret-scan/lint coverage but GitHub only discovers workflows
  under the repository-root `.github/workflows/`, so neither ever runs.
- A clone that only ever uses the root `Makefile` never gets the pre-push
  remote-allowlist hook installed — there is no root `install` target, only
  per-stack ones.
- The project's own version string disagrees across three files:
  `pyproject.toml` (`2.1.9`), `README.md` (`2.2.0`), `docs/architecture/c4_architecture.md`
  (`2.3.0`), `NEXT_STEPS.md` (`2.2.0`).
- `harness/jvm/`'s Makefile implements the full per-stack target contract, but
  nothing in root CI ever invokes it, and neither `README.md` nor
  `harness/CONTRACT.md` says so plainly — a reader can mistake it for a live
  guarantee.
- `harness/__init__.py` and `harness/api_server/__init__.py` don't exist,
  even though both packages are genuinely imported as `harness.x.y`
  (`from harness.api_server.main import app`, etc.), unlike
  `harness/shared/__init__.py` which does. Both currently rely on PEP 420
  implicit namespace packages — inconsistent with the rest of the tree.

**Retracted mid-PR, self-correcting a false finding**: an initial research
pass reported 3 live `ruff` findings (2 unused `# noqa: E402` in
`harness/api_server/tests/test_main.py`, 1 missing `# noqa: BLE001` in
`harness/shared/write_policy.py`) and this spec originally "fixed" them.
Pushing that fix turned CI red with the *opposite* verdict on the same two
files. Root cause: this environment has a bare `ruff` on `PATH` resolving to
`0.15.8`, while `python -m ruff` — what `make lint`, every other `make`
target, and CI's `pip install -r requirements-dev.txt` all actually resolve
to — is the pinned `0.6.9`, and the two versions disagree on both rules for
this exact code shape. `main` was already clean under the pinned version;
neither file is touched by this spec. The same false signal briefly caused
`harness/__init__.py`/`harness/api_server/__init__.py` to be added, then
reverted (a "ruff reports an unrelated finding once these exist" symptom
that only reproduced under the wrong binary); re-tested under
`python -m ruff`, the two files produce zero findings and are restored — see
Requirements below. **Lesson for future verification in this repository**:
never trust a bare `ruff`/`mypy` invocation; always use `make <target>` or
`python -m ruff`/`python -m mypy` explicitly, since a shadowing binary on
`PATH` will silently diverge from the pinned, CI-matching version.

**Deliberately not fixed here**: `make lint-node` (ESLint/Prettier/Knip)
exists but neither `lint` nor `ci`/`ci-python` ever calls it, so Node lint
enforces nothing in CI — the original intent was to close that gap in this
spec. Pre-implementation verification found `make lint-node` currently
**crashes** (`typescript-eslint does not support TS 7.0`, a `typescript`
7.0.2 / `typescript-eslint` 8.67.0 incompatibility pinned in
`harness/node/package.json`) — a genuine, Node-toolchain-side finding,
independent of the Python tool-version issue above and unrelated to
anything else in this PR (no Node source or config file is touched here).
Wiring a currently-broken gate into `ci` would turn CI red on the next PR
for a reason this PR did not cause and does not fix. See Open questions.

**Found and fixed mid-PR, a second CI-red surprise**: `secret-scan` failed
on this PR's own CI despite a clean local `make secrets`. Root cause: all
three `secrets` targets (root, `harness/node`, `harness/jvm`) ran
`gitleaks git` with no `--log-opts`, which scans every ref present in the
local clone rather than the checked-out branch's own history. CI's fresh
`fetch-depth: 0` clone had a real leaked key on an unrelated, concurrently
pushed branch (`feature/governed-run-console`) that this PR's diff and
history never touch; a long-lived local development clone missing that
branch masked the same bug. Confirmed with a from-scratch clone:
`gitleaks git . --log-opts="HEAD"` scans 141 commits (the current ref's own
ancestry, clean) vs. 144 without it (every local ref, the unrelated leak).
Fixed by adding `--log-opts="HEAD"` to all three targets — see R-CEG-6.

## Requirements

- R-CEG-1: The version string in `README.md`, `docs/architecture/c4_architecture.md`,
  and `NEXT_STEPS.md` MUST match `pyproject.toml`'s `version`.
- R-CEG-2: `harness/node/.github/workflows/ci.yml` and `harness/jvm/.github/workflows/ci.yml`
  MUST each carry a header comment identifying them as a reference adoption
  template that GitHub never executes, pointing to the real root workflow.
- R-CEG-3: A root `install` target MUST install the pre-push remote-allowlist
  hook (`harness/shared/install_hooks.sh`).
- R-CEG-4: `harness/CONTRACT.md` MUST state that `harness/jvm/` is an unadopted
  reference template with no live CI enforcement, and MUST state that
  `harness/node/.governance/` is intentionally the repository's only live
  governance root of trust (per DEC-005), not a layout defect to fix.
- R-CEG-5: `harness/__init__.py` and `harness/api_server/__init__.py` MUST
  exist, mirroring `harness/shared/__init__.py`'s existing convention for a
  genuinely-imported package. `harness/control-plane/` MUST NOT gain one —
  its hyphenated name makes it non-importable by design (confirmed by
  `test_import_purity.py`/`test_build_policy_bundle.py`'s own docstrings),
  invoked by file path only.
- R-CEG-6: `make secrets`'s `gitleaks git` invocation, in all three Makefiles
  (root, `harness/node`, `harness/jvm`), MUST scope its history walk to the
  checked-out ref (`--log-opts="HEAD"`), not every local ref.
- C-CEG-1: `python -m ruff check .` (the pinned version) MUST exit 0 against
  the current tree, both before and after R-CEG-5's change.

## Acceptance criteria

- [ ] AC-1: `README.md`, `docs/architecture/c4_architecture.md`, and
      `NEXT_STEPS.md` each contain `2.1.9` and none contains `2.2.0` or
      `2.3.0` as a version string — verified by
      `grep -c 2.1.9 README.md docs/architecture/c4_architecture.md NEXT_STEPS.md`
      (R-CEG-1)
- [ ] AC-2: both per-stack `ci.yml` files contain the phrase "reference
      adoption template" in their header comment — verified by
      `grep -l "reference adoption template" harness/node/.github/workflows/ci.yml harness/jvm/.github/workflows/ci.yml`
      reporting both paths (R-CEG-2)
- [ ] AC-3: `make install` runs `install_hooks.sh` and exits 0 — verified by
      `make install` (R-CEG-3)
- [ ] AC-4: `harness/CONTRACT.md` contains "reference adoption template" and
      "DEC-005" — verified by
      `grep -c "reference adoption template" harness/CONTRACT.md` and
      `grep -c "DEC-005" harness/CONTRACT.md` (R-CEG-4)
- [ ] AC-5: `harness/__init__.py` and `harness/api_server/__init__.py` exist;
      `harness/control-plane/__init__.py` does not — verified by
      `test -f harness/__init__.py && test -f harness/api_server/__init__.py && test ! -f harness/control-plane/__init__.py`
      (R-CEG-5)
- [ ] AC-6: `python -m ruff check .` exits 0 with R-CEG-5's files present —
      verified directly, not via a bare `ruff` invocation (C-CEG-1); this is
      the rejection case this spec exists to re-establish: a bare `ruff`
      reporting a finding here is the wrong-binary failure mode this PR
      already hit once, not evidence the code is wrong
- [ ] AC-7: `pytest harness/shared/tests/test_import_purity.py harness/shared/tests/ -k "import_direction or check_dedup"`
      passes with R-CEG-5's files present — verified by
      `make coverage-python` (full suite; R-CEG-5's import-mode risk was
      already checked against the full 1990-test suite, not just these two
      files)
- [ ] AC-8: `make lint-node`, run standalone, still fails today — verified by
      `make lint-node` exiting non-zero; this is the rejection case: it is
      the evidence that not wiring it into `ci` in this PR was the correct
      call, not an oversight
- [ ] AC-9: all three `secrets` targets pass `--log-opts="HEAD"` to
      `gitleaks git` — verified by
      `grep -c 'log-opts="HEAD"' Makefile harness/node/Makefile harness/jvm/Makefile`
      reporting 1 for each file (R-CEG-6); the rejection case is a from-scratch
      clone that also fetches a branch carrying a real secret — `gitleaks git .
      --log-opts="HEAD"` must report only the checked-out ref's own commit
      count and find nothing, where the same command without `--log-opts`
      finds the unrelated branch's leak (reproduced during this PR's own CI
      failure, not re-testable in a single-branch CI checkout)

## Steps

1. Unify the version string across the 3 drifted files — consumes
   `pyproject.toml`'s `version`
2. Header-comment the two dead per-stack workflow templates
3. Add the root `install` target
4. Document the JVM-template and `.governance/`-layout clarifications in
   `harness/CONTRACT.md`
5. Add `harness/__init__.py` and `harness/api_server/__init__.py`; verify
   with `python -m ruff check .` (not bare `ruff`) and the full test suite
6. Add `--log-opts="HEAD"` to all three `secrets` targets — consumes the
   from-scratch-clone reproduction, produces a ref-scoped secret scan

## Files touched

- `README.md`
- `docs/architecture/c4_architecture.md`
- `NEXT_STEPS.md`
- `Makefile` (protected: `Makefile`) — the root `install` target, and
  `secrets`'s `--log-opts` fix; no change to `ci`/`ci-python`'s prerequisite
  lists survives in this spec
- `harness/node/Makefile` (protected: `harness/*/Makefile`) — `secrets`'s
  `--log-opts` fix only
- `harness/jvm/Makefile` (protected: `harness/*/Makefile`) — `secrets`'s
  `--log-opts` fix only
- `harness/node/.github/workflows/ci.yml`
- `harness/jvm/.github/workflows/ci.yml`
- `harness/CONTRACT.md` (protected: `harness/CONTRACT.md`)
- `harness/__init__.py` (new)
- `harness/api_server/__init__.py` (new)

## Invariants touched

- INV-1: strengthened — the secret scan now proves what its own gate can
  act on (the checked-out ref's history) instead of failing a PR for a
  secret on a branch neither that PR nor its author can fix from within it.
  "Fails closed" is unchanged: a scan that finds nothing on the wrong ref
  was never evidence of safety for the right one, since the ref-scoped
  history is always a subset re-included.
- INV-2: unaffected — the JVM-template clarification documents the existing
  "not yet enforced" status in prose; it does not change what is enforced.
- INV-3: unaffected — the `.governance/` clarification documents the existing
  DEC-005 posture; it does not relocate or change what is enforced.
- INV-5: unaffected by this spec — closing the `lint-node` enforcement gap
  is deferred to the follow-up in Open questions, not delivered here.

## Validation matrix

- `python -m ruff check .` — must exit 0 (never verified via bare `ruff`)
- `make install` — must exit 0 on a clean clone
- `make coverage-python` — full suite, proving R-CEG-5 doesn't regress
  import/collection behavior
- `make secrets` — must exit 0 against a from-scratch clone that also has
  an unrelated branch carrying a real secret present locally (the actual
  reproduction used during this PR); `pytest harness/shared/tests/test_ci_gate_coverage.py harness/shared/tests/test_lint_config_liveness.py`
  — confirms the `secrets` gate mapping and config-liveness checks still
  pass unchanged
- coverage target: 90% lines / 80% branches from
  `governance-policy.json → coverage.{lines,branches}`

## Backward compatibility

Purely additive or corrective: no public API, tool schema, or CLI surface
changes. `ci` and `ci-python`'s prerequisite lists are byte-for-byte
unchanged by this spec. `harness/__init__.py`/`harness/api_server/__init__.py`
convert two PEP 420 implicit namespace packages into regular packages;
`[tool.coverage.run] source=[...]` matches by file path and is unaffected
either way, and the full test suite (1990 tests) passes unchanged with them
present.

## Open questions

`harness/node/`'s `typescript` (`7.0.2`) / `typescript-eslint` (`8.67.0`)
version pin is incompatible, breaking `make lint-node` for reasons unrelated
to this PR. Resolving it (bump `typescript-eslint`, or pin `typescript` back
to a supported 6.x release, then re-verify the whole Node suite) and then
wiring `lint-node` into `ci` as its own direct prerequisite (never into the
shared `lint` target, since `ci-python`'s matrix legs install no pnpm) is
tracked as a follow-up, not resolved here. Also deliberately out of scope
and recorded as backlog rather than open questions: raising the Python 3.9
floor (past upstream EOL, but a compatibility-breaking decision needing its
own spec) and bringing `harness/jvm/` to real CI parity (a substantially
larger effort than labeling it as a template).
