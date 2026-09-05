# Decision records

Generated from `docs/decisions/DEC-*.md`. Do not edit by hand;
regenerate via `python harness/shared/generate_decision_index.py`.

| ID | Date | Status | Title |
| --- | --- | --- | --- |
| [DEC-000](DEC-000.md) | 2026-08-24 | accepted | Projections are explicitly not applicable in the uninstantiated template |
| [DEC-001](DEC-001.md) | 2026-08-26 | accepted | Live smoke tests against remote NVIDIA NIM API are conditionally skipped when endpoints are rate-lim |
| [DEC-002](DEC-002.md) | 2026-08-27 | accepted | `protected_paths` covers the agent control surface and carries root-relative twins for the multi-sta |
| [DEC-003](DEC-003.md) | 2026-08-27 | accepted | The unbound `.mango/hooks/` scripts remain dormant |
| [DEC-004](DEC-004.md) | 2026-08-28 | accepted | Unwired policy keys are classified with reviewed reasons instead of deleted |
| [DEC-005](DEC-005.md) | 2026-08-28 | superseded | The MAS orchestrator consults the PreToolUse guard in-process from the installed harness, never from |
| [DEC-006](DEC-006.md) | 2026-08-28 | accepted | The guard canonicalises its payload envelope across `tool_input` and `args` and denies a JSON object |
| [DEC-007](DEC-007.md) | 2026-08-28 | accepted | `protected_paths` is enforced at tool-call time by the write gate, not only by CI |
| [DEC-008](DEC-008.md) | 2026-08-28 | accepted | Role tool exposure is derived from `agent-policy.json` (union of canonical contracts minus approval- |
| [DEC-009](DEC-009.md) | 2026-08-28 | accepted | The policy decision point runs in process |
| [DEC-010](DEC-010.md) | 2026-08-28 | accepted | A command's action is derived from the command and fails closed to an action no role holds |
| [DEC-011](DEC-011.md) | 2026-08-28 | accepted | `run_command` routes through `ExecutionBroker`, so INV-8 is enforced on the live path |
| [DEC-012](DEC-012.md) | 2026-08-30 | accepted | `read_file` and `apply_patch` join the tool surface behind a new `read_policy.py`, the read-side cou |
| [DEC-013](DEC-013.md) | 2026-08-30 | accepted | A local bare `ruff` resolving to 0.15.8 (vs |
| [DEC-014](DEC-014.md) | 2026-08-30 | accepted | `make secrets`'s `gitleaks git` invocation (all three Makefiles) scanned every ref in the local clon |
| [DEC-015](DEC-015.md) | 2026-08-30 | accepted | GitHub Copilot's review of PR #35 found six real defects in the DEC-013/DEC-014 batch, all fixed her |
| [DEC-016](DEC-016.md) | 2026-08-30 | accepted | DEC-015's `PIP_AUDIT_VERSION` pin (2.10.1) broke the new `audit-matrix` job's 3.9 leg immediately: ` |
| [DEC-017](DEC-017.md) | 2026-08-30 | accepted | `audit-matrix`'s first real run found 7 known CVEs across `starlette`/`click`/`python-dotenv`, all r |
| [DEC-018](DEC-018.md) | 2026-08-30 | accepted | `NEXT_STEPS.md`'s required-status-check list (for the still-unapplied branch ruleset) was accurate w |
| [DEC-019](DEC-019.md) | 2026-08-31 | accepted | The triplicated `digest()` helper across the three control-plane scripts is confirmed intentional (e |
| [DEC-020](DEC-020.md) | 2026-08-31 | accepted | New gate-like modules land under `harness/shared/gates/` going forward |
| [DEC-021](DEC-021.md) | 2026-08-31 | accepted | A coverage-regression check was implemented via `scheduled-drift.yml`'s nightly `main-drift` loop (` |
| [DEC-022](DEC-022.md) | 2026-08-31 | accepted | Two second-round audit findings evaluated individually rather than mechanically fixed: `verification |
| [DEC-023](DEC-023.md) | 2026-09-01 | accepted | PR #55's unconditional `mcp>=1.0.0,<3.0` in `requirements.txt` broke CI two ways: Python 3.9 (no pub |
| [DEC-024](DEC-024.md) | 2026-09-02 | accepted | PR #60 merged with every CI run on its head red under a commit message claiming `make ci` and mypy c |
| [DEC-025](DEC-025.md) | 2026-09-02 | accepted | Constant triage: every operational constant the audit found unlinked is now a policy value (`process |
| [DEC-026](DEC-026.md) | 2026-09-02 | accepted | Python skip accounting: `conftest.py` writes every pytest skip to a TSV that `make verify-zero-skips |
| [DEC-027](DEC-027.md) | 2026-09-02 | accepted | `autonomous_healing.py` and `lats_optimizer.py` parked under `harness/shared/experimental/` (unchang |
| [DEC-028](DEC-028.md) | 2026-09-02 | accepted | The Python 3.9 floor stays |
| [DEC-029](DEC-029.md) | 2026-09-02 | superseded | DEC-020 stands: `harness/shared/` is not regrouped (cyclic on the real import graph |
| [DEC-030](DEC-030.md) | 2026-09-02 | accepted | The Python skip-evidence hooks (DEC-026) and the langgraph deselection live in the repository-root ` |
| [DEC-031](DEC-031.md) | 2026-09-02 | accepted | Dependabot PRs #38–#46 closed as superseded by the universal lock and the Phase 1 toolchain bump (ev |
| [DEC-032](DEC-032.md) | 2026-09-02 | accepted | Post-implementation review found four gates that could report PASS on absent or wrong evidence, all  |
| [DEC-033](DEC-033.md) | 2026-09-03 | accepted | The `pip` ecosystem is removed from `.github/dependabot.yml`, completing DEC-031 instead of restatin |
| [DEC-034](DEC-034.md) | 2026-09-03 | accepted | `make lint-node` is wired into `make ci`, and the recorded blocker was not the real one |
| [DEC-035](DEC-035.md) | 2026-09-03 | accepted | `coverage_gate.py` (470/500 lines) splits into threshold enforcement and `coverage_scope.py` (which  |
| [DEC-036](DEC-036.md) | 2026-09-03 | accepted | `nemotron.top_p` becomes a policy key read by both stacks |
| [DEC-037](DEC-037.md) | 2026-09-03 | accepted | `retry.ts`'s `JITTER_CEILING_MS` is a true constant, recorded separately because DEC-025 names neith |
| [DEC-038](DEC-038.md) | 2026-09-03 | accepted | The protected-path attestation table is derived and verified, not transcribed |
| [DEC-039](DEC-039.md) | 2026-09-03 | accepted | Seven operational defaults accepted as true constants, and the constant inventory made complete |
| [DEC-040](DEC-040.md) | 2026-09-03 | accepted | The attestation check reads the PR description from the API, not `github.event.pull_request.body`, a |
| [DEC-041](DEC-041.md) | 2026-09-03 | accepted | `test_verify_zero_skips.py` (684/700 lines) splits at its own section banner: the `unique_id_glob` c |
| [DEC-042](DEC-042.md) | 2026-09-04 | accepted | The containment layer grades the words the shell produces, not the command text |
| [DEC-043](DEC-043.md) | 2026-09-04 | accepted | A _present_ policy that has lost a key fails closed in every Python reader, matching `policy.ts` |
| [DEC-044](DEC-044.md) | 2026-09-04 | accepted | `main`'s ruleset drops the human-approval rules and keeps the nine required checks |
| [DEC-045](DEC-045.md) | 2026-09-04 | accepted | Every `uses:` in `.github/workflows/` is a 40-hex commit SHA with the version comment Dependabot wri |
| [DEC-046](DEC-046.md) | 2026-09-04 | accepted | The thirteen open Dependabot pull requests are dispositioned, and R-CQ-2's premise for five was wron |
| [DEC-047](DEC-047.md) | 2026-09-04 | accepted | The lock pins artefacts, not just versions, and `audit-python` scans the lock alone |
| [DEC-048](DEC-048.md) | 2026-09-04 | accepted | The 2026 standards audit's gate-runner and test-hygiene slice |
| [DEC-049](DEC-049.md) | 2026-09-04 | accepted | The verdict was forgeable by the agent it judges |
| [DEC-050](DEC-050.md) | 2026-09-04 | accepted | One slice of the 2026 standards-audit remediation (H16, M1, H6, H7, M25) |
| [DEC-051](DEC-051.md) | 2026-09-04 | accepted | The verification grader is imported from the toolchain, not the workspace, and the digested set is t |
| [DEC-052](DEC-052.md) | 2026-09-04 | accepted | The LangGraph graph fails closed on a recorded error and on absent evidence |
| [DEC-053](DEC-053.md) | 2026-09-05 | accepted | `harness/shared/langgraph/` is parked under `harness/shared/experimental/langgraph/` with PEP 562 sh |
| [DEC-054](DEC-054.md) | 2026-09-05 | accepted | `harness/jvm/` is relocated to `docs/adopters/jvm-template/` (Memo 2 option B / R-SR-26 / NS-31) |
| [DEC-055](DEC-055.md) | 2026-09-05 | accepted | The `openspec/` tree is folded into `docs/specs/` and deleted (Memo 3 option Y / R-SR-28 / NS-31) |
| [DEC-056](DEC-056.md) | 2026-09-05 | accepted | Per-stack governance mirroring collapses to a root `.governance/` plus `--workspace` on shared gates |
