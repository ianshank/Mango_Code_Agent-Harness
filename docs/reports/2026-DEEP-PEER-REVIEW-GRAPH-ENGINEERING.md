# Deep peer review: graph engineering applied to this harness

**Reviewed head:** `main` @ `3fc9c3e`, re-verified after merging `main` @ `5cd423b`
(PR #118, `python-floor-310`) — see §2 point 2 and §7 S-6 for what that merge changed
**Subject under review:** the three-model synthesis "Graph Engineering Applied to
Mango_Code_Agent-Harness" (Claude Opus 5 Thinking / Nemotron 3 Ultra / GPT-5.6 Sol Thinking),
26 unique recommendations across four sections
**Companion plan:** [`docs/specs/graph-engineering-adoption.md`](../specs/graph-engineering-adoption.md)
**Method:** every claim below is either a command run against this checkout or a `file:line`
citation read directly. Where the report asserts a repository fact, this review re-derives it
rather than accepting it. Four `openspec-peer-review` personas (Architecture, SDLC/CI Lead,
QA Director, Product) are applied in §5.

> **Scope note.** Every statement below is a command run against this checkout or a
> `file:line` read; none is a claim about branch rulesets or repository settings, which this
> review did not query. `make ci` was **not** run in full — the environment has no `pnpm` and a
> flaky package index — so per `CLAUDE.md`'s DEC-024 rule nothing here is a passing-gate claim;
> the check runs on the pushed head are. The Python suite *was* run on this branch after the
> `main` merge, and §7 S-6 records what it caught.

---

## 1. Summary verdict

The report is **substantially correct in diagnosis and substantially wrong in sequencing.**
Its central thesis — that this repository is already a graph system that does not treat its
graphs as verifiable artifacts — survives contact with the code. Its top-ranked recommendation
does not.

| # | Report's position | Verdict | Basis |
|---|---|---|---|
| 1 | Static verification of the LangGraph `StateGraph` should become the first CI gate (INV-18) | **Rejected as sequenced** | `DEC-053` (accepted, 2026-09-05) parks `harness/shared/langgraph/`. The technique is right; the target is scheduled for `experimental/`. §2 |
| 2 | A code-property graph would cut agent token cost | **Accepted, re-scoped** | Correct, but the report proposes a new Tree-sitter ingestion pass while `execute_generate_code` already holds a parsed AST at the governed write door. §4.3 |
| 3 | Governance policy is naturally a reachability graph | **Accepted, promoted to first** | The chain is real and live: `@with_authority` → `ACTIVE_TO_CANONICAL` → `allowed_actions` → `TOOL_REQUIRED_ACTION`. Today it is checked by unit tests over endpoints, never over paths. §3.1 |
| 4 | Graph-driven regression test selection | **Deferred, unchanged** | Correct that it is a near-free derivative of (2). Wrong that it is urgent — see the QA persona, §5.3. |
| 5 | Traceability belongs in a graph, not glob-scoped scripts | **Diagnosis accepted, prescription rejected** | The glob defect is real and worse than stated: the gate reads 6 IDs and **412 are disjoint from them**. The fix is a `--workspace` flag `DEC-056` already schedules, not a graph database. §4.1 |
| 6 | Evidence manifests form a provenance DAG | **Accepted, low priority** | Structurally true; no defect demonstrated. |
| 7 | Learned topology optimization (GPTSwarm / G-Designer) | **Accepted as parked** | The report's own caution is correct and matches `DEC-027`. |

**Findings all three models missed** are in §4. The most consequential is §4.1: a governance
gate that prints `traceability: passed (6 requirements)` while 412 requirement IDs — a set
sharing not one member with those six — go unread.

---

## 2. The finding that inverts the top recommendation

All three models independently ranked LangGraph static verification first or second. All three
were reading `harness/shared/langgraph/graph.py` and none of them read `docs/decisions/DEC-053.md`.

```
$ sed -n '1,4p' docs/decisions/DEC-053.md
id: DEC-053
title: "`harness/shared/langgraph/` is parked under `harness/shared/experimental/langgraph/` with PEP 562 sh"
status: accepted
```

DEC-053 considered exactly the move the report recommends and rejected it by name:

> Options considered: (A) promote LangGraph to the live runtime — apply limits, checkpointer,
> interrupts, and replace the sequential loop — **rejected** until a dedicated revival spec
> exists […]; (B) park under `harness/shared/experimental/langgraph/` with PEP 562 shims and a
> named sunset — **chosen**

And it named the cost the report's proposal would increase:

> Further Phase-5 product wiring […] would deepen a half-done stack that already costs an
> optional extra, coverage carve-outs, deselection env, and **protected-path attestation on
> every PR**

Four independent facts confirm the park is the correct read of the code, not merely a document:

1. **The only caller is itself experimental.**
   ```
   $ git grep -ln 'build_graph' -- '*.py' | grep -v tests/
   harness/shared/experimental/autonomous_healing.py
   harness/shared/langgraph/__init__.py
   harness/shared/langgraph/graph.py
   ```
   The live runtime is `harness/shared/orchestrator/loop.py:38` (`ExecutionLoop`) — a
   sequential loop, not a graph. Nothing in the production path compiles a `StateGraph`.

2. ~~**The gate could not run on a third of the CI matrix.**~~ **Withdrawn — this fact expired
   during review.** It read: the matrix is `["3.9","3.10","3.12"]` and langgraph declares
   `Requires-Python >=3.10`, so the 3.9 leg sets `MANGO_CI_DESELECT_LANGGRAPH: 1`; a gate that
   compiles the graph is absent on the oldest supported interpreter. PR #118 (`R-RHI-1`,
   `docs/specs/python-floor-310.md`, superseding DEC-028) landed on `main` while this review was
   being written and moved the floor to 3.10 with the matrix `["3.10","3.12","3.14"]`. No leg
   sets the deselect variable any more — the policy key at `governance-policy.json`
   `coverage.optional_extras.langgraph.deselect_env` survives it and is now inert — so langgraph
   installs everywhere and this objection is dead.

   Stated rather than quietly edited, because it is this review's own DEC-024 moment: the claim
   was true when written, checked against the checkout, and false three hours later. §7's S-3
   is the same lesson about a number; this is the version about a fact. **The inversion in §2
   stands on the other three points and on DEC-053 itself, which is still `status: accepted`,
   `superseded_by: null` after the merge.**

