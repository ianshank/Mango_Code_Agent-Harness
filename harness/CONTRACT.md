# Agentic SSD Gate Harness Contract — v2.1

## Core rule

**Gate names and security semantics are cross-stack contracts.** Stack-specific implementation is permitted only when the runtime requires it; security-critical parsing/policy logic is shared byte-for-byte.

## Authority model

1. **External tool broker / PDP** — authoritative for agent network, write, destructive, secret, permission and production actions. It is administered independently of the governed repository.
2. **Local policy decision point + execution broker** — `harness/shared/governance/policy_decision.decide` evaluates each request against `agent-policy.json` in process, and `ExecutionBroker` (`governance/broker.py`) is the approved execution path INV-8 names: it derives the action from the command (`command_actions.classify`, an allowlist whose unmodelled default is an action no role holds), obtains a verdict, applies the write policy to every target the command would create, runs the command guard, and executes with a pinned cwd, a policy-declared timeout, a byte-capped output and an environment stripped of credentials. It **contains but does not isolate** — neither the filesystem nor the network is confined (DEC-010) — and it is **not** the authoritative broker: `tool_broker_reference.py` remains the contract an external broker mirrors, and `test_policy_decision.py` pins that the two agree on every representative request. A local fast control that fails closed, not a replacement for layer 1.
3. **Native pre-push + PreToolUse guards** — execution-time fast controls. They fail closed for the dangerous command families they model, but are not claimed to be impossible to bypass.
4. **Project CI** — authoritative evidence that the evaluated commit conforms to policy. CI is not described as preventing an earlier off-policy network transfer.
5. **Organization required workflow/ruleset** — independently pins the expected governance bundle and protects governance paths.

## Target contract

`install format lint types test cov secrets specs audit remotes projections traceability governance guard-probe pre-pr clean`

`pre-pr` order is exactly: `install lint types cov secrets specs audit remotes projections traceability governance`.

## Invariants

- **INV-1:** secret scan covers working tree and full history and fails closed when tooling is absent, when config is absent, **and when a config is present but declares no ruleset**. `gitleaks --config` *replaces* the built-in rules rather than extending them, so every config must carry `[extend] useDefault = true` or its own `[[rules]]`; all three in this repository declared neither, and the scan reported success on every commit while detecting nothing. Enforced by `test_lint_config_liveness.TestGitleaksActuallyScans`, which parses the TOML rather than grepping it.
- **INV-2:** skipped tests are failures unless the individual test has a live, decision-backed exemption. Node verifies Vitest JSON; JVM listener records evidence and Gradle performs the failing assertion.
- **INV-3:** one shared remote URL normalizer/checker is used by Node, JVM, PreToolUse, pre-push and CI. Host is lowercased; path case and significant ports are preserved.
- **INV-4:** Git hooks install into Git's effective hooks path and never overwrite an unrelated hook silently.
- **INV-5:** CI invokes every policy-required gate by Make target; meta/self-tests detect omissions and raw reconstructions.
- **INV-6:** the project repository is not its own root of trust. High-risk agent authority and the expected policy digest live outside it.
- **INV-7:** agent delegation is bounded and does not transfer authority; every side effect has actor/trace/policy evidence.
- **INV-8:** Generated code MUST execute through an approved execution broker.
- **INV-9:** A candidate MUST receive a deterministic policy verdict before execution or scoring, and an execution path whose backend is unavailable MUST return that verdict as a denial — never a host-process fallback. (`broker.py`, `README.md` and `docs/specs/agent-containment.md` all used INV-9 for the second half while this line stated only the first.)
- **INV-10:** A DENY verdict is terminal for that candidate; a model cannot override it.
- **INV-11:** Every repair attempt MUST have a normalized critique and immutable evidence ID.
- **INV-12:** Repair loops MUST stop at the configured budget and produce FAILED or BLOCKED, never a synthetic success.
- **INV-13:** A “verified” result MUST include policy, test, sandbox, source, and tool-version digests. **Not currently satisfiable.** `ProcessBackend` contains — pinned cwd, bounded runtime, capped output, filtered environment — but does not isolate: it confines neither the filesystem nor the network, so there is no sandbox digest to record and no result produced today claims INV-13 (DEC-010). Isolation is a later capability profile; the primitive cannot be exercised on this repository's CI runners. Stated here rather than left to be discovered, because an invariant published as a MUST and enforced by nothing is the shape `test_invariant_liveness.py` exists to catch.
- **INV-14:** Exportable traces MUST be redacted and marked as approved training candidates before dataset export.
- **INV-15:** LATS MUST remain disabled by default until its cost-adjusted evaluation threshold is met.
- **INV-16:** the cognitive/execution boundary is one-directional — the cognitive plane proposes, the harness disposes. No field of a `CognitiveSignal` (`confidence` and producer identity included) may reach a control path, select a tool or model, or alter tool exposure. Observation-mode producers run with an empty tool schema and receive value objects, never live orchestrator state, and their failures are contained so the incumbent path is unaffected. Enforced by the boundary suite (`pytest -m governance`) and the static boundary scan in `test_shadow_planner.py`.

