# MangoMas_V2 → Mango Code Agent Harness: integration use cases

**Status:** Research (no implementation in this change)
**Date:** 2026-08-27
**Scope:** Answers "what are the best use cases for integrating functions from
`Mango-Metrics-NLM/MangoMas_V2` into this harness?", grounding the prior
multi-model research synthesis against the actual state of this repository.

---

## 1. Verified ground truth (this repo, this session)

The prior research rounds could not read either repository and flagged their own
specifics as memory-derived. This document re-verifies the harness side directly
from the working tree at `main` (merge of PR #7):

| Research claim | Verified reality |
|---|---|
| Open PR stack #4→#5→#6 blocks integration sequencing | **Resolved.** The stack was consolidated and merged to `main` via PR #7 (`76bd06e`). The "merge first" precondition is already satisfied. |
| Dynamic `COV_MIN` at 92.32% | Policy is **90%** lines/statements/functions, **80%** branches, `per_file: true` (`harness/shared/governance-policy.json`); the Makefile reads it dynamically with an 80 fallback. |
| 3-active vs 7-canonical agent-contract drift | The mapping is now **documented and reconciled** in `.mango/agents/README.md` (planner / nemotron-reasoner / verifier ↔ 7 canonical contracts in `harness/shared/agents/`). The drift *class* still exists — reconciliation is by prose + test, not by packaging. |
| Protected-path firewall + `ALLOW_GITHUB_CHANGES=1` prose attestation | Confirmed as implemented (`CONTRACT.md`, `validate_invariants.py`, fail-closed incl. untracked files). The attestation is still an env var + PR prose — the weakest control. |
| External root of trust is future work | **Partially built.** `harness/control-plane/` already has `verify_repository.py`, a digest-pinned `policy-bundle.example.json`, `regenerate_bundle_digests.py` (wired into `make ci`), and a `tool_broker_reference.py`. |
| MangoMas_V2 internals (ten-cell taxonomy, MoE router, etc.) | **Still unverified.** `add_repo` for `Mango-Metrics-NLM/MangoMas_V2` is rejected (cross-owner session restriction). The only public artifact remains the `ianshank/MangoMAS-MoE-7M` model card. Every cell-level claim below is therefore conditional on what the repo actually contains. |

**Existing integration surface in this harness** (where MangoMas functions would
plug in):

- `harness/shared/mango_mas_orchestrator.py` — `MangoMASOrchestrator` ReAct loop:
  loads role prompts from `.mango/agents/*.md`, exposes `write_file` /
  `run_command` + `META_TOOLS_SCHEMA`, executes tools locally under hook
  guardrails (`.mango/hooks/block_dangerous.sh`, `loop_detection.sh`, …).
- `harness/shared/nemotron_bridge.py` — zero-dependency OpenAI-compatible model
  bridge; env-configured endpoint/model (`R-AI-NEMO-1`), secret masking
  (`C-AI-SEC-1`). Already the abstraction seam for model routing.
- `harness/shared/meta_tools.py` — `knowledge_gap_log` / `hypothesis_register`
  persisting to `.mango/memory/*.json` under file locks. This is the existing,
  bounded "memory" channel.
- `harness/control-plane/` — digest pinning + external verification skeleton.
- Gates: `make ci` (ruff, mypy, pytest+coverage, vitest, zero-skip verifier,
  governance validators, dedup drift check, digest regen).

---

## 2. Ranked use cases

Ordering applies the consensus principle all research rounds converged on —
**MangoMas proposes; the harness disposes** — plus the scaling-literature
caution that tool-heavy sequential coding work is the *worst* case for
multi-agent systems. Items 1–3 are net-positive even if no MangoMas cognition
ever ships; 4–6 are the cognition experiments, strictly gated.

### UC-1. Attested policy consumption (integrate *toward* MangoMas, not from it)

**What:** Publish `harness/shared/governance-policy.json` (+ `agent-policy.json`)
as a versioned, signed release artifact (`governance-policy@vX.Y.Z`,
build-provenance attestation). MangoMas_V2 pins the digest and consumes it
read-only as its planning constraint set. Replace the `ALLOW_GITHUB_CHANGES=1`
prose attestation with a signed, per-path, expiring exception record
(SLSA VSA style).

**Why first:** All three research rounds agree the policy is the enforcement
authority MangoMas must consume read-only. Nothing MangoMas produces is
measurable until the policy input is immutable and verifiable. This is also the
cheapest item: ~80% of the machinery (digest pinning, bundle build, CI digest
regen) already exists in `harness/control-plane/`.

**Existing anchor:** `build_policy_bundle.py`, `regenerate_bundle_digests.py`,
`make digest-regen` (already in `make ci`).

### UC-2. Closed SQE loop — MangoMas generates tests, harness executes and gates

**What:** MangoMas's SQE/test-generation function submits candidate tests; the
harness runs them under its own gates and returns structured failure evidence
(stack traces, coverage delta, validator output) as the retry signal. The
harness never accepts a MangoMas PASS claim — only its own gate output counts
(consistent with the verifier contract: "never marks PASS on inspection alone").

**Mandatory amendment (from the review round):** the current per-file 90%
coverage gate is gameable by an LLM test generator (comparable coverage,
~1/3 incorrect assertions in some reported categories). Before wiring any
generator to the gate, add two checks:
1. **Assertion-quality check:** every machine-authored test must fail against a
   deliberately broken build (mutation smoke test).
2. **Mutation score as the promoted gate**, coverage demoted to a diagnostic.
   Express both in the policy (UC-1 artifact), not in Makefile shell.

**Existing anchor:** `make coverage-python`, `verify_zero_skips.py` (INV-2
already blocks the "skip the failing test" failure mode), verifier role
contract, `validation-runner` skill.

### UC-3. Semantic task routing (MoE router) inside the model bridge

**What:** Use MangoMas's router function (the MoE-7M artifact is the one
publicly evidenced MangoMas component) as a *model/effort dispatcher* inside
`nemotron_bridge.py`: classify a task and select model tier / reasoning budget
before the planner→reasoner→verifier loop runs. This is exactly the already
planned Phase 2.1 "NVIDIA NIM multi-model routing" work item
(`NEXT_STEPS_PLAN_v2.md`), with MangoMas supplying the classifier.

