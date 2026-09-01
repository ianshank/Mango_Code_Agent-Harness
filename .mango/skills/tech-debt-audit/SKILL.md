---
name: tech-debt-audit
Reviewed: 2026-08-31
description: >
  Full-repo SDLC/SQE-style tech-debt audit: drift vs. main, code hygiene
  (god-file decomposition, hardcoded values, dead code, missed edge cases,
  reusable-code duplication), coverage-gate verification, doc/decision-log
  sync, and pre-PR validation. Use when asked for a broad "team of
  engineers and product managers" style review, or before a large batch of
  changes lands, instead of re-deriving the checklist ad hoc each time.
  Composes validation-runner and repo-invariant-review for the mechanical
  gates; this skill adds the parts neither one covers.
validator_version: '2.0'
compatibility: python>=3.10
version: 1.0.0
---

# tech-debt-audit — the recurring full-team review, made repeatable

This skill exists because of a concrete failure mode observed in practice: the same
broad "act as a team of SDLC engineers / SQE / architects, scan for gap analysis,
hygiene, coverage, hardcoded values, dead code, doc sync" request was sent three
times, verbatim, in one session. Redoing a multi-hour audit from scratch each time
either wastes the identical work already done, or — worse — invites skipping real
verification the second and third time because it "already happened." Neither is
acceptable. This is the procedure, run once and referenced every time instead.

## 1. Relationship to other skills — do not re-declare, compose

| Already covers | Skill | What this skill adds instead |
|---|---|---|
| The deterministic gate matrix (ruff, mypy, pytest, coverage, check-dedup, validate_invariants) with a PASS/FAIL verdict | `validation-runner` | Nothing — run it, don't reimplement it. |
| Predicting which CI gate a change will collide with (protected paths, size budget, coverage, secrets) | `repo-invariant-review` | Nothing — run it, don't reimplement it. |
| Multi-persona review of a *proposed plan* before implementation | `openspec-peer-review` | This skill reviews *landed or in-flight code*, not a proposal; run that one first if a plan doesn't exist yet. |
| The per-file attestation block a protected-path PR needs | `protected-path-attestation` | Nothing — run it if step 5 below touches a protected path. |

If you find yourself re-typing a coverage threshold, a protected-path list, or a
gate's exit criteria here, stop — read it live from `governance-policy.json` or the
Makefile instead. A restated number is a second copy that can drift from the first.

## 2. Preconditions

- Run from the repo root, on the branch under audit.
- `git fetch origin main` must succeed (network-dependent; report and continue with
  a stale-drift caveat if it fails rather than blocking the whole audit on it).

## 3. Procedure

### 3.1 Drift check against `main`

```bash
git fetch origin main
git log --oneline HEAD..origin/main   # commits on main not yet in this branch
git log --oneline origin/main..HEAD   # commits in this branch not yet on main
```

A non-empty first list means merge `main` in before auditing further — findings
against a stale base are not trustworthy. Report both lists in the final summary
regardless (see §4).

### 3.2 Mechanical gates

```bash
make pre-pr   # ci + review + lint-cold + audit + secrets, per CLAUDE.md
```

Delegate to `validation-runner` for the structured verdict and `repo-invariant-review`
for collision prediction. Do not hand-roll a subset of these checks — a partial
manual re-check is how a real regression gets missed while feeling thorough.

### 3.3 God-file decomposition scan

"God file" in this repo is not a subjective judgment call — the mechanical size
budget already defines it. Read the ceiling live, never restate it:

```bash
python -c "import json; print(json.load(open('harness/shared/governance-policy.json'))['limits']['size_budget_lines'])"
find harness .mango -name "*.py" -not -path "*/tests/*" -not -name "test_*" \
  | xargs wc -l | sort -rn | head -20
```

A file already over the ceiling is a `validate_invariants.py` failure, not an audit
finding — that gate would already be red. The audit-worthy signal is a file at
60%+ of the ceiling: flag it as a *watch item* (name, line count, % of ceiling), not
a mandatory decomposition — forcing a split before a file is actually a problem
trades a hypothetical readability gain for a real, immediate migration cost
(protected-path edits, `check_dedup.py` shim updates). Do the same for the other
stacks' largest non-test files (`harness/node/src/**/*.ts`, `harness/api_server/**/*.py`)
even though they aren't measured against this specific Python-side policy key —
report their sizes for context, not against a ceiling that doesn't apply to them.

