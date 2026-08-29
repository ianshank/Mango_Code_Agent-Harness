# Spec: Verdict propagation — a harness-earned verdict on the orchestration loop

> **Programme:** product-path correctness. First change to point the repository's
> liveness discipline at its own runtime rather than at its gates.
> **Protected-path status:** `harness/shared/mango_mas_orchestrator.py` and the new
> `harness/shared/governance/*.py` are protected. `infra-reviewed` attestation required.
> **Provenance:** reviewed across three rounds by the `openspec-peer-review` personas
> (Architect, SDLC/CI, QA, Product), an adversarial security reviewer and a fresh
> red-team reviewer. Two earlier drafts were rejected; findings are recorded in
> `## Open questions` and `## Residual risk`.

## Problem statement

Each item is a reproduction, not a reading.

- `mango_mas_orchestrator.py:439-480` — `execute_sequential_thinking_loop` calls the
  planner, reasoner and verifier once each and returns the verifier's raw string. No
  code parses it, branches on it, or records it.
- `mango_mas_orchestrator.py:121` — the wire prompt asks the model to "Report PASS or
  FAIL"; `.mango/agents/verifier.md:15` specifies `VERDICT: PASS or FAIL`. Both produce
  prose that nothing consumes.
- `harness/api_server/main.py:94` — `status="success"` is a literal on the only
  non-exception path, so a failing run and a passing run are byte-identical to every
  HTTP client.
- `harness/api_server/tests/test_main.py:33,47` — the sole assertion on `status` is made
  against a mock returning `"PASS: verified"`. Changing that mock to `"FAIL"` leaves the
  assertion green. No test in the repository has ever driven a failure through the loop.
- `mango_mas_orchestrator.py:81-96` — `_format_execution_result` discards `exit_code` on
  the success path, so the one structured signal the broker produces is dropped before
  any caller can read it.

`harness/CONTRACT.md` and `test_invariant_liveness.py:1` name this defect class exactly:
an invariant whose mechanism has no caller enforces nothing. Four milestones removed it
from the gate layer. It remains in the product path.

## Requirements

- R-VP-1: A run's verdict MUST be derived from a command the harness selected and
  executed, never from a command the model selected and never from model prose. A model
  that runs `true` MUST NOT be able to reach `VERIFIED`.
- R-VP-2: The harness check MUST execute through `ExecutionBroker` under
  `execution_identity("verifier")`, granting no action that identity does not already
  hold.
- R-VP-3: The check MUST be invoked as `make -f Makefile <target>`, so that an
  unprotected `GNUmakefile` or `makefile` in the workspace cannot shadow the protected
  `Makefile`.
- R-VP-4: The verification command MUST be injectable at construction, with the module
  default declared in a protected module. A caller that configures none MUST receive
  `verification_not_configured`, never a failure verdict.
- R-VP-5: Availability MUST be established by probing the resolved target
  (`make -f Makefile -n <target>`) and the programs its recipe names, not by testing for
  the existence of a file. A failed probe MUST yield `verification_unavailable`.
- R-VP-6: The runner MUST refuse to execute when its re-entrancy sentinel is already
  present in the environment, returning `verification_reentrant` without invoking the
  broker.
- R-VP-7: The probe MUST NOT be capable of invoking the target it probes.
- R-VP-8: `derive_verdict` MUST accept only a `HarnessCheck` value constructed inside the
  verification runner. Passing an `ExecutionResult` MUST raise.
- R-VP-9: A non-zero exit MUST be graded a failure of the change only when the
  availability probe passed; otherwise it is graded a harness condition and is not
  reported as a failure of the change.
- R-VP-10: `derive_verdict` MUST test the broker status and the exit code independently,
  so that a backend reporting one field incorrectly cannot produce a passing verdict.
- R-VP-11: `execute_sequential_thinking_loop` MUST continue to return the verifier
  agent's own message, byte-identical to its behaviour before this change.
- R-VP-12: New response fields MUST be additive and optional; `status` retains its
  existing meaning of "the orchestration did not raise".
- R-VP-13: The rendered result MUST name the command that was executed and its exit
  code, not a verdict word alone.
- C-VP-1: The change MUST NOT widen any role's authority, add a policy key, or modify
  `governance-policy.json`.