3. **`harness/shared/langgraph/**` is a protected path**
   (`governance-policy.json` → `protected_paths`, 82 entries). Every PR touching it needs the
   `infra-reviewed` attestation table.

4. **The report's proposed dependency is not present.** `import networkx` fails in this
   checkout, and networkx appears in no requirements file. "No new dependency beyond NetworkX"
   is a contradiction in a repo with a hashed `requirements-lock.txt` (216 KB) and a `lock-check` gate.

**This does not retire the idea.** Section 6 of the companion plan re-points it. The
observation that makes it survivable: *the interesting property is not LangGraph-shaped.*
"Every path from entry to a write-capable node passes a gate" is a statement about the
authorization chain, and that chain is live, unparked, and today has no path-level check at all.

---

## 3. Claim-by-claim grounding of what the report got right

### 3.1 The governance authorization chain is a real graph, and it is real code

The report calls this "policy-as-graph" and cites IAM reachability literature. In this
repository the graph is not a metaphor — every edge is a Python object:

| Edge | Source | Shape |
|---|---|---|
| node → active role | `harness/shared/langgraph/nodes.py:89,143,204` | `@with_authority("planner" \| "nemotron-reasoner" \| "verifier", may_write=…)` |
| active role → canonical role | `harness/shared/agent_authority.py:34` | `ACTIVE_TO_CANONICAL` — 3 active → 7 canonical |
| active role → execution identity | `agent_authority.py:48` | `EXECUTION_IDENTITY` |
| canonical role → action | `harness/shared/agent-policy.json` → `agents[].allowed_actions` | minus `human_approval_required_for` |
| tool → required action | `agent_authority.py:60` | `TOOL_REQUIRED_ACTION`, 7 tools |
| action → filesystem effect | `write_policy.py` / `read_policy.py` / `command_actions.py` | `protected_paths`, credential names, `.mango/memory/**` |

`allowed_actions` already implements a non-trivial graph operation and documents why
(`agent_authority.py:93-118`): the union across canonical roles **minus** each role's own
`human_approval_required_for`, because `verifier` maps to `release-auditor`, which grants
`external_write` and `production_change` *and* requires approval for both. A plain union would
hand the verifier production authority.

That subtraction is the exact class of defect flat-rule review misses and reachability analysis
catches. It was caught here — by hand, once, and pinned by a unit test. What is **not** pinned
is the general property: *no active role reaches a high-risk action by any composition of
edges.* `high_risk_actions` has five members
(`external_write`, `destructive`, `secret_access`, `permission_change`, `production_change`)
and `default_deny: true`, and the tests that guard them
(`test_agent_authority.py`, `test_governance_broker.py` — 48 test functions across the broker
file) assert endpoint outcomes, not path non-existence.

**This is the report's strongest recommendation and it ranked it third.** It should be first —
though §7's S-1 and S-2 substantially narrow *which* property is worth checking here. Computing
the graph rather than describing it showed that the grant half is largely covered already by
`validate_agent_policy.py:48-50`, and that the genuinely unasserted property is one level up:
whether any agent-controlled input can reach `policy_decision.decide`'s `human_approved` flag.

