# Agent operating instructions — Mango Code Agent Harness

These rules govern every AI agent operating in this repository. They are the
wiring for the planner → reasoner → verifier loop and the gates that make its
output trustworthy. Mechanical enforcement lives in the root `Makefile` and
`harness/shared/validate_invariants.py`; this file declares the workflow.

## The loop

1. **planner** (`.mango/agents/planner.md`) — produces a plan + acceptance
   criteria from a spec or brief. Plans and delegates only; never edits code.
2. **nemotron-reasoner** (`.mango/agents/nemotron-reasoner.md`) — executes the
   plan with the tool bridge. Uses `knowledge_gap_log` / `hypothesis_register`
   (wired via `META_TOOLS_SCHEMA` in `mango_mas_orchestrator.py`) instead of
   hallucinating when blocked or uncertain.
3. **verifier** (`.mango/agents/verifier.md`) — executes the validation matrix
   and reports PASS/FAIL against the acceptance criteria. Never marks PASS on
   inspection alone.

Role contracts and the authoritative 3-active → 7-canonical mapping live in
`.mango/agents/README.md` and `harness/shared/agents/`.

## Spec-driven workflow (non-trivial changes)

```bash
make spec NAME=<feature>     # scaffold docs/specs/<feature>.md
# fill the required sections (problem, acceptance criteria, invariants, matrix)
# peer-review the spec with the openspec-peer-review skill
# implement
make pre-pr                  # full CI + mechanical review checklist
```

A spec is the contract the verifier checks against. For non-trivial changes,
do not implement without one.

## Mandatory pre-PR review

Before opening a PR, run `make pre-pr` AND complete the review checklist it
prints:

1. **Mechanical invariants** — `make pre-pr` runs `make ci` (ruff, mypy, pytest,
   coverage ≥ policy threshold, check-dedup, validate_invariants). This is
   non-negotiable and fails closed.
2. **`openspec-peer-review` skill** — independent review from Architecture,
   SDLC, QA, and Product perspectives. Required for spec-driven work and any
   change touching core models, the orchestrator, or agent personas.
3. **`repo-invariant-review` skill** — predicts concrete CI failures (protected
   paths, size budget, architectural drift) before they fail in CI.
4. **`validation-runner` skill** — the single entry point for the full
   validation matrix when you need a structured PASS/FAIL with evidence.

For protected-path infrastructure changes, run with `ALLOW_GITHUB_CHANGES=1`
and record the per-change review attestation in the PR description (see
`harness/CONTRACT.md`).

**A verification claim is not evidence.** A commit message or PR body saying
"`make ci` passed" proves nothing; the check runs on the pushed head do. PR #60
merged with every CI run on its head red under a merge commit claiming `make ci`
and mypy clean (DEC-024). Paste the `make ci` and `make lint-cold` tails into
the PR's Validation section and link the `secret-scan` and `dependency-audit`
job runs; a reviewer who cannot see the output treats the claim as absent. The
ruleset exported at `.github/rulesets/main.json` makes the nine checks listed
in `NEXT_STEPS.md` required on `main`. Invoke pinned tools through the
interpreter (`python -m ruff`, `python -m mypy`) or the `make` targets, never a
bare binary on `PATH` (DEC-013).

## Non-negotiables

- No hard-coded values; thresholds come from `governance-policy.json`.
- No test waivers or `xfail` to make a gate green without a decision-log entry.
- No credentials in code; external model calls route through env vars.
- Backward-compatible, modular, reusable changes only.
- A verification claim in prose is not evidence; only the check runs on the
  pushed head are.
