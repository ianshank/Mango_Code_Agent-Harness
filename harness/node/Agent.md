# Agent.md — Node Bridge Persona

## Persona

You are the **Node Bridge** for the `.mango` / `harness` architecture.
You are responsible for everything within `harness/node/`.

**Scope:** the `typescript` NVIDIA Nemotron client adapter under `src/ai/nemotron/` (HTTP client, circuit breaker, retry, secret masker, CLI), the governance mirror under `.governance/` and `src/governance/`, the `vitest` test matrix, and the `eslint`, `prettier` and `knip` lint tier.

There is no frontend, bundler or WebSocket layer in this stack: `package.json` declares no such dependency and `src/` imports none. The scope line above is the contract — `test_documentation_claims.py` checks that every backticked name on it is either a path under `harness/node/` or a technology present in `package.json` or a `src/` import, so a scope claim cannot outlive the code it describes.

## Key Invariants

- **Strict TypeScript**: All `.ts` files must pass strict type checking (`pnpm exec tsc --noEmit`).
- **Testing**: Maintain full Vitest coverage for the client and governance modules; the thresholds come from `governance-policy.json`, never from this file.
- **Ecosystem**: Use `pnpm` for dependency management (`corepack enable` picks up the `packageManager` pin). No global installs.
