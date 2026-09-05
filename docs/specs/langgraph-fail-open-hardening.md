# Spec: langgraph-fail-open-hardening

> Requires the `infra-reviewed` label: it edits `harness/shared/langgraph/**`,
> a protected path. Every protected file touched is attested in the PR
> description per `harness/CONTRACT.md`.

## Problem statement

Six defects in `harness/shared/langgraph/` were reproduced against the real
`langgraph` package (1.2.11, installed from `requirements-langgraph.txt`) on
2026-09-04. Each is a run of the compiled graph, not a reading of the source,
and every line reference below is to the file as it stood before this change.

1. **An authority denial does not change the outcome.** `@with_authority`
   records `{"node", "error", "traceback"}` into the `errors` channel and the
   graph continues to the next node. Nothing routes on `errors`:
   `_route_plan_gate` and `_route_quality_gate` (`graph.py:47`, `graph.py:55`)
   read only `gate_status` and `revision_count`. Replacing `planner_node` with
   the exact dict `decorators.py:58-66` returns on a denial and invoking the
   graph yields:

   ```
   planner DENIED -> verdict: VERIFIED | errors: 1 | plan: ''
   ```

   A denied planner produces a `VERIFIED` verdict over an empty plan.
   `NEXT_STEPS.md:474-477` records these decorators as applied to real nodes
   and `INV-LG-4` as active; they are applied, and their denial is a log line
   and a list append. `quality_gate_node` (`nodes.py:239-244`) consults
   `errors` only when `test_results` is empty, and `test_eval` always appends
   a row, so on every path through the graph the `errors` channel is read by
   nothing.

   This is distinct from `INV-LG-3` (*Fail-Open Error Channel Routing*,
   `docs/architecture/c4_architecture.md:467`), which asks that a node's
   exception be contained in the `errors` channel rather than crashing the
   graph. Containment is correct and is preserved here. What is absent is a
   consumer: a contained error that no gate reads is indistinguishable from no
   error at all.

2. **The quality gate passes vacuously.** With no orchestrator in
   `configurable`, `evaluation_node` returns
   `{"suite": "pytest", "passed": 0, "failed": 0, "skipped": 0}` and
   `quality_gate_node` grades it by `failed > 0` alone, so zero executed tests
   grade `pass` / `VERIFIED`:

   ```
   VERDICT: VERIFIED
   test_results: [{'suite': 'pytest', 'passed': 0, 'failed': 0, 'skipped': 0}]
   ```

   This is the shape DEC-024 named and the vacuous-selector gate of the
   remediation plan exists to reject, reproduced inside the graph's own gate.
   `test_langgraph_nodes.py:260-262` pins the behaviour
   (`quality_gate_node({**DEFAULT_STATE})` asserted `pass` / `VERIFIED` over an
   empty `test_results`), and `test_langgraph_graph.py:185` asserts
   `result["verdict"] in ("VERIFIED", "FAILED", "BLOCKED", "")` — the whole
   domain of the channel, a criterion no implementation can fail.

3. **The policy never reaches the runtime.**
   `harness/shared/experimental/autonomous_healing.py:113-117` — the only
   caller of `build_graph` — loads policy correctly
   (`build_graph(policy=GraphPolicy.from_governance_json())`) and then invokes
   with `config={"configurable": {"orchestrator": orchestrator}}`, carrying no
   `policy` key. `plan_gate_node` and `_route_quality_gate` therefore both take
   their documented `GraphPolicy()` fallback and run on dataclass literals
   (0.35, 10) rather than on `governance-policy.json`. `recursion_limit` is
   read once, to be interpolated into a log line (`graph.py:161-165`), and
   `max_concurrency` is read by nothing:

   ```
   $ grep -rn "max_concurrency\|recursion_limit" harness/shared/langgraph harness/shared/experimental
   harness/shared/langgraph/graph.py:162:        "MangoMAS LangGraph compiled: %d nodes, recursion_limit=%d",
   harness/shared/langgraph/graph.py:164:        policy.recursion_limit,
   ```

   `docs/specs/langgraph-policy-wiring.md` R-LPW-4 and R-LPW-5 made both
   consumers read `config["configurable"]["policy"]`; no producer was ever
   written, so the fallback is the only path any caller takes.

