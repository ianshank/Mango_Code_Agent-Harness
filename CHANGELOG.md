# Changelog

All notable changes to this project will be documented in this file.

> **Scope:** repository-level changes (roadmap, CI, tooling, docs). Harness
> gate-contract versions are tracked separately in `harness/CHANGELOG.md`.

## [2.4.0] - 2026-09-01

### Added

- `harness/shared/orchestrator/` module encompassing `dispatcher.py`, `loop.py`, and `hook_runner.py` to cleanly encapsulate the previously monolithic ReAct orchestrator loop.
- Comprehensive LATS MCTS optimization fixes for negative reward bounds.
- MCP Unicode logging safety in the `mcp_server.py`.

### Changed

- Decomposed `mango_mas_orchestrator.py` into smaller domain modules (`harness.shared.orchestrator.*`).
- `MangoMASOrchestrator` is now a backwards-compatible facade that delegates to the new submodules.
- Strict `mypy` typing across `harness/shared` completely stabilized for dict mappings and `MangoState` implementations.

## [2.3.0] - 2026-08-31

### Added

- `harness/shared/autonomous_healing.py` for test-driven agent remediation.
- `harness/shared/lats_optimizer.py` and `harness/shared/langgraph/ablation.py` for MCTS node expansion.
- `harness/shared/mcp_server.py` Model Context Protocol (MCP) STDIO server.
- `.mango/skills/agent-memory-manager/` skill for persistent multi-agent context.

### Changed

- Wired authority and budget decorators onto existing LangGraph nodes.
- Fortified `@with_authority` and `@budgeted` decorators to fail closed on lookup errors.
- Synchronized `policy-artifact.json` drift and updated governance policy for healing retries.


## [v2.2.4] - 2026-08-30

### Added — LangGraph StateGraph Multi-Agent Orchestration Engine Overlay

- **12-Channel Typed State Architecture (`harness/shared/langgraph/state.py`)**:
  - Implemented `MangoState` `TypedDict` with 4 Accumulator channels (`patches`, `findings`, `test_results`, `errors`) reduced via `operator.add`, and 8 Last-Write-Wins (LWW) channels (`task`, `plan`, `shadow_plan`, `plan_divergence`, `revision_count`, `gate_status`, `verdict`, `tool_budget_used`).
  - Strict disjointness and channel count invariants verified by `test_langgraph_state.py`.
- **Active & Gate Node Topology (`harness/shared/langgraph/nodes.py`)**:
  - Implemented 10 topology nodes: `planner_node`, `shadow_planner_node`, `implementer_node` (wrapping `nemotron-reasoner`), `evaluation_node` (wrapping `verifier` & `VerificationRunner`), `plan_gate_node`, `quality_gate_node`, `clarify_node`, `escalate_node`, `peer_reviewer_node`, and `security_reviewer_node`.
  - Hardened with signature-safe `config=None` and `_get_configurable` extraction supporting both positional and keyword invocation from LangGraph's execution runtime.
  - Fail-open exception trapping recording directly to the `errors` state channel.
- **StateGraph Assembly & Conditional Routing (`harness/shared/langgraph/graph.py`)**:
  - Implemented `build_graph()` assembling the full supervisor-gated DAG with conditional routing on plan gate divergence (`<= 0.35`) and quality gate test verdicts.
- **Role Authority & Budget Enforcement Decorators (`harness/shared/langgraph/decorators.py`)**:
  - Implemented `@with_authority` (gated via `agent_authority.allowed_actions`) and `@budgeted` (gated via `policy_loader.max_tool_calls_per_task`).
- **AQA / Regression Matrix (`test_langgraph_regression.py`)**:
  - 32 dedicated regression tests pinning node calling conventions, state immutability, accumulator concatenation, error isolation, and boundary conditions.
- **Root Makefile & Tooling**:
  - Added `make test-langgraph` target; updated `.gitignore`, `.dockerignore`, and `.gitleaks.toml`.

### Operations & Testing — Full test suite coverage gap fill and AQA/regression expansion

Systematic coverage audit identified 9 source modules with zero direct test
coverage, plus 2 missing regression/AQA tiers. Created 11 new test files
containing 107 new tests, bringing the Pytest total from 2,174 to 2,300
(0 failures). All 60 source files now meet the per-file 90% line coverage
floor. Four defects triaged with RCA:

- **11 new test files** covering previously untested modules:
  `json_logging`, `tool_dispatch`, `validate_adoption`,
  `validate_agent_policy`, `validate_governance_docs`, `validate_policy`,
  `governance/check_traceability`, `governance/process_backend`,
  `governance/verification`.
- **2 regression/AQA expansion files**:
  `regression/test_coverage_gap_regression.py` (pins fixes for log level
  fallback, tool argument normalization, byte-level truncation),
  `regression/test_nemotron_api_aqa.py` (bridge smoke, env resolution,
  secret masking, egress floor via `pytest-socket`).
- **RCA-1**: Escaped docstrings (`\"\"\"` vs `"""`) caused `SyntaxError` in
  the `test_test_quality.py` AST scanner; rewrote with proper syntax.
- **RCA-2**: Case-sensitivity bug — `"no requirement IDs".lower()` doesn't
  match `"no requirement IDs"` because `IDs` → `ids`.
- **RCA-3**: `VerificationRunner.probe()` returned `BLOCKED` on Windows
  because `shutil.which("make")` is `None`; tests now mock the PATH lookup.
- **RCA-4**: 5 happy-path tests lacked explicit `assert` statements; added
  `capsys` fixtures asserting `"passed"` in stdout.

**Verified**: 2,300 passed | 0 failed | 98.17% lines | 95.71% branches |
60/60 per-file | ruff clean | mypy clean (162 files, 0 issues).

### Fixed — `GraphPolicy` hardcoded values and a fail-open bug (PR #53)

Spec: `docs/specs/langgraph-policy-wiring.md`. Found by a tech-debt audit
whose draft plan was itself peer-reviewed by four personas (Architect,
SDLC/CI Lead, QA Director, Product Manager) before implementation, which
caught that the flagship finding targeted code no CI job installs
`langgraph` for, and found a second, more severe bug in the same function
the first draft missed.

`harness/shared/langgraph/policy.py`'s `GraphPolicy.from_governance_json()`
never populated `recursion_limit`, `max_concurrency`, or
`plan_divergence_threshold` from `governance-policy.json` at all — the
policy had no corresponding section — despite the module's own docstring
claiming it avoided hardcoded values. A new `policy_loader.langgraph_defaults()`
closes this, matching the existing `orchestrator_defaults()`/`nemotron_defaults()`
pattern. Two call sites bypassed `GraphPolicy` entirely with independent
literals that happened to match its dataclass defaults, so nothing had ever
caught the drift risk: `graph.py`'s `_route_quality_gate()` (`revision_count < 10`)
and `nodes.py`'s `plan_gate_node()` (`divergence <= 0.35`). Both now read
`GraphPolicy` via `config["configurable"]["policy"]` — the same mechanism
`nodes.py` already uses to thread `orchestrator` through node calls — falling
back to `GraphPolicy()`'s built-in defaults (numerically identical to the
literals removed) when no config is supplied, so every existing bare-state
caller observes unchanged behavior. `build_graph()` now defaults to
`GraphPolicy.from_governance_json()` instead of a bare `GraphPolicy()`.

The more severe bug, found independently during peer review:
`from_governance_json()` wrapped its entire load in a bare
`except Exception: return cls()`, silently substituting hardcoded defaults
not only when the policy file was absent (the legitimate adopter path,
already handled gracefully by `policy_loader`) but also when it was
*present and malformed* — contradicting `policy_loader.py`'s own documented
fail-closed contract. This is the sixth recurrence of the same pattern in
this repository's decision log (`COV_MIN=80`; the `size_budget_lines`/
`check_dedup`/`check_py_compat` trio; DEC-005; DEC-006; DEC-009). The
blanket `except` is removed; a malformed policy now raises. The existing
test for this code (`test_langgraph_policy.py`) was not a safety net — its
assertions all checked values numerically identical between the dataclass
default and the live policy, so they passed whether or not wiring worked,
and its one fallback test defined a helper it never called and monkeypatched
a method it never invoked. Rewritten with tests that inject a distinguishable
(non-default) policy value and a malformed-policy fixture to prove both the
wiring and the fail-closed behavior directly.

Both target branches are masked by other Phase-1 stubs today
(`quality_gate_node` always passes; `shadow_planner_node` always reports
0.0 divergence) and `build_graph()` is not called from any live
orchestration path (confirmed: no CI job installs the `langgraph` package),
so this completes self-documented scaffolding rather than fixing a live
production defect — fail-open is still fixed regardless of reachability.

### Added — enterprise hygiene, evidence-checked coverage-gap closure, and two accepted-debt decisions (PR #53)

`.github/CODEOWNERS` (a `protected_paths` pattern existed for it but the
file didn't — the "silently protects nothing" class `test_protected_path_liveness.py`
exists to catch), a PR template scaffolding the protected-path attestation
convention, issue templates, `SECURITY.md`, `CONTRIBUTING.md`.

Direct test coverage for three modules confirmed to have real gaps (checked
against actual current coverage first, not just a missing same-named test
file — `tool_dispatch.py` was dropped from scope after confirming it's
already well covered by `test_orchestrator_dispatch_regression.py`):
`agent_prompts.py` (the prompt templates encode security-relevant
instructions — no chained shell commands, no `python -c` — that nothing
previously pinned), `tool_result_format.py` (zero direct tests previously;
covers every branch including two edge cases with no prior coverage:
malformed-JSON and wrong-shape-JSON stderr during a `BLOCKED` result),
`tool_schemas.py` (adds the specific missing check: every `required` field
name is a declared `properties` key — schema drift the existing
name-matching test can't see). `.mango/agents/nemotron-reasoner.md`'s
`tools:` frontmatter listed only `Bash, Read, Grep, Glob` though the body
has instructed using `knowledge_gap_log`/`hypothesis_register` since
`SDLC_HYGIENE_REPORT.md` flagged it open (2026-08-26); fixed, with a new
test asserting the parsed frontmatter field specifically (the existing
test only checked the whole file's text, which the prose mention alone
already satisfied — exactly why the gap went unnoticed).

`harness/api_server/main.py`'s dev-runner `host="127.0.0.1"` had no
override, unlike `port`/`reload` in the same block; now `API_SERVER_HOST`,
same pattern, same default. `harness/shared/governance/process_backend.py`'s
`DEFAULT_TIMEOUT_SEC=30` was an unlinked duplicate of
`orchestrator.tool_timeout_sec`; now reads from policy.

Resolved the version/title/diagram divergence between
`docs/architecture/c4_architecture.md` (2.2.4) and
`harness/docs/C4_ARCHITECTURE.md` (2.1.9) — the one doc the original
version-unification pass missed — with a banner naming the former
canonical, rather than discarding the latter's still-detailed content
(notably its Node-subsystem diagram). Recorded two tech-debt findings as
accepted debt (DEC-019, DEC-020) rather than leaving them ambiguous for the
next audit: the triplicated `digest()` helper across the three
control-plane scripts is intentional (root-of-trust isolation, not a dedup
opportunity), and `harness/shared/gates/` is adopted as the convention for
*new* gate-like modules going forward without migrating the 11 existing
`check_*.py`/`validate_*.py` files.

Also fixed a live regression of `R-CEG-1` (the version-string consistency
rule DEC-013 enforced once already): `pyproject.toml` still said `2.1.9`
while `README.md`/`NEXT_STEPS.md` had already moved to `2.2.4` as of the
LangGraph-engine release above — bumped to match.

### Added — second-round tech-debt audit: skill, dead-code removal, edge-case coverage (PR #53)

A second pass, triggered by the same broad SDLC/SQE-style review request
recurring three times verbatim in one session. New
`.mango/skills/tech-debt-audit/SKILL.md` codifies the recurring shape
(drift-vs-main check, god-file scan, adversarial hardcoded-value/dead-code/
edge-case sweep, doc sync) as a repeatable procedure instead of re-deriving
it by hand each time; composes the existing `validation-runner` and
`repo-invariant-review` skills rather than re-declaring their checks.

An independent, evidence-based scan (verify every claim via grep/read
before reporting, no speculation) found: `harness/shared/enforce_coverage.py`
was dead — confirmed via a repo-wide reference search (only its own test
file matched) — a functional duplicate of the live `coverage_gate.py` with
weaker semantics (lines only, no branches; no absent-vs-malformed
distinction); deleted, with its test file. Three real missed-edge-case
gaps closed with new tests: `command_actions.py`'s `write_targets()`
`WRITE_TARGET_PROGRAMS` branch (untested even for the exact `cp evil
.mango/hooks/x.sh` scenario its own docstring names as the reason it
exists); `check_dedup.py`'s `load_config()` `unreadable`-policy branch, its
wrongly-typed `max_shim_lines`/`exempt` fallback behavior, and `run()`'s
full-relative-path exemption form (previously only the bare-filename form
was tested). Two findings verified as already covered rather than acted on:
`write_policy.py`'s non-object-supplied-policy branch (already exercised,
under a different stated purpose, by the existing
`test_a_broken_policy_does_not_kill_the_process`); `coverage_gate.py` vs.
`governance_json.py`'s near-identical JSON-loading helper (already a
deliberate, documented exclusion — DEC-013).

Two findings evaluated and intentionally not fixed, recorded as DEC-022 so
a future audit does not rediscover them as undiscovered debt:
`verification.py`'s `timeout: int = 300` duplicates a policy value but the
module documents a stronger no-filesystem-reads-at-import contract that
sourcing it from policy would violate, and the one production caller
already injects the real value explicitly. `langgraph/decorators.py`'s
`@with_authority`/`@budgeted` are implemented and unit-tested in isolation
but never applied to any real node function — contradicting a checked-off
`NEXT_STEPS.md` claim, now corrected — and both fail open (moot only while
unwired); wiring them is deferred to its own spec, since doing it correctly
means fixing the fail-open behavior in the same change, not just adding
decorator syntax to live-shaped node code.

