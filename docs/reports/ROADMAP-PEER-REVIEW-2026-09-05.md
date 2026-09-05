# Roadmap peer review — `NEXT_STEPS.md` rewrite (2026-09-05)

**Reviewed artefact:** `NEXT_STEPS.md` on `main` @ `2441547` (post PRs #86–#88).
**Method:** same four-persona matrix as [`ROADMAP-PEER-REVIEW.md`](ROADMAP-PEER-REVIEW.md)
(Architecture / SDLC / QA / Product), plus live GitHub API checks (DEC-024).
**Outcome:** roadmap rewritten on branch `docs/next-steps-peer-rewrite-2026-09-05`.

## Thesis

The forward plan still said Phase B was "one PR (#86) away", which made every
Depends-on and every "after Phase B" parked item wrong, and it still treated
LangGraph park as the default while `main` absorbed two fail-closed LangGraph
PRs the same day.

## Counter-argument

Leaving NS-32 open until every remediation AC is green is safer than closing it
early; Phase B might still have unticked work hiding under wrong PR labels.

## Rebuttal

The remediation plan's own boxes are the acceptance authority (AC-6…AC-22 /
AC-33 already `[x]`). PR #86's title and body are audit docs, not R-SR-6…22.
Closing the *mis-labelled* roadmap item and pointing at the plan's boxes is the
honest move; any real remaining Phase B gap should reopen under its R-SR id, not
under "#86".

## Verified checks (2026-09-05)

| Check | Result |
|---|---|
| `GET …/rules/branches/main` | `[]` |
| License API | `null` |
| Tags | 0 |
| `feature/governed-run-console` | present @ `5970249…` |
| PR #86 | MERGED — `docs(reports): 2026 coding-standards audit` |
| PR #87 / #88 | MERGED — LangGraph fail-closed / conclusive counts |
| Remediation plan AC-6…22, AC-33 | `[x]`; AC-1…5, AC-23…32 open |

## Findings

| ID | Severity | Finding |
|---|---|---|
| PR-1 | Blocker (doc) | NS-32 mis-attributed Phase B to PR #86 |
| PR-2 | Blocker (product) | NS-31 park default contradicts DEC-052 / #87–#88 investment |
| PR-3 | Major | Stale `Depends on: NS-32` on NS-18/21/33 (and friends) |
| PR-4 | Blocker (unchanged) | NS-1/2/3/30 still blocked on owner actions |

## Rewrite actions

1. Close NS-32 into §Delivered with correct evidence pointers.
2. Force NS-31 LangGraph **KEEP vs PARK** table; retarget Phase E order.
3. Clear Phase-B depends-on; keep human P0 and real P1 queue.
4. Slim §6 so the file stays forward-looking (history by pointer).
