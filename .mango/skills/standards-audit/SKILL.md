---
name: standards-audit
Reviewed: 2026-09-04
description: >
  Answer "does this repository meet current best practice?" with executed
  evidence rather than opinion: run every repo-defined gate on the head under
  audit, fan out six independent review lenses, cross-check anything the tree
  cannot prove about itself against the GitHub API, then subject the draft to
  an adversarial falsification pass that executes every Blocker and High
  finding before the report is published. Use for a periodic external-standards
  audit (yearly, or when the language/CI baseline moves), not for per-PR review.
  Composes tech-debt-audit, validation-runner and gate-mutation-proof; adds the
  external baseline and the falsification pass neither has.
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# standards-audit — an audit is a claim until something tries to break it

## Why this exists

The first run of this procedure (2026-09-04, `docs/reports/2026-STANDARDS-AUDIT.md`)
found that the revision-1 report was wrong in ways only execution catches: it
called a runtime bypass "High" when running it through the real dispatcher,
broker and backend showed it forges the harness verdict (promoted to a Blocker);
it said the secret scan covered "full history" when the recipe scopes to
`--log-opts="HEAD"`; four of its counts were off; and one `[Likely]` fix
turned out to be provable in two runs. None of that was visible from reading.
The procedure below is what produced the corrections, written down so the next
audit starts from it instead of re-deriving it.

## Relationship to other skills — compose, do not re-declare

| Already covers | Skill | What this skill adds |
|---|---|---|
| Drift vs `main`, god-file watch list, hard-coded values, dead code, doc sync | `tech-debt-audit` | An *external* baseline (what 2026 norms are, with sources) and a verdict against it |
| The deterministic gate matrix with a PASS/FAIL verdict | `validation-runner` | Nothing — run it first, paste its tails into the report (§2 of the report shape) |
| Proving a gate can fail | `gate-mutation-proof` | The same idea applied to the *audit's own findings* (step 5) |
| Predicting which CI gate a change collides with | `repo-invariant-review` | Nothing — run it on any remediation the audit proposes |
| Four-persona review of a proposed plan | `openspec-peer-review` | Step 6 applies it to the remediation plan the audit produces |

## Procedure

1. **Execute the gates on the audited head, in a clean environment.** A venv built
   from the hashed lock (`--require-hashes -r requirements-lock.txt`, then
   `-e . --no-deps`), never the session interpreter. Run every `make` target
   `make pre-pr` chains, individually, and record each tail verbatim. A gate that
   fails because the runner is mis-set-up is itself a finding (the first run found
   two: `secrets-install` off `PATH`, and the session hook installing unhashed).
2. **Fan out six lenses in parallel, read-only.** Python tooling and typing;
   security and supply chain (OpenSSF Scorecard, SLSA, OWASP LLM/Agentic);
   testing rigor; architecture and agent design; developer experience, docs and
   the non-primary stacks; and an *external baseline* lens that pins what "current
   best practice" means with dated sources (EOL calendars, current tool majors,
   spec revisions). Every finding carries `file:line`, a 2026-norm column, a
   recommended fix and a confidence tag (`[Certain]` executed or read directly,
   `[Likely]` inferred, `[Guessing]` gap-fill).
3. **Cross-check the tree's claims about GitHub against GitHub.** Branch
   protection (`/branches/{b}` *and* `/rules/branches/{b}` — the first reflects
   only legacy protection), approving reviews on merged PRs, check conclusions on
   the merge head, open bot PRs, tags. A roadmap that says "re-checked" is a
   claim; the API response is the evidence.
4. **Consolidate into one report** with the shape of
   `docs/reports/2026-STANDARDS-AUDIT.md`: verdict with the deciding facts,
   scorecard by dimension, gate evidence, ranked findings (Blocker/High/Medium/
   Low), what is above the bar and must not regress, the remediation pointer, the
   baseline used, and a revision record.
5. **Falsify the draft before publishing.** A separate reviewer with no part in
   writing it executes every Blocker and High and the first dozen Mediums: build
   the failing input, run the real code path end to end in a scratch workspace,
   time the thing the finding times, re-count the thing it counts. Each row
   returns HOLDS / OVERSTATED / WRONG / ALREADY FIXED / COULD NOT TEST with the
   command run. Corrections go into the report's revision record, never silently
   into the text.
6. **Peer-review the existing plans against the audit, then rewrite them.** Ledger
   every open plan requirement (claimed vs actual, with the command that proves
   it); map every audit finding to a plan owner or to "unowned"; run the ticked
   acceptance criteria through `test_spec_selectors_collect.py`'s matcher (a
   ticked criterion whose selector collects nothing is a false claim). Close
   plans that are mostly landed rather than revising them; write one superseding
   program spec that owns every unowned finding; point the roadmap at it.

## Failure modes this procedure has already hit

- **Reading instead of running.** Revision 1 graded the script-execution bypass
  from the classifier table alone. Running it showed the verdict forgery. Step 5
  exists because of this.
- **Trusting a recipe's name.** `make secrets` reads as "scan secrets"; the
  recipe's `--log-opts="HEAD"` makes it "scan this ancestry". Read the recipe.
- **A count from the wrong tool version.** `warn_unused_ignores` was measured
  with a newer mypy than the pin; the pinned one reports fewer. Measure with the
  pinned tool, through `python -m`.
- **A selector that cannot fail.** Seven ticked criteria across three specs
  cited `-k` expressions collecting zero tests. The static matcher in
  `harness/shared/tests/test_spec_selectors_collect.py` now gates this on every PR.
- **A fourth owner.** The audit's first draft ended in a numbered roadmap while
  the repo already had a program spec and `NEXT_STEPS.md`. Three lists of the
  same work drift three ways; the report must *point*, not own.

## Outputs

- `docs/reports/<year>-STANDARDS-AUDIT.md` (revision ≥ 2, with the revision record).
- A superseding program spec under `docs/specs/` that passes `make specs`.
- `NEXT_STEPS.md` rewritten to point at that spec and carry only decision-blocked
  and agent-executable items with four fields each.
- Corrections to any closed plan whose ticked criteria were vacuous.