Also: re-verified the prior plan's "test-helper duplication" claim (5
files) directly rather than trusting it — only 2 (`test_check_dedup.py`,
`test_check_py_compat.py`) had genuinely identical logic; consolidated
those into `conftest.py`'s new `write_text_file()`, left the other 3 alone
since their helpers serve different subsystems with different shapes.
Corrected `docs/specs/god-file-decomposition.md`'s stale
`mango_mas_orchestrator.py` line count (465 → 483, now 96.6% of the
enforced 500-line ceiling) and flagged `docs/specs/orchestrator-tool-registry.md`
as worth prioritizing given the shrinking headroom. That flag was itself stale:
the spec's implementing commit (`6ae7eb0`) had already landed three days
earlier — its acceptance-criteria checkboxes were simply never ticked, which is
what made it look unstarted here. Corrected 2026-09-01 after re-verifying all
acceptance criteria directly against current source; see the spec's own status note.
Separately, R-ORCH-1..4 as written would not have reduced the orchestrator's
line count even if genuinely unstarted (they reorganize code within the file,
unlike `god-file-decomposition.md`'s pattern of moving it into new files) — the
size-budget headroom concern this entry raised remains open on its own terms.

### Added — dependency-audit gate, a runtime/dev dependency split, and CI-enforcement cleanup

Paired specs: `docs/specs/dependency-hygiene.md` and `docs/specs/ci-enforcement-gaps.md` (DEC-013).

Dependency vulnerability scanning now runs at root, closing the
`KNOWN_GAPS["audit"]` exception `test_ci_gate_coverage.py` had carried: a new
`make audit` (`pip-audit` against a new `requirements.txt`, delegated to the
Node stack's existing `osv-scanner` via `make -C harness/node audit`) and
`make audit-install`, enforced by a dedicated `audit` job in
`.github/workflows/python-package.yml` (mirroring how `secrets` runs outside
`ci` rather than duplicated across matrix legs) and now a `pre-pr`
prerequisite. `requirements.txt` splits the API server's runtime
dependencies (fastapi, uvicorn, pydantic, httpx) out of
`requirements-dev.txt`, which keeps installing both via a
`-r requirements.txt` include; `pyproject.toml` gains a mirrored
`[project.dependencies]`; `.github/dependabot.yml` covers the `pip` and
`npm` ecosystems. `governance/broker.py`'s and `check_dedup.py`'s
JSON-parsing consolidates into `harness/shared/governance_json.py`, a
non-raising classifier — each caller still raises its own existing
exception type and message.

Also: `harness/__init__.py` and `harness/api_server/__init__.py`, for the
two packages genuinely imported as `harness.x.y` (matching
`harness/shared/__init__.py`'s existing convention); a root `install`
target (`harness/shared/install_hooks.sh`) so a clone using only the root
Makefile still gets the pre-push hook; header comments on
`harness/node/.github/workflows/ci.yml` and
`harness/jvm/.github/workflows/ci.yml` identifying them as reference
templates GitHub never executes; the version string unified to `2.1.9`
across `README.md`, `docs/architecture/c4_architecture.md`, and
`NEXT_STEPS.md`. `harness/jvm/` is now explicitly labeled in `README.md`
and `harness/CONTRACT.md` as an unadopted reference template.

**Self-corrected mid-review:** an initial research pass reported 3 live
`ruff` findings and this batch briefly "fixed" them, which turned CI red
with the opposite verdict on the same two files. Root cause: this
development environment has a bare `ruff` on `PATH` resolving to a newer,
unpinned version, while `python -m ruff` — what `make lint` and CI's
`pip install -r requirements-dev.txt` both actually resolve to — is the
pinned `0.6.9`, and the two versions disagree on `E402` and `RUF100`/`BLE001`
for this exact code shape. `main` was already clean under the pinned
version; neither file is touched here. The same false signal briefly caused
`harness/__init__.py`/`harness/api_server/__init__.py` to be reverted before
being restored once re-verified with the correct binary. Lesson recorded in
`docs/specs/ci-enforcement-gaps.md`: always verify with `make <target>` or
`python -m ruff`/`python -m mypy`, never a bare invocation.

**Tried and reverted, unrelated to the above:** wiring `lint-node` into
`ci` — `make lint-node` currently crashes on a pre-existing
`typescript`/`typescript-eslint` version incompatibility in
`harness/node/package.json`, tracked as a follow-up in
`docs/specs/ci-enforcement-gaps.md`'s Open questions.

### Fixed — `make secrets` scanned every branch in the clone, not just the current one

Discovered when this PR's own `secret-scan` job failed CI despite a clean
local `make secrets`: all three `secrets` targets (root, `harness/node`,
`harness/jvm`) ran `gitleaks git` with no `--log-opts`, scanning every ref
in the local clone rather than the checked-out branch's own history. A
real leaked key on an unrelated, concurrently pushed branch
(`feature/governed-run-console`, untouched by this PR) was failing CI for
a reason no PR author could act on. Fixed with `--log-opts="HEAD"` on all
three targets, confirmed with a from-scratch clone (141 commits scanned,
clean, vs. 144 and one leak without the fix). DEC-014.

Spec: `docs/specs/dependency-hygiene.md`, `docs/specs/ci-enforcement-gaps.md`.

### Refactored — the last open god-file requirement (`R-GFD-4`)

`docs/specs/god-file-decomposition.md` shipped across PRs #28-#32 with seven of
its eight requirements closed; `R-GFD-4` — extracting the pure AST-inspection
helpers out of `check_py_compat.py` — was the one left open. `find_pep604`,
`find_datetime_utc`, `has_future_annotations`, `find_pep604_assignments`, and
their private helpers now live in `harness/shared/ast_visitors.py` (120 lines,
zero internal imports beyond stdlib `ast`), and `check_py_compat.py` drops
from 338 to 283 lines, keeping only workflow-matrix resolution, policy-driven
skip-dir loading, the file-scanning loop, and the CLI.

Every extracted symbol is re-exported from `check_py_compat.py`
(`from harness.shared.ast_visitors import X as X`), so the existing 37 tests
in `test_check_py_compat.py` — which reach these functions through the `cc`
module alias — needed no changes. `test_ast_visitors.py` (16 tests) adds
direct unit coverage of the extracted module, independent of the gate that
consumes it. `test_import_purity.py`, `test_import_direction.py`, and
`check_dedup.py` all pass unchanged against the new module. All eight
`R-GFD-*` requirements are now closed; see `docs/specs/god-file-decomposition.md`
and `docs/architecture/god-file-refactoring-guide.md` §2.3 for the updated
acceptance criteria and decomposition map.

### Added — `read_file` and `apply_patch`, and the read policy that had to come first

The reasoner could already read and write code, but only bluntly: every read spawned a
subprocess to `cat` a file, and every edit went through `write_file`, which overwrites
whole files — so changing three lines meant regenerating the file from the model's
context. `read_file` and `apply_patch` close both gaps.

The interesting part is what nearly shipped with them. `command_actions.classify` grades
`cat .env` as `secret_access`, an action **no role in `agent-policy.json` holds**, so
reading a credential through `run_command` is denied for every agent. That grading is a
property of the *command*. `read_file` resolves a path and reads it directly, so nothing
in `command_actions` sees it — and mapped to the `read` action the implementer already
holds, `read_file(".env")` would have been *permitted*, returning `NVIDIA_API_KEY` into
`conversation_history`, which is sent to the model API on the next turn and written to
the debug dump.

There was a `write_policy.py` and no read-side counterpart, because until now there was
only one file-reading door and `command_actions` was standing in it. `read_policy.py` is
the second door's policy and owns the credential pattern both doors now match —
`command_actions` composes its command-scanning form from the same alternation rather
than restating it, so the two cannot drift. The regression test asserts that as a
*property* over a corpus, not a list of filenames: anything `cat <path>` is denied for,
`read_file` is denied for. It additionally refuses anything under `.git/`, which `cat`
does not, because a remote URL there carries a push token.

Two smaller defects were found and fixed while building it:

- **`apply_patch` would have rewritten every line ending in a CRLF file.**
  `Path.read_text` translates newlines on the way in and `write_text` does not restore
  them, so `b'alpha\r\nbeta\r\ngamma\r\n'` came back as `b'alpha\nBETA\ngamma\n'` — a
  one-word patch becoming a whole-file diff. Both sides now use explicit
  `open(..., newline="")`; the `newline=` keyword on `Path.read_text` is 3.13+ and this
  repository's floor is 3.9.
- **`.env.example` pointed "Nemotron" traffic at a different vendor's model.** It shipped
  `NEMOTRON_DEFAULT_MODEL=google/diffusiongemma-26b-a4b-it` while the README documented
  `nvidia/llama-3.3-nemotron-super-49b-v1`, and `nemotron_bridge` has no fallback. The
  value appeared nowhere else in the repository — an unreviewed placeholder in the
  scaffold every adopter copies. `test_documentation_truth.py` now pins the two together.

`agent-policy.json` is unchanged: `apply_patch` grades as the same `write` action as
`write_file`, so the verifier — which holds no `write` — receives `read_file` and not
`apply_patch`. The role that judges the work still cannot edit it (R-AC-8), under the new
tool's name as well as the old one.

Spec: `docs/specs/agent-read-patch-tools.md`.

### Fixed — two credential-protection gaps found reviewing the tool above, before either shipped

An adversarial pass over `read_file`/`apply_patch` before merge, not a bug reported after
the fact.

**Case-sensitive credential matching.** `CREDENTIAL_FILENAME_ALTERNATION` had no
`re.IGNORECASE`, so `.ENV`, `ID_RSA` and `SECRETS.PEM` passed both doors ungoverned —
`read_denial_reason` and `command_actions.classify` alike. Neither filesystem case rules
nor an agent's own naming choice are something either door can assume; both patterns now
compile with `re.IGNORECASE`. No tracked file collides with the widened match (checked
against `git ls-files`).

**`JSON null` crashed a tool handler outside its own error handling.** `args.get(key, "")`
only substitutes the default for a *missing* key; a model sending `{"old_text": null}` — a
present key with nothing to put in it — gets `None` back unchanged, and `None` then hit
`workspace / filepath` or `content.count(old_text)` as a bare `TypeError` outside any
handler's `try/except`. The orchestrator's dispatcher already contains that as a generic
exception (the loop never crashed), but the message the model saw was a raw Python
exception instead of the handler's own scoped `Error reading/writing/patching file ...` —
and the "every handler returns a string, never raises" contract `tool_executors.py`
documents was silently false for this input. `args.get(key) or ""` at the one place these
values are extracted normalises "missing" and "null" to the same empty string every
handler already treats as "nothing supplied"; `confidence` and `start_line`/`end_line` are
deliberately excluded; `0.0` and `None` are both meaningful values there. Fixed for all six
tool handlers in `_tool_handlers`, not only the two new ones — found by testing `read_file`
and `apply_patch`, but the vulnerable `.get(key, "")` idiom was shared by every handler in
the dict.

### Fixed — the invariant liveness gate could not see 13 of the 17 invariants

`test_invariant_liveness.py` computed one set difference,
`set(INVARIANT_MECHANISMS) - _declared_invariants()` — dict minus contract. **The
reverse was never computed.** The dict held 4 entries (INV-8/9/16/17) against 17
declared invariants, so the other 13 sat in no dict and were never examined; the only
completeness guard was `assert len(_declared_invariants()) >= 16`, which an
unclassified addition passes.

That hole is why **INV-11, INV-12 and INV-14 were published as unqualified MUSTs over
capability that does not exist** — no `critique.py`, no `repair_loop.py`, and no
occurrence of `repair` or `critique` in the orchestrator — three lines from INV-13,
which is scrupulously honest about exactly this and names *this module* as the gate
that should have caught it.

Every declared invariant is now classified in one of four dicts, each with a reason:
`INVARIANT_MECHANISMS` (importable symbol with a live caller), `ENFORCED_ELSEWHERE` (a
named gate covering every clause — INV-1/4/6/15), `PARTIALLY_ENFORCED` (what is covered
*and* what is not — INV-2/3/5/7/10) and `DORMANT_INVARIANTS` (nothing enforces it —
INV-11/12/13/14). `test_every_declared_invariant_is_classified` fails closed on an
unclassified addition, mirroring `test_ci_gate_coverage.py`'s `KNOWN_GAPS` /
`PARTIAL_COVERAGE` idiom.

**Invariants are not atomic**, which the first draft of this change got wrong. Several
have clauses with different enforcement status, so a single verdict per invariant is
itself an overclaim: INV-7's delegation half is enforced by `validate_agent_policy.py`
while its evidence half is not (the repo's own `DECLARED_NOT_YET_ENFORCED` already
recorded that nothing cross-checks `evidence_required_for`); INV-2 and INV-3 name the
JVM stack, which no root target runs because the root `Makefile` declares no `JVM_DIR`;
INV-5's own gate declares `audit` a known gap and `specs` partial; INV-10's DENY
*production* is tested but its *terminality* is not, for want of a repair loop able to
violate it. `CONTRACT.md` now carries those qualifiers, so the published text and the
classification cannot disagree — enforced by the existing marker test, whose accepted
phrases are now a declared constant so INV-13's "Not currently satisfiable" keeps its
DEC-010 explanation instead of being reworded to match a literal.

Also: `synthesis.critique_schema_version` and `synthesis.max_repair_cycles` join
`DECLARED_NOT_YET_ENFORCED` as *pinned but unconsumed* — a different state from their
unpinned siblings. `DEC-NS-002`, which proposes `"1.0"`, is still BLOCKING in a DRAFT
openspec document, so the pin records a proposal, not a decision. `decision_id_pattern`
is documented as governing decision-log IDs only: both readers rewrite it into
`\b(...)\b` and use it as a scanner over the log, never as a validator, so
area-scoped `DEC-NS-002`-style identifiers in `openspec/changes/**` are proposal-local
and read by no gate. The neurosym spec's Problem Statement claimed the orchestrator
"runs unbounded multi-agent loops without policy verdicts… violating INV-9, INV-11, and
INV-12"; two-thirds was false since DEC-011 wired `ExecutionBroker` and bounded the loop
with `max_iterations` + `ToolBudget`, and nothing caught the drift because `openspec/`
is outside every CI gate.

**5/5 mutants killed** — one of which found a real defect in the new tests: the
partial-reason check tested `"COVERED:" in reason`, which `"NOT COVERED:"` satisfies as
a substring, so a reason stating only the uncovered half would have passed. The check is
now anchored to the start of the string.

### Added — the plan gate: `make specs` now checks that a plan's criteria could fail

`make review`'s checklist named `openspec-peer-review` as the plan-review step: four
job-title personas, no output schema, no severity vocabulary, and a termination rule
that cannot fail ("Only proceed once all personas sign off"). The mechanical half was
thinner — `validate_specs`' falsifiability check was a three-phrase blocklist
(`works correctly`, `as expected`, `appropriately`) which, measured across all fifteen
plans in the repository (104 acceptance criteria, 139 requirement IDs), **fires zero
times.**

`plan_rules.py` replaces it with four rules decided from the document alone, run by
`validate_plan.py` as a third tier of `make specs` and scoped to plans git reports as
modified: `UNFALSIFIABLE_ACCEPTANCE` (a criterion naming no observable),
`STAGE_REACHABILITY` (one naming a check but assigning it to a human),
`MISSING_FAILURE_PATH` (criteria describing only success) and `ORPHAN_REQUIREMENT` (a
declared ID no criterion cites). On the same corpus they report 10 findings.

**Every rule was calibrated against that corpus before shipping, and three were wrong
on first contact with it.** The observable grammar recognised `make` targets and pytest
selectors but not `ruff check .`, `git grep` or `python -m pytest` — 13 of its 20
findings were that gap (65% false positives), fixed by treating a backticked span as the
marker rather than a curated executable list, which would also have been a hard-coded
value. The non-success vocabulary had `failure` but not `fails`, so
"`test_lint_config_liveness.py` fails when a dead pattern is present" read as
success-only — 4 of 7 findings (57%). And requiring every `R-*` to be cited by a
criterion scored nine of eleven specs at 100% orphaned, because `SPEC_TEMPLATE.md` never
asked for the citation; that rule is now scoped to plans carrying the sections this
change adds. Uncalibrated, the gate's first run would have produced ~127 findings on a
corpus holding perhaps 8 real defects.

Three defects in the migrated structural rules are fixed in the move. Two were recorded
in `NEXT_STEPS.md`: an unfilled `make spec` scaffold satisfied every rule (its
placeholder IDs match the ID patterns), and an `AC-*` bullet containing MUST could never
satisfy the `[CR]-` pattern — unsatisfiable for exactly the bullets the template tells
authors to write. The third was found by running the gate against this change's own
spec: the blocklist matched phrases inside code spans, so it failed any document that
names the phrases it bans. Both phrase-matching rules now strip code spans first, since
a backticked phrase is being named rather than used.

The rules also stopped being defined twice. `validate_specs.sh` carried them as an
inline heredoc and `validate_specs.py` carried them again, and the two had already
drifted — the shell copy discovered specs recursively and skipped no template; the
Python one did neither. One definition, two callers.

INV-17 is added to `harness/CONTRACT.md` with its `test_invariant_liveness` mechanism
entry in the same change, so it is never a published MUST with nothing behind it.
**5/5 mutants killed**: dropping the human-deferral override, un-stripping code spans,
removing the orphan rule's scoping, widening the modified-file scope to every plan, and
turning an unparseable plan into a silent skip.

### Added — Multi-Agent Orchestrator & Governance Kernel God-File Decomposition

- **God-File Refactoring (`R-GFD-1` .. `R-GFD-8`)**: Decomposed large orchestration and governance modules into highly focused single-responsibility units:
  - Extracted isolated executors into [`harness/shared/tool_executors.py`](harness/shared/tool_executors.py) (`execute_write_file`, `execute_run_command`).
  - Extracted tool argument normalization into [`harness/shared/tool_dispatch.py`](harness/shared/tool_dispatch.py) (`_normalize_tool_arguments`).
  - Extracted persona prompt templates and guardrails into [`harness/shared/agent_prompts.py`](harness/shared/agent_prompts.py).
  - Decoupled process execution backend and byte-capping into [`harness/shared/governance/process_backend.py`](harness/shared/governance/process_backend.py) (`ProcessBackend`, `_cap`).
  - Fortified `ExecutionResult` immutability via `@dataclass(frozen=True)` and non-mutating `dataclasses.replace` in [`harness/shared/governance/broker.py`](harness/shared/governance/broker.py).
  - Split monolithic orchestrator tests into four modular test modules (`test_orchestrator_init.py`, `test_orchestrator_tools.py`, `test_orchestrator_hooks.py`, `test_orchestrator_agent_loop.py`).
- **Comprehensive C4 Architecture**: Added full Level 1-4 architectural diagrams and threat boundary models in [`docs/architecture/c4_architecture.md`](docs/architecture/c4_architecture.md).
- **PEP 585 / UP035 Type Modernization**: Standardized on modern typing across all modules (`collections.abc.Callable`, `collections.abc.Mapping`, `typing.Any`, `typing.Final`) and PEP 484 explicit re-export syntax.
- **Cross-Platform Hook & Live E2E Hardening**:
  - Implemented relative POSIX path resolution for `.mango/hooks/*.sh` invocations under Windows MSYS2/Git Bash to avoid backslash escaping issues.
  - Enhanced live E2E test suites (`test_mango_mas_live.py`, `test_orchestrator_agent_loop.py`) to resolve credentials dynamically from `.env` and environment via `nemotron_bridge.resolve_api_key()`.
  - Hardened `_reject_unsafe_relpath` in [`harness/control-plane/publish_policy_artifact.py`](harness/control-plane/publish_policy_artifact.py) to prevent Windows drive letter paths on POSIX hosts.
  - Isolated regression fixtures from `GITHUB_BASE_REF` environment variables to ensure deterministic cross-platform runs.
- **Strict Code Quality & Logging Normalization**:
  - Hoisted all function-scoped `import logging` calls to module-level imports, maintaining 100% clean Ruff checks and Mypy strict validation across all 125 source files.
  - Verified 97.92% total line coverage, 94.88% branch coverage, and 100% per-file compliance across all 50 monitored harness modules.

### Added — every verdict is now logged, not just derived

`status`/`termination_reason` were computable but never observed: nothing in
`harness/` logged or aggregated them, so the question the merged verdict-propagation
spec deferred — whether the observed `FAILED` rate justifies a repair loop — had no
data to answer it with. `_emit()` is the one choke point all three `Verdict`
constructors share (`derive_verdict`'s internal `_v()`, `not_configured()`,
`reentrant()`); wrapping their returns logs `status`/`termination_reason`/
`command`/`exit_code` as message-string fields, since `JSONFormatter.format()`
reads four fixed record attributes and drops `extra=` kwargs. Nothing in `Verdict`
needs redaction: `.reason` never carries captured stdout/stderr, traced through
every branch of `derive_verdict`. Reaches disk today with nothing else built —
`main.py` already configures a root JSON logger and `execute_loop` runs in the same
request thread. **2/2 mutants killed** (dropped logging call; broken pass-through).

A companion change in this same line of work — moving the four prompt-template
constants out of `mango_mas_orchestrator.py` — was developed independently and in
parallel with the God-File Decomposition above, which already extracted the same
four constants (plus the hook-related ones) into `agent_prompts.py`. Superseded on
merge rather than duplicated: no `prompt_templates.py` was added.

### Added — the verifier's verdict is now a value the harness earned, not prose nobody read

`execute_sequential_thinking_loop` ran planner → reasoner → verifier once each and
returned the verifier's raw string. Nothing parsed it. The API wrapped it in a
hardcoded `status="success"`, so a FAIL and a PASS were byte-identical to every
consumer, and every test mocked the loop to return `"PASS"` — so no test had ever
driven a failure through the pipeline. This is the shape
`test_invariant_liveness.py` exists to catch, sitting in the product path while
four milestones removed it from the gates.

**Deriving the verdict from the agent's own commands would not have fixed it.**
The model chooses what to run: a verifier executing `true` produces a
SUCCESS/exit-0 broker result and would have earned VERIFIED. That is model
authorship at one remove, and worse than prose, because the result carries
mechanical authority. So the harness runs a check of its own —
`make -f Makefile test-python`, through the same `ExecutionBroker`, under the
verifier's canonical identity — and `derive_verdict` accepts only a `HarnessCheck`,
which `verification.run` alone constructs. Passing it an `ExecutionResult` raises.
Provenance is a property of the type, not of the call site.

`-f Makefile` is load-bearing, not tidiness. GNU Make searches `GNUmakefile`, then
`makefile`, then `Makefile`. Only the last is a protected path, so an agent holding
`write` defeats the check in one tool call by adding a `GNUmakefile` whose target is
a no-op. Naming the file removes the search.

The probe runs `make -n` plus a `command -v` census rather than testing that a
Makefile exists: a workspace whose Makefile lacks the target exits 2 with **no**
broker reason, which is indistinguishable from a failing suite, and would have been
reported as a failure of the change. `-n` is also why the probe cannot invoke what
it probes — the configured target runs the suite containing this module.

Three reported states, and nothing is promoted between them. **BLOCKED** means no
verdict was obtained (not configured, re-entrant, probe failed, harness fault,
broker denial); **FAILED** means the check ran and failed; **VERIFIED** means it ran
and passed. An earlier draft promoted the unobtainable cases to FAILED on a
misreading of INV-12, whose scope is what a repair loop produces at budget
exhaustion — reporting "we could not check" as "it failed" in a change about honest
verdicts.

`execute_loop` is a new public method returning the typed outcome;
`execute_sequential_thinking_loop` is now a one-line adapter returning the same
string it always did, so R-ORCH-4's five members stay byte-compatible. This
supersedes `orchestrator-tool-registry.md:98-99` (new methods are
underscore-private; public methods keep identical semantics) for this method only,
per `docs/specs/verdict-propagation.md`. Four in-repository test stubs are updated
because they patch the orchestrator class — a `MagicMock` in a `str` field raises
under Pydantic v2 and the endpoint's blanket `except` turns it into a 500.

**`status` is unchanged and still means only "the orchestration did not raise."**
A client reading that field alone still learns nothing, which is why the verdict has
its own fields, why they name the command and exit code, and why `app.js` renders
them: the configured target is one gate, not the repository's full matrix, and a
bare verdict word would read as "CI green".

**19/19 mutants killed** — among them: `derive_verdict` accepting an
`ExecutionResult`; `probe_ok` ignored; a harness fault graded as a failure; either
half of the status/exit-code pair deleted; `-f Makefile` dropped; the probe
succeeding unconditionally, ignoring its result, or probing the file instead of the
target; the census skipped; the sentinel never set or never restored; and the loop
deriving its verdict from the model's prose. Each was applied to the tree and
confirmed to fail the suite. `verdict.py` 100%, `verification.py` 98%.

**Stated rather than implied: this is tamper-evident, not tamper-proof.** A reasoner
holding `write` in the same workspace can defeat any check run inside it —
`conftest.py` is airtight (`pytest_sessionfinish` assigning `session.exitstatus = 0`
forces exit 0), and `pytest.ini`, `tox.ini`, `setup.cfg`, `vitest.config.ts` and
`package.json` are all writable, as is any file `mv` can be pointed at, since `mv`
does not classify its source operand. `docs/specs/verdict-propagation.md` carries
the full list. VERIFIED means "the configured check exited 0" and nothing more.

### Fixed — the tool-call budget was per turn while its name and message said per task

`agent_defaults.max_tool_calls_per_task` is 100, and the refusal it raises says "per
task". It was enforced by a counter initialised inside `execute_agent`, so the three
turns of one orchestration could spend 300. The policy value and the enforced value
agreed on the number and disagreed on the unit — the drift `test_policy_consistency`
exists to catch, one layer down.

`ToolBudget` is a value the caller owns and threads through the turns it wants
accounted together; `execute_agent(..., budget=None)` creates a fresh one per call,
which is byte-for-byte what every existing caller had. Deliberately not an
accumulator on `self`: that needs a reset, a reset needs a correct call site, and a
missing reset is invisible to every test in this repository, all of which build a
fresh orchestrator. **7/7 mutants killed.**

### Changed — `_format_execution_result` moved to `tool_result_format.py`

Extracted so the rendering has one home and the orchestrator stays inside the
500-line budget — the same split, for the same two reasons, as `tool_schemas`.
Nothing outside the orchestrator referenced the private original. It takes a
`typing.Protocol` rather than importing `ExecutionResult`, so it stays at the bottom
of the import graph; `test_import_direction.py` now measures that graph (41 modules,
zero cycles) and pins that `verdict.py` imports nothing first-party.

### Security — the containment layer held against the shapes its own tests named, and little else

An adversarial review of this branch, driven through the real broker in a
temporary workspace, found four ways past the gates it added. Every one is
reproduced by a test that fails against the code as shipped.

#### `1>` and `2>` were not redirects

`_REDIRECT` was `(?<![0-9<>&])(?:>>|>)(?!&)`. The `0-9` was added so `2>&1`
would not read as a redirect — but `(?!&)` already did that, so the digit
exclusion bought nothing and made **every fd-numbered redirect invisible**.
`echo PWNED 1>.git/hooks/pre-commit` classified as `read`, produced no write
targets, and installed a host-executed hook. Since the action never became
`write`, it also let the **verifier** — which holds no `write` action at all —
write files, and the full escalation the spec's problem statement describes was
open end to end: write `post-verifier-run.sh` via `1>`, and the orchestrator
runs it on the host at the end of that same turn.

Now `(?<!>)>(?!&[0-9-])`: every `>` counts, including `1>`, `2>`, `&>`, `>|` and
`<>`; only descriptor duplication and closing are excluded. The control that
motivated the over-broad original — `2>&1` and `>&2` must not be graded writes,
or ordinary commands are denied — is kept and pinned.

#### A trailing redirect downgraded every dangerous command

The redirect branch ran before the program and shape tables **and returned from
it**, so the redirect *was* the classification. Appending ` > out.txt` regraded
anything to `write`, the one action the implementer holds:

| command | was | now |
|---|---|---|
| `rm -rf victim > log.txt` | `write` | `destructive` |
| `curl --version > out.txt` | `write` | `external_write` |
| `env > env.txt` | `write` | `secret_access` |
| `sudo -n true > log.txt` | `write` | `permission_change` |

Seven characters routed around `human_approval_required_for`,
`external_network_default` and every entry in `high_risk_actions`. Classification
now grades the command first and takes the **strictest** of that and the write,
against an explicit severity order in which an action the table does not name
sorts highest — so adding one can never make it downgradable.

A command exercises a *set* of actions, and the strictest is not always the
write: `pytest -q > x.txt` grades `test_execute`, and a role holding
`test_execute` without `write` would still write through the redirect. The
broker now requires `write` separately whenever a command has write targets.

#### Tool authority was enforced by omission from a prompt

`tools_for_role` filters the schema the model is *told* about.
`_dispatch_tool_calls` looked handlers up by name with no reference to that
filtered list — and `write_file` is in `conversation_history` from the reasoner's
turn immediately before the verifier's. A verifier that named the tool anyway got
it. The pre-existing test asserts on `chat.call_args.kwargs["tools"]`, which is
exactly the advisory half, so it stayed green against this.

`agent_authority.tool_is_permitted` now answers the same question at dispatch,
where it decides what runs rather than what is advertised.

#### Brokered commands inherited the full credential environment

`_run_hook` filtered the environment; `ProcessBackend._spawn` did not — and
`_spawn` is the path the model controls. `env` and `printenv` are graded
`secret_access` and denied, but the action model cannot enumerate every
spelling: `cat /proc/self/environ` is `cat`, which grades `read`, an action every
role holds, and returned `NVIDIA_API_KEY`, `API_SERVER_KEY` and
`AGENT_EVIDENCE_KEY` into the model's context. The last is the HMAC key evidence
manifests are signed with, so that was forgery, not only disclosure.

**14/14 mutants killed** across the four fixes, each with a control that a
gate denying everything would fail.

### Fixed — `classify` was quadratic in a model-supplied string

Two `_BY_SHAPE` patterns bridged with `.*` after a repeatable literal, so the
engine retried the tail from every match position. Measured: 0.28 s at 14 KB,
1.07 s at 28 KB, 4.29 s at 56 KB, **17.1 s at 112 KB** — a clean 4× per
doubling. The broker's timeout bounds the subprocess and `classify` runs before
it, so nothing covered this: one oversized `run_command` stalled the
orchestrator and, through `run_in_threadpool`, an API worker.

Both patterns now bridge with a bounded flag run instead of `.*`, and the input
is capped at `orchestrator.max_command_bytes` (new policy key, not a literal).
Same input: 0.0003 s. The cap alone would have left the quadratic patterns live
just beneath it, so both are fixed rather than one.

`debug_dump`'s credential patterns were measured too and are **linear** — worst
case 69 ms at 256 KB. No change needed there.

### Fixed — `ProcessBackend.available()` returned True unconditionally

That is not a probe. It is the `sandbox_available: bool = True` fail-open moved
one method down: same unconditional yes, same unreachable INV-9 branch. And
`test_default_probes_the_backend_rather_than_assuming` passed identically
against both, so the test's *name* was the only thing separating the defect from
the fix.

`available()` now runs the shell. `shutil.which` would answer "a file with that
name is on PATH", which a shell that is present but not executable also
satisfies — and that fails at the first real command instead, with the caller
already past the INV-9 branch. Cached, because `verify_sandbox` is consulted per
tool call and the answer cannot change within a run. **4/4 mutants killed**,
including the original `return True`.

### Changed — the tool schema moved to `tool_schemas.py`

`NEMOTRON_TOOLS` now lives in `harness/shared/tool_schemas.py` and is re-exported
from the orchestrator unchanged; every caller reaches it as
`orch_module.NEMOTRON_TOOLS` and none is affected. This keeps the orchestrator
inside the 500-line budget, which the containment checks had pushed it past.

`test_meta_tools_are_actually_wired_into_the_orchestrator` asserted by searching
the orchestrator's *source text* for `META_TOOLS_SCHEMA`, `knowledge_gap_log` and
`hypothesis_register` — which its own docstring would satisfy, and which a
comment saying the tools are not wired would satisfy equally. It now asserts
against the composed schema and the live dispatch registry.

### Fixed — `.dockerignore` shipped a dead rule and the image shipped test fixtures

`.agents/` was excluded long after the directory was consolidated into
`.mango/skills/` (R-HYG-4). `TestGitignoreHasNoDeadRules` did not catch it: it
reads `.gitignore` only, and its predicate is *the parent exists*, which
`.agents/` satisfies because its parent is the repository root.
`TestDockerignoreHasNoDeadRules` checks the rule's own path. **3/3 mutants
killed.**

`COPY harness/ /app/harness/` also put `harness/shared/tests/` — which holds a
`ghp_...`, an `AKIA...` and `nvapi-...` literals — into the published image.
Those are allowlisted for the *scan*; the allowlist says nothing about what
ships. The Python and JVM suites are excluded from the build context;
`harness/node/tests/` is removed in the runtime stage instead, because
`tsconfig.json` includes `tests/**/*.ts` and dropping it from the context would
not fail the build — it would quietly typecheck less.

### Hardened — `_run_hook` executed any script whose name it was handed

`_run_hook(name)` spawned `<hooks_dir>/<name>.sh` on the host whenever the file
existed, and `execute_agent` builds that name by interpolating its `agent_name`
argument: `f"post-{agent_name}-run"`. `hooks_dir` is inside the workspace, and
in the deployed configuration the workspace *is* the repository, so the pair is
a host-execution primitive keyed on a caller-supplied string.

**Stated precisely, because the distinction matters:** this was not reachable by
the agent. `agent_name` comes from `execute_sequential_thinking_loop`, which
passes the three fixed roles; the model never chooses it. The write policy
already refuses to create a file under `.mango/hooks/**`. This is
defence-in-depth on a primitive whose safety otherwise rested on an argument
being trustworthy — true today, and nothing enforced it.

`_run_hook` now refuses any name outside `PERMITTED_HOOK_NAMES`, checked before
the path is built so the verdict does not depend on whether the file exists.
The set is *derived* — `{PRE_RUN_HOOK} | {f"post-{role}-run" for role in
ACTIVE_TO_CANONICAL}` — so a role added to the authority model gets its hook
without a second edit, and a hand-maintained list cannot go stale into a
permission. Refusal raises rather than returning: a name the orchestrator never
constructs indicates a bug or an injection, and skipping quietly would make it
look like a hook that simply is not installed.

`test_the_allowlist_covers_every_name_the_orchestrator_constructs` parses the
`_run_hook` call sites out of the module and checks the set covers them, so a
new call site the allowlist omits fails here rather than at runtime on whichever
role happens to run last. **5/5 mutants killed**, including an empty allowlist —
which every other assertion in the class would have passed.

The orchestrator tests drove `execute_agent` with a fictional `test-agent`
role. That is no longer a neutral placeholder: the authority model does not
declare it, so `post-test-agent-run` is a name the orchestrator could not have
constructed. Those tests and the regression-tier fixture now use the active
roles, as `test_mango_mas_tools.py` already did.

Raised by review on `mango_mas_orchestrator.py:203`. The companion comment on
`:214` — `set(credential_env_names())` rebuilt once per environment variable
inside the filter comprehension — was already hoisted.

### Fixed — the command guard could hang instead of returning a verdict

`check_command` delegates push-destination decisions to `remotes.py` in a
subprocess, and that call carried no timeout. A guard that hangs produces the one
outcome a fail-closed gate cannot: no verdict at all. The tool call waits on a
subprocess that waits on a network read, and neither the broker's timeout nor
INV-8 has anything to act on.

Threading the broker's own budget through (`check_command(command,
timeout=timeout)`) fixed the broker path and left the other one open.
`main()` — the PreToolUse entry point Claude Code actually executes as a hook —
has no tool budget to hand down, so it kept calling `check_command(str(cmd))`
and the signature default `timeout: int | None = None` passed `None` straight
into `subprocess.run`. A default that reads as "bounded" and is not is the same
shape as the `sandbox_available: bool = True` fail-open removed one commit
earlier.

The default is now resolved from `orchestrator.tool_timeout_sec` in
`governance-policy.json` rather than fixed in the signature, so the hook and the
broker share one policy-declared bound and neither restates it. Read with
`json.loads` rather than through `policy_loader`: Claude Code executes this
module directly, so it takes no harness imports — the same standalone-stdlib
contract `check_projections` and `verify_zero_skips` carry, and the reason they
duplicate the absent-policy rule rather than importing it.

Resolution is inside `check_command`, not at import time, so the value cannot be
pinned to whatever the policy said when the hook module first loaded. An absent
policy is the adopter path; a policy that is *present but unreadable* raises, and
`check_command` converts that raise into a block — an exception escaping a
PreToolUse hook is a crash, which Claude Code reads as a broken hook rather than
as a denial. Absence is separated from inaccessibility by errno, not by a `Path`
predicate, for the reason recorded below: `stat()` answers `NotADirectoryError`
for a policy behind a file-where-a-directory-belongs and `ELOOP` for a symlink
loop, and reading either as "no policy here" silently restores the default.

**8/8 mutants killed** — restoring the unbounded default, dropping the
`TimeoutExpired` catch, falling back on an unusable policy, dropping the
positivity guard, dropping the `bool`-is-an-`int` guard (a policy of `true`
otherwise reads as a one-second budget), letting the `ValueError` escape as a
crash, and either of the two ways to collapse inaccessible into absent.

### Agent containment — INV-8 becomes true on the live path

`run_command` routes through `ExecutionBroker`. Generated code now executes
through the approved broker, which derives the action from the command, obtains
a policy verdict, runs the command guard, and pins the working directory, the
timeout and the captured output size. Nothing falls back to host execution when
the backend is unavailable (INV-9), and a denial is terminal (INV-10).

#### Added

- `test_invariant_liveness.py`, generalising the insight behind
  `test_protected_path_liveness.py` — *a pattern that matches nothing protects
  nothing, silently* — one layer up, to invariants whose enforcement mechanism
  has no caller. It asserts on **resolved imports parsed from the AST**, not on
  text: a symbol appearing in a comment is not a caller. **3/3 mutants killed** —
  removing the orchestrator's broker import fails INV-8, INV-9 and the positive
  control with the intended message.

  It ships with an **empty** waiver dict. Landing it earlier alongside a waiver
  for INV-8 was considered and rejected: a self-destructing waiver introduced in
  the same commit as its own fix can never fire, and a gate whose first act is to
  waive the invariant it exists to catch is the defect wearing a test file.
- `agent_authority.execution_identity` — the canonical contract each active role
  executes as. The active roles are not declared in `agent-policy.json`, and
  adding them would be the agent's own governing policy gaining an execution
  grant. The narrowest contract that covers the role's work is used instead, and
  `test_execution_identity_is_no_wider_than_the_role` pins that it never exceeds
  the role's derived authority.
- `_format_execution_result`, a pure function, so the three output shapes stay
  testable without spawning a process.

#### Changed — accepted consequences

- **An active role the mapping does not declare cannot execute at all.** It is
  denied as an unknown identity rather than defaulting to a permissive one.
- **`pip install` and other external or destructive commands are denied for the
  reasoner.** The reasoner prompt instructed running `pip`; it now names the
  repository's own gates and directs the agent to `knowledge_gap_log` instead of
  retrying a command policy will keep refusing.
- Two classifier defects found by the existing suite rather than by inspection:
  `>&2` and `2>&1` were read as command chains, denying ordinary commands; and
  `sleep`, `sort`, `cut` and similar were unmodelled and therefore denied.
- `test_generic_exception` monkeypatched `orch_module.subprocess.run`. With
  execution behind the broker that patch is inert — it would have passed while
  asserting nothing. Replaced with an injected backend that cannot start.

### Agent containment — the execution broker becomes real

Third in the containment sequence. `ExecutionBroker` is the approved execution
path INV-8 names; it had no production caller and `execute_command` ended at
`FAILED: Execution engine not fully implemented`, so INV-8 was declared and
unreached.

#### Fixed — three fail-open shapes in the broker

- **`sandbox_available: bool = True`.** A caller that never probed was told the
  sandbox was healthy, so INV-9's no-fallback branch was unreachable from the
  constructor most callers would write. The default is now *probe*; an explicit
  bool is still honoured, which is what lets a test drive the unavailable path.
- **`if _PDP_PATH.exists() and _POLICY_PATH.exists():`** skipped the policy
  verdict entirely when either file was missing, rather than denying.
- **The decision point ran as a host subprocess, before the command guard, from
  a path inside the agent's workspace.** Replacing that file replaced every
  subsequent verdict. It is evaluated in process now.
  `tool_broker_reference.py` remains as the contract an external broker mirrors,
  and `test_policy_decision.py` pins that the two agree on every representative
  request.

#### Added

- `governance/command_actions.py` — derives the action a command exercises from
  the command. The action was previously whatever the caller passed, and a
  constant grades `pytest` and `rm -rf /` identically, so
  `human_approval_required_for` was never reached. Classification is an
  allowlist; anything unmodelled resolves to an action **no role holds**, pinned
  by `test_unclassified_action_is_held_by_no_role`. Chained and substituted
  commands are unclassified rather than graded by their first word, and reading
  a credential-bearing file is `secret_access` rather than `read`.
- `governance/policy_decision.py` — the verdict, in process, mirroring the
  reference implementation's three denials in order.
- A process backend that pins the working directory, bounds runtime and caps
  captured output. `execute_command` gains `cwd` and `timeout`: the
  orchestrator's contract is a pinned directory and a policy-declared
  `tool_timeout_sec`, and a broker that dropped them would discard a governed
  budget silently.

#### Scope, stated plainly

The backend **contains**; it does not **isolate**. It confines neither the
filesystem nor the network, so INV-13's sandbox digest is not yet satisfiable
and no result produced here claims otherwise. Isolation is deferred to a
capability profile because the primitive cannot be exercised on this
repository's CI runners — `ubuntu-latest` restricts unprivileged user
namespaces — and a gate that cannot run is the defect this programme exists to
close.

**INV-8 is not yet true on the live path.** The broker still has no production
caller; the orchestrator's `run_command` continues to execute directly. Routing
is the next change, and it is separated deliberately: a self-destructing
dormancy waiver that lands in the same commit as its own fix never fires.

#### Changed

- `test_governance_broker.py` rewritten. The previous tests patched
  `broker.subprocess.run` module-wide to stand in for the PDP child process;
  with a real engine behind the same attribute those patches would have
  intercepted the engine instead and passed while testing nothing. Three of them
  pinned behaviour since identified as a fail-open —
  `test_pdp_skipped_when_files_absent` asserted that a missing policy file
  skipped the verdict.

### Agent containment — the write tool cannot reach the control surface

The second change in the containment sequence. `protected_paths` was enforced
only by `validate_invariants.py` at CI time, against the set of files a commit
changed. In the deployed path the agent's workspace *is* the repository root
(`api_server/main.py` passes `workspace_dir=PROJECT_ROOT`), so `write_file` --
correctly confined to the workspace -- had write access to the guard, the policy
decision point, the orchestrator's own hooks, both policies, the agent personas
and `.git/`.

Enforcement was not absent, it was at the wrong granularity: `pre-nemotron-run`
runs `validate_invariants.py` at the top of every `execute_agent` call, so a
protected-path write is caught at the *next* agent boundary — with a whole
tool-call budget in between, and the last agent's own writes never re-checked
before its post-run hook fires.

#### Fixed

- **`_execute_write_file` consults the write policy at tool-call time**
  (`write_policy.py`), reusing `validate_invariants.is_protected` rather than a
  second matcher. `.git/**` is denied explicitly: `validate_invariants`
  enumerates staged, modified and untracked files, and git never reports
  anything under `.git`, so `protected_paths` structurally cannot cover a hook
  or a `core.fsmonitor` entry written there.
- **The verifier no longer receives `write_file`.** `execute_agent` passed no
  `tools=` for the reasoner or the verifier, so both fell through to the
  implementer schema — the role that judges the work could edit it, and could
  write the hook `_run_hook` executes on the host at the end of its own turn.
  Exposure is now derived from `agent-policy.json`: the union of a role's
  canonical contracts minus each contract's `human_approval_required_for`, so
  `release-auditor`'s approval-gated `external_write` and `production_change` do
  not leak into the verifier either.
- **Credentials no longer leave over HTTP.** `debug_dump` scrubbed
  `NVIDIA_API_KEY` alone while `/api/orchestrate` returned the conversation
  history, so `API_SERVER_KEY` and `AGENT_EVIDENCE_KEY` passed in clear text.
  The second is the HMAC key `EvidenceBuilder` signs with: disclosing it permits
  forged evidence manifests, so this was an escalation rather than a leak. The
  single redactor now covers the reviewed list, sweeps any variable whose *name*
  marks it as a credential (with a length floor, since replacement is by
  substring), and matches seven more provider shapes.
- **Hook environments are filtered.** `_run_hook` handed every hook
  `os.environ.copy()`. `agent-policy.json` has always declared
  `secrets_may_not_be_propagated_to_subagents: true` and nothing enforced it.
- **An escape attempt now leaves a trace.** A write outside the workspace was
  refused and logged nothing at all.

#### Added

- `harness/shared/write_policy.py` and `harness/shared/agent_authority.py`, both
  at 100% line coverage.
- `test_write_containment_regression.py`, parametrised over ten steps of a
  published escalation path and asserting on the filesystem rather than only on
  the returned string. Confirmed failing against the pre-fix commit: the pre-fix
  run reports `Success: Wrote 7 characters to .../pre-nemotron-run.sh`.
- `tool_broker_reference.py`, `write_policy.py` and `mango_mas_orchestrator.py`
  join `protected_paths` and `CRITICAL_PATTERNS`. The PDP is executed by the
  broker as a host subprocess *before* the command guard runs, and was
  unprotected; so were the two enforcement points themselves.

#### Note on a defect found in this change's own first draft

Path normalisation used `lstrip("./")`, which strips a character *set* rather
than a prefix: `.mango/hooks/x.sh` became `mango/hooks/x.sh` and `.git/config`
became `git/config`, so the entire control surface read as unprotected while the
gate reported success. Caught by running the check against real files, and
pinned by `test_dot_prefixed_paths_are_not_mangled`.

### Agent containment — the policy guard is reached, and fails closed

Spec: `docs/specs/agent-containment.md`. Peer-reviewed before implementation by
the Architecture, QA, Security and SDLC/Product personas plus a sandbox-viability
design review; all five rejected two earlier drafts of this work, and the
findings reshaped its sequencing and scope.

#### Fixed — the orchestrator's guard call could not block anything

- **The guard evaluated the empty string for every command.** The orchestrator
  sent `{"tool": ..., "args": {"command": ...}}` while `main()` read
  `tool_input.command`, so `check_command` received `""` and returned 0. A
  `git push` to an arbitrary remote exited 0 through the orchestrator's payload
  shape. The guard now canonicalises both envelopes, so the historical payload is
  evaluated rather than silently allowed, and a JSON object carrying neither
  envelope is denied with the PreToolUse block code (DEC-006).
- **The guard was optional and loaded from agent-writable ground.** It was
  resolved at `workspace_dir / "harness/shared/pretooluse_guard.py"` and skipped
  entirely when absent — the comment on the following line recorded the fail-open
  as intended. It is now imported from the installed harness and consulted
  in-process; absence, import failure and evaluation errors all deny (DEC-005).
- **Non-object JSON exited 1** through an uncaught `AttributeError`, which a
  PreToolUse consumer reads as a broken hook rather than a denial. It now exits 2.
- **A denial's reason never reached the caller.** The remote-destination check
  runs in a child process, so its stderr went to fd 2 rather than into the tool
  result explaining the refusal. It is captured and routed through the guard's
  own block path.

#### Added

- `harness/shared/tests/regression/test_guard_reachability_regression.py` — each
  test confirmed failing against the pre-fix commit on **behaviour**, not on a
  missing symbol: the pre-fix run executes the command (`fatal: not a git
  repository`) where the fixed run refuses it, and the historical payload asserts
  `0 == 2`.
- Structured gate logging in the guard, which previously had no logger at all —
  only a bare `print` to stderr. Blocks now carry a stable reason code, and DEBUG
  records the resolved root, its source, and the allowlist path, so a denial
  caused by a missing allowlist is distinguishable from a policy verdict.
- `TestEnvelopeCanonicalisation`, `TestExtractCommand`, and a test pinning the
  guard's *unmodelled* surface (`rm -rf /`, `curl | sh`, `cat .env`,
  `pip install`) so its advertised scope cannot drift from its real scope.

#### Changed

- `test_block_dangerous_rm` renamed to `test_danger_matches_git_push_forms`: it
  asserted on `git push`, in a guard whose `DANGER` pattern has never modelled
  `rm`. The name advertised a control that does not exist.
- The two orchestrator guard tests materialised a fake `pretooluse_guard.py` in
  the workspace and asserted the orchestrator honoured its exit code — pinning
  the wiring while leaving the payload contract, the thing that was broken,
  unexercised. They now drive real commands through the real matcher.

#### Known scope limit

This change does **not** make `run_command` safe. `DANGER` models `git push` and
`gh repo create --public` and nothing else, so `rm -rf /`, `curl | sh`,
`cat .env` and `pip install` remain unblocked — now pinned by a test rather than
left implicit. Command-level containment arrives with the execution broker.

### Security — three policy readers could not tell an absent policy from an unusable one

`policy_loader.load_policy`, `check_projections.decision_id_regex` and
`verify_zero_skips._decision_id_regex` each documented the same contract — no
policy file is the adopter path, a present-but-malformed policy fails closed —
and each implemented it with a bare `Path.is_file()`, which cannot express it.
`is_file()` answers False both for a path with nothing at it and for one holding
a directory, a dangling symlink, a FIFO or a device node.

The failure is a deployment away, not a hypothetical: a container mount whose
source is missing leaves a directory, and a moved or unextracted target leaves a
dangling symlink. Either one sent all three readers down the adopter branch, so
every threshold and the decision-ID grammar silently fell back to built-in
defaults and the run went green — the gate reporting success precisely because
it had stopped reading the policy that governs it.

Worse, the `Path` predicates also swallow `OSError`. `is_file()`, `exists()` and
`is_symlink()` all answer False when the policy is *present and merely
inaccessible* — a parent directory without execute permission, a path component
that turned out to be a file (`NotADirectoryError`), a symlink loop. No
predicate can express the question; only the errno can.

All three readers now probe with `stat`/`lstat` and branch on the error.
`FileNotFoundError` from both is the adopter path; anything else stops the run.
`lstat` is what separates "nothing here" from "the symlink target is gone",
since `stat` follows the link and reports both as `FileNotFoundError` — while a
symlink to a *real* policy file must still be followed and read, so rejecting
every symlink would be a fail-closed bug of its own. `policy_loader` exposes the
rule as `policy_file_is_absent`; the other two inline it, because both are
standalone-stdlib by contract (the adopter path copies them, so they take no
harness imports).

`test_policy_path_fail_closed.py` pins it twice over. Behaviourally, each reader
is driven with a directory, a dangling symlink and a FIFO, and must raise with a
reason — while a genuinely absent policy must still return the fallback, so the
fix cannot quietly break the adopter case it stands in front of. Structurally, a
source scan bans the shape outright: a policy path is never guarded by
`is_file()`, because there is no correct way to answer this question with it.
(An earlier version of the scan required a compensating `is_symlink()` nearby,
which a guard checking *only* `is_symlink()` would have satisfied while still
failing open on a directory.) The scan carries both a positive and a negative
control, so neither a pattern that matches nothing nor one that matches the
fixed form can pass unnoticed. Every claim about the stdlib that makes this a
regression rather than a style choice is asserted too, not left in a comment.

All of it was verified failing against the reverted code, including a guard
written the way the first review round suggested.

### Remediation programme v3 — peer review of the v2 tech-debt programme

An objective review of PRs #15-#19 plus a wider gap analysis, shipped as three
sequential PRs. Three of the review's own initial claims were wrong and were
corrected against git before any work started: per-file coverage and the
policy-loaded decision-ID grammar do **not** exist on `main` (they arrive with
the open #18/#19), while the `socket.timeout` retry defect is in `main` *and*
in #19 — neither open PR fixes it.

#### Fixed — six runtime defects, each pinned by a failing-first regression test

- **Retry was dead on Python 3.9**, a live CI matrix leg. `urlopen` read
  timeouts raise `socket.timeout`, which only became an alias of `TimeoutError`
  in 3.10, so `NEMOTRON_MAX_RETRIES` did nothing for the most common transient
  failure. Peer resets were unretried on every version.
- The `urllib.Request` was built once and replayed across retry attempts;
  `Retry-After` was ignored; backoff had no ceiling (~34 minutes by the 11th
  retry). A non-JSON body on an HTTP 200 was reported as "Connection Error".
- `resolve_environment()` returned as soon as the key and model were in the
  process environment, making `NEMOTRON_TIMEOUT_MS` / `NEMOTRON_MAX_RETRIES`
  unreachable from `.env` in exactly the normal configuration.
- Orchestrator tool dispatch crashed on `arguments: null` (`json.loads(None)`
  raises `TypeError` past an `except json.JSONDecodeError`) and on
  `arguments: "[]"`. A raising handler aborted the agent loop, leaving the
  model's `tool_calls` message unanswered and skipping the post-run hook.
- **Debug-history redaction never ran.** It was guarded on `self.api_key`,
  which the orchestrator normally leaves `None` because the bridge resolves the
  credential downstream — so `MANGO_DEBUG_DUMP=1` wrote plaintext credentials
  to a predictably named file in the shared temp directory, with default
  directory permissions. The existing test passed `api_key=` explicitly, the
  one configuration where the old code did redact.
- The API server compared its key with `!=` (a timing oracle) and returned
  `conversation_history` verbatim over HTTP. Both fixed; note the hardening's
  own second-order bug, caught by its test: `compare_digest` raises `TypeError`
  on non-ASCII `str`, and header bytes are latin-1 decoded, so a naive fix
  would have traded a timing leak for an unauthenticated 500.

#### Added — enforcement where there was only intention

- **Regression / AQA tier** (`harness/shared/tests/regression/`), selected by
  path rather than by a marker, with one reproduction per defect above. Every
  module was confirmed failing against the pre-fix commit.
- **`test_import_purity.py`** — every shared and control-plane module must
  import from a foreign working directory with exit 0, no output and no writes.
  `validate_adoption.py` ran its entire gate at module scope; two sibling CLIs
  had been fixed by hand in the previous programme and the third survived
  because there was no rule.
- **`test_test_quality.py`** — ten tests in the suite could not fail. It found
  the tenth after the manual pass had found nine.
- **`test_lint_config_liveness.py`** — three `per-file-ignores` patterns
  suppressed nothing (including one for a gitignored directory that does not
  exist), plus a dozen unused codes. Measured with `ruff --isolated`; a normal
  run applies the very ignores under test.
- **`test_deferred_rigor.py`** — every declined lint rule and mypy flag carries
  its measured finding count and a reason, and the register fails in both
  directions.
- **`test_agent_surface_liveness.py`**, **`test_documentation_truth.py`**,
  **`test_makefile_contracts.py`** — skills dated and classified, hooks
  referencing only real paths, `.mango` proven the only skill root, the README
  layout tree checked against the filesystem.
- Three **scheduled workflows** that open issues and never block: nightly drift
  on `main`, weekly skill staleness, weekly hook-install drift.
- One new skill, `protected-path-attestation`, which produces the artifact the
  labelled PRs in this programme need.

#### Changed — measured, not speculative

- ruff gains `BLE`, `RUF100`, `ICN`, `ISC`, `RSE`, `TID`, `A`, `C4`, `PIE`.
  `BLE` turns 27 `# noqa: BLE001` justifications from prose into enforced
  decisions. `RUF100` is safe *because* `BLE` is on: it flagged 20 inert
  directives before, 13 of them exactly those justifications.
- mypy gains `--check-untyped-defs` (14 findings, all fixed), which checks the
  bodies of unannotated functions. Full `--strict` (604) and
  `--disallow-untyped-defs` (533) are deferred with those numbers.
- **Bare `pytest` now passes.** `addopts` deselects `live`, and the live suite
  that lacked its sibling's `skipif` has one.
- `.claude/hooks/session-start.sh` installs Node dependencies through
  `make node-deps`, the same recipe CI uses. `make pre-pr` could not complete
  in a web session before this.
- `.mango/settings.json` routes hook commands through `bash`, matching
  `.claude/settings.json`. Every tracked `.sh` is mode 644 and stays that way —
  the defect was the invocation, not the mode.

#### Removed

- `.github/skills/code-review/` — a second skill root, fully orphaned, naming a
  different project and asserting a >80% coverage bar against a policy of 90.
- Pong ignore rules from `.gitignore`, two PRs after the demo was deleted.
- `.agents/skills/` from the README layout tree; the directory does not exist.

#### Collected — three deferrals that came due when the policy work merged

The v3 stack was built on `main` deliberately excluding the then-open
policy-single-source work, so re-implementing it could not conflict with review
already spent. Three places recorded that dependency in a form that fails when
it is discharged, rather than in a comment nobody re-reads:

- `KNOWN_IMPORT_SIDE_EFFECTS` waived three modules that acted at import.
  `test_every_waiver_is_still_necessary` failed on all three the moment they
  imported cleanly, so the entries were deleted and the modules now fall under
  the purity gate normally. The registry is empty and documents what earns a
  new entry.
- `DTZ` was deferred solely because one source site sat inside a rewritten
  file. Both source sites — waiver expiry in `verify_zero_skips.py`, skill
  staleness in `validate_governance_docs.py` — now anchor to UTC, the rule is
  enabled, and the deferral entry is gone. A waiver keyed on a calendar date
  expires a day early or late depending on the runner's timezone; six test
  sites shared `date.today()` and would have disagreed with the validators for
  the hours where the two dates differ, so they share one clock via a
  `utc_today()` helper.
- Three `per-file-ignores` E402 entries stopped suppressing anything once those
  modules were restructured; `test_every_code_still_suppresses_something`
  reported it and they were removed.


Hygiene remediation batch (DEC-004), shaped by three adversarial reviews of its
own plan -- nine elements of the first draft were rejected as wrong or
net-negative before implementation (among them: a branch-coverage change that
would have silently blended the metric it claimed to gate, regression tests
that could never fail, and deletions that broke the policy template/instance
relation).

### Security — coverage is now two floors, not one blend

- **Branch coverage was not measured at all.** `shadow_planner.py` read 100%
  line-covered while half its branches — including the "no api_key / no model,
  defer to the bridge" leg — had never executed. `branch = true` is now set,
  and measurement exposed a trap: with branch arcs recorded, pytest-cov's
  single total is a blended statements+branches number, so keeping
  `--cov-fail-under` would have gated that blend against `coverage.lines` —
  line coverage could regress below 90 while the blend stayed green, the same
  "gate that lowers itself" inversion the COV_MIN=80 fallback had.
- New `harness/shared/coverage_gate.py` enforces `coverage.lines` and
  `coverage.branches` as **separate floors** from `coverage.json` + policy,
  fail-closed on a missing/malformed report or policy, with no numeric default
  anywhere. `branches` moved from `UNENFORCED_IN_ROOT_CI` to `PYTHON_ENFORCED`
  (waiver deleted, not reworded). Measured: lines 94.10% ≥ 90, branches
  89.46% ≥ 80. The four worst branch offenders were brought to 100% branches
  with behavioural tests (bridge-defaults leg; shim bootstrap and `__main__`
  dispatch legs via runpy, asserting the pretooluse guard's real verdicts).

### Fixed — two crash paths in the policy-reading gates

- `LOG_LEVEL=BOGUS` crashed all three gates with `ValueError` before any check
  ran; `resolve_log_level()` existed for exactly this and none used it. All
  three now degrade bad verbosity instead of failing the gate. Regression
  tests are subprocesses on purpose: under pytest the root logger already has
  a handler and `basicConfig` ignores `level`, so an in-process test passes
  identically with and without the fix.
- A policy of valid JSON that is not an object (`[]`) escaped as a raw
  `AttributeError` traceback; it now routes to the same fail-closed
  "[FAIL] Malformed governance policy" path as a syntax error, with a probe
  per gate.

### Added — cross-file policy consistency gates

- `test_policy_consistency.py` (25 tests): the shared policy is pinned as a
  **superset** of both per-stack instances (value-equal on common keys,
  `protected_paths` the one declared divergence); five unwired keys are
  classified in `DECLARED_NOT_YET_ENFORCED` with reviewed reasons — mirroring
  `UNENFORCED_IN_ROOT_CI` — instead of deleted, because the per-stack mirrors
  sit under root-of-trust + bundle digests and two of the five are
  declarations other artifacts still reference; the decision-ID grammar is
  equality-checked across **all five copies** (three policies, two scanners,
  extracted via AST); `agent_defaults` is cross-checked against
  `agent-policy.json` in all three stacks; `GITLEAKS_VERSION` must be
  identical across the three Makefiles. 5/5 mutants killed.

### Changed — the bundle's top level is finally regenerable

- `build_policy_bundle.py` — the only regenerator of the bundle's top-level
  `governance_policy_sha256`/`agent_policy_sha256`, which
  `verify_repository.py` checks and CI exercises — was invoked by nothing. It
  is now `main()`-guarded, tested, coverage-measured, and wired into
  `make digest-regen` behind the existing `git diff --exit-code` (rebuild
  verified byte-identical before wiring, so the first run is a zero-diff
  no-op). A per-stack policy edit can no longer leave the committed bundle
  stale unnoticed.
- `check_traceability.py` gained the `sys.path` bootstrap it was the only shim
  to lack, structured import-first-then-retry (no E402 exemption). Its
  regression test runs under `python -S`, where the editable install cannot
  mask a gutted bootstrap.

### Removed

- `harness/SHA256SUMS.txt`: pinned 10 files (9 digests stale, 5 entries in a
  deleted directory), read by nothing. The live equivalents are
  `policy-artifact.json` and `policy-bundle.example.json` + `digest-regen`.
- The dead top-level `size_budget_lines` fallback in `validate_invariants.py`
  (no policy file ever carried the key at top level), and the stale claim that
  the module runs as a git pre-push hook.

### Recorded, not built

- The specs gate accepts an entirely unfilled template scaffold (placeholder
  `R-EXAMPLE-*` IDs satisfy it), and an `AC-*` bullet containing MUST can
  never pass its `[CR]-` ID regex — both are future gate refinements.
- `validate_policy.py`'s `scripts/*` critical-path list is CORRECT for its
  actual input (the per-stack policy it validates from CWD); it never reads
  the shared file.

## [2.1.9] - 2026-08-27

Governance follow-ups from the 2.1.8 review passes. Each needed a protected-path
change and therefore the `infra-reviewed` human attestation, which is why they
were recorded rather than patched in 2.1.8.

### Security

- **`protected_paths` patterns that matched zero files are now live.** Four
  patterns (`.governance/**`, `agents/**`, `docs/PROJECT-CHARTER.md`,
  `.github/CODEOWNERS`) were left in a single-stack frame by the layout
  migration in `1eb2f7f`, which migrated only the `scripts/*` entries. Because
  `fnmatch` is whole-string anchored, they matched nothing and the gate reported
  PASS *because nothing matched* — an agent could add itself a test skip-waiver,
  widen the git push allowlist, or edit the external root of trust unreviewed.
  Patterns are added, never replaced: the originals cover a single-stack adopter
  layout and the `**/` twins cover this repo's multi-stack one.
- **The agent control surface is now gated**: `CLAUDE.md`, `harness/CONTRACT.md`,
  `.mango/skills/**`, `agent-policy.json`, the `.claude/` and `.mango/` hook and
  settings files that execute shell, `pyproject.toml` (where lint, type and
  coverage gates can be silently weakened), and the policy publisher plus its
  committed drift baseline. Protected files: 37 → 104.
- Recorded as DEC-002 with the workflow cost measured rather than estimated:
  ~32% of historical commits would newly require the label. DEC-003 records that
  the five unbound `.mango/hooks/` scripts stay dormant.

### Fixed

- **The container image could never have built.** `.dockerignore` excludes the
  whole `.mango/` tree, so `COPY .mango/ /app/.mango/` had no source to resolve
  — reproduced against a real daemon as `"/.mango": not found`, with a
  `COPY harness/` control build succeeding to isolate the cause. Dead since the
  v2.1.1 `.claude/` → `.mango/` rename; no `docker build` runs anywhere to have
  caught it. The runtime stage now sources `/app/harness` from `build` rather
  than the context, which keeps that stage in the graph — BuildKit skips
  unreferenced stages, which would have silently dropped its `tsc --noEmit`.
- `.dockerignore`'s `.governance/vitest-results.json` and `.governance/coverage/`
  had the same anchoring bug as the `.gitignore` entries fixed in 2.1.8 and
  excluded nothing; verified by exporting the build context before and after.

### Changed

- **The `specs` gate now runs in `make ci`.** It was listed in
  `ci_required_targets` but had no CI stage; both meta-tests asserting "CI
  invokes every required target" read the per-stack `ci.yml`, never the root
  workflow. Invoked as `bash harness/shared/validate_specs.sh` because that file
  is mode 644 — a bare `./` invocation would have been a guaranteed red CI.
- **`harness/control-plane` is now measured by the coverage gate**, making
  `publish_policy_artifact.py` (158 statements, 78%) governed. Three CLIs are
  omitted because they run `argparse` at module scope with required arguments
  and have no `__main__` guard, so they cannot be imported in-process and read
  0% as an artifact. `regenerate_bundle_digests.py` is deliberately kept
  measured: it *is* importable, so its 0% is a real gap. Total: 95.69% → 92.97%.

### Security — INV-1 had no live enforcement

- **The secret scan never ran in CI.** The gitleaks steps live in
  `harness/{node,jvm}/.github/workflows/ci.yml`, which are **adopter templates
  GitHub never executes** — it reads workflows only from the repository-root
  `.github/workflows/`, which contained no secret scan at all. INV-1 ("secret scan
  covers working tree and full history and fails closed when tooling is absent")
  was therefore unenforced on every commit in this repository's history.
- Added a root `secrets` target mirroring the per-stack shape (fails closed when
  gitleaks or its config is absent, scans both the working tree and full history)
  plus `secrets-install` pinning the same gitleaks version, and a dedicated
  `secret-scan` CI job that runs it once with `fetch-depth: 0`. It is a separate
  job rather than a `make ci` stage because the scan is interpreter-independent;
  inside the matrix it would repeat identical work on all three Python matrix legs.
- Verified by running the pinned scanner: clean on the working tree (98.7 MB) and
  across all 73 commits of history. No allowlist changes were needed.

  **Superseded — this verification was vacuous.** The config passed to
  `--config` declared no `[[rules]]` and no `[extend] useDefault = true`, and
  `--config` *replaces* gitleaks' built-in ruleset rather than extending it. The
  scan therefore ran with zero rules: "clean across all 73 commits" was a
  statement about a scanner that was not looking for anything, and a planted
  `AKIA...` key scanned clean under this exact config. "No allowlist changes
  were needed" was true for the same reason, and is falsified now that the scan
  runs — one entry (`test_debug_dump.py`) was required. Corrected under
  [Unreleased]; pinned by `test_lint_config_liveness.TestGitleaksActuallyScans`.

### Changed — CI gate coverage (INV-5)

- **`make remotes`** now exists and runs in `make ci`. The remote-allowlist gate
  (INV-3) had a shared implementation and a per-stack target, but no root wiring.
- `test_ci_gate_coverage.py` enforces INV-5 directly: every `ci_required_targets`
  entry must map to a root Make target that CI actually invokes — reachable from
  `make ci`, or run by a root workflow job — or be declared in `KNOWN_GAPS` with a
  reason. `audit` (osv-scanner) is the one declared gap. The suite resolves Make
  prerequisites transitively and expands Make variables, so a mapping that points
  at an unreachable or renamed target fails rather than reading as covered. It
  also fails if a coverage source root declared in `pyproject.toml` is not passed
  to the gate — the exact configured-but-unmeasured state `harness/control-plane`
  was in. Verified against 12 mutants, all killed.

### Fixed — documentation that contradicted the contract

- `PRE_PR_VERIFICATION_REFERENCE.md` **misnumbered two invariants**: it labelled
  INV-5 "Size Budget" and INV-7 "Traceability", while `harness/CONTRACT.md`
  defines INV-5 as CI gate coverage and INV-7 as bounded delegation. The table now
  covers all sixteen invariants, is explicitly an index onto the contract rather
  than a second source of truth, and every command in it was executed to confirm
  it resolves to real tests.
- Removed two hard-coded coverage thresholds that contradicted policy: the
  reference guide's `--cov-fail-under=80` and `.mango/agents/verifier.md`'s
  "coverage % (must be >= 80%)", against a policy value of 90. Both now read the
  threshold from `governance-policy.json`, as `COV_MIN` already did.
- README, C4 architecture, and the reference guide carried stale versions and test
  counts (2.1.7/2.1.8, "575+ tests", "490 Python", "486+ Tests"). Now 2.1.9 with
  measured counts, and the C4 gate diagram includes the spec, remote,
  protected-path, and CI-gate-coverage gates. Diagram re-validated as Mermaid.

### Security — the coverage gate lowered itself, and most declared thresholds ran nowhere

A second audit traced every key in `governance-policy.json` to the code that reads
it. Findings below were each confirmed by running, not by reading.

- **The coverage gate failed *open*.** `COV_MIN` fell back to the literal `80`
  whenever the policy was unreadable or its `coverage` block absent — while the
  policy declared 90. Governance fails closed everywhere else
  (`validate_invariants` exits non-zero on an unreadable policy); this one gate
  silently weakened itself. It now fails closed, and `coverage-python` aborts on an
  unresolved threshold. `pyproject.toml` separately hard-coded `fail_under = 80`,
  so any `pytest --cov` run that did not pass the Makefile's explicit flag enforced
  the weaker number; that declaration is removed, leaving one source of truth.
- **`harness/node/vitest.config.ts` hard-coded all five thresholds**, duplicating
  the policy block it was copied from with nothing detecting divergence — a direct
  violation of CLAUDE.md's "no hard-coded values; thresholds come from
  governance-policy.json". It now reads the policy and fails closed on a malformed
  one.
- **Four of the five declared thresholds are enforced nowhere in the root
  pipeline.** Only `coverage.lines` is applied, and only in aggregate.
  `statements`, `functions` and `branches` are enforced solely by the vitest config
  — which `make test-node` never activates, because it runs `vitest run` **without
  `--coverage`**. Measured: enabling it fails six Node files today, so it is
  recorded as a quantified follow-up rather than switched on into three open PRs.
  `per_file: true` has no Python implementation at all; six measured files fall
  below `lines`, and aggregate headroom is ~60 statements, so an entirely untested
  new module can ship green. `test_coverage_policy_enforcement.py` now fails if a
  threshold key is neither enforced nor declared a gap with a measured reason.
- **`dedup.exempt` was an unguarded bypass** — an entry silently disables the
  shim-vs-copy drift gate for that file. It is empty today and now asserted so.

### Security — the new gates verified names, not substance

An adversarial review of the gates added earlier in this release found they
asserted a target's *name* was wired in without ever asserting the target still
*did* anything. Every case below was confirmed by mutation — the suite stayed
green — and every one is now killed.

- **The protected-path gate could be deleted outright.** Removing the
  `validate_invariants.py` line from the `validate` recipe left its name in `ci`
  and the whole suite passing, disarming every guarantee
  `test_protected_path_liveness.py` exists to make. The same held for `ruff` and
  `mypy` (`lint`), and for the remote-allowlist recipe. `GATE_TO_EVIDENCE` now
  requires each mapped gate's recipe — and its prerequisites' — to still invoke the
  enforcing artifact.
- **Deleting a `protected_paths` pattern was invisible.** Liveness only caught
  patterns that stayed but matched nothing, so `Makefile`, `.mango/settings.json`,
  `remotes.py`, `install_hooks.sh` and `pre_push_scan.sh` could each be
  un-protected with the suite green. `CRITICAL_PATTERNS` is now an explicit floor.
- **The secret-scan gate had four independent false positives**: commented-out
  scan commands satisfied the check (a raw recipe capture includes `#` lines); the
  `fetch-depth: 0` assertion was global, so the *build* job's checkout satisfied it
  while the scanning job went shallow and its history scan turned vacuous; and an
  `if:` guard on the job or step could disable it entirely. Checks are now scoped
  to the job that actually runs `make secrets`, comment lines are stripped, and any
  conditional on that job fails the test.
- **The coverage threshold could be set to zero.** The test inspected `COV_MIN`'s
  *definition*, never its use, so `--cov-fail-under=0`, dropping the flag, or
  deselecting governance tests via `-m` all passed.
- **Makefile parsing accepted fiction as fact.** A single-`#` comment (which Make
  ignores) parsed as prerequisites, so `ci: lint coverage # was: specs remotes …`
  reported every commented-out stage as reachable. Prerequisites are now truncated
  at the first unescaped `#`, line continuations are spliced, and every reachable
  name must resolve to a real rule.
- **Four `make ci` stages were unguarded** — `test-node`, `verify-zero-skips`,
  `check-dedup` and `digest-regen` could all be dropped silently.
  `REQUIRED_CI_STAGES` pins them with a reason each.
- **`--cov={source}` was a substring test**, so broadening the declared coverage
  source to `["harness"]` read as measured while most of the tree was not. Now an
  exact token comparison, with the pyproject read scoped to `[tool.coverage.run]`.
- **Non-ASCII protected paths evaded the gate entirely.** With git's default
  `core.quotePath`, such a path is reported C-escaped and double-quoted, and the
  leading quote defeats every anchored `fnmatch` pattern. Both `validate_invariants`
  and the liveness suite now pass `-c core.quotePath=false`; covered by a regression
  test that fails without it.
- Corrected a factually wrong justification in the dormant-pattern rationale:
  `validate_policy.py` does **not** backstop the shared policy — it runs with
  CWD=`harness/node` and reads that stack's own `policy.json`.

Also newly protected: `.gitleaks.toml` (allowlist edits neuter the INV-1 scan),
`requirements-dev.txt`, the per-stack `Makefile`s, `regenerate_bundle_digests.py`,
and the two gate test modules themselves. Protected files: 104 → 111.

### Added — gate diagnostics

- `json_logging.configure_gate_logging()` — a reusable, operator-controlled gate
  logger. Level comes from `LOG_LEVEL` (names or numerics, case-insensitive); an
  unusable value **degrades to the default rather than raising**, because
  misconfigured verbosity must never be able to fail a governance gate. Writes to
  **stderr**, never stdout: gates print their verdict to stdout and both CI and the
  test suite match on those exact strings, so raising verbosity is structurally
  incapable of changing a verdict. The handler resolves `sys.stderr` at emit time
  rather than at construction, so diagnostics stay visible to pytest capture and to
  any caller that redirects the stream, and `propagate` is off so a stray
  `basicConfig()` elsewhere cannot reroute them onto stdout.
- The traceability gate now names **which side** each requirement is missing from
  (`absent from implementation and tests`) instead of only that something is
  missing, and at `DEBUG` reports which globs matched which files — which is how a
  glob scoped to a single stack, silently checking nothing outside it, becomes
  visible. The original leading sentence is preserved, so existing CI-log and test
  matches are unaffected.

### Fixed — an untested script inside `make ci`

- `regenerate_bundle_digests.py` ran in the `digest-regen` stage with **0% test
  coverage**, because its paths were module constants that could not be pointed at
  a fixture. Paths are now parameters with the same repo-relative defaults (the
  zero-argument form the Makefile uses is unchanged), and the digest computation is
  separated from persistence so drift behaviour is testable without writing to the
  real bundle. Coverage 0% → 92.59%.
- Stale manifest entries were dropped **silently** — a deleted protected file
  vanished from the bundle with no output at all. Drops are now logged at WARNING
  with the specific paths and summarised on stderr, leaving the stdout summary a
  stable shape. Exit semantics are unchanged: `digest-regen` still pairs this with
  `git diff --exit-code`, which is what turns a drop red.

### Security — three more gates that failed open, and a gate module left unprotected

Found by reviewing a *plan* rather than a diff: a proposal to classify unused
policy keys was reframed into "which gate reports PASS without doing its job",
which is the failure class this release exists to eliminate. The keys turned out
to be a non-issue; three fail-open gates and an unprotected gate module did not.

- **Three governance gates degraded to their defaults on a malformed policy.**
  `validate_invariants.size_budget_lines`, `check_dedup.load_config`, and
  `check_py_compat.load_skip_dirs` each wrapped the policy read in a broad
  `except` that returned the built-in default. This is the same inversion
  `COV_MIN` had two commits earlier — a gate that lowers itself on exactly the
  input that should stop it — and all three were missed while fixing the first.
  Confirmed by running against a corrupted policy: all three returned their
  defaults and reported PASS.
- The three now distinguish **absent** from **malformed**. An absent policy still
  defaults, because that is the adopter path and the shared kernel must run
  outside this repository. A policy that exists but cannot be parsed or read
  (`OSError`, including permissions) exits 1 with the reason. `FileNotFoundError`
  is ordered ahead of `OSError` so the two legs stay separable, and a test pins
  that ordering.
- **Every one of these defaults was byte-identical to its policy value**
  (`size_budget_lines: 500` vs `SIZE_BUDGET_LINES = 500`; `max_shim_lines: 40` vs
  `DEFAULT_MAX_SHIM_LINES = 40`), so no existing assertion could tell whether the
  policy was read at all. Each gate now has a probe test driving a deliberately
  distinguishable value through to the *behaviour* — a 7-line size budget must
  reject a 10-line file — which is what makes deleting the block detectable.
- **`test_coverage_policy_enforcement.py` was not in `protected_paths`**, though
  the two sibling gate modules added in the same branch were. It owns the entire
  coverage-threshold classification, so an agent could have deleted that gate
  outright with `make ci` green and no `infra-reviewed` label. It is now
  protected and in the `CRITICAL_PATTERNS` floor, which makes removal — not just
  decay — detectable.

### Testing — the spec gate had no behavioural tests

- **`make specs` was wired into `make ci` last release with nothing asserting it
  does anything.** The only coverage was `test_ci_gate_coverage.py` checking that
  the Makefile *invokes* it: a name check that would pass if the script were
  gutted to `exit 0`. `test_validate_specs.py` drives the real script against
  fixture spec directories and asserts on exit status and diagnostics. Verified
  against 8 mutants (gutted structural tier, each rule removed individually,
  `rglob`→`glob`, `*`-bullets unscanned, empty-directory pass, strict tier failing
  open) — all killed.
- The suite pins the negative space as well: prose containing "MUST", bullets
  without "MUST", and nested spec files must *not* be rejected, so the rules
  cannot be tightened into uselessness either.
- **The strict tier does not run in root CI, and now says so.**
  `validate_specs.sh` is two-tier; `openspec` is pinned nowhere and
  `REQUIRE_STRICT_SPEC_VALIDATOR=1` is set only in
  `harness/{node,jvm}/.github/workflows/ci.yml` — adopter templates GitHub never
  executes — so root CI takes the WARNING branch on every run. Declared in
  `PARTIAL_COVERAGE["specs"]` with a measured reason rather than left implied.
  Installing an unpinned validator as a hard CI dependency is a product decision,
  not a gate fix. A test asserts the waiver is **removed** the moment anything in
  the root pipeline sets the flag, so it cannot outlive the gap it excuses.
- The structural tier is genuinely load-bearing and is now shown to be: it
  rejects a missing required section, a normative `MUST` without a requirement ID,
  and unfalsifiable acceptance language, and it still does all three with the
  strict tier absent. "Degraded" and "off" are now distinguishable by test.

### Testing

- `test_protected_path_liveness.py` replaces a tautological test that asserted
  only that a pattern *string* appeared in the policy — which passes whether or
  not the pattern protects anything, and is how the dead patterns survived. The
  new suite asserts on the set of tracked files each pattern actually matches,
  requires intentionally-dead patterns to be declared with a reason, and checks
  that every discovered surface (workflows, hooks, `.governance/`, agent
  contracts, skills, charters, validators) is covered in full. Verified against
  14 mutants, all killed; one narrowing mutant survived the first draft and
  exposed a genuine gap, which is what added the charter and validator checks.
- `validate_invariants.is_protected` is extracted so the suite measures the real
  matcher instead of a reimplementation that could drift from it.

## [2.1.8] - 2026-08-27

### Fixed (post-implementation adversarial review, second pass)

A second independent adversarial review of the 2.1.8 work below, this time
probing the shipped code with real inputs rather than reading it, found a
blocker in the drift gate the wiring-audit pass had just added and several
correctness defects. All are fixed and covered by new tests in this same
release; see `docs/specs/mangomas-integration-core.md` for the requirement
IDs.

- **BLOCKER** — `publish_policy_artifact.check_artifact` never verified the
  artifact's `files` manifest actually covered `POLICY_FILES`: deleting an
  entry from a tampered artifact passed cleanly, defeating the drift gate
  this function exists to provide. Now verifies `artifact_id`, `policy_id`,
  and `policy_version` (all re-derived from the working tree, not merely
  echoed back), requires the file manifest to match `POLICY_FILES` exactly,
  cross-checks the previously-dead `bytes` field, and rejects an absolute or
  `..`-traversal manifest key (closes a hash-oracle probe for files outside
  the repo) — `_reject_unsafe_relpath` is kept as defense-in-depth for if
  `POLICY_FILES` is ever made config-driven, and is unit-tested directly
  since the manifest-scope check now makes it unreachable via the full
  pipeline. `_deny` now raises `PolicyArtifactError` (a plain `Exception`)
  instead of `SystemExit` (a `BaseException` that escaped `except Exception`
  in any caller, including the module's own use as a library) — `main()` is
  now the sole place a DENY becomes a process exit.
- `cognitive_signal.validate_signal_dict` — timestamp parsing normalizes a
  trailing `Z` before `datetime.fromisoformat`, whose acceptance of that
  suffix is a Python 3.11+ behavior (verified: rejected on 3.10, accepted on
  3.11/3.12); the CI matrix spans 3.9-3.12 and `Z` is the most common
  ISO-8601 UTC suffix an external producer would emit, so this was a real,
  interpreter-dependent acceptance gap. `payload` keys are now required to be
  strings — JSON's duplicate-key collapse (`{1: 'a', '1': 'b'}` silently
  losing `'a'`) was otherwise reachable through the validator. `payload`'s
  type annotation is `dict[str, Any]` (was bare `dict`, a `mypy --strict`
  `type-arg` finding and the type-level root cause of the key gap).
- `cognitive_signal.CognitiveSignalSink.append` — serializes with
  `ensure_ascii=True` (was `False`): a payload containing U+2028/U+2029/
  U+0085 previously produced a byte-safe single line that a Unicode-aware
  reader (`str.splitlines()`, exactly what the shadow-channel-analysis skill
  describes) would still see as multiple lines, and a lone surrogate raised
  `UnicodeEncodeError` uncaught. `ensure_ascii=True` closes both. Also now
  catches `RecursionError` (deep payload nesting) alongside the existing
  `TypeError`/`ValueError`, and `OSError` from `mkdir` (a sink path blocked
  by an existing file) — all as `SignalValidationError`, keeping the "one
  exception type" contract the module already documented but didn't fully
  deliver on.
- `shadow_planner._policy_identity` — a policy file that parses but carries
  an empty, null, or non-string `policy_id` now degrades to `"unknown"`
  instead of passing the bad value through: previously this made the very
  first `sink.append` (the incumbent signal) raise `SignalValidationError`,
  silently discarding the entire run — zero signals written, channel
  effectively dead with no diagnostic.
- `shadow_planner._run` — a shadow-side failure now emits a best-effort
  `plan.shadow_error` terminal signal (same `run_id`, `parent_signal_id` set)
  before the channel's own containment swallows it, so a `run_id` with only
  an incumbent signal is no longer indistinguishable from "still in flight"
  to an offline consumer (the shadow-channel-analysis skill already
  anticipated this case). A malformed/hostile provider response
  (`choices=[None]`, non-dict `message`, Anthropic-style content-block list,
  non-string `content`) now degrades to an empty plan via
  `_extract_shadow_plan_text` instead of raising `AttributeError` past the
  incumbent signal. The two containment layers (channel-level in this
  module, orchestrator-level guard) now log distinct messages so a test can
  tell which one actually caught a given failure, closing a mutation-testing
  gap where deleting either layer's `try/except` still passed the existing
  assertions.
- `harness/shared/tests/test_publish_policy_artifact.py`,
  `test_cognitive_signal.py`, `test_shadow_planner.py` — new tests for every
  fix above, plus `producer_id` assertions on the enabled-path signal test
  (the field C-MMI-2 is entirely about, previously unchecked) and a
  double-failure containment test (the bridge call fails and the best-effort
  `shadow_error` signal write fails too).

### Changed (coverage config)

- `pyproject.toml` — added `harness/control-plane` to
  `[tool.coverage.run] source`. Verified this does **not** yet change what
  `make coverage-python`/CI measures: pytest-cov's `--cov=harness/shared
  --cov=harness/api_server` flags on the `Makefile` command line take
  precedence over the static `source` list for that invocation. Making the
  publisher's coverage actually gate requires adding
  `--cov=harness/control-plane` to that protected `Makefile` line — recorded
  in `NEXT_STEPS.md` rather than done here. `publish_policy_artifact.py`
  itself is independently verified clean under `mypy --strict` (the errors
  that command reports are all pre-existing debt in modules it transitively
  imports — `governance/{verify_zero_skips,remotes,pretooluse_guard,
  check_traceability}.py` — not in the file itself).

### Added

- `docs/specs/mangomas-integration-core.md` — spec for the MangoMas integration core (R-MMI-1..10, C-MMI-1..6): CognitiveSignal envelope, shadow planner channel, policy-artifact publisher.
- `harness/shared/cognitive_signal.py` — immutable versioned CognitiveSignal envelope with fail-closed validation and a workspace-scoped, locked JSONL sink; `confidence` is untrusted metadata and producer identity carries no authority.
- `harness/shared/schemas/cognitive-signal.schema.json` — documentation schema pinned to the validator and dataclass by a drift-guard test.
- `harness/shared/shadow_planner.py` — observation-only shadow plan comparison behind `MANGO_SHADOW_PLANNER=1`: value-object boundary, empty tool schema, bounded timeout, contained failures; records incumbent/shadow signals with lineage, `elapsed_ms`, and provider usage.
- `harness/control-plane/publish_policy_artifact.py` — versioned, digest-pinned policy artifact builder with fail-closed `check` mode and optional `EvidenceBuilder` HMAC attestation whose signature transitively covers the artifact core.
- `harness/shared/tests/test_cognitive_signal.py`, `test_shadow_planner.py`, `test_publish_policy_artifact.py` — envelope validation/metamorphic suites, byte-identity-when-disabled and authority-boundary suites, publisher tamper matrix and subprocess CLI smoke tests.
- `harness/control-plane/policy-artifact.json` — committed policy artifact; `test_committed_artifact_matches_working_tree` drift-gates `governance-policy.json`/`agent-policy.json` inside `make ci` via the existing pytest stage (no protected-path change — `make digest-regen` only ever pinned the per-stack mirrors, never the authoritative files).
- `.mango/skills/boundary-invariant-review/SKILL.md` — reviews whether a diff gives a cognitive-plane field authority; the static boundary scan pins only today's module names, so this is the check that catches the next one.
- `.mango/skills/shadow-channel-analysis/SKILL.md` — freezes the UC-4 agreement/latency/token analysis method before any real producer exists, so the preregistered kill criteria stay preregistered.
- `.claude/settings.json`, `.claude/hooks/session-start.sh` — SessionStart hook installing pinned Python dev dependencies on remote sessions; registers this hook only, deliberately not the tool-guard hooks already declared in `.mango/settings.json`.
- `harness/CONTRACT.md` — INV-16 (one-directional cognitive/execution boundary).
- `harness/docs/C4_ARCHITECTURE.md` — Level 2 nodes for the cognitive boundary and control plane; a new Level 4.2 diagram for the shadow channel and INV-16.
- `.env.example` — the four shadow-channel variables and `AGENT_EVIDENCE_KEY` (required by `CONTRACT.md`/`evidence-signing` but previously undocumented here).

### Changed

- `harness/shared/meta_tools.py` — `_file_lock` promoted to public `file_lock(path, timeout_s, poll_s)`. The retry loop is now bounded by a poll budget as well as the deadline (previously a clock-source mutation, e.g. mixing `time.time()`/`time.monotonic()`, turned lock contention into an unbounded spin instead of a timeout); `Path.replace()`/`contextlib.suppress` hygiene cleanup.
- `harness/shared/cognitive_signal.py` — every sink rejection is now `SignalValidationError`, including a payload holding a non-JSON-serializable value (previously a raw `TypeError` leaked past the fail-closed contract); added `MAX_SINK_BYTES`, a whole-file ceiling checked under the lock, so unbounded sink growth is a structural refusal-to-write rather than a documented limitation; `Path.open()` in place of `open()`.
- `harness/shared/mango_mas_orchestrator.py` — guarded, observation-only shadow comparison hook after the incumbent planner call; disabled behavior byte-identical; minor ruff hygiene (`Path.open()`, unused loop variable).
- `harness/shared/tests/conftest.py` — autouse scrub of shadow-channel env vars keeps the mocked suite hermetic.
- `README.md` — documented the shadow-channel environment variables; refreshed the repository structure tree (10 skills, the live `pre-nemotron-run.sh` hook, `cognitive_signal.py`/`shadow_planner.py`/`schemas/`, `control-plane/publish_policy_artifact.py`); corrected stale test-count claims (575+ combined Python/Node, 486+ under `harness/shared/tests`).
- `NEXT_STEPS.md`, `NEXT_STEPS_PLAN_v2.md` — recorded the completed MangoMas integration core milestone and its follow-ups.
- `harness/docs/PRE_PR_VERIFICATION_REFERENCE.md` — coverage threshold description now points at the dynamic policy read instead of a hard-coded (and stale) percentage.
- `.mango/skills/evidence-signing/SKILL.md` — documented `publish_policy_artifact --attest` as a consumer.
- `.mango/skills/harness-engineering/SKILL.md` — corrected two references to a `.claude/` agent-state directory this repo does not use for that purpose.

### Fixed

- `docs/specs/SPEC_TEMPLATE.md` — added the `## Requirements` section `validate_specs.sh` requires; the template no longer fails the structural spec gate it scaffolds for.
- `harness/shared/tests/test_mango_mas_orchestrator.py` — removed a dead `pytest.importorskip("bash")` that silently skipped the hook execution test on every platform.
- `.gitignore` — `.governance/vitest-results.json` and `.governance/coverage/` were anchored to a repo-root `.governance/` that does not exist (git treats a mid-pattern slash as directory-relative), so `harness/node/.governance/vitest-results.json` and the coverage dir were never actually ignored; running the Node suite and checking `git status` surfaced it. Changed to `**/.governance/vitest-results.json` / `**/.governance/coverage/`, verified to still leave the tracked config files in the same directories (`policy.json`, `decision-log.md`, `traceability.json`, …) unignored.

## [2.1.7] - 2026-08-27

### Added

- `harness/shared/tests/test_validation_scripts_extra.py` — Added unit tests for governance validation scripts to ensure 80% coverage.
- `harness/shared/check_py_compat.py` — runtime Python 3.9 compatibility gate; detects PEP 604 unions and `datetime.UTC` without `from __future__ import annotations`. Now also covers `ast.AnnAssign` (module/class-level variable annotations).
- `harness/shared/check_dedup.py` — drift gate that fails CI when per-stack governance scripts are full copies instead of thin shims delegating to `harness/shared`.
- `harness/shared/governance/broker.py` — `ExecutionBroker` enforcing INV-8 (pretooluse_guard) and INV-9 (no host-process fallback). Paths extracted to module-level constants; structured `logging` throughout.
- `harness/shared/governance/evidence_manifest.py` — `EvidenceBuilder` refactored: `signing_key` now injectable via constructor (env-var fallback), raises `ValueError` (not `OSError`) for missing key, top-level imports, DEBUG logging on export.
- `harness/shared/tests/test_evidence_manifest.py` — 17-test suite covering key resolution priority, all `add_*` methods, HMAC signature verification, manifest immutability, and debug logging.
- `harness/shared/tests/test_governance_broker.py` — 11-test suite covering INV-8/INV-9, PDP allow/deny/absent, human-approved flag, logging, and `ExecutionResult` dataclass.
- `harness/shared/tests/test_mango_mas_orchestrator.py` — Platform-guarded bash hook tests (skip on Windows where bare `bash` cannot interpret Windows paths).
- `pyproject.toml` — Added `[project]` table and `[tool.setuptools.packages.find]` so `pip install -e .` resolves only `harness*` and does not fail with "Multiple top-level packages".
- `.gitignore` — Added `harness/node/test-*/` and `.hypothesis/` exclusions for pytest/hypothesis temp directories.

### Changed

- `harness/shared/validate_agent_policy.py`, `harness/shared/validate_policy.py`, `harness/shared/validate_governance_docs.py` — Refactored to use `main()` functions for importability and testability.
- `.github/workflows/python-package.yml` — Fixed misleading PEP 604 comment; null-guarded `ALLOW_GITHUB_CHANGES` against push events where `pull_request` context is absent.
- `harness/node/.npmrc`, `harness/node/pnpm-workspace.yaml` — Added the pnpm 11 esbuild build-script allowlist configuration.
- `Makefile` — `lint-python` now runs `ruff check .` (all first-party Python); `lint` depends on new `check-compat` target; `ci` depends on new `check-dedup` target; added `spec`, `review`, `pre-pr` targets.
- `harness/shared/governance-policy.json` — Updated `protected_paths` from stale `scripts/*` references to correct `harness/shared/*` layout; added `dedup` and `py_compat` policy sections.
- `harness/control-plane/policy-bundle.example.json` — Regenerated digests after governance script changes.

### Fixed

- `requirements-dev.txt` — Added `pytest-mock` to fix missing `mocker` fixture dependencies.
- `test_mango_mas_orchestrator.py` — Fixed missing mock usage in `test_live_execute_agent`.
- `test_validate_invariants.py::test_main_default_workspace_runs` — Made hermetic by patching `DEFAULT_WORKSPACE_DIR` to a temp repo instead of accepting any exit code from the real working tree.
- `governance/evidence_manifest.py` — Removed insecure HMAC fallback key (`"default-insecure-key"`); raises `ValueError` when `AGENT_EVIDENCE_KEY` is unset.
- `governance/broker.py` — Replaced f-strings in logger calls with lazy `%s` format; extracted hardcoded PDP/policy paths to module-level constants.

## [2.1.6] - 2026-08-26


### Added

- Created `.agents/skills/nemotron-reasoner/SKILL.md` exposing `nemotron_bridge.py` as an Antigravity & Agent framework reasoning skill.
- Added comprehensive live test resilience with graceful skip detection on remote NIM 404/410/429 status codes and diffusion model fallbacks.
- Added robust Mock Fallback logic in `mango-mas-e2e-live.test.ts` and `cli-live.test.ts` to ensure E2E pipelines pass deterministically during API flakiness.

### Changed

- Refactored `nemotron_bridge.py` and `main.py` to use structured Python standard `logging` via `harness/shared/logging.py` (JSONFormatter) for AI parsing compatibility.
- Updated `.gitignore` and `.dockerignore` to ignore `.gradle/`, `scratch/`, `.benchmarks/`, and ephemeral logs.
- Fortified `nemotron-client.test.ts` test isolation by replacing manual `process.env` mutation with `vi.stubEnv`.
- Updated `.gitleaks.toml` allowlist to protect test fixtures and mock API token patterns.

### Fixed

- Fixed ungraceful process exits in `test_nemotron_bridge.py` and converted to `pytest` `caplog` verification.
- Resolved race conditions in Vitest and Pytest test runners across live AI smoke tests.
- Re-established zero-unapproved-skip invariant compliance with full governance validator execution.

## [2.1.5] - 2026-08-25

### Added

- Created `.github/skills/code-review/SKILL.md` to document the code review skill process and testing criteria.

### Changed

- Refactored `mango_mas_orchestrator.py` to extract long prompt strings into named constants (`PLANNER_PROMPT_TEMPLATE`, `REASONER_PROMPT_TEMPLATE`, `VERIFIER_PROMPT_TEMPLATE`) to resolve Ruff E501 line-length violations.
- Fully typed `mango_mas_orchestrator.py`, `meta_tools.py`, and `nemotron_bridge.py` ensuring compliance with `mypy --strict`.
- Updated `.dockerignore` to explicitly ignore `.mango/` workspace directories.
- Minor cleanups in `check_traceability.py` to fix line-length linting errors.

### Fixed

- Fixed un-typed kwargs passing in `complete_chat` function invocation inside `mango_mas_orchestrator.py`.
- Fixed missing `typing` imports in `nemotron_bridge.py` and `meta_tools.py`.
- Ensure fail-closed governance models are strictly adhered to by properly propagating errors from the policy guard in `mango_mas_orchestrator.py`.