**Why safe:** Routing chooses *which single agent/model runs*, it does not add
agents — so it sidesteps the multi-agent overhead findings entirely. Wrong
routing degrades cost/latency, not correctness, because every path still exits
through the same gates. Fallback: env-configured static model list (current
behavior) when the router is unavailable or low-confidence.

**Existing anchor:** `resolve_environment()` / `complete_chat()` in
`nemotron_bridge.py`; routing spec `R-AI-ROUTING-1`.

### UC-4. PlanningCell in shadow mode — the one cognition experiment

**What:** Run MangoMas's planning function *alongside* the incumbent `planner`
role: same task in, both plans logged, MangoMas grants **zero control** —
its plan is never executed. Compare over 30–50 oracle-checkable historical
changes. Report results as a (MangoMas digest, policy version) pair.

**Preregistered kill criteria (from the review round):** plan agreement ≥85%
with the incumbent on gate-relevant steps; wall-clock ≤2× and tokens ≤2×;
mutation score / defect recurrence must not worsen when a plan is promoted.
Given the −70% sequential-planning result in the scaling literature, a negative
outcome is the modal expectation — the experiment is designed so "harness stays
single-agent" is a cheap, decisive success.

**Existing anchor:** `MangoMASOrchestrator.execute_agent()` (add a shadow
producer next to `load_agent_prompt("planner")`); `.mango/memory/` JSONL is the
natural comparison log.

**Wire format:** a versioned `CognitiveSignal` envelope (schema version, run/
task/producer identity, evidence refs, policy tags, parent lineage) over a
subprocess JSONL boundary. `confidence` is logged as untrusted metadata and is
never a gate input.

### UC-5. Contract distribution — MangoMas *installs* the roles, never copies them

