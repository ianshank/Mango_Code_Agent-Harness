# Milestones

## Milestone 1 — Merge semantics before plumbing  [TODO]

Decide and test how two policies combine before making it possible to supply a
second one. Landing the plumbing first would create a window in which a
target-supplied policy could narrow a harness denial.

- Implement the union with direction: harness denials are floor, target-supplied
  patterns may only add. A target policy that omits, disables, or narrows a
  harness pattern has no effect on that pattern.
- Keep `ALWAYS_DENIED_SEGMENTS` and `read_policy.read_denial_reason`
  unconditional and outside the merge entirely.
- Test the adversarial case directly: a target policy crafted to remove a harness
  denial is rejected and reported, not silently honoured.

- **Gate:** `make test-governance` green; the adversarial merge test fails when
  the union direction is inverted.

## Milestone 2 — Digest pinning  [TODO — depends on M1]

- Record the target policy's digest in a store held outside the tree it governs,
  consistent with INV-6 holding that the project repository is not its own root
  of trust.
- Treat a mismatch between the recorded digest and the policy actually loaded as
  a denial. A missing record is also a denial, not a default-allow.

- **Gate:** `make test-governance` green; a mutated target policy is denied and
  the denial names the digest mismatch.

## Milestone 3 — Thread the parameter  [TODO — depends on M1, M2]

- Pass `policy_path` explicitly from both call sites in
  `harness/shared/tool_executors.py` and the one in
  `harness/shared/governance/broker.py`.
- Add a guard asserting no bare call to `write_denial_reason` remains, so the
  defect cannot reappear by omission.

- **Gate:** `make test-governance` green; `make validate` green; a static check
  confirms every call site supplies the parameter.

## Milestone 4 — Portable liveness assertion  [TODO — depends on M3]

- Generalise `test_protected_path_liveness.py`'s assertion so it can be applied
  to a tree other than this repository: report a finding when a pattern set
  matches no file in the tree it governs, and require a dormant pattern to carry
  a declared reason.
- Preserve the existing in-repo behaviour and the seven already-declared dormant
  patterns unchanged.

- **Gate:** `make test-governance` green; `make ci` green; the assertion produces
  a finding against a deliberately mismatched layout and stays quiet against this
  repository's own.
