# 2026 coding-standards audit

**Audited head:** `71223f1` (`main`, 2026-09-04) · **Branch:** `claude/2026-standards-audit-u9kxx0`
**Method:** every repo-defined gate executed on this head in a clean venv (tails in §2), six
independent review lenses (Python tooling, security/supply chain, testing, architecture,
DX/docs/polyglot, external 2026 baseline research), GitHub API cross-checks for anything
the tree cannot prove about itself. Each finding carries a confidence tag:
`[Certain]` = executed or read directly, `[Likely]` = strong inference, `[Guessing]` = gap-fill.

---

## 1. Verdict

**No.** The repository is above the 2026 median on the *mechanics* of quality (hash-locked
universal dependency lock, SHA-pinned actions, fail-closed gates, policy-sourced thresholds,
a self-verifying test suite at 99% line coverage) and below it on the *substance* those
mechanics are supposed to protect. Three facts decide the verdict:

1. **Every gate is advisory.** The GitHub branches API reports `"protected": false` for `main`
   (re-queried during this audit). The ruleset at `.github/rulesets/main.json` has never been
   applied. Nine "required" checks, the secret scan, and the audit are enforced by author
   discipline only. This has been the repo's own P0 for four releases. `[Certain]`
2. **The runtime the gates guard is thin.** The orchestrator loop has no context-window
   management, no run/trace id, no checkpoint or resume, no argument validation at tool
   dispatch, and human-in-the-loop is a policy string with no consumer. The API server rejects
   its own output: `TaskResponse.history` is typed `list[dict[str, str]]`, and any run that
   made a tool call produces an assistant message with `content: None` and a `tool_calls`
   list, so the response fails validation and the client gets a 500. Reproduced during this
   audit. `[Certain]`
3. **The language floor is a year past end-of-life.** `requires-python = ">=3.9"`; 3.9 reached
   EOL 2025-10-31 and 3.10 reaches EOL 2026-10-31. FastAPI, pydantic, mcp, langgraph, pytest,
   mypy and pip-audit have all moved to `>=3.10`. The floor is currently held up by four
   compensating waivers (forked pytest pins, a `continue-on-error` audit leg that is also a
   *required* check, a per-file coverage waiver, and a bespoke AST compatibility gate).
   `[Certain]`

What the repo does well is real and should not be undone in the course of fixing the above.
The governance kernel (`governance/broker.py`, `verdict.py`, `verification.py`,
`policy_loader.py`, `write_policy.py`) is more careful than most 2026 agent harnesses: verdicts
are typed so only the harness can construct a PASS, tool authorization is checked at three
layers, credentials are scrubbed from every child environment, and the import graph is acyclic
by test.

### Scorecard by dimension

| Dimension | Grade | One-line reason |
|---|---|---|
| Supply chain & CI hygiene | **A-** | Hash-locked universal lock, `--require-hashes`, SHA-pinned actions, gitleaks over tree + history. Loses points for unhashed tool installs, no job timeouts/concurrency, root Docker image. |
| Enforcement | **F** | Branch unprotected; label-based attestation survives later pushes; one required check cannot fail. |
| Python tooling & typing | **C+** | ruff lint clean and well-documented deferrals; but no `ruff format` (72/98 source files would change), mypy pinned to Aug-2024, no `[build-system]`, no license, 3.9 floor. |
| Testing rigor | **B** | Fail-closed coverage/zero-skip/egress gates; 3,274 tests green. Missing: property-based tests on the model-facing parser, order randomization, mutation tooling, live/contract tests, any LLM eval harness. |
| Agent architecture | **C** | Strong containment kernel; 2023-style loop (shared history, no budgeting per task, no tracing), LangGraph is scaffolding with 5/10 stub nodes, persona prompts written for Claude Code fed verbatim to Nemotron. |
| Agent security (OWASP LLM/ASI) | **C+** | Allowlist command classifier, egress floor, read/write policies. But `python file.py` is graded `test_execute`, which the implementer holds, so write/read/egress policies are bypassable in two tool calls; `.env` sits inside the workspace. |
| DX & docs | **C-** | No LICENSE, no devcontainer/pre-commit/editorconfig/tool-versions, 1,197-line `[Unreleased]` changelog, decision log is single-line pipe rows in a stack subdirectory, ESLint enforces no rule beyond a line budget, JVM stack never built. |

---

## 2. Gate evidence on this head

All gates were executed in an isolated venv built from `requirements-dev.txt` and
`requirements-langgraph.txt`. Claims are not evidence; these tails are.