4. **`config` never reaches the two routers at all, whatever the caller
   passes.** This was found while fixing defect 3 and is the reason that fix is
   not sufficient on its own. LangGraph injects `config` only when the
   parameter is annotated `RunnableConfig` or `Optional[RunnableConfig]`, or is
   left unannotated — `KWARGS_CONFIG_KEYS` in
   `langgraph._internal._runnable`, whose check ends
   `if kw == "config" ... warnings.warn(...); continue`. Both routers carried
   `config: Any = None`, which is skipped with a `UserWarning`:

   ```
   graph.py:147: UserWarning: The 'config' parameter should be typed as
   'RunnableConfig' or 'RunnableConfig | None', not 'Any'.
   ```

   So R-LPW-4's policy wiring did nothing through a compiled graph, and its
   tests could not see it: `TestQualityGateRoutingUsesPolicy` calls
   `_route_quality_gate` directly, where an ordinary Python default applies.
   Supplying a policy through `runtime_config` and leaving the annotation as it
   was left the clarification bound of defect 5 at the fallback cap of 10 with
   a policy of 3 in the config. The nodes in `nodes.py` are unaffected: they
   leave `config` unannotated, which is one of the accepted forms. `X | None`
   is *not* one of them under PEP 563, where the annotation is compared as the
   string it evaluates to.

5. **The clarify cycle has no fixpoint.** `clarify_node` writes
   `gate_status["plan_gate"] = "pass"`, and `plan_gate_node` immediately
   recomputes that key from `plan_divergence`, which nothing inside the cycle
   changes. `_route_plan_gate` offers no third exit. With `shadow_planner_node`
   failing (its `errors` return leaves a caller-supplied divergence intact) the
   graph spins until the framework's own ceiling:

   ```
   GraphRecursionError: Recursion limit of 10007 reached without hitting a
   stop condition.
   ```

   Defects 3 and 4 are why the policy's `recursion_limit` of 50 does not bound
   this. The cycle is unreachable today only because `shadow_planner_node` hardcodes
   `plan_divergence: 0.0`; it becomes reachable on the first real divergence
   computation.


6. **A denial still cost one write.** Checking the blocking error only at
   `quality_gate` (downstream of `implementer`) made a denial terminal in
   *verdict* while the write-capable node had already run:

   ```
   verdict: BLOCKED | revision_count: 1 | patches: 1 ['stub.py']
   ```

   The blocking-error exit must be the first branch in `_route_plan_gate`,
   ahead of every route that can reach `implementer`, so a denial costs zero
   writes (R-LGH-3).

**Scope note.** This spec hardens the existing topology and changes no node
from stub to real. `peer_reviewer` and `security_reviewer` are registered with
no incoming edge (`build_graph` adds them at `graph.py:114-115` and never
connects them, so `findings` is empty on every run); wiring them in is an
expansion of the graph, it belongs with the in-or-out decision `NEXT_STEPS.md`
NS-31 and remediation-plan R-SR-27 own, and it is out of scope here. Every
change below survives R-SR-27's relocation of this package under
`harness/shared/experimental/`, which is a path move rather than a rewrite.

## Requirements

- R-LGH-1: An error recorded by a **control-plane** node MUST prevent
  `quality_gate_node` from reporting `pass`, and MUST prevent the run from
  terminating with `VERIFIED`. Errors from **observation-plane** nodes
  (`shadow_planner`, `peer_reviewer`, `security_reviewer`) MUST remain
  non-blocking, because INV-16 requires an observation-mode producer's failure
  to leave the incumbent path unaffected.
- R-LGH-2: `quality_gate_node` MUST NOT report `pass` on an inconclusive
  verification result: an empty `test_results` channel, a latest entry whose
  `passed` and `failed` counts are both zero, or a latest entry whose counts
  are missing, non-integral, boolean, or negative. Zero executed tests is an
  absence of evidence, and DEC-024 makes an absence of evidence a non-pass.
  Malformed counts MUST grade inconclusive without raising.
- R-LGH-3: A control-plane error MUST route to `escalate` rather than consume
  revision budget: the `errors` channel is an `operator.add` accumulator that
  no node clears, so a retry can never remove the entry that failed the gate,
  and routing to `implementer` would burn `max_iterations` revisions before
  reaching the same `BLOCKED` terminal. The check MUST happen at **every**
  route that can reach the write-capable `implementer`, not at `quality_gate`
  alone: `quality_gate` is downstream of `implementer`, so checking only
  there makes a denial terminal in verdict while a patch has already been
  written and a revision already spent. A denial MUST cost zero writes.
