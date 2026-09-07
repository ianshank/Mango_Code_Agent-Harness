# Spec: graph-engineering adoption

> **Status:** DRAFT, revision 1. Contract for adopting graph representations of this
> repository's governance chain, generated code, and orchestration topology, as reviewed in
> [`docs/reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md`](../reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md).
> Every design decision below is argued **Thesis → Counter-Argument → Rebuttal**, where the
> rebuttal is required to introduce a third position rather than restate the thesis.

## Problem statement

Three defects, each evidenced against `main` @ `3fc9c3e`:

1. **A governance gate checks a corpus it was not meant to check.**
   `check_traceability.py:25` reads `TRACEABILITY_CONFIG = Path(".governance/traceability.json")`
   relative to the CWD, and `Makefile:255` runs it from `harness/node`. The globs therefore
   resolve to `harness/node/docs/specs/**`. Measured: the gate reads 6 requirement IDs; the
   real corpus at `docs/specs/` holds 380 more, and the two sets are disjoint. `make validate`
   prints `traceability: passed (6 requirements)` and exits 0.

2. **The authorization chain's safety property is argued, not checked.** The chain
   `@with_authority` (`langgraph/nodes.py:89,143,204`) → `ACTIVE_TO_CANONICAL`
   (`agent_authority.py:34`) → `allowed_actions` (`:93`) → `TOOL_REQUIRED_ACTION` (`:60`) →
   `write_policy` / `read_policy` / `command_actions` decides every side effect the harness
   permits. `agent-policy.json` declares `default_deny: true` and five `high_risk_actions`.
   The existing tests assert endpoint outcomes for named roles and named tools; no check
   states the general property that no active role reaches a high-risk action by any
   composition of those edges. DEC-008 and DEC-012 answer that question in prose.

3. **Generated code is validated for syntax and then the analysis is discarded.**
   `execute_generate_code` (`tool_executors.py:144`) parses every generated Python file with
   `ast.parse` to answer "does it parse", then writes. `governance-policy.json` declares
   `synthesis.prohibited_imports` (5 entries) which that AST could decide before bytes reach
   disk, and which nothing checks at the write door.

The three-model report reviewed in the companion document proposes graph engineering as the
remedy for a superset of these. This spec adopts the parts that survive review and states, for
each, the argument against it and the reason the argument does not carry.

## Design dialectic

### D-1 · Which graph first

**Thesis.** Start with static verification of the LangGraph `StateGraph`, as all three models
recommended. The topology is small, the checks are linear, the defect class is real —
`peer_reviewer` and `security_reviewer` are registered with no edges, so the `findings` channel
is empty on every run, and `test_langgraph_graph.py:341` asserts the node *set*, which both
orphans satisfy. The behavioural suite pins the defect rather than catching it.

**Counter-Argument.** `DEC-053` is accepted and parks `harness/shared/langgraph/` under
`harness/shared/experimental/`. It considered "promote LangGraph to the live runtime" as option
(A) and rejected it, naming as the cost "an optional extra, coverage carve-outs, deselection
env, and protected-path attestation on every PR". The only caller of `build_graph` outside tests
is `harness/shared/experimental/autonomous_healing.py`; the live runtime is the sequential
`ExecutionLoop` (`orchestrator/loop.py:38`). A new fail-closed CI invariant over parked code
adds a required check, a `CONTRACT.md` row, and three protected-path attestations to a subsystem
with a named sunset — and the 3.9 CI leg sets `MANGO_CI_DESELECT_LANGGRAPH: 1`, so the check
would be absent on the oldest supported interpreter.

