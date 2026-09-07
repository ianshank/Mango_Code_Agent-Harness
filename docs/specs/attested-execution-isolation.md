# Spec: attested execution isolation

Spec class: program-plan

> Closes INV-13 by building the evidence record first and the sandbox second.
> Supersedes no decision; consumes DEC-010, DEC-013, DEC-024, DEC-052, DEC-065.

## Problem statement

INV-13 requires a "verified" result to carry policy, test, sandbox, source and
tool-version digests. `harness/CONTRACT.md` records it as **not currently
satisfiable**, and `harness/shared/agent-policy.json` names the reason: the
process backend contains but does not isolate.

Three pieces of evidence gathered against `HEAD` on this branch sharpen that
into a plan, and each is reproducible.

**1. The gap is reachable, not theoretical.** Driving the real
`ExecutionBroker` as `implementer`, writing `test_payload.py` into the pinned
workspace and running `pytest -q -s test_payload.py` returns broker status
`SUCCESS` classified `test_execute`, while the payload reads a host file
outside the workspace, writes a file outside the workspace, and opens a TCP
connection to a public address. A direct `printf x > /abs/path` is denied by
the write policy; moving the identical write inside the test file bypasses that
denial entirely. The control grades the command string, not the process.

**2. There is no evidence record on the execution path to attach a digest to.**
`EvidenceBuilder.add_action` and `add_synthesis_result` have no production
caller anywhere; `EvidenceBuilder` is constructed only by
`harness/control-plane/publish_policy_artifact.py`. The verdict object
`HarnessCheck` carries `target`, `command`, `status`, `exit_code`, `reason`,
`probe_ok`, `latency_ms` and `tampered_files`, and no digest of any kind. INV-13
is therefore **zero of five**, not "four of five plus a sandbox". Adding a
sandbox digest to a record that does not exist is not a change that can land.

**3. The environment does not offer one universal primitive.** Probed
directly: this agent container reports `landlock_create_ruleset` → `ENOSYS`,
no reachable Docker daemon, and working user, mount and network namespaces.
GitHub's `ubuntu-latest` is Ubuntu 24.04 on kernel `6.17.0-*-azure` with
passwordless `sudo`, Docker and Podman preinstalled, `bubblewrap` absent, and
unprivileged user namespaces restricted by default through
`kernel.apparmor_restrict_unprivileged_userns`. Whether Landlock is in the
active LSM list on that image is undetermined from documentation and must be
probed. A `bool` cannot express that spread, which is why
`ExecutionBroker(sandbox_available=...)` cannot become an attestation.

Two defects found while gathering the above are folded in because they are
cheap and they distort the record:

- `python -m ruff check .` and `python -m mypy harness` classify to
  `destructive`, an action no role holds, so the invocation form `CLAUDE.md`
  mandates under DEC-013 cannot execute through the broker. Only `pytest`,
  `unittest`, `py_compile`, `doctest` and `pip install` are modelled after
  `python -m`. Over a corpus of 36 ordinary developer commands, 13 resolve to
  an action no role holds.
- `check_dedup` and `check_py_compat` both exit 0 against an empty tree,
  printing `[PASS] 0 per-stack script(s)` and
  `[PASS] 0 file(s) compatible with Python (undeclared)`. `check_traceability`
  exits 1 on the same input, because DEC-065 gave it a population floor. The
  floor is the pattern; two gates lack it.

## Requirements

- R-AEI-1: The published test, coverage and requirement-ID figures MUST be
  generated from a CI artifact rather than transcribed, so a stale count cannot
  outlive the run that produced it (DEC-024).
- R-AEI-2: A governed execution MUST produce an evidence entry recording the
  command's classified action, the broker status, the backend identity and the
  digests available at that point, through `EvidenceBuilder` on the execution
  path rather than in the control plane alone.
- R-AEI-3: The evidence entry MUST carry the enforcement digest, the active
  policy digest and the backend name and version, sourced from
  `enforcement_digest.enforcement_digests`, `write_policy.policy_digest` and the
  backend's own capability record rather than recomputed locally.
- R-AEI-4: An `ExecutionBackend` protocol MUST define the seam the broker
  executes through, and `ProcessBackend` MUST satisfy it with no behavioural
  change to any existing caller.
