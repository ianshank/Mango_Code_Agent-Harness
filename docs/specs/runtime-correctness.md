# Spec: runtime-correctness

> PR A of the v3 remediation program. Touches **no** protected path and
> therefore needs no `infra-reviewed` label; the gate, lint and agent-surface
> work that does is deliberately deferred to PRs B and C so each attestation
> answers one reviewable question.

## Problem statement

Six defects reached `main` in the runtime path (the Nemotron bridge, the MAS
orchestrator, and the FastAPI server). Evidence: each is reproduced by a test
under `harness/shared/tests/regression/` that was confirmed **failing against
the pre-fix commit** — 7 of 15 in the bridge module, 16 of 19 in the
orchestrator module, and 4 of 14 in the API-server module. The remainder are
documented guards for behaviour that was already correct but untested.

1. **Retry was dead for the most common transient failure on Python 3.9**, a
   live leg of the CI matrix. `urlopen` read timeouts raise `socket.timeout`,
   which only became an alias of `TimeoutError` in 3.10, so
   `isinstance(e, (URLError, TimeoutError))` never matched and
   `NEMOTRON_MAX_RETRIES` did nothing. Peer resets (`ConnectionResetError`,
   which urllib does not wrap) were unretried on every version.
2. **The `urllib.Request` was constructed once outside the retry loop** and
   replayed, so attempt *n* resent an object mutated by attempts *1..n-1*.
3. **`Retry-After` was ignored** and backoff had no ceiling — unbounded
   doubling reaches ~34 minutes on the 11th retry, converting a transient
   outage into a hung build rather than a failure.
4. **A non-JSON body on an HTTP 200 was reported as "Connection Error"**,
   pointing operators at the wrong subsystem.
5. **`resolve_environment()` short-circuited** as soon as `api_key` and
   `default_model` were in the process environment, making
   `NEMOTRON_TIMEOUT_MS` and `NEMOTRON_MAX_RETRIES` unreachable from `.env` in
   exactly the normal configuration.
6. **Tool dispatch had two crash shapes and one contract violation.**
   `arguments: null` reached `json.loads(None)`, raising `TypeError` past an
   `except json.JSONDecodeError` that cannot catch it; `arguments: "[]"`
   parsed to a list and killed every registry lambda on `.get`; and an
   exception from a handler aborted `execute_agent` mid-loop, leaving the
   model's `tool_calls` message unanswered and skipping the `post-*-run` hook.
7. **Debug-history redaction never ran.** It was guarded on `self.api_key`,
   but the orchestrator normally leaves that `None` and lets the bridge
   resolve the credential downstream, so `MANGO_DEBUG_DUMP=1` wrote an
   unredacted history to a predictably named file in the shared temp
   directory, with default directory permissions.
8. **The API server compared its key with `!=`** (a timing oracle), returned
   `conversation_history` verbatim over HTTP, and created `static/` at module
   import — mutating the working tree on every test collection.

## Requirements

- R-RT-1: The retry predicate MUST match `socket.timeout` explicitly, not via
  `TimeoutError`, so it holds on every Python in the CI matrix; it MUST also
  cover `ConnectionError`, and MUST NOT treat `HTTPError` as a transport
  failure (status codes decide those).
- R-RT-2: Each attempt MUST build its own `urllib.Request`.
- R-RT-3: A server-supplied `Retry-After` (delta-seconds or HTTP-date) MUST
  override computed backoff, and every delay — computed or supplied — MUST be
  capped. A malformed header MUST fall back to computed backoff, never
  disable retrying.
- R-RT-4: Backoff arithmetic MUST live in a pure, injectable module
  (`harness/shared/retry_policy.py`) with no environment, clock, or network
  access, so delays are asserted by value rather than by counting sleeps.
- R-RT-5: A malformed response body MUST surface as a protocol error naming
  the body, distinct from a connection error.
- R-RT-6: `resolve_environment()` MUST consult `.env` unless *every* key is
  already supplied by the process environment; the process environment MUST
  still win per key.
- R-RT-7: Tool dispatch MUST emit **exactly one tool message per requested
  tool call** for every input, including `null`, non-object, and unparseable
  `arguments`, an unknown tool name, and a handler that raises.
- R-RT-8: Redaction MUST NOT depend on the caller holding the credential: an
  explicit key is used when given, the environment is consulted when it is
  not, and a provider-shaped token is scrubbed by pattern regardless. It MUST
  cover every string in a message, not only `content`, and MUST NOT mutate its
  input.