**Rebuttal (third position).** Both arguments assume the deliverable is "a LangGraph checker",
and it is not. The property worth having — *every path from entry to a write-capable node
traverses a gate* — is not LangGraph-shaped; it is a statement about the authorization chain,
which is live, unparked, present on all three interpreters, and imported by the broker on every
tool call. Building it there yields the same theorem over code that is not scheduled for
deletion, and if NS-31 later revives LangGraph the same path-checking primitive re-points at the
compiled topology for the cost of a second extractor. The disagreement dissolves once the
deliverable is named as *reachability over a governance graph* rather than *a graph framework
linter*. **Resolution: R-GEA-2 first; LangGraph topology becomes R-GEA-6, gated on NS-31.**

### D-2 · What substrate

**Thesis.** Use an embedded property graph with a real query language (the report's Nemotron
position). Reachability, path enumeration, and community detection are one Cypher statement
each, and hand-rolling them means writing and testing graph algorithms instead of governance
logic.

**Counter-Argument.** Every dependency here is a lock entry in a 240 KB hashed
`requirements-lock.txt` behind a `lock-check` gate, an `audit` surface, and a `check_py_compat`
risk against a 3.9 floor. `import networkx` fails in this checkout and networkx is in no
requirements file, so even the report's "no new dependency beyond NetworkX" is a new dependency.
Kùzu, the obvious embedded choice, was archived in October 2025. A new module must additionally
carry ≥90% line and ≥80% branch coverage *on its own file* (`coverage.per_file: true`) and stay
under `limits.size_budget_lines`.

**Rebuttal (third position).** The substrate question is downstream of a question neither side
asked: *does anything need to be stored?* The authorization graph is small — 3 active roles, 7
canonical roles, 7 tools, ~10 actions — and it is **derived**, not observed: it is a pure
function of `agent-policy.json` and three mappings in `agent_authority.py`. A persisted graph of
derived data is a cache, and a cache of governance state is a staleness bug with a security
consequence: the stored graph says one thing while the broker enforces another. So the right
answer is neither "a graph database" nor "NetworkX" but **no store at all** — recompute the
graph in-process from the same functions the broker calls, on every run. That also satisfies the
Architect's boundary objection, since a recomputed graph cannot become a dependency of the
governance layer. Storage becomes a live question only for the code graph (R-GEA-5), which
*is* observed data over 278 files, and is deferred behind a measurement.

### D-3 · Whether the code graph earns its place

**Thesis.** Build the read-only code graph and expose `trace_call_path`, `detect_changes`, and
`get_architecture` over `mcp_server.py`. The cited benchmark is 10× fewer tokens and 2.1× fewer
tool calls; the subagents here re-derive repository structure every turn.

**Counter-Argument.** The benchmark is someone else's corpus. `CLAUDE.md` states the rule this
repository applies to its own claims — *"A verification claim is not evidence"* — and an
imported benchmark is a claim. This corpus is 278 Python files; a 10× reduction measured on a
larger one is not transferable, and the honest prior is that the gain shrinks with corpus size.
Adopting first and measuring later is precisely the DEC-024 shape.

**Rebuttal (third position).** The disagreement is about *adoption*, and the actual first move
is neither adopt nor decline: it is to make the measurement itself a deliverable. Neither side
can name the current tokens-per-turn figure, because nothing records it — so the argument is
being had without the number that settles it. R-GEA-5 therefore ships a baseline harness before
any graph, and makes adoption conditional on a threshold read from `governance-policy.json`
rather than from the paper. If the measured reduction misses the threshold, the correct outcome
is that the code graph is not built, and that outcome is a success of the process rather than a
failure of the plan.

### D-4 · Where code generation meets the graph

**Thesis.** Code generation is downstream of the graph: generate, then analyse, then repair on
the next cycle. `synthesis.max_repair_cycles: 3` already budgets that loop.

**Counter-Argument.** Post-hoc analysis means the defect is already on disk. `execute_generate_code`
already refuses to write syntactically invalid code — the file never exists — and that is
strictly cheaper than writing, running `make ci`, reading a failure, and spending a repair cycle.
Analysis that runs after the write has given up the tool's main advantage.

