# Spec: langgraph-policy-wiring

> Requires the `infra-reviewed` label: it edits `harness/shared/langgraph/**`
> and `harness/shared/governance-policy.json`, both protected paths. Every
> protected file touched is attested in the PR description per
> `harness/CONTRACT.md`.

## Problem statement

A tech-debt audit of this repository (independently verified by a 4-persona
peer review — Architect, SDLC/CI Lead, QA Director, Product Manager — each
reading the source directly) found real, live violations of `CLAUDE.md`'s
"no hard-coded values; thresholds come from `governance-policy.json`" rule
inside `harness/shared/langgraph/`, plus a more severe fail-open bug in the
same code path:

1. **`GraphPolicy.from_governance_json()` fails open on a malformed policy.**
   `harness/shared/langgraph/policy.py`'s factory wraps its entire load in a
   bare `except Exception: return cls()`, silently substituting hardcoded
   defaults — not just when the policy file is absent (the legitimate
   adopter path, already handled gracefully by `policy_loader.load_policy()`
   returning `{}`), but also when it is *present and malformed*. This
   directly contradicts `policy_loader.py`'s own documented contract:
   *"a present but malformed policy raises, because silently falling back
   would let a corrupted policy weaken a gate or a runtime limit."* This is
   the sixth occurrence of the same recurring pattern in this repository's
   decision log (`COV_MIN=80`; the `size_budget_lines`/`check_dedup`/
   `check_py_compat` trio `NEXT_STEPS.md` already documents as "the same
   inversion... missed three more times"; DEC-005; DEC-006; DEC-009).
2. **Three fields are never populated from policy at all.**
   `recursion_limit` (50), `max_concurrency` (3), and
   `plan_divergence_threshold` (0.35) are dataclass defaults that
   `from_governance_json()` never reads from `governance-policy.json` —
   which has no corresponding section — despite the module's own docstring
   claiming it "avoids hardcoded values per user rule."
3. **Two call sites bypass `GraphPolicy` entirely with independent literals**
   that happen to match the dataclass defaults above, so nothing has ever
   caught the drift risk:
   - `harness/shared/langgraph/graph.py:62`, `_route_quality_gate()`:
     `if revision_count < 10:`, with its own comment admitting the debt
     (`# Will be overridden by policy in Phase 4`).
   - `harness/shared/langgraph/nodes.py:203`, `plan_gate_node()`:
     `"pass" if divergence <= 0.35 else "fail"`.
4. **`build_graph()` defaults to a bare `GraphPolicy()`** (`graph.py:89-90`)
   instead of `GraphPolicy.from_governance_json()`, so the one call site that
   would otherwise load policy silently skips it on the default path.
5. **The existing test for this code is not a safety net.**
   `test_langgraph_policy.py`'s assertions all check values that are
   numerically identical between the dataclass default and the live policy
   value, so they pass whether or not wiring works. Its
   `test_fallback_on_missing_policy` defines a `_raise_import()` helper it
   never calls, and monkeypatches `from_governance_json` to a lambda it also
   never invokes — the real fail-open path is completely untested today.

**Context that changes urgency, not correctness**: both target branches are
currently unreachable in normal execution. `quality_gate_node` (`nodes.py`)
is an explicit "Phase 1 stub: always passes" per its own docstring, so
`_route_quality_gate`'s cap is never consulted; `shadow_planner_node`
hardcodes `"plan_divergence": 0.0` always ("No real comparison yet"), so
`plan_gate_node`'s threshold is never tested against a real value either.
This is completing self-documented Phase-1 scaffolding ahead of a Phase-4
the code already names for itself, not patching a live production defect —
and `build_graph()` is not called from any live orchestration path today
(gated behind `LANGGRAPH_AVAILABLE`, and confirmed as of 2026-08-31 that no
CI job installs the `langgraph` package at all — only two test modules
import `graph.py`, both of which mock `StateGraph` rather than exercising
the real library). Fail-open is still fixed regardless of reachability: a
gate that lies about its own state is a defect independent of whether
anything currently depends on the lie.

## Requirements

- R-LPW-1: `GraphPolicy.from_governance_json()` MUST raise (fail closed) when
  `governance-policy.json` is present but malformed, and MUST continue to
  use built-in defaults only when the policy file is genuinely absent — both
  behaviors delegated to `policy_loader`'s existing, already-correct
  absent-vs-malformed distinction, not reimplemented.
- R-LPW-2: `GraphPolicy.from_governance_json()` MUST source `recursion_limit`,
  `max_concurrency`, and `plan_divergence_threshold` from a new `langgraph`
  section in `governance-policy.json`, read via a new `policy_loader.langgraph_defaults()`
  function following the existing `orchestrator_defaults()`/`nemotron_defaults()`
  pattern (type-validated via the existing `_int_value`/`_float_value` helpers).
- R-LPW-3: `build_graph()` MUST default to `GraphPolicy.from_governance_json()`
  when no `policy` argument is supplied.
- R-LPW-4: `_route_quality_gate()`'s revision-loop cap MUST be sourced from
  `GraphPolicy.max_iterations` (already correctly wired to
  `orchestrator.max_iterations` — no new policy key needed), read from
  `config["configurable"]["policy"]` when the caller supplies one, via the
  same `_get_configurable` mechanism `nodes.py` already uses for
  `orchestrator`. When no policy is supplied via `configurable`, it MUST
  fall back to `GraphPolicy()`'s built-in default (10) — numerically
  identical to today's literal, so this is a behavior-preserving default,
  not a second independent constant.
- R-LPW-5: `plan_gate_node()`'s divergence threshold MUST be sourced from
  `GraphPolicy.plan_divergence_threshold` (per R-LPW-2) via the same
  `configurable`-based mechanism and fallback rule as R-LPW-4.
- R-LPW-6: Any node/routing function signature changed to accept `config`
  MUST preserve the existing calling-convention contract pinned by
  `test_langgraph_regression.py::TestLangGraphNodeInvocationRegression`
  (accepts single positional state / two positional args / keyword config).
- C-LPW-1: The change MUST NOT alter `build_graph()`'s node count, edge
  count, or `compile()` call signature (`test_build_graph_assembles_nodes_and_edges`
  pins `compile.assert_called_once_with(checkpointer=None)` — policy is
  threaded through `configurable` at invoke time, never baked into `compile()`).
- C-LPW-2: The change MUST NOT require the real `langgraph` package to be
  installed for its tests to execute — the current test suite (as of
  2026-08-31) verifies this code via a mocked `StateGraph`, and this spec
  does not change that; genuine integration testing against the real
  library is out of scope (see Open questions).

## Acceptance criteria

- [x] AC-1: `GraphPolicy.from_governance_json()` raises when
      `governance-policy.json` is replaced with malformed JSON (or a
      present-but-wrong-typed `langgraph.recursion_limit`) — verified by
      `pytest harness/shared/tests/test_langgraph_policy.py -k malformed`
      · stage: `make coverage-python` (R-LPW-1)
- [x] AC-2: `GraphPolicy.from_governance_json()` still returns built-in
      defaults when the policy file is absent entirely (no regression to the
      legitimate adopter path) — verified by
      `pytest harness/shared/tests/test_langgraph_policy.py -k absent`
      · stage: `make coverage-python` (R-LPW-1)
- [x] AC-3: a policy fixture with a distinguishable, non-default
      `langgraph.recursion_limit` (e.g. 999) actually flows through
      `GraphPolicy.from_governance_json().recursion_limit` — verified by
      `pytest harness/shared/tests/test_langgraph_policy.py -k distinguishable`
      · stage: `make coverage-python` (R-LPW-2)
- [x] AC-4: `_route_quality_gate` with a custom policy's lower `max_iterations`
      (e.g. 2) in `config["configurable"]["policy"]` escalates at
      `revision_count=2`, where the *default* policy's cap (10) would not —
      proving the literal no longer decides this — verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k TestQualityGateRoutingUsesPolicy`
      · stage: `make coverage-python` (R-LPW-4)
- [x] AC-5: `_route_quality_gate` called with no `config` at all still
      escalates at `revision_count=10` exactly as before this change —
      verified by `pytest harness/shared/tests/test_langgraph_graph.py -k default_policy`
      · stage: `make coverage-python` (R-LPW-4, backward compatibility)
- [x] AC-6: `plan_gate_node` with a custom policy's lower
      `plan_divergence_threshold` (e.g. 0.1) fails at `divergence=0.2`, where
      the *default* policy's threshold (0.35) would pass — verified by
      `pytest harness/shared/tests/test_langgraph_nodes.py -k TestPlanGateNodeUsesPolicy`
      · stage: `make coverage-python` (R-LPW-5)
- [x] AC-7: `test_langgraph_regression.py` still collects with no new errors
      (its own pre-existing, unrelated-to-this-change `LANGGRAPH_AVAILABLE`
      skip condition still applies — as of 2026-08-31 this file is
      unconditionally skipped regardless of this change, unlike
      `test_langgraph_graph.py`/`test_langgraph_nodes.py`, which PR #52
      already converted to run via mocks; this file was not part of that
      PR). It therefore cannot itself prove R-LPW-6 today — that is instead
      proven directly by AC-4/AC-6 below (`_route_quality_gate`/`plan_gate_node`
      each invoked with zero, one, and two positional args plus keyword
      `config`) — verified by
      `pytest harness/shared/tests/regression/test_langgraph_regression.py -v`
      · stage: `make coverage-python` (R-LPW-6)
- [x] AC-8: `test_build_graph_assembles_nodes_and_edges` still passes
      unchanged, including its `compile.assert_called_once_with(checkpointer=None)`
      assertion, exercised entirely via a mocked `StateGraph` with no real
      `langgraph` package required — verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k assembles`
      · stage: `make coverage-python` (C-LPW-1, C-LPW-2)
- [x] AC-9: `build_graph()` called with no `policy` argument compiles a
      graph whose logged `recursion_limit` matches
      `GraphPolicy.from_governance_json().recursion_limit`, not the bare
      dataclass default from a different policy fixture — verified by
      `pytest harness/shared/tests/test_langgraph_graph.py -k default_policy_is_loaded`
      · stage: `make coverage-python` (R-LPW-3)

## Steps

1. Add `langgraph_defaults()` to `harness/shared/policy_loader.py` — produces
   a policy-reading function; consumes nothing new.
2. Add a `langgraph` section to `harness/shared/governance-policy.json` with
   today's dataclass-default values (50/3/0.35) — produces a new policy key
   set; purely additive, no other section's values change.
3. Rewrite `GraphPolicy.from_governance_json()` in
   `harness/shared/langgraph/policy.py` to call `langgraph_defaults()` and
   remove the blanket `except Exception` fallback — consumes step 1 and 2's
   outputs.
4. Change `build_graph()`'s default in `harness/shared/langgraph/graph.py`
   to `GraphPolicy.from_governance_json()`.
5. Change `_route_quality_gate()` in `graph.py` to accept
   `(state, config=None, **kwargs)`, import `_get_configurable` from
   `nodes.py`, and read `policy.max_iterations` instead of the literal `10`.
6. Change `plan_gate_node()` in `harness/shared/langgraph/nodes.py` to accept
   `(state, config=None, **kwargs)` and read `policy.plan_divergence_threshold`
   instead of the literal `0.35`.
7. Rewrite `test_langgraph_policy.py`'s `test_fallback_on_missing_policy`
   (vacuous today) into two real tests — absent-policy-uses-defaults and
   malformed-policy-raises — and add a distinguishable-value liveness test.
8. Extend `test_policy_consistency.py::TestFallbackConstantsMirrorPolicy`
   with a `langgraph_defaults()` mirrors-policy test, matching the existing
   pattern for `orchestrator_defaults()`/`nemotron_defaults()`.
9. Add policy-consumption tests to `test_langgraph_graph.py` (routing) and
   `test_langgraph_nodes.py` (`plan_gate_node`).

## Files touched

- `harness/shared/policy_loader.py` (protected: literal entry)
- `harness/shared/governance-policy.json` (protected: literal entry)
- `harness/control-plane/policy-artifact.json` (protected: literal entry —
  the committed content-digest artifact, regenerated via
  `publish_policy_artifact.py build` after `governance-policy.json` changes;
  its own drift gate, `test_committed_artifact_matches_working_tree`, is
  what makes forgetting this step fail loudly rather than silently)
- `harness/shared/langgraph/policy.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/langgraph/graph.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/langgraph/nodes.py` (protected: `harness/shared/langgraph/**`)
- `harness/shared/tests/test_langgraph_policy.py`
- `harness/shared/tests/test_langgraph_graph.py`
- `harness/shared/tests/test_langgraph_nodes.py`
- `harness/shared/tests/test_policy_consistency.py`

## Invariants touched

- None of INV-1..INV-17 directly — this is an internal policy-sourcing
  correction to a module not on any live enforcement path (`LANGGRAPH_AVAILABLE`
  is `False` in every CI job as of 2026-08-31). It does, however, reinforce
  the fail-closed posture `harness/CONTRACT.md`'s coverage-gate note and
  `policy_loader.py`'s own docstring both already require of every
  policy-derived default in this repository.

## Validation matrix

- `make coverage-python` — full pytest suite + coverage; must stay ≥
  `coverage.lines` (90%) and ≥ `coverage.branches` (80%) from
  `governance-policy.json`, with `harness/shared/langgraph/**` continuing to
  meet the per-file floor it currently meets (100%/98%/100%/100% as of
  2026-08-31, per PR #52's mocked test coverage — this change must not drop
  any of the four files below 90%).
- `pytest harness/shared/tests/regression/test_langgraph_regression.py` —
  the dedicated calling-convention/topology regression tier.
- `python -m ruff check .` / `python -m mypy ... --check-untyped-defs` — clean.
- `ALLOW_GITHUB_CHANGES=1 make validate` — protected-path gate passes with
  attestation.

## Backward compatibility

Every fallback value introduced by this change (`GraphPolicy()`'s bare
defaults, used when no `config`/`configurable` is supplied) is numerically
identical to the literal it replaces (10, 0.35), so every existing caller
and every existing test that invokes these functions with a bare `state`
argument continues to observe identical behavior. The only new failure mode
is `GraphPolicy.from_governance_json()` raising on a malformed policy file —
previously silent — which is the fix, not a regression: no caller today
relies on a malformed policy silently producing wrong values, since
`build_graph()` (the only caller) is not invoked from any live path.

## Open questions

Genuine integration testing against the real `langgraph` package (verifying
this wiring against actual `StateGraph`/`add_conditional_edges` semantics,
not a `MagicMock`) is out of scope here — no CI job installs the package as
of 2026-08-31 (tracked separately; not part of this spec's problem
statement, which is about hardcoded values, not test infrastructure). If the
team wants that closed, it needs its own spec: either install the
`langgraph` extra on a CI leg, or formally record the gap in
`test_ci_gate_coverage.py`'s `KNOWN_GAPS` convention.
