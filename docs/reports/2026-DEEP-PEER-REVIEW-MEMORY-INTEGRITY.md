# Deep peer review: agent-memory integrity, and a comparison against `main`

**Reviewed head:** `main` @ `6ce45d1` (2026-09-06, DEC-058 landed)
**Open PR compared:** #115 (`feature/origin-sync-test-e2e-aqa-20260906` → `main`), all four
Python build legs red at review time
**Method:** every claim below is either a command run against this checkout, a `file:line`
citation read directly, or a `gh api` / `gh run` call against the live repository. Four
`openspec-peer-review` personas (Architecture, SDLC/CI Lead, QA Director, Product) are applied
to one finding: agent memory has no integrity control on the write path that reaches a future
prompt. This finding is **not** already tracked by `docs/reports/2026-STANDARDS-AUDIT.md`,
`docs/specs/2026-standards-remediation-plan.md`, or `NEXT_STEPS.md` — confirmed by
`git grep -rn "memory poison\|ASI06\|memory.*integrity\|memory.*tamper" docs/ NEXT_STEPS.md`
returning nothing. The companion spec is `docs/specs/agent-memory-integrity.md`.

---

## 1. Where this repository already stands, verified fresh

The repository's own audit trail (`docs/reports/2026-STANDARDS-AUDIT.md`,
`docs/specs/2026-standards-remediation-plan.md`) is unusually rigorous and mostly still
accurate. Re-querying rather than trusting the prose:

```
$ gh api repos/ianshank/Mango_Code_Agent-Harness/rules/branches/main
[]
$ gh api repos/ianshank/Mango_Code_Agent-Harness/rulesets
[]
```

**B1 (branch ruleset never applied) is still open** — `NEXT_STEPS.md` NS-1 already says so and
is current. No new finding here; restated only so this report's "compare to main" instruction
is answered with evidence, not assumed from the prior conversation's summary.

**B4 (verdict forgery via `Makefile` rewrite) is closed**, contrary to what an earlier pass of
this review assumed from a stale summary. `DEC-049`, `DEC-051` and R-SR-6/R-SR-7 landed on
PR #86:

```
$ python3 -c "import json;d=json.load(open('harness/shared/governance-policy.json'));print('Makefile' in d['protected_paths'], 'GNUmakefile' in d['protected_paths'])"
True True
```

`harness/shared/governance/enforcement_digest.py` now records a `sha256` digest of every
`protected_paths` file before the first agent turn and `VerificationRunner` refuses to grade a
run in which any of them changed (`harness/shared/governance/verification.py`,
`snapshot_enforcement` / `enforcement_tampered`). `harness/shared/agent-policy.json`'s own
comment block names the residual honestly: *"Known gap until OS isolation lands: `test_execute`
permits running a workspace script, and the script is not governed by this model... The verdict
is protected against that route... the script's other effects are not prevented."*

That sentence is the seam this review pulls on. The verdict is protected. A different piece of
harness-trusted state that a script can also reach — the agent's own persisted memory — is not,
and nothing in the closed B4 work, DEC-057, or DEC-058 claims it is.

---

## 2. The finding: agent memory has no write-side integrity control

### 2.1 The exploit chain, each link cited against `main` @ `6ce45d1`

1. **The active role that writes memory also holds raw file-write tools.**
   `harness/shared/agent_authority.py:34-38` maps `nemotron-reasoner` → canonical role
   `implementer`, whose `allowed_actions` in `harness/shared/agent-policy.json` are
   `["read", "write", "test_execute"]`. `TOOL_REQUIRED_ACTION` in the same module maps
   `write_file` → `write` and `apply_patch` → `write`, and separately maps
   `knowledge_gap_log` → `read` and `hypothesis_register` → `read` (`agent_authority.py:60-78`).
   The reasoner therefore holds **both** the meta-tool that is supposed to be the only writer of
   memory, and the raw tools that can write anywhere else `write_policy` allows.