- R-AEI-5: A backend MUST publish a structured `BackendCapabilities` record
  naming filesystem isolation, network isolation, process isolation and backend
  version as separate fields, so each is separately attestable and separately
  refusable.
- R-AEI-6: Execution routing MUST be selected by a key in
  `governance-policy.json` whose only legal states are brokered execution and
  refusal, discharging R-AC-12 in `docs/specs/agent-containment.md`, which is
  cited by `broker.py` today but backed by no policy key.
- R-AEI-7: A capability probe MUST report, for the host it runs on, the active
  LSM list, the Landlock ABI, the unprivileged-user-namespace restriction state,
  and which container runtimes are reachable, and MUST run on every CI matrix
  leg so the vendor decision is made from measurement.
- R-AEI-8: An isolation backend MUST confine the filesystem to the pinned
  workspace and MUST deny outbound network by default, and MUST report the
  capabilities it actually enforced rather than the ones it requested.
- R-AEI-9: The isolation backend's policy MUST be compiled from
  `governance-policy.json` and `agent-policy.json` at build time, so no second
  hand-maintained security policy exists to drift.
- R-AEI-10: A capability that is enforced only by environment variables the
  child process may ignore, such as `HTTP_PROXY` or `ALL_PROXY` egress
  steering, MUST NOT set the network-isolation field to enforced.
- R-AEI-11: An escape corpus MUST express each reachable route from the problem
  statement as a test that fails while the route is open, covering
  out-of-workspace read, out-of-workspace write, outbound connection, and the
  same three reached indirectly through `pytest`.
- R-AEI-12: The classifier MUST model the interpreter-invoked forms `CLAUDE.md`
  mandates under DEC-013, so a command the contributor guide instructs an agent
  to run does not resolve to an action no role holds.
- R-AEI-13: The share of a declared command corpus that resolves to an action no
  role holds MUST be reported as a metric with a ceiling read from
  `governance-policy.json`, so the allowlist is tuned against evidence.
- R-AEI-14: Every gate named in `ci_required_targets` MUST fail rather than pass
  when its population is empty, and MUST have a case proving it.
