# Spec: per-directory AGENTS.md documentation

## Problem statement

An agent editing `harness/shared/governance/` receives the root `CLAUDE.md` and a
38 KB `README.md`, and nothing local stating that the directory is a protected
path, that its import direction is AST-enforced, or that it may not import
`authority_graph.py`. Those facts exist in `harness/CONTRACT.md`,
`test_import_direction.py` and `governance-policy.json` — everywhere except
where the edit happens.

Evidence that instruction files drift without a gate: the 2026 standards audit
(M26) found `harness/node/Agent.md` claiming React/Vite/WebSocket scope over a
stack whose `package.json` declares none of them, alongside two further false
prose claims with no check behind any of them. Two `Agent.md` files existed, in
a filename no external tool reads and which Claude Code does not load. A
third-party measurement of the same failure mode (ContextCov, arXiv 2603.00822)
puts prose-only constraint compliance at 67.0% against 88.3% when the same
constraints are compiled into executable checks.

## Requirements

- R-ADOC-1: Each directory in the derived required set MUST carry a document
  named by `agents_doc.filename`, whose claims are checked against that
  directory's real contents.
- R-ADOC-2: The required set MUST be derived from the tree — every directory
  holding at least `agents_doc.min_source_files` first-party sources, minus
  `agents_doc.waived_directories`, plus `agents_doc.additional_directories` —
  never transcribed as a literal list, so a directory added later is caught.
- R-ADOC-3: Each document MUST ship beside a companion file named by
  `agents_doc.companion_filename` whose entire body is
  `agents_doc.companion_body`, because Claude Code reads `AGENTS.md` only where
  no `CLAUDE.md` sits at or above it and this repository has one at its root.
- R-ADOC-4: Every threshold MUST be sourced from the `agents_doc` block of
  `harness/shared/governance-policy.json` rather than a literal, under the
  precedence `explicit argument > environment > policy > built-in default`.
- R-ADOC-5: The gate MUST report the directory and the specific claim for every
  finding, so a failure names the fix rather than the symptom.
- C-ADOC-1: A policy that declares the `agents_doc` block MUST fail closed on a
  missing numeric key; a policy that does not declare the block at all MUST take
  the built-in defaults, so an adopter policy predating the block keeps working.
- C-ADOC-2: The change MUST NOT create any file under `.mango/agents/` or any
  `harness/*/agents/` directory, whose `*.md` namespace is the persona set that
  five existing assertions hold to an exact membership.
- C-ADOC-3: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`,
  and MUST NOT widen an existing gate's exclusion list to accommodate a document.
- C-ADOC-4: Document staleness MUST NOT block a pull request, because a
  time-based gate over many files turns CI red for changes that touch none of
  them; freshness is reported by the weekly drift workflow instead.

## Acceptance criteria

- [x] AC-1: Every directory in the required set carries both files — verified by
      `pytest harness/shared/tests/test_agents_doc.py -k test_every_required_directory_carries_a_document` · stage:
      `make ci` (R-ADOC-1, R-ADOC-3)
- [x] AC-2: A document naming a path that does not exist under its own directory
      is **rejected**, on the `**Scope:**` line and in the `## Key files` table —
      verified by `pytest harness/shared/tests/test_agents_doc.py -k "missing_path or does_not_exist or escaping_the_directory"` · stage:
      `make ci` (R-ADOC-1, R-ADOC-5)
- [x] AC-3: Deleting any one document **fails** `make ci` naming that directory,
      and a new source directory with no document and no waiver **fails** the
      same way — verified by `pytest harness/shared/tests/test_agents_doc.py -k TestAudit` · stage: `make ci` (R-ADOC-2)
- [x] AC-4: A declared policy block missing a numeric key **raises** `PolicyError`
      rather than substituting a default, and an undeclared block does not —
      verified by `pytest harness/shared/tests/test_agents_doc.py -k TestConfigResolution` · stage: `make ci` (C-ADOC-1)
- [x] AC-5: A companion file whose body is anything other than the configured
      import is **rejected** — verified by
      `pytest harness/shared/tests/test_agents_doc.py -k TestCompanionFindings` · stage: `make ci` (R-ADOC-3)
- [x] AC-6: A mermaid diagram opening with an unknown keyword, carrying an
      unbalanced quote or bracket, or declaring more than
      `agents_doc.max_diagram_nodes` nodes is **rejected**; diagrams also remain
      subject to the existing bare-bracket rule — verified by
      `pytest harness/shared/tests/test_agents_doc.py -k TestMermaidFindings` · stage: `make ci` (R-ADOC-1)
- [x] AC-7: A subagent definition whose frontmatter Claude Code would **silently
      skip** — no opening `---` on line 1, no `name`, a `name` containing `:`, or
      no `description` — is reported — verified by
      `pytest harness/shared/tests/test_agents_doc.py -k TestSubagentFindings` · stage: `make ci` (R-ADOC-5)
- [x] AC-8: An empty tree **fails** the population floor rather than passing
      vacuously — verified by
      `pytest harness/shared/tests/test_agents_doc.py -k test_the_population_floor_catches_a_vacuous_pass` · stage:
      `make ci` (R-ADOC-2)
- [x] AC-9: No file is added under `.mango/agents/` or `harness/*/agents/`, and
      the five persona-namespace assertions still pass unchanged — verified by
      `pytest harness/shared/tests/test_agent_harness_wiring.py
      harness/shared/tests/test_agent_surface_liveness.py
      harness/shared/tests/test_agent_surface_determinism.py
      harness/shared/tests/test_reasoner_bridge_tool_parity.py` · stage:
      `make ci` (C-ADOC-2, C-ADOC-3)
