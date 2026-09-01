# Change: Fix Protected-Path Portability (PPP)

> **Status: proposed.** This is a live defect in this repository, independent of
> any consumer. It has no legal precondition and does not depend on any other
> change package.

## Why

`write_denial_reason` accepts a `policy_path` parameter that no caller passes,
so the protected-path set is always this repository's own, matched against
whatever tree the agent happens to be working in. Against this repository that
is correct and well-guarded. Against any other layout it degrades to a gate that
permits everything, and it does so without emitting a signal.

**Evidence:** `harness/shared/write_policy.py` declares
`def write_denial_reason(relpath: str, policy_path: Path | None = None) -> str | None`
and resolves `DEFAULT_POLICY_PATH = Path(__file__).resolve().parent /
"governance-policy.json"`, with the comment that the policy travels with the
installed harness rather than being read out of whatever tree the agent is
working in. Every call site invokes it bare:
`harness/shared/tool_executors.py` twice, as
`write_denial_reason(str(target_path.relative_to(workspace)))`, and
`harness/shared/governance/broker.py` once, as `write_denial_reason(target)`.
The pattern set in `governance-policy.json` enumerates sixty-two entries, all
written for this repository's layout (`harness/shared/governance/**`,
`.mango/agents/**`, `harness/CONTRACT.md`). `harness/CONTRACT.md` states the
consequence directly: *"a pattern written for a different repository layout
matches nothing and protects nothing — silently."*

**What already exists, and what it does not cover.** This repository is not
naive about the failure: `test_protected_path_liveness.py` asserts on the set of
files each pattern actually matches and requires an intentionally-dormant
pattern to be declared with a reason, and seven patterns are so declared. That
guard is real and this change does not replace it. What it does not do is
travel: it validates this repository's patterns against this repository's tree.
Nothing checks a pattern set against a foreign tree, because nothing can
currently supply one.

**The tempting fix is worse than the defect.** Reading a policy out of the tree
the agent is being governed in means an agent that can write to that tree can
widen its own policy. `harness/CONTRACT.md` INV-6 holds that the project
repository is not its own root of trust, and a naive `policy_path` threading
would violate it. The remedy therefore has to be a merge with a direction, not a
substitution: a target-supplied policy may add denials and may never remove one,
and its digest is pinned outside the tree it governs.

## What Changes

- Thread the existing `policy_path` parameter from all three call sites in
  `tool_executors.py` and `governance/broker.py`, so a policy can be supplied
  rather than always resolved next to the module.
- Constrain the merge: a target-supplied pattern set is unioned with the harness
  set. A pattern present in the harness set cannot be removed, disabled, or
  narrowed by a target-supplied policy. `ALWAYS_DENIED_SEGMENTS` and the
  read-side denials in `read_policy.read_denial_reason` remain unconditional.
- Pin the target policy by digest in a record held outside the target tree, and
  treat a digest mismatch as a denial rather than a warning.
- Generalise the liveness assertion so it can run against a foreign tree: a
  pattern set that matches no file in the tree it is applied to produces a
  finding, and an intentionally-dormant pattern must be declared with a reason,
  exactly as the existing in-repo guard requires.

## Non-Goals

- **No new CLI or HTTP surface accepting a target repository.** This change
  makes the policy portable; it does not make the orchestrator targetable. The
  two are separable and the second must not land first.
- **No widening of what is denied.** This change alters where a policy may be
  read from and how two policies combine. It removes no denial and relaxes no
  existing pattern.
- **No dependency on the hook layer.** `.mango/settings.json` declares its hooks
  dormant by DEC-003 and states they are deliberately not mirrored into the file
  Claude Code reads, so none of them run. Every control here lives on the
  in-process broker path.

## Affected Capabilities

- `protected-path-portability`