**What:** Package `.mango/` (7 canonical agent contracts, gate skills, the
`block_dangerous` / `loop_detection` / budget hooks) as an installable plugin
that MangoMas_V2 consumes as a pinned dependency. The 3-vs-7 drift fixed in the
Phase 1 work is currently held closed by a README mapping plus a test; the
moment a second repo holds copies, the drift class reopens. Distribution
replaces synchronization.

**Trigger discipline:** per the repo's own third-recurrence rule — if contract
drift reappears at a new site after the documented reconciliation, that is the
signal to stop patching and package.

### UC-6. Evidence/episode telemetry via an OTel adapter

**What:** Emit a per-run episode bundle (plan, tool calls, gate outputs,
artifacts, usage) using the OTel GenAI `plan` / `execute_tool` / `invoke_agent`
vocabulary — but **behind a one-file translation adapter**, never as a direct
dependency: no `gen_ai.*` attribute is Stable, the conventions moved to a
separately versioned repo (v1.42.0) and `invoke_agent` was already split
(v1.41.0). This is planned Phase 4.2 (`R-OBS-1`); MangoMas consumes the same
episode schema so both sides describe runs identically.

---

## 3. Anti-use-cases (explicitly do not integrate)

1. **MetaCognitiveCell as reviewer/judge.** The checks it would perform —
   "claimed file change absent from diff", "success after skipped test",
   "criterion unmapped to evidence" — are pure functions over `git diff`, test
   JSON, and gate output. This harness already implements the pattern
   deterministically (`validate_invariants.py`, `verify_zero_skips.py`,
   `check_traceability.py`). LLM self-review without ground truth is the
   configuration the self-correction and self-preference-bias literature most
   directly contraindicates. If a judgment call is ever needed, use a different
   model family than the generator — the multi-model bridge (UC-3) makes that
   cheap.
2. **Full PM→SWE→SQE graph replacement of the loop.** Tool-heavy sequential
   coding is the empirically worst MAS profile; even centralized coordination
   still amplifies errors (4.4×). The three-role loop stays the incumbent;
   cells compete against it one at a time (UC-4).
3. **MemoryCell / LearningCell.** Disabled until retention, redaction, and
   rollback exist. The harness's bounded `meta_tools.py` JSON memory (explicit
   schema, file-locked, in-repo, reviewable) is the ceiling for now.
4. **A general-purpose bespoke tool gateway.** The protected-path firewall
   covers file mutation and stays; broad tool-call brokering, if ever needed,
   comes from the mature MCP-gateway category, not in-house code. (Kimi K3's
   caveat stands: the firewall is *not* a substitute for tool-call governance —
   it is simply the only enforcement point currently needed.)

---

## 4. Preconditions before any MangoMas code crosses the boundary

1. **License/SBOM inventory of MangoMas_V2 (Phase 0).** The repo sits under a
   different owner (`Mango-Metrics-NLM`) and remains unreadable from harness
   sessions (cross-owner `add_repo` rejected this session). Until its license
   is verified compatible, only the artifact/contract integrations (UC-1,
   UC-5, UC-6 schema) are safely buildable; any cell code may need a clean-room
   adapter.
2. **Boundary invariants as tests** (metamorphic, in the existing pytest
   idiom): changing a producer ID must not change granted permissions;
   removing evidence from an envelope must never raise completion confidence;
   with cognition disabled, harness behavior is byte-identical; no cell can
   reach a side-effecting tool (`write_file` / `run_command` are never in a
   cell's schema).
3. **Spec first.** Each UC is a `make spec NAME=<uc>` spec with acceptance
   criteria mapped to gates, peer-reviewed per `CLAUDE.md`, before
   implementation.

## 5. Suggested order

UC-1 → UC-2 (with the mutation-gate amendment) → UC-3 → UC-4 (single shadow
experiment, preregistered kill criteria) → UC-5 / UC-6 as they earn triggers.
Every step is independently valuable; the cognition bet (UC-4) is deliberately
last and killable.