2. **`write_policy.write_denial_reason` does not deny `.mango/memory/`.** Read in full
   (`harness/shared/write_policy.py:360-430`): the checks, in order, are absolute-path, `..`
   traversal, `ALWAYS_DENIED_SEGMENTS` (`(".git",)` only — `write_policy.py:95`), credential
   filename, then `protected_paths`. `.mango/memory/hypotheses.json` matches none of them:

   ```
   $ python3 -c "
   from pathlib import Path
   from harness.shared.write_policy import write_denial_reason
   print(write_denial_reason('.mango/memory/hypotheses.json'))
   print(write_denial_reason('.mango/memory/gaps.json'))
   "
   None
   None
   ```

   `None` means *allowed*. `harness/shared/governance-policy.json`'s `protected_paths` lists
   `.mango/agents/**`, `.mango/settings.json`, `.mango/hooks/**` and `.mango/skills/**`
   (lines 143–146) — every `.mango` subtree the agent does not write at runtime — but not
   `.mango/memory/**`, the one subtree it does.

3. **The enforcement-digest tamper check does not cover it either, for the same reason.**
   `harness/shared/governance/enforcement_digest.py` digests exactly the `protected_paths` set
   (`effective_protected_patterns`, sourced from the same `write_policy` matcher). A file absent
   from that set is absent from the baseline and absent from the tamper comparison. This is not
   a bug in `enforcement_digest.py` — it is doing precisely what it says — it is that
   `.mango/memory/` was never added to the set it walks.

4. **The meta-tool's own validation is bypassed entirely by the raw-write path.**
   `harness/shared/meta_tools.py:160-166` defines `HYPOTHESIS_STATUSES = (provisional,
   confirmed, retracted)` and `hypothesis_register` (`meta_tools.py:198-244`) raises when a
   caller-supplied `status` is outside that tuple, and (per the docstring at
   `memory_view.py:1-20`) `confidence` is held to a finite range. None of that code runs when
   the write happens through `write_file` or `apply_patch` instead of the `hypothesis_register`
   tool call: those tools call `tool_executors.write_file`, which calls `write_denial_reason`
   (link 2, returns `None`) and then writes the caller's bytes verbatim. A forged entry that is
   **well-formed** — real-shaped `uuid4` id, a status inside `HYPOTHESIS_STATUSES`, a confidence
   inside range — passes every check `memory_view.py` runs on read
   (`_is_open`, `_render_confidence`), because those checks exist to keep a *malformed*,
   hand-edited store from crashing the renderer (`memory_view.py:126-160`'s own comments say so:
   *"can only come from a hand-edited store"*), not to authenticate that an entry came from a
   real `hypothesis_register` call. Shape validation and authenticity are different properties;
   this module has the first and not the second. `knowledge_gap_log` (`meta_tools.py:121-150`)
   has **no** field validation at all — it appends `question`/`what_needed`/`proposed_approach`
   verbatim — so the raw-write bypass for `gaps.json` is not even a bypass of a check; there was
   never one to bypass, only the file-path gate this spec adds.
   One clarification the shape of the exploit must not overstate: registering a `confirmed`,
   high-confidence hypothesis through the **real** `hypothesis_register` call is not itself a
   defect — every canonical role holds the `read` action `hypothesis_register` requires
   (`agent_authority.TOOL_REQUIRED_ACTION`), and a model asserting a settled belief is the
   feature working as designed. The defect is specifically that a **second**, unvalidated path
   to the same bytes exists for the one role (`nemotron-reasoner`) that also holds `write_file`,
   and that second path skips checks the first path enforces.

5. **The forged entry is then rendered into a real prompt with no signature check.**
   `format_hypotheses_for_reasoner` (referenced by DEC-058, implemented per
   `docs/specs/hypothesis-surfacing.md`) reads the store through `load_hypotheses` →
   `_read_json_safe`, filters to open entries, and renders up to
   `agent_memory.reasoner_hypothesis_limit` (10) of them into
   `REASONER_PROMPT_TEMPLATE`'s `{open_hypotheses}` slot
   (`harness/shared/agent_prompts.py`, `harness/shared/orchestrator/loop.py`). Nothing between
   step 3 and here checks that the bytes on disk were produced by a call the meta-tool's own
   validation ever saw.

**First blocking link found: none.** Every link above is a direct read of `main` @ `6ce45d1`,
not an inference. `harness/shared/tests/test_write_policy.py` has zero cases naming
`.mango/memory` (`grep -n "mango\|memory" harness/shared/tests/test_write_policy.py` returns
only unrelated `.mango/hooks` / `.mango/agents` lines), and
`harness/shared/tests/test_hypothesis_revision.py` /
`harness/shared/tests/test_hypothesis_surfacing.py` test the meta-tool's own validation and the
formatter's rendering, never the raw-write bypass of either. No existing test pins this
scenario either way.

