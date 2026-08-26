# Changelog

All notable changes to this project will be documented in this file.

## [2.1.6] - 2026-08-26

### Added

- Created `.agents/skills/nemotron-reasoner/SKILL.md` exposing `nemotron_bridge.py` as an Antigravity & Agent framework reasoning skill.
- Integrated `CONTEXT7_API_KEY` in `.env.example` for Upstash Context7 MCP server compatibility.
- Added comprehensive live test resilience with graceful skip detection on remote NIM 404/410/429 status codes and diffusion model fallbacks.

### Changed

- Refactored `nemotron_bridge.py` to use structured Python standard `logging` with JSON output formats, `--debug` verbose output, and PEP8 compliant line wrapping.
- Updated `.gitignore` and `.dockerignore` to ignore `.gradle/`, `scratch/`, `.benchmarks/`, and ephemeral logs.
- Fortified `nemotron-client.test.ts` test isolation by preventing inadvertent `.env` disk reads via isolated working directories.
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
