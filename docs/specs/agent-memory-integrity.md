# Spec: agent-memory-integrity (closing the raw-write bypass of `hypothesis_register` / `knowledge_gap_log`)

> **Status:** DRAFT, revision 1. Not yet implemented; no acceptance criterion below is
> ticked. Informed by the deep peer review in
> `docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md`, which this spec discharges.
> **Protected-path status:** touches `harness/shared/write_policy.py` (protected — under
> `harness/shared/governance/**`'s sibling, itself listed by name would need adding; confirm
> at implementation via `make attestation`), `harness/shared/meta_tools.py`,
> `harness/shared/memory_view.py`, `harness/shared/memory_store.py`. `infra-reviewed`
> attestation required if `make validate` reports any of these as protected on the
> implementation branch.
> **Base:** written against `main` @ `6ce45d1`.
> **Peer review:** not yet run. Step 1 below is `openspec-peer-review` from the
> Architecture, SDLC-CI, QA and Product perspectives, required by `CLAUDE.md` because this
> change touches core agent-memory modules.
> **Related:** `docs/specs/hypothesis-revision.md` (DEC-057) and
> `docs/specs/hypothesis-surfacing.md` (DEC-058) gave the store revision and prompt-surfacing
> semantics this spec assumes and does not change. `docs/decisions/DEC-049.md` /
> `DEC-051.md` fixed the parallel defect on the verdict-forgery surface (audit B4); this spec
> is the analogous fix for the memory surface, which that work's scope never named.

## Problem statement

