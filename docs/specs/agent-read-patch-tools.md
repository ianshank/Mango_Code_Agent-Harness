# Spec: agent-read-patch-tools

> Direct file read and in-place patch tools for the reasoner, and the read-side
> policy that keeps the new door no wider than the one it supplements.

## Problem statement

`nemotron-reasoner` can already read and write code, but only bluntly. Every read
goes `run_command("cat foo.py")` → `ExecutionBroker` → `ProcessBackend`, spawning a
subprocess to print a file. Every edit goes through `write_file`, which overwrites
whole files, so changing three lines means regenerating the file from the model's
context — the mechanism behind truncated and mangled large files.

Evidence, from the live authority model and classifier:

```
implementer actions: ['read', 'test_execute', 'write']
'cat harness/shared/tool_schemas.py' -> read           allowed=True
'cat .env'                           -> secret_access  allowed=False
'cat secrets.pem'                    -> secret_access  allowed=False
```

The second half of that evidence is the hazard. `command_actions.classify` grades a
credential read as `secret_access`, an action no role in `agent-policy.json` holds,
so `run_command("cat .env")` is denied for every agent. That grading is a property
of the *command*. A `read_file` tool resolves a path and reads it directly, so
nothing in `command_actions` sees it — and mapped to the `read` action the
implementer already holds, `read_file(".env")` would be *permitted* and would
return `NVIDIA_API_KEY` into `conversation_history`, which is sent to the model API
on the next turn and written to the debug dump.

There is a `write_policy.py` and no read-side counterpart. The tool cannot land
without one.

## Requirements

- R-RPT-1: `read_file` MUST return workspace file contents without spawning a
  subprocess, and MUST return them verbatim with no line-number prefixes, so the
  result is a valid `old_text` for `apply_patch`.
- R-RPT-2: `read_file` MUST deny credential-bearing paths, matched from a single
  shared pattern that `command_actions` also composes, so the two doors cannot
  drift apart.
- R-RPT-3: `read_file` MUST deny any path containing a `.git` segment, while
  leaving `.gitignore` and `.gitleaks.toml` readable.
- R-RPT-4: `read_file` output MUST be bounded by the same limit and carry the same
  truncation marker as brokered command output, sourced from
  `process_backend.DEFAULT_MAX_OUTPUT_BYTES` rather than a literal.
- R-RPT-5: `apply_patch` MUST refuse unless `old_text` matches exactly once, MUST
  report the observed count, and MUST leave the file unchanged when it refuses.
- R-RPT-6: `apply_patch` MUST evaluate `write_denial_reason` against its resolved
  target, so it reaches no path `write_file` cannot reach.
- R-RPT-7: `apply_patch` MUST preserve the file's existing line endings and its
  final-newline byte outside the replaced span.
- C-RPT-1: The change MUST NOT widen any role's authority; `agent-policy.json` is
  unchanged and `apply_patch` grades as the same `write` action as `write_file`.

## Acceptance criteria

- [ ] AC-1: `execute_read_file` returns file bytes with no `ProcessBackend` call and
      no header on a full read — `pytest -k test_reads_the_whole_file_verbatim`
      · stage: `make test-python` (R-RPT-1)
- [ ] AC-2: `read_file(".env")` returns a denial string and the secret does not
      appear in it, while the tool is permitted for the role —
      `pytest -k test_read_file_is_permitted_but_still_refuses_the_credential`
      · stage: `make test-python` (R-RPT-2)
- [ ] AC-3: every path `classify("cat <path>")` grades `secret_access` is denied by
      `read_denial_reason`, asserted as a property over a corpus that is checked to
      be non-vacuous — `pytest -k test_the_read_door_is_no_wider_than_the_command_door`
      · stage: `make test-python` (R-RPT-2)
- [ ] AC-4: `.git/config` is refused and `.gitignore` is not —
      `pytest -k TestGitDirectoryIsDenied` and `pytest -k test_ordinary_path_is_permitted`
      · stage: `make test-python` (R-RPT-3)
- [ ] AC-5: a file larger than `DEFAULT_MAX_OUTPUT_BYTES` comes back carrying
      `[truncated at N bytes]` — `pytest -k test_output_is_capped_and_marked`
      · stage: `make test-python` (R-RPT-4)
- [ ] AC-6: `apply_patch` with a doubled `old_text` reports `matched 2 times` and
      the file on disk is byte-identical afterwards —
      `pytest -k test_multiple_matches_are_refused_unchanged`
      · stage: `make test-python` (R-RPT-5)
- [ ] AC-7: `apply_patch` against `.mango/hooks/pre-nemotron-run.sh` fails with the
      protected-path reason — `pytest -k test_a_protected_path_is_refused`
      · stage: `make test-python` (R-RPT-6)
- [ ] AC-8: patching one word in a CRLF file leaves every other byte identical —
      `pytest -k test_crlf_line_endings_survive_a_patch`
      · stage: `make test-python` (R-RPT-7)
- [ ] AC-9: the verifier holds `read_file` and does not hold `apply_patch`, and
      `agent-policy.json` is unchanged in the diff —
      `pytest -k test_the_verifier_cannot_patch_files`
      · stage: `make test-governance` (C-RPT-1)