### 2.2 Why this is the same bug class the harness already fixed once, on a different surface

`harness/shared/governance/enforcement_digest.py`'s own module docstring narrates exactly this
shape of defect for a different file: a protected-in-name-only surface (`Makefile`) that a
downstream consumer (`VerificationRunner`) trusted without checking whether the agent's own
prior turn had rewritten it. The fix there was: (a) name the file as `protected_paths`, (b)
digest it before the run, (c) refuse to trust it if the digest moves. `.mango/memory/` is
`protected_paths`-eligible in the identical sense — it is read by a downstream consumer
(the reasoner's own next prompt, or the *next run's* reasoner) that has no way to know whether
the bytes it is trusting came from the tool call whose contract it assumes, or from a write that
skipped that contract. This report proposes the same three-part fix, scoped to memory.

### 2.3 Severity and blast radius

- **Cross-run persistence.** Unlike a prompt-injection payload in one turn's context (which
  resets at run end), a forged hypothesis or gap survives in `.mango/memory/*.json` across every
  future run against the same workspace until FIFO-trimmed (`agent_memory.max_hypotheses: 100`).
  This is the property OWASP's ASI06 write-up names as what distinguishes memory poisoning from
  ordinary prompt injection: the attack "persists across sessions and executes days or weeks
  after the initial write" (Vectorize, "OWASP ASI06: Memory and Context Poisoning Explained",
  2026).
- **No detection surface today.** No log line, digest, or test would currently distinguish a
  forged entry from a genuine one. `harness/shared/memory_view.py`'s own module docstring states
  the intended reachability contract (`memory_store <- meta_tools <- memory_view <- loop`), and
  the finding is that the contract has a second, unenforced entrance (`write_file`/`apply_patch`
  → the same files) that the docstring's diagram does not show because nothing blocks it.