- R-LGH-4: The graph MUST expose one constructor for its runtime
  configuration, so a caller threads `GraphPolicy` into
  `config["configurable"]["policy"]` — the key the policy-wiring spec's
  consumers already read — together with `recursion_limit` and `max_concurrency`, and
  `autonomous_healing` MUST invoke through it rather than assembling a
  `configurable` dict that omits the policy.
- R-LGH-5: The `plan_gate` ↔ `clarify` cycle MUST terminate on a bounded
  number of clarification attempts and MUST route to `escalate` when that
  bound is reached, so a divergence that clarification does not resolve ends
  `BLOCKED` rather than exhausting the framework recursion ceiling.
- R-LGH-7: Every routing function and node that reads `config` MUST annotate
  that parameter in a form LangGraph injects — `RunnableConfig`,
  `Optional[RunnableConfig]`, or no annotation — and a check MUST fail when one
  of those signatures drifts out of that set, because LangGraph's only signal
  for the skipped injection is a `UserWarning` raised at graph-build time that
  no existing gate observes.
- R-LGH-6: Every error record written by a node or a decorator MUST carry its
  own blocking classification, so a single definition decides R-LGH-1 for both
  producers and no caller infers terminality from the node name at the point of
  reading. The node's classification MUST be a **floor**: a record may declare
  itself blocking, and MUST NOT be able to declare itself less blocking than
  its node, since a record is data the graph is handed rather than a
  judgement it made.
- R-LGH-8: Only a failing test suite MUST be retryable. A blocking error and
  an inconclusive result MUST route to `escalate` on the first occurrence,
  because neither can be changed from inside the revision loop and each retry
  runs the **write-capable** implementer. The set MUST be expressed as the
  retryable reasons rather than the terminal ones, so a reason added later is
  terminal until someone argues otherwise.
- C-LGH-1: The change MUST NOT alter `build_graph`'s node count, its
  `add_conditional_edges` count, or its `compile()` call signature, all pinned
  by `test_build_graph_assembles_nodes_and_edges`, which the policy-wiring
  spec's own constraint already pinned.
- C-LGH-2: The change MUST NOT alter `CHANNEL_COUNT`, the accumulator/LWW split
  of `MangoState`, or `EXPECTED_NODE_COUNT`; the clarification bound lives
  inside the existing `gate_status` dict, so INV-LG-1's twelve channels stand.
- C-LGH-3: The change MUST NOT weaken INV-LG-3: a node exception stays
  contained in the `errors` channel and MUST NOT propagate out of the node.

## Acceptance criteria

- [x] AC-1: a control-plane node returning the denial record
      `decorators.py` writes leaves the compiled graph with a verdict that is
      not `VERIFIED` — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k TestControlPlaneErrorIsTerminal`
      · stage: `make coverage-python` (R-LGH-1, R-LGH-3)
- [x] AC-2: an `errors` entry from `shadow_planner` does not fail the quality
      gate, so an observation-plane failure cannot block the incumbent path —
      verified by
      `pytest harness/shared/tests/test_langgraph_nodes.py -k observation_plane_error_does_not_block`
      · stage: `make coverage-python` (R-LGH-1, R-LGH-6)
- [x] AC-3: `quality_gate_node` over an empty `test_results` channel, and over
      a latest result of `passed=0, failed=0`, both report `fail` and a verdict
      other than `VERIFIED`, where today both report `pass` — verified by
      `pytest harness/shared/tests/test_langgraph_nodes.py -k inconclusive`
      · stage: `make coverage-python` (R-LGH-2)
- [x] AC-4: `quality_gate_node` still reports `pass` and `VERIFIED` on a
      conclusive passing result (`passed=1, failed=0`, no errors), so the
      orchestrator-backed path is unchanged — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k test_full_e2e_graph_with_orchestrator`
      · stage: `make coverage-python` (R-LGH-2, backward compatibility)
- [x] AC-5: `runtime_config(GraphPolicy(max_iterations=2, recursion_limit=7))`
      produces a config whose `configurable.policy` is that policy and whose
      `recursion_limit` is 7, and a graph invoked through it escalates at a
      revision count the dataclass default would retry — verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k TestRuntimeConfig`
      · stage: `make coverage-python` (R-LGH-4)
- [x] AC-6: `autonomous_healing`'s LangGraph branch invokes with a config
      carrying `configurable.policy` and `recursion_limit`, and the test fails
      when the policy key is dropped from the call — verified by
      `pytest harness/shared/tests/test_autonomous_healing.py -k langgraph_branch`
      · stage: `make coverage-python` (R-LGH-4)
- [x] AC-7: a graph whose `plan_divergence` stays above the threshold
      terminates with `BLOCKED` after a bounded number of clarify visits
      instead of raising `GraphRecursionError` — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k TestClarifyCycleTerminates`
      · stage: `make coverage-python` (R-LGH-5)