- R-RT-9: Debug dumps MUST be written UTF-8 into an owner-only directory,
  including when a laxer directory already exists, and a write failure MUST be
  logged rather than raised.
- R-RT-10: The API key MUST be compared with `secrets.compare_digest` over
  encoded bytes. `verify_api_key` MUST be total: every input yields 401 or
  success, never a 500.
- R-RT-11: `/api/orchestrate` MUST redact the history it returns, reusing the
  same redactor as the dumps.
- R-RT-12: Importing `harness.api_server.main` MUST NOT touch the filesystem
  or write to stdout.
- R-RT-13: A regression tier MUST exist at
  `harness/shared/tests/regression/`, selected by path, with one reproduction
  per defect above.
- R-RT-14: The suite MUST contain no test that cannot fail, enforced
  structurally rather than by review.
- C-RT-1: No protected path may be modified (this PR carries no label).
- C-RT-2: No existing public surface may change: `RETRY_BACKOFF_BASE_SEC`,
  `RETRYABLE_HTTP_STATUSES`, `complete_chat`'s keyword surface, and the
  orchestrator constructor all keep their names and meanings.

## Acceptance criteria

- [x] AC-1: Every regression test was confirmed failing against the pre-fix
  source and passing after — verified by reverting each source file in turn
  (`git stash push <file>`) and re-running its regression module.
- [x] AC-2: `python -m pytest -m "not live"` is green — 901 tests, up from 809.
- [x] AC-3: `ruff check .` and `mypy harness/shared harness/api_server` are
  clean; `check_py_compat.py` passes for Python 3.9.
- [x] AC-4: `coverage_gate.py` passes both floors from
  `governance-policy.json`; `retry_policy.py` and `debug_dump.py` are at 100%
  lines.
- [x] AC-5: The shim suites and `test_harness.py` pass in **both** collection
  orders, proving the `sys.modules` registration no longer leaks.
- [x] AC-6: `test_test_quality.py` reports no assertion-free test and no
  assertion on a freshly imported module, with an empty waiver map.

## Invariants touched

- INV-2: unaffected — no test is skipped, quarantined, or waived. The tier is
  additive and runs in the default selection.
- INV-5: preserved — no Make target changes in this PR; gates are still
  invoked by target. `make test-regression` is deferred to PR B, which owns
  the protected `Makefile`.
- INV-6: not engaged — no protected path is touched, so no attestation is due.

## Validation matrix

- `make lint` — ruff + mypy + `check_py_compat`
- `make test-python` — full suite, live tests deselected
- `make coverage-python` — both floors from
  `governance-policy.json → coverage.{lines,branches}`
- `python -m pytest harness/shared/tests/regression` — the tier on its own
- Collection-order probe: the shim suite and `test_harness.py` in both orders

## Backward compatibility

- `complete_chat`'s signature and keyword surface are unchanged. Retry
  behaviour changes only in directions that were previously broken: failures
  that were never retried now are, and delays that were unbounded now stop at
  a cap.
- Backoff is jittered by default, so delays are no longer exactly
  `base * 2**n`. Every existing test asserts sleep *counts*, not values, and
  the new pure module makes exact values assertable where that matters. A
  caller needing determinism sets `retry_jitter_ratio=0`.
- `RETRY_BACKOFF_BASE_SEC` is retained as an alias of
  `retry_policy.DEFAULT_BASE_SEC` rather than deleted; it is part of the
  module's public surface.
- `_dump_debug_history` keeps its name and signature and now delegates.
- The API server's responses gain redaction. Content that is not a credential
  is returned byte-identical, pinned by a test, so the dashboard is unaffected.
- `harness/api_server/tests` becoming a package changes no import that
  existed; it removes a flat-namespace collision hazard.

## Open questions

None. Two decisions worth recording:

1. **The regression tier is selected by path, not by a `regression` marker.**
   A marker would additionally require registering it in the protected
   `pyproject.toml`, which would have forced an `infra-reviewed` label onto a
   PR that otherwise needs none — for no extra selectivity, since the
   directory already is the selector.
2. **Redaction is deliberately aggressive.** A short credential will scrub
   substrings of ordinary prose. Over-redacting a debug dump costs
   legibility; under-redacting it leaks a credential. The behaviour is pinned
   by a test so it stays a decision rather than a surprise.
