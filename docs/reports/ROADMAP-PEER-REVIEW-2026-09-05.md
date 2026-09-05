# Roadmap peer review - `NEXT_STEPS.md` rewrite (2026-09-05)

**Reviewed artefact:** `NEXT_STEPS.md` on `main` @ `2441547` (post PRs #86-#88).
**Method:** same four-persona matrix as [`ROADMAP-PEER-REVIEW.md`](ROADMAP-PEER-REVIEW.md)
(Architecture / SDLC / QA / Product), plus live GitHub API checks (DEC-024).
**Outcome:** roadmap rewritten on branch `docs/next-steps-peer-rewrite-2026-09-05`.

## Thesis

The forward plan still said Phase B was "one PR (#86) away", which made every
Depends-on and every "after Phase B" parked item wrong. Separately, PR #87/#88 +
DEC-052 made LangGraph fail-closed on `main`, so NS-31 must record an explicit
decision - with **PARK (DEC-053 draft)** still the recommended path per Memo 1 /
R-SR-27, not KEEP-by-default.

## Counter-argument

(1) Leaving NS-32 open until every remediation AC is green is safer than closing
it early under a docs-titled PR. (2) Fail-closed investment on `main` should flip
the default to KEEP.

## Rebuttal

(1) PR #86's own body says "Phase B, landed here" and ticks AC-6…AC-22 / AC-33
with the commands they name across a 97-file diff; the docs-only title is
misleading, not dispositive. Closing NS-32 as landed on #86 and bumping the
remediation plan to rev 2 (Phase B Done) is the honest move; any real remaining
gap reopens under its R-SR id. (2) Fail-closed is correct whether parked or kept;
Memo 1 / R-SR-27 still recommend park-with-sunset. KEEP requires a DEC that
supersedes those memos - it is contested, not the default.

## Verified checks (2026-09-05)

| Check | Result |
|---|---|
| `GET …/rules/branches/main` | `[]` |
| License API | `null` |
| Tags | 0 |
| `feature/governed-run-console` | present @ `5970249…` |
| PR #86 | MERGED - title docs-only; body + diff = Phase B landing (R-SR-6…22) |
| PR #87 / #88 | MERGED - LangGraph fail-closed / conclusive counts (DEC-052) |
| Remediation plan AC-6…22, AC-33 | `[x]`; AC-1…5, AC-23…32 open |
| Phase E memo order | JVM → LangGraph → openspec → mirroring (R-SR-26…29) |
| Dependabot (NS-4) | `pip` removed; DEC-033; bot PRs #62-#73 left for maintainer close |

## Findings

| ID | Severity | Finding |
|---|---|---|
| PR-1 | Blocker (doc) | Open roadmap treated Phase B as unfinished; #86 *is* the Phase B landing PR despite docs-only title |
| PR-2 | Blocker (product) | NS-31 must choose KEEP vs PARK; **DEC-053 park recommended** after #87/#88 fail-closed - KEEP only via superseding DEC |
| PR-3 | Major | Stale `Depends on: NS-32` on NS-18/21/33 (and friends) - cleared to `nothing` |
| PR-4 | Blocker (unchanged) | NS-1/2/3/30 still blocked on owner actions |

## Rewrite actions

1. Close NS-32 into §Delivered as **landed on PR #86**; bump remediation plan to
   rev 2 (Phase B Done).
2. Force NS-31 **DEC-053 park recommended** table; Phase E order
   JVM → LangGraph → openspec → mirroring; do not log DEC-053 in this PR.
3. Clear Phase-B depends-on (NS-18/21/33 → nothing); keep Dependabot closed
   disposition (NS-4 / DEC-033 / #62-#73) visible in §Delivered.
4. Slim §6 so the file stays forward-looking (history by pointer); index this
   report in `harness/README.md`.


---

## Second pass (2026-09-05b)

Full method, evidence, findings PR-5…PR-12, and thesis / counter / rebuttal live
in [`ROADMAP-PEER-REVIEW.md`](ROADMAP-PEER-REVIEW.md) §5. Summary: tip is
`58490c1`; NS-11 / NS-31 / NS-33 move to Delivered; plan → revision 3 with AC-5
ticked; Phase E hard-gated on NS-2 (not on already-logged DECs); NS-17 stays
open citing #97 `policy_path`; Dependabot open queue empty.
