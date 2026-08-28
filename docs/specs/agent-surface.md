# Spec: agent-surface

> PR C of the v3 remediation program; **requires the `infra-reviewed` label**.
> It edits `.mango/**`, `.claude/hooks/session-start.sh`,
> `.github/workflows/**` and `README.md`. Per-file attestation is in the PR
> description per `harness/CONTRACT.md`.

## Problem statement

The agent control surface — skills, hooks, session bootstrap — is the part of
this repository with the least enforcement and the most authority. Measured
before this change:

1. **Not one of the ten `SKILL.md` files carried a `Reviewed:` date**, so the
   policy's `skill_max_age_days: 90` applied to `GOVERNANCE_SKILL.md` alone.
   The skills could age indefinitely with no signal.
2. **Only three skills were reachable from an executable step.** (The earlier
   audit reported six as "orphaned"; measured, *every* skill is mentioned
   somewhere — in the README, `CONTRACT.md`, or source. The real gap is that
   being *mentioned* is not being *invoked*, and nothing distinguished a skill
   a gate runs from a skill that is documentation.)
3. **`.mango/settings.json` invoked hook scripts by bare path**, while every
   tracked `.sh` in the repository is mode 644 — a guaranteed
   `Permission denied` the moment anyone woke them. (The audit called this a
   file-mode problem; it is an invocation problem. `.claude/settings.json`
   already routes through `bash`.)
4. **Two hooks named files that do not exist** — `PLAN.md`, `NOTES.md` — and
   `save_state_before_compact.sh` would have appended to
   `$PROJECT_DIR/NOTES.md`, a path neither tracked nor ignored, leaving an
   untracked file in every subsequent `git status`.
5. **`.github/skills/code-review/` was a second skill root**: fully orphaned,
   naming a different project ("Mango-Metrics-NLM"), and asserting a >80%
   coverage bar against a policy that declares 90.
6. **`make pre-pr` could not complete in a web session.** CLAUDE.md calls it
   non-negotiable, but `.claude/hooks/session-start.sh` installed Python only,
   so `test-node` and `verify-zero-skips` had no `node_modules`.
7. **`README.md` drew `.agents/skills/nemotron-reasoner/SKILL.md`** in its
   layout tree — a directory that does not exist — and `.gitignore` still
   carried Pong rules two PRs after the demo was deleted.
8. **No scheduled automation existed at all**; `python-package.yml` was the
   only workflow, so nothing could observe drift that no single PR causes.

## Requirements

- R-AS-1: Every `SKILL.md` MUST carry a `Reviewed: YYYY-MM-DD` line inside its
  frontmatter. Presence MUST block; **age MUST NOT** — a clock-dependent gate
  turns unrelated PRs red at a date boundary.
- R-AS-2: Every skill MUST be classified as either reachable from an
  enforcement path (with what invokes it, verified) or standalone
  documentation (with a substantive reason).
- R-AS-3: `.mango/` MUST be the only skill root in the repository, enforced
  against the tracked file list rather than a hard-coded directory list.
- R-AS-4: Every hook command in both settings files MUST route through `bash`.
  File modes MUST be uniform; **no file may be made executable** — the
  convention is 644 and the invocation is what changes.
- R-AS-5: Every path a hook script names MUST exist, or be a gitignored runtime
  artifact the script guards with a conditional. Hooks MUST write only into
  gitignored locations.
- R-AS-6: The `.mango` lifecycle hooks MUST remain dormant (DEC-003), pinned by
  a test that fails if one is bound in `.claude/settings.json`.
- R-AS-7: `session-start.sh` MUST install every dependency `make ci` needs,
  through the same Make target CI uses, with an opt-out
  (`MANGO_SKIP_NODE_DEPS=1`) and without failing the session when the Node
  install fails. gitleaks is the one declared gap.
- R-AS-8: Documentation that names a repository path MUST name one that
  exists, enforced for the README layout tree and for `.gitignore`.
- R-AS-9: `agent-policy.json`'s roles and `harness/shared/agents/*.md` MUST be
  in exact correspondence in both directions.
- R-AS-10: Scheduled workflows MUST open issues and MUST NOT block: everything
  they detect is either clock-dependent or caused by interleaved merges, not by
  the PR in front of the author.
- C-AS-1: No agent gains authority. No hook is woken, no tool added, no matcher
  widened.
- C-AS-2: Exactly one new skill (`protected-path-attestation`); the 3-active
  role set is unchanged.

## Acceptance criteria

- [x] AC-1: `ALLOW_GITHUB_CHANGES=1 make ci` passes end to end.
- [x] AC-2: `test_agent_surface_liveness.py` passes, and fails when
  `session_start.sh` is reverted to naming `PLAN.md` (verified).
- [x] AC-3: `test_documentation_truth.py` fails when `.agents/` is reintroduced
  into the README tree (verified).
- [x] AC-4: `actionlint` is clean over both workflows.
- [x] AC-5: `git ls-files -s .mango/hooks .claude/hooks` reports one mode.
- [x] AC-6: Every skill is classified; the wired claims are checked against the
  Makefile rather than trusted.

## Invariants touched

- INV-4 (hook installer): unchanged in code; the weekly workflow observes it
  and reports, never blocks.
- INV-5: preserved — no Make target changes in this PR.
- INV-6: engaged — protected paths modified, attested per file in the PR.
- INV-7 (bounded agent authority): **strengthened**. The
  agent-policy/contract correspondence is now enforced in both directions, so
  a role cannot be granted authority without a written contract, and a contract
  cannot exist for a role the policy never approved.
- INV-16: unaffected.

## Validation matrix

- `ALLOW_GITHUB_CHANGES=1 make pre-pr`
- `actionlint .github/workflows/*.yml`
- `bash -n` over every hook script
- Negative probes: revert `session_start.sh`; reintroduce `.agents/` into the
  README tree. Each must fail its gate.

## Backward compatibility

- No hook changes behaviour, because none of them run: the `.mango` set is
  dormant by DEC-003, and this PR keeps it that way. The scripts are corrected
  so that waking them later is a decision rather than a debugging session.
- `session-start.sh` gains a step. It is skippable (`MANGO_SKIP_NODE_DEPS=1`),
  skipped automatically when pnpm is absent, and non-fatal on failure, so the
  worst case is the behaviour that existed before.
- Deleting `.github/skills/code-review/` removes nothing that was reachable:
  no file, target, or workflow referenced it. It is deliberately **not** added
  to `protected_paths` — a pattern for a directory that should not exist is the
  dead-pattern problem this programme has been removing.
- The scheduled workflows cannot fail a PR; they have `issues: write` and
  `contents: read`, and run only on `schedule` and `workflow_dispatch`.

## Open questions

None. Two corrections to the plan, both from measurement:

1. **"Six orphaned skills" was wrong** — every skill is referenced somewhere.
   The useful distinction is invoked-by-a-gate versus documentation, which is
   what the classification test encodes.
2. **The hook problem was never file mode.** Every tracked `.sh` is 644 and
   that is correct; the defect was `.mango/settings.json` invoking bare paths.
   `chmod +x` would have "fixed" it by breaking the convention. The one 755
   outlier was normalised **down**.
