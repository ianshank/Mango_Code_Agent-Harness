/**
 * Nemotron request defaults, read from the governance policy.
 *
 * Requirement Citations:
 * - R-NPW-1: `timeout_ms`, `max_retries`, `temperature` and `max_tokens` come
 *   from `harness/shared/governance-policy.json`, never from a literal here.
 * - R-NPW-2: The read fails closed. A policy file with no `nemotron` block, or
 *   one where any of the four keys is missing or not a number, throws a
 *   descriptive Error at module load rather than substituting a fallback. The
 *   Node client previously shipped a retry budget of three while the policy said `0`,
 *   and nothing detected the divergence because the literal never consulted the
 *   policy; a reader that quietly filled in a default on a malformed policy
 *   would recreate exactly that drift under a more trustworthy-looking name.
 *   This mirrors `harness/node/vitest.config.ts`, which reads the `coverage`
 *   block the same way for the same reason.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

/** Location of the shipped policy, resolved relative to this module. */
export const NEMOTRON_POLICY_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../shared/governance-policy.json',
);

/** The `nemotron` block of `governance-policy.json`, keys as written there. */
export interface NemotronPolicy {
  readonly timeout_ms: number;
  readonly max_retries: number;
  readonly temperature: number;
  readonly max_tokens: number;
}

const NEMOTRON_POLICY_KEYS = [
  'timeout_ms',
  'max_retries',
  'temperature',
  'max_tokens',
] as const satisfies readonly (keyof NemotronPolicy)[];

/**
 * Read and validate the `nemotron` block of a governance policy file.
 *
 * `policyPath` defaults to the shipped policy; tests pass a temp copy to prove
 * the client follows the file rather than a literal that happens to agree.
 */
export function loadNemotronPolicy(
  policyPath: string = NEMOTRON_POLICY_PATH,
): NemotronPolicy {
  const raw = JSON.parse(readFileSync(policyPath, 'utf-8')) as {
    nemotron?: Partial<Record<keyof NemotronPolicy, unknown>>;
  };
  const nemotron = raw.nemotron;
  if (!nemotron) {
    throw new Error(
      `${policyPath} declares no "nemotron" block; refusing to substitute client defaults`,
    );
  }
  for (const key of NEMOTRON_POLICY_KEYS) {
    if (typeof nemotron[key] !== 'number') {
      throw new Error(
        `${policyPath} nemotron.${key} is missing or not a number`,
      );
    }
  }
  return nemotron as NemotronPolicy;
}

/** The shipped policy, loaded once at module load (throws if malformed). */
export const NEMOTRON_POLICY: NemotronPolicy = loadNemotronPolicy();
