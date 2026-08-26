# Milestones

## Milestone 1 — Governance extraction and evidence foundation
- Inventory existing shared scripts, schemas, hooks, control-plane policies, and tests.
- Define the public Python API for `harness.shared.governance`.
- Move or wrap `pretooluse_guard.py`, `verify_zero_skips.py`, `check_traceability.py`, `remotes.py`, and policy-schema validation without behavior changes.
- Add compatibility shims at old import paths.
- Add a manifest generator that hashes policy bundles, agent definitions, hooks, test commands, lockfiles, and source revision.
- Add tests proving old and new import paths give equivalent policy results.
- Add mutation testing only for governance-critical branches and the circuit breaker.
- **Gate**: existing suites remain green; no skipped tests; mutation score threshold agreed before enforcement.

## Milestone 2 — Provider-neutral model runtime
- Define shared provider-neutral request, response, stream-event, retry, and error contracts.
- Extract `SecretMasker`, jittered retry, and circuit breaker into reusable components.
- Implement `OpenAICompatibleProvider` first.
- Implement `NvidiaProvider` as configuration over the compatible protocol where possible.
- Add an explicit local endpoint provider for LM Studio/vLLM-style endpoints.
- Keep Anthropic as a deferred adapter until its protocol differences are test-covered.
- Update documentation: state protocol compatibility precisely; do not claim universal provider compatibility.
- **Gate**: provider contract tests, SSE replay fixtures, secret-redaction tests, and open/half-open/closed circuit-breaker tests.

## Milestone 3 — Execution broker and capability policies
- Define versioned capability profiles: policy-only, unit-test, build-test, network-isolated, and human-approved.
- Implement broker request/result schemas.
- Add a WASM backend proof-of-concept for a supported narrow language/runtime.
- Add a no-fallback rule: sandbox unavailable returns BLOCKED.
- Add network-denial, workspace-only filesystem, environment allowlist, timeout, memory, and output-size checks.
- Add adversarial escape fixtures: `find -delete`, `git clean -fdx`, Python `shutil` deletion, `curl`-pipe-shell, mount-style Docker escapes, encoded shell payloads.
- **Gate**: every escape fixture is denied or blocked with a specific evidence record.

## Milestone 4 — Evaluation harness before search
- Define 30 seed tasks: repository-local maintenance, policy violation, parser failure, compiler failure, tests, secret exposure, and sandbox denial.
- Include a fixed subset of Pong deterministic faults as simulation fixtures, not product features.
- Implement a single-shot baseline using the provider-neutral runtime.
- Implement deterministic verifier-only baseline.
- Add evaluation result schema and OpenTelemetry GenAI-compatible spans.
- Capture model ID, provider, version/revision, policy digest, prompt digest, source revision, tool versions, cost, latency, and outcome.
- **Gate**: benchmark results are reproducible from an evidence bundle.

## Milestone 5 — Bounded LATS and repair loop
- Define `SynthesisStrategy`, `SingleShotStrategy`, and `BoundedLatsStrategy`.
- Implement bounded tree configuration: depth, width, rollout count, timeout, token/cost budget.
- Normalize policy/test/compiler/sandbox failures into a redacted `Critique` schema.
- Enforce maximum three repair cycles.
- Add agentless, verifier-only, and bounded-LATS ablation runs.
- Establish rollout threshold: LATS is default-off unless it materially improves task completion or security without failing cost/latency budgets.
- **Gate**: candidate DENY cannot be revived through reflection, voting, or repair.

## Milestone 6 — Skill packaging and portability
- Create `.mango/skills/neurosym-synthesis/SKILL.md`.
- Define required tools, policy profiles, non-goals, bounded-autonomy rules, and verification commands.
- Add `AGENTS.md` as the portable, tool-neutral entry point; generate or link tool-specific guidance from canonical material.
- Add a minimal FastAPI service only after the local CLI/evaluation path is stable.
- Add export workflow for redacted, explicitly approved academic datasets.
- **Gate**: `openspec validate add-neurosym-governed-synthesis`, full Mango pre-pr, Tier 6 sandbox tests, and a documented ablation report pass.

## Evaluation Gate

Do not enable LATS by default based on qualitative demos. Require the following decision table:

| Condition | Default strategy |
|---|---|
| LATS improves verified task completion but exceeds cost or latency cap | Single-shot + verifier |
| LATS improves quality-per-dollar and does not degrade security or reproducibility | Bounded LATS eligible |
| Sandbox backend unavailable | BLOCKED; no host fallback |
| Policy denies a candidate | Prune; no repair of that exact candidate |
| Repair budget exhausted | FAILED with evidence bundle |
| Trace export lacks redaction/provenance | Keep trace internal; prohibit dataset export |