```text
$ make lint
python -m ruff check .                                   All checks passed!
python -m mypy harness/shared harness/api_server harness/control-plane --explicit-package-bases --check-untyped-defs
                                                         Success: no issues found in 216 source files
python -m vulture ... --min-confidence 80                (clean)
python harness/shared/check_py_compat.py --repo-root .   [PASS] 239 file(s) compatible with Python 3.9.

$ make lint-cold                                         Success: no issues found in 216 source files
$ make lock-check                                        lock-check: passed
$ make coverage-python
==== 3274 passed, 1 skipped, 7 deselected, 10 warnings in 82.92s ====
INFO: [PASS] Coverage branches: 97.87% >= 80.00%
INFO: [PASS] Coverage lines: 99.24% >= 90.00%
INFO: [PASS] Coverage per-file: 74 file(s) meet the lines floor of 90.00% (0 waived)
$ make verify-zero-skips-python                          zero-skip: passed
$ make validate check-dedup specs remotes                --- All governance validators passed ---
                                                         [PASS] 20 per-stack script(s) delegate to the shared kernel
                                                         specs: structural validation passed (24 documents)
$ make digest-regen                                      (no diff)
$ make audit-python                                      pip-audit --requirement requirements-lock.txt: No known vulnerabilities found
$ make secrets                                           gitleaks dir: no leaks found / gitleaks git (285 commits): no leaks found
$ make secrets-allowlist-check                           [PASS] all 7 allowlist entr(ies) still suppress a real finding
$ make lint-node test-node verify-zero-skips             Statements 98.31% Branches 93.77% Functions 100% Lines 98.91%; zero-skip: passed
$ make lock-upgrade-check                                exit 1: anyio 4.14.2→4.15.0, sse-starlette 3.4.8→3.4.10 available (informational)
```

Two gates failed on first attempt for reasons that are themselves findings:

- `make secrets` fails closed after a successful `make secrets-install`, because
  `go install` drops the binary in `$(go env GOPATH)/bin`, which the recipe never adds to
  `PATH`. Re-running with `PATH="$(go env GOPATH)/bin:$PATH"` passes. `[Certain]`
- `.claude/hooks/session-start.sh` installs `requirements-dev.txt` (unhashed) with system pip;
  in this container that install aborted on a Debian-owned PyJWT and silently left mypy and
  pytest missing. CI installs `--require-hashes -r requirements-lock.txt`; the hook should
  use the same recipe. `[Certain]`

GitHub-side state at audit time: CI green on `main` head; eight Dependabot PRs open and
unmerged (actions/checkout v7, setup-python v7, setup-node v7, setup-go v7, pnpm/action-setup
v6, plus three npm dev bumps); zero git tags despite `version = "2.4.0"`.

---

## 3. Findings, ranked

Severity reflects impact on the "meets 2026 standards" question, not merge risk on this PR.

### Blockers

| # | Finding | Evidence | Fix |
|---|---|---|---|
| B1 | **Branch ruleset committed but never applied; `main` is unprotected.** Every required check, review rule and push restriction is advisory. PR #60 merged red; #79/#80 merged with zero reviews. `[Certain]` | GitHub API `protected: false`; `NEXT_STEPS.md:44-56`; `.github/rulesets/main.json` | Import the ruleset now. Add `required_signatures` and `required_linear_history` at the same time. Add a scheduled job that queries the branches API and opens an issue while `protected == false`, so the gap self-reports. |
| B2 | **No license.** No `LICENSE`, no `license` in `pyproject.toml` or `package.json`, while README and `harness/CONTRACT.md` position the repo as an adoption template. `[Certain]` | `ls LICENSE*` → none; `pyproject.toml:1-11` | Add `LICENSE`, PEP 639 `license = "..."` + `license-files`, and `"license"` in `harness/node/package.json`. If proprietary, say so in README. |
| B3 | **API server 500s on every tool-using run.** `TaskResponse.history: list[dict[str, str]]` rejects `content: None` and `tool_calls: [...]`; the blanket `except` converts it to "Internal orchestration error". The only test uses string-only history. `[Certain]` — reproduced: `history.0.content Input should be a valid string`; `history.0.tool_calls Input should be a valid string`. | `harness/api_server/main.py:46,105-119`; `orchestrator/loop.py:166` | Typed message models (union of system/user/assistant-with-tool_calls/tool) or `list[dict[str, Any]]` as a stopgap; add a test whose mocked history contains a tool call. |

### High