- C-AEI-1: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`,
  and MUST NOT introduce a waiver for an invariant it could enforce instead.
- C-AEI-2: No threshold here MUST be written as a literal; every one is read
  from `governance-policy.json`.
- C-AEI-3: A backend whose probe, policy compilation or capability attestation
  fails MUST return `BLOCKED`, and MUST NOT fall back to the process backend.
- C-AEI-4: This change MUST NOT enable LATS, revive the parked LangGraph
  package, or alter `synthesis.lats_enabled`, which stays governed by INV-15.

## Acceptance criteria

- [ ] AC-1: `make baseline-figures` writes counts from a CI artifact and
      `pytest -k test_readme_figures_match_artifact` fails when `README.md`
      states a figure the artifact contradicts · stage: `make specs` (R-AEI-1)
- [ ] AC-2: `pytest -k test_broker_emits_evidence_entry` asserts one entry per
      governed execution carrying action, status and backend identity, and
      `pytest -k test_evidence_entry_absent_is_blocked` asserts a run that
      cannot record evidence returns `BLOCKED` · stage: `make cov` (R-AEI-2)
- [ ] AC-3: `pytest -k test_evidence_digests_sourced` asserts the entry's
      enforcement, policy and backend-version digests equal the values the
      existing helpers return, and fails when any is recomputed locally
      · stage: `make cov` (R-AEI-3)
- [ ] AC-4: `pytest -k test_process_backend_satisfies_protocol` typechecks
      `ProcessBackend` against `ExecutionBackend`, and `python -m mypy harness`
      exits 0 · stage: `make types` (R-AEI-4)
- [ ] AC-5: `pytest -k test_backend_capabilities_fields` asserts the four
      fields are present and independently settable, and
      `test_capabilities_boolean_rejected` asserts a bare `bool` is refused
      where a capability record is required · stage: `make cov` (R-AEI-5)
- [ ] AC-6: `pytest -k test_routing_key_two_states` asserts the policy key
      accepts brokered execution and refusal, and denies any third value with a
      non-zero exit · stage: `make governance` (R-AEI-6, R-AC-12)
- [ ] AC-7: `python harness/shared/governance/capability_probe.py --json` prints
      the LSM list, Landlock ABI, userns restriction state and reachable
      runtimes, and exits 1 when it cannot determine one of them rather than
      reporting a default · stage: `make ci` (R-AEI-7)
- [ ] AC-8: `pytest -k test_isolated_backend_confines_workspace` asserts a read
      and a write outside the pinned workspace both fail inside the backend,
      and `test_isolated_backend_denies_egress` asserts an outbound connection
      is refused · stage: `make cov` (R-AEI-8)
- [ ] AC-9: `pytest -k test_sandbox_policy_is_compiled` asserts the compiled
      policy is byte-identical to a rebuild from the two JSON sources, and goes
      red when a key is edited in the compiled artifact alone · stage:
      `make governance` (R-AEI-9, C-AEI-2)
- [ ] AC-10: `pytest -k test_proxy_egress_not_attested` asserts a backend whose
      egress control is environment-variable steering reports network isolation
      as unenforced, and that a verdict claiming INV-13 on it is refused
      · stage: `make cov` (R-AEI-10)
- [ ] AC-11: `pytest -m escape_corpus` fails on the current `ProcessBackend` for
      all six routes and passes on the isolation backend, and each route has a
      mutation case per the `gate-mutation-proof` skill · stage: `make cov`
      (R-AEI-11)
- [ ] AC-12: `pytest -k test_dec013_forms_are_modelled` asserts
      `python -m ruff` and `python -m mypy` classify to an action the
      implementer role holds, and that `python -c` still resolves to the
      unmodelled default · stage: `make cov` (R-AEI-12)
- [ ] AC-13: `python harness/shared/governance/denial_rate.py` reports the share
      of the declared corpus resolving to an unheld action and exits non-zero
      above the policy ceiling · stage: `make governance` (R-AEI-13)
- [ ] AC-14: `pytest -k test_gate_refuses_empty_population` asserts
      `check_dedup` and `check_py_compat` exit non-zero against an empty tree,
      where both exit 0 today · stage: `make ci` (R-AEI-14)
- [ ] AC-15: `python harness/shared/validate_invariants.py --workspace .` exits
      0 and reports no invariant downgraded, and
      `pytest -k test_lats_disabled` asserts `synthesis.lats_enabled` is still
      false · stage: `make validate` (C-AEI-1, C-AEI-4)
- [ ] AC-16: `pytest -k test_backend_failure_blocks` asserts that a probe
      failure, a policy-compilation failure and an attestation failure each
      return `BLOCKED`, and that no path reaches `ProcessBackend` afterwards
      · stage: `make cov` (C-AEI-3)

## Steps

1. Generate the baseline figures from a CI artifact — produces
   `docs/reports/baseline-figures.json`; consumes the coverage and collection
   output of the `3.10` matrix leg (AC-1).
2. Add the evidence entry to the execution path — consumes
   `enforcement_digest.enforcement_digests` and `write_policy.policy_digest`;
   produces the entry asserted by AC-2 and AC-3.
3. Extract the `ExecutionBackend` protocol and `BackendCapabilities`, adapting
   `ProcessBackend` behind it — produces the seam AC-4 and AC-5 check; touches
   the four construction sites in `mcp_server.py`,
   `mango_mas_orchestrator.py`, `experimental/autonomous_healing.py` and the
   broker default.
4. Add the routing key to `governance-policy.json` — produces the two-state
   selector AC-6 checks and discharges R-AC-12.
5. Run the capability probe on every matrix leg — produces the measurement the
   backend decision record consumes (AC-7).
6. Record the backend decision as a new entry under `docs/decisions/` — consumes
   step 5's output; produces the vendor choice this spec deliberately leaves
   open.
7. Implement the isolation backend and the policy compiler — consumes the
   decision record and the two JSON policy sources; produces the artifact AC-8,
   AC-9 and AC-10 check.
8. Add the escape corpus and its mutation cases — consumes step 7 (AC-11).
9. Model the DEC-013 invocation forms and add the denial-rate metric — produces
   the report AC-12 and AC-13 check.
10. Give `check_dedup` and `check_py_compat` a population floor — produces the
    refusal AC-14 checks.

## Files touched

- `harness/shared/governance/broker.py`
- `harness/shared/governance/process_backend.py`
- `harness/shared/governance/execution_backend.py` (new)
- `harness/shared/governance/capability_probe.py` (new)
- `harness/shared/governance/sandbox_policy.py` (new)
- `harness/shared/governance/denial_rate.py` (new)
- `harness/shared/governance/evidence_manifest.py`
- `harness/shared/governance/command_actions.py`
- `harness/shared/governance-policy.json` — **protected**, needs `infra-reviewed`
- `harness/shared/check_dedup.py` — **protected**, needs `infra-reviewed`
- `harness/shared/check_py_compat.py` — **protected**, needs `infra-reviewed`
- `harness/CONTRACT.md` — **protected**, needs `infra-reviewed`
- `.github/workflows/python-package.yml` — **protected**, needs `infra-reviewed`
- `README.md`
- `docs/decisions/` (new entry, from step 6)

## Invariants touched

- INV-8: preserved. The isolation backend is reached through `ExecutionBroker`
  and adds no second execution path; AC-4 pins the seam.
- INV-9: strengthened. The no-fallback branch becomes reachable for three new
  failure modes, each asserted by AC-16.
- INV-10: unaffected. No denial is retried or downgraded by this change.
- INV-13: this is the change that makes it earnable. It moves from zero of five
  digests to three at step 2, and to five once the isolation backend attests
  its own identity at step 7.
- INV-15: unaffected and asserted so, by AC-15. LATS stays disabled.
- INV-17: this document is the plan the gate reads; `make specs` runs
  `validate_plan.py` over it.

## Validation matrix

- `make ci` — ruff, mypy, pytest, coverage at or above `coverage.lines`,
  `check-dedup` and `validate_invariants`
- `make lint-cold` — the cold-cache lint leg, tail pasted into the PR per
  DEC-024
- `make governance` — the routing key, compiled-policy and denial-rate gates
  (R-AEI-6, R-AEI-9, R-AEI-13)
- `make specs` — `validate_plan.py` over this document (INV-17)
- coverage target: `coverage.lines` and `coverage.per_file` from
  `governance-policy.json`; traceability bounded by
  `traceability.min_discovered_requirement_ids` and
  `traceability.max_uncited_contract_requirement_ids`
- the capability probe (R-AEI-7) runs on each leg of the `python-version`
  matrix, so a backend that works on one interpreter and not another is caught
  before the decision record is written

## Backward compatibility

`ExecutionBroker(sandbox_available=...)` keeps its keyword and its meaning for
callers that pass an explicit bool; the value becomes one field of the
capability record rather than the whole answer, and callers passing nothing
still probe. `ProcessBackend` stays exported from `governance.broker` and keeps
its current behaviour, so the three existing construction sites are unchanged at
step 3. `EvidenceBuilder` gains a caller, not a new signature. The routing key
is additive with a default equal to today's behaviour, so a policy file that
predates it still loads.

## Open questions

- Which isolation primitive the backend uses is deliberately unanswered here.
  Step 5 measures and step 6 records it. Documentation does not settle whether
  Landlock is in the active LSM list on GitHub's Ubuntu 24.04 image, Docker and
  Podman are preinstalled there while `bubblewrap` is not, and this agent
  container reports `ENOSYS` for Landlock with no reachable Docker daemon. The
  candidates carry known costs: Anthropic's sandbox runtime needs the AppArmor
  userns restriction relaxed with root and filters egress through proxy
  environment variables, which R-AEI-10 refuses to attest; NVIDIA OpenShell
  runs standalone on a Docker or Podman driver with no cluster, but has not
  been shown running inside GitHub Actions.
- Whether evidence signing moves from symmetric HMAC to an asymmetric
  attestation is out of scope and belongs in its own spec. Any party that can
  verify a manifest today can also forge one, which matters for an external
  auditor and not for this change.
- Whether R-AEI-14 generalises into a new invariant covering every protected
  gate is left to a follow-up, once the two named gates have floors.
