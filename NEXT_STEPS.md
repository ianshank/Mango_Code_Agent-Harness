# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.2.4  
**Status:** In Progress / Strategic Roadmap

---

## 0. Completed Milestones

### 🚧 Tech-debt reduction, LangGraph policy wiring & enterprise hygiene batch (PR #53, in review)

A full audit (3 parallel research passes) whose draft plan was itself put
through a 4-persona peer review (Architect, SDLC/CI Lead, QA Director,
Product Manager) before implementation — the review caught that the
flagship finding targeted code no CI job installs `langgraph` for, and
surfaced a second, more severe bug the first draft missed. Spec:
`docs/specs/langgraph-policy-wiring.md`.

- [x] **`GraphPolicy` fully wired to `governance-policy.json`**: `recursion_limit`,
      `max_concurrency`, `plan_divergence_threshold` were never read from
      policy at all; `graph.py`'s `_route_quality_gate()` and `nodes.py`'s
      `plan_gate_node()` used raw literals (`10`, `0.35`) instead of
      consulting it. Both now read policy via `config["configurable"]["policy"]`,
      the same mechanism already used for `orchestrator`, with a
      behavior-preserving fallback when none is supplied.
- [x] **Fail-open bug fixed**: `GraphPolicy.from_governance_json()` silently
      substituted defaults on a *malformed* policy, not just an absent one —
      the sixth recurrence of this exact pattern in the decision log. Now
      raises. The existing test for this code asserted nothing that could
      distinguish wiring from coincidence; rewritten with a
      distinguishable-value liveness test and a malformed-policy fixture.
- [x] **Enterprise hygiene**: `.github/CODEOWNERS`, PR/issue templates,
      `SECURITY.md`, `CONTRIBUTING.md`.
- [x] **Evidence-checked coverage-gap closure**: direct tests for
      `agent_prompts.py`, `tool_result_format.py`, `tool_schemas.py` — each
      confirmed to have a real gap first; `tool_dispatch.py` dropped from
      scope after confirming it's already well covered.
- [x] **Two hard-coded-value fixes**: `api_server/main.py`'s dev-runner host
      is now env-overridable; `process_backend.py`'s `DEFAULT_TIMEOUT_SEC`
      now reads policy instead of an unlinked duplicate literal.
- [x] **`.mango/agents/nemotron-reasoner.md`'s `tools:` frontmatter fixed** —
      open since `SDLC_HYGIENE_REPORT.md` (2026-08-26); the existing test
      didn't catch it because it checked the whole file's text, satisfied by
      a prose mention alone. New test asserts the parsed frontmatter field.
