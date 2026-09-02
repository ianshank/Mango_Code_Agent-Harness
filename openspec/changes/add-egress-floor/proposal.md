# Change: Add Egress Floor (EGF)

> **Status: proposed.** Scoped to this repository only. No legal precondition,
> and deliberately no commits into any repository currently under claim review.

## Why

This harness cannot currently demonstrate that a run made no network call. It
can be configured not to make one, and its tests can inject a fake transport,
but nothing fails when a connection is attempted. For a harness whose reasoning
step sends source and specification text to a vendor endpoint, absence of egress
is a property worth proving rather than arranging.

**Evidence:** `harness/node/src/ai/nemotron/nemotron-client.ts` sets
`DEFAULT_NEMOTRON_CONFIG.baseUrl` to the vendor endpoint, and its constructor
signature is `constructor(customConfig: Partial<NemotronConfig> = {}, customFetch?:
typeof fetch | undefined)` — a real injectable transport seam, already exercised
by `harness/node/tests/ai/unit/nemotron-transport.test.ts`. But
`harness/node/src/ai/nemotron/cli.ts` constructs
`new NemotronClient(timeoutMs ? { timeoutMs } : {})` with no second argument, so
the product path always resolves to the global `fetch`. There is no
`NEMOTRON_OFFLINE`, no null provider, and no recorded-fixture player: the seam is
reachable from code and not from the CLI.

**The pattern most likely to be copied here does not do what it appears to.**
`ianshank/Agents` is often cited as the reference for this problem, and its
`Null*` client seam is genuinely worth copying for its shape — an ABC with a
recording null double, a guarded `try`/`except ImportError` inside the factory
rather than at module scope. But its `--offline` flag selects the Langfuse client
and nothing else; `configure_tracing(config.phoenix)` runs before and regardless
of it. Its `pyproject.toml` sets `addopts = "-q"` with no `--disable-socket`,
`pytest-socket` is absent from its `dev` extra, its `tests/conftest.py` patches no
sockets, and no workflow declares a blocking egress policy. Its
`architecture.yaml` uses "airgap" to mean an import-graph boundary, not a network
one. Zero-network there is achieved by dependency exclusion and job segregation,
enforced by comments. There is no egress assertion to port; this is construction.

**The negative control has to work inside the control.** A test that proves an
egress guard can fail must not require reaching the internet, because the CI job
being certified is the one with egress blocked. Connecting to a loopback listener
on an ephemeral port exercises the socket guard exactly as an outbound call would,
and is compatible with a deny-all egress policy.

## What Changes

- Add a Python socket floor: `pytest-socket` in the test extra, sockets disabled
  by default in `addopts`, so an attempted connection fails the test rather than
  succeeding quietly.
- Add a TypeScript socket floor: install an `undici` mock dispatcher with net
  connect disabled for the offline suite, so an un-mocked request throws. A Python
  socket guard cannot observe a `fetch` in a Node process, and the reasoning path
  this change exists to cover is the Node one.
- Wire a product-level offline mode from `cli.ts` through the existing
  `customFetch` seam, with an explicit fail-closed default: when the mode is
  unset, the client refuses to construct a networked transport rather than
  defaulting to one.
- Add a mutation check for each guard: a deliberate connection to a loopback
  listener raises under the guard, proving the assertion is capable of failing.
- Add a blocking egress policy to the offline CI job and keep every networked job
  in a separately triggered workflow.

## Non-Goals

- **No commits into `ianshank/Agents`.** That repository's public history is
  concurrently in front of counsel for an anticipation analysis; adding to an
  artifact under claim review, mid-review, is a decision to be taken explicitly
  rather than as a side effect of a test-infrastructure change. Its socket floor
  is deferred to its own package.
- **No live-endpoint negative control.** A test requiring real egress cannot run
  in the job whose egress is blocked, and exempting it would punch a hole in the
  control being certified.
- **No claim that this covers run-time disclosure.** This change proves absence
  of egress in an offline mode. What governs a run that must reach a model is a
  separate question and is not answered here.
- **No self-hosted model as a prerequisite.** Serving a large reasoner locally is
  a capacity question, not an egress-proof question, and the two are decoupled by
  this change.

## Affected Capabilities

- `egress-floor`
