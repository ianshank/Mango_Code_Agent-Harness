# Spec: reflection-hardening-increment

> Status: IN PROGRESS (Step 1/2 landed, `docs/specs/python-floor-310.md` /
> `DEC-064`; Steps 3-5 not started) · Date: 2026-09-07 ·
> Base: `main` @ `33f21044`
>
> **Spec class:** program-plan — the requirement IDs below name scheduled work, so the
> traceability gate counts and reports them without requiring an implementation citation
> until the work lands (see `docs/specs/graph-engineering-adoption.md`).
>
> This is a **ledger increment**, not a fourth from-scratch audit. Three prior
> program plans already ran the full-team reflection this request asks for:
> `docs/specs/tech-debt-hardening-plan.md` (29/29 boxes ticked, some selectors
> later corrected), `docs/specs/code-quality-tech-debt-plan.md` (CLOSED,
> superseded), and `docs/specs/2026-standards-remediation-plan.md` ("the
> remediation plan", IN PROGRESS, Phase B Done on PR #86, R-SR-5/AC-5 Done on
> PR #93). Re-deriving their findings would violate
> `.mango/skills/tech-debt-audit/SKILL.md`'s own rule: "run once and referenced
> every time instead." This document re-measures every open claim against
> `33f21044` (all commands below were run against that head, not copied from an
> older report), carries forward what is still true, drops what has already
> landed, and schedules only what remains a real defect.
>
> Two scope decisions were made by the repository owner before this document
> was written (recorded here because a decision without a record cannot be
> checked later): (1) write a new increment spec rather than continuing the
> remediation plan's own numbering or re-auditing from zero; (2) honor
> **DEC-053 (PARK)** for LangGraph — `harness/shared/langgraph/` moves under
> `harness/shared/experimental/` with deprecation shims, superseding no prior
> decision. Neither choice is re-litigated by this document.

## Context7 disclosure

Context7 MCP was queried three times while drafting this document
(`resolve-library-id` for `pytest`, `ruff`, and `GitHub Actions` documentation
purposes only, per instruction — never for implementation). All three calls
returned `Monthly quota exceeded`. No requirement or acceptance criterion below
is sourced from Context7. Implementers of each step below MUST retry
`resolve-library-id` / `query-docs` once for the tool that step touches
(ruff/mypy for Step 1, GitHub Actions for Step 3) before falling back to the
official upstream docs URL, and MUST cite whichever source actually answered
the question in that step's PR description — Context7 is for reading
documentation, never for generating product code (user instruction, repeated

**Step 1 retry (2026-09-07, at implementation time).** `resolve-library-id`
was retried for both `Ruff` and `mypy`; both again returned
`Monthly quota exceeded`. Falling back per this section's own instruction:
Step 1's ruff/mypy claims (`target-version` deriving from `requires-python`
when unset; `mypy` 2.3.1 installing and running under `warn_unused_ignores`)
were verified empirically against this repository's own toolchain —
`python3 -m ruff check .` / `python3 -m ruff format --check .` and
`python3 -m mypy --version` run against the changed `pyproject.toml`,
not read off an upstream docs page — because the tools themselves are the
authoritative source for "does this exact pinned version behave this way,"
and a version-specific behavior claim checked against a different release
than the one this repository pins would be weaker evidence than running the
pinned release directly.
in `CLAUDE.md`'s spirit of "no hallucination, cite evidence").

## Problem statement

Every number below was measured directly against `33f21044` in this session,
not carried from an older report.

**1. Nine required-check names include one that cannot fail on a finding.**
`.github/rulesets/main.json` lists `dependency-audit (3.9)` as required
status check #7; `.github/workflows/python-package.yml:345` sets
`continue-on-error: ${{ matrix.python-version == '3.9' }}` on that exact job.
A required check that always reports success regardless of its own finding is
not a check (carries R-SR-23's finding H1, still true at this head).

**2. The Python floor is past EOL and forces two forked dependency pins.**
`pyproject.toml:4` still declares `requires-python = ">=3.9"` and
`pyproject.toml:89` pins `target-version = "py39"`. Python 3.9 reached EOL
2025-10-31 — over ten months ago relative to this document's date (corrected
at peer review from an earlier "nine months," which undercounted).
`requirements-dev.txt:10-11` forks `pytest==9.0.3` (`>=3.10`) against
`pytest==8.4.2` (`<3.10`); `:19-20` forks `pytest-randomly` the same way;
`requirements.txt:9` gates `mcp` itself behind `python_version >= "3.10"`, so
the floor interpreter cannot import the MCP server at all.
`harness/shared/check_py_compat.py:79` (`PEP604_MIN = (3, 10)`) exists only to
catch PEP 604 unions that work at runtime on 3.10+ and crash on 3.9 — a
compatibility check for one interpreter minor, with its own docstring naming
the exact prior incident ("a 3.9 job stayed green" while an import-time
annotation crashed). `requirements-dev.txt:38` pins `mypy==1.11.2` (August
2024) because mypy 2.x removed the `--python-version 3.9` flag entirely
(DEC-046 already records this fact; the floor is what keeps mypy frozen a
year behind).

**3. The reasoner persona still advertises tools the bridge does not have.**
`.mango/agents/nemotron-reasoner.md:5` frontmatter reads
`tools: Bash, Read, Grep, Glob, knowledge_gap_log, hypothesis_register`. The
tool bridge's actual registry, `NEMOTRON_TOOLS` in
`harness/shared/tool_schemas.py:19`, has no `Bash`, `Read`, `Grep`, or `Glob`
entries — those are Claude Code IDE tool names, not bridge function names.
`harness/shared/orchestrator/loop.py:110` (`load_agent_prompt`) reads this
markdown file verbatim, frontmatter included, into the Nemotron system prompt.
`docs/specs/reasoner-bridge-tool-parity.md` already scaffolds the fix
(R-RBT-1..5, AC-1..4) but is marked "Scaffolded (not implemented)" — a spec
that exists and sits unimplemented is exactly the "spec ceremony vs. real
defect" distinction this ledger exists to make, and grep confirms zero tests
name `test_reasoner_system_prompt_tools_match_bridge`,
`test_persona_tools_subset_of_nemotron_tools`, or
`test_model_call_logs_prompt_sha` anywhere under `harness/shared/tests/`.

**4. The Dockerfile still has three of the four defects the remediation plan
named (R-SR-25).** `Dockerfile:2` is `FROM node:26-alpine` — a floating tag,
no `@sha256:` digest. No `USER` directive exists anywhere in the file, so the
runtime stage runs as root. `Dockerfile:37-38` still declares
`EXPOSE 8080` for a `CMD` that is `node --loader tsx src/ai/nemotron/cli.ts
--help`, which prints usage and exits — nothing listens, so the exposed port
documents a lie. `.github/dependabot.yml` already added the `docker`
ecosystem (dated comment says so), but no entry anywhere in that file sets a
`cooldown:` key. `harness/shared/tests/test_dockerfile_contract.py` and
`test_dependabot_contract.py` do not exist (`ls` on both paths fails) despite
being named by the remediation plan's own AC-25.

**5. Protected-path attestation does not bind to the commit it approved.**
Grep across `harness/shared/tests/test_workflow_contracts.py` finds no test
selector matching `attestation_sha` or `protection_report`; the remediation
plan's own AC-24 says so and it is still open. A PR can carry an
`infra-reviewed` label and an attestation table from one commit, then take a
later, different push before merge — the label and the table do not know the
head moved (audit H3).

**6. One hard-coded threshold remains outside the policy in the orchestrator
loop.** `harness/shared/orchestrator/loop.py:123`:
`if not final_content.strip() and len(messages) > 3:` — a bare `3` gating a
fallback-response path, with no named constant and no policy key. It is not
in `governance-policy.json` under any key, and
`test_constant_triage.TestTheInventoryIsComplete` does not currently list it
(confirmed by reading the file; no `# noqa` or triage comment sits on that
line). Everything else the prior audits flagged in this file
(`max_iterations`, `api_timeout`, `max_tool_calls_per_task`) already resolves
through `policy_loader.orchestrator_defaults()` — this is the one survivor.

**7a. Peer review correction (2026-09-07).** An independent adversarial review
of this document's first draft, checking every file:line citation against the
tree rather than trusting the prose, found the evidence above to be correct
line-for-line, but found six citation/reference defects, corrected in place
below and listed here so a later audit does not re-derive them: (1) AC-1's
original text cited `test_ci_gate_required_checks.py` as the test that fails
when the ruleset still lists `dependency-audit (3.9)` — read directly, that
test only compares `NEXT_STEPS.md`'s prose sentence to the workflow's derived
check names and never opens `.github/rulesets/main.json`; the test that
actually asserts ruleset-required-contexts equal workflow-reported-checks is
`test_workflow_contracts.py::TestRulesetExportMirrorsTheWorkflow::test_required_contexts_are_exactly_the_reported_check_names`
(confirmed at `test_workflow_contracts.py:396`, reading `RULESET` at `:336`).
(2) AC-1's grep list omitted `requirements-lock.txt`, which pins
`--python-version 3.9` in its own regenerate-command header comment and
carries `python_full_version < '3.10'` / `>= '3.10'` fork markers throughout —
confirmed directly. (3) `harness/shared/tests/_workflow_paths.py:31` declares
`UNSUPPORTED_LEG = "3.9"`, consumed by
`test_workflow_contracts.py::TestTheUnsupportedLegDeselectsRatherThanSkips`
and by `test_dependency_lock_contracts.py::test_the_lock_carries_langgraph_behind_a_marker`
(`:96-102`, confirmed) — once every remaining leg can install `langgraph`,
this deselect/waiver mechanism becomes dead code; neither file was in the
original Files-touched list for Step 1/2. (4) Open question #2 originally
cited "`NEXT_STEPS.md`'s NS-4 open question" for the LangGraph sunset release
name — read directly, `NEXT_STEPS.md`'s NS-4 is the already-closed
Dependabot/DEC-031 item and has nothing to do with LangGraph; the real
citation is the remediation plan's own **Open Question 4**
(`2026-standards-remediation-plan.md:673-674`), which DEC-053 already quotes
verbatim. (5) C-RHI-3's precedent parenthetical named `plan_rules.py` as an
example of the DEC-035 split-by-seam pattern — read directly, DEC-035 split
`coverage_gate.py`/`coverage_scope.py` and never mentions `plan_rules.py`; no
decision-log entry does. (6) The Ledger's "Disposition here" column originally
mis-numbered which Step each gated item lands in (off by one against the
actual Steps section) and DEC-029 was described as flatly "Standing" when its
own frontmatter is `status: superseded, superseded_by: DEC-056` (DEC-020
alone is what stands; DEC-029's clause (2) is explicitly superseded). All six
are corrected at their point of use below; none changes this document's scope
or the Ledger's dispositions.

**7. Files at 94-96% of the size budget have zero headroom for the changes
this document schedules.** Measured directly (`wc -l`) against `33f21044`:
`harness/shared/langgraph/nodes.py` 481/500 (96%),
`harness/shared/meta_tools.py` 476/500 (95%),
`harness/shared/write_policy.py` 475/500 (95%),
`harness/shared/governance/command_actions.py` 471/500 (94%),
`harness/shared/orchestrator/loop.py` 397/500 (79%, but Step 2 edits it).
`harness/shared/tests/test_mcp_server.py` is 686/700 (98%) — the tightest
margin in the tree. No production file exceeds the 500-line ceiling today;
`harness/shared/mango_mas_orchestrator.py` (the file the closed
`god-file-decomposition.md` spec was written against) is now 204 lines, so
that spec's own concern is resolved and stays closed. This item is a
**pre-condition on Steps 2 and 3**, not a standalone requirement: a step
whose edit would cross 500 lines on a watch-list file splits that file in the
same PR, by seam, per the DEC-035 split-by-defect-seam pattern (see C-RHI-3
for the precise precedent and its correction).

**8. What is intentionally not re-opened here.** DEC-020 (accepted, standing:
no regroup of `harness/shared/`) — DEC-029 restated the same "no regroup"
position but is itself `status: superseded, superseded_by: DEC-056`
(confirmed by reading its frontmatter); this document treats DEC-020 as the
live authority for "no regroup" and does not rely on DEC-029's superseded
text for anything. The closed plan's ceremony items (R-CQ-19,
R-CQ-20, R-CQ-21's fixture-dedup rule, R-CQ-24 marker liveness, R-CQ-26
pre-emptive splits, R-CQ-27 archive index, R-CQ-28 `Status:` tier rule,
R-CQ-31 mutation-prose assertions) — the remediation plan's own "Explicitly
not doing" section already disposed of these with reasons, and re-scheduling
them here without a new defect behind them would be exactly the "inventory or
ceremony with no defect behind them for a single maintainer" the remediation
plan warns against. SBOM, an OpenAPI snapshot, and a formal threat-model
document remain absent and remain a **recorded gap**, not a requirement — each
is a product decision needing an owner call this document does not make.

### Ledger — every remaining remediation-plan item, one disposition each

| Remediation-plan ref | Current state at `33f21044` | Disposition here |
|---|---|---|
| AC-1 (ruleset import) | `GET .../rules/branches/main` not re-queried in this offline session; NEXT_STEPS.md NS-1 still open | **Owner action.** No code changes this. |
| AC-2 (credential rotate) | `feature/governed-run-console` branch state not re-queried; NS-2 still open | **Owner action; hard gate on Phase E.** |
| AC-3 (LICENSE) | `ls LICENSE` fails | **Owner action** (NS-30). This document adds no licence text. |
| AC-4 (`v2.4.0` tag) | `git tag -l` is empty locally | **Owner action** (NS-3). |
| AC-23 (Python ≥3.10) | Confirmed still `>=3.9`, forked pins, `continue-on-error` 3.9 audit live | **Done: Step 1/2**, `docs/specs/python-floor-310.md`, `DEC-064`. |
| AC-24 (attestation SHA binding) | No matching test selector found | **Scheduled: Step 4**, minus `required_signatures` (needs NS-1 first). |
| AC-25 (Dockerfile + Dependabot cooldown) | 3 of 4 sub-defects confirmed live; contract tests absent | **Scheduled: Step 4.** |
| AC-26 (JVM relocate) | `harness/jvm/` present, 49 files | **Gated on NS-2** (DEC-054). Not started here. |
| AC-27 (LangGraph park) | `harness/shared/langgraph/` present and live, `nodes.py` at 96% of budget | **Gated on NS-2** (DEC-053, owner-confirmed PARK). Recorded in Phase E below; not started here. |
| AC-28 (openspec fold) | `openspec/changes/*` present, 3 proposals | **Gated on NS-2** (DEC-055). Not started here. |
| AC-29 (mirroring collapse) | Per-stack shims still present by design (DEC-004) | **Gated on NS-2** (DEC-056), last in Phase E order. |
| NS-18 (reasoner/bridge parity) | Spec scaffolded, zero implementing tests | **Scheduled: Step 3**, implementing the existing scaffold verbatim. |
| Orchestrator `len(messages) > 3` | Confirmed live, untriaged | **Scheduled: Step 5.** |
| R-CQ-19/20/21/24/26/27/28, retry-parity, fixture-dedup | Explicitly dropped by the remediation plan | **Stays dropped.** Not re-derived. |
| DEC-020 (no `harness/shared/` regroup) | `status: accepted`, standing | **Stands.** No package split in this document. |
| DEC-029 (restated the same position) | `status: superseded, superseded_by: DEC-056` | **Not relied upon.** DEC-020 alone carries "no regroup" here. |
| SBOM / OpenAPI snapshot / threat model | Absent | **Recorded gap.** Not scheduled; needs an owner product decision first. |
| HITL / OS sandbox / `mutmut` score / LATS wiring | Parked in `NEXT_STEPS.md` §4 | **Stays parked.** Out of scope. |

## Requirements

### Phase 1 — agent-executable now (this document's scope)

- R-RHI-1: `pyproject.toml`'s `requires-python` MUST become `>=3.10`; the 3.9
  CI matrix leg, the `continue-on-error` 3.9 audit step, the required-check
  name `dependency-audit (3.9)`, both forked `python_version < "3.10"`
  dependency pins, the `mcp` 3.10 gate (now unconditional),
  `check_py_compat.py`'s PEP 604 minimum-version check,
  `requirements-lock.txt`'s `--python-version 3.9` regenerate-command header
  and its `python_full_version` fork markers, and
  `harness/shared/tests/_workflow_paths.UNSUPPORTED_LEG` (with its two
  consuming tests, `test_workflow_contracts.py::TestTheUnsupportedLegDeselectsRatherThanSkips`
  and `test_dependency_lock_contracts.py::test_the_lock_carries_langgraph_behind_a_marker`)
  MUST all be deleted rather than re-homed, matching the remediation plan's
  own R-SR-23 shape; `ruff`'s `target-version` MUST be removed so it derives
  from `requires-python`; `mypy` MUST move to a current 2.x release with
  `warn_unused_ignores = true`; Python 3.14 MUST join the build matrix. A
  child spec (`make spec NAME=python-floor-310`) supersedes DEC-028 before
  this lands, per the remediation plan's own precondition.
- R-RHI-2: The runtime system prompt assembled for every active role via
  `load_agent_prompt` MUST include a tool paragraph generated from that
  role's filtered `NEMOTRON_TOOLS` list (`tools_for_role`), never from a
  hand-maintained name list in persona markdown; YAML frontmatter MUST be
  stripped before assembly so IDE-only tool names (`Bash`, `Read`, `Grep`,
  `Glob`) cannot reach the model; every `model_call` structured-log event MUST
  carry `prompt_sha` (`hashlib.sha256` of the exact prompt bytes) and MUST NOT
  carry the prompt body. This requirement implements
  `docs/specs/reasoner-bridge-tool-parity.md` R-RBT-1..5 verbatim; it is not
  re-specified here beyond binding it to this document's Steps and files.
- R-RHI-3: The protected-path attestation table on a PR MUST bind to the head
  commit SHA it was written against; `build-full` MUST fail when the table's
  recorded SHA does not match the current head, so a later push invalidates a
  stale attestation. A scheduled job MUST query `/rules/branches/main` and
  open or update a tracking issue for as long as the response is empty,
  without itself importing the ruleset (that step stays NS-1, an owner
  action).
- R-RHI-4: `Dockerfile`'s `FROM` MUST pin the base image by
  `@sha256:<digest>` rather than a floating tag; the runtime stage MUST run
  under a non-root `USER`; the file MUST NOT declare `EXPOSE` for a port the
  `CMD` never listens on; the runtime `CMD` MUST NOT invoke the `tsx` loader
  (a dev dependency) — `tsc` already compiles the build stage, so the runtime
  stage runs the compiled output. `.github/dependabot.yml`'s `docker` entry
  MUST declare an explicit `cooldown`. Two new contract tests
  (`test_dockerfile_contract.py`, `test_dependabot_contract.py`) MUST exist
  and fail on a `tmp_path` copy of the file missing any one of these
  properties.
- R-RHI-5: `harness/shared/orchestrator/loop.py`'s bare `3` in
  `len(messages) > 3` MUST resolve from a named constant
  (`MIN_MESSAGES_BEFORE_FALLBACK` or equivalent) triaged in
  `test_constant_triage.py`, either as a module-level constant with a
  decision-log id or as a `governance-policy.json` key if the value is meant
  to be adopter-tunable; a present policy missing the key (if policy-sourced)
  MUST fail closed, matching every other Phase-B-hardened reader.
- C-RHI-1: No requirement above MAY re-home a Python-3.9-specific carve-out to
  a different guard; each MUST be deleted.
- C-RHI-2: No requirement above MAY widen any role's tool set relative to
  `agent_authority.tools_for_role` (carries R-RBT's own C-RBT-1).
- C-RHI-3: A watch-list file (≥90% of `limits.size_budget_lines` measured at
  the start of the step that edits it) that would cross the 500-line ceiling
  under a step's change MUST be split by seam in the same PR, with a re-export
  shim at the old import path, before the feature edit lands — never after,
  following the split-by-defect-seam precedent DEC-035 used for
  `coverage_gate.py`/`coverage_scope.py` (not `plan_rules.py`, which no
  decision-log entry mentions — corrected at draft review). This is a
  procedural discipline this document imposes on its own steps; no existing
  gate mechanically fires at a 90% watch threshold today (only the hard
  500-line ceiling is enforced, by `validate_invariants.py`), so AC-7 below
  proves only the post-hoc ceiling rejection, and compliance with the 90%
  trigger itself is reviewed at PR time, not machine-checked.

### Phase 2 — recorded, gated on NS-2 (owner action, not this document's code)

- R-RHI-6: When NS-2 (credential rotation + purge) is satisfied,
  `harness/shared/langgraph/` MUST move to `harness/shared/experimental/langgraph/`
  with PEP 562 deprecation shims at the old import paths for one minor
  release, per DEC-053 and the remediation plan's R-SR-27; the
  `except ImportError: pass` / `# pragma: no cover` swallow in
  `harness/shared/langgraph/__init__.py` MUST be removed in the same slice
  (NS-9), and `lats_enabled` MUST remain `false` (INV-15 unchanged). This
  requirement is recorded for sequencing; it MUST NOT be implemented before
  NS-2 closes, and Phase E order (JVM → LangGraph → openspec → mirroring) is
  inherited from the remediation plan, not re-derived.

## Acceptance criteria

At least one criterion per step names a rejection/failure outcome, not only a
success path.

- [x] AC-1: `python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['requires-python'])"`
      prints `>=3.10` (today: `>=3.9`); `git grep -n '"3\.9"\|'"'"'3\.9'"'"'\|UNSUPPORTED_LEG\|dependency-audit (3\.9)' .github/workflows .github/rulesets/main.json harness/shared/tests/_workflow_paths.py`
      returns nothing (today: the matrix's quoted `"3.9"` leg, the ruleset's
      `dependency-audit (3.9)` context, and `_workflow_paths.UNSUPPORTED_LEG`;
      **narrowed at implementation** from a blanket `git grep -n "3\.9"` — the
      unscoped form also flags legitimate historical prose, e.g.
      `check_py_compat.py`'s docstring explaining what the check caught back
      when 3.9 was the floor, and `requirements-dev.txt`'s comment on why
      `mypy`/`pip-audit` were pinned; those explain a past decision rather
      than encode a live carve-out, so banning the string itself would make
      the AC fail on correct documentation); `git grep -n "target-version" pyproject.toml`
      returns nothing; `python3 -m mypy --version` reports a 2.x release with
      `warn_unused_ignores = true` in `pyproject.toml`; the ruleset's required
      list contains no `dependency-audit (3.9)` context, verified by
      `pytest harness/shared/tests/test_workflow_contracts.py -k test_required_contexts_are_exactly_the_reported_check_names`
      (not `test_ci_gate_required_checks.py`, which only compares
      `NEXT_STEPS.md`'s prose to the workflow and never reads
      `.github/rulesets/main.json` — corrected at draft review, confirmed by
      reading both test files); `NEXT_STEPS.md`'s check-name sentence stays in
      sync, verified by the unchanged `test_ci_gate_required_checks.py`
      · stage: `make ci` (R-RHI-1, C-RHI-1) — **done**, `docs/specs/python-floor-310.md`.
- [ ] AC-2: `pytest harness/shared/tests -k test_reasoner_system_prompt_tools_match_bridge`
      passes and asserts the composed system prompt names exactly
      `tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)`'s function names,
      containing none of `Bash`, `Read`, `Grep`, `Glob` (today: this test does
      not exist; the raw markdown, frontmatter included, is what the loop
      currently sends); mutating a `tmp_path` persona fixture to add a
      non-registry tool name fails
      `test_persona_tools_subset_of_nemotron_tools`, and restoring a
      registry-only name passes it; the same run asserts no role's effective
      tool set grew relative to `agent_authority.tools_for_role` today
      · stage: `make test-python` (R-RHI-2, R-RBT-1, R-RBT-2, R-RBT-5, C-RHI-2, C-RBT-1)
- [ ] AC-3: A mocked `execute_agent` call records `prompt_sha` on the
      `model_call` extra dict equal to
      `hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()`, and the
      dict never contains the prompt text itself
      (`test_model_call_logs_prompt_sha`); a `tmp_path` persona fixture that
      still carries a `tools:` frontmatter block asserts the assembled prompt
      contains none of the frontmatter's raw tool names, only the
      registry-derived paragraph (rejection case for C-RBT-3)
      · stage: `make test-python` (R-RHI-2, R-RBT-3, R-RBT-4, C-RBT-3)
- [ ] AC-4: `pytest harness/shared/tests/test_workflow_contracts.py -k attestation_sha`
      fails on a `tmp_path` PR body whose attestation table names a SHA that
      is not the current head (today: no such test exists — an attestation
      naming any SHA passes silently) and passes when the table's SHA matches
      · stage: `make ci` (R-RHI-3)
- [ ] AC-5: `pytest harness/shared/tests/test_dockerfile_contract.py` fails on
      a `tmp_path` Dockerfile missing a `@sha256:` pin, missing `USER`,
      carrying `EXPOSE`, or invoking `tsx` in the runtime `CMD`, and passes on
      the tree (today: the module does not exist; the tree fails all four
      checks); `pytest harness/shared/tests/test_dependabot_contract.py -k cooldown`
      fails when the `docker` ecosystem entry lacks `cooldown` and passes on
      the tree once added · stage: `make ci` (R-RHI-4)
- [ ] AC-6: `pytest harness/shared/tests/test_constant_triage.py -k messages_before_fallback`
      (or the equivalent name chosen at implementation) fails on a `tmp_path`
      module carrying the bare `3` untriaged and passes on the tree once named
      · stage: `make test-python` (R-RHI-5)
- [ ] AC-7 (rejection case): `python3 harness/shared/validate_invariants.py`
      still exits nonzero on a `tmp_path` tree with any watch-list file one
      line over 500 after Steps 2-4 land, proving no step above widened the
      size-budget gate to accommodate its own edit · stage: `make validate`
      (C-RHI-3)
- [ ] AC-8: `git grep -nE "R-SR-23|R-RBT-|R-SR-24|R-SR-25" docs/specs/reflection-hardening-increment.md`
      finds each carried id, and neither `docs/specs/python-floor-310.md` nor
      `docs/specs/reasoner-bridge-tool-parity.md`'s existing content is
      duplicated by a new spec name (the parity spec is implemented in place,
      not re-specified) · stage: `make specs`
- [ ] AC-9 (blocked by NS-2 / R-SR-2): `ls harness/shared/langgraph` fails and
      `ls harness/shared/experimental/langgraph/__init__.py` succeeds;
      `python3 -W error::DeprecationWarning -c "import harness.shared.langgraph"`
      raises `DeprecationWarning` naming the new path;
      `git grep -n "except ImportError:\s*$" harness/shared/experimental/langgraph/__init__.py`
      returns nothing (the NS-9 swallow is gone); `lats_enabled` in
      `governance-policy.json` is still `false` · stage: `make ci`
      (R-RHI-6, R-SR-27) — **stays unticked until NS-2 closes**; recorded here
      only so the requirement is not orphaned, per this document's own rule
      that a requirement without a citing criterion is not a plan, it is a
      sentence.

## Steps

1. `make spec NAME=python-floor-310` superseding DEC-028 — produces the child
   spec; consumes this document's R-RHI-1.
2. Python floor bump: `pyproject.toml`, both workflow files, both dependency
   files plus `requirements-lock.txt`, `check_py_compat.py`,
   `harness/shared/tests/_workflow_paths.py` (drop `UNSUPPORTED_LEG`),
   `test_workflow_contracts.py` (drop the unsupported-leg test; this file
   already carries the ruleset-equality test AC-1 uses),
   `test_dependency_lock_contracts.py` (drop the langgraph-marker-exclusion
   assertion), `governance-policy.json`'s `coverage.optional_extras.langgraph`
   3.9 waiver if it names 3.9 specifically, `.github/rulesets/main.json` —
   produces a green `make ci` on 3.10/3.12/3.14; consumes step 1's spec.
   Protected: `pyproject.toml`, workflows, `Makefile` if `PYTHON_FLOOR`
   derivation changes, `governance-policy.json`.
3. Reasoner/bridge parity: implement
   `docs/specs/reasoner-bridge-tool-parity.md` R-RBT-1..5 in
   `harness/shared/orchestrator/loop.py` (split first if the edit crosses 500
   lines — currently 397/500, 79%, headroom likely sufficient but MUST be
   re-measured at implementation time), `harness/shared/agent_prompts.py`,
   `.mango/agents/*.md` — produces the four tests named in
   `reasoner-bridge-tool-parity.md`'s AC-1..4; consumes `NEMOTRON_TOOLS` from
   `tool_schemas.py`. Protected: `.mango/agents/`, `orchestrator/loop.py`.
4. Phase D minus signatures: `harness/shared/governance/attestation.py`,
   `.github/workflows/python-package.yml` (`build-full`'s attestation check),
   a new scheduled job in `.github/workflows/scheduled-drift.yml`, the two new
   Dockerfile/Dependabot contract tests, `Dockerfile`, `.github/dependabot.yml`
   — produces AC-4 and AC-5; consumes nothing new. Protected: workflows,
   `Dockerfile`, `governance/attestation.py`.
5. Constant triage: `orchestrator/loop.py`'s `len(messages) > 3`,
   `governance-policy.json` if policy-sourced, `test_constant_triage.py` —
   produces AC-6; consumes nothing new (can land with step 3 in the same PR
   since both touch `loop.py`, or standalone — implementer's choice, recorded
   in the PR body either way).
6. Coverage and mutation-proof ride every step above; no separate step.

## Files touched

Protected paths are marked (P); every (P) slice carries the attestation table
(bound per R-RHI-3 once step 4 lands) and the `infra-reviewed` label.

- Step 1/2: `docs/specs/python-floor-310.md` (new),
  `pyproject.toml` (P), `requirements-dev.txt` (P), `requirements.txt` (P),
  `requirements-lock.txt`, `.github/workflows/python-package.yml` (P),
  `.github/rulesets/main.json`,
  `harness/shared/check_py_compat.py` (P) (comment-only, no behavior
  change — its matrix-derived floor needed no code edit, `python-floor-310.md`
  R-PF-6/AC-7),
  `harness/shared/tests/_workflow_paths.py` (removes `UNSUPPORTED_LEG`),
  `harness/shared/tests/test_workflow_contracts.py` (removes
  `TestTheUnsupportedLegDeselectsRatherThanSkips`; this is also where the
  ruleset-drift assertion for AC-1 lives, not `test_ci_gate_required_checks.py`),
  `harness/shared/tests/test_dependency_lock_contracts.py` (removes the
  langgraph-marker-exclusion assertion, since every remaining leg installs it
  unconditionally once 3.9 is gone),
  `harness/shared/governance-policy.json` (P) if the langgraph 3.9 waiver
  changes shape, `NEXT_STEPS.md` (close NS-6).
- Step 3: `harness/shared/orchestrator/loop.py` (P),
  `harness/shared/agent_prompts.py`, `harness/shared/tool_schemas.py`
  (read-only reference), `.mango/agents/nemotron-reasoner.md` (P),
  `.mango/agents/planner.md` (P), `.mango/agents/verifier.md` (P),
  `harness/shared/tests/test_orchestrator_agent_loop.py`,
  `harness/shared/tests/test_agent_prompts.py` (new or extended),
  `docs/specs/reasoner-bridge-tool-parity.md` (tick AC boxes),
  `NEXT_STEPS.md` (close NS-18).
- Step 4: `Dockerfile`, `.github/dependabot.yml`,
  `harness/shared/tests/test_dockerfile_contract.py` (new),
  `harness/shared/tests/test_dependabot_contract.py` (new),
  `harness/shared/governance/attestation.py` (P),
  `.github/workflows/python-package.yml` (P),
  `.github/workflows/scheduled-drift.yml` (P) — new protection-report job,
  `harness/shared/tests/test_workflow_contracts.py`,
  `NEXT_STEPS.md` (close NS-36 minus `required_signatures`).
- Step 5: `harness/shared/orchestrator/loop.py` (P) (shared with step 3),
  `harness/shared/tests/test_constant_triage.py`,
  `harness/shared/governance-policy.json` (P) if policy-sourced.

## Invariants touched

- INV-1: unaffected — no `.sh` body or secret-scan scope changes.
- INV-2 (zero unapproved skips): Step 1 deletes the 3.9 `continue-on-error`
  carve-out and any skip guard keyed to `python_version < "3.10"`; no new skip
  is added. Proved by `make verify-zero-skips-python` on every slice.
- INV-5 (gate wiring / required checks): Step 1 removes a required-check name;
  `test_ci_gate_required_checks.py`'s equality test is the proof it was
  removed everywhere at once (ruleset export, workflow, `NEXT_STEPS.md`).
  Step 4 adds a check (`build-full`'s attestation-SHA assertion) without
  removing any existing one.
- INV-8/INV-9/INV-10 (broker/write authority): Step 3 does not widen any
  role's tool set (C-RHI-2); it changes what prose the model sees, not what
  the dispatcher permits.
- INV-15 (LATS/healing switch): unaffected by Phase 1; Phase 2's park keeps
  `lats_enabled: false`.
- INV-16 (cognitive/execution boundary): unaffected; `pytest -m governance`
  runs on every slice regardless.
- INV-17 (spec-driven changes gated by `make specs`): this document and its
  one child spec (`python-floor-310`) are gated by `make specs`;
  `reasoner-bridge-tool-parity.md` already exists and is ticked in place
  rather than re-specified (AC-8).

## Validation matrix

- `make ci` on every slice: ruff + mypy + vulture + pytest with floors from
  `governance-policy.json → coverage.{lines,branches,per_file}` + lock-check +
  specs + remotes + validate + check-dedup + digest-regen.
- `make lint-cold` on every slice; `secret-scan` and `dependency-audit` job
  URLs on the pushed head in the PR body (a verification claim in prose is not
  evidence, per `CLAUDE.md` and DEC-024).
- `make test-node` / `make lint-node` unaffected by Steps 1-5 (no Node source
  changes; Dockerfile is Node-adjacent infra, not Node source).
- `make validate` with and without `ALLOW_GITHUB_CHANGES=1` on every
  protected-path slice.
- `make verify-zero-skips-python` after every slice (INV-2).
- Coverage: floors are read from policy, never restated as a number here; each
  slice's PR reports the gate's own line/branch totals and the per-file line
  for every file it touched, per `coverage-gate` skill convention.
- Negative test per new gate: AC-1 (required-check equality), AC-2/AC-3
  (persona/prompt-sha), AC-4 (attestation SHA mismatch), AC-5 (Dockerfile/
  Dependabot contract), AC-6 (constant triage), AC-7 (size-budget rejection
  case).

## Backward compatibility

Python 3.9 support is the one breaking change in this document and is
intentional (3.9 is over ten months past EOL); it is isolated to Step 1/2 and
recorded as the floor bump, not silently absorbed into another step. Every
other step is additive or corrective: the reasoner persona's *observable*
tool set does not change (C-RHI-2) — only how it is derived; `prompt_sha` is a
new log field with no consumer contract to break. The attestation-SHA check
(Step 4) only starts failing on a stale table going forward; it does not
retroactively fail a merged PR. `Dockerfile` changes are runtime-image-only
and do not change any published interface. Any moved public symbol keeps a
PEP 562 shim for one minor release (only relevant if Step 2's `check_py_compat`
changes remove an importable name — none currently is). Phase 2 (LangGraph
park) keeps its own compatibility path per DEC-053/R-SR-27 and is not
implemented by this document.

## Open questions

1. **`python-floor-310` scope: 3.10 only, or 3.10 now + 3.11 in the same
   spec — resolved to 3.10 only, with a dated trigger, not left open.**
   The remediation plan recommended both in one spec to avoid a second floor
   change in November; this document scheduled 3.10 only, reasoning that no
   owner had asked for 3.11. On its own, that reasoning under-weighs the
   plan's actual warning: 3.10 itself reaches EOL 2026-10-31 — about seven
   weeks after this document's date — so "wait for the owner to ask" risks
   the exact repeat this ledger otherwise exists to prevent (an EOL floor
   discovered only after it has already lapsed, as DEC-028/DEC-064 record
   happened once with 3.9). Neither re-opening 3.11 unrequested nor leaving
   this as a passive question a human might not revisit is the fix: **NS-6
   in `NEXT_STEPS.md` now carries an explicit trigger** — "before
   2026-10-31, run `make spec NAME=python-floor-311`, gated on the same
   dependency-floor evidence check this spec ran for 3.10" — so the next
   session (agent or human) has a dated, actionable item instead of a static
   paragraph to rediscover.
2. **LangGraph park sunset release name.** The remediation plan's own **Open
   Question 4** (`2026-standards-remediation-plan.md:673-674`; corrected at
   draft review — the original citation pointed at `NEXT_STEPS.md`'s NS-4,
   which is an unrelated, already-closed Dependabot item) — "Memo 1 proposes
   'first minor release after the floor moves'" — is unresolved and is
   inherited, not answered, by this document's Phase 2 record.
3. **`len(messages) > 3` — module constant or policy key.** If the value is
   meant to ever be adopter-tunable, it belongs in `governance-policy.json`
   under a new `orchestrator` key with a fail-closed accessor; if it is a
   structural constant (e.g. "system + user + at least one exchange"), a named
   module constant with a decision-log id is enough and avoids growing the
   policy schema for a value nothing has ever needed to tune. Recommendation:
   module constant, decided at Step 5 implementation time based on whether
   any adopter template already overrides it (none do today).