### 3.2 The orphan-node finding is real, known, and ungated

```
$ grep -c 'add_node' harness/shared/langgraph/graph.py
10
$ grep -n 'peer_reviewer\|security_reviewer' harness/shared/langgraph/graph.py
190:    builder.add_node("peer_reviewer", peer_reviewer_node)
191:    builder.add_node("security_reviewer", security_reviewer_node)
```

Two of ten nodes are registered with **no incoming edge and no outgoing edge**. The `findings`
channel is therefore empty on every run. DEC-052 says so in prose:

> Not closed here and named in the spec: `peer_reviewer` and `security_reviewer` are registered
> with no incoming edge, so `findings` is empty on every run

Meanwhile `test_langgraph_graph.py:341-352` asserts the node **set**, which both orphans
satisfy, and `EXPECTED_NODE_COUNT = 10`, which they also satisfy. The behavioural suite
therefore *pins the defect in place*: a fix that wires the reviewers in would not fail the test,
and a fix that deleted them would.

This is the report's best evidence for its own thesis, and it is stronger than the report
realised: the defect is not merely undetected, it is **asserted**. It is also exactly why §2's
rejection is about sequencing rather than merit — the check would work; it would just be
working on parked code, where DEC-052 has already decided the orphans stay until NS-31 closes.

### 3.3 Token economics: the direction is right, the number is unearned

The report cites 10× fewer tokens and 2.1× fewer tool calls from the Codebase-Memory paper and
then, to its credit, tells you to measure on your own repo before believing it. That caveat is
the load-bearing part and should be promoted from a clause to an acceptance criterion. This
repository's own `DEC-024` rule — *"a verification claim in prose is not evidence"* — applies
to imported benchmarks at least as strongly as to internal ones.

Concretely: the corpus here is 278 Python files. A 10× token reduction on a 278-file repo is a
different proposition from a 10× reduction on the corpus that paper measured, and the honest
prior is that the gain shrinks as the repo shrinks. The plan therefore makes the measurement
the gate, not the adoption.

### 3.4 Determinism vs. learned topology: correct, and already decided

The report's caution about GPTSwarm/G-Designer is right and needs no argument here, because the
repository already made this decision: `governance-policy.json` → `synthesis.lats_enabled:
false`, gated on an ablation that has not passed (INV-15), with `lats_optimizer.py` parked under
`harness/shared/experimental/` per DEC-027. The report's recommendation is to do what has been
done. No action.

---

## 4. What all three models missed

### 4.1 The traceability gate reads 6 of 412 requirement IDs

The report flags that "the repo's own globs don't reach root `docs/specs/`". That is true and
the magnitude is worse than implied.

`make validate` runs the gate from inside the Node stack (`Makefile:255`):

```
@(cd $(NODE_DIR) && $(PYTHON) ../shared/governance/check_traceability.py)
```

and the gate reads `TRACEABILITY_CONFIG = Path(".governance/traceability.json")` —
**CWD-relative** (`check_traceability.py:25`). So the globs that run are:

```
$ cat harness/node/.governance/traceability.json
{ "spec_globs": ["docs/specs/**/*.md"], ... }
```

resolved against `harness/node/`, not the repository root. Measured:

```
$ ls harness/node/docs/specs/*.md | wc -l                        # 2   — what the gate reads
$ ls docs/specs/*.md | grep -v SPEC_TEMPLATE | wc -l             # 35  — where the specs are
```

Unique requirement IDs on each side, and their intersection:

```
gate-visible (harness/node/docs/specs): 6
  C-AI-SEC-1, C-GOV-1, R-AI-NEMO-1, R-AI-NEMO-2, R-AI-RES-3, R-GOV-2
root docs/specs (excluding SPEC_TEMPLATE.md): 412
root IDs not in the gate-visible set:        412
```

The gate prints `traceability: passed (6 requirements)` and exits 0. **412 requirement IDs
across 35 specifications are never checked for implementation or test citation, and the two
sets are disjoint** — the gate is not checking a subset of the real corpus, it is checking a
different corpus.

This is the same defect shape DEC-024 and DEC-052 each recorded once: a check that passes for a
reason unrelated to what it claims to check. It is more severe than either, because
bidirectional traceability is the mechanism by which the `verifier` role is supposed to know
that a requirement was actually built. The gate's own docstring anticipates it —

> the common failure where a glob is scoped to one stack and silently checks nothing outside it

— and the gate still ships scoped to one stack.

**How much is actually broken.** Running the gate's own logic against root-scoped globs, with
the same `REQ` pattern and the same bidirectional rule:

```
$ python3 - <<'PY'   # gate logic verbatim, globs re-pointed at the repository root
unique requirement IDs across 35 specs: 412
unique IDs missing a citation:          271
PY
```

