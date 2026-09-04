# Contributing

This repository runs an unusually strict, evidence-driven contribution
process. This doc is the short version; `CLAUDE.md` and `harness/CONTRACT.md`
are the authoritative references — read those before a non-trivial change.

## Before you start

For anything beyond a small, obviously-safe fix, write a spec first:

```bash
make spec NAME=<feature>
```

This scaffolds `docs/specs/<feature>.md` from `docs/specs/SPEC_TEMPLATE.md` —
problem statement, requirements, acceptance criteria, invariants touched,
validation matrix, and backward compatibility. A spec is the contract the
verifier checks against; see any file under `docs/specs/` for examples of the
expected level of detail.

## Local setup

```bash
make install          # installs the pre-push remote-allowlist hook
pip install -r requirements-dev.txt
pip install -e .
```

## Before opening a PR

```bash
make pre-pr
```

`make pre-pr` is the bar. It runs `ci` (lint, coverage, tests, specs, remotes,
governance validators, drift checks), `review`, a cold mypy pass (`lint-cold`),
the dependency audit (`audit`) and the secret scan (`secrets`). `make review`
prints a checklist naming three skills worth running for non-trivial changes:
`openspec-peer-review`, `repo-invariant-review`, and `validation-runner`.

Two of those gates need Go binaries: `audit` uses `osv-scanner` and `secrets`
uses `gitleaks`, installed by `make audit-install` / `make secrets-install`
(`pip-audit` comes from pip). Where the Go toolchain is absent, the documented
fallback is to run `make ci` and `make lint-cold` locally and to link the
`dependency-audit` and `secret-scan` job runs on the pushed head in the PR's
Validation section — those jobs are the evidence for the two gates you could
not run. That is the one sanctioned substitute; a claim that the gates passed
without either the local output or the job link is treated as absent.

Python dependencies are pinned by one universal lock. If you change
`requirements.txt`, `requirements-dev.txt` or `requirements-langgraph.txt`, run
`make lock` and commit `requirements-lock.txt` in the same change — `make ci`
runs `lock-check`, which recompiles and fails on any difference. Do not hand-edit
the lock; `make lock-upgrade` (not `make lock`) is what takes newer releases, and
the weekly drift job opens an issue when the lock falls behind.

**A verification claim is not evidence.** Paste the tail of `make ci` and
`make lint-cold` (the pass/fail lines, not "all green") into the PR's
Validation section and link the `secret-scan` and `dependency-audit` job runs.
A reviewer who cannot see the output treats the claim as absent: this
repository once merged a PR whose every CI run was red under a commit message
claiming `make ci` and mypy clean (DEC-024). The ruleset exported at
`.github/rulesets/main.json` makes the required checks a merge requirement on
`main`, so the check runs on the pushed head are the record.

Always invoke the pinned tools through the interpreter (`python -m ruff`,
`python -m mypy`, or the `make` targets): a bare `ruff` on `PATH` can be a
different version that disagrees with CI on real code (DEC-013).

## Protected paths

Some files are gated (`Makefile`, `pyproject.toml`, `.github/workflows/**`,
the governance kernel, `.mango/`/`.claude/` agent config, `CLAUDE.md`,
`harness/CONTRACT.md`, and more — see `protected_paths` in
`harness/shared/governance-policy.json`). A PR touching any of these needs:

1. A per-file attestation table in the PR description under
   `## Protected-path attestation` (the `.github/PULL_REQUEST_TEMPLATE.md`
   scaffolds this; the `protected-path-attestation` skill generates it
   accurately from your actual diff).
2. The `infra-reviewed` label from a maintainer, which sets
   `ALLOW_GITHUB_CHANGES=1` in CI for that PR.

Applying the label without an honest attestation table defeats the invariant
it exists to enforce — don't do that to unblock a red check.

## Non-negotiables (from `CLAUDE.md`)

- No hard-coded values — thresholds come from `governance-policy.json`.
- No test waivers or `xfail` to make a gate green without a decision-log
  entry (`harness/node/.governance/decision-log.md`).
- No credentials in code; external model calls route through env vars.
- A gate, threshold-loader, or policy-derived default must fail **closed**
  (raise) on malformed input, never silently substitute a default — this
  repo's decision log documents this exact bug recurring multiple times, so
  it's checked deliberately, not assumed.

## Commit and PR conventions

- Keep PRs small and answerable to one question — this repo's own history
  (see the decision log) consistently splits work this way specifically so
  each `infra-reviewed` attestation is reviewable.
- Prefer a new commit over amending; never force-push over another
  contributor's branch.
- Don't skip hooks (`--no-verify`) or disable a check to get to green — fix
  the underlying issue, or record an explicit, reasoned exception the way
  `test_ci_gate_coverage.py`'s `KNOWN_GAPS`/`PARTIAL_COVERAGE` dictionaries do.

## Reporting a security issue

See [`SECURITY.md`](./SECURITY.md) — please don't open a public issue for a
suspected vulnerability.
