# Spec: graph-engineering adoption

> **Status:** DRAFT, revision 3. Contract for adopting graph representations of this
> repository's governance chain, generated code, and orchestration topology, as reviewed in
> [`docs/reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md`](../reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md).
> Every design decision below is argued **Thesis → Counter-Argument → Rebuttal**, where the
> rebuttal is required to introduce a third position rather than restate the thesis.
>
> **Revision 2** applies findings S-1…S-5 of that report's §7, which computed the graph this
> spec proposes and found four defects in revision 1: `R-GEA-2` targeted a property
> `validate_agent_policy.py` already decides (S-1) instead of the agent-input-to-privileged-flag
> path that is genuinely unasserted (S-2); `R-GEA-1` would have produced a gate that can never
> go green (S-3); and `R-GEA-6` forbade the plain test `D-5` says should exist (S-4).

## Problem statement

Three defects, each evidenced against `main` @ `3fc9c3e` and re-verified after merging
`main` @ `5cd423b` (PR #118, `python-floor-310`):

1. **A governance gate checks a corpus it was not meant to check.**
   `check_traceability.py:25` reads `TRACEABILITY_CONFIG = Path(".governance/traceability.json")`
   relative to the CWD, and `Makefile:255` runs it from `harness/node`. The globs therefore
   resolve to `harness/node/docs/specs/**`. Measured: the gate reads 6 requirement IDs; the
   real corpus at `docs/specs/` holds 412, sharing not one member with them. `make validate`
   prints `traceability: passed (6 requirements)` and exits 0.

2. **One approval flag is guarded by construction and by nothing else.** `policy_decision.decide`
   takes `human_approved`, the single argument that turns a high-risk denial into an ALLOW
   (`policy_decision.py:51,76`). `broker.py:133` sources it from `context` with an identity check
   (`is True`), and `tool_executors.py:384` builds that context as a literal
   `{"agent_id": execution_identity(active_role)}` — no such key, so the agent path cannot reach
   the flag. The guarantee is real and it rests on one dict literal in one function;
   `broker.execute_command(command, **kwargs)` makes threading a caller-supplied context
   syntactically easy, and no test would go red. The property "no agent-controlled input reaches
   `human_approved`" is nowhere asserted.

   The neighbouring property is *not* a gap, and revision 1 wrongly claimed it was:
   `validate_agent_policy.py:48-50` already fails closed on any role granting a high-risk action
   without approval-gating it. Three of the five `high_risk_actions` — `destructive`,
   `permission_change`, `secret_access` — are declared by no role at all, because they are
   `command_actions.classify` output rather than grants, and `decide()` denies them by absence.
   `high_risk_actions` mixes a grant vocabulary and a classification vocabulary in one namespace,
   which is what made the distinction easy to miss.

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
with a named sunset. *(A fourth point — that the 3.9 leg would not run the check — is withdrawn:
PR #118 moved the floor to 3.10 and langgraph now installs on every leg. The counter stands on
the remaining three and on DEC-053's unchanged `accepted` status.)*

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

**Counter-Argument.** Every dependency here is a lock entry in a 216 KB hashed
`requirements-lock.txt` behind a `lock-check` gate, an `audit` surface, and a `check_py_compat`
risk against the 3.10 floor. `import networkx` fails in this checkout and networkx is in no
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

### D-6 · Whether an unexecuted park is a park (added in revision 2)

**Thesis.** D-1 settled this: DEC-053 parks LangGraph, so nothing new is built on it. The
orphan reviewers wait for NS-31.

**Counter-Argument.** DEC-053 is a decision, not a state. `harness/shared/langgraph/` is still
at its original path; `harness/shared/experimental/` contains only `autonomous_healing.py` and
`lats_optimizer.py`. The only thing that moves it is Phase E, gated on NS-2 — a credential
rotation requiring a human at a provider, open since at least 2026-09-05, and NEXT_STEPS says
plainly that "DEC-053…056 are logged; they do not lift this gate". So `findings` is empty on
every run and `test_langgraph_graph.py` keeps asserting the node set that pins it, for an
indefinite period. "Don't invest in parked code" against an indefinitely deferred park means the
defect ships indefinitely.

**Rebuttal (third position).** Both positions argue about whether to *build the checker*, and
neither notices they want different artifacts. D-1 rejects a fail-closed **CI gate** on parked
code — a required check, a `CONTRACT.md` row, three protected-path attestations, an entry in a
ten-item `ci_required_targets`. The counter wants the defect **visible**, which needs none of
that. D-5's rebuttal already dissolved this: the choice is which enforcement surface, and a pure
function over repository state belongs in the test suite. So the answer is neither "add a gate"
nor "wait for the park" — it is a plain test, following `test_constant_triage.py`'s precedent,
asserting the reviewers are edgeless *and that this is DEC-052's recorded state*. It fails when
someone wires them in without amending DEC-052, and when someone deletes them silently. One test
file, no target, no policy entry, no attestation. **Resolution: R-GEA-6 is split — 6 keeps the
gate parked, 6b requires the test, and revision 1's blanket prohibition is withdrawn as the same
conflation D-5 had already resolved.**

## Requirements

- R-GEA-1: The repository invocation of `check_traceability.py` MUST pass `--workspace .` and run
  from the repository root, so its configuration and globs resolve there rather than under
  `harness/node`, where `make validate` previously ran it, and the requirement IDs it reads are
  the corpus under `docs/specs/` rather than `harness/node/docs/specs/`. The option's
  omitted-value default remains CWD-relative for the per-stack compatibility shims.
  *Revision 4: revision 3 required the argument to default to the repository root. It does not
  and must not — the shipped default is `Path.cwd()`, and a repository-root default would have
  broken the per-stack shims the Backward compatibility section below guarantees, so the
  requirement contradicted both the code and its own compatibility clause. What fixes the defect
  is the explicit root on the required check, not a changed default.*
- R-GEA-1b: The gate MUST distinguish **contract specs**, whose requirement IDs name shipped
  behaviour and must carry both citations, from **program plans**, whose IDs name scheduled work
  and cannot cite an implementation until it exists. The class MUST be declared per document
  rather than inferred from the filename, and a document declaring neither MUST be treated as a
  contract spec so the permissive class is never the default. Without this, re-scoping the globs
  alone produces a gate that cannot go green while any planned work exists — measured at 98 of
  271 current gaps declared only in roadmap documents (83), plus 14 in this plan itself — and a gate that cries wolf is
  switched off.
- R-GEA-2: A new module `harness/shared/authority_graph.py` MUST derive, without any persisted
  artifact, the reachability of `policy_decision.decide`'s `human_approved` argument from
  agent-controlled input: the graph's nodes are the call sites that construct a broker `context`,
  and it MUST report any path on which a value not literal in the constructing function can
  reach `context["human_approved"]`.
- R-GEA-2b: The same module MUST model the two grant surfaces separately — `allowed_actions`
  (tool exposure) and `EXECUTION_IDENTITY` (what the broker asks the PDP about) — because they
  deliberately disagree: `planner` holds `spec_write` while executing as `orchestrator`, which
  lacks it, and `verifier` holds `review_write` and `security_scan` while executing as
  `test-eval`, which lacks both. A query that does not name which surface it means MUST raise
  rather than pick one.
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
  or `ci_required_targets` entry while `DEC-053`'s park stands. It MUST NOT be omitted from the
  ordinary test suite on that account: per D-5 the two are different enforcement surfaces, and
  DEC-053's park is decided but unexecuted — `harness/shared/langgraph/` is still at its original
  path and Phase E is blocked behind NS-2 — so the defect is live for an indefinite period.
- R-GEA-6b: A test MUST assert that `peer_reviewer` and `security_reviewer` have no incoming or
  outgoing edge **and** that this is `DEC-052`'s recorded state, so it fails both when the
  reviewers are wired in without updating DEC-052 and when they are deleted silently. Its
  enforcement surface is the ordinary pytest run, following `test_constant_triage.py`'s
  precedent: no `make` target, no policy entry, no protected path.
- R-GEA-6c: If NS-31 supersedes DEC-053, the topology extractor MUST derive nodes and edges from
  module source via `ast` rather than from a compiled graph object, so the check needs no
  `skipif` on an optional import and cannot become a skip in search of a waiver under INV-2.
  The original reason — that a compiling check would be absent on the 3.9 leg where
  `MANGO_CI_DESELECT_LANGGRAPH` is set — expired when PR #118 moved the floor to 3.10
  (`docs/specs/python-floor-310.md`); langgraph now installs on every leg and the policy's
  `deselect_env` key is inert. The requirement stands on the INV-2 ground alone, which is the
  stronger of the two and was always the load-bearing half.
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

- [x] AC-GEA-1: `check_traceability.py --workspace .` run from the repository root discovers at
      least 412 requirement IDs, and the same invocation against a workspace containing no spec
      files exits non-zero with `no spec files matched` — verified by
      `pytest -k test_traceability_workspace_scope` · stage: `make test-python` (R-GEA-1)
- [x] AC-GEA-1b: a repository-scoped run exits 0 only while the count of contract-spec IDs
      missing a citation is at or below `traceability.max_uncited_contract_requirement_ids`, and
      exits non-zero naming the excess and the rule that the ratchet may only be lowered —
      verified by `pytest -k test_traceability_gaps_are_cited_or_recorded`
      · stage: `make test-python` (R-GEA-1, C-GEA-4). *Revision 3: revision 2 asked for each
      remaining gap to be listed in a `DEC-` record the gate reads as an exemption. What shipped
      is a ratchet over a count, with no DEC-record reader. The ratchet is the stronger control
      for this backlog — a per-ID exemption list of 223 entries is a list nobody re-reads, while
      a number that may only fall cannot outlive the gaps it covers — but the criterion is
      rewritten to describe what exists rather than left describing what does not.*
- [x] AC-GEA-1c: a document declaring no class is graded as a contract spec and its uncited IDs
      fail the gate, while a document declaring `program-plan` has its IDs counted and reported
      but not required to cite an implementation; a document declaring an unrecognised class
      raises rather than defaulting to the permissive branch — verified by
      `pytest -k test_spec_class_defaults_to_the_strict_branch` · stage: `make test-python`
      (R-GEA-1b)
- [x] AC-GEA-2: `authority_graph` reports zero agent-reachable paths to
      `context["human_approved"]`, and a fixture in which `execute_run_command` forwards a
      caller-supplied `context` instead of its literal dict makes the test go red with a witness
      naming that call site — verified by
      `pytest -k test_no_agent_input_reaches_the_approval_flag` · stage: `make test-python`
      (R-GEA-2)
- [x] AC-GEA-2b: `reachable_actions("verifier")` excludes `external_write` and
      `production_change`, and reverting the `human_approval_required_for` subtraction in
      `agent_authority.allowed_actions` makes exactly that assertion go red; the same test
      asserts that `destructive`, `permission_change`, and `secret_access` are absent from every
      role's `allowed_actions`, so the criterion states which two of the five high-risk actions
      it is non-vacuous for rather than passing on three that have no edge — verified by
      `pytest -k test_high_risk_reachability_names_its_live_half` · stage: `make test-python`
      (R-GEA-2b, R-GEA-4)
- [x] AC-GEA-3: `authority_graph` path enumeration from `nemotron-reasoner` to `write_file`
      returns a witness naming each intermediate role and action on the surface it was asked
      about, returns the empty list for `planner`, and **raises** when the caller does not name
      a surface — with `planner` → `spec_write` present on the tool-exposure surface and absent
      on the execution-identity surface, which is the pair a single-surface query would answer
      wrongly — verified by `pytest -k test_write_paths_name_their_surface`
      · stage: `make test-python` (R-GEA-2b)
- [x] AC-GEA-4: `execute_generate_code` writes zero bytes, leaves any pre-existing file
      byte-for-byte unchanged, and returns a denial naming the offending symbol for each of the
      three shapes the policy key spans — `import subprocess`, `import os` followed by a call to
      `os.system`, and a bare `__import__("os")` — while ordinary code importing `pathlib` still
      writes — verified by `pytest -k test_generate_code_denies_prohibited_import`
      · stage: `make test-python` (R-GEA-3, C-GEA-3)
- [x] AC-GEA-5: `prohibited_symbol_findings` raises rather than accepting every input when the
      prohibited list is empty, missing, of the wrong type, or holds a non-string member — proved
      for both a directly-passed list and a policy file on disk — verified by
      `pytest -k test_empty_list_in_a_present_policy`
      · stage: `make test-python` (R-GEA-4). *Revision 3: revision 2 named a selector,
      `test_empty_prohibited_list_is_`, that matches no test, and ticking it tripped
      `test_spec_selectors_collect.py` — a ticked criterion whose selector collects nothing is
      the unfalsifiable shape R-GEA-4 is about, arriving in this spec's own acceptance list.
      Revision 2 also asked for the raise to be shown through `execute_generate_code` under a
      temporary policy; that path needs `MANGO_WRITE_POLICY_PATH`, and `write_denial_reason` then
      demands a pin-digest record for any supplied policy, so the end-to-end form needs a pin
      fixture that does not exist. The raise propagates out of `execute_generate_code` unchanged,
      which is the property; the criterion now claims only what is proven.*
- [x] AC-GEA-6: A static import scan asserts that no file under `harness/shared/governance/`,
      nor `write_policy.py`, `read_policy.py`, or `agent_authority.py`, names `authority_graph`,
      and the test fails if such an import is introduced — verified by
      `pytest -k test_governance_layer_does_not_import_the_graph` · stage: `make test-python`
      (C-GEA-2)
- [x] AC-GEA-7: `make lock-check` recompiles `requirements-lock.txt` with no diff after this
      change lands, and `python -m harness.shared.check_py_compat` exits 0 for every new module
      — verified by `make lock-check` · stage: `make ci` (C-GEA-1)
- [ ] AC-GEA-8: `docs/reports/` contains a baseline naming measured tokens and tool calls per
      subagent turn for at least three recorded turns, and no module implementing a code-property
      graph exists in the tree until that file does — verified by
      `pytest -k test_code_graph_is_gated_on_a_recorded_baseline` · stage: `make test-python`
      (R-GEA-5)
- [x] AC-GEA-9: No `StateGraph` topology **target** is reachable from `make ci` or listed in
      `governance-policy.json` → `ci_required_targets` while `docs/decisions/DEC-053.md` carries
      `status: accepted`; the test goes red if such a target is added without superseding
      DEC-053, and does not fail merely because a topology *test* exists — verified by
      `pytest -k test_topology_gate_is_parked_with_langgraph` · stage: `make test-python`
      (R-GEA-6)
- [x] AC-GEA-9b: A test asserts `peer_reviewer` and `security_reviewer` are edgeless in
      `graph.py` and that `DEC-052` records that state; wiring either reviewer in without
      amending DEC-052 fails it, and deleting either node fails it — verified by
      `pytest -k test_orphan_reviewers_match_the_recorded_decision`
      · stage: `make test-python` (R-GEA-6b)
- [x] AC-GEA-10: a run whose backlog sits below the ratchet reports the count *and the
      headroom*, naming the lower value the ratchet should be set to, so an allowance that has
      stopped being needed is visible on every green run rather than only on a red one — verified
      by `pytest -k test_the_repository_run_reports_the_count_and_the_headroom`
      · stage: `make test-python` (C-GEA-4). *Revision 3: revision 2 asked for a stale **exemption
      entry** to be rejected and named `test_stale_exemption_fails_closed`, which matches no test —
      caught by `test_spec_selectors_collect.py`, the second time this spec's own acceptance list
      tripped that gate. What shipped for C-GEA-4 is a ratchet over a count rather than a list of
      per-subject exemptions, so "stale" means headroom above zero, and the gate reports it rather
      than raising: a backlog that has shrunk is not a failure, it is a number waiting to be
      lowered. The criterion now describes that.*
- [x] AC-GEA-11: The topology extractor reads `graph.py` as source and
      imports nothing from `langgraph`, so it returns the same node and edge sets whether or not
      that package is installed, and raises rather than reporting an empty topology when no
      `StateGraph` assignment is found — verified by
      `pytest -k test_topology_extraction_is_source_based` · stage: `make test-python`
      (R-GEA-6c, R-GEA-4). *Revision 3: the conditional prefix "If DEC-053 is superseded" is
      dropped. DEC-053 is accepted, so the criterion could never fire and was unfalsifiable —
      the defect class this spec's own R-GEA-4 exists to prevent. R-GEA-6c stands on the INV-2
      ground alone, which never depended on the park.*

## Steps

Ordered so that each step's inputs exist before it runs, and so that the defect blocking every
later requirement ID is closed first.

1. **Fix the traceability scope, and classify the corpus in the same change.** Add `--workspace`
   to `check_traceability.py`; the root invocation passes `--workspace .`, while the omitted-value
   default remains CWD-relative, which is what keeps the per-stack shim working during the
   `DEC-056` shim window; and add a per-document class declaration (contract spec vs program plan)
   defaulting to the strict branch — consumes `harness/node/.governance/traceability.json` (reads
   it; the file is deliberately left unedited, which is what makes the shim invocation a live
   proof of the compatibility claim); produces a root `.governance/traceability.json`, a class
   declaration in each program plan, and a gate that reads the real corpus. *The scope fix and
   the classification are one step because shipping the first alone produces a gate that cannot
   go green (S-3).*
2. **Reconcile the newly visible corpus.** Fixing step 1 exposes 412 previously unchecked IDs.
   Running the gate's own logic against root-scoped globs measures **271 of 412 IDs missing an
   implementation citation, a test citation, or both** — a figure sensitive to the chosen
   `implementation_globs` / `test_globs` and therefore an order of magnitude, not a target.
   Consumes step 1's output; produces either citations or a decision record listing accepted
   gaps with reasons. *This is the largest step in the plan, and it is sequenced second so its
   size is measured before anything depends on it. Step 1 without step 2 turns a silently
   passing gate into a loudly failing one, which is why they are one deliverable and not two.*
3. **Derive the authorization graph, on both surfaces.** Add `harness/shared/authority_graph.py`:
   role/action/tool nodes with edges from `ACTIVE_TO_CANONICAL`, `agent-policy.json`, and
   `TOOL_REQUIRED_ACTION`, modelled twice — tool exposure and execution identity — with
   `reachable_actions(role, surface)` and `paths_to(role, tool, surface)` returning witnesses and
   raising on an unnamed surface — consumes `agent_authority`, `policy_loader`; produces the
   graph and its tests.
4. **Assert the approval-flag property.** Add the `human_approved` reachability check over the
   call sites that construct a broker `context`, plus the mutation proof that forwarding a
   caller-supplied context from `execute_run_command` turns the test red with a witness naming
   that site — consumes step 3, `broker.py`, `tool_executors.py`. *This, not the grant graph, is
   the unasserted property: `validate_agent_policy.py:48-50` already decides the grant half
   (S-1, S-2).*
5. **Escalate the write door.** Extend `execute_generate_code` to reuse the parsed AST for a
   prohibited-import check, sourced from `synthesis.prohibited_imports` — consumes
   `tool_executors._validate_code_syntax`; produces the pre-write denial and its regression test.
6. **Record the baseline.** Instrument and record tokens and tool calls per subagent turn —
   produces `docs/reports/` baseline; gates step 7.
7. **Decide the code graph.** Compare the baseline against the policy threshold; build only on a
   pass, and record the decision either way — consumes step 6.
8. **Pin the orphan reviewers and park the topology *gate*.** Add the test asserting
   `peer_reviewer` and `security_reviewer` are edgeless and that DEC-052 records it, and the test
   pinning the absence of a topology *target* to DEC-053's status — consumes
   `docs/decisions/DEC-052.md`, `docs/decisions/DEC-053.md`, `harness/shared/langgraph/graph.py`
   (read only). *Step 8 needs only the R-GEA-6c extractor, which is why the two ship
   together; beyond that it depends on nothing else in this plan, and it closes the only
   defect here that is live in the tree today.*

## Files touched

Rows marked **protected** match `protected_paths` in `governance-policy.json` and each needs a
row in the PR's `infra-reviewed` attestation table. `make attestation BASE_REF=main` generates
that table from `protected_paths` and the branch diff and is the authority; the list below is a
snapshot of one head, kept in prose only so a reader can notice an omission without running
anything. Measured on `eab19b8`: 42 files changed against `origin/main`, of which **ten** are
protected. `BASE_REF=main` resolves to `origin/main`, because `git_modified_files` prepends
`origin/`, and `origin/main` is this PR's real base. Do not substitute a bare `git diff
main...HEAD`: the local `main` ref is an ancestor of `origin/main`, 113 commits behind it, so
that diff reports several hundred files and buries the ten.

*Revision 3: revision 2 opened this section with "No path below matches `protected_paths` … so
this spec's own landing needs no `infra-reviewed` attestation", which was false of its own list
— four rows below were already marked protected, and the PR carries the required `infra-reviewed`
attestation. The sentence was written when the plan expected to touch only documentation and was
not revised when the implementation landed.*
*Revision 4: revision 3's own replacement then carried a stale count, "seven attestation rows",
against a table of ten, and a list that had drifted from the implementation in four further ways
— `docs/specs/*.md` claimed a class-declaration line "per document" where only the five program
plans received one, a code-graph threshold was attributed to the policy that step 7 never
reached, `harness/node/.governance/traceability.json` was listed as edited when leaving it
untouched is what proves the compatibility claim, and 27 of the 42 changed files were absent —
seven of them protected, so a reviewer working from this list would have expected four
attestation rows, only three of which are real, and met ten. A wrong count in the paragraph
warning about attestation drift is
that drift. The count is kept rather than replaced by a bare pointer, because a pointer gives a
reviewer nothing to disagree with and drift is only ever caught by two figures failing to match;
it is now stamped with the commit and the command that produced it, so a later reader can tell a
measurement from a carried-forward claim (DEC-024).*

New modules and their tests:

- `harness/shared/authority_graph.py` — new, step 3
- `harness/shared/tests/test_authority_graph.py` — new, step 4
- `harness/shared/authority_call_sites.py` — new, step 4 (the `human_approved` reachability scan)
- `harness/shared/code_safety.py` — new, step 5 (`prohibited_symbol_denial` over the parsed AST)
- `harness/shared/tests/test_code_safety.py` — new, step 5
- `harness/shared/graph_topology.py` — new, step 8 (the R-GEA-6c extractor AC-GEA-9b consumes)
- `harness/shared/tests/test_graph_topology.py` — new, step 8
- `harness/shared/tests/test_graph_topology_parked.py` — new, step 8 (reads `graph.py`, edits nothing)
- `harness/shared/tests/test_traceability_scope.py` — new, step 1
- `harness/shared/tests/regression/test_traceability_corpus_regression.py` — new, step 1
- `harness/shared/tests/regression/test_prohibited_symbol_write_door_regression.py` — new, step 5

Existing code and tests amended:

- `harness/shared/governance/check_traceability.py` — **protected** (`harness/shared/governance/**`), step 1
- `harness/shared/tool_executors.py` — **protected**, step 5 — the write door itself
- `harness/shared/governance-policy.json` — **protected**, step 1 — adds
  `traceability.min_discovered_requirement_ids`, `max_uncited_contract_requirement_ids`,
  `default_spec_class`, `program_plan_class` and `spec_class_marker`. It does **not** add a
  code-graph threshold: step 7 is gated on step 6's baseline, which this change does not reach.
- `Makefile` — **protected** (`Makefile`), step 1 — the second, repository-scoped
  `check_traceability.py --workspace .` invocation alongside the per-stack one
- `harness/shared/tests/test_protected_path_liveness.py` — **protected**, step 1 — reclassifies
  `.governance/**` out of `DORMANT_PATTERNS`, since the root directory is now live
- `harness/shared/tests/test_constant_triage.py` — step 1 — one row, registering
  `test_traceability_scope.ACCEPTED_RATCHET_CEILING` against DEC-065
- `harness/shared/tests/test_code_generation_tool.py` — step 5
- `harness/shared/tests/test_agent_surface_liveness.py` — a pointer to its new companion,
  `harness/shared/tests/test_agent_surface_determinism.py`. Both pin the derived role/tool
  surface R-GEA-2b models. They are listed because they changed on this branch, not because a
  step above produces them.

Governance artefacts and records:

- `.governance/traceability.json` — **protected** (`.governance/**`), step 1 — new, the
  repository-scoped config declaring `"scope": "repository"`
- `.mango/agents/README.md` — **protected** (`.mango/agents/**`) — corrects the effective-tool
  table, which omitted `generate_code` from both roles' surfaces
- `harness/CONTRACT.md` — **protected**, step 1 — records that root `.governance/` is now live
- `harness/control-plane/policy-artifact.json` — **protected**, step 1 (policy digest regen,
  because `governance-policy.json` changed)
- `harness/node/.governance/decision-log.md` — **protected** (`**/.governance/**`)
- `docs/decisions/DEC-065.md`, `docs/decisions/index.md`, `docs/decisions/index.json`
- `CHANGELOG.md`, `NEXT_STEPS.md`, `.gitignore`, `.dockerignore`

Later than the `eab19b8` snapshot, and so *not* in the ten counted above:
`harness/shared/tool_schemas.py` — **protected** — whose `validate_syntax` description had gone
on claiming the flag decides whether validation happens, which step 5 stopped being true.
Regenerate the table with `make attestation BASE_REF=main` before opening the PR rather than
trusting the count above; that is what the count is a snapshot *of*.

Documentation:

- `docs/specs/graph-engineering-adoption.md` (this document)
- `docs/reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md`
- `docs/specs/2026-standards-remediation-plan.md`, `docs/specs/code-quality-tech-debt-plan.md`,
  `docs/specs/god-file-decomposition.md`, `docs/specs/reflection-hardening-increment.md`,
  `docs/specs/tech-debt-hardening-plan.md` — one class-declaration line each, carrying the
  `traceability.spec_class_marker` prefix, step 1. (Naming that prefix literally here would
  declare a class for *this* document, which is why it is named through the policy key.) These
  five are the program plans; every other document under `docs/specs/` is left undeclared and so
  graded as a contract spec by `traceability.default_spec_class`, which is the strict branch
  R-GEA-1b requires the default to be.
- `README.md`, `harness/README.md`, `docs/architecture/c4_architecture.md`

**Not** touched, deliberately: `harness/node/.governance/traceability.json`. Revision 3 listed it
as edited. Step 1 *reads* it through the per-stack shim invocation `make validate` still runs, and
leaving it byte-identical is what makes that invocation a live proof of the Backward compatibility
claim rather than an assertion about it.

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
  3.10 floor for every new module (C-GEA-1)
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