`hypothesis_register` and `knowledge_gap_log` are the declared, sole path by which the agent
records what it believes and what it could not determine
(`harness/shared/meta_tools.py`'s module docstring). Both validate their input before writing:
`hypothesis_register` rejects a `status` outside `HYPOTHESIS_STATUSES` and a `confidence`
outside `[_CONFIDENCE_MIN, _CONFIDENCE_MAX]` (`meta_tools.py:242-268`). Neither the write door
(`write_policy.write_denial_reason`) nor the tamper-detection door
(`harness/shared/governance/enforcement_digest.py`) knows those tools exist. Both doors are
path-based, and the path they do not name is the one the meta-tools write to.

Evidence on `main` @ `6ce45d1`:

```
$ python3 -c "
from harness.shared.write_policy import write_denial_reason
print(write_denial_reason('.mango/memory/hypotheses.json'))
print(write_denial_reason('.mango/memory/gaps.json'))
"
None
None
```

`None` means the write is allowed. `nemotron-reasoner` (the only active role that calls
`hypothesis_register`) maps to canonical role `implementer`
(`harness/shared/agent_authority.py:34-38`), whose `allowed_actions` include `write`
(`harness/shared/agent-policy.json`), which is exactly the action `write_file` and
`apply_patch` require (`agent_authority.TOOL_REQUIRED_ACTION`). The same active role that
legitimately calls the validated meta-tool can, in the same turn or a later one, call
`write_file(".mango/memory/hypotheses.json", <attacker-shaped JSON>)` instead, and the bytes
reach disk with none of `hypothesis_register`'s checks run over them — confirmed by reading
`harness/shared/tool_executors.py:88-115` (`execute_write_file` calls `write_denial_reason`
and, on `None`, writes the caller's content verbatim) and comparing against
`harness/shared/meta_tools.py:150,311` (`knowledge_gap_log` / `hypothesis_register` call
`append_locked` directly — a different function, never `write_denial_reason` — so the two
paths converge only on the file, not on any shared validation).

A forged entry that is well-formed by the *shape* checks `harness/shared/memory_view.py`
already runs defensively (`_is_open`, `_render_confidence` — both written to tolerate a
"hand-edited store" without crashing, per their own docstrings) passes those checks
identically to a genuine one, because shape and authenticity are different properties and
this module has never claimed the second. `format_hypotheses_for_reasoner`
(`docs/specs/hypothesis-surfacing.md`, DEC-058) then renders it into
`REASONER_PROMPT_TEMPLATE`'s `{open_hypotheses}` slot with no check in between.

No existing test exercises this: `harness/shared/tests/test_write_policy.py` has no case
naming `.mango/memory`; `harness/shared/tests/test_hypothesis_revision.py` and
`test_hypothesis_surfacing.py` test the meta-tool's own validation and the formatter's
rendering, never the raw-write path that skips both.

### Why the fix is a write-door denial, not a signature

A signature (HMAC or similar) over each entry was considered and is **not** proposed as the
primary control. The active role that can forge an entry already has `read_file` over the
whole harness source tree and, per `agent-policy.json`, `test_execute`; any signing key
resolvable by the harness process at write time is resolvable by the same role at forge time,
by reading the code that resolves it or the environment it resolves from. A signature scheme
under that threat model authenticates "produced by code that had the key," which the forger
also has — it would not be a security control, only a more complicated one. (This is the same
reasoning `agent-policy.json`'s own comment block uses for why `ProcessBackend` is described
as containment, not isolation: naming a control that does not hold under the actual threat
model is worse than not claiming it.)

The control that does hold is structural: deny the raw-write tools the path the meta-tools
own, the same way `write_denial_reason` already denies a credential filename regardless of
`protected_paths` — "writing it is the `secret_access` action, which no agent role holds"
(`write_policy.py:398-406`). This spec adds the equivalent sentence for memory: writing the
memory store directly is the meta-tool's action, which only `hypothesis_register` and
`knowledge_gap_log` may take, and `write_file` / `apply_patch` / a `run_command` redirect are
none of those.

`harness/shared/governance/broker.py:254` already applies `write_denial_reason` to every
`run_command` write target via `command_write_targets.write_targets`
(`harness/shared/governance/command_write_targets.py`), so one change in
`write_denial_reason` closes all three tool paths (`write_file`, `apply_patch`,
`run_command`-redirect) at once, and none of it touches `meta_tools.append_locked`, which
never calls `write_denial_reason` and is unaffected.

## Requirements

- R-AMI-1: `write_policy.write_denial_reason` MUST deny any write target whose path, once
  resolved relative to the workspace, falls inside the agent memory directory
  (`.mango/memory/`, matched the same way `ALWAYS_DENIED_SEGMENTS` matches `.git` — by path
  segment, not by a `protected_paths` glob, and evaluated before `protected_paths` is
  consulted, so an unreadable policy still denies it). The denial reason MUST name the
  meta-tools as the sanctioned path, mirroring the credential-filename message's shape
  (`write_policy.py:398-406`). `meta_tools.append_locked` MUST NOT call
  `write_denial_reason` and MUST remain the only writer that reaches the store's bytes,
  unaffected by this change.
- R-AMI-2: The denial MUST apply uniformly across `write_file`, `apply_patch`, and any
  `run_command` whose resolved write targets fall inside the memory directory
  (`command_write_targets.write_targets`), proven by one test per tool rather than assumed
  from R-AMI-1 alone, since the three tools reach `write_denial_reason` through three
  different call sites (`tool_executors.execute_write_file`,
  `tool_executors.execute_apply_patch`, `governance/broker.py:254`).
- R-AMI-3: The denial MUST hold for both memory-directory resolution modes
  `meta_tools.resolve_memory_dir` supports: the workspace-scoped path
  (`<workspace>/.mango/memory/`) and the legacy install-root path, so an agent cannot route
  around the denial by writing to whichever resolution the running harness is *not* currently
  scoped to.
- R-AMI-4: A regression test MUST reproduce the exact scenario named in
  `docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md` §2.1: a **well-formed** forged
  hypothesis (valid `uuid4`-shaped id, a status inside `HYPOTHESIS_STATUSES`, a confidence
  inside range, a false claim) attempted via `write_file` MUST be refused before any byte
  reaches disk, and the store's prior content (if any) MUST be verified unchanged
  byte-for-byte after the attempt. A test that only forges a malformed entry does not satisfy
  this requirement — the found gap is specifically that well-formed forgeries pass every
  existing shape check.
- R-AMI-5: The fix MUST NOT add a new dependency, a new module, or a new policy key: the
  memory directory's resolved path is already computable from
  `meta_tools.resolve_memory_dir`, and the denial belongs beside the other
  decided-before-any-policy-is-read checks already in `write_denial_reason`
  (`ALWAYS_DENIED_SEGMENTS`, credential filenames), per the module's own stated ordering.
- C-AMI-1: `.mango/memory/**` MUST NOT be added to `governance-policy.json`'s
  `protected_paths`. That list feeds `enforcement_digest.py`'s pre/post-run tamper baseline,
  and the memory store legitimately changes on every run a meta-tool is called — adding it
  there would make every ordinary `hypothesis_register` call during a run register as
  `enforcement_tampered` on the next verification, which is a regression this spec must not
  introduce. The denial is a `write_policy`-only, tool-path-only control, deliberately
  outside the protected-paths / digest mechanism.
- C-AMI-2: The meta-tools' own validation (`HYPOTHESIS_STATUSES` membership, confidence
  range, the `revises` resolution logic from DEC-057) is unchanged. This spec closes the
  bypass of that validation; it does not add a second validation layer to the validated path.
- C-AMI-3: `memory_view.py`'s existing defensive rendering (`_is_open`, `_render_confidence`)
  stays as-is: it protects against a store that predates this fix, or one edited by a
  human operator directly (a use case this spec does not remove), and is orthogonal to the
  write-door fix, not superseded by it.

## Acceptance criteria

- [ ] AC-AMI-1: `write_denial_reason('.mango/memory/hypotheses.json')` and
      `write_denial_reason('.mango/memory/gaps.json')` each return a non-`None` string naming
      the meta-tools as the sanctioned writer, and a path outside the memory directory
      (e.g. `.mango/memory-not-really/x.json`, a sibling with a similar prefix) is unaffected;
      `git grep -c "^import\|^from" harness/shared/write_policy.py` reports no new import
      added by this change (no new dependency, no new module) —
      `pytest -k "test_the_memory_directory_is_denied_to_raw_writes or test_a_lookalike_path_outside_the_memory_directory_is_not_denied"`
      · stage: `make coverage` (R-AMI-1, R-AMI-5)
- [ ] AC-AMI-2: dispatching `write_file` and `apply_patch` at `.mango/memory/hypotheses.json`
      each return the denial message and leave the file's prior bytes unchanged; a
      `run_command` whose shell redirects into that path (e.g. `echo x > .mango/memory/hypotheses.json`)
      is denied by the broker before the subprocess runs —
      `pytest -k "test_write_file_is_denied_over_the_memory_store or test_apply_patch_is_denied_over_the_memory_store or test_a_shell_redirect_into_the_memory_store_is_denied"`
      · stage: `make test-python` (R-AMI-2)
- [ ] AC-AMI-3: with the harness resolved to workspace-scoped memory and, separately, to the
      legacy install-root path (`meta_tools.resolve_memory_dir` monkeypatched each way), a
      `write_file` at the resolved hypotheses path is denied in both configurations —
      `pytest -k test_the_denial_holds_under_both_memory_resolution_modes`
      · stage: `make coverage` (R-AMI-3)
- [ ] AC-AMI-4: seed a store with one genuine `confirmed` entry via `hypothesis_register`;
      attempt `write_file` with a second, well-formed entry (valid uuid4, status
      `confirmed`, confidence `0.99`, a false claim) appended to the same file; assert the
      write is denied, the store on disk still contains exactly the one genuine entry
      (byte-for-byte), and `format_hypotheses_for_reasoner` over that store renders only the
      genuine entry — `pytest -k test_a_well_formed_forged_hypothesis_is_refused_and_never_surfaced`
      · stage: `make test-regression` (R-AMI-4)
- [ ] AC-AMI-5: `hypothesis_register` and `knowledge_gap_log`, called normally through the
      dispatcher against a fresh or existing store, succeed exactly as before this change
      (no new denial, no new argument, no changed return shape) — the full existing
      `test_hypothesis_revision.py` and `test_hypothesis_surfacing.py` suites pass unmodified
      · stage: `make coverage` (C-AMI-2)
- [ ] AC-AMI-6: `git grep -n "\.mango/memory" harness/shared/governance-policy.json` returns
      nothing, and a test asserts `enforcement_digests()` over a workspace that has had
      `hypothesis_register` called twice during a simulated run reports the same digest set
      before and after (memory is invisible to the tamper baseline by construction) —
      `pytest -k test_the_memory_store_is_not_part_of_the_enforcement_digest_baseline`
      · stage: `make coverage` (C-AMI-1)
- [ ] AC-AMI-7: a store written by a human operator directly (bypassing both the meta-tool
      and the agent's tool surface entirely, as `make memory-show`'s own workflow assumes is
      possible) with a malformed entry still renders safely via the existing
      `_is_open` / `_render_confidence` defensive paths — the pre-existing tests for those
      functions pass unmodified · stage: `make coverage` (C-AMI-3)

## Steps

1. Land this spec — peer-review it with `openspec-peer-review` (required: this change touches
   `write_policy.py` and the memory read/write modules).
2. Denial — add the memory-directory check to `write_policy.write_denial_reason`, ordered
   beside `ALWAYS_DENIED_SEGMENTS` and the credential-filename check (R-AMI-1, R-AMI-3, R-AMI-5).
   Resolve the memory directory via `meta_tools.resolve_memory_dir` rather than a hard-coded
   `.mango/memory` literal, so both resolution modes are covered without a second constant.
3. Tool-path proof — one test per tool (`write_file`, `apply_patch`, `run_command` redirect)
   against the real dispatcher/broker (R-AMI-2, AC-AMI-2).
4. Resolution-mode proof — the workspace-scoped and legacy-install-root cases (R-AMI-3, AC-AMI-3).
5. The well-formed-forgery regression — the scenario the peer review named, seeded through the
   real `hypothesis_register` call and then attacked through the real `write_file` dispatch,
   with a byte-for-byte store diff assertion (R-AMI-4, AC-AMI-4). Lands in
   `harness/shared/tests/regression/` per this repository's convention for end-to-end
   forgery reproductions (mirrors `test_verdict_forgery_regression.py`'s shape for the B4
   fix).
6. Non-regression proof — the full existing hypothesis/gap suites, unmodified, plus the
   digest-baseline exclusion test and the human-edited-store defensive-path test
   (C-AMI-1, C-AMI-2, C-AMI-3, AC-AMI-5, AC-AMI-6, AC-AMI-7).
7. Record it — a `docs/decisions/DEC-0NN.md` entry (next available id at implementation
   time) naming the closed gap, the rejected signature approach and why, and the explicit
   `protected_paths` exclusion (C-AMI-1) so a future reviewer does not "fix" this by adding
   `.mango/memory/**` there; `make decision-index`; move the corresponding `NEXT_STEPS.md`
   item to §6 Delivered; mark this report's finding closed in
   `docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md`.
8. Gate — `ALLOW_GITHUB_CHANGES=1 make pre-pr`; attestation table via `make attestation` if
   `write_policy.py` or `meta_tools.py` resolve as protected on the implementation branch.

## Files touched

- `docs/specs/agent-memory-integrity.md` — this document (new)
- `harness/shared/write_policy.py` — the new denial check (R-AMI-1, R-AMI-3, R-AMI-5)
- `harness/shared/tests/test_write_policy.py` — AC-AMI-1
- `harness/shared/tests/test_orchestrator_dispatch_regression.py` (or equivalent dispatcher
  test module) — AC-AMI-2
- `harness/shared/tests/regression/test_memory_integrity_regression.py` — new, AC-AMI-4
- `harness/shared/tests/test_meta_tools.py` / `test_hypothesis_revision.py` — AC-AMI-3,
  AC-AMI-5
- `harness/shared/tests/test_enforcement_digest.py` — AC-AMI-6
- `harness/shared/tests/test_memory_view.py` / existing formatter tests — AC-AMI-7
  (unmodified, cited as evidence, not touched)
- `docs/decisions/DEC-0NN.md` (new, at implementation), `docs/decisions/index.{md,json}`
- `NEXT_STEPS.md`, `CHANGELOG.md`,
  `docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md` (finding marked closed)

## Invariants touched

- INV-6 (protected paths): explicitly **not** engaged (C-AMI-1) — this is the invariant this
  spec deliberately does not reach for, and the reason is recorded so it is not re-derived as
  "just add it to `protected_paths`" by a future pass.
- INV-8/INV-9/INV-10 (write/read/broker containment): extended. The write door gains one more
  decided-before-any-policy-is-read case, in the same family as `.git` and credential
  filenames, proved by the direct-door and `run_command`-redirect tests (AC-AMI-2).
- INV-16 (cognitive/execution boundary): unaffected. This spec does not change what reaches a
  prompt (`memory_view.py`'s renderers are untouched); it changes what may reach the *store*
  the renderers read from.

## Validation matrix

- `make coverage` — AC-AMI-1, AC-AMI-3, AC-AMI-5, AC-AMI-6, AC-AMI-7, plus existing coverage
  floors
- `make test-python` — AC-AMI-2
- `make test-regression` — AC-AMI-4, and the existing `test_verdict_forgery_regression.py`
  tier unchanged (confirms the new check does not interact with the B4 fix's own tests)
- `make validate` — protected-path attestation if `write_policy.py` resolves as protected
- `make specs` — the plan gate over this document (INV-17)
- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — the full gate

## Backward compatibility

Additive and narrowing only in the direction of denial, never of grant:

- A workspace whose agent has never attempted a raw write to `.mango/memory/` sees no
  behavioural change: `hypothesis_register` and `knowledge_gap_log` continue to succeed
  exactly as before (AC-AMI-5).
- A workspace or test fixture that directly manipulates
  `.mango/memory/*.json` via ordinary filesystem APIs (`Path.write_text`, `open()`, not
  through the harness's own `write_file` tool dispatch) is unaffected: R-AMI-1 gates the
  **tool dispatch path** (`write_file` / `apply_patch` / `run_command`), not filesystem access
  in general, matching how the credential-filename check works today for `.env`. Human
  operators using `make memory-show` or hand-editing the store for testing are unaffected
  (C-AMI-3, AC-AMI-7).
- No policy key, schema, or CLI flag changes. No adopter migration is required.

## Open questions

1. **Should a future multi-tenant or shared-workspace mode revisit C-AMI-1's exclusion from
   `protected_paths`?** If a later design makes the memory store shared across concurrent
   agents (out of scope for the current single-workspace-per-run model), a run-scoped tamper
   baseline over memory might become meaningful in a way it is not today, where every run
   legitimately mutates it. Recorded so a future spec revisits the premise deliberately
   rather than by accident.
2. **Is a provenance *log* (not a signature) worth adding later?** `R-HS-7`
   (`docs/specs/hypothesis-surfacing.md`) already logs `event=hypotheses_surfaced` with
   `run_id` and rendered `ids` on read. A symmetric `event=hypothesis_written` /
   `event=gap_written` on the write side, inside `meta_tools.py`, would let an operator
   correlate "this id was written by a real tool call at this run_id" after the fact, which
   is a detective control the door-denial fix does not provide (denial prevents; a log lets
   an operator notice if a denial is ever itself regressed). Not required by this spec's
   acceptance criteria; proposed as a Phase F-style slack item for a follow-up spec rather
   than folded in here, to keep this change reviewable as one structural fix.