## Supply chain

Node requires a committed frozen `pnpm-lock.yaml`. Builds that execute install scripts (e.g., `esbuild`) must be explicitly allowlisted in the committed pnpm 11 configuration (`.npmrc` / `pnpm-workspace.yaml`); undeclared build scripts remain blocked. JVM enables `lockAllConfigurations()` with `LockMode.STRICT` and requires both `gradle.lockfile` and reviewed `gradle/verification-metadata.xml`. Missing security scanners or lock state is a failure, never a clean/no-op pass.

## Template adoption blockers

CI examples intentionally contain `PIN_FULL_COMMIT_SHA`; adopters must replace each with a reviewed full action SHA in the independently protected onboarding change. JVM wrapper, lockfile and verification metadata must also be generated and reviewed. These are explicit blockers rather than silently insecure defaults.

## Protected-paths escape hatch

The `protected_paths` policy (see `governance-policy.json`) forbids unreviewed modifications to governance-critical files. Two groups are covered: the **enforcement layer** (`Makefile`, `pyproject.toml`, `.github/workflows/**`, the shared validators, the policy publisher and its committed artifact, and the per-stack roots of trust under `.governance/`), and the **agent control surface** — everything an agent reads to decide what it may do: `CLAUDE.md`, `harness/CONTRACT.md`, `agent-policy.json`, agent role contracts, `.mango/skills/**`, and the `.mango/` and `.claude/` hook and settings files that execute shell. `validate_invariants.py` enforces this at `make validate` / `make ci` time and **fails closed** when a protected path is modified.

Since DEC-007 the same matcher also runs at **tool-call granularity**: `harness/shared/write_policy.write_denial_reason` reuses `validate_invariants.is_protected` — one matcher, not two — and is consulted by the orchestrator's `write_file` handler and by `ExecutionBroker` for every target a `run_command` would create or redirect into. It additionally denies any path containing a `.git` segment, which `protected_paths` structurally cannot express: `validate_invariants` enumerates staged, tracked-modified and untracked files, and git never reports anything under `.git`. A policy that cannot be read denies the write. The CI gate remains the *review* gate; the runtime gate closes the tool-call budget between agent boundaries, which the review gate cannot see.

Patterns are matched with `fnmatch` against repo-root-relative paths, so a pattern written for a different repository layout matches nothing and protects nothing — silently. `test_protected_path_liveness.py` guards against that by asserting on the set of files each pattern actually matches, and requires any intentionally-dormant pattern to be declared with a reason.

Legitimate infrastructure modernization (CI, Makefile, governance scripts) necessarily touches these paths. Such changes MUST be made on a dedicated branch with an explicit, reviewed decision-log entry, and the protected-path gate is satisfied by setting `ALLOW_GITHUB_CHANGES=1` in the CI environment **for that reviewed change only**. The env var is a per-change attestation of review, not a blanket bypass: it is not set in the default CI environment and must never be committed to a `.env` file.

Untracked files in protected paths are also caught (fail-closed) — `validate_invariants` enumerates staged, tracked-modified, and untracked non-ignored files.

## Coverage gate

Coverage thresholds are read dynamically from `governance-policy.json` by `harness/shared/coverage_gate.py`, so the gate and the policy cannot silently drift, and the gate **fails closed**: an unreadable or malformed policy or report aborts `coverage-python` rather than falling back to a weaker literal. (The predecessor `COV_MIN` mechanism degraded to 80 while the policy declared 90 — a gate that lowers itself when it cannot read its own policy.) `pyproject.toml` deliberately declares no competing `fail_under`, and `[tool.coverage.run] branch = true` keeps branch arcs measured — which is also why the gate applies `coverage.lines` and `coverage.branches` as two separate floors instead of gating pytest-cov's blended total.

**Which thresholds are actually enforced.** `governance-policy.json` declares `lines`, `statements`, `functions`, `branches` and `per_file`; since the gate-hardening change every one of them is enforced by the root pipeline:

