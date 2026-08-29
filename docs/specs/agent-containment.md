# Spec: Agent containment — reaching the constraint layer on the live path

> **Programme:** runtime containment of the MAS orchestrator's tool surface.
> **Protected-path status:** every PR in this spec is labelled (`infra-reviewed`);
> the guard, the policies, the decision log and the agent personas are all
> protected paths.
> **Provenance:** peer-reviewed before implementation by the Architecture, QA,
> Security and SDLC/Product personas of `openspec-peer-review`, plus a
> sandbox-viability design review. All five rejected the two preceding drafts;
> the findings below are the surviving design.

## Problem statement

The repository declares a complete authority model and does not consult it on the
path that executes model-authored code. Each item is a reproduction, not a reading.

- The agent's workspace is the repository root — `harness/api_server/main.py:85`
  constructs `MangoMASOrchestrator(workspace_dir=PROJECT_ROOT)`. `write_file` is
  correctly confined to the workspace, and the workspace contains the guard, the
  policy decision point, the hooks the orchestrator executes on the host, the
  agent personas, and `.git/`.
- `protected_paths` is consulted only by the CI gate. Evidence: the sole non-test
  readers of `validate_invariants.is_protected` are `validate_invariants.py` and
  `validate_policy.py`. `agent-policy.json` declares `self_modify_policy: false`
  and `validate_agent_policy.py:52` asserts only that the literal is `false`.
- The orchestrator's guard call cannot block. It sends
  `{"tool": ..., "args": {"command": ...}}` (`mango_mas_orchestrator.py:211`)
  while `governance/pretooluse_guard.py:194` reads `tool_input.command`, so the
  guard evaluates an empty string. Reproduced: a `git push` to an arbitrary
  remote exits 0 through the orchestrator's payload shape.
- The guard is loaded from `workspace_dir` (`:209`) and skipped when absent — the
  comment at `:227` records the fail-open as intended behaviour.
- `_run_hook:165-179` executes `bash <script>` with no guard call and
  `env=os.environ.copy()`, carrying `NVIDIA_API_KEY`, `AGENT_EVIDENCE_KEY` and
  `API_SERVER_KEY`. Three of the four hook names it will run do not exist, so
  `write_file` can create one.
- The verifier role receives `write_file`: `:408` passes no `tools=`, defaulting
  to the implementer tool set. The four canonical contracts it maps to each deny
  implementation changes; `peer-reviewer.md:5` denies "changing the
  implementation being judged".
- Credentials leak through the HTTP response. `debug_dump.py:39` scrubs only
  `NVIDIA_API_KEY` by value and the `nvapi-` shape, while `main.py:96` returns the
  conversation history. `AGENT_EVIDENCE_KEY` is the HMAC key `EvidenceBuilder`
  signs with, so its disclosure permits forged evidence manifests.
- `ExecutionBroker` has no production caller and ends at
  `FAILED: Execution engine not fully implemented`, so INV-8 has no enforcement
  on any live path.

## Requirements

- R-AC-1: The orchestrator MUST send the guard the envelope shape the guard
  parses, expressed as one shared constant rather than restated at the call site.
- R-AC-2: The guard MUST be resolved from the installed harness package, never
  from a path under `workspace_dir`.
- R-AC-3: Guard unavailability MUST deny. Absence, import failure, or an
  evaluation error returns a blocked result rather than executing the command.
- R-AC-4: A guard payload that parses to a JSON object carrying no recognised
  command-bearing key MUST exit with the PreToolUse block code, sourced from a
  named constant rather than a literal at each return.
- C-AC-1: Guard input that does not parse as JSON MUST retain its present
  behaviour, so the existing hook contract and its test are preserved.
- R-AC-5: The guard MUST emit structured diagnostics on stderr through
  `json_logging.configure_gate_logging`, keeping stdout reserved for the verdict.
- R-AC-6: `_execute_write_file` MUST refuse a write whose resolved
  workspace-relative path matches `protected_paths`, evaluated at tool-call time
  and sourced from `governance-policy.json`.
- R-AC-7: `_execute_write_file` MUST refuse any path under the repository's git
  directory, which `protected_paths` cannot match because git never lists it.
- R-AC-8: Tool exposure MUST be derived per active role from `agent-policy.json`
  and the active-to-canonical role mapping, so no role receives an action its
  canonical contracts deny.
- R-AC-9: `_run_hook` MUST execute only a git-tracked hook whose name is in a
  declared set, with an environment filtered of credentials.
