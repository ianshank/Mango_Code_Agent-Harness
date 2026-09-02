# Spec: node-policy-wiring

> Child spec of `docs/specs/tech-debt-hardening-plan.md` R-TDH-13 / AC-13.
> Scaffolded by `make spec NAME=node-policy-wiring`. A spec is the contract
> the `verifier` role checks against. Without one, "done" is undefined.

## Problem statement

`harness/shared/governance-policy.json` carries a `nemotron` block
(`temperature`, `max_tokens`, `timeout_ms`, `max_retries`) and the Python side
reads it through `policy_loader.nemotron_defaults()`. The Node client never
did. `harness/node/src/ai/nemotron/nemotron-client.ts` shipped
`DEFAULT_NEMOTRON_CONFIG = { timeoutMs: 30000, maxRetries: 3, ... }` and
restated `0.2` / `4096` inline in both `complete()` and `stream()`;
`harness/node/src/ai/nemotron/cli.ts` restated `0.2` again for its
`--temperature` default and in its help text.

Evidence of live drift, not a hypothetical: the shipped policy says
`nemotron.max_retries: 0` while the Node literal said `3`, so a Node caller
retried three times against a policy that budgets zero retries. Nothing
detected it because the literal never consulted the policy, and
`tests/ai/unit/nemotron-client.test.ts` pinned `maxRetries` to the literal
`3` rather than to the policy. `CLAUDE.md` forbids exactly this ("No
hard-coded values; thresholds come from `governance-policy.json`").
`harness/node/vitest.config.ts` already reads the `coverage` block the right
way -- path resolved relative to the module, fail closed on a missing key --
so the pattern exists in the Node tree; the client did not use it.

## Requirements

- R-NPW-1: `nemotron-client.ts` and `cli.ts` MUST source `timeoutMs`,
  `maxRetries`, the default request `temperature` and the default
  `max_tokens` from the `nemotron` block of
  `harness/shared/governance-policy.json` via one shared reader module,
  `harness/node/src/ai/nemotron/policy.ts`, resolved relative to the module
  file the way `vitest.config.ts` resolves its path. No literal for any of
  the four values may remain under `harness/node/src`.
- R-NPW-2: The reader MUST fail closed: `loadNemotronPolicy()` throws an
  `Error` whose message names the file and the offending key when the
  `nemotron` block is absent or when any of `timeout_ms`, `max_retries`,
  `temperature`, `max_tokens` is missing or not a number. It MUST NOT
  substitute a fallback value. Because the client reads the policy at module
  load, a malformed policy makes importing `nemotron-client.ts` reject.
- R-NPW-3: `loadNemotronPolicy(path?: string)` MUST accept an explicit path so
  a test can point it at a temp copy of the policy and prove the loaded value
  flows into `DEFAULT_NEMOTRON_CONFIG` and into a `NemotronClient` built with
  no override -- a liveness test with a distinguishable value, not one that
  passes whether or not the wiring exists.
- C-NPW-1: `DEFAULT_NEMOTRON_CONFIG` MUST keep its exported name and
  `NemotronConfig` shape, and no public function signature in
  `nemotron-client.ts` or `cli.ts` may change. Callers that pass their own
  `timeoutMs` / `maxRetries` / `temperature` / `max_tokens` see no change.
- C-NPW-2: `baseUrl`, `baseBackoffMs`, `maxBackoffMs` and `top_p` have no
  policy key today and MUST be left as they are; wiring them is
  `tech-debt-hardening-plan.md` R-TDH-23's job, not this spec's.
- C-NPW-3: The change MUST NOT modify `harness/shared/governance-policy.json`,
  `harness/node/vitest.config.ts`, `harness/node/package.json` or any Python
  file; it reads the policy, it does not reshape it.

## Acceptance criteria

- [ ] AC-1: `pnpm exec vitest run tests/ai/unit/nemotron-policy-wiring.test.ts`
      writes a temp copy of the policy with `nemotron.max_retries` rewritten
      to a distinguishable value (7; the shipped value is 0 and the old
      literal was 3), asserts `loadNemotronPolicy(tempPath).max_retries` is 7,
      and asserts `DEFAULT_NEMOTRON_CONFIG.maxRetries` and
      `new NemotronClient({ apiKey }).config.maxRetries` both follow it when
      the client module is loaded against that copy
      · stage: `make test-node` (R-NPW-1, R-NPW-3)
- [ ] AC-2: `pnpm exec vitest run tests/ai/unit/nemotron-policy-wiring.test.ts`
      asserts `loadNemotronPolicy()` throws matching `/nemotron\.max_retries/`
      on a copy lacking that key, throws matching
      `/nemotron\.timeout_ms is missing or not a number/` when the key is a
      string, throws matching `/no "nemotron" block/` when the block is
      absent, and that importing `nemotron-client.ts` against the
      key-less copy rejects with the same key-naming message
      · stage: `make test-node` (R-NPW-2)
- [ ] AC-3: `pnpm exec vitest run tests/ai/unit/nemotron-policy-wiring.test.ts`
      loads the shipped policy with no path argument and asserts
      `DEFAULT_NEMOTRON_CONFIG.maxRetries === nemotron.max_retries` and
      `DEFAULT_NEMOTRON_CONFIG.timeoutMs === nemotron.timeout_ms`; the same
      file asserts `runNemotronCli(['--help'])` prints the policy's
      `temperature` and `timeout_ms` when loaded against a copy carrying
      distinguishable values (1.25 / 4321)
      · stage: `make test-node` (R-NPW-1, R-NPW-3)
- [ ] AC-4: `git grep -n "maxRetries: 3" harness/node/src` returns nothing, and
      `git grep -nE "(: 0\.2|\?\? 4096|timeoutMs: 30000)" harness/node/src/ai/nemotron`
      returns nothing · stage: `make lint-node` (R-NPW-1)
- [ ] AC-5: `pnpm exec vitest run tests/ai` passes with
      `tests/ai/unit/nemotron-client.test.ts` pinning the default client's
      `timeoutMs` / `maxRetries` to `DEFAULT_NEMOTRON_CONFIG` rather than to
      numerals, and every pre-existing test file under `tests/ai` unchanged
      except that one assertion; the exported `DEFAULT_NEMOTRON_CONFIG` still
      satisfies `NemotronConfig` under `pnpm exec tsc --noEmit`
      · stage: `make test-node` (C-NPW-1)
- [ ] AC-6: `git diff --stat -- harness/shared/governance-policy.json
      harness/node/vitest.config.ts harness/node/package.json '*.py'` is
      empty, and `git grep -n "baseBackoffMs: 500" harness/node/src` still
      returns the one line in `nemotron-client.ts` (the unwired values are
      untouched, left for R-TDH-23) · stage: `make lint-node` (C-NPW-2, C-NPW-3)
- [ ] AC-7: `make test-node` meets the per-file thresholds from
      `governance-policy.json → coverage` for `src/ai/nemotron/policy.ts`
      (both branches of every guard exercised by AC-2), and
      `pnpm exec eslint . --max-warnings=0 && pnpm exec knip` exit 0 with
      no unused export reported for `policy.ts`
      · stage: `make lint-node` (R-NPW-2, C-NPW-1)

## Steps

1. Add `harness/node/src/ai/nemotron/policy.ts` -- consumes
   `harness/shared/governance-policy.json` at module load; produces
   `NemotronPolicy`, `loadNemotronPolicy(path?)`, `NEMOTRON_POLICY` and
   `NEMOTRON_POLICY_PATH`.
2. Edit `harness/node/src/ai/nemotron/nemotron-client.ts` -- consumes
   `NEMOTRON_POLICY`; `DEFAULT_NEMOTRON_CONFIG.timeoutMs` / `.maxRetries` and
   the inline `temperature` / `max_tokens` fallbacks in `complete()` and
   `stream()` read from it. Leaves `baseUrl`, backoff and `top_p` alone.
3. Edit `harness/node/src/ai/nemotron/cli.ts` -- consumes `NEMOTRON_POLICY`
   for the `--temperature` default and the help-text defaults.
4. Add `harness/node/tests/ai/unit/nemotron-policy-wiring.test.ts` --
   consumes steps 1-3; produces the liveness, fail-closed and shipped-policy
   assertions of AC-1..AC-3.
5. Edit `harness/node/tests/ai/unit/nemotron-client.test.ts` -- replace the
   two numeral pins with `DEFAULT_NEMOTRON_CONFIG` pins (AC-5).
6. Run `make test-node`, `make verify-zero-skips`, `make lint-node`,
   `make specs` -- produces the gate evidence for the validation matrix.

## Files touched

- `harness/node/src/ai/nemotron/policy.ts` (new)
- `harness/node/src/ai/nemotron/nemotron-client.ts`
- `harness/node/src/ai/nemotron/cli.ts`
- `harness/node/tests/ai/unit/nemotron-policy-wiring.test.ts` (new)
- `harness/node/tests/ai/unit/nemotron-client.test.ts`
- `docs/specs/node-policy-wiring.md` (this file)

None of these matches `protected_paths` in `governance-policy.json`; no
`infra-reviewed` attestation is needed.

## Invariants touched

- INV-2 (zero unapproved skips): no test is skipped or waived; the new file
  adds eight always-running cases. `make verify-zero-skips` proves it from
  `.governance/vitest-results.json`.
- INV-4 / the coverage gate: `make test-node` keeps every file under
  `src/ai/nemotron` above the per-file floors read from
  `governance-policy.json → coverage`; the new module is fully exercised
  because every guard has a throwing test (AC-2) and a passing test (AC-1).
- No other invariant in `harness/CONTRACT.md` is affected: this change reads
  the policy, it does not alter enforcement paths, remotes, or protected
  files.

## Validation matrix

- `make test-node` -- Vitest with coverage; thresholds (lines, statements,
  functions, branches, `per_file`) come from
  `governance-policy.json → coverage`, never restated here. Proves
  AC-1, AC-2, AC-3, AC-5, AC-7 (R-NPW-1, R-NPW-2, R-NPW-3, C-NPW-1).
- `make verify-zero-skips` -- INV-2 over the run above.
- `make lint-node` -- ESLint (`--max-warnings=0`), Prettier, Knip; plus the
  `git grep` observables of AC-4 and AC-6 (R-NPW-1, C-NPW-2, C-NPW-3).
- `make specs` -- this document passes the structural and plan tiers.
- coverage target: `governance-policy.json → coverage.lines` and
  `coverage.branches`, applied per file.

## Backward compatibility

`DEFAULT_NEMOTRON_CONFIG` keeps its name and shape; `NemotronClient`,
`runNemotronCli` and every option type are unchanged. Callers that supply
their own `timeoutMs`, `maxRetries`, `temperature` or `max_tokens` observe
no difference. Callers that relied on the *defaults* see them move to the
policy's values: `timeoutMs` stays 30000 (policy and literal agreed);
`maxRetries` moves from 3 to the policy's 0. That is the fix, not a
regression -- the policy has budgeted zero retries all along and the Python
bridge already honours it. Anyone who wants Node retries changes
`nemotron.max_retries` in the policy, once, for both stacks.

The one new failure mode is a throw at import time when the policy is
malformed. Previously a malformed policy was invisible to the Node client
because it never read it; now the client refuses to start with an
unspecified retry or timeout budget, which is the same posture
`vitest.config.ts` already takes for coverage thresholds.

## Open questions

None blocking. `baseBackoffMs`, `maxBackoffMs`, `top_p` and `baseUrl` remain
literals by design (C-NPW-2) until R-TDH-23 gives them policy keys; the
stale `(default: 3)` doc comment on `NemotronConfig.maxRetries` in
`types.ts` is outside this spec's file list and should be corrected by
whichever change next touches that file.
