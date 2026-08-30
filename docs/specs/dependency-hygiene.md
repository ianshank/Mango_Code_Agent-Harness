# Spec: dependency-hygiene

> Tech-debt reduction program, paired with `docs/specs/ci-enforcement-gaps.md`.
> Requires the `infra-reviewed` label: it edits `Makefile`, `pyproject.toml`,
> `requirements-dev.txt`, `.github/workflows/python-package.yml`,
> `harness/shared/governance-policy.json`, `harness/shared/governance/broker.py`,
> and `harness/shared/check_dedup.py` — all protected paths. Every protected
> file touched is attested in the PR description per `harness/CONTRACT.md`.

## Problem statement

No dependency-vulnerability scanning exists anywhere in the root pipeline —
`audit` is a `KNOWN_GAPS` exception in `test_ci_gate_coverage.py` — and no
Dependabot config exists at all. Separately, `pyproject.toml` declares no
`[project.dependencies]`, so `pip install -e .` (used in CI) installs no
runtime dependencies of its own; the API server's real runtime deps
(fastapi, uvicorn, pydantic, httpx) live only inside `requirements-dev.txt`,
indistinguishable from dev tooling like ruff and mypy. Separately again, 5
independent "load governance JSON, fail closed" implementations exist across
`policy_loader.py`, `coverage_gate.py`, `governance/broker.py`,
`validate_invariants.py`, and `check_dedup.py` — though
`docs/specs/policy-single-source.md` already made a deliberate decision to
keep `validate_invariants.py` (and the runpy-invoked per-stack scanners)
standalone-stdlib, so this spec narrows consolidation to the two files where
that decision does not apply and no test individually pins more than a
substring of the failure message.

## Requirements

- R-DH-1: A root `make audit` target MUST scan Python runtime dependencies
  (`pip-audit` against `requirements.txt`) and delegate to the Node stack's
  existing `osv-scanner`-based `audit` target.
- R-DH-2: `audit` MUST be enforced by a dedicated CI job (mirroring
  `secrets`), because `pre-pr` alone is a local-only convenience the GitHub
  workflow never invokes.
- R-DH-3: Runtime dependencies (fastapi, uvicorn, pydantic, httpx) MUST be
  declared in a dedicated `requirements.txt` and in `pyproject.toml`'s
  `[project.dependencies]`, separate from dev/tooling dependencies in
  `requirements-dev.txt`.
- R-DH-4: `.github/dependabot.yml` MUST cover the `pip` and `npm` ecosystems.
- R-DH-5: `governance/broker.py`'s and `check_dedup.py`'s JSON-parsing MUST
  share one non-raising classification primitive
  (`harness/shared/governance_json.py`), while each MUST keep raising its own
  existing exception type and log message on failure.
- C-DH-1: `policy_loader.py`, `coverage_gate.py`, and `validate_invariants.py`
  MUST NOT be changed to use the new primitive. `policy-single-source.md`
  already decided `validate_invariants.py` (and the runpy-invoked per-stack
  scanners) stay standalone-stdlib; reproducing `coverage_gate.py`'s and
  `policy_loader.py`'s many individually-pinned exception messages safely is
  out of scope here.
- C-DH-2: `requirements-dev.txt` MUST continue to install every dependency it
  does today via a single `pip install -r requirements-dev.txt` — no change
  to that CI step.

## Acceptance criteria

- [ ] AC-1: `audit` appears in `GATE_TO_ROOT_TARGET`, not `KNOWN_GAPS`, in
      `test_ci_gate_coverage.py` — verified by
      `pytest harness/shared/tests/test_ci_gate_coverage.py` (R-DH-1, R-DH-2)
- [ ] AC-2: a dedicated `audit` job in `.github/workflows/python-package.yml`
      runs `make audit` with no `if:` conditional — verified by
      `grep -A30 "^  audit:" .github/workflows/python-package.yml | grep "make audit"`
      (R-DH-2)
- [ ] AC-3: `pyproject.toml`'s `[project.dependencies]` and `requirements.txt`
      both list `fastapi`, `uvicorn`, `pydantic`, and `httpx` — verified by
      `grep -c fastapi pyproject.toml requirements.txt` reporting at least 1
      for each file (R-DH-3)
- [ ] AC-4: `.github/dependabot.yml` declares both a `pip` and an `npm`
      `package-ecosystem` entry — verified by
      `grep -c 'package-ecosystem: "pip"' .github/dependabot.yml` and
      `grep -c 'package-ecosystem: "npm"' .github/dependabot.yml`, each
      reporting 1 (R-DH-4)