- R-AC-10: The redactor MUST cover every environment variable whose name marks it
  as a credential, and its shape patterns MUST be sourced from the same
  configuration the secret scanner reads.
- R-AC-11: `ExecutionBroker.execute_command` MUST accept the working directory and
  timeout the orchestrator is bound by, sourced from the policy `orchestrator`
  block rather than re-declared.
- R-AC-12: Execution routing MUST be selected by a policy value whose only legal
  states are brokered execution and refusal, so a degraded state cannot become
  host execution.
- C-AC-2: No requirement here MUST be satisfied by a literal value that
  `governance-policy.json` or `agent-policy.json` already declares.
- C-AC-3: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`, and
  MUST NOT introduce a waiver for an invariant the same change could enforce.

## Acceptance criteria

- [x] AC-1: The historical orchestrator envelope (`{"tool": …, "args": {"command": …}}`),
      fed to the guard, exits with the block code instead of exiting 0 (R-AC-1).
      *Restated:* the orchestrator no longer constructs a payload at all —
      `_execute_run_command` routes through `ExecutionBroker`, which calls
      `check_command` as a Python function — so the envelope fix is pinned at the
      guard boundary, where it holds for every caller rather than for one. Verified
      by `make test-regression`
      (`test_the_orchestrators_historical_payload_is_no_longer_a_silent_allow`).
- [x] AC-2: A command the *policy* allows is still refused by the guard, so the
      guard is proven to be on the path rather than shadowed by an earlier policy
      denial (R-AC-1, R-AC-3). *Restated:* the original wording required a block
      "for a reason that is not allowlist unavailability", and DEC-005 settled that
      allowlist unavailability **is** the accepted reason an agent `git push`
      blocks — creating a root `.governance/` was rejected because the pattern is
      declared dormant. As written the criterion could only be met by undoing a
      recorded decision. Verified by `make test-regression`
      (`TestTheCommandGuardIsOnThePath`).
- [x] AC-3: An orchestrator whose workspace contains no guard file denies the
      command instead of running it (R-AC-2, R-AC-3) — verified by `make test-python`
      (`test_dangerous_command_never_reaches_the_shell`; the fixture workspace is a
      bare temp directory with no guard).
- [x] AC-4: A guard payload of `{"unexpected": {}}` exits with the block code,
      while non-JSON input retains its prior exit status (R-AC-4, C-AC-1) —
      verified by `make test-python`.
- [x] AC-5: A `write_file` targeting `.mango/hooks/pre-nemotron-run.sh`, the
      policy decision point, `governance-policy.json` and `.git/config` is refused,
      and a hook created during a run is never executed (R-AC-6, R-AC-7, R-AC-9) —
      verified by `make test-regression`. The second half is now enforced as well
      as asserted: `_run_hook` refuses any name outside `PERMITTED_HOOK_NAMES`,
      derived from `ACTIVE_TO_CANONICAL`.
- [x] AC-6: The tool schema offered to the verifier role excludes the file-write
      tool, derived from policy rather than asserted (R-AC-8) — verified by
      `make test-python`. **The schema was not sufficient:** `_dispatch_tool_calls`
      looked handlers up by name with no reference to the filtered list, so a model
      naming `write_file` anyway got it. `agent_authority.tool_is_permitted` now
      answers the same question at dispatch
      (`TestToolAuthorityIsEnforcedAtDispatchNotOnlyInTheSchema`).
- [x] AC-7: A conversation history containing the evidence signing key and the API
      server key returns both redacted (R-AC-10) — verified by `make test-python`.
      Extended: brokered commands no longer inherit either variable, so
      `cat /proc/self/environ` cannot return what `redact_history` would have
      caught only at the HTTP boundary.
- [x] AC-8: Every declared invariant naming an enforcement mechanism resolves to a
      caller on a live path, with no dormancy waiver present (C-AC-3) — verified by
      `pytest -m governance` (`test_invariant_liveness.py`, `DORMANT_INVARIANTS = {}`).
- [x] AC-9: Every gate introduced by this spec reports a mutation kill count in its
      pull request description — verified by review. Counts recorded: guard
      envelope 3/3, invariant liveness 3/3, guard destination timeout 8/8, hook-name
      allowlist 5/5, containment bypasses 14/14, availability probe 4/4,
      `.dockerignore` liveness 3/3.
- [x] AC-10: `make ci` passes on every leg of the CI matrix (C-AC-2, C-AC-3).
      `ALLOW_GITHUB_CHANGES=1 make pre-pr` (which runs `make ci`) exits 0 locally:
      1633 Python and 46 Node tests, lines 97.97%, branches 94.38%, per-file 40/40.
      **On CI the three `build (3.x)` legs and `build-full` are red on the
      protected-path gate**, which is the designed behaviour until a human applies
      the `infra-reviewed` label; `secret-scan` is green. Not tickable by the author
      of the change — that is the point of the gate.

## Invariants touched

- INV-1: strengthened. The redactor gains coverage of the remaining credential
  environment variables and sources its shapes from the secret-scanner config, so
  the two cannot drift. Verified by AC-7.
- INV-7: strengthened. Delegation stops transferring authority in practice: role
  tool exposure is derived from the policy that declares each role's actions.
  Verified by AC-6.
- INV-8: reached. Generated code executes through the broker once routing lands,
  and the liveness gate ships with no waiver. Verified by AC-8.
- INV-9: preserved and made reachable. Guard and broker unavailability deny rather
  than falling back to host execution. Verified by AC-3 and AC-4.
- INV-16: unaffected. No envelope field reaches a control path; role tool exposure
  is derived from committed policy, never from model output or a signal payload.
  Verified by the boundary suite.
- Size budget (`limits.size_budget_lines`): new logic lands in new modules rather
  than growing the orchestrator, which sits close to the budget.

## Validation matrix

| Stage | Command | Pass criteria |
|---|---|---|
| Lint and types | `make lint` | ruff, mypy `--check-untyped-defs`, Python compatibility gate clean |
| Regression tier | `make test-regression` | AC-1, AC-2, AC-5 pass; each confirmed failing against the pre-fix commit |
| Governance suite | `pytest -m governance` | AC-8 passes; policy consistency and protected-path liveness stay green |
| Coverage | `make coverage` | aggregate and per-file floors from `governance-policy.json → coverage` |
| Full pipeline | `make ci` | every stage green on the CI matrix |
| Pre-submission | `make pre-pr` | full CI plus the mechanical review checklist |

Thresholds are read from `harness/shared/governance-policy.json`; no value is
restated here.

## Backward compatibility

- `NEMOTRON_TOOLS` remains exported and remains the implementer tool set, so any
  caller importing it is unaffected. Role scoping narrows what the orchestrator
  offers per role; it does not change the exported constant.
- `ExecutionBroker(sandbox_available=...)` is retained as a keyword argument whose
  permissive default is removed. The constructor form that passes an explicit
  backend is additive.
- `execute_command` gains working-directory and timeout parameters with defaults
  drawn from policy, so existing two-argument callers keep their behaviour.
- The guard's exported names are unchanged; `check_command` becomes importable
  without altering the existing shim's re-exports.
- Relocating the agent workspace changes where generated files land. The prior
  location is the repository root, which no consumer depends on for output.

## Open questions

1. **Resolved — DEC-005.** Agent-initiated `git push` blocks once the envelope is
   corrected, because the repository root carries no remote allowlist and the
   guard fails closed on the missing file. The block is **accepted as policy**.
   Creating a root allowlist directory was excluded: that pattern is declared
   dormant and waking it fails
   `test_protected_path_liveness.py::test_dormant_patterns_are_still_dormant`.
   `TestTheCommandGuardIsOnThePath` pins that the guard, not only the policy
   decision point, is what refuses it — so the block cannot silently become a
   policy denial that would still hold if the guard were removed.
2. **Resolved — DEC-011.** Adding the active roles to `agent-policy.json` would
   give the agent's own governing policy an execution grant, and trips the
   bidirectional role-to-contract equality tests. Resolved without touching the
   policy: `agent_authority.EXECUTION_IDENTITY` maps each active role to the
   *narrowest canonical contract that covers its work* — `planner` →
   `orchestrator`, `nemotron-reasoner` → `implementer`, `verifier` → `test-eval`
   — and `test_execution_identity_is_no_wider_than_the_role` pins that the
   mapping never grants more than the role's own derived authority. An unmapped
   role is denied as an unknown identity.
3. **Still open.** Requirement identifiers in the root spec directory are traced
   by nothing: `check_traceability` runs from the Node stack and its globs reach
   two specs, discovering six requirement IDs — none of them this spec's. Either
   widen the configuration or declare the gap. It is currently declared in prose
   (`README.md`) with no gate behind the declaration, which is the same
   "documented, therefore handled" shape this spec exists to argue against.
   Blocks AC-9's traceability claim, not the implementation.