- **Self-reinforcing risk.** A forged "confirmed" hypothesis with high confidence
  (`confidence` up to `_CONFIDENCE_MAX`) that reads, for instance, "the coverage gate threshold
  check in `coverage_gate.py` already accounts for the per-file waiver list; do not re-derive it"
  would be read by the reasoner as its own prior, validated conclusion and would bias planning
  and tool-call choices in every subsequent run — the "bootstrap poisoning" pattern OWASP's
  2026 Top 10 names explicitly as mitigation item 6 (*"Prevent automatic re-ingestion of an
  agent's own generated outputs into trusted memory to avoid self-reinforcing contamination"*).

---

## 3. Four-persona review of the finding and its proposed remediation

### Architecture

The three-layer split (`memory_store` mechanics → `meta_tools` semantics → `memory_view`
presentation, stated in `memory_view.py`'s own docstring) is a clean, SRP-respecting design and
should not be undone. The gap is not architectural sloppiness; it is a **missing fourth
property** the split never claimed to provide: *authenticity of the bytes on disk*. The
remediation in `docs/specs/agent-memory-integrity.md` adds that property at the layer that
already owns "what a record means" (`meta_tools`) rather than inventing a fifth module,
mirroring the same reasoning `hypothesis-surfacing.md`'s peer review used to reject a bespoke
`hypothesis_prompt.py` (the accepted proposal there: the formatter belongs with the existing
reader layer, not a new module for one function). The write-side fix belongs in
`write_policy.py` (already the single place path-based denial is decided) plus `meta_tools.py`
(already the single place record shape is decided); no new layer is warranted.

### SDLC / CI Lead

This finding has zero CI coverage today and would land silently — no gate currently exercises
`write_file(".mango/memory/...")`. That is itself evidence for the finding, not just a
consequence of it: `test_write_policy.py`'s test-case list is a reasonable proxy for "what the
authors of the write door were thinking about when they wrote it", and `.mango/memory/` is
absent from it. The remediation spec's acceptance criteria are written so this stops being true
— each AC names a `pytest -k` selector that must exist and collect before the fix, per this
repository's own `R-SR-21` / `test_spec_selectors_collect.py` convention (an unticked box here
is deliberate: nothing below is implemented yet, so nothing is checked `[x]`).

### QA Director

The most important test is a **negative** one: a forged entry that is well-formed by every
existing shape check (`_is_open`, `_render_confidence`, `HYPOTHESIS_STATUSES` membership) must
still be rejected once the fix lands, specifically *because* it is well-formed — that is the
case the current code cannot catch and the one an adversary optimizing for stealth would
produce (the "sub-threshold propagation gap" pattern industry write-ups describe for
memory-laundering attacks: a payload can pass every present filter and still poison downstream
reasoning). A test that only forges a malformed entry would prove nothing new, since
`memory_view.py` already handles those defensively.

### Product

The fix must be additive and silent for every workspace that has never had a forged entry: the
same backward-compatibility contract `hypothesis-surfacing.md` used for the `{open_hypotheses}`
slot (byte-identical output on the empty/absent case) applies here to the *signature* field —
an existing store with no signature must not suddenly break the loop; it should be treated as
unsigned (legacy) and either trusted-with-a-logged-warning for one release or quarantined,
depending on the migration posture the spec's open question resolves. Silently discarding a
whole store on first upgrade would look like the harness eating an agent's memory, which is a
worse operator experience than the vulnerability it fixes.

---

## 4. PR #115 — cross-reference against `main`, verified fresh

PR #115 (`feature/origin-sync-test-e2e-aqa-20260906`) is unrelated to the memory-integrity
finding but was explicitly requested to be compared against `main`. All four Python build legs
are red (`gh pr checks 115`); `secret-scan` and `dependency-audit` pass. A dedicated subagent
re-derived each root cause from primary evidence (`git show`/`git log` at the exact culprit
commit, live CI logs, direct byte-hashing) rather than the CI summary alone; the results refine
two of the four rows below:

| # | Defect | Evidence on the PR branch | Fix direction |
|---|---|---|---|
| 1 | `.gitignore` / `.dockerignore` re-saved as UTF-16-like binary (NUL-interleaved), breaking `test_documentation_truth.py`'s dead-rule checks | Exact culprit isolated to commit `795f6e6` ("chore(docs): update documentation and ops files for version 2.5.0 origin sync") — `git show` reports both files `Bin … -> Bin …` there for the first time; the immediately preceding commit still shows them as ASCII/UTF-8 text. `main` is correct throughout | Re-save both files as UTF-8/ASCII, keeping `795f6e6`'s intended rule additions, before merge |
| 2 | Version mirrors partially bumped to `2.5.0`; `pyproject.toml` still `2.4.0` | Precise mirror-by-mirror check against `pyproject.toml` (2.4.0 on both branches): only `README.md`, `NEXT_STEPS.md`, and `docs/architecture/c4_architecture.md` drifted to `2.5.0`. `Makefile`, `CHANGELOG.md`'s `## [x.y.z]` heading, and `harness/node/package.json` were **never bumped on either branch** — the CHANGELOG's Unreleased section only narrates 2.5.0-shaped work in prose, and `main` has zero drift anywhere | This is a half-finished release, not a stray edit: finish the bump (`pyproject.toml` → `2.5.0`, `package.json` → `2.5.0`, add a real `## [2.5.0]` CHANGELOG heading, update the Makefile version comment) rather than reverting the three docs that were already bumped |
| 3 | `harness/control-plane/policy-artifact.json` claims `policy_version` / hash `641510baabdddc74` (6732 bytes); the actual `governance-policy.json` on the branch hashes to `ad55682ced09dd25` (6731 bytes) | CI log (`test_publish_policy_artifact.py::test_committed_artifact_matches_working_tree`). Traced to commit `36c95d5` ("renumber Windows DECs"), which touches **only** `policy-artifact.json` — `governance-policy.json` is byte-identical before and after that commit, and stays `ad55682ced09dd25`/6731 bytes through every later commit up to the PR tip | The artifact's claimed hash corresponds to **no committed state of `governance-policy.json`** on this branch, before or after `36c95d5` — the publisher script was evidently run against an uncommitted or stale local copy of the policy file, and only its output was committed. Regenerate from the actual committed source (`python harness/control-plane/publish_policy_artifact.py build --output harness/control-plane/policy-artifact.json`), which reproduces `ad55682ced09dd25`/6731 bytes for the current tree — unless a real policy content change was intended and is simply missing from the PR, in which case add that change first |
| 4 | `build-full` fails closed: 11 protected paths touched, PR body has no attestation table | CI log: `[FAIL] ... 11 protected path(s) need one`; `gh pr view 115 --json body` shows the template's `\| File \| Change \| Why it is safe \|` header still followed by one empty row | The already-applied `infra-reviewed` label sets `ALLOW_GITHUB_CHANGES=1` for the mechanical Makefile gate but does **not** excuse this separate, unconditional check — populate one row per listed protected file per DEC-038's "verified, not transcribed" rule before merge |

None of these four are in tension with the current `main`; they are pre-merge hygiene defects
local to the PR branch. Confirmed no DEC-number collision: PR #115 declares DEC-059…DEC-062
(inherited 057/058 unchanged, four new IDs, 63 total entries, no duplicates), and `main`'s
`docs/decisions/index.json` currently ends at DEC-058, so the numbering is contiguous, not
colliding, as of this review. Required-check name drift was also checked independently (static
workflow parse, the repo's own `test_required_contexts_are_exactly_the_reported_check_names`,
and live `gh pr checks 115` output): none found — the nine checks declared in
`.github/rulesets/main.json` are exactly the nine GitHub actually reports.

---

## 5. Academic and industry grounding

- **MAST (Cemri et al., NeurIPS 2025, arXiv:2503.13657)** — the empirically-grounded 14-mode
  multi-agent failure taxonomy. The memory-poisoning finding above maps most directly to
  **FM-2.6 (reasoning–action mismatch)**: an agent acting on a belief that contradicts what its
  own tool-validated reasoning trail would show, because the belief entered through a path the
  trail does not cover. It is adjacent to, but distinct from, **FM-3.2 (incomplete
  verification)** — the verifier role has no reason to check memory integrity, since memory is
  not in its verification target (`DEFAULT_TARGET = "test-python"` in `verification.py`), so
  this is a verification gap the taxonomy's own category predicts.
- **OWASP Top 10 for Agentic Applications 2026, ASI06 (Memory & Context Poisoning)** — the
  official mitigation list (genai.owasp.org/download/52117, section ASI06) is nine numbered
  items; the remediation spec below implements #1 (baseline protection via write-policy denial),
  #2 (content validation before commit — already partially present in `meta_tools`'s status/
  confidence checks, extended to a required call path), and #5/#7 (provenance and resilience via
  a signature and a verification step), and explicitly defers #3/#4/#8/#9 (multi-tenant
  segmentation, retention decay, trust-weighted retrieval) as out of scope for a single-workspace
  harness with an existing FIFO retention policy, recorded as an open question rather than
  silently dropped.