- [ ] AC-5: `test_check_dedup.py` and `test_governance_broker.py` pass
      unchanged — verified by
      `pytest harness/shared/tests/test_check_dedup.py harness/shared/tests/test_governance_broker.py`
      (R-DH-5)
- [ ] AC-6: `policy_loader.py`, `coverage_gate.py`, and `validate_invariants.py`
      import nothing from `governance_json` — verified by
      `grep -rl governance_json harness/shared/policy_loader.py harness/shared/coverage_gate.py harness/shared/validate_invariants.py`
      returning no output (C-DH-1); this is the rejection case: the shared
      primitive must not spread to the three files this spec deliberately
      excludes
- [ ] AC-7: `requirements-dev.txt` still starts with `-r requirements.txt`,
      so `pip install -r requirements-dev.txt` continues installing both the
      runtime and dev/tooling sets in one step — verified by
      `grep -c "^-r requirements.txt$" requirements-dev.txt` reporting 1, and
      by every existing CI job (`build`, `build-full`), which already runs
      exactly this install command unmodified (C-DH-2)

## Steps

1. Add `harness/shared/governance_json.py` (the shared non-raising primitive)
   — produces the module
2. Refactor `governance/broker.py`'s and `check_dedup.py`'s JSON loading to
   use it — consumes the module, preserves each file's existing exception
   type and log message
3. Split `requirements.txt` out of `requirements-dev.txt`; add
   `[project.dependencies]` to `pyproject.toml`; add `requirements.txt` to
   `protected_paths` — produces `requirements.txt`
4. Add the root `audit`/`audit-install` Makefile targets; wire `audit` into
   `pre-pr` — consumes `requirements.txt`
5. Add the dedicated `audit` CI job to `python-package.yml` — consumes the
   root `audit` target
6. Update `test_ci_gate_coverage.py` (remove the `KNOWN_GAPS["audit"]` entry,
   add `audit` to `GATE_TO_ROOT_TARGET`/`GATE_TO_EVIDENCE`) and
   `test_makefile_contracts.py` (`pre-pr`'s exact prerequisite list)
7. Add `.github/dependabot.yml`

## Files touched

- `harness/shared/governance_json.py` (new; protected:
  `harness/shared/governance_json.py`)
- `harness/shared/governance/broker.py` (protected:
  `harness/shared/governance/**`)
- `harness/shared/check_dedup.py` (protected)
- `requirements.txt` (new; protected: `requirements.txt`)
- `requirements-dev.txt` (protected)
- `pyproject.toml` (protected)
- `harness/shared/governance-policy.json` (protected)
- `Makefile` (protected)
- `.github/workflows/python-package.yml` (protected:
  `.github/workflows/**`)
- `.github/dependabot.yml` (new)
- `harness/shared/tests/test_ci_gate_coverage.py` (protected)
- `harness/shared/tests/test_makefile_contracts.py`

## Invariants touched

- INV-5: closes the `audit` `KNOWN_GAPS` exception — "CI invokes every
  policy-required gate by Make target" now covers `audit`, mapped like
  `secrets` via a dedicated workflow job rather than a `ci`/`ci-python`
  prerequisite.
- INV-6: all protected-path edits ride the `infra-reviewed` attestation, per
  the decision-log entry this PR adds.

## Validation matrix

- `make audit` — pip-audit against `requirements.txt`, delegated Node
  osv-scanner; must fail closed if either tool or its input file is missing
- `make ci` and `make ci-python` — unaffected by this spec (`audit` stays out
  of both, by design, mirroring `secrets`)
- `make pre-pr` — now includes `audit`
- `pytest harness/shared/tests/test_ci_gate_coverage.py harness/shared/tests/test_makefile_contracts.py harness/shared/tests/test_check_dedup.py harness/shared/tests/test_governance_broker.py`
- coverage target: 90% lines / 80% branches from
  `governance-policy.json → coverage.{lines,branches}`, including the new
  `governance_json.py` module

## Backward compatibility

`pip install -r requirements-dev.txt` installs the exact same package set as
before (now via a `-r requirements.txt` include), so no existing CI or local
workflow step changes. `broker.py`'s `_load_json` exception type was
previously undocumented and untested, and is caught broadly
(`except Exception`) by its only caller, so this is not a breaking change for
that module. `check_dedup.py`'s `load_config` keeps its exact `SystemExit(1)`
exit code and "Malformed governance policy" / "Could not read governance
policy" log substrings.

## Open questions

None. The narrower consolidation scope (excluding `policy_loader.py`,
`coverage_gate.py`, `validate_invariants.py`) was itself the resolution of an
open question raised during review; see this PR's description for the full
reasoning and the decision-log entry it cites.
