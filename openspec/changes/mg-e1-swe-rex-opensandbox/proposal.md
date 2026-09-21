# Proposal: MG-E1 SWE-ReX + OpenSandbox adapter pack

## Why
Mango soft-P1 needs optional isolation backends without changing the ProcessBackend default.

## What
Additive SweRexBackend and OpenSandboxBackend behind a fail-closed policy-selected registry (`execution_backend.backend_id`). Isolation claims assert `capabilities().filesystem_isolation == enforced` (R-AEI-10).

## Non-goals
MG-E2 native differentials; Distilled/Neuroharness/FORGE packs; changing ProcessBackend default; annotated release tags.