- **CaMeL (Debenedetti et al. / Google DeepMind + ETH Zürich, arXiv:2503.18813)** — the
  capability-based defense against prompt injection separates a privileged planner from a
  quarantined reader of untrusted data, achieving provable security on 77% of the AgentDojo
  benchmark's tasks (vs. 84% for an undefended baseline). The relevant idea for this harness is
  narrower than adopting the full two-LLM architecture: CaMeL's core insight — untrusted data
  should carry provenance/capability metadata that a downstream consumer checks before acting on
  it, rather than being trusted by position in the pipeline — is exactly what a per-entry
  signature over `meta_tools`-validated content gives the memory store, without requiring a
  second model.
- **Reward hacking / verifier-gaming (SpecBench, arXiv:2605.21384; ImpossibleBench, Meng et al.
  2025)** — orthogonal to memory poisoning but relevant to why `DEFAULT_TARGET = "test-python"`
  (§1) matters here too: SpecBench's finding that the visible/held-out test gap widens 28
  percentage points per 10x growth in code size is the general argument for why a verdict scoped
  to one command (not the full `make ci`) under-detects specification drift as the codebase this
  harness itself produces grows — a standing risk this report notes but does not scope a fix
  for, since it is `main`'s existing, already-tracked scope question (Phase F, `docs/specs/
  2026-standards-remediation-plan.md`), not new.

---

## 6. Disposition

This report is peer-review output only; no code changes are proposed or made here. The
remediation is specified in `docs/specs/agent-memory-integrity.md`, written to this
repository's existing spec conventions (Problem statement → Requirements → Acceptance criteria
→ Steps → Files touched → Invariants touched → Validation matrix → Backward compatibility →
Open questions), ready for `openspec-peer-review` and then implementation as its own PR. It is
additive to, not a replacement for, `docs/specs/2026-standards-remediation-plan.md`: that plan's
Phase B already closed the parallel defect on the verdict-forgery surface (B4); this spec closes
the analogous gap on the memory surface, which that plan's scope never named.
