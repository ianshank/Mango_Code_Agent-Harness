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

- **INV-1:** secret scan covers working tree and full history and fails closed when tooling is absent, when config is absent, **and when a config is present but declares no ruleset**. `gitleaks --config` *replaces* the built-in rules rather than extending them, so every config must carry `[extend] useDefault = true` or its own `[[rules]]`; all three in this repository declared neither, and the scan reported success on every commit while detecting nothing. Enforced by `test_lint_config_liveness.TestGitleaksActuallyScans`, which parses the TOML rather than grepping it. The allowlist is bounded separately: a path there exempts its whole file from every rule, and asserting only that the path *exists* is how the list reached 23 entries of which 18 suppressed nothing. `make secrets-allowlist-check` (`governance/check_secret_allowlist.py`) scans with the allowlist removed and fails any entry matching no finding; a scan yielding zero findings across the tree is itself a failure, since it cannot be distinguished from a ruleset that is not running. It runs in the `secret-scan` job, never the unit suite, which has no gitleaks and must not gain a skip (INV-2). Entries deliberately kept without a finding are declared in the config beside the entry, inside the `[allowlist]` block — a declaration elsewhere in the file grants nothing (R-GT-10).
- **INV-2:** skipped tests are failures unless the individual test has a live, decision-backed exemption. Node verifies Vitest JSON; Python records every skip the session produced and verifies it through the same gate; JVM listener records evidence and Gradle performs the failing assertion. **Partially enforced:** the Node half runs at root via `make verify-zero-skips`, and since DEC-026 the Python half runs via `make verify-zero-skips-python` — a prerequisite of both `ci` and `ci-python` — reading the TSV the repository-root `conftest.py` writes (DEC-030 moved those hooks up from `harness/shared/tests/conftest.py`, where pytest scoped them to one of the three suites) against `harness/shared/tests/skip-waivers.json`, whose glob waivers widen the address but never the approval: the skip reason must still carry the waiver's `DEC-` id. The JVM half is **not yet enforced** there, because the root `Makefile` declares no `JVM_DIR` and `harness/jvm/Makefile` is an adopter template only its own never-executed workflow invokes.
- **INV-3:** one shared remote URL normalizer/checker is used by Node, JVM, PreToolUse, pre-push and CI. Host is lowercased; path case and significant ports are preserved. **Partially enforced:** `remotes.py` is genuinely the single implementation and runs at root via `make remotes`, but the claim that the JVM stack shares it is **not yet enforced** — no root target runs anything under `harness/jvm`.
- **INV-4:** Git hooks install into Git's effective hooks path and never overwrite an unrelated hook silently.
- **INV-5:** CI invokes every policy-required gate by Make target; meta/self-tests detect omissions and raw reconstructions. **Partially enforced:** `test_ci_gate_coverage.py` maps every `ci_required_targets` entry to a target CI actually reaches, either as a direct `make ci` prerequisite or, like `secrets`, via a dedicated workflow job. One exception remains declared in that gate's own dictionaries — `specs` in `PARTIAL_COVERAGE` (the strict tier is **not yet enforced** at root). `audit` closed its `KNOWN_GAPS` exception via a dedicated `audit` CI job mirroring `secrets` (DEC-013). "Every" is therefore aspirational by one.
- **INV-6:** the project repository is not its own root of trust. High-risk agent authority and the expected policy digest live outside it.
- **INV-7:** agent delegation is bounded and does not transfer authority; every side effect has actor/trace/policy evidence. **Partially enforced:** the delegation clause is checked by `validate_agent_policy.py` (fails closed unless `default_deny` holds, every `delegation_depth` is within `max_delegation_depth`, each role's approval-gated actions are a subset of its allowed actions, and no role may self-modify policy). The evidence clause is **not yet enforced**: `evidence_manifest.py` is live, but nothing cross-checks its coverage against `agent_defaults.evidence_required_for`, as `test_policy_consistency.DECLARED_NOT_YET_ENFORCED` already records.
- **INV-8:** Generated code MUST execute through an approved execution broker.
- **INV-9:** A candidate MUST receive a deterministic policy verdict before execution or scoring, and an execution path whose backend is unavailable MUST return that verdict as a denial — never a host-process fallback. (`broker.py`, `README.md` and `docs/specs/agent-containment.md` all used INV-9 for the second half while this line stated only the first.)
- **INV-10:** A DENY verdict is terminal for that candidate; a model cannot override it.
- **INV-11:** Every repair attempt MUST have a normalized critique and immutable evidence ID. **Not yet enforced**, because there are no repair attempts: no `critique.py`, no `repair_loop.py`, and no occurrence of `repair` or `critique` in the orchestrator. The only check touching it asserts `synthesis.critique_schema_version == "1.0"` — a string in a JSON file that no production path reads, as the *Synthesis policy* note below already states. The mechanism lands with openspec Milestone 5; `DEC-NS-002`, which proposes that schema, is still BLOCKING in a DRAFT spec, so the pinned value is a placeholder rather than a decision.
- **INV-12:** Repair loops MUST stop at the configured budget and produce FAILED or BLOCKED, never a synthetic success. **Not yet enforced**: there is no repair loop to bound. `max_repair_cycles` is asserted to be a bounded positive integer, which checks the policy value's shape and not any loop's behaviour. Lands with openspec Milestone 5.
- **INV-13:** A “verified” result MUST include policy, test, sandbox, source, and tool-version digests. **Not currently satisfiable.** `ProcessBackend` contains — pinned cwd, bounded runtime, capped output, filtered environment — but does not isolate: it confines neither the filesystem nor the network, so there is no sandbox digest to record and no result produced today claims INV-13 (DEC-010). Isolation is a later capability profile; the primitive cannot be exercised on this repository's CI runners. Stated here rather than left to be discovered, because an invariant published as a MUST and enforced by nothing is the shape `test_invariant_liveness.py` exists to catch.
- **INV-14:** Exportable traces MUST be redacted and marked as approved training candidates before dataset export. **Not yet enforced**: no dataset export path exists, so there is nothing to redact or mark. Lands with openspec Milestone 6, which defines the export workflow.
- **INV-15:** LATS MUST remain disabled by default until its cost-adjusted evaluation threshold is met.
- **INV-16:** the cognitive/execution boundary is one-directional — the cognitive plane proposes, the harness disposes. No field of a `CognitiveSignal` (`confidence` and producer identity included) may reach a control path, select a tool or model, or alter tool exposure. Observation-mode producers run with an empty tool schema and receive value objects, never live orchestrator state, and their failures are contained so the incumbent path is unaffected. Enforced by the boundary suite (`pytest -m governance`) and the static boundary scan in `test_shadow_planner.py`.
- **INV-17:** a plan reaching implementation has been checked for the defect classes the plan gate decides. Acceptance criteria that name no observable, that name a check but assign it to a human, that describe only success, or that leave a declared requirement uncited are findings, not style notes. Enforced by `plan_rules.py` via `validate_plan.py` in `make specs`, scoped to plans git reports as modified — landed plans predate the sections these rules read, and back-filling them would mean inventing retrospective plans for shipped work. The rules were calibrated against all fifteen plans in this repository before shipping: three were wrong on first contact with that corpus, and the blocklist they replace fired zero times across 104 acceptance criteria.

## Supply chain

Node requires a committed frozen `pnpm-lock.yaml`. Builds that execute install scripts (e.g., `esbuild`) must be explicitly allowlisted in the committed pnpm 11 configuration (`.npmrc` / `pnpm-workspace.yaml`); undeclared build scripts remain blocked. JVM enables `lockAllConfigurations()` with `LockMode.STRICT` and requires both `gradle.lockfile` and reviewed `gradle/verification-metadata.xml`. Missing security scanners or lock state is a failure, never a clean/no-op pass.

Python's runtime dependencies are pinned by range in `requirements.txt` (mirrored in `pyproject.toml`'s `[project.dependencies]`, kept separate from `requirements-dev.txt`'s tooling pins) and scanned by `make audit` (`pip-audit`), enforced by a dedicated CI job mirroring `secrets` — see `docs/specs/dependency-hygiene.md`.

## Template adoption blockers

CI examples intentionally contain `PIN_FULL_COMMIT_SHA`; adopters must replace each with a reviewed full action SHA in the independently protected onboarding change. JVM wrapper, lockfile and verification metadata must also be generated and reviewed. These are explicit blockers rather than silently insecure defaults.

**`harness/jvm/` is a reference adoption template, not an enforced stack.** It ships a complete Makefile target contract (mirroring `harness/node/`), but nothing under the repository-root `Makefile` or `.github/workflows/` invokes it — `harness/jvm/.github/workflows/ci.yml` exists but is never executed by GitHub, which only discovers workflows under the repo-root `.github/workflows/`. This is the concrete shape of INV-2 and INV-3's "partially enforced" status above: treat `harness/jvm/`'s passing-looking Makefile targets as a starting point for an adopter, not as a live guarantee about this repository's own CI.

## Protected-paths escape hatch

The `protected_paths` policy (see `governance-policy.json`) forbids unreviewed modifications to governance-critical files. Two groups are covered: the **enforcement layer** (`Makefile`, `pyproject.toml`, `.github/workflows/**`, the shared validators, the policy publisher and its committed artifact, and the per-stack roots of trust under `.governance/`), and the **agent control surface** — everything an agent reads to decide what it may do: `CLAUDE.md`, `harness/CONTRACT.md`, `agent-policy.json`, agent role contracts, `.mango/skills/**`, and the `.mango/` and `.claude/` hook and settings files that execute shell. `validate_invariants.py` enforces this at `make validate` / `make ci` time and **fails closed** when a protected path is modified.

`.governance/` currently exists only under `harness/node/.governance/` — there is no root-level `.governance/` directory, even though root-level scripts (`verify_zero_skips.py`, `remotes.py`) consult it by explicit path. This is intentional, not an oversight to fix: DEC-005 rejected creating a root `.governance/allowed-remotes.txt` specifically because `.governance/**` is declared dormant in `protected_paths` (see `test_protected_path_liveness.py`'s `DORMANT_PATTERNS`), part of a deliberate posture that keeps agent-initiated `git push` fail-closed until a human explicitly stands up a root-level root of trust. A future stack wiring its own root of trust should follow the same per-stack pattern unless that posture is revisited with its own decision-log entry.

Since DEC-007 the same matcher also runs at **tool-call granularity**: `harness/shared/write_policy.write_denial_reason` reuses `validate_invariants.is_protected` — one matcher, not two — and is consulted by the orchestrator's `write_file` handler and by `ExecutionBroker` for every target a `run_command` would create or redirect into. It additionally denies any path containing a `.git` segment, which `protected_paths` structurally cannot express: `validate_invariants` enumerates staged, tracked-modified and untracked files, and git never reports anything under `.git`. A policy that cannot be read denies the write. The CI gate remains the *review* gate; the runtime gate closes the tool-call budget between agent boundaries, which the review gate cannot see.

Since DEC-012 there is a read-side counterpart at the same granularity: `harness/shared/read_policy.read_denial_reason`, consulted by the orchestrator's `read_file` handler. It does not consult `protected_paths` — an agent has to read the Makefile and the policies to do its work, and reading is not writing — but it denies credential-bearing filenames (`.env*`, `.netrc`, `*.pem`, ...) and any `.git` path segment, composing the same filename alternation `command_actions.classify` already uses to grade `cat <credential-file>` as `secret_access` for `run_command`. Without it, `read_file` would have been a second, ungoverned door onto exactly the credentials the command classifier already refuses: mapped to the plain `read` action, it would have returned a secret directly rather than denying it. `apply_patch` is not a third mechanism — it calls `write_denial_reason` unchanged, so it reaches no path `write_file` cannot reach, and it grades as the same `write` action, so the verifier receives `read_file` and not `apply_patch`.

Patterns are matched with `fnmatch` against repo-root-relative paths, so a pattern written for a different repository layout matches nothing and protects nothing — silently. `test_protected_path_liveness.py` guards against that by asserting on the set of files each pattern actually matches, and requires any intentionally-dormant pattern to be declared with a reason.

Legitimate infrastructure modernization (CI, Makefile, governance scripts) necessarily touches these paths. Such changes MUST be made on a dedicated branch with an explicit, reviewed decision-log entry, and the protected-path gate is satisfied by setting `ALLOW_GITHUB_CHANGES=1` in the CI environment **for that reviewed change only**. The env var is a per-change attestation of review, not a blanket bypass: it is not set in the default CI environment and must never be committed to a `.env` file.

Untracked files in protected paths are also caught (fail-closed) — `validate_invariants` enumerates staged, tracked-modified, and untracked non-ignored files.

The per-file attestation table that accompanies such a change MUST match the set the gate enforces, and is machine-checked rather than asserted: `harness/shared/governance/attestation.py` derives the table from `validate_invariants`' own matcher and file discovery, and `make attestation-check FILE=<pr-body>` fails closed on a missing attestation section, a section with no table, or any row-to-path mismatch in either direction. `build-full` runs it on every pull request, deliberately **before** and independent of the label that sets `ALLOW_GITHUB_CHANGES` — a reviewer has to be able to read a verified table before attesting to it. A hand-transcribed table had already overstated its own coverage (DEC-038).

## Coverage gate

Coverage thresholds are read dynamically from `governance-policy.json` by `harness/shared/coverage_gate.py`, so the gate and the policy cannot silently drift, and the gate **fails closed**: an unreadable or malformed policy or report aborts `coverage-python` rather than falling back to a weaker literal. (The predecessor `COV_MIN` mechanism degraded to 80 while the policy declared 90 — a gate that lowers itself when it cannot read its own policy.) `pyproject.toml` deliberately declares no competing `fail_under`, and `[tool.coverage.run] branch = true` keeps branch arcs measured — which is also why the gate applies `coverage.lines` and `coverage.branches` as two separate floors instead of gating pytest-cov's blended total.

**Which thresholds are actually enforced.** `governance-policy.json` declares `lines`, `statements`, `functions`, `branches` and `per_file`; since the gate-hardening change every one of them is enforced by the root pipeline:

- **Python** (`coverage_gate.py`): `lines` and `branches` in aggregate, plus `lines` per measured file when `per_file` is true — a single new untested module turns CI red regardless of aggregate headroom.
- **Node** (`vitest.config.ts`, activated by `make test-node`, which runs vitest with `--coverage`): `lines`, `statements`, `branches`, `functions`, and `perFile`.
- `statements` and `functions` have no distinct Python-side metric (coverage.py's statement and line counts are the same measure, and it produces no per-function number); their enforcement is Node-side, recorded with reasons in `test_coverage_policy_enforcement.py`, which fails if a declared threshold key ever loses its enforcement or its classification.

Node thresholds are read from this same policy rather than restated as literals, so the two cannot drift.

The `synthesis` section of `governance-policy.json` carries additional config-driven parameters (`max_repair_cycles`, `lats_enabled`, `critique_schema_version`) that must not be hardcoded in any implementation. They are currently schema-shape guards for an unimplemented feature: no production code path consults them.

`decision_id_pattern` in `governance-policy.json` governs the identifiers in
`.governance/decision-log.md` and nothing else. `check_projections.py` and
`governance/verify_zero_skips.py` rewrite it from `^(...)$` into `\b(...)\b` and use it
as a *scanner* over the log, harvesting the IDs a waiver or projection may cite — never
as a validator that rejects a malformed ID. Area-scoped identifiers appearing in
`openspec/changes/**` (`DEC-NS-002`, `DEC-AE-001`, `DEC-GCP-002`, `DEC-CE-002`) are
proposal-local: they name open questions inside a draft change, are read by no gate, and
carry no authority until the decision is minted as a real `DEC-<n>` entry in a log.

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