**Rebuttal (third position).** Both positions treat the AST as something to be *acquired*. It is
already in hand and thrown away: `_validate_code_syntax` parses the module, checks that parsing
succeeded, and returns a string. The question is not when to analyse but **what to ask the parse
tree that is already there** — and the answer is bounded by what can be decided from a single
module without whole-program context: declared imports against `synthesis.prohibited_imports`,
and new edges into modules the caller may not write. Anything needing cross-module resolution
(does this symbol exist, is this call reachable) belongs to R-GEA-5's corpus graph and must not
be smuggled into the write door, because a write door that needs a repository-wide index is a
write door that fails when the index is stale. **Resolution: R-GEA-3 is scoped to
single-module decidable checks, and says so as a constraint (C-GEA-3).**

### D-5 · Whether to add a CI gate at all

**Thesis.** Each check becomes a `make` target wired into `make ci`, matching how every other
invariant here is enforced (INV-5: every `ci_required_target` reachable from `make ci`).

**Counter-Argument.** `ci_required_targets` has ten entries and `pre_pr_order` eleven stages.
Each addition costs a policy entry, a `harness/CONTRACT.md` row, a `test_ci_gate_coverage.py`
update, and protected-path attestation on `Makefile`, `governance-policy.json`, and
`harness/CONTRACT.md` — three attestations per gate. The marginal gate is not free and the
report priced none of this.

**Rebuttal (third position).** The premise that each check needs its own gate is wrong on this
repository's own evidence: `validate_invariants.py` already carries four unrelated invariants
behind one `make validate` entry, and `test_constant_triage.py` enforces a repository-wide
property from inside the ordinary pytest run with no target of its own. So the choice is not
"gate or no gate" but *which enforcement surface*. Checks that are pure functions over
repository state belong in the test suite, where they cost nothing new and inherit INV-2's
zero-skip discipline; only checks that must run outside pytest — because they shell out, or
because an operator needs to run them alone — earn a target. On that rule R-GEA-1 and R-GEA-2
are tests, R-GEA-3 is a code path in an existing tool, and no new `ci_required_target` is
proposed by this spec at all.

## Requirements

- R-GEA-1: `check_traceability.py` MUST resolve its configuration and globs against an explicit
  workspace root rather than the process CWD, defaulting to the repository root, so that the
  requirement IDs it reads are the corpus under `docs/specs/` and not `harness/node/docs/specs/`.
- R-GEA-2: A new module `harness/shared/authority_graph.py` MUST derive the authorization graph
  — active role → canonical role → action → tool → filesystem effect — by calling
  `agent_authority` and `policy_loader` at runtime, and MUST NOT read or write any persisted
  graph artifact.
- R-GEA-3: `execute_generate_code` MUST reject, before any bytes reach disk, generated Python in
  which any entry of `governance-policy.json` → `synthesis.prohibited_imports` appears as an
  imported name **or** as a resolved attribute reference, reusing the AST already parsed by
  `_validate_code_syntax` rather than reparsing. The two forms are both required because the
  key's five entries are not all importable: `subprocess` and `importlib` are modules, while
  `os.system` and `shutil.rmtree` are attribute call targets reachable through a bare
  `import os`, and `__import__` is a builtin that no import statement names at all — a check
  reading only `ast.Import` / `ast.ImportFrom` would decide two of the five and silently pass
  the other three.
- R-GEA-4: Every check added by this spec MUST fail closed when its own input set is empty —
  a derived node set, edge set, or requirement-ID set that comes back empty is a broken
  extractor, not a satisfied property, and MUST raise rather than pass.
- R-GEA-5: A baseline measurement of tokens and tool calls per subagent turn MUST be recorded
  under `docs/reports/` before any code-property graph is built, and the decision to build one
  MUST compare that baseline against a threshold read from `governance-policy.json`.
- R-GEA-6: Static topology verification of a `StateGraph` MUST NOT be wired into any CI target
  while `DEC-053`'s park stands; if NS-31 supersedes DEC-053, the topology extractor MUST derive
  nodes and edges from module source via `ast` rather than from a compiled graph object, so the
  check runs on the 3.9 leg where `MANGO_CI_DESELECT_LANGGRAPH` is set.