- C-VP-2: `verdict.py` MUST import no first-party module.
- C-VP-3: The tool-call budget named by `agent_defaults.max_tool_calls_per_task` MUST be
  cumulative across a task, matching its name and its own diagnostic text.
- C-VP-4: No new module MUST perform I/O, print, or exit at import time.

## Acceptance criteria

- [ ] AC-1: A verifier turn that executes only `true` yields a verdict other than
      `VERIFIED` — verified by `make test-governance` (R-VP-1)
- [ ] AC-2: With a `GNUmakefile` defining the target as a no-op present in the
      workspace, the check does not reach `VERIFIED` — verified by
      `make test-governance` (R-VP-3)
- [ ] AC-3: A runner constructed with no command returns `verification_not_configured`
      and never invokes the broker — verified by `make test-governance` (R-VP-4)
- [ ] AC-4: A workspace whose Makefile lacks the target yields
      `verification_unavailable`, and a non-zero exit under a failed probe is not graded
      a failure of the change — verified by `make test-governance` (R-VP-5, R-VP-9)
- [ ] AC-5: With the sentinel preset in the environment, the runner returns
      `verification_reentrant` and the broker is not called — verified by
      `make test-governance` (R-VP-6)
- [ ] AC-6: The probe spawns no process running the resolved target — verified by
      `make test-governance` (R-VP-7)
- [ ] AC-7: `derive_verdict` raises when handed an `ExecutionResult` — verified by
      `make test-governance` (R-VP-8)
- [ ] AC-8: A check reporting `SUCCESS` with a non-zero exit code, and one reporting
      `FAILED` with a zero exit code, both yield a non-passing verdict — verified by
      `make test-governance` (R-VP-10)
- [ ] AC-9: `execute_sequential_thinking_loop` returns the verifier message unchanged,
      and the existing orchestrator suite passes unmodified — verified by
      `make test-python` (R-VP-11)
- [ ] AC-10: A run whose check exits non-zero returns a different `verdict` field from
      one whose check exits zero, driven through a real broker with a stubbed backend —
      verified by `make test-governance` (R-VP-1, R-VP-12)
- [ ] AC-11: A response carries the executed command and exit code — verified by
      `make test-governance` (R-VP-13)
- [ ] AC-12: A tool-call budget is consumed cumulatively across the turns of one task,
      and a caller invoking a single turn receives a fresh budget — verified by
      `make test-python` (C-VP-3)
- [ ] AC-13: The first-party import graph is acyclic and `verdict.py` imports no
      first-party module — verified by `make test-governance` (C-VP-2)
- [ ] AC-14: Every new module imports cleanly from a working directory that is not the
      repository root, with exit 0, empty stdout and no writes — verified by
      `make test-python` (C-VP-4)
- [ ] AC-15: `make ci` passes on every leg of the CI matrix, with per-file coverage at or
      above the policy floor — verified by CI (C-VP-1)

## Invariants touched

- INV-8 (approved execution broker): **preserved and extended.** The harness check is
  itself routed through `ExecutionBroker`, so the one command this change adds executes
  on the same approved path as the agent's. Verified by AC-1, AC-2.
- INV-9 (deterministic verdict; unavailable backend denies): **strengthened.** Every
  condition under which a verdict cannot be obtained — not configured, re-entrant, probe
  failed, harness fault, broker denial — resolves to a denial rather than to a pass or a
  failure of the change. Verified by AC-3, AC-4, AC-5.
- INV-10 (a denial is terminal): **preserved.** A broker denial of the harness check
  yields a denial verdict; nothing retries or downgrades it. Verified by AC-4.
- INV-16 (one-directional cognitive boundary): **preserved.** No model-authored string
  reaches the verdict: `derive_verdict` accepts only a `HarnessCheck`, which the
  verification runner alone constructs. Verified by AC-7, AC-10.
- INV-11, INV-12: **unaffected.** This change implements neither a critique nor a repair
  loop, and registers neither invariant in `INVARIANT_MECHANISMS`.
- Size budget (`limits.size_budget_lines`): new logic lands in new modules; the
  orchestrator's growth is bounded and measured in `## Validation matrix`.

## Validation matrix

Thresholds are read from `harness/shared/governance-policy.json`; no value is restated
here.

