---
name: gate-mutation-proof
Reviewed: 2026-09-04
description: >
  Prove a gate actually catches the defect it claims to catch, by mutating the
  code so the defect returns, asserting the gate fails, restoring, and asserting
  it passes. Use whenever a change adds or narrows a gate, a validator, a policy
  rule or a liveness test — a green test on a fixed tree proves the tree is
  fixed, never that the test would notice if it broke. Also the standing answer
  to "how do I know this test is not vacuous?".
validator_version: '2.0'
compatibility: python>=3.10
version: '1.0.0'
---

# gate-mutation-proof — a gate is only as good as its failing case

## Why this exists

A test written alongside a fix passes for two reasons that look identical from
the outside: the fix works, or the test cannot tell the difference. This
repository has shipped the second kind repeatedly, and each time the discovery
came from mutation rather than from review:

- Round 2's `AC-28` was ticked against `pytest -W error::DeprecationWarning`,
  a stage no `make` recipe ran (NS-29 review record).
- `test_constant_triage.check_row` evaluated an expression that made the whole
  R-TDH-16 gate green regardless of its input (DEC-032).
- `AC-7` in the round-3 plan named `pytest test_orchestrator_hooks.py -k timeout`,
  which matched only a pre-existing mocked test that passed with and without the
  fix under it.

The procedure below found all three, and was run on **every gate** the
`code-quality-tech-debt-plan` Phase 1 change added or altered, repeatedly, before
being written down here. A repeated manual procedure with a mechanical shape and
a history of finding real defects is a skill, not a habit (NS-20).

No running total is claimed, deliberately. An earlier draft of this file said
"ten times", the PR body said "twelve", and neither could be reconstructed from
the evidence — the same gate was mutated twice as its tests were strengthened,
so "how many" depends on whether you are counting gates or runs. A count nobody
can check is the kind of claim this skill exists to refuse (DEC-024). Record
which mutation was run against which gate and what it produced; that is
checkable, and a total is not.

## The loop

Four steps. All four are required; the last two are the ones people skip.

1. **Mutate** — reintroduce the *specific* defect the gate claims to catch. Edit
   the source, not the test. A one-character change is ideal.
2. **Assert it fails** — run the gate. It must fail, and the failure must name
   the mutated behaviour. A gate that fails for an unrelated reason has not been
   proved.
3. **Restore** — put the file back byte-for-byte.
4. **Assert it passes** — run the gate again, green. Without this you have
   proved the gate fails, not that it discriminates.

```bash
GATE='python -m pytest harness/shared/tests/test_x.py -q -p no:cacheprovider'
cp harness/shared/target.py /tmp/target.bak          # step 0: the restore point
# ... mutate harness/shared/target.py ...
$GATE                                                # step 2: MUST fail
cp /tmp/target.bak harness/shared/target.py          # step 3
$GATE                                                # step 4: MUST pass
```

## Four failure modes this procedure has itself

All four were hit while running it, and all four make the proof worthless rather
than merely awkward:

- **A mutation that leaves the tree dirty.** `git checkout` does not restore an
  *untracked* file, and `git stash` will carry your mutation into the stash. Copy
  the file aside first (step 0) and restore from that copy. Verify with
  `git diff --stat` that the tree is clean before you continue.
- **A proof run against a stale artifact.** Gates that read a generated file
  (`coverage.json`, `policy-artifact.json`, `.governance/vitest-results.json`,
  `pytest-skips.tsv`) will happily re-read the *previous* run's output and report
  the answer you were hoping for. Regenerate the artifact inside the mutated
  state, or assert against the source rather than the artifact.
- **A fixture whose value coincides with the default.** The one that has bitten
  most often — three separate times in the change that wrote this file. A test
  asserting `runner._timeout == orchestrator_defaults()["api_timeout_sec"]`
  passes with the policy read reverted to a literal `300`, *because the policy
  also says 300*. Same for any threshold whose fixture happens to equal the
  built-in. **Pick a value no default equals** — 287, not 300 — and the proof
  discriminates. `test_langgraph_policy.py::test_distinguishable_value_actually_flows_through`
  is the pattern; it exists because the same thing happened there first.
- **A probe that sets state the mutation reads at import.** Monkeypatching a
  module attribute *after* importing cannot test anything module scope did. A
  module-scope read has no "after import": `verify_zero_skips._POLICY_PATH`
  derives from `__file__`, so the fixture has to be on disk beside the module
  before the import statement runs — stage a copy of the module in a tmp tree.
  The first version of that test set the attribute after importing and passed
  with the fix reverted.

The common shape of the last two: **an assertion looser than the property it
claims to pin.** If the mutation passes, do not weaken the mutation — the test
is what is wrong. Fix the test, re-run the mutation, and record that it failed
first (see *Recording the result*): a proof that needed two attempts is more
informative than one that worked, because it names a trap the next author will
otherwise walk into.

## What counts as a mutation

Pick the change that a future contributor would most plausibly make by accident.

| Gate kind | Mutate by |
|---|---|
| A regex that must match a defect | Revert one alternative (`[<>]\(` → nothing) |
| A policy value read from JSON | Replace the read with the literal it used to be |
| A denial rule | Delete the branch that returns the denial |
| A liveness test over a file set | Point it at an empty set, or delete a row it checks |
| A workflow or Makefile contract | Remove the step or prerequisite it asserts |
| A fail-closed reader | Give the missing key a default instead of raising |

Two mutations beat one when a gate has halves that can fail independently — the
Phase 1 classifier needed separate proofs for the glob rule and the brace
expander, and reverting only one left the other's tests green.

## Recording the result

A mutation proof is evidence, so it goes where evidence goes: the PR's
Validation section, as the mutation and both counts.

```text
revert _COMPOUND to the pre-fix form   -> 3 failed, 109 passed
disable the glob check                 -> 9 failed, 103 passed
all restored                           -> 0 failed
```

Do not paraphrase it as "mutation tested". `CLAUDE.md`'s rule applies to this
skill as much as to anything else: a verification claim in prose is not evidence.

## When it does not apply

- A gate whose failing case is already a committed test (a `tmp_path` negative
  probe). That *is* the mutation, permanently. Say so instead of repeating it.
- A pure refactor with no behaviour change and no new gate.
- Anything where the mutation cannot be made without editing the test itself:
  that is the finding. A gate you can only break by breaking its own test is
  measuring the test.