**271 of 412 requirement IDs have no implementation citation, no test citation, or neither.**

> **Read that number with §7's S-3 correction.** 83 of the 271 (31%) are declared *only* in
> roadmap documents, whose `R-SR-*` / `R-CQ-*` / `R-RHI-*` IDs name scheduled work rather than
> shipped behaviour, and 14 more are declared only in this PR's own plan. The contract-spec
> backlog is nearer **174**. The figure is also sensitive to the choice of
> `implementation_globs` and `test_globs` — the ones used here are `harness/**/*.py` plus the
> Node stack, reasonable but not authoritative.

What is not scope-sensitive is the direction: repairing the gate does not produce a green gate,
it produces a backlog — and, per S-3, one that a scope fix alone can never clear, because a
roadmap item has no implementation to cite until it is done. The companion plan therefore ships
the scope fix and a contract-spec/program-plan class distinction as one step, and sequences the
reconciliation immediately after, so its size is measured rather than assumed.

**The fix is not a graph.** DEC-056 already schedules `--workspace` on "the seven CWD-relative
gates" and a single root `.governance/`. Adding a graph database here would be building
infrastructure to work around a missing command-line flag. The plan treats this as a
prerequisite defect, not a graph deliverable — and notes the irony that the companion spec's
own ten requirement IDs are, at the time of writing, among the ones the gate cannot see.

**Anti-vacuity note.** The gate does have a `if not specs: raise SystemExit` guard and a
`if not ids: raise SystemExit` guard. Both pass. The failure mode is not "found nothing"; it is
"found the wrong two files". No emptiness check can catch that — only asserting a floor on the
discovered ID count, or fixing the scope.

### 4.2 `generate_code` already parses the AST the code graph would need

The report never mentions the code-generation tool, which landed on PR #116 nine days before
the report's head (`DEC-059`, `NS-38`, `docs/specs/code-generation-tool.md`). This is the single
best insertion point in the repository for a code graph, and all three models proposed building
a separate ingestion pass instead.

`harness/shared/tool_executors.py:144-206` (`execute_generate_code`) runs five checks in order —
workspace confinement, `write_denial_reason`, overwrite guard, **syntax validation**, length
bound — and only then writes. Syntax validation for Python is `ast.parse`. The tool therefore:

- holds a **parsed AST of every generated Python file**, at the moment of writing;
- discards it immediately after checking that it parsed;
- sits behind `authorize_write` and `TOOL_REQUIRED_ACTION["generate_code"] == "write"`, so
  every invocation is already authorized, logged, and confined.

Three consequences the report has no way to see:

1. **Incremental graph maintenance is nearly free.** The expensive part of a code graph is
   ingestion and staleness. A graph updated at the write door has neither: it is updated by the
   only governed writer, at write time, from an AST that was parsed anyway.
2. **The validation escalation is natural.** `validate_syntax` today answers "does it parse".
   The same AST answers "does it reach a symbol in `synthesis.prohibited_imports`", "does it
   call a symbol that exists", "does it add an edge into a protected module". That is a
   pre-write *semantic* gate, and it is the only place in the system where a defect can be
   stopped before bytes reach disk rather than after `make ci` goes red.

   A caution that only appears once you read the key rather than its name. Its five entries are
   `['os.system', 'subprocess', 'shutil.rmtree', 'importlib', '__import__']` — three shapes, not
   one. `subprocess` and `importlib` are importable modules; `os.system` and `shutil.rmtree` are
   attribute call targets reachable through a bare `import os`; `__import__` is a builtin that no
   import statement ever names. A checker built on `ast.Import` / `ast.ImportFrom` alone — the
   obvious reading of the key's name — would decide two of five and pass the other three, which
   is the §5.3 vacuity failure mode arriving through the front door. The companion spec makes
   covering all three shapes a requirement rather than an implementation note.
