# Spec: Egress Floor (EGF)

> **Change:** `add-egress-floor`
> **Version:** 1.0.0
> **Authors:** maintainer · reviewer
> **Status:** APPROVED

---

## Problem Statement

Absence of network egress is currently arranged rather than proven. No test
fails when a connection is attempted, the product path cannot reach the
transport seam that would make an offline run possible, and the client defaults
to a vendor endpoint when nothing says otherwise. A guard that has never been
shown capable of failing is not evidence.

**Evidence:** `nemotron-client.ts` defaults `baseUrl` to the vendor endpoint and
exposes `customFetch?: typeof fetch` as its second constructor parameter, which
`harness/node/tests/ai/unit/nemotron-transport.test.ts` injects; `cli.ts`
constructs the client with no such argument, so the product path always resolves
to the global `fetch`. No offline environment variable, null provider, or
fixture player exists. The pattern commonly cited as the remedy does not supply
one either: in `ianshank/Agents`, `--offline` selects a single client while
`configure_tracing(config.phoenix)` runs regardless, `addopts` carries no socket
flag, `pytest-socket` is absent from the `dev` extra, `tests/conftest.py` patches
no sockets, and no workflow declares an egress policy.

---

## Requirements

- R-EGF-1: An offline run MUST be proven by an executable assertion that fails
  when a connection is attempted, and MUST NOT rest on dependency absence, lazy
  imports, configuration convention, or reviewer inspection.
- R-EGF-2: Each guard MUST be shown capable of failing by a mutation check that
  connects to a loopback listener on an ephemeral local port; a negative control
  MUST NOT require outbound reachability.
- R-EGF-3: The assertion MUST cover both language runtimes independently, because
  a Python socket guard cannot observe a request issued by the Node process that
  carries the reasoning path.
- R-EGF-4: The assertion MUST cover a complete planner, reasoner, and verifier
  pass, not a single client call in isolation.
- R-EGF-5: When no offline mode is declared, the client MUST refuse to construct
  a networked transport; an unset mode MUST NOT resolve to the vendor endpoint.
- R-EGF-6: A test requiring a socket MUST declare that requirement at the test,
  and MUST NOT be enabled by a global exemption.
- C-EGF-1: This change MUST NOT commit into any repository currently under claim
  review.
- C-EGF-2: This change MUST NOT be represented as governing run-time disclosure;
  it establishes an offline floor only.

---

## Acceptance Criteria

- [ ] **AC-EGF-1 (non-success):** With the Python socket guard active, a
  deliberate connection to a loopback listener on an ephemeral port raises; the
  same connection succeeds when the guard is removed, proving the guard detects
  connections. (R-EGF-1, R-EGF-2)
  _Verified by:_ `pytest -k test_python_socket_guard_blocks_loopback_and_can_fail` · stage: `make test`

- [ ] **AC-EGF-2 (non-success):** With the Node dispatcher guard active, an
  un-mocked request throws rather than dialling out, and a deliberate loopback
  request under the guard throws as well. (R-EGF-2, R-EGF-3)
  _Verified by:_ `pytest -k test_node_dispatcher_guard_blocks_unmocked_requests` · stage: `make test`

- [ ] **AC-EGF-3 (non-success):** Disabling either guard independently causes the
  full-pass assertion to fail, so neither runtime's coverage can mask a gap in the
  other. (R-EGF-3)
  _Verified by:_ `pytest -k test_disabling_either_guard_fails_the_full_pass` · stage: `make ci`

- [ ] **AC-EGF-4:** A complete planner, reasoner, and verifier pass runs to
  completion in offline mode with both guards active and no connection attempted.
  (R-EGF-4)
  _Verified by:_ `pytest -k test_full_pass_completes_offline_with_no_connection` · stage: `make ci`

- [ ] **AC-EGF-5 (non-success):** Constructing the client with no offline mode
  declared is denied, and the denial names the missing declaration rather than
  falling back to the vendor endpoint. (R-EGF-5)
  _Verified by:_ `pytest -k test_unset_mode_refuses_networked_transport` · stage: `make test`

- [ ] **AC-EGF-6:** The product path in `cli.ts` reaches the injectable transport
  seam, so an offline run is achievable without editing source. (R-EGF-5)
  _Verified by:_ `pytest -k test_cli_reaches_the_transport_seam` · stage: `make test`

