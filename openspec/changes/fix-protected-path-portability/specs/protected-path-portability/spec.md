# Spec: Protected-Path Portability (PPP)

> **Change:** `fix-protected-path-portability`
> **Version:** 1.0.0
> **Authors:** maintainer · reviewer
> **Status:** APPROVED

---

## Problem Statement

The write gate resolves its pattern set from a location fixed relative to the
installed harness and matches it against paths relative to whatever workspace it
is given. Where those two layouts differ, every pattern misses and the gate
permits every write, emitting no signal. The obvious remedy — reading the policy
from the governed tree — would let a writable tree widen the policy that governs
writes to it, so the remedy must constrain the merge rather than simply relocate
the source.

**Evidence:** `harness/shared/write_policy.py` declares `write_denial_reason(relpath,
policy_path=None)` and resolves `DEFAULT_POLICY_PATH` next to its own module;
`harness/shared/tool_executors.py` calls it bare twice and
`harness/shared/governance/broker.py` once, so the parameter is never exercised
outside tests. `governance-policy.json` carries sixty-two patterns written for
this repository's layout. `harness/CONTRACT.md` records the outcome as *"a
pattern written for a different repository layout matches nothing and protects
nothing — silently,"* and separately holds under INV-6 that the project
repository is not its own root of trust. An existing guard,
`test_protected_path_liveness.py`, asserts on the files each pattern matches and
requires dormant patterns to be declared, but validates only this repository's
patterns against this repository's tree.

---

## Requirements

- R-PPP-1: A supplied policy MUST combine with the harness policy by union, and
  a pattern declared by the harness policy MUST NOT be removed, disabled, or
  narrowed by a supplied policy.
- R-PPP-2: `ALWAYS_DENIED_SEGMENTS` and the read-side denials MUST remain
  unconditional and outside the merge.
- R-PPP-3: A supplied policy MUST be pinned by digest in a record held outside
  the tree it governs; a mismatched or absent record MUST produce a denial, never
  a default-allow.
- R-PPP-4: Every call site of `write_denial_reason` MUST supply an explicit
  policy path, and a bare call MUST fail a static check.
- R-PPP-5: A pattern set that matches no file in the tree it governs MUST produce
  a finding, and a pattern intended to match nothing MUST carry a declared
  reason.
- C-PPP-1: This change MUST NOT relax any denial that holds today, and MUST NOT
  add a CLI or HTTP surface accepting a target repository.
- C-PPP-2: No control introduced here may depend on the hook layer, which
  DEC-003 declares dormant and deliberately unmirrored.

---

## Acceptance Criteria

- [ ] **AC-PPP-1 (non-success):** A supplied policy crafted to remove a harness
  denial does not remove it; the write is still denied and the attempt is
  reported. (R-PPP-1)
  _Verified by:_ `pytest -k test_supplied_policy_cannot_remove_a_harness_denial` · stage: `make test-governance`

- [ ] **AC-PPP-2:** A supplied policy adding a pattern absent from the harness set
  causes a write matching only that pattern to be denied. (R-PPP-1)
  _Verified by:_ `pytest -k test_supplied_policy_adds_a_denial` · stage: `make test-governance`

- [ ] **AC-PPP-3 (non-success):** A write touching an always-denied segment is
  denied regardless of what any supplied policy says, and the read-side denials
  are unaffected by the merge. (R-PPP-2)
  _Verified by:_ `pytest -k test_always_denied_segments_ignore_supplied_policy` · stage: `make test-governance`

- [ ] **AC-PPP-4 (non-success):** A supplied policy whose digest does not match
  its record is denied and the denial names the mismatch; a supplied policy with
  no record is also denied rather than defaulting to the harness set. (R-PPP-3)
  _Verified by:_ `pytest -k test_digest_mismatch_and_missing_record_both_deny` · stage: `make test-governance`

