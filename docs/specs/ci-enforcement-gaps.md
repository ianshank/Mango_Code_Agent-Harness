# Spec: ci-enforcement-gaps

> Tech-debt reduction program, paired with `docs/specs/dependency-hygiene.md`.
> Requires the `infra-reviewed` label: it edits `Makefile` and `harness/CONTRACT.md`,
> both protected paths. Every protected file touched is attested in the PR
> description per `harness/CONTRACT.md`.

## Problem statement

Several things look enforced or documented but are not, found by a direct
tech-debt audit rather than a failing test:

- `ruff check .` currently reports 3 findings (2 unused `# noqa: E402` in
  `harness/api_server/tests/test_main.py`, 1 missing `# noqa: BLE001` in
  `harness/shared/write_policy.py`) — `make lint` is not actually clean today,
  contradicting a several-days-stale hygiene report that claimed 0 findings.
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

**Deliberately not fixed here**: `make lint-node` (ESLint/Prettier/Knip)
exists but neither `lint` nor `ci`/`ci-python` ever calls it, so Node lint
enforces nothing in CI — the original intent was to close that gap in this
spec. Pre-implementation verification found `make lint-node` currently
**crashes** (`typescript-eslint does not support TS 7.0`, a `typescript`
7.0.2 / `typescript-eslint` 8.67.0 incompatibility pinned in
`harness/node/package.json`), unrelated to anything else in this PR — no
Node source or config file is touched here. Wiring a currently-broken gate
into `ci` would turn CI red on the next PR for a reason this PR did not
cause and does not fix. See Open questions.

## Requirements

- R-CEG-1: `make lint` MUST exit 0 against the current tree.
- R-CEG-2: The version string in `README.md`, `docs/architecture/c4_architecture.md`,
  and `NEXT_STEPS.md` MUST match `pyproject.toml`'s `version`.
- R-CEG-3: `harness/node/.github/workflows/ci.yml` and `harness/jvm/.github/workflows/ci.yml`
  MUST each carry a header comment identifying them as a reference adoption
  template that GitHub never executes, pointing to the real root workflow.
- R-CEG-4: A root `install` target MUST install the pre-push remote-allowlist
  hook (`harness/shared/install_hooks.sh`).
- R-CEG-5: `harness/CONTRACT.md` MUST state that `harness/jvm/` is an unadopted
  reference template with no live CI enforcement, and MUST state that
  `harness/node/.governance/` is intentionally the repository's only live
  governance root of trust (per DEC-005), not a layout defect to fix.

## Acceptance criteria

- [ ] AC-1: `ruff check .` exits 0 — verified by `make lint` (R-CEG-1)
- [ ] AC-2: `README.md`, `docs/architecture/c4_architecture.md`, and
      `NEXT_STEPS.md` each contain `2.1.9` and none contains `2.2.0` or
      `2.3.0` as a version string — verified by
      `grep -c 2.1.9 README.md docs/architecture/c4_architecture.md NEXT_STEPS.md`
      (R-CEG-2)
- [ ] AC-3: both per-stack `ci.yml` files contain the phrase "reference
      adoption template" in their header comment — verified by
      `grep -l "reference adoption template" harness/node/.github/workflows/ci.yml harness/jvm/.github/workflows/ci.yml`
      reporting both paths (R-CEG-3)
- [ ] AC-4: `make install` runs `install_hooks.sh` and exits 0 — verified by
      `make install` (R-CEG-4)
- [ ] AC-5: `harness/CONTRACT.md` contains "reference adoption template" and
      "DEC-005" — verified by
      `grep -c "reference adoption template" harness/CONTRACT.md` and
      `grep -c "DEC-005" harness/CONTRACT.md` (R-CEG-5)
- [ ] AC-6: `make lint-node`, run standalone, still fails today — verified by
      `make lint-node` exiting non-zero; this is the rejection case: it is
      the evidence that not wiring it into `ci` in this PR was the correct
      call, not an oversight

## Steps

1. Fix the 3 live ruff findings — produces a clean `ruff check .`
2. Unify the version string across the 3 drifted files — consumes
   `pyproject.toml`'s `version`
3. Header-comment the two dead per-stack workflow templates
4. Add the root `install` target
5. Document the JVM-template and `.governance/`-layout clarifications in
   `harness/CONTRACT.md`

## Files touched

- `harness/api_server/tests/test_main.py`
- `harness/shared/write_policy.py`
- `README.md`
- `docs/architecture/c4_architecture.md`
- `NEXT_STEPS.md`
- `Makefile` (protected: `Makefile`) — the root `install` target only; no
  change to `ci`/`ci-python`'s prerequisite lists survives in this spec
- `harness/node/.github/workflows/ci.yml`
- `harness/jvm/.github/workflows/ci.yml`
- `harness/CONTRACT.md` (protected: `harness/CONTRACT.md`)

## Invariants touched

- INV-2: unaffected — the JVM-template clarification documents the existing
  "not yet enforced" status in prose; it does not change what is enforced.
- INV-3: unaffected — the `.governance/` clarification documents the existing
  DEC-005 posture; it does not relocate or change what is enforced.
- INV-5: unaffected by this spec — closing the `lint-node` enforcement gap
  is deferred to the follow-up in Open questions, not delivered here.

## Validation matrix

- `make lint` — ruff, must exit 0
- `make install` — must exit 0 on a clean clone
- coverage target: 90% lines / 80% branches from
  `governance-policy.json → coverage.{lines,branches}` (unaffected by this
  spec's changes, which are Makefile/docs/workflow-comment only)

## Backward compatibility

Purely additive or corrective: no public API, tool schema, or CLI surface
changes. `ci` and `ci-python`'s prerequisite lists are byte-for-byte
unchanged by this spec.

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
