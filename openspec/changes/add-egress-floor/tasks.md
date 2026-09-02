# Milestones

## Milestone 1 — Python socket floor  [DONE]

- Add `pytest-socket` to the test extra and disable sockets by default in
  `addopts`, so a connection attempt fails rather than succeeding quietly.
- Add the loopback mutation check: a deliberate connection to a listener on an
  ephemeral local port raises under the guard. This proves the guard detects
  connections without requiring any outbound reachability.
- Exempt nothing. A test that genuinely needs a socket declares it per-test, and
  the declaration is visible in the test rather than in global configuration.

- **Gate:** `make test` green with sockets disabled; the mutation check fails when
  the guard is removed.

## Milestone 2 — TypeScript socket floor  [DONE]

The reasoning path this change exists to cover runs in Node. A Python guard
cannot see it.

- Install a mock dispatcher with net connect disabled for the offline suite, so
  an un-mocked request throws rather than dialling out.
- Add the loopback mutation check on this side too: a deliberate request under
  the guard throws, proving the assertion can fail.

- **Gate:** `make test` green; the Node mutation check fails when the dispatcher
  is not installed.

## Milestone 3 — Product-level offline mode  [DONE]

- Thread an offline mode from `cli.ts` into the existing `customFetch` constructor
  seam, which `harness/node/tests/ai/unit/nemotron-transport.test.ts` already
  exercises but no product path reaches.
- Default fail-closed: when the mode is unset, refuse to construct a networked
  transport. An absent flag must not resolve to the vendor endpoint.
- Follow the null-double shape worth borrowing: a narrow interface, a recording
  null implementation, and a guarded import inside the factory rather than at
  module scope.

- **Gate:** `make test` green; constructing the client with no mode set is denied
  and the denial names the missing declaration.

## Milestone 4 — Full-pass assertion  [PARTIAL]

- Assert the negative across a complete planner, reasoner, and verifier pass in
  offline mode, not a single client call: the pass completes and no connection is
  attempted on either language side.
- Keep the two guards independent so a gap on one side cannot be masked by the
  other.

- **Gate:** `make ci` green; the full-pass assertion fails when either guard is
  disabled.

## Milestone 5 — CI egress policy  [TODO]

- Add a blocking egress policy to the offline job, and keep every job that needs
  network in a separately triggered workflow.
- Record the blocked-connection count for the offline job as an artifact, so a
  regression shows as a number rather than a silence.

- **Gate:** `make ci` green; the offline job reports no blocked connections and a
  deliberately egressing branch reports at least one.

---

## Landed

- **M1.** `pytest-socket==0.7.0` declared in `requirements-dev.txt`;
  `--disable-socket` added to `addopts` in `pyproject.toml`. Ten tests in
  `harness/shared/tests/regression/test_api_server_regression.py` genuinely need
  a socket (FastAPI's `TestClient` drives the app over loopback) and now carry a
  class-level `@pytest.mark.enable_socket` with the reason stated inline —
  declared per test, never a global allow-list (R-EGF-6).
  `harness/shared/tests/test_egress_floor.py` adds four tests: the guard is
  active, a deliberate **loopback** connect is refused (the mutation check, valid
  under a deny-all egress policy), the marker can turn it off per test, and
  `addopts` still carries the floor with no `--allow-hosts`/`--enable-socket`
  re-opening it.

- **M2 + M3.** `nemotron-client.ts` gains `NEMOTRON_MODE` (`online` | `offline`),
  `NemotronEgressRefused`, and `resolveTransport()`. `doFetch` no longer resolves
  `globalThis.fetch` directly. The rule: an injected transport is always honoured
  (supplying one IS the declaration); a `globalThis.fetch` that is no longer the
  pristine module-load reference is a test double and likewise honoured; only the
  genuine vendor path requires `NEMOTRON_MODE=online`. **Unset refuses**, naming
  the missing declaration rather than silently reaching the vendor endpoint
  (R-EGF-5, DEC-EGF-003). `cli.ts` gains `--offline` / `--online`.
  `tests/ai/unit/nemotron-egress-floor.test.ts` adds 7 tests including a mutation
  check proving the refusal is conditional rather than vacuous.

  Deviation from the package: `undici`'s `MockAgent` is **not** used. It is not
  importable in this workspace, and all egress here goes through `fetch`, so the
  pristine-reference check covers the same ground without adding a dependency.

- **M4 (partial).** Both runtimes are guarded and each is proven capable of
  failing, but the single end-to-end planner→reasoner→verifier pass asserting
  zero connections across both at once is not yet written.

- **M5.** Not started: no `harden-runner` egress policy in CI yet.