- [x] AC-8: `build_graph` compiles with the same ten nodes, two conditional
      edges and `compile(checkpointer=None)` signature after the change —
      verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k assembles`
      · stage: `make coverage-python` (C-LGH-1)
- [x] AC-9: `CHANNEL_COUNT`, the accumulator/LWW partition and
      `EXPECTED_NODE_COUNT` are unchanged, and the channel-reducer regression
      still passes — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k TestLangGraphChannelReducersRegression`
      · stage: `make coverage-python` (C-LGH-2)
- [x] AC-10: a node whose orchestrator raises still returns a contained
      `errors` record rather than propagating the exception — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k TestLangGraphErrorIsolationRegression`
      · stage: `make coverage-python` (C-LGH-3)
- [x] AC-12: every routing function and node that reads `config` annotates it
      in one of the three forms LangGraph injects, and the check rejects a
      signature that drifts back to `Any` — verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k TestConfigInjectionContract`
      · stage: `make coverage-python` (R-LGH-7)
- [x] AC-13: `build_graph()` raises no `UserWarning`, so nothing in the
      compiled graph is silently denied its `config` — verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k emits_no_injection_warning`
      · stage: `make coverage-python` (R-LGH-7)
- [x] AC-15: a record declaring `blocking: False` on a control-plane or
      unrecognised node still blocks, an explicit `True` raises an
      observation-plane record, and a non-boolean flag leaves the node to
      decide — verified by
      `pytest harness/shared/tests/test_langgraph_nodes.py -k TestErrorClassification`
      · stage: `make coverage-python` (R-LGH-6)
- [x] AC-16: an inconclusive run escalates after one revision and one patch
      whatever `max_iterations` says, where it previously wrote one patch per
      revision up to the cap — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k TestInconclusiveDoesNotBuyRetries`
      · stage: `make coverage-python` (R-LGH-8)
