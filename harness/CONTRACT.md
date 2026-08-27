# Agentic SSD Gate Harness Contract — v2.1

## Core rule

**Gate names and security semantics are cross-stack contracts.** Stack-specific implementation is permitted only when the runtime requires it; security-critical parsing/policy logic is shared byte-for-byte.

## Authority model

1. **External tool broker / PDP** — authoritative for agent network, write, destructive, secret, permission and production actions. It is administered independently of the governed repository.
2. **Native pre-push + PreToolUse guards** — execution-time fast controls. They fail closed for the dangerous command families they model, but are not claimed to be impossible to bypass.
3. **Project CI** — authoritative evidence that the evaluated commit conforms to policy. CI is not described as preventing an earlier off-policy network transfer.
4. **Organization required workflow/ruleset** — independently pins the expected governance bundle and protects governance paths.

## Target contract

`install format lint types test cov secrets specs audit remotes projections traceability governance guard-probe pre-pr clean`

`pre-pr` order is exactly: `install lint types cov secrets specs audit remotes projections traceability governance`.

## Invariants

- **INV-1:** secret scan covers working tree and full history and fails closed when tooling/config is absent.
- **INV-2:** skipped tests are failures unless the individual test has a live, decision-backed exemption. Node verifies Vitest JSON; JVM listener records evidence and Gradle performs the failing assertion.
- **INV-3:** one shared remote URL normalizer/checker is used by Node, JVM, PreToolUse, pre-push and CI. Host is lowercased; path case and significant ports are preserved.
- **INV-4:** Git hooks install into Git's effective hooks path and never overwrite an unrelated hook silently.
- **INV-5:** CI invokes every policy-required gate by Make target; meta/self-tests detect omissions and raw reconstructions.
- **INV-6:** the project repository is not its own root of trust. High-risk agent authority and the expected policy digest live outside it.
- **INV-7:** agent delegation is bounded and does not transfer authority; every side effect has actor/trace/policy evidence.
- **INV-8:** Generated code MUST execute through an approved execution broker.
- **INV-9:** A candidate MUST receive a deterministic policy verdict before execution or scoring.
- **INV-10:** A DENY verdict is terminal for that candidate; a model cannot override it.
- **INV-11:** Every repair attempt MUST have a normalized critique and immutable evidence ID.
- **INV-12:** Repair loops MUST stop at the configured budget and produce FAILED or BLOCKED, never a synthetic success.
- **INV-13:** A “verified” result MUST include policy, test, sandbox, source, and tool-version digests.
- **INV-14:** Exportable traces MUST be redacted and marked as approved training candidates before dataset export.
- **INV-15:** LATS MUST remain disabled by default until its cost-adjusted evaluation threshold is met.
- **INV-16:** the cognitive/execution boundary is one-directional — the cognitive plane proposes, the harness disposes. No field of a `CognitiveSignal` (`confidence` and producer identity included) may reach a control path, select a tool or model, or alter tool exposure. Observation-mode producers run with an empty tool schema and receive value objects, never live orchestrator state, and their failures are contained so the incumbent path is unaffected. Enforced by the boundary suite (`pytest -m governance`) and the static boundary scan in `test_shadow_planner.py`.

## Supply chain

Node requires a committed frozen `pnpm-lock.yaml`. Builds that execute install scripts (e.g., `esbuild`) must be explicitly allowlisted in the committed pnpm 11 configuration (`.npmrc` / `pnpm-workspace.yaml`); undeclared build scripts remain blocked. JVM enables `lockAllConfigurations()` with `LockMode.STRICT` and requires both `gradle.lockfile` and reviewed `gradle/verification-metadata.xml`. Missing security scanners or lock state is a failure, never a clean/no-op pass.

## Template adoption blockers

CI examples intentionally contain `PIN_FULL_COMMIT_SHA`; adopters must replace each with a reviewed full action SHA in the independently protected onboarding change. JVM wrapper, lockfile and verification metadata must also be generated and reviewed. These are explicit blockers rather than silently insecure defaults.

## Protected-paths escape hatch

The `protected_paths` policy (see `governance-policy.json`) forbids unreviewed modifications to governance-critical files (`Makefile`, `.github/workflows/**`, the shared validators, agent contracts, and the root of trust). `validate_invariants.py` enforces this at `make validate` / `make ci` time and **fails closed** when a protected path is modified.

Legitimate infrastructure modernization (CI, Makefile, governance scripts) necessarily touches these paths. Such changes MUST be made on a dedicated branch with an explicit, reviewed decision-log entry, and the protected-path gate is satisfied by setting `ALLOW_GITHUB_CHANGES=1` in the CI environment **for that reviewed change only**. The env var is a per-change attestation of review, not a blanket bypass: it is not set in the default CI environment and must never be committed to a `.env` file.

Untracked files in protected paths are also caught (fail-closed) — `validate_invariants` enumerates staged, tracked-modified, and untracked non-ignored files.

## Coverage gate

The coverage threshold (`COV_MIN`) is read dynamically from `governance-policy.json` (`coverage.lines`, default 80 if unreadable) so the gate and the policy cannot silently drift. The gate enforces aggregate coverage across all first-party Python modules; per-file enforcement is a documented follow-up. The `synthesis` section of `governance-policy.json` carries additional config-driven parameters (`max_repair_cycles`, `lats_enabled`, `critique_schema_version`) that must not be hardcoded in any implementation.

## Evidence signing

`EvidenceBuilder` (`harness/shared/governance/evidence_manifest.py`) requires a signing key sourced from the `AGENT_EVIDENCE_KEY` environment variable or injected via the `signing_key` constructor parameter. Constructor injection takes precedence over the environment variable. A missing key raises `ValueError` (not `OSError`) at `export()` time. The insecure hardcoded fallback key was removed in v2.1; fail-closed behavior is mandatory. See `.mango/skills/evidence-signing/SKILL.md` for the reusable skill.

## Python compatibility gate

`check_py_compat.py` enforces that all first-party Python uses only syntax available in the minimum CI matrix version (currently 3.9). It detects: PEP 604 union syntax (`X | Y`), `datetime.UTC` (3.11+), and annotated assignments (`ast.AnnAssign`) that use union types without `from __future__ import annotations`. Run via `make check-compat`.
