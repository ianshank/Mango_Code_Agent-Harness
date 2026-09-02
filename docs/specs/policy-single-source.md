# Spec: policy-single-source

> PR 4 of the tech-debt reduction program, and the first requiring the
> `infra-reviewed` label: it edits `governance-policy.json`, protected
> validators, and other protected agent-control-surface files. Every protected
> file touched is attested in the PR description per `harness/CONTRACT.md`.

## Problem statement

CLAUDE.md's first non-negotiable is "no hard-coded values; thresholds come
from `governance-policy.json`" — yet the runtime violates it structurally:

- `mango_mas_orchestrator.py` hard-coded `max_iterations=10`,
  `api_timeout=300`, `tool_timeout=30` while the policy's
  `agent_defaults.max_tool_calls_per_task` (and siblings) had **zero code
  readers** — the policy and the runtime did not know about each other.
- `nemotron_bridge.py` hard-coded `temperature=0.2`, `max_tokens=4096`, and a
  30s timeout.
- The decision-ID grammar existed in five copies: `decision_id_pattern` in
  three policy files plus hand-copied regexes in `check_projections.py` and
  `governance/verify_zero_skips.py`, held in lockstep only by a test.
- Fallback constants (`validate_invariants.SIZE_BUDGET_LINES`,
  `check_dedup.DEFAULT_MAX_SHIM_LINES`) duplicate policy numbers with no
  equality test.
- The four shared re-export shims carried three different hand-rolled
  `sys.path` bootstraps.
- `harness/{node,jvm}/agents/*.md` were byte-identical copies (8 files × 2)
  invisible to `check_dedup` (which scans only `scripts/*.py`).

## Requirements

- R-POL-1: The policy MUST declare `orchestrator` (`max_iterations`,
  `api_timeout_sec`, `tool_timeout_sec`) and `nemotron` (`temperature`,
  `max_tokens`, `timeout_ms`, `max_retries`) blocks mirroring the previous
  literals, and both MUST have code readers in the same change.
- R-POL-2: A shared loader (`harness/shared/policy_loader.py`) MUST resolve
  explicit argument > policy > built-in default with fail-closed semantics:
  absent policy = adopter defaults; present-but-malformed policy = raise (as
  `coverage_gate.load_thresholds` does). Environment-variable overrides stay
  in the callers that define them (the bridge reads NEMOTRON_TIMEOUT_MS /
  NEMOTRON_MAX_RETRIES before falling back to the loader's policy values,
  completing arg > env > policy > builtin for those knobs); the loader itself
  reads no environment so gates and runtimes share one deterministic reader.
- R-POL-3: `MangoMASOrchestrator` limits MUST resolve through the loader with
  constructor kwargs still overriding; `agent_defaults.max_tool_calls_per_task`
  MUST gain its first code reader as a cumulative tool-call budget per task.
- R-POL-4: Both decision-ID scanners MUST load the grammar from the policy at
  runtime (converting the anchored `^(...)$` form to the `\b(...)\b` search
  form), keeping a fallback literal only for the adopter path; a
  present-but-malformed pattern fails closed. The scanners stay standalone
  stdlib scripts (per-stack shims runpy them from arbitrary CWDs), so each
  carries the ~10-line loader rather than importing the harness package.
- R-POL-5: `test_policy_consistency.py` MUST keep the five-copy lockstep by
  pinning the fallback literals to the policy body, and MUST gain equality
  pins for `SIZE_BUDGET_LINES`, `DEFAULT_MAX_SHIM_LINES`, and the loader's
  built-in defaults.
- R-POL-6: The shared shims (`remotes`, `pretooluse_guard`,
  `verify_zero_skips`) MUST use the import-first try/except bootstrap already
  used by `check_traceability.py`, keeping `__all__` and `__main__` behavior.
- R-POL-7: `check_projections.py` MUST become importable (argparse moves under
  `main()` + `__main__` guard) with identical CLI behavior.
- R-POL-8: The byte-identical per-stack agent role contracts MUST become
  pointer stubs referencing `harness/shared/agents/`; `GOVERNANCE_SKILL.md`
  (stack-specific, content-validated) stays as-is.
