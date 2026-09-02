# Mango Code Agent Harness — SDLC Gap Analysis & Code Hygiene Remediation

> Moved from the repository root to `docs/reports/` (tech-debt hardening plan R-TDH-24); content unchanged.

**Repository:** `ianshank/Mango_Code_Agent-Harness`
**Branch / PR:** `chore/sdlc-hygiene-gap-analysis` → [PR #4](https://github.com/ianshank/Mango_Code_Agent-Harness/pull/4)
**Date:** 2026-08-26
**Scope:** Objective peer review of the Python governance kernel (`harness/shared/`, `harness/api_server/`), CI/wiring, dependency hygiene, coverage gates, edge cases, and reusable-component opportunities.

---

## Executive Summary

The harness is a polyglot governance-and-evidence layer (Python kernel + Node TS + Kotlin JVM). The Python kernel is well-structured and mypy-clean, but had accumulated real hygiene gaps: a stale CI workflow that ignored the polished `make ci` pipeline, an orphaned validator with 0% coverage, a 3× duplication of the entire governance kernel across stacks, a hard-coded key in tests, and an exception-leaking API endpoint.

All findings below are evidence-backed and the high-confidence fixes are implemented and verified in PR #4. **ruff clean, mypy clean, 161 tests pass (was 142), coverage 86.99% (was 80.21%).**

---

## Methodology

1. Cloned `main` + inspected all branches and the `.mango/` harness config.
2. Installed the dev toolchain and ran the actual gates: `ruff`, `mypy`, `pytest --cov`.
3. Diffs across stacks to detect duplication; greps for orphaned wiring and hard-coded values.
4. Implemented fixes on a feature branch and re-ran the full gate matrix to verify.

---

## Verification Evidence (post-fix)

| Gate | Before | After |
|---|---|---|
| `ruff check` | 5 errors | **0 errors** |
| `mypy` | clean | clean (29 files) |
| pytest | 142 passed | **161 passed** |
| coverage | 80.21% (barely passing) | **86.99%** |
| `validate_invariants.py` coverage | 0% | **91%** |
| `make check-dedup` | n/a | PASS |
| `make ci` wiring | not run by CI | full pipeline wired |

---

## Findings & Remediation

### CRITICAL — CI workflow was the stale auto-generated template
`.github/workflows/python-package.yml` was GitHub's default Python template: it ran `flake8` (not `ruff`), bare `pytest` with no coverage, installed only `flake8 pytest`, never installed `requirements-dev.txt` or the package (`-e .`), and never installed `fastapi` — so `harness/api_server/tests/` could not even be collected. The matrix `["3.9","3.10","3.11"]` was invalid because the source uses PEP 604 unions (`str | None`), which require Python 3.10+; 3.9 would fail to parse the source at all. The polished root `Makefile` `make ci` pipeline was never invoked by CI.

**Fix:** Rewrote the workflow to call `make ci`; matrix `["3.11","3.12"]`; pinned `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`; pip + pnpm caching.

### CRITICAL — 3× duplication of the governance kernel
All 9 governance scripts (`check_projections`, `check_traceability`, `pretooluse_guard`, `remotes`, `validate_adoption`, `validate_agent_policy`, `validate_governance_docs`, `validate_policy`, `verify_zero_skips`) are **byte-identical copies** across `harness/shared/`, `harness/node/scripts/`, and `harness/jvm/scripts/` (verified with `diff -q`). Any fix must be applied 3× — directly contradicting the "portable governance kernel first" principle in the project charter.

**Fix (non-breaking):** Added `make check-dedup`, a drift gate that fails CI if any node/jvm copy diverges from `harness/shared/` (the single source of truth). The Makefile `validate` target already calls the shared copies via `(cd $(NODE_DIR) && python ../shared/$script.py)`, so the node/jvm copies are already redundant; the gate prevents silent drift until a future dedup-by-symlink/import refactor.

### HIGH — `validate_invariants.py` was orphaned
The script existed but was (a) wired into **no** Makefile target, (b) at **0% test coverage**, and (c) hard-coded its workspace path (`Path(__file__).resolve().parent.parent.parent`), making it untestable in isolation.

**Fix:** Refactored `main()` to accept `workspace_dir`/`policy_path` params (backward-compatible defaults); decomposed into `load_protected_patterns`, `git_modified_files`, `check_protected_paths`, `check_hardcoded_secrets`, `check_size_budget`; wired into `make validate`; added `test_validate_invariants.py` (19 tests) → coverage 0% → 91%.

### HIGH — Hard-coded key + exception leak in API server
- `harness/api_server/tests/test_main.py` committed `os.environ["API_SERVER_KEY"] = "default-dev-key"` (a literal secret in source).
- `harness/api_server/main.py` caught broad `Exception` and echoed internals to clients via `detail=str(e)`.

**Fix:** Replaced the literal with a per-test `secrets.token_urlsafe` fixture (autouse `monkeypatch`); the endpoint now re-raises `HTTPException` unchanged and returns a generic 500 with `logger.exception` for the real cause. Updated the failure test to assert the internal message is **not** echoed.

### MEDIUM — Dependency gap: `fastapi`/`httpx`/`pydantic`/`uvicorn` missing
`requirements-dev.txt` only listed pytest/ruff/mypy. The API server imports `fastapi`/`pydantic` and its tests import `fastapi.testclient` (needs `httpx`). `make coverage-python` includes `harness/api_server/tests/` but those tests couldn't be collected without manually installing the deps.

**Fix:** Added `fastapi>=0.110`, `uvicorn[standard]>=0.27`, `pydantic>=2.5`, `httpx>=0.27` to `requirements-dev.txt`; added `API_SERVER_KEY` to `.env.example`.

### MEDIUM — `nemotron_bridge.py` hard-coded base URL, no logging
`complete_chat()` inlined `os.environ.get("NVIDIA_BASE_URL") or DEFAULT_BASE_URL` and had no structured logging.

**Fix:** Extracted `resolve_base_url()` (prefers `NVIDIA_BASE_URL` env, backward-compatible fallback to the constant); added a module `logger`; log masked key + model + latency on the request path.

### LOW — ruff lint errors
5 ruff errors across `mango_mas_orchestrator.py` (duplicate `import time` — a genuine latent bug), `meta_tools.py` (long description lines), `nemotron_bridge.py` (long f-string), `validate_invariants.py` (long f-string). All fixed by reformatting (no behavior change).

---

## Governance Note — Needs Your Decision

`validate_invariants.py` is now wired into `make ci`. Its `protected_paths` policy includes `Makefile` and `.github/workflows/**` — and **PR #4 modifies both** (to wire the gate and modernize CI). CI will therefore fail the protected-paths invariant unless `ALLOW_GITHUB_CHANGES=1` is set, or the policy is updated to permit this modernization. This is the invariant working as designed — but the escape-hatch policy is your call.

Also: `protected_paths` references a stale `scripts/` layout (e.g. `scripts/validate_policy.py`) that does not match the actual `harness/shared/` layout — those entries are currently no-ops and should be updated in a follow-up.

---

## Opportunities: Reusable Skills / Agents from Reusable Actions

The `.mango/` harness already defines 3 agents (`planner`, `nemotron-reasoner`, `verifier`) and 4 skills. Several repeated actions are not yet turned into reusable skills/hooks:

| Repeated action | Currently | Recommendation |
|---|---|---|
| Protected-path / secrets / size-budget enforcement | one-off script | Already a skill candidate — wrap `validate_invariants.py` as `.mango/skills/repo-invariant-review` action (the skill exists but doesn't invoke the executable gate). |
| Cross-stack script parity | manual | `make check-dedup` (added) — expose as a `pre-pr` hook so drift is caught before push. |
| Coverage gate verification | manual `make coverage` | The `verifier` agent already calls `make pre-pr`; ensure it always includes `--cov-fail-under` (it does via `make ci`). |
| Nemotron pre-flight | `pre-nemotron-run.sh` hook | Already wired via the orchestrator's `_run_hook("pre-nemotron-run")` (not orphaned — invoked programmatically, not via `settings.json`). Consider exposing its result as structured evidence in `conversation_history`. |

## Opportunities: Hooks / Loops

- **`check-dedup` as a `pre-push` hook** — currently a Makefile target; wiring it into `.mango/hooks/` or a git `pre-push` would catch cross-stack drift before it reaches CI.
- **Coverage regression loop** — the `Stop` hook (`pre_completion_checklist.sh`) could assert coverage didn't drop vs. a baseline, closing a loop where a refactor silently reduces coverage below the 80% gate.
- **`validate_invariants` on `PreToolUse` for `Edit|Write`** — the existing `loop_detection.sh` fires on edits; a companion could run the protected-path check live so a forbidden edit is blocked at edit time, not at `make ci`.
- **`knowledge_gap_log` / `hypothesis_register` meta-tools** — already defined in `meta_tools.py`; not wired into any agent's tool list in `.mango/agents/*.md`. Consider exposing them to the `nemotron-reasoner` agent (its SKILL.md references them but the agent `tools:` line only lists `Bash, Read, Grep, Glob`).

---

## Follow-Ups (not in this PR, surfaced for roadmap)

1. **Dedup the 9 scripts by import, not copy** — replace `harness/node/scripts/*.py` and `harness/jvm/scripts/*.py` with thin shims that import from `harness/shared/` (or generate them), guarded by `check-dedup`.
2. **Raise `mango_mas_orchestrator.py` coverage from 59%** — the core MAS loop is the lowest-covered module; add tests mocking the Nemotron bridge (mark live API tests `@pytest.mark.live`).
3. **Modernize `requirements-dev.txt` pins** — `ruff==0.1.0` and `mypy==1.8.0` are old; bump to current and re-baseline.
4. **Fix stale `protected_paths`** to match the `harness/shared/` layout.
5. **Decide the `ALLOW_GITHUB_CHANGES` escape-hatch policy** for legitimate infra PRs.

---

## References

- Repository: [ianshank/Mango_Code_Agent-Harness](https://github.com/ianshank/Mango_Code_Agent-Harness)
- Pull Request #4: [chore(hygiene): SDLC gap analysis & code hygiene remediation](https://github.com/ianshank/Mango_Code_Agent-Harness/pull/4)
- Project context: [Mango Code Agent Harness knowledge page](https://www.perplexity.ai/computer/tasks/c6237a75-a814-4669-92c3-30bed67d7716)
