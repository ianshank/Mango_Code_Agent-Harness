# Spec: code-generation-tool

> **Status:** DRAFT, revision 1. Contract for the dedicated code generation writing tool (`generate_code`),
> providing syntax-validated code generation, workspace confinement, write policy integration,
> and dynamic configuration without hard-coded limits.

## Problem statement

The reasoner currently edits and creates files using `write_file` (raw string overwrite) and
`apply_patch` (substring replacement). When generating code:
1. `write_file` performs no language or syntax validation; a model generating syntactically
   invalid code (e.g., Python code with unmatched brackets or syntax errors) writes it directly
   to disk, leaving broken files that fail subsequent test executions and require expensive
   multi-turn repair cycles.
2. `write_file` provides no structured code generation capabilities (such as AST validation,
   language auto-detection, formatting normalization, or dry-run validation).
3. Writing operations need a unified governance approach where code generation adheres to the
   same workspace confinement (`_resolve_in_workspace`), policy decision point (`authorize_write`),
   and write denial rules (`write_denial_reason`, including the `.mango/memory/` denial established
   in `docs/specs/agent-memory-integrity.md`).

## Requirements

- R-CGT-1: The orchestrator MUST advertise the `generate_code` function in `NEMOTRON_TOOLS`
  (`harness/shared/tool_schemas.py`) with parameters: `filepath` (string, required), `code`
  (string, required), and optional parameters: `language` (string, optional), `validate_syntax`
  (boolean, optional, default True), and `overwrite` (boolean, optional, default True).
- R-CGT-2: `execute_generate_code` in `harness/shared/tool_executors.py` MUST enforce workspace
  confinement via `_resolve_in_workspace` and write policy via `write_denial_reason(..., policy_path=active_policy_path())`,
  denying attempts that escape the workspace, target protected paths, target credential filenames,
  or target `.mango/memory/`.
- R-CGT-3: `generate_code` MUST require the `write` action via `agent_authority.TOOL_REQUIRED_ACTION`
  and MUST be authorized by `authorize_write` before execution.
- R-CGT-4: When `validate_syntax` is True and the file type is supported (e.g., `.py` or `.pyw` for
  Python, `.json` for JSON), `execute_generate_code` MUST validate the syntax (e.g. via `ast.parse`
  for Python or `json.loads` for JSON) before writing to disk. Python targets are always parsed so
  prohibited-symbol checks cannot be bypassed; `validate_syntax` controls whether syntax errors are
  reported. If syntax validation fails, the tool MUST refuse to write to disk and MUST return an error
  detailing the syntax error location and message.
- R-CGT-5: When `overwrite` is False and the destination file already exists, `execute_generate_code`
  MUST refuse to overwrite and MUST return an error indicating the file exists.
- R-CGT-6: Output lengths and file size bounds MUST derive from `governance-policy.json` or
  `DEFAULT_MAX_OUTPUT_BYTES` rather than hard-coded numeric literals.
- R-CGT-7: All tool operations (successes, denials, syntax errors, I/O errors) MUST emit structured
  logging (`logger.info`, `logger.warning`, `logger.exception`) with operation context.
- C-CGT-1: The tool MUST NOT widen any agent role's authority in `agent-policy.json`; it is
  accessible only to roles holding the `write` action (`implementer` / `nemotron-reasoner`).
- C-CGT-2: Existing tools (`write_file`, `apply_patch`, `read_file`, `run_command`) MUST remain
  unaltered in interface and backward-compatible.

## Acceptance criteria

- [x] AC-CGT-1: `execute_generate_code` writes valid Python code to a workspace file and returns a success
      message naming the character count and resolved path, with structured logging emitted —
      verified by `pytest -k test_generate_code_writes_valid_python`
      · stage: `make test-python` (R-CGT-1, R-CGT-6, R-CGT-7)
- [x] AC-CGT-2: `execute_generate_code` with syntactically invalid Python (e.g. `def broken(:`) refuses
      to write to disk, leaves any pre-existing file untouched, and returns a detailed syntax error message —
      verified by `pytest -k test_generate_code_syntax_error_refuses_write`
      · stage: `make test-python` (R-CGT-4)
