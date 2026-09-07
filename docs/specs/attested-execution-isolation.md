# Spec: attested execution isolation

Spec class: program-plan

> Closes INV-13 by building the evidence record first and the sandbox second.
> Consumes DEC-010, DEC-013, DEC-024, DEC-043, DEC-052, DEC-065. Retires the
> `AC-CE-1` "ProcessBackend capability profiles" row parked in NEXT_STEPS §4.
> Revised after peer review; the review findings are recorded inline where they
> changed a requirement.

## Problem statement

INV-13 requires a "verified" result to carry policy, test, sandbox, source and
tool-version digests. `harness/CONTRACT.md` records it as **not currently
satisfiable**, and `harness/shared/agent-policy.json` names the reason: the
process backend contains but does not isolate.

Five results measured against this branch turn that into a plan. Each was
reproduced independently before this spec was written.

**1. The gap is reachable.** Driving the real `ExecutionBroker` as
`implementer`, writing `test_payload.py` into the pinned workspace and running
`pytest -q -s test_payload.py` returns broker status `SUCCESS` classified
`test_execute`, while the payload reads a host file outside the workspace,
writes a file outside it, and opens an outbound connection. A direct
`printf x > /abs/path` is denied, because `write_policy` requires a
workspace-relative target; the identical write inside the test file is not
denied. The control grades the command string, not the process.

**2. There is no evidence record on the execution path.**
`EvidenceBuilder.add_action` and `add_synthesis_result` have no production
caller; `EvidenceBuilder` is constructed only by
`harness/control-plane/publish_policy_artifact.py`, which calls
`add_policy_snapshot` and `export`. No digest field exists anywhere on the
verdict chain: `HarnessCheck`, `Verdict` and `ExecutionResult` all lack one.
INV-13 is **zero of five**. A sandbox digest cannot be added to a record that
does not exist, which is why this plan orders the work as it does.

**3. The classifier graded a rewrite as a gate run, and was opposed to
`CLAUDE.md`.** `ruff` and `eslint` were graded `test_execute` by program name in
every form, so `ruff format .` and `ruff check --fix .` — each of which rewrites
every file it reaches, in place — ran for every role holding `test_execute`.
Reproduced through the real broker as `implementer`: `ruff format .` rewrote
`harness/shared/governance/broker.py`, a path `write_denial_reason` refuses by
name, and the broker returned `SUCCESS`. `write_targets` looks for a redirect,
which an in-place formatter does not present, so the write policy was never
consulted. Closed by DEC-066.

The same table settles the opposite defect.
`python -m ruff check .` and `python -m mypy harness` classify `destructive`,
an action `agent-policy.json` states no role may hold, so the forms `CLAUDE.md`
mandates under DEC-013 cannot execute through the broker. The bare forms it
forbids, `ruff check .` and `mypy harness`, classify `test_execute` and run.
Over a corpus of 36 ordinary developer commands, 13 resolve to an action no
role holds.

**4. Two gates pass on an empty population.** `check_dedup` and
`check_py_compat` both exit 0 against an empty tree, printing
`[PASS] 0 per-stack script(s)` and
`[PASS] 0 file(s) compatible with Python (undeclared)`. `check_traceability`
exits 1 on that input, but by an uncaught `FileNotFoundError` on a missing
config rather than by the DEC-065 population floor; the floor is real and
reached only once a config and spec files exist. The floor is still the
pattern to copy, and the misreading is recorded here so the follow-up does not
enshrine a crash as reference behaviour.

**5. No isolation primitive spans the environments.** Probed directly, the
agent container reports `ENOSYS` for `landlock_create_ruleset`, has no
reachable Docker daemon, and has working user, mount and network namespaces.
GitHub's `ubuntu-latest` is Ubuntu 24.04 on a 6.17 Azure kernel with
passwordless `sudo`, Docker and Podman preinstalled, `bubblewrap` absent, and
unprivileged user namespaces restricted by
`kernel.apparmor_restrict_unprivileged_userns`. Whether Landlock is in the
active LSM list there is undetermined from documentation. A `bool` cannot
express that spread, which is why `sandbox_available` cannot become an
attestation and why the primitive is chosen by measurement here.