- C-POL-1: `make digest-regen` MUST run in the same change (the policy's
  top-level digest moves) and the committed bundle must be drift-free.
- C-POL-2: Behavior with no policy file (adopter path) MUST be identical to
  before this change — every built-in default mirrors the previous literal.

## Acceptance criteria

- [ ] AC-1: `grep -rn "max_iterations: int = 10\|api_timeout: int = 300"
  harness/shared/` returns nothing; orchestrator limits come from the policy —
  verified by `test_policy_loader.py` / `TestPolicySourcedLimits`. — open
  2026-09-02: the grep returns
  `harness/shared/langgraph/policy.py:21: max_iterations: int = 10` (plus a
  test helper signature in `test_shadow_planner.py:432`);
  `test_policy_loader.py` + `TestPolicySourcedLimits`: 22 passed; blocked by
  tech-debt-hardening-plan R-TDH-12
- [x] AC-2: A task exceeding `max_tool_calls_per_task` raises and fires the
  `budget_exceeded` hook — verified by `make test`. — verified 2026-09-02:
  `pytest harness/shared/tests/test_tool_budget.py harness/shared/tests/test_orchestrator_agent_loop.py -k budget`:
  15 passed
- [x] AC-3: `test_policy_consistency.py` passes with the new pins (five-copy
  grammar lockstep against fallback literals, fallback-constant equality) —
  verified by `make test`. — verified 2026-09-02:
  `pytest harness/shared/tests/test_policy_consistency.py`: 36 passed
- [ ] AC-4: `ALLOW_GITHUB_CHANGES=1 make pre-pr` passes end-to-end, including
  `digest-regen` drift check. — open 2026-09-02: `make ci`, `review` and `lint-cold` pass; `audit` and `secrets` need
  `pip-audit`, `osv-scanner` and `gitleaks`, absent in this environment, so those two are
  evidenced by the `dependency-audit` and `secret-scan` CI jobs (tech-debt-hardening-plan
  C-TDH-3); no plan item
- [x] AC-5: `python harness/shared/check_projections.py --help` and per-stack
  shim invocations behave identically to before (same flags/exit codes) —
  verified by `make validate`. — verified 2026-09-02: `--help` exits 0 with
  the `--config`/`--decision-log` flags; `ALLOW_GITHUB_CHANGES=1 make validate`
  ends `All governance validators passed` (the flag covers this branch's
  uncommitted protected-path edits, not this spec)

## Invariants touched

- INV-5: preserved — no Make target changes; gates invoked identically.
- INV-6: preserved — protected-path changes ride the `infra-reviewed`
  attestation; digests regenerate in the same commit.
- INV-2/INV-3: untouched.

## Validation matrix

- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — full CI plus cold lint
- coverage target: `governance-policy.json → coverage.lines` (aggregate)
- Targeted: `pytest harness/shared/tests/test_policy_loader.py
  harness/shared/tests/test_policy_consistency.py
  harness/shared/tests/test_mango_mas_orchestrator.py
  harness/shared/tests/test_nemotron_bridge.py`

## Backward compatibility

- Orchestrator constructor keeps its kwargs; defaults change from literals to
  `None`-resolves-through-policy, and the policy values mirror the old
  literals, so observed behavior is unchanged in this repo and for adopters
  without a policy file.
- `complete_chat` keyword surface unchanged; `temperature`/`max_tokens`
  become `Optional` with policy-mirrored defaults.
- The shims keep `__all__` exports and CLI entry behavior; the scanners keep
  their CLI contract, and `ID_RE` remains a module attribute of
  `governance/verify_zero_skips.py`.
- Per-stack agents files still exist at their old paths (pointer stubs), so
  `protected_paths` patterns and liveness tests keep matching.

## Open questions

None. The choice to keep the scanners standalone-stdlib (duplicating a small
loader) instead of importing `policy_loader` follows the repo's existing
design for gates (`validate_invariants.py` is deliberately stdlib-only), with
the lockstep test preventing rot.