| Stage | Command | Pass criteria |
|---|---|---|
| Lint + types | `make lint` | ruff 0 findings, mypy 0 errors, compat gate 0 violations |
| Coverage | `make coverage` | aggregate and per-file floors from `coverage` policy |
| Governance | `make test-governance` | AC-1 … AC-8, AC-10, AC-11, AC-13 |
| Python suite | `make test-python` | AC-9, AC-12, AC-14 |
| Specs | `make specs` | structural tier passes |
| Full gate | `ALLOW_GITHUB_CHANGES=1 make pre-pr` | AC-15 |

## Backward compatibility

- `execute_sequential_thinking_loop` keeps its signature and its `str` return, now
  produced by delegation. `test_mango_mas_orchestrator.py` and `test_mango_mas_live.py`
  pass unmodified.
- `execute_loop` is a new public method. `docs/specs/orchestrator-tool-registry.md:98-99`
  states that new methods are underscore-private and that public methods keep identical
  semantics. **Both halves are superseded for this method** by this spec and its
  decision-log entry. R-ORCH-4's five named members remain byte-compatible, and the
  loop's semantics are unchanged: one planner turn, one reasoner turn, one verifier turn.
- `execute_agent` gains a keyword argument defaulting to `None`, which reproduces its
  current per-call budget exactly. Every existing caller is unaffected.
- `TaskResponse` gains optional fields with defaults. Clients reading `status`, `result`
  or `history` are unaffected; four in-repository test stubs are updated because they
  patch the orchestrator class rather than because the wire contract changed.

## Residual risk

A reasoner holding `write` in the same workspace can defeat any check run inside that
workspace. `conftest.py` is the airtight case: a `pytest_sessionfinish` hook assigning
`session.exitstatus = 0` forces a zero exit regardless of failures, and
`harness/shared/tests/conftest.py` already exists and is unprotected. `pytest.ini`,
`tox.ini`, `setup.cfg`, `vitest.config.ts` and `package.json` are likewise writable, and
`harness/pytest.ini` would be located before the root `pyproject.toml`. Separately, `mv`
does not classify its source operand, so a failing test file can be relocated rather than
fixed.

Therefore `VERIFIED` means "the configured check exited zero" and nothing more. It is
tamper-evident, not tamper-proof. This is why R-VP-13 requires the command and exit code
to be reported rather than a verdict word: the reader is told what was run, and can judge
what that is worth. The alternative — running the check against a copy the agent never
touched — is recorded as a follow-up rather than built here.

Filed, not addressed: `cat .env*` classifies as a read because the credential shape
requires whitespace or end-of-string after `.env`, so a `.env` glob evades it; the
resulting bytes reach `conversation_history` and the HTTP response today, unchanged by
this work.

## Open questions

- **Resolved.** Whether the verdict may be derived from the agent's own results. It may
  not: a verifier running `true` reaches a passing broker result, so the agent's command
  selection is model authorship at one remove. R-VP-1.
- **Resolved.** Whether `make test` or `make test-python` is the target. `make test`
  depends on the Node stack; a container without it would report a failure of the change
  for a toolchain condition. `VERIFIED` consequently does not imply lint, types,
  coverage, or the governance validators, and R-VP-13 exists so that this is legible.
- **Resolved.** Whether the record of a run is persisted here. It is not; persistence,
  critique normalisation and the repair loop are deferred until the distribution of
  outcomes this change measures says whether a repair loop can succeed. The measuring
  now exists: every `Verdict` is logged at construction (`verdict.py`'s `_emit()`,
  the one choke point all three constructors share) and reaches disk today through
  the existing root JSON logger, with nothing else built — an operator can already
  tally `status`/`termination_reason` from production stdout. The repair loop itself
  remains deferred pending that data and a recorded decision.
- **Still open.** Whether the verification command belongs in `governance-policy.json`.
  It does under the no-hard-coded-values rule, and does not while the module default is
  the only consumer and a policy change would require rebuilding the committed policy
  artifact. Revisit when a second consumer exists.
- **Still open.** Whether the configuration surface (`GNUmakefile`, `makefile`,
  `conftest.py`, `pytest.ini`, `tox.ini`, `setup.cfg`, `vitest.config.ts`) should join
  `protected_paths`, and whether `mv` should classify its source. Both are pre-existing
  containment questions this change surfaces but does not answer.