- [x] **Two diverged C4 docs reconciled** with a banner (not a destructive
      merge — the older doc's content is still detailed and partly unique).
- [x] **Two tech-debt findings recorded as accepted debt** (DEC-019, DEC-020)
      rather than left ambiguous: the control-plane `digest()` triplication
      is intentional (root-of-trust isolation); `harness/shared/gates/`
      adopted as the convention for new gate modules, not a migration.
- [x] **Fixed a live `R-CEG-1` regression**: `pyproject.toml` still said
      `2.1.9` while `README.md`/this file had already moved to `2.2.4`.
- [ ] **Not yet green**: CI requires the `infra-reviewed` label (this batch
      touches multiple protected paths, each individually attested in its
      commit message) — a human sign-off step, not something this batch can
      self-certify.

### ✅ v2.2.4 — LangGraph StateGraph Multi-Agent Architecture & Deterministic Node Orchestration

- [x] **12-Channel Typed State Architecture (`MangoState`)**: Designed and implemented the 12-channel StateGraph schema with partitioned Accumulator channels (reduced via `operator.add`) and LWW channels.
- [x] **10 Topology Nodes & Dynamic Parameter Ingestion**: Implemented 10 topology nodes with fail-open error isolation and runtime configuration extraction supporting both positional and keyword invocation.
- [x] **Active Node Wiring**: Connected `planner_node`, `implementer_node` (reasoner), and `evaluation_node` (verifier + `VerificationRunner`) to the active orchestrator.
- [x] **Authority & Budget Decorators (`@with_authority`, `@budgeted`)**: Enforced role-based write gates and per-task tool invocation budgets at node boundaries.
- [x] **AQA Regression Suite (`test_langgraph_regression.py`)**: Added 32 automated regression tests covering calling conventions, state immutability, accumulator concatenation, error trapping, and divergence thresholds.
- [x] **C4 Architecture v2.2.4**: Updated Level 1-4 diagrams and documented LangGraph invariants (`INV-LG-1` .. `INV-LG-4`).

### ✅ v2.2.3 — Live NVIDIA Nemotron NIM Multi-Domain Triage, RCA & Autonomous MAS Certification

- [x] **Live Multi-Domain E2E Defect Triage & RCA (`docs/rca/e2e_nemotron_live_triage_rca.md`)**: Triaged and remediated 10 defects across cross-platform newline preservation, credentials discovery, scratch workspace prompt fallback, cross-drive workspace confinement, discard stream filtering, verifier verdict guarantees, python execution in command actions, tool version queries, prompt chaining, and cryptographic policy-bundle digest synchronization.
- [x] **Command Broker Action Classification & Tool Discovery**: Added `test_execute` for `python [flags] script.py` and `python -m (pytest|unittest|py_compile|doctest)`, `read` for tool version queries (`--version`, `-V`, `command -v`), and excluded stream bit buckets (`/dev/null`, `nul`, `NUL`, `/dev/zero`, `/dev/stdout`, `/dev/stderr`) from write target checks.
- [x] **Multi-Domain Live MAS E2E Scenarios**: Validated full multi-agent sequential thinking loop (`calculate_fibonacci`), multi-file application synthesis (`DataValidator`), and symbolic mathematical reasoning (`prime_factors`) with 100% pass rate.
- [x] **AQA Regression Suite (`test_e2e_nemotron_triage_regression.py`)**: 11 new automated regression tests integrated into the test matrix, bringing the total regression suite to 132 tests.
- [x] **Live Ecosystem Parity**: Verified end-to-end against live NVIDIA Nemotron NIM endpoints across Python (`test_nemotron_bridge_live.py`, `test_mango_mas_live.py`, `test_neurosym_sandbox_e2e.py`) and Node TypeScript (`vitest run`).
- [x] **Cryptographic Governance Bundle**: Synchronized all SHA256 digests in `policy-bundle.example.json` with zero drift.

### ✅ v2.2.1 — Neuro-Symbolic Sandbox Synthesis, Critique Normalization & E2E Validation

- [x] **Critique Normalization (`AC-NS-3`)**: Implemented normalization in `tool_result_format.py` for sandbox violations (`network_access_denied`, capability constraints) into structured critiques with backwards-compatible error handling.
- [x] **Deterministic Sandbox E2E Matrix (`test_neurosym_sandbox_e2e.py`)**: Verified `INV-9` fail-closed backend checks, `AC-CE-1` capability profiles, and `AC-NS-3` multi-turn critique repair loops.
- [x] **Regression & AQA Suite**: Expanded with `test_sandbox_violation_regression.py`, achieving 1,779 passing tests across 7 tiers with 97% code coverage.
- [x] **Invariants Performance Optimization**: Replaced recursive directory scans with pruned `os.walk` in `validate_invariants.py`.

### 🚧 Direct file I/O: `read_file` / `apply_patch` (PR #32, in review)

- [x] **`read_file`**: reads workspace files directly and verbatim (no line-number prefixes, so output pastes straight into `apply_patch`'s `old_text`), bounded by the same output cap and `[truncated at N bytes]` marker `run_command` uses.
- [x] **`apply_patch`**: replaces one exactly-unique substring in place, refusing (and naming the count) unless `old_text` matches exactly once, and preserving the file's existing line endings byte-for-byte (`harness/shared/tool_executors.py`).
- [x] **`read_policy.py`** (`DEC-012`): the read-side counterpart to `write_policy.py`. Composes one shared credential-filename pattern verified by `test_read_file_credential_parity.py`. Spec: [`docs/specs/agent-read-patch-tools.md`](docs/specs/agent-read-patch-tools.md).
- [x] **`.env.example` correctness**: `NEMOTRON_DEFAULT_MODEL` corrected and pinned by `test_documentation_truth.py`.

### ✅ v2.2.0 — God-File Decomposition, Codebase Hardening & Live E2E Readiness

- [x] **God-File Refactoring (`R-GFD-1` .. `R-GFD-8`)**: Decomposed monolithic orchestrator and governance files into modular components (`tool_executors.py`, `tool_dispatch.py`, `agent_prompts.py`, `process_backend.py`, `ast_visitors.py`). `R-GFD-4` (the AST-inspection helpers out of `check_py_compat.py`) was the one requirement left open behind this checkbox until the follow-up change recorded at the top of `## [Unreleased]` in `CHANGELOG.md` closed it — all eight requirements are now verified against the actual tree, not carried over from the original PR description.
- [x] **PEP 585 / UP035 Type Modernization**: Replaced legacy typing aliases with modern standard library constructs across all modules and tests.
- [x] **Cross-Platform Hardening**: Resolved Windows/NTFS path resolution and quoting edge cases, verified across 20 new regression tests.
- [x] **C4 Architecture & Specifications**: Completed traceable specification [`docs/specs/god-file-decomposition.md`](docs/specs/god-file-decomposition.md) and full C4 architecture model in [`docs/architecture/c4_architecture.md`](docs/architecture/c4_architecture.md).
- [x] **Strict Quality Gates**: 0 Ruff lint errors, 145/145 Python 3.9+ compatible files, and 1,696 passed tests.

### 🚧 v2.1.10 — Remediation programme v3 (in review)

An objective peer review of the v2 tech-debt programme (PRs #15-#19), shipped
as three sequential PRs so each `infra-reviewed` attestation answers one
question.

- [x] **PR A — runtime correctness** (no label): six defects in the Nemotron
      bridge, the MAS orchestrator and the API server, each pinned by a
      regression test confirmed failing against the pre-fix commit. Introduces
      the regression/AQA tier and two extracted modules (`retry_policy.py`,
      `debug_dump.py`).
- [x] **PR B — gate reach** (labelled): import purity becomes a rule rather
      than a series of fixes; bare `pytest` passes again; lint and mypy expand
      by measurement, with every decline recorded against its finding count.
- [x] **PR C — agent surface** (labelled): skills dated and classified, hook
      invocation and path references corrected while staying dormant per
      DEC-003, session-start brought to parity with `make ci`, and the first
      scheduled (notify-only) automation in the repository.

**Deliberately out of scope**, because #18 and #19 already implement them and
duplicating on `main` would conflict with reviewed work: policy
single-sourcing, the cumulative tool-call budget, per-file coverage
enforcement, and the policy-loaded decision-ID grammar.

**Follow-ups this programme identified but did not take:**

- Enable per-file **branch** enforcement once #19 lands (`per_file_branches`);
  it needs the per-file machinery that only exists there.
- ~~Enable `DTZ` (8 findings) once #18 lands~~ — done: `DTZ` is live in
  `pyproject.toml`'s `[tool.ruff.lint].select`, confirmed by direct read
  (2026-08-31).
- ~~Six files sit below the per-file coverage floor on `main`~~ — re-checked
  2026-08-31 via `make coverage-python` against current `main`: all 61
  measured files, including the six named here, now pass the 90% per-file
  lines floor (`publish_policy_artifact.py` 100%, `check_traceability.py`
  100% lines, `coverage_gate.py` 94%, `governance/pretooluse_guard.py` 97%,
  `validate_adoption.py` 97%, `validate_invariants.py` 100%). No further work
  needed here.
- Annotating the test suite is a separate project: `--disallow-untyped-defs`
  reports 533 findings, essentially all `no-untyped-def` on test functions.

> **Document scope:** this file is the single roadmap for the repository.
> The former `NEXT_STEPS_PLAN_v2.md` phased implementation plan was retired in
> v2.1.10 hygiene: its Phase 0/1 items shipped (PRs #7, #9, #11, #13, #14) and
> its remaining themes (per-file coverage enforcement, policy single-sourcing,
> gate hardening) are tracked in `docs/specs/` under the tech-debt reduction
> program.

### ✅ v2.1.9 — Governance Follow-Ups (protected-path frame, CI wiring, Docker)

Lands the findings v2.1.8 recorded rather than patched, each of which needed a
protected-path change and therefore the `infra-reviewed` human attestation.
Shipped as three PRs so the label-free Docker fix did not wait behind a label
round-trip.

- [x] **`protected_paths` patterns that matched zero files are now live.** Root
      cause was an incomplete layout migration in `1eb2f7f`, which converted only
      the `scripts/*` entries by replacement and left `.governance/**`,
      `agents/**`, `docs/PROJECT-CHARTER.md` and `.github/CODEOWNERS` in the
      single-stack frame. `fnmatch` is whole-string anchored, so they matched
      nothing and the gate reported PASS *because nothing matched*.
- [x] **The agent control surface is gated** — `CLAUDE.md`, `harness/CONTRACT.md`,
      `.mango/skills/**`, `agent-policy.json`, the `.claude/`/`.mango/` hook and
      settings files, `pyproject.toml`, and the policy publisher plus its
      committed drift baseline. Protected files: 37 → 104. DEC-002 records the
      measured workflow cost (~32% of historical commits); DEC-003 records that
      the five unbound `.mango/hooks/` scripts stay dormant.
- [x] **`test_protected_path_liveness.py`** replaces the tautology that let the
      dead patterns through (`assertIn(pattern_string, policy_list)` passes
      whether or not the pattern protects anything). Asserts on matched file
      sets; 14/14 mutants killed, including narrowings that keep the pattern list
      looking plausible. `validate_invariants.is_protected` extracted so the
      suite measures the real matcher.
- [x] **`specs` wired into `make ci`** as `bash harness/shared/validate_specs.sh`
      — the file is mode 644, so a bare `./` invocation would have been red CI.
- [x] **`harness/control-plane` measured by the coverage gate** (95.69% → 92.97%),
      making `publish_policy_artifact.py` governed. Three module-scope-argparse
      CLIs omitted as measurement artifacts; `regenerate_bundle_digests.py` kept
      measured because its 0% is a real gap.
- [x] **The Dockerfile bug is confirmed and fixed, not just flagged.** v2.1.8
      could not verify it (no daemon); this milestone reproduced it against a
      real daemon — `COPY .mango/` fails with `"/.mango": not found`, while a
      `COPY harness/` control build succeeds. Also fixed two `.dockerignore`
      rules with the same anchoring bug, A/B tested by exporting the context.
- [x] **INV-1 had no live enforcement.** The gitleaks steps live in
      `harness/{node,jvm}/.github/workflows/ci.yml`, which are adopter templates
      GitHub never executes — it reads workflows only from the repository-root
      `.github/workflows/`. Added a root `secrets` gate (fails closed on missing
      tooling; scans working tree *and* full history) and a dedicated `secret-scan`
      CI job with `fetch-depth: 0`. **The verification recorded here was
      vacuous:** all three `.gitleaks.toml` files declared an `[allowlist]` and
      no `[[rules]]`, and `--config` *replaces* gitleaks' built-in ruleset
      rather than extending it — so the scan ran with zero rules and could not
      have found a secret in any file or any commit. Armed in the containment
      programme (`[extend] useDefault = true` in all three configs) and pinned
      by `test_lint_config_liveness.TestGitleaksActuallyScans`; clean on the
      working tree under the real ruleset.
- [x] **`make remotes` wired** — INV-3 had a shared implementation and a per-stack
      target but no root wiring.
- [x] **INV-5 is now enforced by `test_ci_gate_coverage.py`**: every
      `ci_required_targets` entry must map to a root target CI actually invokes, or
      be a declared gap with a reason. `specs` (the strict/openspec tier) is the
      single remaining declared gap; `audit` closed via a dedicated CI job
      (DEC-013). 12/12 mutants killed.
- [x] Documentation corrected where it contradicted the contract: the pre-PR
      reference misnumbered INV-5 and INV-7, and two hard-coded 80% coverage
      thresholds contradicted the policy value of 90.
- [ ] Remaining open, and **the highest-value item on this list**: `main` has no
      branch ruleset — CI is not a required check, and 0 of 8 PRs were approved
      before merge. Every gate above is advisory until one exists. A
      repository-settings change, not code.

      Required status checks (derived from `.github/workflows/python-package.yml`,
      not from memory): `build (3.9)`, `build (3.10)`, `build (3.12)`,
      `build-full`, `secret-scan`, `dependency-audit`, `dependency-audit (3.9)`,
      `dependency-audit (3.10)`, `dependency-audit (3.12)`.

      `build (3.x)` runs `make ci-python`; `build-full` (Python 3.11) is the
      only leg that runs `make ci`, the Node stack and the regression tier;
      `secret-scan` is a dedicated job because it is genuinely interpreter-
      independent (gitleaks doesn't care which Python runs it). `dependency-audit`
      is dedicated for the opposite reason: its outcome *is* interpreter-specific
      (DEC-015/DEC-017), which is exactly why it further splits into a single-
      interpreter `audit` job and the matrixed `audit-matrix` legs rather than
      folding into `build`. `dependency-audit (3.9)` sets `continue-on-error`
      at the step level, per DEC-017 (unpatchable CVEs on that interpreter), so
      the job's reported conclusion is success regardless of what `pip-audit`
      finds. Requiring it as a status check only ensures the leg keeps running
      and reporting — a rename or silent removal would surface as this repo's
      own liveness test failing — not that a new vulnerability on that leg
      could ever block a merge; that finding stays visible solely in the job's
      own log.

      This item previously listed only 5 checks — the three `build (3.x)` legs,
      `build-full` and `secret-scan` — and omitted `dependency-audit` and its
      three matrix legs entirely, added by DEC-013/DEC-016/DEC-017 after that
      list was last written. `test_ci_gate_coverage.py` now asserts this list
      against the workflow file mechanically, so it cannot drift silently
      again the way it did between the two paragraphs above.
- [x] **`audit` (dependency vulnerability scanning) is now enforced at root**
      (DEC-013): `make audit` runs `pip-audit` against `requirements.txt` and
      delegates to the Node stack's existing `osv-scanner` target, enforced by
      a dedicated `audit` CI job (mirroring `secrets`, kept out of the
      per-matrix-leg `ci`/`ci-python` run since it's interpreter-independent).
- [ ] **Wire `lint-node` into `ci`** once the `typescript` 7.0.2 /
      `typescript-eslint` 8.67.0 incompatibility breaking `make lint-node` is
      resolved (bump `typescript-eslint` or pin `typescript` back to a
      supported 6.x release, then re-verify the whole Node suite). Tracked in
      `docs/specs/ci-enforcement-gaps.md`'s Open questions (DEC-013).
- [x] **Three more gates failed open, and one gate module was left unprotected.**
      `size_budget_lines`, `check_dedup.load_config` and
      `check_py_compat.load_skip_dirs` all degraded to their built-in defaults on
      a malformed policy — the same inversion `COV_MIN` had, missed three more
      times while fixing the first. All three now separate *absent* (the adopter
      path, still defaults) from *malformed* (exit 1 with the reason). Because
      every default was byte-identical to its policy value, each gate also gained
      a probe driving a distinguishable value through to the behaviour.
      `test_coverage_policy_enforcement.py` is now protected and in the
      `CRITICAL_PATTERNS` floor. 5/5 mutants killed.
- [x] **The `specs` gate has behavioural tests.** It was wired into `make ci`
      with only a name check behind it — the script could have been gutted to
      `exit 0` with the suite green. `test_validate_specs.py` drives it against
      fixtures; 8/8 mutants killed. Its strict tier (`openspec`) is unenforced at
      root and is now declared in `PARTIAL_COVERAGE["specs"]`, with a test that
      removes the waiver the moment the root pipeline enforces it.
- [x] **Python branch coverage is measured and enforced** as its own floor:
      `branch = true` + `coverage_gate.py` applying `coverage.lines` and
      `coverage.branches` separately (a single `--cov-fail-under` would gate a
      blended number mislabeled as the lines floor). Lines 94.10%, branches
      89.46% at enablement; the `branches` waiver in `UNENFORCED_IN_ROOT_CI`
      is deleted.
- [x] **The bundle's top-level policy digests are regenerable in CI**:
      `build_policy_bundle.py` is wired into `make digest-regen` behind
      `git diff --exit-code`; previously nothing invoked the only tool that
      could refresh the digests `verify_repository.py` checks.
- [ ] **Specs-gate refinements (recorded 2026-08-28):** the structural tier
      accepts an entirely unfilled template scaffold (placeholder
      `R-EXAMPLE-*` IDs satisfy every rule), and an `AC-*` bullet containing
      MUST can never pass the `[CR]-` requirement-ID regex — acceptance
      criteria must avoid the word or use `C-*` IDs. Both are gate-quality
      follow-ups, not urgent.
- [x] **Node coverage floor enforced.** Delivered by the gate-hardening change
      (docs/specs/gate-hardening.md): `make test-node` now runs vitest with
      `--coverage`, activating the policy-sourced thresholds (perFile
      included); the Python gate additionally enforces the lines floor per
      file, and `UNENFORCED_IN_ROOT_CI` is empty. The coverage-lift PR made
      the flip land green.
- [x] **`harness/SHA256SUMS.txt` deleted.** It pinned 10 files at digests of
      which 9 no longer matched, listed 5 files in a directory that no longer
      exists, and had zero readers anywhere. The live equivalents are
      `policy-artifact.json` (authoritative shared files, drift-gated in CI) and
      `policy-bundle.example.json` + `make digest-regen` (per-stack mirrors).

### ✅ v2.1.8 — MangoMas Integration Core (Shadow Comparison Channel)

Delivers the boundary machinery from `docs/research/mangomas-v2-integration-use-cases.md`
(UC-1 + UC-4), spec-first at `docs/specs/mangomas-integration-core.md`. Peer-reviewed
(Architect/QA-SQE/SDLC+Product) before implementation and re-audited for hygiene/wiring
after. Framed explicitly as channel infrastructure validated with a same-model producer —
no UC-4 experiment evidence is claimed by this milestone.

- [x] `harness/shared/cognitive_signal.py` — versioned, fail-closed `CognitiveSignal`
      envelope; workspace-scoped locked JSONL sink with per-signal and whole-sink byte
      ceilings; `confidence` is untrusted metadata, never a control input (INV-16).
- [x] `harness/shared/shadow_planner.py` + a guarded orchestrator hook — observation-only
      shadow plan comparison behind `MANGO_SHADOW_PLANNER=1`; zero tool authority; bounded
      timeout; disabled behavior byte-identical to baseline (proven by test, not asserted).
- [x] `harness/control-plane/publish_policy_artifact.py` — versioned, digest-pinned policy
      artifact with fail-closed `check` and HMAC attestation whose signature transitively
      covers the artifact core; committed `policy-artifact.json` closes a real drift gap
      (`make digest-regen` only pinned the per-stack mirrors, never the authoritative
      `governance-policy.json`/`agent-policy.json`).
- [x] Two new skills: `boundary-invariant-review` (reviews whether a diff gives a
      cognitive-plane field authority) and `shadow-channel-analysis` (freezes the UC-4
      analysis method before any producer exists).
- [x] `.claude/` SessionStart hook installs pinned dev dependencies on remote sessions.
- [x] INV-16 (one-directional cognitive/execution boundary) added to `harness/CONTRACT.md`.
- [x] Hardening from a post-implementation gap analysis: the lock retry loop is bounded by
      a poll budget independent of clock behavior (a clock-source mutation previously hung
      the suite instead of failing it); sink rejections are uniformly `SignalValidationError`
      instead of leaking a raw `TypeError` on unserializable payloads.
- [x] Second-pass adversarial review: fixed a BLOCKER (`publish_policy_artifact.check_artifact`
      never verified its file manifest actually covered the governed policy files — a
      narrowed manifest defeated the drift gate entirely), a cross-Python-version timestamp
      acceptance gap (`Z`-suffix ISO timestamps parse on 3.11+ but not 3.10, and CI runs
      both), a silent-channel-death bug (`policy_id: ""` discarded every signal in a run),
      and hardened the shadow channel against hostile provider responses and a data-integrity
      gap in payload key handling. Full findings in `CHANGELOG.md` [2.1.8].
- [x] `.gitignore` — `.governance/vitest-results.json`/`.governance/coverage/` were anchored
      to a nonexistent repo-root `.governance/` (same class of bug as the `protected_paths`
      finding below) and never actually matched `harness/node/.governance/`; surfaced by
      running the Node suite and checking `git status`. Fixed to `**/.governance/...`.
- [x] Findings recorded for follow-up, not silently patched (each requires a protected-path
      change and `infra-reviewed`): 5 of 6 `.mango/hooks/` scripts never fire because
      `.mango/settings.json` isn't the file Claude Code reads; `protected_paths` pattern
      `.governance/**` matches no real directory (`fnmatch` full-string anchoring); the
      `specs` CI-required target has no `make ci` stage; `R-MMI-*` requirement IDs aren't
      covered by `check_traceability` (its globs are scoped to `harness/node/`);
      `harness/control-plane` is in `pyproject.toml`'s coverage `source` but not yet
      measured by `make coverage-python` (the Makefile's explicit `--cov=` flags take
      precedence over the static config) — needs `--cov=harness/control-plane` added to
      the protected `Makefile` line; `publish_policy_artifact.py` itself is independently
      confirmed clean under `mypy --strict`, so this is purely a wiring gap, not a quality
      one; the Dockerfile `COPY .mango/ /app/.mango/` appears to copy nothing, since
      `.dockerignore` excludes the entire `.mango/` tree from the build context — flagged,
      not fixed: no Docker daemon was available in this session to verify with a real build,
      and the runtime image never installs Python regardless, so `harness/shared`/
      `harness/control-plane` cannot execute in it today irrespective of this bug.

### ✅ v2.1.6 — Live Smoke Test Resilience & Native Agent Skill Binding

- [x] Implemented resilient handling for live NIM API rate limits (429) and model deprecation (404/410) with graceful skip triggers.
- [x] Bound `nemotron_bridge.py` as a native Antigravity / Agent Skill (now canonical at `.mango/skills/nemotron-reasoner/SKILL.md`).
- [x] Configured Upstash Context7 MCP environment template integration.
- [x] Refactored `nemotron_bridge.py` with structured `logging` module, `--debug` flags, and full type annotations.
- [x] Verified full 7-tier test pyramid compliance across 243+ tests and 85%+ coverage gates.

### ✅ v2.1.4 — Governance Kernel Extraction & MAS Orchestrator

- [x] Extracted policy evaluation mechanisms into `harness/shared/governance/`.
- [x] Implemented `mango_mas_orchestrator.py` with fail-closed PreToolUse guards.
- [x] Implemented `meta_tools.py` for meta-learning and knowledge gaps tracking.
- [x] Updated C4 architecture, documentation, and root Makefile to align with governance boundaries.

### ✅ v2.1.3 — Python AQA Framework & Code Hygiene

- [x] Implemented full Python AQA suite: 133 tests, 98.44% coverage across `harness/shared`.
- [x] Created root `Makefile` with `lint`, `test`, `coverage`, `validate`, `ci` targets.

---

## 1. Near-Term Milestones (v2.2.0)

### 1.1 Optimize Language Agent Tree Search (LATS)

- [ ] **MCTS Refinement:** Refine the Monte Carlo Tree Search components in the reasoning layer.
- [ ] **Ablation Studies:** Measure the efficacy of LATS implementations against standard chain-of-thought methods.
- [ ] **Trace Logging:** Formalize the trace logging formats for LATS pathways.

### 1.2 Autonomous Healing Integration

- [ ] **Merge Experimental Branch:** Merge and stabilize the experimental Autonomous Healing branch.
- [ ] **Test-Driven Healing:** Wire the healing routines to automatically trigger upon test suite failures (`vitest` and `pytest`).
- [ ] **Policy Enforcement:** Gate autonomous healing behind the `.governance/` policy invariants to prevent out-of-bounds structural modifications.

### 1.3 Multi-Agent Memory Maturation

- [ ] **Persistent Storage:** Extend `meta_tools.py` for persistent JSON/Markdown storage for knowledge gap logs.
- [ ] **Retention Policies:** Establish retention policies and periodic context summarization protocols for the agent `memory/` directory.

---

## 2. Infrastructure & DevSecOps Milestones (v2.3.0)

### 2.1 NVIDIA NIM Multi-Model Routing & Token Budgeting

- [ ] **Dynamic Model Fallback:** Implement multi-tier routing (e.g. fast reasoning → deep synthesis).
- [ ] **Prompt Cache & Cost Tracking:** Add local disk/memory prompt-cache adapter to minimize repeated token costs on invariant verification prompts.
- [ ] **Model Context Protocol (MCP) Server:** Package `NemotronClient` as an independent standard STDIO/SSE MCP server for seamless integration with external AI IDEs and clients.