- [x] AC-10: New modules reach the per-file coverage floor from
      `governance-policy.json → coverage.lines` — verified by
      `make coverage-python` · stage: `make ci` (R-ADOC-4)
- [x] AC-11: A document whose `**Reviewed:**` date is older than
      `governance-policy.json → skill_max_age_days` does **not** fail `make ci`;
      a document with a missing or unparseable `**Reviewed:**` line does. The
      stale date is reported by the weekly drift workflow, which opens an issue
      and never blocks a pull request — verified by
      `pytest harness/shared/tests/test_agents_doc.py -k "reviewed"` and by `.github/workflows/scheduled-drift.yml`
      declaring no `pull_request` trigger · stage: `make ci` (C-ADOC-4)

## Steps

1. Add the `agents_doc` block to `harness/shared/governance-policy.json` —
   produces the thresholds R-ADOC-4 requires.
2. Write `harness/shared/agents_doc_policy.py` — consumes the block; produces
   `AgentsDocConfig` and `load_config` (R-ADOC-4, C-ADOC-1).
3. Write `harness/shared/agents_doc.py` — consumes `AgentsDocConfig`; produces
   discovery, parsing, the checks and a command-line entry point
   (R-ADOC-1, R-ADOC-2, R-ADOC-5).
4. Write `harness/shared/tests/test_agents_doc.py` — consumes both modules;
   produces the blocking gate and its positive controls (all AC).
5. Author one document and companion per required directory — consumes the
   `--directory` draft check; produces the documents (R-ADOC-1, R-ADOC-3).
6. Rename the three live `Agent.md` references and both existing files —
   produces a single filename across the tree (R-ADOC-1).
7. Add `.claude/agents/` subagents and `.claude/rules/` path-scoped rules —
   produces the authoring and audit path, and covers the `docs/` subtrees that
   cannot hold a document (R-ADOC-5, C-ADOC-2).
8. Extend the weekly drift workflow with a freshness report — produces a
   non-blocking staleness signal (C-ADOC-4).

## Files touched

Protected paths are marked; each needs an `infra-reviewed` attestation row.

- `harness/shared/agents_doc.py`, `harness/shared/agents_doc_policy.py`
- `harness/shared/tests/test_agents_doc.py`
- `harness/shared/governance-policy.json` **(protected)**
- `harness/shared/agent_prompts.py` **(protected)**
- `.mango/agents/nemotron-reasoner.md` **(protected)**
- `CLAUDE.md` **(protected)**
- `.github/workflows/scheduled-drift.yml` **(protected)**
- `harness/shared/governance/AGENTS.md`, `harness/shared/orchestrator/AGENTS.md`,
  `harness/shared/langgraph/AGENTS.md`, `.mango/skills/AGENTS.md`,
  `.mango/hooks/AGENTS.md` and their companions **(protected)**
- `harness/shared/tests/test_documentation_claims.py`
- `AGENTS.md` and `CLAUDE.md` in each remaining required directory
- `.claude/agents/directory-doc-author.md`,
  `.claude/agents/directory-doc-auditor.md`
- `.claude/rules/docs-specs.md`, `.claude/rules/docs-decisions.md`
- `docs/decisions/DEC-070.md` and the regenerated decision index
  **(`harness/node/.governance/decision-log.md` is protected)**

## Invariants touched

- INV-2: no test waiver or skip is added; the new suite runs unconditionally in
  `make ci` and carries no entry in `skip-waivers.json`.
- INV-6: the documents record what the gates already enforce; none of them
  grants authority, and none is described as preventing an off-policy action.
- No other invariant changes. `validate_invariants.py` proves the protected-path
  set still matches real files via `test_protected_path_liveness.py`, and
  `check_py_compat.py` proves both new modules import on the matrix floor.

## Validation matrix

- `make ci` — ruff + mypy + pytest + coverage (≥ `coverage.lines`) + check-dedup +
  validate_invariants, run with `ALLOW_GITHUB_CHANGES=1` for the protected paths
- `make lint-cold` — cold, non-incremental mypy as CI runs it
- `make pre-pr` — the above plus `review`, `audit` and `secrets`
- `python -m harness.shared.agents_doc --repo-root .` — the gate standalone
- coverage target: from `governance-policy.json → coverage.lines`, per-file
- mutation proof: each rule reintroduced as a defect, asserted to **fail**, then
  restored and asserted green, per the `gate-mutation-proof` skill

## Backward compatibility

Additive. No existing caller changes signature, and no threshold moves.

- An adopter policy with no `agents_doc` block keeps working: `load_config`
  returns built-in defaults rather than raising (C-ADOC-1), which is the DEC-043
  hazard `gate_floors` already guards against.
- `scope_names` and the `**Scope:**` pattern move from
  `test_documentation_claims.py` into `harness/shared/agents_doc.py` and are
  imported back. Behaviour is byte-identical; the module's 28 existing tests
  pass unchanged. A second copy would have been the shim-versus-copy drift
  `check_dedup` exists to refuse.
- `harness/node/Agent.md` and `harness/api_server/Agent.md` are renamed with
  `git mv`, so history follows. `harness/node`'s existing `**Scope:**` line is
  preserved byte-for-byte and remains under the stack-specific check in
  `test_documentation_claims.py`; technology names on a scope line stay outside
  the path-only rule, which has no manifest to resolve them against.
- No migration or removal release is required.

## Open questions

None blocking. One deferred, recorded in DEC-070: reconciling the README layout
tree against these documents. The tree stays canonical for this change, and the
`## Key files` cap of `agents_doc.max_key_files` keeps a document a summary
rather than a second copy of it.
