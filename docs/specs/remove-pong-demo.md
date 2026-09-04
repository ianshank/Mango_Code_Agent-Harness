# Spec: remove-pong-demo

> Scaffolded by `make spec NAME=remove-pong-demo`. This spec covers PR 1 of the
> tech-debt reduction program: repository hygiene plus removal of the Pong demo
> workload from the Node stack.

## Problem statement

The repository carries dead and misplaced content that dilutes the harness's
purpose and its enforcement surface:

- `harness/node/src/pong/**` (~30 source files) and `harness/node/tests/pong/**`
  (21 test files) implement a Pong game unrelated to the agent harness, and the
  `Dockerfile` default command runs `pong-cli` — the shipped container runs a
  game demo, not the harness. Evidence: `Dockerfile` header "Agentic SSD Pong &
  Nemotron AI Runner" and `CMD` invoking `src/pong/cli/pong-cli.ts`.
- Seven files are tracked inside gitignored `scratch/` (one-shot fixup scripts
  plus a stale 68 KB mypy report), and five run-artifact logs are tracked in
  `harness/test-results/` despite `*.log` being gitignored. Evidence:
  `git ls-files -i -c` lists all twelve.
- `harness/jvm/scripts/run_vitest.sh` is a Vitest (JavaScript) runner inside the
  Kotlin stack; no jvm Makefile target invokes it.
- `run_vitest.sh` (shared and node copies) resolves `$ROOT` to the repo
  top-level and then references `$ROOT/scripts/verify_zero_skips.py` and
  `$ROOT/node_modules/.bin/vitest`, neither of which exists — the script is
  broken in every copy.
- `.agents/skills/nemotron-reasoner/SKILL.md` duplicates the canonical
  `.mango/skills/nemotron-reasoner/SKILL.md`.
- `harness/api_server/main.py` dev-runner uses port 8000 with `reload=True`
  while the `Dockerfile` exposes 8080 — divergent defaults and a dev-only flag
  hard-enabled.
- `NEXT_STEPS.md` and `NEXT_STEPS_PLAN_v2.md` are near-identical siblings at the
  repository root.

## Requirements

- R-HYG-1: The repository MUST NOT track any path that `.gitignore` excludes
  (`scratch/**`, `harness/test-results/*.log`).
- R-HYG-2: `run_vitest.sh` (shared and node copies) MUST resolve the Node
  project root from the script's own location so that both the vitest binary
  and the zero-skips verifier resolve to existing paths.
- R-HYG-3: The Kotlin stack MUST NOT carry JavaScript tooling
  (`harness/jvm/scripts/run_vitest.sh` removed).
- R-HYG-4: Exactly one copy of the nemotron-reasoner skill MUST exist, at
  `.mango/skills/nemotron-reasoner/`.
- R-HYG-5: The api_server dev runner MUST default to the container port (8080)
  and MUST enable auto-reload only when `API_SERVER_RELOAD=1` is set in the
  environment, not unconditionally.
- R-PONG-1: `harness/node/src/pong/**`, `harness/node/tests/pong/**`, and the
  pong architecture/user-guide docs MUST be removed.
- R-PONG-2: The `Dockerfile` default command MUST run harness functionality
  (the Nemotron CLI), not a game demo.
- C-HYG-1: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`;
  no protected path is modified, so no `ALLOW_GITHUB_CHANGES` attestation is
  required.
- C-HYG-2: If `harness/node/package.json` changes (unused-dependency cleanup),
  the policy bundle digests MUST be regenerated in the same commit
  (`make digest-regen`).
- C-PONG-1: Removing pong tests together with the pong feature is feature
  removal, not a test waiver; the remaining Node suite MUST pass with zero
  unapproved skips.

## Acceptance criteria

- [x] AC-1: `git ls-files scratch harness/test-results` returns nothing —
  verified by that command's empty output in `make pre-pr` review. — verified
  2026-09-02: the command prints nothing
- [x] AC-2: `make ci` passes end-to-end (ruff, mypy, compat, pytest+coverage
  gate, vitest, zero-skips, specs, remotes, validate, check-dedup,
  digest-regen) — verified by `make ci`. — verified 2026-09-02: `ALLOW_GITHUB_CHANGES=1 make ci` on the Phase 1 tree: lint, lock-check,
  coverage-python (2513 passed, 0 failed), test-node, verify-zero-skips, specs, remotes,
  validate and check-dedup all exit 0; `digest-regen` exits 0 once the regenerated bundle
  is committed (its `git diff --exit-code` compares against the index). The earlier mypy
  blocker was fixed in `test_workflow_contracts.py` before this run
- [ ] AC-3: `bash harness/node/scripts/run_vitest.sh` exits 0 from a clean
  checkout with node_modules installed — verified by `make test-node`. — open
  2026-09-02: the script exits 1 — vitest passes (53 passed, 11 skipped) but
  its `verify_zero_skips.py` call passes no waivers/decision-log arguments
  and prints `zero-skip: decision log missing/unreadable or contains no IDs;
  refusing exemptions`, whereas `make test-node` + `make verify-zero-skips`
  both exit 0; no plan item; needs a decision
- [ ] AC-4: `git grep -il pong -- ':!docs/specs'` returns no hits outside this
  spec and historical changelog entries — verified by that command's output.
  — open 2026-09-02: besides the two changelogs the grep reports
  `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` (since moved to `docs/reports/`), `harness/TEST-REPORT.md`,
  `harness/docs/BENCHMARK_REPORT.md` (superseded reports),
  `harness/shared/tests/test_documentation_truth.py` (the test asserting the
  Pong artefacts stay gone) and three files under
  `openspec/changes/add-neurosym-governed-synthesis/`; R-TDH-24 relocates the
  reports but strikes no mention; no plan item; needs a decision
- [x] AC-5: The `Dockerfile` CMD references an existing file under
  `harness/node/src/` — verified by `test -f` on the CMD path (container
  build optional). — verified 2026-09-02: CMD is
  `["node", "--loader", "tsx", "src/ai/nemotron/cli.ts", "--help"]` under
  `WORKDIR /app/harness/node`; `test -f harness/node/src/ai/nemotron/cli.ts`
  exits 0

## Invariants touched

- INV-2 (zero unapproved skips): preserved — pong tests are deleted with the
  feature, not skipped; `verify_zero_skips` runs in `make ci`.
- INV-5 (gates invoked by Make target): untouched — no Makefile or workflow
  changes in this PR.
- INV-1/INV-3/INV-6: untouched — no secret-scan, remote, or root-of-trust
  changes.

## Validation matrix

- `make ci` — ruff + mypy + compat + pytest + coverage gate + vitest +
  zero-skips + specs + remotes + validate + check-dedup + digest-regen
- coverage target: `governance-policy.json → coverage.lines` (aggregate; this
  PR deletes Node code and its tests together, Python coverage is unaffected)
- `cd harness/node && pnpm exec vitest run` — Node suite green post-deletion

## Backward compatibility

- The Pong demo was never part of the harness contract (no gate, digest, or
  protected path references it); its removal breaks no adopter surface.
- `harness/api_server` dev-runner port change (8000 → 8080) affects only the
  `python -m harness.api_server.main` convenience path; the FastAPI app object
  and `/api/orchestrate` contract are unchanged. Anyone needing the old
  behavior can pass the port explicitly via uvicorn.
- `run_vitest.sh` argument surface (`--coverage` passthrough) is preserved.

## Open questions

None — scope decisions (remove Pong, keep jvm stack as adopter template) were
made by the repository owner before implementation.
