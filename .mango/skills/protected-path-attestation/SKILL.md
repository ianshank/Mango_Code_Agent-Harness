---
name: protected-path-attestation
Reviewed: 2026-08-28
description: >
  Produce the per-file attestation block that a protected-path change requires
  before the `infra-reviewed` label can honestly be applied. Reads
  protected_paths from governance-policy.json, diffs the branch against its
  base, and for every matched file states what changed and why it is safe. Use
  whenever validate_invariants reports "Unauthorized modifications to protected
  paths", or before opening any PR that touches the Makefile, pyproject.toml,
  .github/workflows/**, .mango/**, .claude/**, CLAUDE.md, harness/CONTRACT.md,
  the governance policy, or a shared validator.
---

# Protected-path attestation

`harness/CONTRACT.md` requires a per-change review attestation for every
protected file a PR modifies. `validate_invariants.py` enforces that a change
*has* been reviewed — `ALLOW_GITHUB_CHANGES=1`, derived from the
`infra-reviewed` label — but it cannot tell whether anyone looked at the diff.
The attestation block is what makes the label mean something, and writing one
is a repeatable procedure. This skill is that procedure.

It complements `repo-invariant-review`, which *predicts* which gates a change
will trip. This one *produces the artifact* that clears them.

## When it applies

Run this when any of these is true:

- `make validate` fails with `[FAIL] Protected Paths: Unauthorized
  modifications to protected paths detected: [...]`.
- You are about to open a PR whose diff touches a path matched by
  `protected_paths` in `harness/shared/governance-policy.json`.
- You are asking a human to apply the `infra-reviewed` label.

If none applies, stop. An attestation for an unprotected change is noise that
trains reviewers to skim the real ones.

## Procedure

1. **Generate, do not enumerate by hand.** One command prints the rows:

   ```bash
   make attestation                 # markdown rows, ready to paste
   make attestation BASE_REF=main   # only if the remote publishes no origin/HEAD
   ```

   This calls `harness/shared/governance/attestation.py`, which **imports**
   `is_protected` and `git_modified_files` from `validate_invariants.py` rather
   than reimplementing them. That matters more than convenience. This step used
   to be an inline script here that re-derived the match with its own `fnmatch`
   loop, hard-coded `origin/main`, and enumerated only `merge-base...HEAD` —
   so it could not see a staged, unstaged, or untracked protected file that the
   gate *does* see, and it broke outright on a fork whose default branch is not
   `main`. Two implementations of "which protected paths does this change
   touch" is one too many; the count that reaches the reviewer must come from
   the same code that fails the build (DEC-038).

   `fnmatch` is whole-string anchored. A pattern that matches nothing reports
   PASS *because nothing matched* — which is exactly how an earlier layout
   migration left four patterns silently dead. That is a reason to read the
   validator's output rather than trust a pattern list, not a reason to write a
   second matcher.

2. **Read each diff hunk.** Not the file, the hunk. `git diff <base>...HEAD --
   <path>`.

3. **Write one row per file**, with three columns: the file, what changed, and
   *why it is safe*. The third column is the attestation; the first two are
   context.

4. **Answer the question the reviewer will actually ask.** For each category:

   - **`Makefile`** — did `ci`'s prerequisite list change? If yes, say which
     gate was added or removed and what now enforces it. INV-5 requires gates
     be invoked by target; a recipe inlined into a workflow step is a
     regression even if CI stays green.
   - **`pyproject.toml`** — did a threshold, a `select` entry, or an ignore
     move in the *weakening* direction? A removed rule, a widened
     `per-file-ignores`, or a lowered floor all need the number that justified
     it.
   - **`.github/workflows/**`** — can the change cause a gate to be skipped on
     any matrix leg, or on any event type? Name the legs.
   - **`.mango/**`, `.claude/**`** — does the change alter what an agent is
     permitted to do? Waking a dormant hook, adding a tool, or widening a
     matcher all change tool-call behaviour for every future session. DEC-003
     keeps the `.mango` lifecycle hooks dormant; reversing that is its own
     reviewed change, never a side effect.
   - **`governance-policy.json`** — does a threshold move down? Does a
     `protected_paths` pattern stop matching a file it used to match? Run
     `make digest-regen` in the same commit; the committed bundle must be
     drift-free.
   - **Shared validators** (`validate_*.py`, `check_*.py`, `verify_*.py`) —
     does the gate still **fail closed**? State the input that used to fail and
     confirm it still does. A validator that starts returning early on a
     malformed input has been disabled, not fixed.
   - **`harness/CONTRACT.md`, `CLAUDE.md`** — does the prose now describe what
     the code does? A contract that overstates enforcement is worse than one
     that admits a gap.

5. **Name what you did not verify.** An attestation that claims more than you
   checked is worse than a short one.

## Output format

Paste this into the PR description, under a `## Protected-path attestation`
heading:

| File | Change | Why it is safe |
|---|---|---|
| `Makefile` | added `test-regression`, `node-deps` | `ci`'s prerequisite list is byte-identical (INV-5); both additions are new targets |
| `pyproject.toml` | expanded ruff `select`; pruned 3 dead ignores | expanded set is clean at time of change; pruned entries suppressed nothing measurable |

One row per protected file. No file may be omitted, and "no functional change"
is only acceptable when the diff is genuinely comments or formatting — say
which. The rows above are an *illustration of the columns*; never paste them.
`make attestation` emits the real ones with the third column blank, which is
the only column you have to write.

5. **Verify before you ask anyone to sign it.**

   ```bash
   make attestation-check FILE=pr-body.md   # or any file holding the description
   ```

   This fails if a protected path has no row, **or** if a row names a path the
   change does not touch — an over-long table asks the reviewer to attest to
   something absent, which is the same overstatement as a missing row pointed
   the other way. `build-full` runs the same check on every pull request,
   before `make ci` and independent of the label, so a mismatch is caught
   whether or not you run it locally.

## Failure modes this exists to prevent

- **One attestation for twenty files.** A single row saying "infra changes" is
  the pattern the per-change rule exists to prevent. Split the PR instead.
- **Attesting the file rather than the diff.** "Makefile: still valid Make" is
  not an attestation.
- **Copying the previous PR's block.** The enumeration step is cheap; a stale
  list is how a protected file rides along unreviewed.
- **Applying the label to unblock CI.** The label *is* the human review record.
  Applying it to make a red check go green makes the record false.