- [ ] **AC-EGF-7 (non-success):** No global socket exemption exists; a test
  needing a socket carries its own declaration, and adding a blanket exemption
  fails the check. (R-EGF-6)
  _Verified by:_ `pytest -k test_no_global_socket_exemption_exists` · stage: `make test`

- [ ] **AC-EGF-8:** The offline CI job reports no blocked connections, and a
  branch that deliberately egresses reports at least one, so the policy is shown
  to be measuring rather than silent. (R-EGF-1)
  _Verified by:_ `pytest -k test_offline_job_reports_blocked_connection_count` · stage: `make ci`

- [ ] **AC-EGF-9 (non-success):** Every file this change adds or modifies resolves
  inside this repository; a change set naming a path in a repository under claim
  review fails the check. (C-EGF-1)
  _Verified by:_ `pytest -k test_change_set_touches_no_repository_under_review` · stage: `make validate`

- [ ] **AC-EGF-10 (non-success):** This change package states, in a section a
  reader cannot miss, that it does not govern run-time disclosure; removing that
  statement fails the check. (C-EGF-2)
  _Verified by:_ `pytest -k test_package_disclaims_run_time_coverage` · stage: `make test`

---

## Invariants Touched

- Mango INV-13 — digest-complete verified results, which `harness/CONTRACT.md`
  records as not currently satisfiable because the process backend confines
  neither the filesystem nor the network (DEC-010). This change supplies the
  network half of that gap independently and does not assume INV-13 holds.
- Mango INV-9 — a candidate receives a deterministic policy verdict before
  execution, and an unavailable backend returns a denial rather than a host
  fallback. R-EGF-5 extends the same fail-closed posture to transport
  construction. `harness/shared/tests/test_invariant_liveness.py` classifies
  INV-9 under `INVARIANT_MECHANISMS`, so it is enforced by a reachable symbol
  rather than dormant, which is why this change may rely on it.
- Mango INV-16 — the cognitive plane proposes, the harness disposes. Unaffected;
  nothing here lets a model select a transport.

---

## Decisions

- **DEC-EGF-001 (resolved):** The negative control connects to a loopback
  listener, never an external endpoint. A live-endpoint control cannot run in the
  job whose egress is blocked, and exempting it would defeat the control being
  certified.
- **DEC-EGF-002 (resolved):** Both runtimes are guarded separately. A single
  cross-language assertion was rejected because the mechanisms differ and a shared
  abstraction would hide which side actually held.
- **DEC-EGF-003 (resolved):** An unset offline mode fails closed. Defaulting to a
  networked transport when nothing is declared reproduces the current defect with
  extra configuration.
- **DEC-EGF-004 (resolved):** The `Null*` seam from `ianshank/Agents` is borrowed
  for its shape and not for its guarantees. Its `--offline` selects one client and
  the repository carries no socket-level or CI-level egress assertion, so this is
  construction rather than a port. An earlier reading to the contrary was wrong
  and is corrected here.
- **DEC-EGF-005 (resolved):** No commit lands in `ianshank/Agents` under this
  change while its public history is in front of counsel.

---

## Non-Success Criteria (what this change rejects)

- An offline claim justified by dependency absence, lazy imports, or code review
  rather than an executable assertion is rejected (AC-EGF-1, DEC-EGF-004).
- A negative control requiring outbound reachability is rejected as unsatisfiable
  in the job it certifies (DEC-EGF-001).
- A guard covering one runtime while the reasoning path runs in the other is
  rejected (AC-EGF-3, DEC-EGF-002).
- An assertion covering a single client call rather than a full pass is rejected
  (R-EGF-4).
- A default that resolves an unset mode to a networked transport is rejected
  (AC-EGF-5, DEC-EGF-003).
- A global socket exemption is rejected; exemptions are per-test and visible
  (AC-EGF-7).
- Any representation of this change as governing run-time disclosure is rejected
  (C-EGF-2).

---

## Validation Matrix

| Stage | Make Target | Pass Criteria |
|---|---|---|
| Unit | `make test` | AC-EGF-1, AC-EGF-2, AC-EGF-5, AC-EGF-6, AC-EGF-7 |
| Full | `make ci` | AC-EGF-3, AC-EGF-4, AC-EGF-8 |
| Governance | `make test-governance` | No regression in broker or write-gate behaviour |
| Pre-submission | `make pre-pr` | All of the above green |
