# Changelog

All notable changes to this project will be documented in this file.

## [2.1.7] - 2026-08-27

### Added

- `harness/shared/check_py_compat.py` — runtime Python 3.9 compatibility gate; detects PEP 604 unions and `datetime.UTC` without `from __future__ import annotations`. Now also covers `ast.AnnAssign` (module/class-level variable annotations).
- `harness/shared/check_dedup.py` — drift gate that fails CI when per-stack governance scripts are full copies instead of thin shims delegating to `harness/shared`.
- `harness/shared/governance/broker.py` — `ExecutionBroker` enforcing INV-8 (pretooluse_guard) and INV-9 (no host-process fallback). Paths extracted to module-level constants; structured `logging` throughout.
- `harness/shared/governance/evidence_manifest.py` — `EvidenceBuilder` refactored: `signing_key` now injectable via constructor (env-var fallback), raises `ValueError` (not `OSError`) for missing key, top-level imports, DEBUG logging on export.
- `harness/shared/tests/test_evidence_manifest.py` — 17-test suite covering key resolution priority, all `add_*` methods, HMAC signature verification, manifest immutability, and debug logging.
- `harness/shared/tests/test_governance_broker.py` — 11-test suite covering INV-8/INV-9, PDP allow/deny/absent, human-approved flag, logging, and `ExecutionResult` dataclass.
- `harness/shared/tests/test_mango_mas_orchestrator.py` — Platform-guarded bash hook tests (skip on Windows where bare `bash` cannot interpret Windows paths).
- `pyproject.toml` — Added `[project]` table and `[tool.setuptools.packages.find]` so `pip install -e .` resolves only `harness*` and does not fail with "Multiple top-level packages".
- `.gitignore` — Added `harness/node/test-*/` and `.hypothesis/` exclusions for pytest/hypothesis temp directories.

### Changed

- `.github/workflows/python-package.yml` — Fixed misleading PEP 604 comment; null-guarded `ALLOW_GITHUB_CHANGES` against push events where `pull_request` context is absent.
- `harness/node/package.json` — Added `"pnpm": { "onlyBuiltDependencies": ["esbuild"] }` to allowlist esbuild's build script under pnpm 11 supply-chain security policy.
- `Makefile` — `lint-python` now runs `ruff check .` (all first-party Python); `lint` depends on new `check-compat` target; `ci` depends on new `check-dedup` target; added `spec`, `review`, `pre-pr` targets.
- `harness/shared/governance-policy.json` — Updated `protected_paths` from stale `scripts/*` references to correct `harness/shared/*` layout; added `dedup` and `py_compat` policy sections.
- `harness/control-plane/policy-bundle.example.json` — Regenerated digests after governance script changes (19 node + 21 jvm protected file digests).

### Fixed

- `test_validate_invariants.py::test_main_default_workspace_runs` — Made hermetic by patching `DEFAULT_WORKSPACE_DIR` to a temp repo instead of accepting any exit code from the real working tree.
- `governance/evidence_manifest.py` — Removed insecure HMAC fallback key (`"default-insecure-key"`); raises `ValueError` when `AGENT_EVIDENCE_KEY` is unset.
- `governance/broker.py` — Replaced f-strings in logger calls with lazy `%s` format; extracted hardcoded PDP/policy paths to module-level constants.

## [2.1.6] - 2026-08-26


### Added

- Created `.agents/skills/nemotron-reasoner/SKILL.md` exposing `nemotron_bridge.py` as an Antigravity & Agent framework reasoning skill.
- Added comprehensive live test resilience with graceful skip detection on remote NIM 404/410/429 status codes and diffusion model fallbacks.
- Added robust Mock Fallback logic in `mango-mas-e2e-live.test.ts` and `cli-live.test.ts` to ensure E2E pipelines pass deterministically during API flakiness.

### Changed

- Refactored `nemotron_bridge.py` and `main.py` to use structured Python standard `logging` via `harness/shared/logging.py` (JSONFormatter) for AI parsing compatibility.
- Updated `.gitignore` and `.dockerignore` to ignore `.gradle/`, `scratch/`, `.benchmarks/`, and ephemeral logs.
- Fortified `nemotron-client.test.ts` test isolation by replacing manual `process.env` mutation with `vi.stubEnv`.
- Updated `.gitleaks.toml` allowlist to protect test fixtures and mock API token patterns.

### Fixed

- Fixed ungraceful process exits in `test_nemotron_bridge.py` and converted to `pytest` `caplog` verification.
- Resolved race conditions in Vitest and Pytest test runners across live AI smoke tests.
- Re-established zero-unapproved-skip invariant compliance with full governance validator execution.

## [2.1.5] - 2026-08-25

### Added

- Created `.github/skills/code-review/SKILL.md` to document the code review skill process and testing criteria.

### Changed

- Refactored `mango_mas_orchestrator.py` to extract long prompt strings into named constants (`PLANNER_PROMPT_TEMPLATE`, `REASONER_PROMPT_TEMPLATE`, `VERIFIER_PROMPT_TEMPLATE`) to resolve Ruff E501 line-length violations.
- Fully typed `mango_mas_orchestrator.py`, `meta_tools.py`, and `nemotron_bridge.py` ensuring compliance with `mypy --strict`.
- Updated `.dockerignore` to explicitly ignore `.mango/` workspace directories.
- Minor cleanups in `check_traceability.py` to fix line-length linting errors.

### Fixed

- Fixed un-typed kwargs passing in `complete_chat` function invocation inside `mango_mas_orchestrator.py`.
- Fixed missing `typing` imports in `nemotron_bridge.py` and `meta_tools.py`.
- Ensure fail-closed governance models are strictly adhered to by properly propagating errors from the policy guard in `mango_mas_orchestrator.py`.
