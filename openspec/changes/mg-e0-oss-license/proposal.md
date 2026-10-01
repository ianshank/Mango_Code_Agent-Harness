# Change: MG-E0 OSS License (`mg-e0-oss-license`)

> **Status: proposed.** Critic Gate A GO (Product board). Hygiene only.
> SPDX binding: **MIT** (match SWE-ReX; Apache-2.0 patent grant deferred unless Ian requires it).

## Why

The public repository has no SPDX license (`license: null` on GitHub; no `LICENSE` file on `main`). Downstream adapters planned for MG-E1 (SWE-ReX, OpenSandbox) and any third-party reuse are blocked or legally ambiguous while the tree is unlicensed. MG-E0 closes that gap before any backend or shadow-agent work.

**Evidence:** GitHub API `license` is null; tree listing on `main` has no `LICENSE` / `LICENSE.md`; `pyproject.toml` `[project]` has no `license` field.

## What Changes

- Add root `LICENSE` with the standard MIT text, copyright Ian Cruickshank, year 2026.
- Set `[project].license` in `pyproject.toml` to the SPDX id `MIT`.
- OpenSpec package under `openspec/changes/mg-e0-oss-license/` with proposal, design, tasks, and capability spec `oss-license`.
- Kill criteria: GitHub `license.spdx_id` non-null after merge (or equivalent LICENSE presence check); CI/docs must not treat a missing LICENSE as acceptable once this change is archived.

## Non-Goals

- No ProcessBackend default change (E1 open question stays design).
- No SWE-ReX / OpenSandbox / Stagehand / mini-swe-agent adapters (MG-E1..E4 Soft P1 after E0 ships).
- No second dangerous-command classifier; no broker policy replacement.
- No Distilled_Agents, Neuroharness, or FORGE work.
- No dual-license or Apache-2.0 unless Ian overrides the Critic MIT binding.

## Affected Capabilities

- `oss-license`