- [ ] AC-10: declared tools, `TOOL_REQUIRED_ACTION` and `_tool_handlers` remain
      three equal sets — `pytest -k test_every_declared_tool_has_a_required_action`
      and `pytest -k test_every_declared_tool_has_a_handler`
      · stage: `make test-governance` (R-RPT-1, R-RPT-6)

## Steps

1. Add the read policy — produces `harness/shared/read_policy.py` (R-RPT-2, R-RPT-3)
2. Point the command classifier at that pattern — consumes
   `harness/shared/read_policy.py`; produces the edit to
   `harness/shared/governance/command_actions.py` (R-RPT-2)
3. Add the executors — consumes `harness/shared/read_policy.py` and
   `harness/shared/write_policy.py`; produces `execute_read_file` and
   `execute_apply_patch` in `harness/shared/tool_executors.py`
   (R-RPT-1, R-RPT-4, R-RPT-5, R-RPT-6, R-RPT-7)
4. Declare the tools — produces the two entries in
   `harness/shared/tool_schemas.py` (R-RPT-1, R-RPT-5)
5. Map each to its action — produces the `TOOL_REQUIRED_ACTION` rows in
   `harness/shared/agent_authority.py` (C-RPT-1)
6. Register the handlers — consumes `harness/shared/tool_executors.py`; produces
   the `_tool_handlers` rows in `harness/shared/mango_mas_orchestrator.py` (C-RPT-1)
7. Tell the model the tools exist — produces the edits to
   `harness/shared/agent_prompts.py` and `.mango/agents/nemotron-reasoner.md`
   (R-RPT-1, R-RPT-5)
8. Register the new control as protected — produces the `protected_paths` entry in
   `harness/shared/governance-policy.json` (R-RPT-2)

## Files touched

- `harness/shared/read_policy.py` — new; protected once step 8 lands (R-RPT-2, R-RPT-3)
- `harness/shared/tool_executors.py` (R-RPT-1, R-RPT-4, R-RPT-5, R-RPT-6, R-RPT-7)
- `harness/shared/tool_schemas.py` (R-RPT-1, R-RPT-5)
- `harness/shared/governance/command_actions.py` — **protected** (R-RPT-2)
- `harness/shared/agent_authority.py` — **protected** (C-RPT-1)
- `harness/shared/mango_mas_orchestrator.py` — **protected** (C-RPT-1)
- `harness/shared/governance-policy.json` — **protected** (R-RPT-2)
- `.mango/agents/nemotron-reasoner.md` — **protected** (R-RPT-1, R-RPT-5)
- `harness/shared/agent_prompts.py` (R-RPT-1, R-RPT-5)
- `harness/shared/tests/test_read_policy.py` — new (R-RPT-2, R-RPT-3)
- `harness/shared/tests/test_tool_executors.py` — new (R-RPT-1, R-RPT-4, R-RPT-5, R-RPT-7)
- `harness/shared/tests/regression/test_read_containment_regression.py` — new (R-RPT-2)
- `harness/shared/tests/test_agent_authority.py` (C-RPT-1)
- `harness/shared/tests/test_documentation_truth.py`
- `.env.example`
- `CHANGELOG.md`

The five protected paths carry the `infra-reviewed` attestation in the pull request
description, produced by the `protected-path-attestation` skill.

## Invariants touched

- INV-8: preserved and untouched. INV-8 governs *execution* through the approved
  broker; a file read is not execution, and `execute_write_file` already writes
  outside the broker. `apply_patch` sits at exact parity with `write_file` and
  opens no new bypass — `run_command` remains the only path that runs anything.
- INV-7: unchanged. `evidence_required_for` names `write`, which `apply_patch`
  takes, and the evidence clause of INV-7 is recorded in `harness/CONTRACT.md` as
  not yet enforced. `apply_patch` inherits `write_file`'s posture exactly; this
  change neither closes that gap nor widens it.
- INV-17: this document is subject to it. `validate_plan.py` runs over specs git
  reports as modified, so the plan gate grades these criteria.

## Validation matrix

- `make test-python` — the executor, policy and regression suites (AC-1 … AC-8)
- `make test-governance` — authority and wiring pins (AC-9, AC-10)
- `make specs` — the plan gate over this document (INV-17)
- `make coverage` — per-file floor from `governance-policy.json → coverage.lines`
- `ALLOW_GITHUB_CHANGES=1 make validate` — protected paths, with the attestation
- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — the full gate

## Backward compatibility

Additive. `write_file` and `run_command` keep their signatures, their handler
names and their error strings; `test_command_actions.py` and
`test_write_policy.py` pass unmodified, which is the evidence the classifier
refactor changed no verdict. No role gains an action, so an adopter who does not
update `.mango/agents/` sees the two new tools offered and unused rather than a
behaviour change.

`execute_write_file` keeps universal-newline semantics rather than adopting
`newline=""`. It replaces whole files, so it has no surrounding content to
preserve, and changing it would alter existing behaviour for no requirement here.

## Open questions

None blocking. One follow-up is recorded rather than resolved: `read_file` and
`write_file` disagree on newline handling, as the note above explains. Unifying
them belongs with the INV-7 evidence work, not here.