## Requirements

- R-AEI-1: The classifier MUST grade a tool by the form it is invoked in
  rather than by its program name, from one table driving both the bare and the
  `python -m` path, so an inspecting form keeps the action it already had, a
  rewrite naming its files is `write` over exactly those paths, and a rewrite
  over a directory, a glob or no operand reaches the unmodelled default because
  it has no enumerable target set for `write_targets` to report.
- R-AEI-2: The share of a committed command corpus resolving to an action no
  role holds MUST be reported against a ceiling and a population floor, both
  read from `governance-policy.json`, so neither an untuned allowlist nor an
  empty corpus can pass.
- R-AEI-3: `check_dedup` and `check_py_compat` MUST exit non-zero when their
  population is empty, against a floor read from `governance-policy.json`.
- R-AEI-4: A governed execution MUST produce an evidence entry through
  `EvidenceBuilder`, whose signing key is injected at broker construction
  rather than read from the environment at export, so the suite needs no
  environment mutation and a keyless broker is a decidable state.
- R-AEI-5: The evidence sink MUST lie outside the agent workspace and outside
  every `protected_paths` pattern, because `VerificationRunner` re-reads the
  enforcement digest around each check and a write matching a protected pattern
  turns every verdict into `enforcement_tampered`.
- R-AEI-6: The evidence entry MUST carry the policy digest, the loop-start
  enforcement baseline as a single digest-of-digests, the backend name and
  version, and a test digest over the resolved verification command and its
  collected node identifiers, giving four of INV-13's five digests.
- R-AEI-7: The enforcement baseline MUST be computed once per loop and cited by
  reference, never recomputed per execution, because `enforcement_digests`
  walks the whole workspace without pruning caches and its protected patterns
  match `__pycache__` bytecode whose digest changes within a single run.
- R-AEI-8: An `ExecutionBackend` protocol MUST accept a single
  `ExecutionRequest` value carrying the command, the workspace root, the
  working directory, the timeout, the output cap, the classified action and the
  capabilities the caller requires, so a backend receives the workspace it must
  confine and can refuse a capability it cannot supply.
- R-AEI-9: `ExecutionResult` and `BackendCapabilities` MUST be defined in the
  protocol module and re-exported from `process_backend`, so the abstraction
  does not import its implementation.
- R-AEI-10: A backend MUST publish `BackendCapabilities` naming filesystem
  isolation, network isolation, process isolation and backend version as
  separate three-state fields, and MUST report what it enforced rather than
  what it requested.
- R-AEI-11: Execution routing MUST be selected by a key in a **new** top-level
  block of `governance-policy.json` whose only legal states are brokered
  execution and refusal, discharging R-AC-12; a new block is required because
  DEC-043 makes an absent key inside an existing block a `PolicyError` for
  every adopter policy that predates it.
- R-AEI-12: A capability probe MUST report the active LSM list, the Landlock
  ABI, the unprivileged-user-namespace restriction state and the reachable
  container runtimes, each as enforced, absent or undetermined, and MUST fail
  only on undetermined, since absence is itself a determination.
- R-AEI-13: An isolation backend MUST confine the filesystem to the request's
  workspace and MUST deny outbound network by default, and MUST treat an absent
  workspace as a precondition failure rather than inheriting a working
  directory.
- R-AEI-14: The isolation backend's policy MUST be compiled in memory from
  `governance-policy.json` and `agent-policy.json` at backend start, and MUST
  NOT be committed as a derived artifact, which `authority_graph.py` already
  refuses on the grounds that stale derived governance state has a security
  consequence.
