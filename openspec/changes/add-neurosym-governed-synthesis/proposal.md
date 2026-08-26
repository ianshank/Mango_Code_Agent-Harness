# Change: Add Governed Neuro-Symbolic Code Synthesis

## Why
Mango currently contains reusable governance primitives, a resilient NVIDIA-oriented model client, deterministic verification utilities, hooks, and specialized skills. Those capabilities are fragmented and do not yet provide a portable, evidence-backed way to evaluate code-generation strategies against deterministic constraints.

The project needs a reusable control-plane-first synthesis capability that:
- preserves fail-closed governance;
- supports multiple model providers without vendor lock-in;
- safely evaluates generated code;
- measures whether multi-step search earns its cost relative to a simple baseline;
- exports redacted, reproducible evidence rather than unverified claims.

## What Changes
- Extract a versioned governance kernel from `harness/shared`.
- Generalize the model adapter into protocol, resilience, security, and provider layers.
- Add a capability-based execution broker with default-deny sandbox profiles.
- Add an evaluation harness with a single-shot baseline and bounded LATS strategy.
- Add structured critiques, bounded repair attempts, OpenTelemetry traces, and signed evidence manifests.
- Add a portable `neurosym-synthesis` Mango skill.

## Non-Goals
- No autonomous merging or deployment.
- No persistent learned memory or vector-store memory in this change.
- No NL-to-Rego generation in the first release.
- No claim that WASM alone provides sufficient isolation.
- No production default for LATS until ablation thresholds are met.