- C-GEA-1: This change MUST NOT add a runtime dependency; every module it introduces imports
  only the standard library and existing first-party modules, so `make lock-check` recompiles
  unchanged.
- C-GEA-2: No module introduced by this spec may be imported by `harness/shared/write_policy.py`,
  `harness/shared/read_policy.py`, `harness/shared/agent_authority.py`, or anything under
  `harness/shared/governance/`; the graph reads the governance layer and the governance layer
  MUST NOT depend on the graph.
- C-GEA-3: R-GEA-3's pre-write check MUST be decidable from the single module being written;
  it MUST NOT consult a repository-wide index, because a write door that depends on a stale
  index denies valid writes.
- C-GEA-4: Any exemption list this spec introduces MUST be rejected as stale when its subject no
  longer needs the exemption, so a waiver cannot outlive the defect it covers.

## Acceptance criteria

- [ ] AC-GEA-1: `check_traceability.py --workspace .` run from the repository root discovers at
      least 380 requirement IDs, and the same invocation against a workspace containing no spec
      files exits non-zero with `no spec files matched` — verified by
      `pytest -k test_traceability_workspace_scope` · stage: `make validate` (R-GEA-1)
- [ ] AC-GEA-1b: after step 2, `make validate` exits 0 with every discovered ID carrying both
      citations, or with each remaining gap listed in a `DEC-` record that the gate reads as an
      accepted exemption; a gap that is neither cited nor recorded fails the gate — verified by
      `pytest -k test_traceability_gaps_are_cited_or_recorded` · stage: `make validate`
      (R-GEA-1, C-GEA-4)
- [ ] AC-GEA-2: `authority_graph.reachable_actions("verifier")` excludes every member of
      `agent-policy.json` → `high_risk_actions`, and a mutation that removes the
      `human_approval_required_for` subtraction in `agent_authority.allowed_actions` makes the
      test go red — verified by `pytest -k test_no_active_role_reaches_a_high_risk_action`
      · stage: `make test-python` (R-GEA-2)
- [ ] AC-GEA-3: `authority_graph` path enumeration from `nemotron-reasoner` to `write_file`
      returns a witness path naming each intermediate role and action, and returns the empty
      list for `planner`, whose canonical roles hold no `write` — verified by
      `pytest -k test_write_paths_are_role_specific` · stage: `make test-python` (R-GEA-2)
- [ ] AC-GEA-4: `execute_generate_code` writes zero bytes, leaves any pre-existing file
      byte-for-byte unchanged, and returns a denial naming the offending symbol for each of the
      three shapes the policy key spans — `import subprocess`, `import os` followed by a call to
      `os.system`, and a bare `__import__("os")` — while ordinary code importing `pathlib` still
      writes — verified by `pytest -k test_generate_code_denies_prohibited_import`
      · stage: `make test-python` (R-GEA-3, C-GEA-3)
- [ ] AC-GEA-5: With `synthesis.prohibited_imports` set to an empty list in a temporary policy,
      `execute_generate_code` raises rather than silently accepting every import, proving the
      check cannot pass vacuously — verified by
      `pytest -k test_empty_prohibited_list_is_a_broken_policy` · stage: `make test-python`
      (R-GEA-4)
- [ ] AC-GEA-6: A static import scan asserts that no file under `harness/shared/governance/`,
      nor `write_policy.py`, `read_policy.py`, or `agent_authority.py`, names `authority_graph`,
      and the test fails if such an import is introduced — verified by
      `pytest -k test_governance_layer_does_not_import_the_graph` · stage: `make test-python`
      (C-GEA-2)
- [ ] AC-GEA-7: `make lock-check` recompiles `requirements-lock.txt` with no diff after this
      change lands, and `python -m harness.shared.check_py_compat` exits 0 for every new module
      — verified by `make lock-check` · stage: `make ci` (C-GEA-1)