3. **The repository already has the AST discipline.** `ast_visitors.py`, `check_py_compat.py`,
   `check_projections.py`, and `test_constant_triage.py` (which "discovers only int/float module
   constants … by ast, not read from a hand-kept list") establish the pattern. A code graph
   built with `ast` is idiomatic here; one built with Tree-sitter is a new toolchain.

### 4.3 The repository's constraints make three of the report's substrate options illegal

The report's storage debate (Kùzu vs. Neo4j vs. NetworkX vs. SQLite) is resolved by constraints
none of the models enumerated:

| Constraint | Source | Consequence |
|---|---|---|
| Python floor 3.10 *(was 3.9 until PR #118)* | `pyproject.toml:4`, matrix `["3.10","3.12","3.14"]` | `check_py_compat.py` is still a gate, now against runtime-only 3.11+ constructs; its PEP 604 check is inert at this floor |
| Hashed universal lock + `lock-check` | `Makefile:362`, `requirements-lock.txt` (216 KB) | Any new dependency is a lock regeneration and an `audit` surface |
| Per-file coverage floor | `governance-policy.json` → `coverage.per_file: true`, `lines: 90`, `branches: 80` | A new module must carry ≥90% line coverage *on its own* |
| Per-file size budget | `limits.size_budget_lines: 500` / `test_size_budget_lines: 700` | No single-file graph engine |
| Every module-level numeric constant triaged | `test_constant_triage.py:341` | Any tuning number must cite a policy key or a `DEC-` id |
| `vulture` dead-code gate at confidence 80 | `Makefile` → `lint-python` | An unused public helper fails lint |

Net: **stdlib `ast` + a hand-rolled BFS, or nothing.** Not because minimalism is a virtue here,
but because a graph library is a lock entry, an audit surface, a py-compat risk, and a coverage
carve-out — four gates — to replace roughly forty lines of breadth-first search. The report's
GPT-5.6 position was right for reasons it did not state.

### 4.4 Counting errors in the report

Minor, but they matter for a document that will be cited:

| Report claim | Measured at `3fc9c3e` | Note |
|---|---|---|
| "431-commit" | `git log --oneline \| wc -l` → **296** | |
| "25-spec" | `ls docs/specs/*.md \| wc -l` → **33** | 32 excluding `SPEC_TEMPLATE.md` |
| "3,970 tests" | 2,595 `def test_*` across 152 files; parametrization plausibly reaches ~3,970 | Not contradicted; not verified — `pytest --collect-only` cannot run in this environment |
| "68 broker tests" | 48 `def test_` in `test_governance_broker.py` | The larger figure may span `test_agent_authority.py` + `test_policy_decision.py`; not reconciled |
| "37 LangGraph regression tests" | not verified — suite requires `langgraph`, absent here | |

### 4.5 The report's own recommendation would add a ninth required check to a set of ten

`governance-policy.json` → `ci_required_targets` has ten entries; `pre_pr_order` has eleven
stages; the pre-PR path is `make pre-pr` → `ci review lint-cold audit secrets`. `INV-5` requires
every `ci_required_target` to be reachable from `make ci` or declared as a gap
(`test_ci_gate_coverage.py`). Adding `verify-graph` is not a Makefile line: it is a policy
entry, an INV row in `harness/CONTRACT.md`, a `test_ci_gate_coverage.py` update, and three
protected-path attestations (`Makefile`, `governance-policy.json`, `harness/CONTRACT.md`).

None of the three models priced this. It does not change the answer for the authorization graph
— which is worth it — but it changes the answer for anything speculative, and it is why the plan
puts measurement before wiring.

---

## 5. Four-persona review of the report as a proposal

### 5.1 Architect

**Signs off with one boundary objection.** The dependency direction the report proposes for the
MCP code-graph tools is backwards for this codebase. `harness/shared/langgraph/decorators.py:5`
states the rule explicitly: *"They import **downward** into the existing governance layer —
nothing in the governance layer imports from this module."* A graph service that
`write_policy.py` or `agent_authority.py` had to import would invert that and make the
governance kernel depend on an analysis cache. The graph must be a **reader** of the governance
modules, never a dependency of them — which the plan enforces by making the authorization graph
a derived artifact recomputed from the same functions the broker calls, with no persistent
store at all.

Second objection, minor: `OBSERVATION_NODES` is deliberately a code constant, not a policy key
(DEC-052: *"a policy-driven security exemption list is one an adopter can widen to silently
disable the fail-closed behaviour"*). Any topology exemption list must follow the same rule, or
it becomes the widening surface that decision exists to prevent.

### 5.2 SDLC / CI Lead

**Blocks recommendation 1, approves recommendation 3.** Reasons in §2 and §4.5. Additional
deployment concern: the report proposes emitting witness traces signed through `EvidenceBuilder`.
That is a good instinct, but `harness/shared/governance/**` is a protected path and
`enforcement_digest.py` records a digest of every protected file before the first agent turn —
so an agent that modified the evidence builder to sign its own graph witnesses would trip
`enforcement_tampered`. Witness emission must be a *consumer* of evidence signing, added
outside `governance/`, or it is a change only a human can land.

### 5.3 QA Director

**Two objections, both about vacuity.**

First: every check the report proposes can pass for the wrong reason, and this repository has
already been bitten three times by exactly that (DEC-024's carried-forward claim; DEC-052's
`verdict in ("VERIFIED","FAILED","BLOCKED","")` assertion over the channel's whole domain;
§4.1's `traceability: passed (6 requirements)`). Specifically:

- A gate-coverage check is vacuous if the **write-capable node set is derived and comes back
  empty** — a renamed decorator silently makes "every path to a write node passes a gate" true
  by having no write nodes.
- A reachability check is vacuous if the **extractor returns zero edges** — an AST walker keyed
  on the local name `builder` breaks the moment someone writes `g = StateGraph(...)`.
- An exemption list is vacuous the moment an exemption **stops being needed** and nobody removes
  it.

Every one of these must fail closed, and the third must fail closed in *both* directions:
a listed-but-now-reachable node is as much a defect as an unlisted unreachable one. The plan
carries all three as explicit requirements rather than as implementation care.

Second: determinism. `make test-python` runs "in a seeded random order across every core", and
`INV-2` allows zero unapproved skips. Any graph check must be order-independent and must not be
`skipif`-gated on an optional import, or it becomes a skip in search of a waiver. Deriving the
topology from source text rather than from a compiled object satisfies both.

### 5.4 Product

**Rejects the report's framing of the user problem.** The report optimizes three cost centers —
topology correctness, token spend, CI wall-clock — and asks the reader to pick by measurement.
That is a reasonable framing for a generic repository and the wrong one for this one, because
this repository's product is *trustworthy verdicts*. `README.md`, `CLAUDE.md`, and
`harness/CONTRACT.md` all describe the same value proposition: a gate that cannot be talked
past.

Under that framing the three cost centers are not peers:

- **Token spend** is a cost of goods. Reducing it is good and changes nothing about what the
  product claims.
- **CI wall-clock** is a cost of goods. Same.
- **A gate that passes while checking 1.6% of what it claims to check** (§4.1) is a *defect in
  the product itself*. So is an authority chain whose safety property is argued in DEC-008 and
  DEC-012 rather than checked.

So the ordering falls out of the product, not out of a benchmark: fix the gate that lies, then
make the authority argument machine-checked, then optimize cost of goods. The report's
"measure all three baselines first" is good advice applied to the wrong set — two of the three
are optimizations and one is a bug.

---

## 6. What this review recommends

Ordered, with the reasoning in the companion plan
([`docs/specs/graph-engineering-adoption.md`](../specs/graph-engineering-adoption.md)),
where each decision is argued Thesis → Counter-Argument → Rebuttal.

| Order | Work | Why here | Report's rank |
|---|---|---|---|
| 0a | Pin the orphan reviewers to DEC-052 as a plain test | Live in the tree today, depends on nothing, costs one test file (§7 S-4) | not proposed |
| 0b | Fix the traceability scope **and** classify the corpus | A gate that lies is a defect, not an optimization. The scope fix alone cannot go green (§7 S-3) | not proposed |
| 1 | Reachability of `decide()`'s `human_approved` from agent input | Holds by construction in one dict literal, asserted nowhere (§7 S-2) | 3rd, and aimed at the wrong half |
| 2 | Pre-write semantic validation on the AST `generate_code` already parses | The only place a defect can be stopped before bytes hit disk | not proposed |
| 3 | Static topology verification, retargeted at the *live* orchestrator and re-pointed at LangGraph only if NS-31 revives it | Technique is sound; DEC-053 makes the original target wrong | 1st |
| 4 | Read-only code graph + MCP tools, adopted only if measured on this corpus | Real but unproven gain; the measurement is the gate | 2nd |
| 5 | Test-impact selection | Free derivative of 4; no independent case | 4th |
| 6 | Learned topology optimization | Already decided: parked (`lats_enabled: false`, DEC-027) | parked |

**Net assessment of the report.** It is a good document that would have been a much better one
with `docs/decisions/` in its context window. Its diagnosis is sound, its literature is
apposite, and its instinct to defer to the repository's determinism ethos is correct. Its
ranking is wrong because it read the code and not the decisions — which is, appropriately
enough, the exact failure mode a queryable graph over this repository's own governance artifacts
would prevent.

---

## 7. Review of this review

The sections above were written from reading. This section was written after *computing* the
graph §3.1 proposes — building the authorization graph by hand from
`ACTIVE_TO_CANONICAL`, `agent-policy.json`, and `TOOL_REQUIRED_ACTION` and asking it the
questions the companion plan's acceptance criteria ask — and then, in S-6, after CI answered
back. Six findings, five of them against this review and its plan rather than against the report.

The pattern in S-1 through S-5 is the same one §5.3 warned about, arriving from the inside: **a
check that passes for a reason unrelated to what it claims to check.** Naming that failure mode
in a persona review turns out to be no protection against committing it four paragraphs later.
S-6 is the complement: a check that failed for exactly the reason it claims to check, and caught
this document.

### S-1 · `AC-GEA-2` is 60% vacuous, and the plan does not say so — *Major*

The criterion asserts that `reachable_actions("verifier")` excludes every member of
`high_risk_actions`. Computed:

```
destructive          declared_by= -- NOBODY --          approval_gated_on=[]
external_write       declared_by= ['release-auditor']   approval_gated_on=['release-auditor']
permission_change    declared_by= -- NOBODY --          approval_gated_on=[]
production_change    declared_by= ['release-auditor']   approval_gated_on=['release-auditor']
secret_access        declared_by= -- NOBODY --          approval_gated_on=[]
```

Three of the five high-risk actions are declared by **no canonical role at all**. The criterion
passes for those three for a reason that has nothing to do with reachability — there is no edge
to traverse — and the mutation proof it specifies (revert the `human_approval_required_for`
subtraction in `allowed_actions`) cannot move them. The property is non-trivial for
`external_write` and `production_change` only, both through the single
`verifier → release-auditor` edge.

Worse, the half that *is* non-trivial is **already enforced**. `validate_agent_policy.py:48-50`:

```python
unapproved = high.intersection(allowed) - set(approvals)
if unapproved:
    raise SystemExit(f"agent-policy: {rid} high-risk actions lack human approval: …")
```

So `R-GEA-2` as written proposes a graph to re-derive a property a nine-line gate already
decides. That is not worthless — the graph would catch it across *composition* where the gate
checks one file — but the plan claimed a gap that is mostly closed.

### S-2 · The property actually worth checking is one level up — *Major*

Why the three actions are ungranted turns out to be the interesting part. `destructive`,
`permission_change`, and `secret_access` are not grant-vocabulary at all: they are what
`command_actions.classify` **produces** from a command name — `rm` → `destructive`, `chmod` →
`permission_change`, `env` → `secret_access`, with `UNCLASSIFIED_ACTION = "destructive"` so an
unmodelled command fails closed. `high_risk_actions` mixes both vocabularies in one namespace.
Their absence from every role's `allowed_actions` *is* the denial: `decide()` returns
`DENY, "action 'destructive' is not granted to …"` by absence, which is `default_deny: true`
operationalised.

Which relocates the real question. `decide()` takes `human_approved`, and a `True` there is the
one argument that turns a high-risk denial into an ALLOW. Tracing every non-test setter:

```
broker.py:133   human_approved = context.get("human_approved", False) is True
broker.py:166   verdict = decide(agent_id, required, policy, human_approved=human_approved)
tool_executors.py:384   "context": {"agent_id": execution_identity(active_role)}   # no such key
```

The agent path cannot reach the flag: `execute_run_command` builds the context as a literal
dict, the only agent-controlled input is `command`, and that goes to `classify()`, not to
`context`. The identity check (`is True`, with a comment explaining why `bool("false")` makes
truthiness wrong) is a second defense.

**The property holds. It holds by construction, in one dict literal, and nothing asserts it.**
`broker.execute_command(command, **kwargs)` makes threading a caller-supplied context
syntactically easy, and no test would go red. *That* is a path property — agent input to
privileged flag — and it is what `R-GEA-2` should target instead of the grant graph.

### S-3 · This review's own headline number is inflated for the use it was put to — *Major*

§4.1 reports 271 of 412 requirement IDs missing a citation. The figure is what the gate's logic
produces, but presenting it as a citation backlog overstates it. Counting each unique ID once and
attributing it only where it is declared *exclusively*:

| Source | Unique gapped IDs |
|---|---|
| declared only in roadmap documents — `2026-standards-remediation-plan`, `reflection-hardening-increment`, `code-quality-tech-debt-plan`, `god-file-decomposition`, `tech-debt-hardening-plan` | **83 (31%)** |
| declared only in `graph-engineering-adoption.md` (this PR's own plan) | 14 |
| remainder — contract specs | **~174** |

`R-SR-*`, `R-CQ-*`, and `R-RHI-*` are roadmap items. A requirement that says "park LangGraph" has no
implementation file to cite until it is done, and citing it in a test would be meaningless.
Quoting 271 without that split is the same species of unearned number this review criticised the
source report for in §3.3.

The correction matters beyond arithmetic, because it exposes a design defect in `R-GEA-1`:
**re-scoping the globs alone produces a gate that can never go green** while any planned-but-undone
work lives in `docs/specs/`. Step 1 needs a class distinction between contract specs and program
plans that neither the current gate nor the plan has. Without it, fixing the scope trades a gate
that lies for a gate that cries wolf, and the second gets switched off.

### S-4 · `R-GEA-6` commits the conflation `D-5` dissolved — *Moderate*

`D-5`'s rebuttal concluded that the choice is not "gate or no gate" but *which enforcement
surface*, and that pure functions over repository state belong in the test suite where `INV-2`
already governs them. `R-GEA-6` then says a topology checker "MUST NOT be wired into any CI
target while `DEC-053`'s park stands" — and `AC-GEA-9` tests for its absence. That forbids the
gate and the plain test alike.

It matters because the park is **decided but not executed**:

```
$ ls harness/shared/experimental/          # __init__.py autonomous_healing.py lats_optimizer.py
$ test -d harness/shared/langgraph && echo STILL THERE    # STILL THERE
```

Phase E is blocked on NS-2 — a credential rotation requiring a human at a provider, open since
at least 2026-09-05, and NEXT_STEPS is explicit that "DEC-053…056 are logged; they do not lift
this gate." So `findings` stays empty on every run, and `test_langgraph_graph.py` keeps pinning
it, for an indefinite period during which this plan forbids even noticing.

The fix is small and follows `test_constant_triage.py`'s precedent exactly: a plain test
asserting the two reviewers are edgeless **and that this is DEC-052's recorded state**, which
goes red both when someone wires them in without updating DEC-052 and when someone deletes them
silently. One test file, no protected path, no new gate, no attestation.

### S-5 · `AC-GEA-3`'s witness paths are narrower than the criterion implies — *Minor*

Eight of the eleven declared actions are exercised by no tool:

```
declared (11): delegate evidence_write external_write plan production_change read
               review_write security_scan spec_write test_execute write
tool-required (3): read test_execute write
```

So role→tool witness paths exist only for `read`, `write`, and `test_execute`. Related, and
worth stating rather than discovering later: each active role has **two** grant surfaces that
deliberately disagree — `allowed_actions` (tool exposure) and `EXECUTION_IDENTITY` (what the
broker asks the PDP about). `planner` holds `spec_write` but executes as `orchestrator`, which
lacks it; `verifier` holds `review_write` and `security_scan` but executes as `test-eval`, which
lacks both. A reachability check over the wrong surface returns a confident wrong answer, and
`R-GEA-2` names only one of the two.

### S-6 · CI caught this review with a gate the review did not know existed — *Major, and the most instructive*

The first push of this document turned all four `build` legs red. One assertion, on every leg:

```
FAILED harness/shared/tests/test_documentation_claims.py::TestEveryReportIsIndexed::
       test_the_index_matches_the_directory
  harness/README.md indexes [...11 reports...]
  but docs/reports/ holds [...12, including '2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md']
1 failed, 4176 passed, 1 skipped
```

`harness/README.md` carries a prose index of `docs/reports/`, and
`test_documentation_claims.py:315` asserts that index equals the directory. Adding a report
without indexing it is a CI failure. The fix is one filename in one sentence.

Three things make this worth a numbered finding rather than a footnote.

**It is the exact inverse of §4.1.** That section's whole argument is that this repository has a
gate reading a corpus it was not aimed at, passing on 6 IDs while 412 go unread. `TestEveryReportIsIndexed`
is the same *kind* of check — documentation claim against directory reality — aimed correctly,
failing closed, and catching a real drift within minutes. The repository is not uniformly weak
at this; it is strong at it in the places someone thought about, and §4.1 is a place someone did
not. A review that reported only the failure would have mischaracterised the codebase.

**The local gate run that "passed" was not the gate.** §4 of this document lists four validators
run locally, all green — `validate_plan`, `validate_specs`, `validate_invariants`,
`validate_governance_docs`. None of them is `make ci`, and the failing assertion lives in the
pytest suite that `coverage-python` runs, which the local environment could not execute at the
time. The PR body said so explicitly, which is the only reason this is a caught defect rather
than a false claim — but "I ran the validators" was still doing rhetorical work that "I ran the
gate" would have earned. `CLAUDE.md`'s rule is that a verification claim in prose is not
evidence; the sharper form this incident teaches is that **a partial verification reported
without naming what it omits reads as a total one.**

**A graph would not have caught it, and that is the honest limit.** The dependency here is
`docs/reports/*.md` → a prose sentence in `harness/README.md`. No call graph, no import graph,
and no code-property graph contains that edge. It is a documentation-consistency invariant,
enforced by a hand-written test that someone had to think of — exactly the kind of thing the
source report's graph-first framing has nothing to say about. The graph is the right tool for
§4.2's write door and §7's S-2 approval flag. It is not a general solvent, and a review
advocating for it should say where it stops.

### What survives

§2's inversion stands: DEC-053 is accepted, unsuperseded, and the report's top recommendation
still lands on it. §4.1's defect stands — the gate reads a disjoint corpus — with the magnitude
corrected. §4.2 stands unchanged. §4.3's constraint table stands.

What does not survive unamended is this review's own plan, in four places, and the corrections
are in the companion spec's revision 2 rather than left as prose here. The exercise is worth
generalising: **every finding in S-1 through S-5 was produced by executing the plan's own
acceptance criteria against real data rather than reading them.** None was visible from the
document. That is the argument for the graph, made against its own advocate — and it is also why
`R-GEA-4` (fail closed when the input set is empty) was the most valuable requirement in the
first draft, and the one this review then failed to apply to itself.
