# Spec: orchestrator-tool-registry

> PR 2 of the tech-debt reduction program: decompose the orchestrator's ReAct
> loop, decouple tool dispatch from tool declaration, and wire the advertised
> but unread Nemotron bridge environment variables. No protected paths are
> touched; the public API of every touched module is unchanged.

## Problem statement

- `mango_mas_orchestrator.py::execute_agent` is a 117-line method doing hook
  invocation, message assembly, API calls, response finalization, a debug-dump
  subsystem (with three function-local imports), and tool dispatch. Evidence:
  lines 187–303 on `main`.
- Tool dispatch is an `if/elif` chain that must be edited for every new tool,
  even though tools are already declared declaratively in `NEMOTRON_TOOLS` /
  `META_TOOLS_SCHEMA` — declaration and dispatch can silently drift (an
  advertised tool with no handler returns "Unknown tool" at runtime instead of
  failing a test).
- `.env.example` advertises `NEMOTRON_TIMEOUT_MS` and `NEMOTRON_MAX_RETRIES`,
  but `nemotron_bridge.resolve_environment()` reads neither and no retry logic
  exists anywhere in the bridge — documented knobs that do nothing.
- `nemotron_bridge.py` line 67–68 swallows every exception from `.env` parsing
  with a bare `except Exception: pass` — a malformed `.env` fails invisibly.
- Ten logging calls use f-string interpolation, defeating log-level
  short-circuiting; magic literals (`task[:100]`, confidence `0.5`) are inline.

Verified non-problem (deviation from the program plan, recorded here):
`shadow_planner.py`'s broad `except Exception` handlers were flagged by the
initial debt scan, but each is deliberate, documented containment required by
C-MMI-5 ("no failure in this module may affect the incumbent") and every one
logs with `exc_info`. Narrowing them would weaken the containment contract, so
this spec explicitly leaves `shadow_planner.py` unchanged.

## Requirements

- R-ORCH-1: Tool dispatch MUST be table-driven: a registry mapping each
  declared tool name to a handler, consulted by the ReAct loop; unknown tools
  keep returning the existing `Error: Unknown tool '<name>'` string to the
  model.
- R-ORCH-2: Every function name declared in `NEMOTRON_TOOLS` MUST have a
  registered handler, enforced by a unit test (declaration/dispatch cannot
  drift).
- R-ORCH-3: `execute_agent` MUST be decomposed so that tool-call execution,
  final-response handling, and the debug dump are separate methods; all
  function-local imports move to module scope.
- R-ORCH-4: The public surface of `MangoMASOrchestrator` (constructor
  signature, `execute_agent`, `execute_sequential_thinking_loop`,
  `load_agent_prompt`, `conversation_history`) MUST be byte-compatible with
  callers on `main` — the existing orchestrator test suite passes unmodified
  except where it asserts internal structure.
- R-BRIDGE-1: `resolve_environment()` MUST read `NEMOTRON_TIMEOUT_MS` and
  `NEMOTRON_MAX_RETRIES` (environment first, then `.env`, same precedence as
  the existing keys), and `complete_chat` MUST honor them: the timeout when
  the caller does not pass `timeout_sec` explicitly, the retry count for
  transient failures (HTTP 429/5xx and connection errors) with backoff.
- R-BRIDGE-2: The default retry count MUST be 0 so existing behavior is
  preserved when the variable is unset.
- R-BRIDGE-3: `.env` parsing failures MUST NOT be silent: the except clause is
  narrowed to `(OSError, UnicodeDecodeError)` and logged at debug level.
- C-ORCH-1: No hard-coded threshold moves into policy in this PR (that is the
  policy-single-source infra PR); inline magic literals become named module
  constants only.
- C-ORCH-2: Logging calls in touched files MUST use lazy `%s` formatting, not
  f-strings.

## Acceptance criteria

- [ ] AC-1: A test asserts every `NEMOTRON_TOOLS` function name has a handler
  in the registry — verified by `make test`.
- [ ] AC-2: The full orchestrator/bridge/shadow-planner test suites pass —
  verified by `make coverage-python`.
- [ ] AC-3: `make ci` passes end-to-end — verified by `make ci`.
- [ ] AC-4: `grep -n 'logger\.\w*(f"' harness/shared/mango_mas_orchestrator.py
  harness/shared/nemotron_bridge.py` returns nothing.
- [ ] AC-5: With `NEMOTRON_MAX_RETRIES=2`, a mocked transient HTTP 503 is
  retried and succeeds on a later attempt; with the variable unset, no retry
  occurs — verified by unit tests.

## Invariants touched

- INV-5: untouched — no Makefile or gate changes.
- INV-16 (cognitive/execution boundary): preserved — `shadow_planner.py` is
  deliberately unchanged; no `CognitiveSignal` field reaches a control path.
- INV-8/INV-9: preserved — `_execute_run_command`'s pretooluse-guard routing is
  moved verbatim, not modified.

## Validation matrix

- `make ci` — ruff + mypy + compat + pytest + coverage gate + vitest +
  zero-skips + specs + remotes + validate + check-dedup + digest-regen
- coverage target: `governance-policy.json → coverage.lines` (aggregate)
- Targeted: `pytest harness/shared/tests/test_mango_mas_orchestrator.py
  harness/shared/tests/test_nemotron_bridge.py
  harness/shared/tests/test_shadow_planner.py`

## Backward compatibility

- `MangoMASOrchestrator` public methods and constructor keep identical
  signatures and semantics; new methods are underscore-private.
- `complete_chat` keeps its full keyword surface; `timeout_sec` becomes
  `Optional[int] = None` where `None` resolves to the env-configured value and
  finally the previous literal default — an explicit `timeout_sec=30` caller
  sees identical behavior.
- `resolve_environment()` continues returning at least its existing keys; new
  keys are additive.
- Retries default to 0 (off) — no behavior change unless the operator opts in.

## Open questions

None. The one scope decision (leave `shadow_planner.py` containment intact,
deviating from the program plan's original line-item) is recorded in the
problem statement above.