- [ ] AC-GEA-8: `docs/reports/` contains a baseline naming measured tokens and tool calls per
      subagent turn for at least three recorded turns, and no module implementing a code-property
      graph exists in the tree until that file does — verified by
      `pytest -k test_code_graph_is_gated_on_a_recorded_baseline` · stage: `make test-python`
      (R-GEA-5)
- [ ] AC-GEA-9: No `StateGraph` topology checker is reachable from `make ci` or listed in
      `governance-policy.json` → `ci_required_targets` while `docs/decisions/DEC-053.md` carries
      `status: accepted`; a test asserts the pairing and goes red if a topology target is added
      without superseding DEC-053 — verified by
      `pytest -k test_topology_gate_is_parked_with_langgraph` · stage: `make test-python`
      (R-GEA-6)
- [ ] AC-GEA-10: An exemption entry whose subject no longer requires it is rejected: a test
      constructs an exemption for a node that is reachable and asserts the checker exits
      non-zero with a `stale exemption` message — verified by
      `pytest -k test_stale_exemption_fails_closed` · stage: `make test-python` (C-GEA-4)

## Steps

Ordered so that each step's inputs exist before it runs, and so that the defect blocking every
later requirement ID is closed first.

1. **Fix the traceability scope.** Add `--workspace` to `check_traceability.py`, defaulting to
   the repository root; keep the CWD-relative path working for the per-stack shim during the
   `DEC-056` shim window — consumes `harness/node/.governance/traceability.json`; produces a
   root `.governance/traceability.json` and a passing gate over 386 IDs.
2. **Reconcile the newly visible corpus.** Fixing step 1 exposes 380 previously unchecked IDs.
   Running the gate's own logic against root-scoped globs measures **251 of 392 IDs missing an
   implementation citation, a test citation, or both** — a figure sensitive to the chosen
   `implementation_globs` / `test_globs` and therefore an order of magnitude, not a target.
   Consumes step 1's output; produces either citations or a decision record listing accepted
   gaps with reasons. *This is the largest step in the plan, and it is sequenced second so its
   size is measured before anything depends on it. Step 1 without step 2 turns a silently
   passing gate into a loudly failing one, which is why they are one deliverable and not two.*
3. **Derive the authorization graph.** Add `harness/shared/authority_graph.py`: nodes are roles,
   actions, and tools; edges come from `ACTIVE_TO_CANONICAL`, `agent-policy.json`, and
   `TOOL_REQUIRED_ACTION`; expose `reachable_actions(role)` and `paths_to(role, tool)` returning
   witness paths — consumes `agent_authority`, `policy_loader`; produces the graph and its tests.
4. **Assert the safety property.** Add the reachability tests and the mutation proof that each
   goes red when the corresponding governance logic is reverted — consumes step 3.
5. **Escalate the write door.** Extend `execute_generate_code` to reuse the parsed AST for a
   prohibited-import check, sourced from `synthesis.prohibited_imports` — consumes
   `tool_executors._validate_code_syntax`; produces the pre-write denial and its regression test.
6. **Record the baseline.** Instrument and record tokens and tool calls per subagent turn —
   produces `docs/reports/` baseline; gates step 7.
7. **Decide the code graph.** Compare the baseline against the policy threshold; build only on a
   pass, and record the decision either way — consumes step 6.
8. **Park the topology checker.** Add the test that pins R-GEA-6's parking to `DEC-053`'s status,
   so a future topology gate cannot land without superseding it — consumes `docs/decisions/DEC-053.md`.

## Files touched

No path below matches `protected_paths` in `governance-policy.json`, so this spec's own landing
needs no `infra-reviewed` attestation. Steps 1, 5, and 7 do touch protected paths and are called
out.