- [x] AC-CGT-3: `execute_generate_code` targeting `.mango/memory/hypotheses.json` or a protected path
      returns a denial string from `write_denial_reason` and writes zero bytes to disk —
      verified by `pytest -k test_generate_code_denied_on_governed_paths`
      · stage: `make test-python` (R-CGT-2)
- [x] AC-CGT-4: `execute_generate_code` with `overwrite=False` against an existing file refuses
      to overwrite and returns a file-already-exists error — verified by `pytest -k test_generate_code_refuses_overwrite_when_false`
      · stage: `make test-python` (R-CGT-5)
- [x] AC-CGT-5: `execute_generate_code` with a path escaping workspace (e.g. `../../etc/passwd`)
      fails closed with confinement denial — verified by `pytest -k test_generate_code_confinement_denial`
      · stage: `make test-python` (R-CGT-2)
- [x] AC-CGT-6: Calling `generate_code` with a role lacking the `write` action (e.g. `planner` or `verifier`)
      is refused by `authorize_write` — verified by `pytest -k test_generate_code_requires_write_authority`
      · stage: `make test-python` (R-CGT-3, C-CGT-1)
- [x] AC-CGT-7: Existing `write_file` and `apply_patch` tests continue to pass unmodified —
      verified by `pytest harness/shared/tests/test_write_policy.py harness/shared/tests/test_tool_executors.py`
      · stage: `make test-python` (C-CGT-2)

## Steps

1. Scaffold and validate spec — produces `docs/specs/code-generation-tool.md` (R-CGT-1).
2. Schema & Authority declaration — update `harness/shared/tool_schemas.py` to add `generate_code`
   and `harness/shared/agent_authority.py` to map `generate_code` to `write` (R-CGT-1, R-CGT-3, C-CGT-1).
3. Tool implementation — add `execute_generate_code` to `harness/shared/tool_executors.py` with
   syntax validation, confinement, and write policy checks (R-CGT-2, R-CGT-4, R-CGT-5, R-CGT-6, R-CGT-7).
4. Dispatcher integration — wire `generate_code` into `ToolDispatcher` in `harness/shared/mango_mas_orchestrator.py`
   and the local tool handlers (R-CGT-1, R-CGT-3).
5. Unit and integration tests — implement comprehensive test suite in `harness/shared/tests/test_code_generation_tool.py`
   and update `test_tool_executors.py` (AC-CGT-1..AC-CGT-7).
6. Memory integrity verification — confirm `generate_code` is denied by `write_denial_reason` for `.mango/memory/`
   paths alongside `write_file` and `apply_patch` (R-CGT-2, AC-CGT-3).
7. Validation matrix — run `make specs`, `make test-python`, `make coverage`, and `make ci`.

## Files touched

- `docs/specs/code-generation-tool.md` (this spec)
- `harness/shared/tool_schemas.py`
- `harness/shared/tool_executors.py`
- `harness/shared/agent_authority.py`
- `harness/shared/mango_mas_orchestrator.py`
- `harness/shared/tests/test_code_generation_tool.py`
- `NEXT_STEPS.md`
- `docs/specs/agent-memory-integrity.md`

## Invariants touched

- INV-8: Broker execution containment preserved (all writes go through policy decision points).
- INV-9: Sandbox and execution bounds preserved.
- INV-10: Pretooluse checks preserved.

## Validation matrix

- `make specs` — validates spec structural and plan integrity rules.
- `make test-python` — runs Python test suite including new tests for `generate_code`.
- `make coverage` — enforces coverage threshold from `governance-policy.json`.
- `make ci` — full CI gate.

## Backward compatibility

Fully backward-compatible. `generate_code` is an additive tool. `write_file` and `apply_patch`
remain untouched and fully operational. No existing tool signatures or behaviors are altered.

## Open questions

None. The syntax validation approach leverages standard library `ast` and `json` parsers,
preventing external dependency drift.