### 3.4 Hardcoded-value / dead-code / missed-edge-case sweep

This is the one step that must be adversarial and evidence-based, not a pattern-match
against memory of what a prior pass found. For each candidate:

- **Hardcoded value**: is it read from `governance-policy.json` via `policy_loader.py`
  elsewhere in the codebase for the same concept? If yes, this is a real duplicate —
  cite both locations. If no equivalent policy key exists and the value is a true
  constant (HTTP status codes, exit codes, `encoding="utf-8"`), it is not a finding.
- **Dead code**: grep the definition *and every call site*. A function with only its
  own definition as a match is dead. Do not report on inspection alone.
- **Missed edge case**: read the corresponding test file and name the specific
  untested branch (function + condition), not a vague "needs more tests."

Prefer delegating this step to a subagent with no prior context on what was already
fixed, explicitly told what NOT to re-report (paste the disposition table from the
last audit round) — an agent with fresh eyes and a hard "verify, don't speculate"
instruction reliably outperforms re-scanning your own prior findings for staleness.

Quality bar: five verified findings beat twenty speculative ones. A category with
nothing real gets "checked, clear" in the report — not padded to look thorough.

### 3.5 Reusable-code / duplication check

Two call sites computing the same derived value, or two near-identical helper
functions in different files, are only a real finding if you can point to both sites
and confirm the logic — not just the shape — matches. A shared *signature* with
different *bodies* (e.g. two `_write()` helpers that write to different layouts for
different subsystems) is not duplication; forcing them into one abstraction is a
regression, not a fix. Confirm identical bodies before proposing a consolidation.

### 3.6 Doc / decision-log sync

Compare against what actually changed (§3.1's diff), not against a fixed checklist —
an audit round with no protected-path changes has nothing to attest, and one with
no new accepted-debt decision has nothing to log:

- `CHANGELOG.md` — new `###` entry under `## [Unreleased]` if anything shipped.
- `NEXT_STEPS.md` — milestone checklist entry if this round closes or opens one.
- `docs/architecture/c4_architecture.md` — only if a component/boundary changed.
- `README.md` — test-count / coverage-percentage figures, if `validation-runner`'s
  output changed them; verified by `test_documentation_truth.py`, not by eye.
- `harness/node/.governance/decision-log.md` + `harness/node/agents/GOVERNANCE_SKILL.md`
  — only for a genuine new decision (an accepted gap, a deferred item, a design
  choice) — not for routine bug fixes. Both files together, or
  `validate_governance_docs.py`'s freshness gate fails.
- `.gitignore` / `.dockerignore` / gitleaks config / `Makefile` — only if this
  round added a new artifact type, target, or secret pattern that needs one.

An audit round that touches none of these is not a gap — say so explicitly rather
than inventing a doc change to look complete.

## 4. Report format

One table, most-actionable first:

| Area | Finding | Disposition |
|---|---|---|
| Drift vs. main | e.g. "up to date" or "N commits behind" | merged / not applicable |
| Mechanical gates | pass/fail per `validation-runner`'s verdict | — |
| God-file watch list | file, lines, % of ceiling | watch / decompose now |
| Hardcoded values | file:line, concept, existing policy key if any | fix now / not a finding |
| Dead code | file:line, symbol | remove / not a finding |
| Missed edge cases | file:line, function, untested branch | add test / accepted gap |
| Duplication | both file:line locations | consolidate / not real duplication |
| Doc sync | which docs, why | updated / not applicable this round |

Every "not a finding" / "not applicable" row is as valuable as an actionable one —
it is the evidence that the category was actually checked, not skipped.

## 5. Non-negotiables (from `CLAUDE.md`, restated here because this skill exists to
enforce them, not to relax them)

- No hard-coded values — thresholds come from `governance-policy.json`.
- No test waivers or `xfail` without a decision-log entry.
- No credentials in code.
- Don't force an abstraction to close a "duplication" finding that isn't real (§3.5).
- Never mark a category clean without running its check — "probably fine" is not a
  disposition.