- `docs/specs/graph-engineering-adoption.md` (this document)
- `docs/reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md`
- `harness/shared/authority_graph.py` — new, step 3
- `harness/shared/tests/test_authority_graph.py` — new, step 4
- `harness/shared/governance/check_traceability.py` — **protected** (`harness/shared/governance/**`), step 1
- `harness/shared/tool_executors.py` — **protected**, step 5
- `harness/shared/governance-policy.json` — **protected**, step 7 only, to add the code-graph threshold
- `harness/node/.governance/traceability.json` — **protected** (`**/.governance/**`), step 1

## Invariants touched

- INV-2 (zero unapproved skips): every check this spec adds runs unconditionally in the ordinary
  pytest run. None is `skipif`-gated on an optional import, so none can become a skip in search
  of a waiver. Preserved by construction; proven by `make verify-zero-skips-python`.
- INV-5 (CI gate coverage): unchanged. Per D-5 this spec adds no `ci_required_target`, so
  `test_ci_gate_coverage.py` sees no new entry to reconcile.
- INV-7 (bounded agent authority and trace logging): R-GEA-2 makes the bound machine-checked
  rather than argued. The graph is read-only and derived, so it cannot widen any authority;
  AC-GEA-2's mutation proof is what shows the check has teeth.
- INV-9…INV-15 (synthesis policy gates): R-GEA-3 tightens the write door using
  `synthesis.prohibited_imports`, an existing policy key, and adds no new threshold literal.
- INV-16 (cognitive/execution boundary): unaffected. Nothing here reads a `CognitiveSignal` or
  lets one select a tool.
- INV-17 (plan defect classes): this document is itself subject to `plan_rules.py` via
  `validate_plan.py`, since it is a modified plan under `make specs`.
- INV-LG-1…INV-LG-7: untouched. R-GEA-6 deliberately adds no LangGraph invariant while DEC-053
  stands.

## Validation matrix

Thresholds are read from `harness/shared/governance-policy.json`; none is restated here.

- `make lint` — ruff check, ruff format, mypy, vulture, and `check_py_compat` against the
  3.9 floor for every new module (C-GEA-1)
- `make test-python` — the reachability, witness-path, vacuity, boundary, and parking tests
  (AC-GEA-2…AC-GEA-6, AC-GEA-8…AC-GEA-10)
- `make coverage-python` — per-file lines and branches floors from `coverage.lines`,
  `coverage.branches`, `coverage.per_file` for `authority_graph.py`
- `make validate` — `check_traceability.py` over the repaired scope (AC-GEA-1)
- `make lock-check` — recompiles unchanged, proving no dependency was added (AC-GEA-7)
- `make specs` — structural tier plus `plan_rules.py` over this document (INV-17)
- `make verify-zero-skips-python` — no new skip (INV-2)
- `make pre-pr` — the full pipeline plus `lint-cold`, `audit`, and `secrets`

## Backward compatibility

- **R-GEA-1** keeps `check_traceability.py`'s CWD-relative behaviour as the default when
  `--workspace` is absent, so the per-stack shims that `runpy` it during the `DEC-056` shim
  window keep working unchanged. The root invocation passes `--workspace .` explicitly. The
  flag is removed only when DEC-056's entry-point migration retires the shims.
- **R-GEA-2** adds a module; no existing caller changes. C-GEA-2 forbids the reverse dependency,
  so no governance module's import list moves.
- **R-GEA-3** changes `execute_generate_code`'s behaviour for one previously accepted input
  class: Python importing a prohibited distribution now returns a denial where it previously
  wrote the file. That is a deliberate narrowing, stated rather than hidden. No other tool
  (`write_file`, `apply_patch`, `read_file`, `run_command`) changes, preserving C-CGT-2 from
  `docs/specs/code-generation-tool.md`.
- **R-GEA-6** is a constraint on future work and removes nothing. If NS-31 supersedes DEC-053,
  AC-GEA-9's test is updated in the same change that supersedes it, which is the point of
  pinning the pairing.
