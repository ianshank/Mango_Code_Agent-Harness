# Deep peer review: graph engineering applied to this harness

**Reviewed head:** `main` @ `3fc9c3e` (2026-09-07, "fix(ci): restore main tip after #115")
**Subject under review:** the three-model synthesis "Graph Engineering Applied to
Mango_Code_Agent-Harness" (Claude Opus 5 Thinking / Nemotron 3 Ultra / GPT-5.6 Sol Thinking),
26 unique recommendations across four sections
**Companion plan:** [`docs/specs/graph-engineering-adoption.md`](../specs/graph-engineering-adoption.md)
**Method:** every claim below is either a command run against this checkout or a `file:line`
citation read directly. Where the report asserts a repository fact, this review re-derives it
rather than accepting it. Four `openspec-peer-review` personas (Architecture, SDLC/CI Lead,
QA Director, Product) are applied in §5.

> **Scope note.** This review does not have network access to the live GitHub API in this
> session, so it makes no claim about branch rulesets, run status, or PR state. Every
> statement below is about the checkout at `3fc9c3e`. `make ci` was **not** run — the
> environment has no `fastapi`, no `langgraph`, no `pnpm`, and a flaky package index. Per
> `CLAUDE.md`'s DEC-024 rule, nothing here should be read as a passing-gate claim.

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
| 5 | Traceability belongs in a graph, not glob-scoped scripts | **Diagnosis accepted, prescription rejected** | The glob defect is real and worse than stated: the gate reads 6 IDs and **380 are disjoint from them**. The fix is a `--workspace` flag `DEC-056` already schedules, not a graph database. §4.1 |
| 6 | Evidence manifests form a provenance DAG | **Accepted, low priority** | Structurally true; no defect demonstrated. |
| 7 | Learned topology optimization (GPTSwarm / G-Designer) | **Accepted as parked** | The report's own caution is correct and matches `DEC-027`. |

**Findings all three models missed** are in §4. The most consequential is §4.1: a governance
gate that prints `traceability: passed (6 requirements)` while 380 requirement IDs — a set
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

2. **The gate could not run on a third of the CI matrix.** The matrix is
   `["3.9", "3.10", "3.12"]` (`.github/workflows/python-package.yml:61`) and langgraph
   declares `Requires-Python >=3.10`, so the 3.9 leg sets
   `MANGO_CI_DESELECT_LANGGRAPH: 1` (line 102). A gate that compiles the graph is a gate
   that is absent on the oldest supported interpreter.

3. **`harness/shared/langgraph/**` is a protected path**
   (`governance-policy.json` → `protected_paths`, 82 entries). Every PR touching it needs the
   `infra-reviewed` attestation table.

4. **The report's proposed dependency is not present.** `import networkx` fails in this
   checkout, and networkx appears in no requirements file. "No new dependency beyond NetworkX"
   is a contradiction in a repo with a hashed `requirements-lock.txt` and a `lock-check` gate.

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

**This is the report's strongest recommendation and it ranked it third.** It should be first.

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

### 4.1 The traceability gate reads 6 of 382 requirement IDs

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
$ ls docs/specs/*.md | grep -v SPEC_TEMPLATE | wc -l             # 32  — where the specs are
```

Unique requirement IDs on each side, and their intersection:

```
gate-visible (harness/node/docs/specs): 6
  C-AI-SEC-1, C-GOV-1, R-AI-NEMO-1, R-AI-NEMO-2, R-AI-RES-3, R-GOV-2
root docs/specs (excluding SPEC_TEMPLATE.md): 380
root IDs not in the gate-visible set:        380
```

The gate prints `traceability: passed (6 requirements)` and exits 0. **380 requirement IDs
across 32 specifications are never checked for implementation or test citation, and the two
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
specs matched: 34 | impl files: 286 | test files: 191
requirement IDs discovered: 392
IDs with a missing citation: 251
PY
```

**251 of 392 requirement IDs have no implementation citation, no test citation, or neither.**
That figure is sensitive to the choice of `implementation_globs` and `test_globs` — the ones
used here are `harness/**/*.py` plus the Node stack, which is a reasonable but not authoritative
scope — so treat 251 as the order of magnitude, not the final number. What is not
scope-sensitive is the direction: repairing the gate does not produce a green gate, it produces
a backlog. The companion plan sequences that reconciliation second, before anything depends on
it, precisely so its size is discovered rather than assumed.

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
| Python floor 3.9 | `pyproject.toml:4`, matrix `["3.9","3.10","3.12"]` | No `match`, no PEP 604 at runtime; `check_py_compat.py` is a gate |
| Hashed universal lock + `lock-check` | `Makefile:362`, `requirements-lock.txt` (240 KB) | Any new dependency is a lock regeneration and an `audit` surface |
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
| 0 | Fix the traceability scope (6 IDs → the whole 386-ID corpus) | A gate that lies is a defect, not an optimization. Prerequisite: it is how every later requirement ID gets checked | not proposed |
| 1 | Authorization reachability over the live governance chain | Live, unparked, security-critical, no path-level check today | 3rd |
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