- [x] AC-14: a run whose planner is denied reaches `BLOCKED` with
      `revision_count == 0` and an empty `patches` channel, so the
      write-capable implementer never executes after a denial — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -k write_capable_implementer_never_runs`
      · stage: `make coverage-python` (R-LGH-3)
- [x] AC-11: `blocking_error` grades a record from every registered node, and
      an unrecognised node name grades as blocking, so an unclassified error
      fails closed — verified by
      `pytest harness/shared/tests/test_langgraph_nodes.py -k TestErrorClassification`
      · stage: `make coverage-python` (R-LGH-6)

## Steps

1. Add `harness/shared/langgraph/errors.py` — produces `OBSERVATION_NODES`,
   `error_record()` and `blocking_error()`; imports nothing from `nodes.py` or
   `decorators.py`, so both can consume it without a cycle.
2. Rewrite the error literals in `harness/shared/langgraph/decorators.py` to
   call `error_record()` keyed on the wrapped function's node name — consumes
   step 1.
3. Rewrite the error literals in `harness/shared/langgraph/nodes.py` to call
   `error_record()`; change `quality_gate_node` to read `errors` through
   `blocking_error()` and to grade an inconclusive result as `fail`; record the
   failing reason in `gate_status["quality_gate_reason"]`; increment
   `gate_status["clarify_count"]` in `clarify_node` — consumes step 1.
4. Add `runtime_config()` to `harness/shared/langgraph/graph.py`; import
   `RunnableConfig` at runtime beside the existing `langgraph.graph` import and
   re-annotate both routers' `config` parameters into the injectable form;
   route `_route_quality_gate` to `escalate` on the `error` reason; give
   `_route_plan_gate` its `escalate` exit at the clarification bound and add
   that target to the existing `add_conditional_edges` mapping — consumes
   step 3's `gate_status` keys.
5. Change `harness/shared/experimental/autonomous_healing.py` to invoke through
   `runtime_config()` — consumes step 4.
6. Extend `test_langgraph_nodes.py`, `test_langgraph_graph.py`,
   `test_autonomous_healing.py` and
   `harness/shared/tests/regression/test_langgraph_regression.py` with the
   criteria above, and replace the two assertions that pin the vacuous pass.

## Files touched

- `harness/shared/langgraph/errors.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/langgraph/decorators.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/langgraph/nodes.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/langgraph/graph.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/experimental/autonomous_healing.py`
- `harness/shared/tests/test_langgraph_nodes.py`
- `harness/shared/tests/test_langgraph_graph.py`
- `harness/shared/tests/test_autonomous_healing.py`
- `harness/shared/tests/regression/test_langgraph_regression.py`

## Invariants touched

- INV-10: reinforced. A DENY verdict is terminal for that candidate; an
  authority denial recorded by `@with_authority` now reaches a terminal
  `BLOCKED` instead of being overridden by a later node's success (R-LGH-1,
  R-LGH-3, AC-1).
- INV-16: preserved. The observation plane's failures stay contained and
  cannot decide the control path, which is why R-LGH-1 classifies
  `shadow_planner` as non-blocking rather than failing the gate on any error
  at all (AC-2).
- INV-LG-1: unchanged. Twelve channels, same accumulator/LWW partition; the
  clarification bound lives in the existing `gate_status` dict (C-LGH-2, AC-9).
- INV-LG-3: preserved. Node exceptions stay contained in the `errors` channel;
  this change adds a consumer for that channel and does not let an exception
  escape a node (C-LGH-3, AC-10).
- INV-LG-4: made consequential. The decorators already enforce at the node
  boundary; their denial record now decides the verdict (R-LGH-6, AC-11).

## Validation matrix

- `make ci` — ruff + mypy + pytest + coverage (≥ `coverage.lines`) +
  check-dedup + validate_invariants; `harness/shared/langgraph/**` holds its
  per-file floor from `governance-policy.json → coverage.per_file`.
- `make test-langgraph` — the LangGraph suite, run with the optional extra
  installed so the live-execution classes covering AC-1, AC-4, AC-7, AC-9 and
  AC-10 execute rather than skip.
- `ALLOW_GITHUB_CHANGES=1 make validate` — protected-path gate with the
  per-file attestation, since every source file above matches
  `harness/shared/langgraph/**`.
- `make lint-cold` — cold mypy over the changed modules.

## Backward compatibility

Three observable behaviours change, each of them a defect this spec names.

A run that records a control-plane error now ends `BLOCKED` where it ended
`VERIFIED`; a run with no conclusive test result now ends `BLOCKED` where it
ended `VERIFIED`. No caller depends on either: `autonomous_healing` reads the
graph's return value for nothing, re-running its own suite afterwards to decide
success, and it is the only caller.

Two assertions in the existing suite pin the vacuous pass rather than a
contract — `test_langgraph_nodes.py`'s `quality_gate_node({**DEFAULT_STATE})`
asserting `pass` / `VERIFIED` over an empty `test_results`, and
`test_langgraph_graph.py`'s `verdict in ("VERIFIED", "FAILED", "BLOCKED", "")`
covering the channel's whole domain. Both are rewritten to assert the graded
outcome; neither is waived, skipped or marked `xfail`.

`runtime_config()` is additive. `build_graph()`'s signature, defaults and
compile call are untouched, and a caller that keeps passing a bare
`{"configurable": {"orchestrator": ...}}` keeps the `GraphPolicy()` fallback
R-LPW-4 documents.

The router re-annotation is a behaviour change only in the direction R-LPW-4
already intended: a caller that supplied a policy was being ignored, and is now
obeyed. A caller that supplied none is unaffected, and direct calls to either
router — how every existing test reaches them — are unchanged, since an
ordinary Python default was always what those saw.

`harness/shared/langgraph/graph.py` now imports `langchain_core.runnables`
inside the existing `try/except ImportError`, with `RunnableConfig = dict` in
the fallback branch beside the `END`/`START`/`StateGraph` fallbacks. The import
cannot sit under `TYPE_CHECKING`: LangGraph resolves a router's annotations
with `typing.get_type_hints` at build time, which raises `NameError` on a name
that exists only for the type checker. `langchain_core` is a hard dependency of
`langgraph`, so the fallback branch is reached only where the whole optional
extra is absent and `build_graph` already raises.

## Open questions

Six `GraphPolicy` fields remain read by nothing after this change:
`api_timeout_sec`, `tool_timeout_sec`, `coverage_floor_lines`,
`coverage_floor_branches`, `max_delegation_depth` and `max_parallel_subagents`.
Per-node timeouts need a cancellation mechanism the synchronous node contract
does not have, and the coverage floors need the quality gate to read a real
coverage report rather than a `test_results` row. Both are expansions of the
graph and both are downstream of the in-or-out decision NS-31 owns; neither is
resolved here, and this spec deliberately leaves the fields dead rather than
inventing a consumer for them.