| # | Finding | Evidence | Fix |
|---|---|---|---|
| H1 | **Python 3.9 floor, one year past EOL; 3.10 EOL in eight weeks.** Held up by: forked pytest pins (`8.4.2` on 3.9 carries PYSEC-2026-1845), `dependency-audit (3.9)` is `continue-on-error` *and* a required check (so one of nine required contexts is vacuous), `coverage.optional_extras` waiver, `check_py_compat.py`, and interpreter-conditional `mcp`/`langgraph` deps that make `mcp_server.py` dead on the floor interpreter. `[Certain]` | `pyproject.toml:4`; `requirements-dev.txt:5-11`; `.github/workflows/python-package.yml:44,320`; DEC-028 | Write the spec DEC-028 asks for; bump to `>=3.10` now and plan `>=3.11` for November; drop all four waivers; add 3.14 to the matrix; drop `target-version` (ruff infers from `requires-python`). |
| H2 | **Runtime policies are bypassable in two tool calls.** `python <file>.py` and `pytest` classify as `test_execute`, which the implementer role holds. A script written with `write_file` and then executed can write `.git/hooks`, `.mango/hooks`, protected paths, read `.env` (which lives in the workspace, and the API server's workspace *is* the repo root), and open sockets. Egress denial is by argv[0] name only. `broker.py:18-25` already admits "containment, not isolation", but `SECURITY.md` and `agent-policy.json` present these as controls. `[Certain]` on mechanism | `governance/command_actions.py:165,233`; `agent-policy.json:32`; `api_server/main.py:20,96`; `nemotron_bridge.py:140-143` | Run `ProcessBackend` under OS isolation (container/bwrap/nsjail, `--unshare-net`, `.git`/`.mango`/`.env` masked or read-only). Until then, reword SECURITY.md and move `.env` out of the workspace for the API path. |
| H3 | **`infra-reviewed` label persists across later pushes.** The ruleset dismisses stale *reviews* on push; labels are never dismissed. A PR labelled once can accept arbitrary later commits to workflows, Makefile and policies and stay green. `[Certain]` | `python-package.yml:84,201`; `rulesets/main.json:18` | Bind the attestation to the head SHA (attestation-check requires the SHA in the table), or a workflow that strips the label on `synchronize`. |
| H4 | **No context-window management in the loop.** One `conversation_history` is shared across planner → reasoner → verifier; every role appends another system message and the whole history (tool results up to 64 KiB each, up to 100 calls per role) is resent on every call. No token counting, truncation or compaction. `usage` from the provider is discarded. `[Certain]` | `orchestrator/loop.py:89,132-136,144,166`; `governance-policy.json:98` | Per-role message lists seeded from a summarized handoff; read `usage.prompt_tokens`; evict oldest tool results against a policy `context_budget_tokens`. |
| H5 | **Human-in-the-loop is declared, not implemented.** `human_approved` is a broker flag no live path sets; LangGraph `clarify`/`escalate` are stubs that auto-pass; `human_approval_required` has no runtime reader. `[Certain]` | `governance/broker.py:133`; `langgraph/nodes.py:259-281`; `governance-policy.json:77-83` | Implement `interrupt()` with a checkpointer and `thread_id`; approval token bound to `(agent_id, action, target)` with expiry. |
| H6 | **Observability is unstructured logs.** No run/trace id on the primary path; `JSONFormatter` drops `extra=` fields; no per-call record of tool name, latency, tokens, outcome. OpenTelemetry GenAI conventions are still "Development" status, so pin to a commit rather than wait. `[Certain]` | `json_logging.py:35-46`; `loop.py:155-166`; `NEXT_STEPS.md:268-294` | Generate `run_id` in `execute_loop`, thread it through dispatch and `CognitiveSignal`; one structured event per model call and per tool call; OTel spans behind an optional extra. |
| H7 | **No property-based testing or schema validation at the model boundary.** `_normalize_tool_arguments` only coerces to dict; handlers do `args.get(x) or ""`, so a missing required `filepath` becomes `""` and reaches the executor; `additionalProperties: false` is advertised in schemas but never enforced. 13 hand-picked example tests. `[Certain]` | `tool_dispatch.py:15-47`; `orchestrator/dispatcher.py:41-60,118-127`; no `hypothesis` in dev deps | Validate `args` against `function.parameters` (jsonschema/pydantic) at dispatch; add `hypothesis` strategies over JSON-ish input asserting "never raises, always returns a dict". |
| H8 | **No test-order randomization or parallelism, after an order-coupling bug was found by luck.** Root `conftest.py` records that the suite "passed only because alphabetical collection happened to put them the other way round". `os.chdir` in tests would break under xdist. `[Certain]` | `conftest.py:44-52`; `tests/test_validators.py:25-58`; `api_server/tests/test_main.py:13` (module-level `TestClient`) | Add `pytest-randomly` (seed printed in CI) and `pytest-xdist -n auto`; replace `os.chdir` with `monkeypatch.chdir`. |
| H9 | **Mutation testing is a manual ritual recorded as prose.** `gate-mutation-proof` describes a by-hand loop; results appear in CHANGELOG as "five mutation proofs". No tool, no score, no target. This is exactly the unverifiable claim CLAUDE.md rejects. `[Certain]` | `.mango/skills/gate-mutation-proof/SKILL.md:40-58`; `CHANGELOG.md:56,134,196,299` | `mutmut` scoped to `orchestrator/`, `tool_dispatch.py`, `tool_executors.py`, `command_actions.py`, `write_policy.py`; nightly first, then a `mutation.min_score` policy floor on changed files. |
| H10 | **Live model contract never exercised in CI; no LLM eval harness.** No workflow supplies `NVIDIA_API_KEY`; Node live tests are waived until 2027-01-01; the eval spec is DRAFT with zero implementation; the only prompt tests are substring pins. `[Certain]` | `scheduled-drift.yml:66`; `node/.governance/skip-waivers.json`; `openspec/changes/add-neurosym-governed-synthesis/specs/agent-evaluation/spec.md` | Secret-gated nightly `live-smoke` job; record real NIM responses and replay them (respx/cassettes) in PR CI; implement AC-AE-1/2/3/5 with mocked transcripts; snapshot rendered system prompts. |
| H11 | **`ruff format` is not adopted.** No `[tool.ruff.format]`, no target, no CI step; `ruff format --check` would change 176 of 360 files (72 of 98 non-test source files). `E`/`W` are selected but the formatter that replaced them in 2026 is absent. `[Certain]` | `pyproject.toml:84-110`; `grep -rn "ruff format"` → 0 | One reformat commit recorded in `.git-blame-ignore-revs`; add `ruff format --check` to `lint-python`. |
| H12 | **Packaging is pre-PEP-621 in substance.** No `[build-system]` (pip falls back to legacy setuptools), no `description`/`readme`/`authors`/`classifiers`/`urls`, no `[project.scripts]` (which is why 30 `sys.path.insert` bootstraps and 28 per-stack shim files exist), tests shipped in the wheel, no `py.typed`, `httpx` declared as runtime but imported only by tests. `[Certain]` | `pyproject.toml:1-28`; `grep -rn sys.path.insert harness` → 30 | Declare `hatchling` or `setuptools>=77`; fill metadata; console scripts for API server, MCP server and gate scripts; `exclude = ["harness.*.tests*"]`; move `httpx` to the dev group. |
| H13 | **ESLint enforces nothing.** `eslint.config.js` extends no ruleset; the only rules are `no-unused-vars: off`, `no-undef: off`, and `max-lines`. `eslint --max-warnings=0` in `make lint-node` is near-vacuous while README and CONTRACT present it as a gate. `[Certain]` | `harness/node/eslint.config.js:38-79` | Add `tseslint.configs.recommendedTypeChecked` and `js.configs.recommended`; add a liveness test that at least one type-aware rule is active. |
| H14 | **JVM stack violates the repo's first non-negotiable and is never built.** Coverage floors are literals in `build.gradle.kts`; no wrapper, no lockfile, no verification metadata (templates only); 41 LOC of Kotlin; 3 file-content tests; zero root-workflow references. `[Certain]` | `harness/jvm/build.gradle.kts:53-54`; `harness/jvm/Makefile:15-17` | Either move it to `docs/adopters/jvm-template/` and delete its 14 shims and 8 personas, or commit wrapper + lock + verification metadata and add a CI job. Not both halves. |
| H15 | **Decision log and changelog are accreting prose, not records.** 48 decisions as single pipe-delimited lines (max 4,591 chars) in `harness/node/.governance/decision-log.md` although they are repo-wide; every entry must be restated in a 31 KB `GOVERNANCE_SKILL.md` by validator; `docs/decisions/` does not exist. `[Unreleased]` is 1,197 lines with shell transcripts while policy caps release sections at 400. Zero git tags for `2.4.0`. `[Certain]` | `harness/node/.governance/decision-log.md:3`; `CHANGELOG.md:11-1208`; `git tag` → empty | MADR-style `docs/decisions/DEC-NNN-*.md` with status/context/consequences and machine-readable supersession; Keep-a-Changelog categories; tag `v2.4.0`; `git-cliff` or `release-please` from the conventional-commit subjects already in use. |
| H16 | **Verification timeout uses the model-latency key.** `make test-python` (3k tests, ~85 s here) runs under `orchestrator.api_timeout_sec` (300 s); a slow runner turns a real verdict into `BLOCKED/harness_fault`. `[Certain]` on mapping | `governance/verification.py:88-90`; `mango_mas_orchestrator.py:94-96` | Add `orchestrator.verification_timeout_sec` to policy and `OrchestratorLimits`. |

### Medium

| # | Finding | Evidence | Fix |
|---|---|---|---|
| M1 | Tool budget is per-role on the live path (3 × 100 per task), not per-task as `tool_budget.py` intends; only the LangGraph node threads it. `[Certain]` | `loop.py:139,197,219,223` | One `ToolBudget` per `execute_loop`, passed to all three roles. |
| M2 | Persona prompts written for Claude Code subagents are fed verbatim to Nemotron: they name `Bash/Read/Grep/Glob`, skills and `make pre-pr`, none of which exist in the tool bridge. No prompt hash/version. `[Certain]` | `.mango/agents/nemotron-reasoner.md:4,26-27`; `loop.py:96-105` | Split subagent personas from runtime system prompts; generate the tool paragraph from `NEMOTRON_TOOLS`; log a prompt sha. |
| M3 | LangGraph variant is scaffolding: 5/10 nodes stubs, `shadow_planner_node` always 0.0 divergence, two nodes edgeless, `recursion_limit`/`max_concurrency` loaded and never applied, `checkpointer=None`. Only caller is experimental. `[Certain]` | `langgraph/graph.py:109-118,157-165`; `nodes.py:88-102,181` | Either make it the runtime (apply limits, interrupts, checkpointer) or move it under `experimental/`. |
| M4 | Meta-tools are write-only and install-path-scoped: nothing reads `knowledge_gap_log`/`hypothesis_register` output; `MEMORY_DIR` is resolved from the harness install path so all workspaces share one store. `[Certain]` | `meta_tools.py:20-22,117-166` | Feed open gaps into the next planner prompt; scope the store under the workspace. |
| M5 | Model client is a function, not a provider boundary; `max_retries` defaults to 0; retry base/cap/jitter keys are read by `RetryPolicy.from_mapping` but never populated by `_ENV_VAR_KEYS`; `stream: False` hard-coded; no token/cost ledger. `[Certain]` | `nemotron_bridge.py:118-124,237,256`; `retry_policy.py:151-156` | `ChatProvider` Protocol; typed `ChatResult(message, usage, latency_ms)`; retries on by default. |
| M6 | Import-time policy I/O: `process_backend` reads the policy at import and `governance/__init__` eagerly imports the whole package, so importing `verdict` executes `broker`; the layering test deliberately ignores `__init__` edges and so measures a graph Python does not execute. `[Certain]` | `governance/process_backend.py:23,31`; `governance/__init__.py:7-14`; `test_import_direction.py:50` | Resolve defaults in `ProcessBackend.__init__`; thin or lazy `__init__`; stop excluding `__init__` edges. |
| M7 | Thresholds have a third copy in `GraphPolicy` dataclass defaults plus policy-external literals (shadow timeout 60 s, signal 256 KiB, lock 10 s, port 8080…) reconciled via the `EXCLUDED` list in `test_constant_triage.py`. `[Certain]` | `langgraph/policy.py:21-53`; `test_constant_triage.py:221` | Default-less `GraphPolicy`; move operational literals into policy blocks. |
| M8 | Duplicate dispatch tables: `mcp_server._build_tool_handlers` hand-mirrors `ToolDispatcher.tool_handlers` (docstring admits it); five loop-like constructs exist (`loop.py`, `nodes.py`, `TestHealer`, `LATSOptimizer`, shadow planner ×2). `[Certain]` | `mcp_server.py:53-100` vs `dispatcher.py:42-60` | One `ToolRegistry` consumed by dispatcher, MCP and `tools_for_role`. |
| M9 | MCP server runs synchronous subprocess handlers inline in `async def handle_call_tool`, blocking the loop. `[Certain]` | `mcp_server.py:143-161` | `await asyncio.to_thread(handler, args)`; select ruff `ASYNC`. |
| M10 | mypy pinned at 1.11.2 (Aug 2024; mypy 2.x current); `warn_unused_ignores` off (18 would fire), `disallow_any_generics` off (37 bare generics), global `ignore_missing_imports`, no overrides, no `py.typed`. The `--strict` deferral's counts are stale and mostly test-side. `[Certain]` | `requirements-dev.txt:20-21`; `pyproject.toml:107-111`; `test_deferred_rigor.py:113-126` | Bump; `[[tool.mypy.overrides]]` strict on source, relaxed on tests; scope `ignore_missing_imports` to `mcp.*`, `langgraph.*`. |
| M11 | Deferral register conflates "expensive in tests" with "expensive": `ARG`, `PT`, `S`, `PTH` deferred wholesale when `per-file-ignores` on `**/tests/**` would enable them for source at near-zero cost; `FA`, `ANN`, `RET`, `PERF`, `FURB`, `ASYNC`, `LOG`, `PL*` never evaluated. `[Certain]` | `test_deferred_rigor.py:47-111` | Split deferrals by scope; add unevaluated families with counts. |
| M12 | Module-wide `enable_socket` disables the egress floor for 29 tests; the real need is asyncio's unix `socketpair`, which `--allow-unix-socket` covers. The api_server justification ("TestClient drives the app over loopback") is inaccurate: TestClient is in-memory ASGI. `[Likely]` | `tests/test_mcp_server.py:20`; `test_autonomous_healing.py:12`; `api_server/tests/test_main.py:37-168` | `--allow-unix-socket` in addopts; per-test marks only where TCP is actually opened. |
| M13 | Over-mocking at the bridge/MCP boundary: `Path` patched wholesale, HTTP as `MagicMock` at `urlopen`, MCP SDK replaced by hand-rolled fakes with one real-SDK test routed around an autouse fixture. `[Certain]` | `test_nemotron_bridge.py:32-52`; `test_mcp_server.py:23-70` | Boundary fakes at the transport; real SDK on ≥3.10 legs. |
| M14 | No OpenAPI snapshot or schemathesis run; no `/healthz`/`/readyz`; no version prefix; synchronous 300 s×N request holds a threadpool slot with no job model; orchestrator workspace is the server's own source tree. `[Certain]` | `api_server/main.py:17,20,88-125` | `POST /v1/runs` → 202 + id; health/readiness; workspace from config; committed `openapi.json` + schemathesis. |
| M15 | Tooling installs are unhashed: `pip install --upgrade pip` floats; `pip-audit==2.9.0` and `uv` installed without `--require-hashes` inside the audit job with the repo checked out. `[Certain]` | `python-package.yml:61,115`; `Makefile:293` | Hashed `requirements-tools.txt` compiled by uv. |
| M16 | No `timeout-minutes` and no `concurrency` groups on any job. `[Certain]` | both workflows | Add both. |
| M17 | Docker: base not digest-pinned, runs as root, no `HEALTHCHECK`, dev deps shipped (`--loader tsx` is a devDependency), never built or scanned in CI. `[Certain]` | `Dockerfile:2,38` | Digest pin, `USER node`, multi-stage prod-only, Trivy + CycloneDX SBOM in CI. |
| M18 | No `required_signatures`/linear history; agent commits unsigned. Dependabot lacks `docker`/`gradle` ecosystems and `cooldown` (GitHub default is now 3 days). `[Certain]` | `rulesets/main.json`; `.github/dependabot.yml` | Add rules; add ecosystems; configure cooldown explicitly. |
| M19 | Prompt-injection handling is declarative only: tool output is appended verbatim as `role: tool` with no untrusted-content framing; `untrusted_content_is_data: true` has no reader. `[Certain]` | `orchestrator/dispatcher.py:130`; `agent-policy.json:67` | Delimit tool results with a "data, not instructions" preamble; keep structural sandbox as primary. |
| M20 | API server: no rate limit, no size bound on `task`, single static key; acceptable only because default host is loopback and Vercel deploy was killed with `vercel.json`. `[Certain]` | `api_server/main.py:39-40,88-99` | `max_length`, rate limit at proxy, per-caller keys before any non-loopback exposure. |
| M21 | Onboarding lacks 2026 baseline files: no `.devcontainer/`, `.pre-commit-config.yaml`, `.editorconfig`, root `.python-version`/`.tool-versions`; `make pre-pr` needs Python + pnpm + Go + uv and README never mentions `corepack enable`; CONTRIBUTING says `pre-pr` "must pass" and then concedes Go tools may not install. `[Certain]` | `CONTRIBUTING.md:29-45`; `README.md:244-277` | devcontainer (the session-start hook is most of it), `mise.toml`, pre-commit with ruff/ruff-format/prettier/gitleaks. |
| M22 | `openspec/` is an orphaned second spec system: three proposals outside `docs/specs/`, the `openspec` CLI is in no requirements file or workflow, `REQUIRE_STRICT_SPEC_VALIDATOR` defaults to 0 so the strict tier has never run. `[Certain]` | `harness/shared/validate_specs.sh:12-22` | Install and pin it with the strict tier required, or fold the proposals into `docs/specs/` and delete the tier. |
| M23 | Per-stack mirroring is accidental complexity: 14 + 14 shim scripts, byte-identical `policy.json`/`agent-policy.json` across node and jvm, 7/8 identical personas; root `make validate` executes repo-wide governance from inside `harness/node`. `check_dedup.py` is a gate for a problem the layout created. `[Certain]` | `Makefile:157-164`; `diff -rq harness/node/scripts harness/jvm/scripts` | Root `.governance/`; `--workspace` flag on shared tools; delete both `scripts/` dirs and `check_dedup.py`. |
| M24 | Skills live only in `.mango/skills/` and a test forbids any other root; Claude Code discovers `.claude/skills/`. The Stop hook that would remind an agent to run them is dormant (DEC-003). `[Likely]` | `test_agent_surface_liveness.py:179-197`; `.mango/settings.json` | Symlink or move under `.claude/skills/`. |
| M25 | Structured logging inconsistent: 8 gate scripts call `logging.basicConfig` directly duplicating `GATE_LOG_FORMAT`; `validate_specs.py` hard-codes INFO. `[Certain]` | `json_logging.py:26,101` and callers | Route all through `configure_gate_logging`; add `extra` support. |
| M26 | Stale doc claims: `harness/CONTRACT.md:49` says CI examples contain `PIN_FULL_COMMIT_SHA` (zero remain); `harness/node/Agent.md:7` claims React/Vite/WebSockets scope with no such deps; C4 doc lists `/health`, `/v1/orchestrator/run`, `/v1/models` and "streams reasoning", none of which exist. `[Certain]` | as cited; `docs/architecture/c4_architecture.md:41,85,125,333` | Fix; extend `test_documentation_truth.py` to assert route claims against `app.routes`. |

### Low (abbreviated)

- `make secrets` fails after `make secrets-install` because `GOPATH/bin` is never added to `PATH` (reproduced). Add it to the recipe. `[Certain]`
- `.claude/hooks/session-start.sh` installs unhashed `requirements-dev.txt` instead of `--require-hashes -r requirements-lock.txt`; in this container it aborted silently. `[Certain]`
- Root `Makefile` lacks `.SHELLFLAGS := -eu -o pipefail -c` that both stack Makefiles set. `[Certain]`
- `check_hardcoded_secrets` in `validate_invariants.py` matches four literals with a mandatory space before `=` and only `.py` files; gitleaks is the real control. Delete or strengthen. `[Certain]`
- Gitleaks allowlist `.*\.example.*` is unanchored. `[Certain]`
- `go-version: 'stable'` floats the toolchain compiling gitleaks/osv-scanner. `[Certain]`
- `nemotron_bridge` accepts `http://` base URLs for a bearer-token call. `[Certain]`
- `_finalize_response` fabricates an assistant message from the last tool result and mutates history. `[Certain]`
- Hooks receive the full prompt in one env var (`E2BIG` risk); `check=True` on post-hooks kills a completed run. `[Likely]`
- `agent-policy.json` is re-read from disk on every tool call. `[Certain]`
- Six domain exceptions with no common base. `[Certain]`
- Two latent `pytest.skip` calls carry no decision id. `[Likely]`
- All 12 Python waivers expire on one day (2027-09-02); all Node waivers on 2027-01-01. `[Certain]`
- Clock-dependent tests without a frozen clock. `[Likely]`
- `make test-regression` re-runs a subset CI already runs. `[Certain]`
- Version duplicated by hand in `pyproject.toml` and `README.md`. `[Certain]`
- `vercel.json` kill-switch and `pnpm-lock.yaml.template`/`gradle.lockfile.template` are leftovers. `[Certain]`
- Issue templates are Markdown, not YAML forms; no spec-proposal form for a spec-driven process. `[Certain]`

---

## 4. What is above the 2026 bar (keep it)

- Universal, hash-generated lock installed with `--require-hashes` on every leg; `lock-check` diffs hashes, not just pins; `test_dependency_lock_contracts.py` pins the contract.
- Every `uses:` SHA-pinned with version comments; workflow token `contents: read`; no `pull_request_target`.
- gitleaks over tree and full history, with an allowlist that must keep earning each entry.
- Coverage gate that refuses a policy without numeric floors, refuses a report without branch data, and checks the measured set covers every first-party file.
- Zero-skip evidence written by a root `conftest.py` hook, proven via `pytester`, with class-scoped expiring waivers.
- Egress floor asserted by a test that proves a socket raises, not by config alone.
- Typed verdict that only `VerificationRunner` can construct; the model's own `VERDICT: PASS` is advisory.
- Three-layer tool authorization with a recorded history of the bypass that motivated each layer.
- A deferral register (`test_deferred_rigor.py`) that records *why* each lint rule is off with a live-measured count and a revisit threshold.
- `BLE` + `RUF100` so every `noqa` in the tree is load-bearing; zero `shell=True`; zero `os.path`; DTZ-clean.
- PR bodies that actually paste gate tails and derived attestation tables.

---

## 5. Remediation roadmap

Ordered by leverage per hour. Items 1 to 4 are settings or one-file changes.

1. **Apply the ruleset** (B1) and add signatures + linear history. Add the self-reporting scheduled check.
2. **Add LICENSE and PEP 621 metadata** with `[build-system]` (B2, H12 part 1).
3. **Fix `TaskResponse.history`** and add the tool-call history test (B3).
4. **Fix `make secrets-install` PATH and the session-start hook install recipe** (Low).
5. **Bump the floor to 3.10** with the spec DEC-028 requests; remove the four waivers; add 3.14 to the matrix (H1). Plan `>=3.11` for November.
6. **Adopt `ruff format`** in one commit with `.git-blame-ignore-revs` (H11).
7. **Bind attestation to head SHA** (H3); add `timeout-minutes` and `concurrency` (M16); hash the tool installs (M15).
8. **`pytest-randomly` + `pytest-xdist`**, `--allow-unix-socket`, `hypothesis` on `tool_dispatch`/`dispatcher` (H7, H8, M12).
9. **Schema-validate tool args at dispatch** and introduce a `HarnessError` hierarchy (H7, Low).
10. **Loop hardening**: per-task budget (M1), run_id + structured per-call events (H6), `verification_timeout_sec` (H16), context budget (H4).
11. **Decide the LangGraph question** (M3) and the JVM question (H14). Both are "in or out"; the current halfway state costs gates and personas.
12. **Move decisions to `docs/decisions/` as ADRs, tag `v2.4.0`, trim `[Unreleased]`** (H15).
13. **ESLint recommended-type-checked** (H13); collapse per-stack mirroring (M23).
14. **OS-level sandbox for `ProcessBackend`** and move `.env` out of the workspace (H2). This is the largest item and the one that turns "containment" into the isolation the docs already claim.
15. **Eval harness + nightly live smoke + recorded cassettes** (H10) and mutation score (H9).

---

## 6. Baseline used (Sept 2026)

Sourced by the research lens; dates are the source's, not inferred.

- Python: 3.9 EOL 2025-10-31; 3.10 EOL 2026-10-31; 3.14 stable (2025-10-07); 3.15 final due 2026-10-01. FastAPI, pydantic, mcp, langgraph, pytest 9, mypy 2, pip-audit 2.10 all `>=3.10`; pip 26.1 dropped 3.9.
- Packaging: PEP 621 + PEP 735 dependency groups; PEP 751 `pylock.toml` final with pip 26.1 and uv support; explicit `[build-system]`; hash-verified installs.
- Lint/type: ruff 0.16.x with `ruff format` as the Black replacement; mypy 2.x (parallel, `--strict-bytes` default); `ty` still beta; Pyright/Pyrefly for editors, mypy as CI gate.
- Testing: pytest 9; `pytest-randomly` + `xdist` norm; Hypothesis for model boundaries; mutation testing selective; schemathesis for OpenAPI; DeepEval/Promptfoo/Inspect for LLM evals.
- Supply chain: OpenSSF Scorecard 20 checks; SLSA 1.2; GitHub artifact attestations; Dependabot 3-day cooldown default since 2026-07-14; rulesets as the branch-protection successor (one-click migration 2026-08-11).
- Agentic: OWASP LLM Top 10 (2025) and OWASP Agentic Top 10 (2026 ed.: ASI01 goal hijack … ASI05 unexpected code execution … ASI10 rogue agents); MCP spec 2026-07-28 (stateless core, OAuth 2.1 + PKCE, RFC 9728/8707/9207, DCR deprecated); OTel GenAI conventions still Development-status; shared-kernel containers judged insufficient for model-generated code.
- FastAPI: lifespan, pydantic v2, `Annotated` deps, OTel instrumentation, separate liveness/readiness.