- **Python** (`coverage_gate.py`): `lines` and `branches` in aggregate, plus `lines` per measured file when `per_file` is true — a single new untested module turns CI red regardless of aggregate headroom.
- **Node** (`vitest.config.ts`, activated by `make test-node`, which runs vitest with `--coverage`): `lines`, `statements`, `branches`, `functions`, and `perFile`.
- `statements` and `functions` have no distinct Python-side metric (coverage.py's statement and line counts are the same measure, and it produces no per-function number); their enforcement is Node-side, recorded with reasons in `test_coverage_policy_enforcement.py`, which fails if a declared threshold key ever loses its enforcement or its classification.

Node thresholds are read from this same policy rather than restated as literals, so the two cannot drift.

The `synthesis` section of `governance-policy.json` carries additional config-driven parameters (`max_repair_cycles`, `lats_enabled`, `critique_schema_version`) that must not be hardcoded in any implementation. They are currently schema-shape guards for an unimplemented feature: no production code path consults them.

## Evidence signing

`EvidenceBuilder` (`harness/shared/governance/evidence_manifest.py`) requires a signing key sourced from the `AGENT_EVIDENCE_KEY` environment variable or injected via the `signing_key` constructor parameter. Constructor injection takes precedence over the environment variable. A missing key raises `ValueError` (not `OSError`) at `export()` time. The insecure hardcoded fallback key was removed in v2.1; fail-closed behavior is mandatory. See `.mango/skills/evidence-signing/SKILL.md` for the reusable skill.

## Python compatibility gate

`check_py_compat.py` enforces that all first-party Python uses only syntax available in the minimum CI matrix version (currently 3.9). It detects: PEP 604 union syntax (`X | Y`), `datetime.UTC` (3.11+), and annotated assignments (`ast.AnnAssign`) that use union types without `from __future__ import annotations`. Run via `make check-compat`.

## Regression / AQA tier

`harness/shared/tests/regression/` holds one reproduction per defect that has
already reached `main`. Every module there was confirmed **failing against the
pre-fix commit** before its fix landed; a test in that directory that cannot
fail is worse than no test, because it converts an open question into a false
assurance.

The tier is selected **by path**, not by a pytest marker: the directory is
already the selector, and a marker would additionally have to be registered in
`pyproject.toml` for no extra selectivity. Run it alone with
`make test-regression`; it also runs inside `make test-python`, and therefore
inside `make ci`, which `test_makefile_contracts.py` pins.

## Static analysis: what is enforced, and what is deliberately not

Every ruff rule and mypy flag is either **selected** or **recorded as deferred
with the finding count that justified deferring it**. `test_deferred_rigor.py`
is the register, and it fails in both directions: a deferral that names a
now-enabled rule is stale cover and must be deleted, and a rule whose cost has
fallen below its recorded revisit threshold must be enabled or re-argued.

Two selections were bought with real work and must not be dropped silently:

- **`BLE`** — the repository carried 16 `# noqa: BLE001` comments explaining why
  particular broad `except Exception` handlers are deliberate fail-closed
  boundaries. With `BLE` unselected those comments were inert prose. Selecting
  it turned all 27 into enforced decisions.
- **`RUF100`** — safe *only because* `BLE` is on. It previously flagged 20 inert
  `noqa` directives, 13 of which were exactly those `BLE001` justifications, so
  enabling it alone would have invited deleting the reasoning. With `BLE`
  selected the count drops to the genuinely dead directives, and `RUF100` now
  keeps every `noqa` in the tree load-bearing.

mypy runs with `--check-untyped-defs` (via `MYPY_FLAGS`), which checks the
bodies of unannotated functions — where latent test defects live, such as a
`re.search(...).group()` that raises `AttributeError` instead of failing with a
message. Measured at 14 findings, all fixed in the change that enabled it.
Full `--strict` (604) and `--disallow-untyped-defs` (533) are deferred: both
are dominated by `no-untyped-def` on test functions, which buys annotations
rather than correctness.

## Configuration liveness

Suppressions and allowlists are write-only unless something checks them, so two
gates keep them honest:

- `test_lint_config_liveness.py` — every `per-file-ignores` pattern must still
  match a file, and every code in it must still suppress a real finding
  (measured with `ruff --isolated`, since a normal run applies the very ignores
  under test). Ruff has no unused-ignore check for config-level ignores, so
  without this a one-time prune simply rots again. It also asserts every literal
  path in `.gitleaks.toml`'s allowlist still exists — an allowlist entry that
  outlives its file is a widening blind spot.
- `test_import_purity.py` — every module under `harness/shared` and
  `harness/control-plane` must import, from a working directory that is *not*
  the repo root, with exit 0, empty stdout, and no writes. Modules that still
  act at import are declared in `KNOWN_IMPORT_SIDE_EFFECTS` with a reason, and
  the declaration self-destructs: a separate test fails once the module imports
  cleanly, so a waiver cannot outlive the defect it describes.