- [ ] **AC-PPP-5:** No bare call to `write_denial_reason` remains in
  `tool_executors.py` or `governance/broker.py`, enforced by a static check that
  fails when one is reintroduced. (R-PPP-4)
  _Verified by:_ `pytest -k test_no_bare_write_denial_reason_call_remains` · stage: `make test-governance`

- [ ] **AC-PPP-6 (non-success):** A pattern set applied to a tree it matches no
  file in produces a finding rather than a clean pass, while this repository's own
  pattern set against its own tree stays quiet and its seven declared dormant
  patterns remain accepted. (R-PPP-5)
  _Verified by:_ `pytest -k test_pattern_set_matching_nothing_is_a_finding` · stage: `make test-governance`

- [ ] **AC-PPP-7 (non-success):** No denial that holds before this change is
  absent after it, verified by replaying the existing denial corpus against the
  merged policy. (C-PPP-1)
  _Verified by:_ `pytest -k test_existing_denial_corpus_is_unchanged` · stage: `make ci`

- [ ] **AC-PPP-8 (non-success):** No control introduced by this change resolves
  through a hook binding; disabling the hook layer entirely leaves every
  acceptance criterion above still passing. (C-PPP-2)
  _Verified by:_ `pytest -k test_controls_do_not_depend_on_the_hook_layer` · stage: `make test-governance`

---

## Invariants Touched

- Mango INV-6 — the project repository is not its own root of trust. Directly
  engaged: R-PPP-3 keeps the digest record outside the governed tree, which is
  what allows a policy to be read from that tree without the tree becoming its
  own anchor.
- Mango INV-8, INV-9, INV-10 — broker execution, deterministic verdict with
  denial on an unavailable backend, terminal DENY. Unchanged. Note that
  `harness/shared/tests/test_invariant_liveness.py` classifies INV-8 and INV-9
  under `INVARIANT_MECHANISMS`, meaning each is enforced by a reachable symbol
  rather than left dormant, which is why this change may rely on them.
- Mango INV-13 — digest-complete verified results. Not relied upon:
  `harness/CONTRACT.md` records it as not currently satisfiable because the
  process backend confines neither the filesystem nor the network (DEC-010). The
  digest pinning in R-PPP-3 is scoped to the policy artifact alone and does not
  assume INV-13.

---

## Decisions

- **DEC-PPP-001 (resolved):** Policies combine by union with the harness set as
  a floor. Substitution was rejected: it converts a silent-no-match failure into
  a self-modification failure, which is worse because the tree being governed is
  the tree supplying the constraint.
- **DEC-PPP-002 (resolved):** Merge semantics and digest pinning land before the
  parameter is threaded. Threading first would open a window in which a supplied
  policy could narrow a harness denial.
- **DEC-PPP-003 (resolved):** The existing in-repo liveness guard is generalised,
  not replaced. It already encodes the right assertion; it simply cannot travel.

---

## Non-Success Criteria (what this change rejects)

- A design in which a supplied policy substitutes for the harness policy is
  rejected outright (AC-PPP-1, DEC-PPP-001).
- Threading the parameter before the merge direction is tested is rejected
  (DEC-PPP-002).
- A digest record stored inside the tree it governs is rejected as a violation of
  INV-6 (R-PPP-3).
- A missing digest record treated as a default-allow is rejected (AC-PPP-4).
- Any control that stops working when the dormant hook layer is disabled is
  rejected as a dependency (AC-PPP-8).
- Adding an orchestrator target surface as part of this change is rejected;
  portability and targetability are separable and land separately (C-PPP-1).

---

## Validation Matrix

| Stage | Make Target | Pass Criteria |
|---|---|---|
| Governance | `make test-governance` | AC-PPP-1 through AC-PPP-6, AC-PPP-8 |
| Focused | `make validate` | Package validates clean; no bare call remains |
| Full | `make ci` | AC-PPP-7; no regression in the existing suite, lint, or type-check |
| Pre-submission | `make pre-pr` | All of the above green |