- R-AEI-15: A capability enforced only by environment variables the child may
  ignore, such as `HTTP_PROXY` or `ALL_PROXY` egress steering, MUST NOT set
  `network_isolation` to enforced.
- R-AEI-16: An escape corpus MUST express each reachable route as an assertion
  that passes in both states: that the route is open on `ProcessBackend`, and
  that it is closed, or the backend returns `BLOCKED`, on the isolation
  backend, so the suite is green at every point in the sequence and INV-2's
  no-unwaived-skip rule is never engaged.
- R-AEI-17: Every network assertion in the corpus MUST target a listener bound
  on an ephemeral loopback port inside the test process, guarded by a positive
  control asserting the test process can reach it, so an absent network cannot
  be read as proof of isolation.
- C-AEI-1: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`,
  and MUST NOT introduce a waiver for an invariant it could enforce instead.
- C-AEI-2: No threshold here MUST be written as a literal; every one is read
  from `governance-policy.json`.
- C-AEI-3: A backend whose probe, policy compilation or capability attestation
  fails MUST return `BLOCKED`, and MUST NOT fall back to the process backend.
- C-AEI-4: This change MUST NOT enable LATS, revive the parked LangGraph
  package, or alter `synthesis.lats_enabled`, which stays governed by INV-15.
- C-AEI-5: Neither `evidence_manifest` nor `execution_backend` MUST import
  `broker`, and both MUST be declared in the `LAYERS` map that
  `test_import_direction.py` reads, so direction is enforced rather than left
  to the acyclicity check.
- C-AEI-6: If the probe reports that no available primitive enforces both
  filesystem and network isolation, the programme MUST close at four of five
  digests with the sandbox digest recorded as unattestable and `CONTRACT.md`
  updated to say so, and MUST NOT record an unenforced capability as enforced.

## INV-13 digest coverage

Stated as a table because the earlier draft claimed five digests from four
requirements and no reviewer could check the arithmetic.

| INV-13 digest | Produced by | Proven by |
|---|---|---|
| policy | R-AEI-6 | AC-5 |
| source | R-AEI-6, R-AEI-7 | AC-5, AC-6 |
| tool-version | R-AEI-6, R-AEI-10 | AC-5, AC-9 |
| test | R-AEI-6 | AC-5 |
| sandbox | R-AEI-13, R-AEI-14 | AC-12, AC-13 |

Phases 1 and 2 reach four of five. The fifth lands with the isolation backend,
or is recorded as unattestable under C-AEI-6.

## Acceptance criteria

- [x] AC-1: `pytest harness/shared/tests/test_tool_forms.py` asserts
      `python -m ruff check` and `python -m mypy` reach an action the
      implementer holds, that an unbounded rewrite reaches the unmodelled
      default, and that `ruff format .` through the real broker returns
      `BLOCKED` leaving a protected file unchanged · stage: `make coverage`
      (R-AEI-1)
- [x] AC-2: `pytest -k test_an_unmodelled_module_is_not_guessed_at` asserts
      an unmodelled `python -m` module is not made executable as a side effect,
      and `test_the_unmodelled_default_is_held_by_no_role` asserts the premise
      every denial here rests on · stage: `make coverage` (R-AEI-1)
- [x] AC-3: `python harness/shared/governance/denial_rate.py` exits non-zero
      above the policy ceiling and exits non-zero when the committed corpus
      holds fewer entries than the policy floor, and dropping the denied
      entries fails on the floor rather than rescuing the run · stage:
      `make validate` (R-AEI-2, C-AEI-2)
- [ ] AC-4: `pytest -k test_gate_refuses_empty_population` asserts
      `check_dedup` and `check_py_compat` exit non-zero on an empty tree, that
      a population one below the policy floor fails, and that a population at
      the floor passes · stage: `make ci` (R-AEI-3)
- [ ] AC-5: `pytest -k test_evidence_entry_digests` monkeypatches
      `enforcement_digests`, `policy_digest` and the backend capability record
      to return sentinels and asserts each sentinel appears verbatim in the
      entry, so a local recomputation cannot satisfy it · stage:
      `make coverage` (R-AEI-6)
- [ ] AC-6: `pytest -k test_baseline_cited_not_recomputed` asserts the walk
      runs once per loop regardless of execution count, and fails if a second
      execution triggers a second walk · stage: `make coverage` (R-AEI-7)
- [ ] AC-7: `pytest -k test_keyless_broker_blocks` asserts a broker
      constructed without a signing key returns `BLOCKED` with a reason naming
      `AGENT_EVIDENCE_KEY`, and `test_evidence_manifest_verifies` asserts an
      exported manifest verifies under HMAC · stage: `make coverage` (R-AEI-4)
- [ ] AC-8: `pytest -k test_verification_with_evidence_verified` runs
      `VerificationRunner.run` against a real broker with evidence enabled and
      asserts `VERIFIED`, a non-empty entry list, and an entry count at or
      below a policy-sourced bound, so an evidence write that trips
      `enforcement_tampered` or a per-command walk both go red · stage:
      `make coverage` (R-AEI-5, R-AEI-7)
- [ ] AC-9: `python -m mypy harness` exits 0 with a module-level
      `_: ExecutionBackend = ProcessBackend()` binding in `process_backend.py`,
      and `pytest -k test_protocol_rejects_wrong_signature` asserts a stub with
      correct attribute names and wrong signatures is rejected · stage:
      `make lint` (R-AEI-8, R-AEI-9)
- [ ] AC-10: `pytest -k test_capabilities_three_state` asserts a backend that
      requested network isolation on a host that could not apply it reports
      `network_isolation` unenforced, driven by an injected probe result
      · stage: `make coverage` (R-AEI-10, R-AEI-15)
- [ ] AC-11: `pytest -k test_routing_block` asserts a policy predating the new
      block still loads, that the block present with its key absent raises
      `PolicyError`, and that a third routing value is refused · stage:
      `make validate` (R-AEI-11, R-AC-12)
- [ ] AC-12: `python harness/shared/governance/capability_probe.py --json`
      prints each field as enforced, absent or undetermined, exits 0 when a
      field is absent, and exits 1 only when one is undetermined · stage:
      `make validate` (R-AEI-12)
- [ ] AC-13: `pytest -k test_isolated_backend_confines` asserts a read and a
      write outside the request workspace both fail inside the backend, and
      that a request carrying no workspace returns `BLOCKED` rather than
      inheriting a directory · stage: `make coverage` (R-AEI-13, C-AEI-3)
- [ ] AC-14: `pytest -k test_sandbox_policy_compiled_in_memory` asserts the
      compiled policy equals a rebuild from the two JSON sources, that no
      derived artifact is committed, and that a mismatch at backend start
      returns `BLOCKED`; recorded with a kill count per the
      `gate-mutation-proof` skill · stage: `make validate` (R-AEI-14, C-AEI-2)
- [ ] AC-15: `pytest -m security -k escape_corpus` asserts each route is open
      on `ProcessBackend` and closed or `BLOCKED` on the isolation backend,
      with every network route targeting a loopback listener behind a positive
      control, and no case skipped · stage: `make coverage` (R-AEI-16,
      R-AEI-17)
- [ ] AC-16: `pytest -k test_backend_failure_blocks` asserts a probe failure, a
      policy-compilation failure and an attestation failure each return
      `BLOCKED`, and that no path reaches `ProcessBackend` afterwards · stage:
      `make coverage` (C-AEI-3)
- [ ] AC-17: `pytest -k test_governance_no_direct_spawn` asserts by AST scan
      that no module under `harness/shared/governance/` except the backends and
      the probe references `subprocess` or `os.exec`, and
      `test_import_direction` asserts the new modules are in `LAYERS` and that
      neither imports `broker` · stage: `make validate` (C-AEI-5, C-AEI-1)
- [ ] AC-18: `python harness/shared/validate_invariants.py --workspace .` exits
      0, and `pytest -k test_lats_disabled` asserts `synthesis.lats_enabled` is
      false · stage: `make validate` (C-AEI-4)
- [ ] AC-19: when the probe reports no primitive enforcing both dimensions,
      `pytest -k test_sandbox_digest_unattestable` asserts the verdict records
      the sandbox digest as unattestable and refuses a claim of INV-13, rather
      than recording an unenforced capability as enforced · stage:
      `make coverage` (C-AEI-6)

## Steps

Ordered so the two live defects ship first and nothing waits on the vendor
question. Each phase is one pull request.

1. Grade tools by invocation form and add the denial-rate metric with its
   committed corpus — produces `harness/shared/governance/tool_forms.py`,
   `denial_rate.py` and `command-corpus.json`; the table is a sibling module
   because `command_actions.py` stood 29 lines below `limits.size_budget_lines`
   (AC-1, AC-2, AC-3). **Landed** as DEC-066.
2. Give the two gates a population floor — consumes
   `traceability.min_discovered_requirement_ids` as the pattern; produces the
   refusal AC-4 checks.
3. Add the evidence entry, its sink and the test digest — consumes the
   loop-start baseline and `write_policy.policy_digest`; produces the record
   AC-5 through AC-8 check. INV-13 reaches four of five here.
4. Extract the `ExecutionBackend` protocol, `ExecutionRequest` and
   `BackendCapabilities`; adapt `ProcessBackend` behind them — touches the four
   construction sites in `mcp_server.py`, `mango_mas_orchestrator.py`,
   `experimental/autonomous_healing.py` and the broker default (AC-9, AC-10,
   AC-17).
5. Add the routing block to `governance-policy.json` and its accessor in
   `policy_loader` — produces the two-state selector AC-11 checks and
   discharges R-AC-12.
6. Run the capability probe on every matrix leg — produces the measurement
   step 7 consumes (AC-12).
7. Record the backend decision under `docs/decisions/` and run
   `make decision-index` — consumes step 6's output; produces the vendor choice
   this spec leaves open, or the C-AEI-6 finding that none qualifies.
8. Implement the isolation backend and the in-memory policy compiler —
   consumes step 7; produces the artifact AC-13, AC-14, AC-16 and AC-19 check.
9. Add the escape corpus and its mutation cases — consumes step 8 (AC-15).

## Files touched

The protected set is large: `protected_paths` contains
`harness/shared/governance/**`, so every module below is protected, as are
`pyproject.toml`, `governance-policy.json`, `validate_policy.py`,
`check_dedup.py`, `check_py_compat.py` and `CONTRACT.md`. The table for each
pull request MUST be regenerated with `make attestation` on that branch rather
than copied from this list, because `make attestation-check` fails closed on a
mismatch in either direction (C-AEI-1).

- `harness/shared/governance/broker.py`, `process_backend.py`,
  `evidence_manifest.py`, `command_actions.py`, `verdict.py`, `__init__.py`
- `harness/shared/governance/execution_backend.py`, `tool_forms.py`,
  `capability_probe.py`, `sandbox_policy.py`, `denial_rate.py`,
  `command-corpus.json` (new)
- `harness/shared/governance-policy.json`, `validate_policy.py`,
  `policy_loader.py`
- `harness/shared/check_dedup.py`, `check_py_compat.py`
- `harness/CONTRACT.md`
- `pyproject.toml` — the corpus fixture and any marker registration
- `harness/shared/tests/**` — not protected
- `docs/decisions/` and its regenerated index

## Invariants touched

- INV-2: engaged by AC-15. The corpus asserts rather than skips, so no waiver
  in `skip-waivers.json` is needed on a host without the primitive.
- INV-7: the evidence entry is what gives a repair attempt an immutable
  evidence ID to point at; this change produces the record, not the loop.
- INV-8: preserved, with a stated exemption. The capability probe and the
  policy compiler run outside the broker because they establish whether a
  broker backend can exist; AC-17 bounds that exemption by AST scan so no other
  governance module spawns a process.
- INV-9: strengthened. The no-fallback branch becomes reachable for three new
  failure modes, each asserted by AC-16.
- INV-10: unaffected. No denial is retried or downgraded.
- INV-13: this is the change that makes it earnable, per the coverage table
  above.
- INV-15: unaffected and asserted so by AC-18.
- INV-17: this document is the plan the gate reads; `make specs` runs
  `validate_plan.py` over it.

## Validation matrix

Stage names are the root vocabulary. `cov`, `types` and `governance` are the
per-stack adopter names defined only in `harness/node/Makefile` and
`harness/jvm/Makefile`; `test_ci_gate_coverage.py` holds the mapping to
`coverage`, `lint` and `validate`, and an earlier draft of this spec named the
adopter forms in twelve criteria that could not have run.

- `make ci` — the full gate on the primary leg; `make ci-python` on the
  remaining interpreters
- `make coverage` — pytest and the coverage floor at `coverage.lines` and
  `coverage.per_file`
- `make lint` — ruff and mypy, with `make lint-cold` for the cold-cache leg
  whose tail DEC-024 requires in the pull request
- `make validate` — the governance validators, the routing block, the compiled
  policy, the denial rate and the capability probe (R-AEI-2, R-AEI-11,
  R-AEI-12, R-AEI-14)
- `make specs` — `validate_plan.py` over this document (INV-17)
- `make validate` is the probe's stage because it is the one target reached by
  both `ci` and `ci-python`, so R-AEI-12 runs on every matrix leg
- traceability stays bounded by
  `traceability.min_discovered_requirement_ids` and
  `traceability.max_uncited_contract_requirement_ids`

## Backward compatibility

`ExecutionBroker(sandbox_available=...)` keeps its keyword and meaning for
callers passing an explicit bool; the value becomes one field of the capability
record. `ProcessBackend` keeps its behaviour and its export from
`governance.broker`, and gains an `ExecutionRequest` adapter rather than a
changed signature, so the three existing construction sites are unchanged at
step 4. `ExecutionResult` moves to the protocol module and is re-exported from
`process_backend`, so every existing import path resolves. `EvidenceBuilder`
gains a constructor-injected key, which its signature already accepts, and a
caller. The routing key lands in a new top-level block so a policy predating it
loads unchanged under DEC-043, which a key added to an existing block would
not.

## Open questions

- Which isolation primitive the backend uses is unanswered here by design.
  Step 6 measures and step 7 records. Every named candidate carries a known
  cost: Anthropic's sandbox runtime needs the AppArmor userns restriction
  relaxed with root and steers egress through proxy environment variables,
  which R-AEI-15 refuses to attest; NVIDIA OpenShell runs standalone on a
  Docker or Podman driver with no cluster, but has not been shown running
  inside GitHub Actions; a namespace-only backend is the sole candidate that
  works in both this agent container and CI. C-AEI-6 defines the outcome if
  none qualifies, so a probe returning "nothing works" is a completed
  measurement rather than a failed programme.
- Publishing generated baseline figures instead of transcribed ones is DEC-024
  hygiene that advances no INV-13 digest, and it was cut from this spec after
  review. It needs its own spec, because it is the only reason this change
  would have touched `README.md`, the `Makefile` and workflow artifact
  plumbing.
- Whether evidence signing moves from symmetric HMAC to an asymmetric
  attestation is out of scope. Any party who can verify a manifest today can
  forge one, which matters for an external auditor and not for this change, so
  the enterprise-audit claim is not made here.
- Whether R-AEI-3 generalises into an invariant covering every gate in
  `ci_required_targets` is left to a follow-up, once the two named gates have
  floors. `check_traceability`'s floor is the model, though its behaviour on a
  configless tree is a crash rather than a refusal and should be fixed there.
