# Spec: 2026 standards remediation plan (audit round 4)

> Status: IN PROGRESS (Phase B Done; A/C/D/E/F open — A and E owner-blocked), revision 2 · Date: 2026-09-05 · Base: `main` @ `2441547` (post PRs #86–#88)
>
> Supersedes the open remainder of `docs/specs/code-quality-tech-debt-plan.md`
> (closed 2026-09-04 at revision 2) and owns every Blocker, High and Medium
> finding in `docs/reports/2026-STANDARDS-AUDIT.md` (revision 2). `NEXT_STEPS.md`
> points here; it no longer restates this plan's status. Every requirement below
> names the audit finding or the closed plan's requirement it carries, so the
> next audit can ledger this document the way this one ledgered its predecessor.

## Executive summary

The uncomfortable finding was not that `main` is unprotected — the roadmap has said
so for four releases — it was that the runtime verdict the whole harness exists to
produce was **forgeable by the agent it judges**, in two tool calls, through the
real dispatcher, broker and backend (audit B4; closed by PR #86 / DEC-049–051).
The previous program plan spent six product-path PRs closing string-level spellings
of credential reads and never looked at script execution. Its remaining thirteen
PRs were inventory, gate and document ceremony. This plan reordered around four
facts: the verdict was forgeable (now contained; residual OS isolation stays Phase
F), the API server 500ed on every tool-using run (closed by #86), the language
floor is a year past end-of-life, and none of the nine required checks is required.

| Phase | Outcome | PRs | Protected rows | Owner decision |
|---|---|---|---|---|
| A | Ruleset imported; DEC-014 credential rotated; `LICENSE` chosen; `v2.4.0` tagged; four in-or-out decisions recorded as DECs | 0 code, 1 doc | ~2 | **yes**: all five |
| B | Runtime correctness and containment: typed API history, verification timeout key, per-task budget, run id and structured events, schema-validated tool args, indirect-execution door closed, verification tamper check, unix-socket egress floor, order randomization, gate-runner fixes, documentation truth, vacuous-selector gate | 1 (#86, merged) | ~30 | no |
| C | Floor to 3.10 with every compensating waiver deleted; 3.14 in the matrix; mypy 2.x; `target-version` removed | 1 + spec | ~8 | **yes**: adopters' floor |
| D | CI truthfulness: attestation bound to head SHA, scheduled branch-protection self-report, signed commits, Dockerfile, Dependabot ecosystems and cooldown | 2 | ~6 | no |
| E | Decide, then delete: JVM relocated, LangGraph parked, `openspec/` folded, per-stack mirroring collapsed behind `[project.scripts]` | 5–7 | ~55 | **yes**: DEC-005 posture |
| F | Slack items, each one PR: `ruff format`, PEP 621 metadata, ESLint type-checked, ADR directory and changelog cap, OS sandbox, eval harness and live smoke, mutation score, context budget, HITL, provider boundary | per item | varies | no |

Phase B is Done via PR #86 (AC-6…AC-22, AC-33). Phases C–F remain open; Phase A
and E are blocked on owner actions (NS-1/2/3/30/31). Status and Phase E order in
this file win; `NEXT_STEPS.md` must not restate them. Phases A and C block nothing
in B and everything in E.

## Review record

This plan was produced by four reviews run before revision 1 was written, so the
record is of what shaped it rather than what corrected it. Evidence is the review's
own command or `file:line` on `71223f1`.

| Input | Reviewer finding | Evidence | Disposition here |
|---|---|---|---|
| Audit rev 1 H2 "bypassable in two tool calls" | Executed end to end: script rewrote the protected `Makefile`, next `VerificationRunner.run` → `VERIFIED` on a failing suite; verifier role reproduces it; `GNUmakefile` unprotected | scratch run through `ToolDispatcher`+`ExecutionBroker`+`ProcessBackend`; `command_actions.py:165,233`; `write_denial_reason("GNUmakefile") → None` | Blocker B4; R-SR-6, R-SR-7, R-SR-8 in Phase B; OS sandbox stays Phase F |
| Program plan rev 2, 19 PRs | 9/31 requirements landed; 0/3 audit Blockers and 2/16 Highs covered; three ticked criteria collected zero tests; R-CQ-14 landed the wrong timeout key | ledger in the closed plan's header; `verification.py:81-89`; `-k patch_denied_read` → 0 collected | Plan closed; carried items listed in R-SR-30; dropped items listed in §Explicitly not doing |
| `tech-debt-hardening-plan.md` (29/29 ticked) | AC-28 false (no `-W error::DeprecationWarning` stage exists); AC-12 third clause false; two more vacuous selectors (AC-1, AC-9) | `grep -rn "error::DeprecationWarning" Makefile pyproject.toml .github/workflows` → 0 | Selectors corrected in place; the `-W error` stage is R-SR-19 |
| `NEXT_STEPS.md` (14 open) | 1 done and still listed; 3 without Done-when; 1 with no observable; 0 bound to a stage; duplicates R-CQ on five items; audit omitted NS-2 | `validate_plan.py --spec-dir . --all` → 0 acceptance bullets parsed | Roadmap rewritten to point here; NS-2 is R-SR-2 |
| Four in-or-out memos | JVM: relocate (4 lines of product Kotlin, never built); LangGraph: park with sunset (5/10 stubs, one experimental caller); `openspec/`: fold (tier mis-specified, never run); mirroring: collapse after the other three, gated on a DEC superseding DEC-005 | Memo artefacts are **not in the tree**; the summaries in this table are the only in-repo record until DEC-053… are logged | Phase E, JVM → LangGraph → openspec → mirroring (SoT; R-SR-26 … R-SR-29) |
| PR #86 | Phase B landed; AC-6…AC-22 and AC-33 ticked; DEC-048…DEC-051 carry the containment/runtime narrative. Title understated (`docs(reports): 2026 coding-standards audit`) relative to the code it shipped | `gh pr view 86` MERGED; plan boxes AC-6…22, AC-33 `[x]` | **Done** — Phase B closed |
| PR #87 / #88 + DEC-052 | LangGraph fail-closed on recorded errors and absent evidence; conclusive counts fail closed. Hardens the package **in place** under `harness/shared/langgraph/` | DEC-052; `docs/specs/langgraph-fail-open-hardening.md`; merge SHAs on `main` | **Does NOT satisfy R-SR-27** (park + sunset). Out of scope for AC-6…22 |
| Proposed DEC-053 | Park LangGraph with a named sunset (and the other three Phase E decisions); draft exists off-tree / owner-pending | Not present in `decision-log.md` (max DEC on main is 052) | **Drafted, not logged** — do not treat as done; logging DEC-053 is preferred before describing Phase C as starting the R-SR-27 sunset |
| Audit rev 1 §5 numbered roadmap | A fourth owner of the same work | `code-quality-tech-debt-plan.md`, `NEXT_STEPS.md` | Audit §5 now points here |

## Problem statement

Evidence for each item is in `docs/reports/2026-STANDARDS-AUDIT.md` §3 under the
finding id given; only the deciding facts are restated.

1. **Nothing is enforced.** `GET /repos/…/rules/branches/main` → `[]`;
   `protected: false`; PR #60 merged with all four build checks `failure`;
   #60/#79/#80 carry no approving review (B1). The `infra-reviewed` label that
   gates protected-path changes survives later pushes (H3). The required check
   `dependency-audit (3.9)` is `continue-on-error` (H1).
2. **The verdict was forgeable (closed by #86 / DEC-049–051).** The B4 script-rewrite path through the dispatcher/broker/backend returned VERIFIED on a failing suite; those surfaces are now protected and digests are checked. **Residual:** script execution can still read on-disk `.env` and open sockets until OS isolation lands (Phase F).
3. **The API server rejected its own output (closed by #86).** `TaskResponse.history` failed on tool-call shapes; clients got 500 on every tool-using run (B3).
4. **The floor is EOL.** `requires-python >= 3.9`; 3.9 EOL 2025-10-31; 3.10 EOL
   2026-10-31; every runtime dependency is `>= 3.10`; four waivers hold the floor
   (H1). mypy is pinned to August 2024 because 2.x removed `--python-version 3.9`
   (M10).
5. **The loop is 2023-shaped.** Shared history across three roles with no token
   bound (H4); per-role tool budgets on the live path (M1); no run id and a JSON
   formatter that drops `extra` (H6); verification runs under the model-latency
   timeout (H16); tool arguments reach executors without schema validation (H7);
   HITL declared, not implemented (H5).
6. **Test rigor has holes the 99% line coverage hides.** No order randomization or
   parallelism (H8); 35 socket-enabled tests for a need `--allow-unix-socket`
   satisfies (M12); mutation "proofs" are prose (H9); live model contract never
   exercised (H10); seven ticked acceptance criteria across three specs cited
   selectors collecting zero tests (review record).
7. **Half-done stacks cost gates.** JVM never built, hard-codes floors (H14);
   LangGraph 5/10 stub nodes with one experimental caller (M3); `openspec/` tier
   never run and mis-specified (M22); 28 shim scripts and byte-identical policy
   mirrors policed by a gate for a problem the layout created (M23).
8. **Records accrete.** 48 single-line decisions, longest 4,591 characters, in a
   stack subdirectory; `[Unreleased]` 1,197 lines, exempt from the 400-line cap
   by the cap's own regex; zero tags (H15). No `LICENSE` (B2).
9. **Two gate runners lie.** `make secrets` fails closed after a successful
   `make secrets-install` (GOPATH/bin never on PATH); the session-start hook
   installs unhashed and aborted silently on a Debian-owned package (§2).

## Requirements

Requirement ids are `R-SR-<n>` (functional) and `C-SR-<n>` (constraint). Each
names the audit finding or closed-plan requirement it carries.

### Phase A — owner actions (zero code)

- R-SR-1: The ruleset at `.github/rulesets/main.json` MUST be imported so that
  `GET /repos/{owner}/{repo}/rules/branches/main` returns at least the
  `required_status_checks`, `pull_request`, `non_fast_forward` and `deletion` rules
  it declares, with `required_signatures` and `required_linear_history` added to
  the export in the same change (B1, M18; carries R-CQ-1).
- R-SR-2: The credential DEC-014 documents MUST be rotated at the provider before
  Phase E begins, the branch `feature/governed-run-console` deleted or purged, and a
  decision-log entry MUST record the rotation date (NS-2; carries R-CQ-2).
- R-SR-3: A `LICENSE` file MUST exist at the repository root and `pyproject.toml`
  MUST declare the same licence under PEP 639 `license` / `license-files`;
  `harness/node/package.json` MUST carry the matching `license` field (B2).
- R-SR-4: An annotated tag MUST exist at the commit that set the declared
  version, and `test_documentation_truth.TestTheDeclaredVersionIsARealRelease`
  MUST additionally require that tag (NS-3; carries OQ1 of the hardening plan).
- R-SR-5: Four decision-log entries MUST record, before Phase E code lands: JVM
  relocation (review-record / Memo 2 option B), LangGraph park with sunset
  (proposed DEC-053; Memo 1 option B — memos not in tree), `openspec/` fold
  (Memo 3 option Y), and the mirroring collapse including the superseding of
  DEC-005's push posture (Memo 4). DEC-052 MUST NOT count as one of the four.

### Phase B — runtime correctness and containment (merged #86)

- R-SR-6: Executing a workspace file MUST NOT be a route around the write policy:
  `GNUmakefile`, `makefile`, `setup.py`, nested `conftest.py`, `sitecustomize.py`
  and `usercustomize.py` at the root and nested (`**/`), `pytest.ini`, `tox.ini`,
  `setup.cfg` and `*.pth` MUST be in `protected_paths`; `make -f <non-Makefile>`,
  `make --file=…`, `make -C …`, `make -e`, any long option not spelled in full
  (GNU make resolves unique prefixes) and a `MAKEFILES=` prefix MUST grade
  `destructive`; `pnpm exec <x>` / `npx <x>` MUST grade `test_execute` only for
  the module's existing test-runner set, and only with no option before `<x>`
  (B4).
- R-SR-7: `VerificationRunner.run` MUST return `BLOCKED` with reason
  `enforcement_tampered` naming the file when the digest of the workspace
  `Makefile` (and any other digested enforcement file the recipe depends on)
  differs from the digest recorded at loop start or from the one re-read after
  the verification command exits, reusing the control-plane digest function
  rather than a second implementation; the digested set MUST be the set the
  write door protects, walked over the whole workspace with only
  `ALWAYS_DENIED_SEGMENTS` skipped (B4).
- R-SR-8: `SECURITY.md` and the comment block of `harness/shared/agent-policy.json`
  MUST describe the runtime as containment, not isolation, and MUST name the
  remaining gap (script execution can read the on-disk `.env` and open sockets
  until OS isolation lands) (B4, M19).
- R-SR-9: `TaskResponse.history` MUST accept every message shape the orchestrator
  appends (system, user, assistant with optional `tool_calls`, tool with
  `tool_call_id`), reject unknown roles with a 500 that leaks no internals, and
  keep the wire shape of string-only histories byte-identical (B3).
- R-SR-10: The API server MUST expose unauthenticated `/healthz` (always 200) and
  `/readyz` (200 only when the key and policy load; 503 otherwise), and MUST move
  logging setup out of import time into `lifespan` (M14).
- R-SR-11: `governance-policy.json` MUST declare
  `orchestrator.verification_timeout_sec`; `VerificationRunner` and the facade
  MUST use it and never `api_timeout_sec`; a present policy lacking the key MUST
  raise `PolicyError` (H16; unwinds R-CQ-14's landed clause).
- R-SR-12: `execute_loop` MUST share one `ToolBudget(max_tool_calls_per_task)`
  across planner, reasoner and verifier (M1).
- R-SR-13: `JSONFormatter` MUST emit non-standard `LogRecord` attributes as
  top-level keys, never a credential-named key; `execute_loop` MUST generate a
  `run_id` and emit one structured event per model call (agent, iteration,
  latency_ms, usage tokens when present) and per tool call (tool, permitted,
  duration_ms), without logging arguments or message contents (H6).
- R-SR-14: The dispatcher MUST validate tool arguments against the tool's own
  `function.parameters` (required keys, `additionalProperties: false`, primitive
  types) before execution, returning `Error: invalid_arguments: <key>` and never
  calling the executor on failure; the validator lives in a non-protected module
  with seeded random-input tests and no new dependency (H7).
- R-SR-15: `mcp_server` MUST build its handler table from `ToolDispatcher`'s
  registry rather than a hand-mirrored copy, MUST run handlers via
  `asyncio.to_thread`, and MUST log tool name, role, permitted/denied and
  duration_ms per call with argument key names only (M8, M9).
- R-SR-16: Every gate script MUST configure logging through
  `json_logging.configure_gate_logging`, and `validate_specs.py` /
  `validate_plan.py` MUST honour `LOG_LEVEL` via `resolve_log_level` (M25).
- R-SR-17: `addopts` MUST carry `--allow-unix-socket` beside `--disable-socket`;
  no module-level `enable_socket` mark MAY remain; `test_egress_floor.py` MUST
  prove a unix socketpair is permitted and a TCP connect still raises (M12).
- R-SR-18: `pytest-randomly` and `pytest-xdist` MUST be pinned in
  `requirements-dev.txt` and present in the hashed lock; `os.chdir` in tests MUST
  become `monkeypatch.chdir`; the module-level `TestClient` MUST become a fixture
  (H8).
- R-SR-19: `make secrets` MUST pass immediately after `make secrets-install` with
  no PATH edit; the session-start hook MUST install `--require-hashes -r
  requirements-lock.txt` then `-e . --no-deps` and MUST name a failed install
  instead of continuing; the root `Makefile` MUST set `.SHELLFLAGS := -eu -o
  pipefail -c`; every CI job MUST carry `timeout-minutes` and the PR workflow a
  `concurrency` group; `pip-audit` and `uv` MUST install from the hashed lock
  (§2, M15, M16; carries C-TDH-2's `-W error` stage if it lands in this slice).
- R-SR-20: Documentation claims pinned false by the audit MUST be corrected with a
  mechanical pin each: `harness/CONTRACT.md`'s `PIN_FULL_COMMIT_SHA` sentence,
  `harness/node/Agent.md`'s scope line, the C4 document's routes and streaming
  claim, `CONTRIBUTING.md`'s `pre-pr` contradiction; `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md`
  MUST move under `docs/reports/` (M26; carries the unfinished half of R-CQ-30).
- R-SR-21: A test MUST fail when any ticked acceptance criterion in `docs/specs/`
  cites a `pytest` selector that collects no test, using pytest's own `-k`
  grammar; the seven vacuous selectors found by hand MUST be corrected in place
  (review record).
- R-SR-22: The audit procedure MUST be a skill (`.mango/skills/standards-audit/`)
  classified by `test_agent_surface_liveness.py`, composing `tech-debt-audit`,
  `validation-runner` and `gate-mutation-proof` rather than restating them.

### Phase C — the floor

- R-SR-23: `requires-python` MUST move to `>= 3.10`; the 3.9 matrix legs, the
  forked pytest pins, `coverage.optional_extras`, `check_py_compat.py`'s PEP 604
  check, the `continue-on-error` audit leg and the `dependency-audit (3.9)`
  required context MUST be deleted, not re-homed; 3.14 MUST join the matrix;
  mypy MUST move to the current 2.x with `warn_unused_ignores` on and
  `disallow_any_generics` on for source via overrides; ruff `target-version` MUST
  be removed so it derives from `requires-python` (H1, M10; supersedes DEC-028;
  carries R-CQ-16, R-CQ-23 by deletion).
  **Note (rev 2):** Phase C is safe before NS-31 for waiver deletion, but MUST
  NOT be described as starting the R-SR-27 sunset until DEC-053 is logged.
  Prefer: log DEC-053 first (even if park code waits), then land C, or land C
  with an explicit sentence that the sunset clock starts at the next tagged
  minor after DEC-053. Sync `.github/rulesets/main.json` in the same PR as the
  context deletions if NS-1 has not yet been applied.

### Phase D — CI truthfulness

- R-SR-24: The protected-path attestation MUST bind to the PR head SHA so a later
  push invalidates it; a scheduled job MUST query `/rules/branches/main` and open
  or update an issue while the ruleset is absent; commits on `main` MUST be signed
  once `required_signatures` is live (H3, B1, M18).
- R-SR-25: The Dockerfile MUST pin its base by digest, run as a non-root user, and
  ship no dev dependency at runtime; Dependabot MUST cover `docker` and declare an
  explicit `cooldown` (M17, M18; carries R-CQ-11).
  **Note (rev 2):** Action majors were closed after DEC-046 without
  merge; open queue empty 2026-09-05
  package bumps via recreate; not Phase E.
  R-SR-25 still owns docker + cooldown only.

### Phase E — decide, then delete

- R-SR-26: `harness/jvm/` MUST be relocated to `docs/adopters/jvm-template/` with
  its shims, personas and `.governance/` deleted, the bundle tooling tolerating an
  absent stack, and every test that loops over `("node", "jvm")` retargeted
  (H14; review-record / Memo 2 option B — memos not in tree).
- R-SR-27: `harness/shared/langgraph/` MUST move under `harness/shared/experimental/`
  with PEP 562 shims at the old paths for one minor release and a sunset clause in
  its DEC (M3; review-record summary of Memo 1 option B — memos not in tree;
  carries R-CQ-22). DEC-052 (#87/#88) fail-closed the graph **in place** and does
  **not** satisfy this requirement; proposed DEC-053 (park + named sunset; drafted,
  not logged) is the decision that does, and must state that the DEC-052 suite
  relocates with the package.
- R-SR-28: The three `openspec/changes/*` proposals MUST become `docs/specs/*.md`
  passing `make specs`, and the strict tier, its env var, its tests and the
  `openspec/` tree MUST be deleted (M22; review-record / Memo 3 option Y — memos not in tree).
- R-SR-29: Per-stack mirroring MUST collapse to a root `.governance/` plus a
  `--workspace` flag on the seven CWD-relative gates, with `[project.scripts]`
  entry points replacing the 28 shim scripts and `check_dedup.py` deleted, in the
  five-PR order summarised in the review record (Memo 4 artefact not in tree),
  each PR green on its own (M23, H12; carries R-CQ-18's bootstrap clause and
  R-CQ-25 by decision; supersedes DEC-029 (2)).

### Carried and dropped

- R-SR-30: The following closed-plan requirements are carried into the phases
  named and MUST NOT be re-derived: R-CQ-11 → R-SR-25; R-CQ-12 (`GraphPolicy`
  default-less) → Phase F only if LangGraph is revived; R-CQ-18 ESLint half →
  Phase F; R-CQ-21 defect subset → R-SR-17, R-SR-18; R-CQ-22 → R-SR-27;
  R-CQ-25 → R-SR-29; R-CQ-30 doc move → R-SR-20.
- R-SR-31: The verification recipe MUST import its grader from the installed
  toolchain and never from the workspace: the Python runner MUST start the
  interpreter in isolated mode (`-I`) and MUST export `PYTHONSAFEPATH=1` to its
  worker processes, so a `pytest.py` or `pytest/` package an agent writes into
  the workspace — not a protected path — is not the pytest that runs; a
  regression MUST prove the forgery under the old recipe shape and its absence
  under the new one, and `SECURITY.md` MUST name the residuals (workers on
  Python < 3.11, the toolchain's own packages in the workspace virtualenv)
  (B4, Copilot review on PR #86).
- C-SR-1: No threshold, timeout or count MAY appear as a literal outside
  `governance-policy.json`; every new key MUST have a `TypedDict` field, an
  accessor, a fail-closed test, and a regenerated bundle.
- C-SR-2: No test skip, `xfail`, waiver widening or marker MAY be added to make a
  gate green; INV-2 evidence MUST stay at zero unapproved skips.
- C-SR-3: Every protected-path slice MUST carry the derived attestation table from
  `make attestation`; a verification claim in prose is not evidence (DEC-024).
- C-SR-4: Every change MUST be backward compatible for one minor release: renamed
  paths keep PEP 562 shims, new policy keys have no default (fail closed) but
  existing keys keep their meaning, and the API wire shape for string-only
  histories does not change.

## Acceptance criteria

- [ ] AC-1: `GET /repos/ianshank/Mango_Code_Agent-Harness/rules/branches/main`
      returns a non-empty rule list including `required_status_checks`, and a
      PR whose head has a failing required check cannot be merged (the merge
      button reports the failure) · stage: owner action, evidenced by the API
      response pasted into the closing PR (R-SR-1)
- [ ] AC-2: `gitleaks git . --config .gitleaks.toml --log-opts="--all"` reports
      no leaks after the rotation and purge, and
      `git grep -n "DEC-014" harness/node/.governance/decision-log.md` finds the
      rotation entry; the scan fails on the pre-rotation ref set (R-SR-2)
- [ ] AC-3: `ls LICENSE` succeeds; `python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['license'])"`
      prints the licence; `pytest harness/shared/tests/test_documentation_truth.py -k license`
      fails when either is removed · stage: `make test-python` (R-SR-3)
- [ ] AC-4: `git tag -l v2.4.0` prints the tag and
      `pytest harness/shared/tests/test_documentation_truth.py -k real_release`
      fails when the tag is absent · stage: `make test-python` (R-SR-4)
- [ ] AC-5: Four Phase E decision-log entries exist with **explicit** park /
      relocate / fold / mirroring language (expected ids DEC-053+; titles must
      name JVM relocate, LangGraph park+sunset, `openspec/` fold, and mirroring
      collapse). `git grep -nE "DEC-05[3-9].*(park|reloc|fold|mirroring|jvm|openspec)" harness/node/.governance/decision-log.md`
      returns those four and MUST NOT treat DEC-048…DEC-052 (Phase B / fail-closed)
      as satisfying this criterion; `make validate` passes on them
      (`validate_governance_docs.py` rejects an entry missing from
      `GOVERNANCE_SKILL.md`) · stage: `make validate` (R-SR-5)
- [x] AC-6: `pytest harness/shared/tests/test_command_actions_indirect_exec.py`
      asserts `make -f GNUmakefile x`, `make -C sub`, `MAKEFILES=x make` and
      `pnpm exec node -e 1` grade `destructive`, while `make test-python`, `pytest`
      and `pnpm exec vitest` keep `test_execute`;
      `pytest harness/shared/tests/test_protected_path_liveness.py` passes with
      every new pattern live · stage: `make test-python` (R-SR-6)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `test_command_actions_indirect_exec.py`: 83 passed; `test_protected_path_liveness.py` green with the ten new patterns declared
- [x] AC-7: `pytest harness/shared/tests/regression -k enforcement_tampered`
      runs the forgery recipe (write a script that rewrites `Makefile`, run it,
      verify) end to end through the real dispatcher, broker and backend and
      asserts `BLOCKED/enforcement_tampered`; reverting the digest check yields
      `VERIFIED` · stage: `make test-regression` (R-SR-7)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `regression/test_verdict_forgery_regression.py`: the recipe yields `BLOCKED/enforcement_tampered` through the real dispatcher, broker and backend; untampered passing → `VERIFIED`, untampered failing → `FAILED`
- [x] AC-8: `git grep -n -i "OS isolation" SECURITY.md harness/shared/agent-policy.json`
      finds both (each names OS isolation of the process backend as the missing
      control), and `git grep -n "\.env" SECURITY.md` names the remaining gap
      · stage: `make validate` (R-SR-8)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); both greps find the OS-isolation wording; SECURITY.md names the on-disk `.env` gap
- [x] AC-9: `pytest harness/api_server/tests -k tool_using_history_round_trips` asserts
      HTTP 200 with a round-tripped `tool_calls` assistant message and a `tool`
      message, and `pytest harness/api_server/tests -k malformed_message` asserts
      500 whose body does not contain the pydantic error text;
      `pytest harness/shared/tests/regression -k "tool_call_and_tool_result or unknown_role_is_still_refused"`
      reproduces the pre-fix 500 · stage: `make test-python` (R-SR-9)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `test_tool_using_history_round_trips`, `test_a_malformed_message_is_an_internal_error_that_leaks_nothing`, `TestToolUsingRunsReachTheClient` (4 shapes + 5 argument shapes) green
- [x] AC-10: `pytest harness/api_server/tests -k "healthz or readyz"` asserts
      200/200 with a key and 200/503 without; `git grep -n "setup_json_logging" harness/api_server/main.py`
      shows it inside `lifespan` only · stage: `make test-python` (R-SR-10)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); healthz/readyz: 200/200 with a key, 503 without, 503 on a broken policy, 503 on a missing `agent_defaults` block; `setup_json_logging` inside `lifespan`
- [x] AC-11: `python -c "from harness.shared.policy_loader import orchestrator_limits as o;print(o().verification_timeout_sec)"`
      prints the policy value; `pytest harness/shared/tests -k verification_timeout`
      fails when the key is removed from a `tmp_path` policy and when
      `api_timeout_sec` is patched but the verification timeout is unchanged
      · stage: `make test-python` (R-SR-11, C-SR-1)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); accessor prints 900; `test_the_verification_timeout_does_not_follow_api_timeout` and `test_moving_the_model_latency_key_does_not_move_the_verification_timeout` green
- [x] AC-12: `pytest harness/shared/tests -k "sum_across_roles or task_within_the_budget"`
      asserts that with a budget of N the sum of tool calls across the three
      roles cannot exceed N, and fails when each role gets a fresh budget
      · stage: `make test-python` (R-SR-12)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `test_the_sum_across_roles_cannot_exceed_the_task_budget` and `test_a_task_within_the_budget_completes` green
- [x] AC-13: `pytest harness/shared/tests/test_json_logging.py -k extra` asserts
      `extra={"run_id": …}` appears as a top-level key and a key named
      `NVIDIA_API_KEY` never does; `pytest harness/shared/tests -k run_id`
      asserts model and tool events in one loop run share a `run_id`
      · stage: `make test-python` (R-SR-13)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `test_extra_fields_become_top_level_keys`, `test_a_credential_named_extra_is_never_emitted`, `test_model_and_tool_events_carry_the_same_run_id` green
- [x] AC-14: `pytest harness/shared/tests/test_tool_arg_validation.py` passes
      including its seeded random-dict cases, and
      `pytest harness/shared/tests -k "never_reaches_the_executor or extra_key_is_rejected"`
      asserts `write_file` without `filepath` never reaches the executor
      (reverting → the executor raises `IsADirectoryError`) and an undeclared
      key is rejected by name · stage: `make test-python` (R-SR-14)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `test_tool_arg_validation.py` (seeded random cases) green; `test_a_missing_required_key_never_reaches_the_executor`, `test_an_extra_key_is_rejected_by_name` green
- [x] AC-15: `pytest harness/shared/tests/test_mcp_server.py -k "registry or off_the_event_loop or concurrent_tool_calls_overlap or parity"`
      asserts the MCP handler names equal the dispatcher's and that two
      concurrent calls overlap in time; dropping a name from the shared registry
      fails the parity test · stage: `make test-python` (R-SR-15)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); registry parity, `test_call_tool_runs_the_handler_off_the_event_loop_thread`, `test_two_concurrent_tool_calls_overlap` green; dropping a name fails the parity check
- [x] AC-16: `git grep -n "logging\.basicConfig(" -- harness/shared harness/control-plane ':!*/tests/*' ':!harness/shared/mcp_server.py' ':!harness/shared/json_logging.py'`
      returns nothing (the MCP server is a stdio transport, not a gate, and
      keeps its WARNING floor; `json_logging.py` names the call only in a
      docstring), and `LOG_LEVEL=DEBUG python harness/shared/validate_specs.py`
      emits DEBUG records · stage: `make lint` (R-SR-16)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); grep returns nothing; `LOG_LEVEL=DEBUG` honoured by `validate_specs.py` and `validate_plan.py`
- [x] AC-17: `git grep -n "mark.enable_socket" -- harness ':!*/test_egress_floor.py' ':!*/test_nemotron_bridge_live.py' ':!*/test_mango_mas_live.py'`
      returns no mark (the three survivors open real TCP and say so at the
      mark); `pytest harness/shared/tests/test_egress_floor.py -k socketpair`
      asserts a unix socketpair succeeds and a TCP connect raises
      `SocketBlockedError` · stage: `make test-python` (R-SR-17)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); no mark outside the three declared TCP users; `test_a_unix_socketpair_is_permitted_while_tcp_still_raises` green
- [x] AC-18: `make lock-check` passes with `pytest-randomly` and `pytest-xdist` in
      the lock; `make coverage-python` prints a `randomly` seed; three runs with
      distinct `--randomly-seed` values pass; `git grep -n "os\.chdir(" -- harness`
      returns nothing · stage: `make ci` (R-SR-18)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `make lock-check: passed`; `make coverage-python` prints `--randomly-seed` and runs `-n auto` (4 workers); three seeds green in the slice run; `os.chdir(` absent
- [x] AC-19: `make secrets-install && make secrets` exits 0 in a shell whose PATH
      lacks GOPATH/bin, pinned by `pytest harness/shared/tests/test_makefile_contracts.py -k gopath_bin`;
      `pytest harness/shared/tests/test_agent_surface_liveness.py -k SessionStartPreparesTheGates`
      asserts the hook installs the hashed lock and names a failed step;
      `pytest harness/shared/tests/test_workflow_runtime_limits.py` fails when
      a job loses its timeout or the PR workflow its concurrency group;
      `grep -n "^.SHELLFLAGS" Makefile` finds the line;
      `pytest harness/shared/tests/test_makefile_contracts.py -k installs_the_lock_with_hashes`
      asserts the audit tooling installs from the hashed lock · stage: `make ci` (R-SR-19)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `make secrets-install && make secrets` passed with no PATH edit; `test_a_gitleaks_in_gopath_bin_is_what_the_secrets_gate_runs`, `TestSessionStartPreparesTheGates`, `test_workflow_runtime_limits.py`, `test_the_install_target_installs_the_lock_with_hashes` green; `.SHELLFLAGS` present
- [x] AC-20: `pytest harness/shared/tests/test_documentation_truth.py harness/shared/tests/test_documentation_claims.py -k "Placeholder or DocumentedRoutes or PersonaScope or ContributingGate"`
      fails when any corrected claim is reverted; `ls docs/reports/SDLC_HYGIENE_AND_GAP_ANALYSIS.md`
      succeeds and `ls docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` fails
      · stage: `make test-python` (R-SR-20)
      — verified 2026-09-04 on `bf5fe22`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (lines 99.25 %, branches 97.91 %, 78 files at the per-file floor, 0 waived); `test_documentation_claims.py` (placeholder, persona scope, contributing gate) and `TestDocumentedRoutesExist` green; the report lives under `docs/reports/`
- [x] AC-21: `pytest harness/shared/tests/test_spec_selectors_collect.py` passes on
      the tree and fails on a spec whose ticked criterion names `-k patch_denied_read`
      (its `test_a_dead_keyword_reports_zero` case) · stage: `make test-python`
      (R-SR-21) — verified 2026-09-04: `61 passed`; before the four
      in-place corrections it reported `4 failed, 57 passed` naming
      `tech-debt-hardening-plan.md` AC-1/AC-9 and `gate-truthfulness.md` AC-2/AC-6
- [x] AC-22: `pytest harness/shared/tests/test_agent_surface_liveness.py -k "SkillsAreDated or EverySkillIsWiredOrDeclared or SkillsNameRealTargets"`
      passes with `standards-audit` classified; removing its `STANDALONE_SKILLS`
      entry fails `EverySkillIsWiredOrDeclared` · stage: `make test-python`
      (R-SR-22) — verified 2026-09-04 on this branch
- [ ] AC-23: `python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['requires-python'])"`
      prints `>=3.10`; `git grep -n "3\.9" .github/workflows pyproject.toml requirements-dev.txt harness/shared/governance-policy.json`
      returns nothing; `git grep -n "target-version" pyproject.toml` returns
      nothing; `python -m mypy --version` reports 2.x and `make lint-cold`
      passes with `warn_unused_ignores = true`; the ruleset lists no
      `dependency-audit (3.9)` context and `pytest harness/shared/tests/test_ci_gate_required_checks.py`
      fails if it does · stage: `make ci` (R-SR-23)
- [ ] AC-24: `pytest harness/shared/tests/test_workflow_contracts.py -k "attestation_sha or protection_report"`
      asserts the attestation step reads the head SHA from the table and the
      scheduled job calls `/rules/branches/main`; a PR with a stale SHA in its
      table fails `build-full` · stage: `make ci` (R-SR-24)
- [ ] AC-25: `pytest harness/shared/tests/test_dockerfile_contract.py` asserts a
      digest-pinned `FROM`, a `USER` line, and no `tsx` in the runtime stage;
      `pytest harness/shared/tests/test_dependabot_contract.py` asserts `docker`
      and `cooldown` and fails when either is removed · stage: `make test-python`
      (R-SR-25)
- [ ] AC-26: `ls harness/jvm` fails and `ls docs/adopters/jvm-template/build.gradle.kts`
      succeeds; `make digest-regen` exits 0 with no `jvm` profile in
      `policy-bundle.example.json`; `pytest harness/shared/tests/test_harness.py`
      passes with no `("node", "jvm")` loop · stage: `make ci` (R-SR-26)
- [ ] AC-27: `python -c "import warnings;warnings.simplefilter('error');import harness.shared.langgraph.graph"`
      raises `DeprecationWarning` naming the new path;
      `pytest harness/shared/tests/test_deprecation_shims.py -k langgraph` passes
      and `make test-langgraph` passes from the new path · stage: `make ci`
      (R-SR-27)
- [ ] AC-28: `ls openspec` fails; `make specs` reports three more documents than
      before the fold; `git grep -n "REQUIRE_STRICT_SPEC_VALIDATOR" .` returns
      nothing; `pytest harness/shared/tests/test_ci_gate_coverage.py` passes with
      no `specs` partial-coverage entry · stage: `make ci` (R-SR-28)
- [ ] AC-29: `ls harness/node/scripts` shows only `run_vitest.sh`; `ls harness/shared/check_dedup.py`
      fails; `python -m harness.shared.validate_policy --workspace harness/node`
      exits 0 and exits 1 on a workspace with a malformed policy;
      `make validate` runs from the repository root and `pytest harness/shared/tests/test_validators.py`
      exercises the root `.governance/` layout · stage: `make ci` (R-SR-29)
- [ ] AC-30: `git grep -nE "R-CQ-(11|12|18|21|22|25|30)" docs/specs/2026-standards-remediation-plan.md`
      finds each carried id in R-SR-30 or a phase requirement, and none is
      re-specified in a new child spec (`ls docs/specs/retry-parity.md docs/specs/control-plane-package.md`
      both fail) · stage: `make specs` (R-SR-30)
- [ ] AC-31: `pytest harness/shared/tests/test_constant_triage.py harness/shared/tests/test_policy_consistency.py`
      passes after every Phase B, C and D slice with no new `EXCLUDED` row;
      `make verify-zero-skips-python` and `make verify-zero-skips` report zero
      unapproved skips; `make attestation-check FILE=<pr-body>` exits 0 on every
      protected slice and exits 1 on a table with a missing row · stage:
      `make ci` (C-SR-1, C-SR-2, C-SR-3)
- [ ] AC-32: `pytest harness/api_server/tests -k string_only_history` asserts the
      pre-change JSON for a string-only history is byte-identical;
      `pytest harness/shared/tests/test_deprecation_shims.py` passes for every
      renamed path; a `tmp_path` policy from `71223f1` raises `PolicyError` only
      for the keys this plan adds · stage: `make test-python` (C-SR-4)
- [x] AC-33: `pytest harness/shared/tests/regression -k shadow` proves a
      workspace `pytest.py` passes a failing suite under the old recipe shape
      and is not imported under the isolated one (module and package forms,
      with a passing-suite control), and
      `pytest harness/shared/tests/test_makefile_contracts.py -k shadow` pins
      the real `PYTEST` definition to `-I` and the exported `PYTHONSAFEPATH`
      · stage: `make test-regression` (R-SR-31)
      — verified 2026-09-04 on `e1232d4`: `ALLOW_GITHUB_CHANGES=1 make ci` exit 0 (3,757 passed, 1 skipped under DEC-026, lines 99.19 %, branches 97.88 %, 78 files at the per-file floor, 0 waived); the premise test runs the old recipe shape against a real failing suite and reports exit 0 with the shadow module's output, and the same forgery under the isolated shape yields `FAILED`, not `VERIFIED` and not `enforcement_tampered`; the passing-suite control yields `VERIFIED`; the first `make ci` on `84bb85a` caught the premise test inheriting the Makefile's own `PYTHONSAFEPATH` export, fixed in the fixture

## Steps

Ordered by dependency. Phase B was one PR (#86), merged 2026-09-04; later phases
are one PR per numbered step. Phase E order below is the source of truth.

### Phase A (0 code)

1. Owner imports the ruleset, rotates the credential, chooses the licence, tags
   `v2.4.0`, and records the four DECs (R-SR-1 … R-SR-5) — produces the API
   response for AC-1, `LICENSE`, the tag, four decision-log entries.

### Phase B (Merged #86)

2–7. Containment, API server, loop/policy, MCP, test infrastructure, documentation
   truth / vacuous-selector gate / audit skill (R-SR-6 … R-SR-22) — landed on
   `main` via PR #86 (merge `d9ab598`, 2026-09-04). Title understated relative to
   the code shipped; evidence is the ticked AC-6…AC-22 / AC-33 boxes and
   DEC-048…DEC-051.
8. **Merged #86.** `make ci` / attestation evidence is on the merge commit; do not
   open a second Phase B PR under this plan.

### Phase C

9. `make spec NAME=python-floor-310` superseding DEC-028, then the bump, the
   deletions, 3.14, mypy 2.x, `target-version` removal (R-SR-23).

### Phase D

10. Attestation bound to SHA; scheduled protection report; signatures
    (R-SR-24). 11. Dockerfile and Dependabot (R-SR-25).

### Phase E (after Phase A's DECs) — SoT order

12. JVM relocation (R-SR-26). 13. LangGraph park with sunset after DEC-053
    (R-SR-27; DEC-052 does not satisfy). 14. `openspec/` fold (R-SR-28).
15. Mirroring collapse, `[project.scripts]` first (R-SR-29).
    Order **JVM → LangGraph → openspec → mirroring** is authoritative here;
    memo files are not on `main` — do not invent a second order from absent
    artefacts.

### Phase F

16. One PR each, any order, when there is slack: `ruff format` with
    `.git-blame-ignore-revs` (H11); PEP 621 metadata and `py.typed` (H12);
    ESLint `recommendedTypeChecked` (H13); `docs/decisions/` ADRs and the
    `[Unreleased]` cap (H15); OS sandbox for `ProcessBackend` (B4 permanent —
    the digest check runs before and after the verification command, so the
    remaining window is a swap-and-restore inside the run, which only an
    immutable snapshot or OS isolation closes; Copilot review on PR #86);
    eval harness and nightly live smoke (H10); `mutmut` score floor (H9);
    context budget (H4); HITL interrupts (H5); `ChatProvider` boundary (M5);
    meta-tool readers (M4); runtime-specific personas (M2); a subprocess-level
    egress floor for the suite (a refusing `curl` shim on `PATH` or
    `unshare -n` around `ProcessBackend` in tests), since `pytest-socket` cannot
    see a child process and one regression test currently makes a real
    outbound connection attempt (audit Low list).

## Files touched

Protected paths are marked (P); every (P) slice carries the attestation table and
the `infra-reviewed` label. Phase B's list is what PR #86 carried; later phases
list their principal files and defer the full set to their own PR bodies.

- Phase A: `.github/rulesets/main.json`, `LICENSE` (new), `pyproject.toml` (P),
  `harness/node/package.json`, `harness/node/.governance/decision-log.md` (P),
  `harness/node/agents/GOVERNANCE_SKILL.md` (P), `NEXT_STEPS.md`.
- Phase B: `harness/shared/governance-policy.json` (P),
  `harness/shared/governance/command_actions.py` (P),
  `harness/shared/governance/verification.py` (P), `harness/shared/write_policy.py` (P),
  `harness/shared/agent-policy.json` (P), `SECURITY.md`,
  `harness/control-plane/policy-artifact.json` (P),
  `harness/control-plane/policy-bundle.example.json`,
  `harness/api_server/main.py`, `harness/api_server/tests/*`,
  `harness/shared/policy_loader.py` (P), `harness/shared/mango_mas_orchestrator.py` (P),
  `harness/shared/orchestrator/loop.py` (P), `harness/shared/orchestrator/dispatcher.py` (P),
  `harness/shared/tool_arg_validation.py` (new), `harness/shared/json_logging.py`,
  `harness/shared/mcp_server.py`, the eight gate scripts that called
  `logging.basicConfig` (several P), `harness/shared/validate_specs.py` (P),
  `harness/shared/validate_plan.py` (P), `pyproject.toml` (P),
  `requirements-dev.txt` (P), `requirements-lock.txt`, `Makefile` (P),
  `harness/node/Makefile` (P), `.claude/hooks/session-start.sh` (P),
  `.github/workflows/python-package.yml` (P), `.github/workflows/scheduled-drift.yml` (P),
  `harness/CONTRACT.md` (P), `harness/node/Agent.md` (P),
  `docs/architecture/c4_architecture.md`, `CONTRIBUTING.md`, `README.md`,
  `docs/reports/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` (moved),
  `harness/shared/tests/test_spec_selectors_collect.py` (new),
  `harness/shared/tests/test_agent_surface_liveness.py`,
  `.mango/skills/standards-audit/SKILL.md` (new, P),
  `docs/specs/code-quality-tech-debt-plan.md`, `docs/specs/gate-truthfulness.md`,
  `docs/specs/tech-debt-hardening-plan.md`, the test modules each slice names.
- Phase C: `pyproject.toml` (P), `requirements-dev.txt` (P), `requirements-lock.txt`,
  `.github/workflows/*.yml` (P), `.github/rulesets/main.json`,
  `harness/shared/governance-policy.json` (P), `harness/shared/check_py_compat.py` (P),
  `conftest.py` (P), `harness/shared/tests/test_ci_gate_required_checks.py` (P),
  `NEXT_STEPS.md`, `docs/specs/python-floor-310.md` (new).
- Phase D: `.github/workflows/python-package.yml` (P), `.github/workflows/scheduled-drift.yml` (P),
  `harness/shared/governance/attestation.py` (P), `Dockerfile`, `.github/dependabot.yml`,
  `harness/shared/tests/test_dockerfile_contract.py` (new),
  `harness/shared/tests/test_dependabot_contract.py` (new).
- Phase E: per the four memos' blast-radius lists, recorded in each PR body.

## Invariants touched

- INV-1: `make secrets` unchanged in scope (`--log-opts="HEAD"` per DEC-014);
  R-SR-2's `--all` scan is a one-time owner action. Proved by `secret-scan` on
  every slice.
- INV-2: R-SR-17 removes marks, adds none; R-SR-18 adds plugins, no skips. Proved
  by `make verify-zero-skips-python` and `verify-zero-skips` (AC-31).
- INV-3: untouched until Phase E step 15, where the superseding DEC decides the
  root `allowed-remotes.txt` posture. Proved by `make remotes`.
- INV-5: R-SR-19 adds timeouts and concurrency, never removes a gate; R-SR-23
  removes the 3.9 legs and their required contexts together, pinned by
  `test_ci_gate_required_checks.py`.
- INV-6: R-SR-6 widens the protected set; R-SR-7 adds a digest check that reads
  the bundle's own function. Bundle regenerated in the same slice.
- INV-8, INV-9, INV-10: R-SR-6 narrows what reaches the broker; R-SR-7 adds a
  terminal `BLOCKED`; R-SR-14 refuses malformed arguments before the executor.
  Proved by the containment suites and the new regression tests.
- INV-15: unchanged; `lats_enabled` stays `false`; R-SR-27 moves the graph beside
  the code that uses it.
- INV-16: no cognitive-signal path is touched; `pytest -m governance` on every
  slice.
- INV-17: this document, the closed plan and the two corrected specs are gated by
  `make specs`; `test_spec_selectors_collect.py` adds the vacuous-selector rule.

## Validation matrix

- `make ci` on every slice: ruff + mypy + vulture + py-compat + pytest with
  floors from `governance-policy.json → coverage.{lines,branches,per_file}` +
  lock-check + specs + remotes + validate + check-dedup + digest-regen
  (R-SR-6 … R-SR-29, C-SR-1, C-SR-2).
- `make lint-cold`, `make audit`, `make secrets` on every slice; the
  `secret-scan` and `dependency-audit` job URLs on the pushed head in the PR body
  (C-SR-3, R-SR-19).
- `make attestation` / `make attestation-check` on every protected slice (C-SR-3).
- `make test-regression` for the end-to-end reproductions (R-SR-7, R-SR-9).
- `make specs` on this document and every spec it corrects (R-SR-21, R-SR-30).
- Coverage floors from policy; the baseline on `71223f1` is lines 99.24 %,
  branches 97.87 %, 77 files measured — a report line, not a threshold (C-SR-1).
- Negative test per new gate: R-SR-6, R-SR-7, R-SR-9, R-SR-11, R-SR-12, R-SR-13,
  R-SR-14, R-SR-15, R-SR-17, R-SR-19, R-SR-20, R-SR-21, R-SR-24, R-SR-25 (C-SR-4
  for the compatibility half).
- Carried ids from the closed plans, ledgered here so the orphan rule sees each
  one owned rather than re-derived: R-CQ-1 and R-CQ-2 (AC-1, AC-2); R-CQ-11
  (AC-25); R-CQ-12 (Phase F, conditional on R-SR-27's sunset); R-CQ-14 (AC-11
  unwinds its landed clause); R-CQ-16 and R-CQ-23 (AC-23, by deletion); R-CQ-18
  (AC-29 bootstrap half, Phase F ESLint half); R-CQ-21 (AC-17, AC-18); R-CQ-22
  (AC-27); R-CQ-25 (AC-29); R-CQ-30 (AC-20); C-TDH-2 (AC-19 if the stage lands
  in Phase B, else Phase F).

## Backward compatibility

String-only API histories serialize byte-identically; tool-call histories that
previously produced a 500 now produce a 200 (R-SR-9). `orchestrator.verification_timeout_sec`
has no default: an adopter's present policy without it raises `PolicyError` at
the first verification, matching DEC-043's shape for every other key; the
shipped policy carries it (R-SR-11). Commands that graded `test_execute` and now
grade `destructive` (`make -f <other>`, `make -C`, `pnpm exec <non-runner>`) are
refused with the existing reason strings; no in-tree persona or hook issues them
(R-SR-6). `enable_socket` marks are removed, not deprecated; a downstream test
that opened loopback TCP under the module-level mark must carry its own mark
(R-SR-17). Renamed module paths in Phase E keep PEP 562 shims for one minor
release and warn on attribute access, per DEC-027 (R-SR-27, R-SR-29). The 3.10
floor is the one breaking change for adopters and gets its own spec and DEC
(R-SR-23).

## Explicitly not doing

Recorded so the next audit does not rediscover them, each with the reason:

- The closed plan's R-CQ-13 `retry-parity` child spec, R-CQ-15 mask-width parity,
  R-CQ-19 shell variables for dormant hooks, R-CQ-20 `_deprecation.py`/`env_int`,
  R-CQ-21 fixture-dedup rule, R-CQ-24 marker-liveness gate, R-CQ-26 pre-emptive
  splits, R-CQ-27 archive index, R-CQ-28 `Status:` tier rule, R-CQ-31 and
  AC-31/34/35 process assertions: inventory or ceremony with no defect behind
  them for a single maintainer.
- `ruff format` inside Phase B: 176 files change; it needs its own commit and
  `.git-blame-ignore-revs` entry (Phase F).
- A `HEALTHCHECK` in the Dockerfile: nothing listens (the closed plan was right).
- Pre-emptive decomposition of `write_policy.py` (448/500), `plan_rules.py` (428),
  `nemotron-client.ts` (432): headroom exists; a split lands with the change that
  needs it, and R-SR-6 is the first such change for `write_policy.py`.

## Open questions

1. **Licence.** MIT, Apache-2.0, or proprietary. Blocks R-SR-3 only; the plan
   recommends Apache-2.0 for the patent grant.
2. **Push posture after the mirroring collapse.** A root `allowed-remotes.txt` is
   what `validate_adoption` needs and what DEC-005 withheld to keep agent pushes
   blocked. The superseding DEC must say which control replaces the absence
   (the PreToolUse guard and pre-push hook are the candidates). Blocks Phase E
   step 15 only.
3. **3.10 or 3.11 (narrowed rev 2).** Recommend `requires-python >= 3.10` now;
   3.10 EOL is 2026-10-31. Schedule 3.11 in the same spec as a non-default
   follow-on matrix note — do not block the floor bump on choosing 3.11 first.
4. **LangGraph sunset date (narrowed rev 2).** Proposed DEC-053 must name the
   sunset release; default remains "first minor release after the floor moves"
   unless NS-31 picks otherwise. Memo 1 is not in the tree; DEC-052 is fail-closed
   in place and is **not** the park decision.
