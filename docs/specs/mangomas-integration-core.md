# Spec: mangomas-integration-core

> Contract for the MangoMas integration core: the CognitiveSignal envelope, the
> shadow-mode planner comparison channel, and the versioned policy-artifact
> publisher. Derived from `docs/research/mangomas-v2-integration-use-cases.md`
> (UC-1, UC-4) and peer-reviewed via the `openspec-peer-review` persona matrix
> before implementation.

## Problem statement

The research record (PR #8) concludes that MangoMas_V2 integration requires a
one-directional boundary: the cognitive plane proposes, the harness disposes.
Today no machinery for that boundary exists — evidence:

- There is no versioned envelope for cognitive-plane output; nothing enforces
  that a cognitive producer's identity, lineage, or confidence stays
  authority-free (research doc, section 4.2 boundary invariants).
- There is no channel to compare an alternative planner against the incumbent
  without granting it control (UC-4 requires shadow mode with zero authority).
- `harness/shared/governance-policy.json` has no content-versioned, digest-
  pinned publication form a consumer could pin; the file's `schema_version` is
  a format version, not a content version (UC-1).

Scope note (framing): this change delivers the shadow comparison **channel**,
validated with a same-model producer. It produces no UC-4 experiment evidence;
the experiment starts only when a MangoMas producer is registered after the
license/SBOM verification precondition (research doc, section 4.1).

## Requirements

Envelope (`harness/shared/cognitive_signal.py`):

- R-MMI-1: The envelope MUST be an immutable record carrying
  `schema_version, signal_id, run_id, task_id, producer_id, signal_type,
  payload, policy_id, policy_version, timestamp`, with optional
  `producer_version`, `parent_signal_id`, `evidence_refs`, `confidence`.
- R-MMI-2: Validation MUST be fail-closed: unknown `schema_version`, missing or
  mistyped fields, malformed `signal_type`, timezone-naive or unparseable
  timestamps, and `confidence` outside `[0, 1]` (NaN included) are rejected
  with `SignalValidationError`, and every rejection is logged.
- R-MMI-3: The JSONL sink MUST serialize one signal per physical line with
  strict JSON (`allow_nan=False`), UTF-8, no CRLF, under a file lock, and MUST
  reject signals whose serialized size exceeds the module byte ceiling.
- R-MMI-4: The sink location MUST derive from the orchestrator workspace
  (`<workspace>/.mango/memory/signals/`), overridable via `MANGO_SIGNAL_DIR`.
- C-MMI-1: `confidence` is untrusted metadata: no code path MUST branch on it,
  and no envelope field may alter harness control flow or tool exposure.
- C-MMI-2: `producer_id`/`producer_version` are identity metadata only: no
  authority semantics MUST attach to any envelope field.

Shadow channel (`harness/shared/shadow_planner.py` + orchestrator hook):

- R-MMI-5: With `MANGO_SHADOW_PLANNER` set to exactly `"1"`, the orchestrator
  MUST emit an incumbent-plan signal and a shadow-plan signal (shared
  `run_id`, shadow `parent_signal_id` = incumbent `signal_id`) after the
  incumbent planner completes.
- R-MMI-6: Shadow signals MUST carry `elapsed_ms` and the provider `usage`
  object in their payload so the UC-4 wall-clock/token criteria are measurable
  by a future consumer.
- R-MMI-7: The shadow pass MUST reuse the existing `planner` role prompt and
  MUST be bounded by `MANGO_SHADOW_TIMEOUT_SEC` (default below the
  orchestrator API timeout); `MANGO_SHADOW_MODEL` MAY select a different model.
- C-MMI-3: The shadow pass MUST run with an empty tool schema and no
  `tool_choice`; `shadow_planner.py` MUST NOT reference the orchestrator tool
  registry, its executors, or its hook runner.
- C-MMI-4: With the flag unset or any other value, orchestrator behavior MUST
  be indistinguishable from the pre-change baseline: identical bridge-call
  transcript, return value, conversation history, hook invocations, and
  workspace tree.
- C-MMI-5: A failure anywhere in the shadow path MUST NOT affect the incumbent
  result (double containment: the channel never raises, and the orchestrator
  guard swallows and logs).

Policy artifact (`harness/control-plane/publish_policy_artifact.py`):

- R-MMI-8: `build` MUST produce an artifact pinning the sha256 digest and byte
  size of each governed policy file, with `policy_version` computed as a
  content digest of `governance-policy.json` (not its `schema_version`).
- R-MMI-9: `--check` MUST fail closed (DENY exit) on: missing file, digest
  length mismatch, digest mismatch, unknown artifact `schema_version`, or an
  empty file manifest.
- R-MMI-10: `--attest` MUST reuse `EvidenceBuilder` (HMAC-SHA256, key from
  argument or `AGENT_EVIDENCE_KEY`) and the signature MUST transitively cover
  the artifact core: a final policy snapshot binds the canonical-JSON digest of
  the artifact minus its attestation, and verification recomputes both the HMAC
  and the core digest and cross-checks every file digest against its snapshot.
- C-MMI-6: `--attest` without a resolvable key MUST DENY, never emit an
  unsigned artifact silently.

## Acceptance criteria

- [ ] AC-1: `make lint` (ruff, mypy, py-compat) passes — verified by `make lint`.
- [ ] AC-2: Aggregate Python coverage meets `governance-policy.json →
  coverage.lines` — verified by `make coverage-python`.
- [ ] AC-3: Governance validators and drift gates pass — verified by
  `make validate`, `make check-dedup`, `make digest-regen`.
- [ ] AC-4: `bash harness/shared/validate_specs.sh` passes with this spec
  present.
- [ ] AC-5: The byte-identity suite proves C-MMI-4 across flag values
  (unset, "0", "true", "yes", "", " 1", "TRUE") including a workspace tree
  snapshot diff — verified by pytest.
- [ ] AC-6: The boundary suite proves C-MMI-1/2/3 via the parametrized
  envelope-invariance property test and the static boundary scan — verified by
  pytest (`-m governance`).
- [ ] AC-7: The publisher tamper matrix (R-MMI-9) and the attestation-coverage
  regression (flipping a file digest with intact attestation MUST DENY,
  R-MMI-10) pass — verified by pytest.
- [ ] AC-8: `.mango/agents/` remains exactly {planner, nemotron-reasoner,
  verifier} — verified by `test_agent_harness_wiring.py`.
- [ ] AC-9: No UC-4 kill-criteria evidence is claimed by this change; the
  shadow channel is validated with a same-model producer only.

## Invariants touched

None weakened. Relevant proofs:

- INV-5 (CI gates by Make target): no gate is altered; new modules enter the
  existing coverage denominator and are covered near-fully.
- INV-6 (protected paths): every touched path is outside `protected_paths`;
  `validate_invariants.py` confirms on a clean tree — no
  `ALLOW_GITHUB_CHANGES` attestation is required for this change.
- INV-7 (bounded delegation, no authority transfer): C-MMI-1/2/3 make the
  cognitive boundary structural (value-object seam, empty tool schema,
  identity-only metadata), enforced by the boundary test suite.
- Size budget (`limits.size_budget_lines`): every new module stays under the
  policy budget; verified by `validate_invariants.py` in `make validate`.

## Validation matrix

Thresholds are read from `harness/shared/governance-policy.json` — no values
are hard-coded here.

- `make lint` — ruff + mypy + `check_py_compat` (minimum Python from the CI
  matrix).
- `make coverage-python` — pytest (excluding `live`) with
  `--cov-fail-under` = `coverage.lines`.
- `make validate` — governance validators + `validate_invariants`
  (protected paths, secrets, `limits.size_budget_lines`).
- `make check-dedup`, `make digest-regen` — drift gates (no-ops for these
  paths, run to prove it).
- `bash harness/shared/validate_specs.sh` — structural spec gate.
- Publisher end-to-end: `build` → `--check` round-trip in a scratch directory,
  exercised via subprocess in tests (import-safety and CLI wiring).

## Backward compatibility

Additive only:

- `MangoMASOrchestrator` gains no constructor or signature changes; the
  api_server call site and response model are untouched. The shadow path never
  writes `conversation_history`.
- `meta_tools._file_lock` remains as an alias of the promoted `file_lock`;
  existing callers and tests are unaffected.
- All new behavior is disabled by default (env flag) and the publisher is an
  unwired CLI; a rollback is "unset the flag" for behavior and revert for code.
  The orchestrator's import of `shadow_planner` is top-level; an import-time
  smoke test guards the flag-off import path.

## Open questions

Recorded for follow-up; none block this implementation.

- Policy-block promotion: `MANGO_SHADOW_PLANNER` migrates to a
  `shadow_planner` block in `governance-policy.json` (protected path, requires
  the `infra-reviewed` process) only if the UC-4 experiment passes its
  preregistered kill criteria (plan agreement threshold, wall-clock/token
  ratio bounds, no mutation-score regression — research doc section 2, UC-4).
- JSONL consumer: an agreement/latency/token reporter over
  `cognitive-signals.jsonl` is the first deliverable of the UC-4 experiment
  step; until then the sink is audit-only, unbounded append, operator-pruned
  (gitignored under `.mango/memory/`).
- Specs gate drift: `specs` appears in `ci_required_targets` but `make ci`
  has no specs stage; wiring it touches the protected root `Makefile` and
  needs its own reviewed change.
- Lock semantics: the sink lock is single-host, best-effort
  (`O_CREAT|O_EXCL` lockfile with bounded timeout); crashed-process stranding
  is bounded by the timeout and surfaces as a swallowed warning. Revisit if
  the channel ever becomes multi-writer.
- `MANGO_SIGNAL_DIR` may point outside the workspace by operator choice; this
  is trusted-operator surface, same class as the existing debug env vars.
- The publisher is intentionally outside the mypy target set and the coverage
  denominator (`harness/control-plane` is not in the coverage source list);
  its correctness is held by its own test module.
