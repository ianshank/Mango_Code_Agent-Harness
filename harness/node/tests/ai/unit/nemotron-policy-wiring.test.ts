/**
 * Nemotron Policy Wiring Tests (docs/specs/node-policy-wiring.md).
 * Requirement Citations:
 * - R-NPW-1: client and CLI defaults are read from governance-policy.json
 * - R-NPW-2: the reader fails closed on a missing block or key
 * - R-NPW-3: the shipped policy loads and the exported default follows it
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import {
  loadNemotronPolicy,
  NEMOTRON_POLICY,
  NEMOTRON_POLICY_PATH,
} from '../../../src/ai/nemotron/policy.js';
import { DEFAULT_NEMOTRON_CONFIG } from '../../../src/ai/nemotron/nemotron-client.js';

const CLIENT_MODULE = '../../../src/ai/nemotron/nemotron-client.js';
const CLI_MODULE = '../../../src/ai/nemotron/cli.js';

/** Distinguishable fixture value: the shipped policy says 0 and the old literal was 3. */
const FIXTURE_MAX_RETRIES = 7;

type PolicyDocument = { nemotron?: Record<string, unknown> } & Record<
  string,
  unknown
>;

describe('Nemotron policy reader (R-NPW-1, R-NPW-2, R-NPW-3)', () => {
  const tempDirs: string[] = [];

  afterEach(() => {
    vi.doUnmock('node:fs');
    vi.resetModules();
    vi.restoreAllMocks();
    for (const dir of tempDirs.splice(0)) {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  /** Write a copy of the shipped policy with `mutate` applied; returns its path. */
  function policyCopy(mutate: (doc: PolicyDocument) => void): string {
    const doc = JSON.parse(
      fs.readFileSync(NEMOTRON_POLICY_PATH, 'utf-8'),
    ) as PolicyDocument;
    mutate(doc);
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nemo-policy-'));
    tempDirs.push(dir);
    const file = path.join(dir, 'governance-policy.json');
    fs.writeFileSync(file, JSON.stringify(doc), 'utf-8');
    return file;
  }

  /**
   * Freshly import `specifier` with reads of the shipped policy path served
   * from `policyPath`. The real reader runs against the real resolved path;
   * only the bytes differ, so a module-load throw here is the genuine one.
   */
  async function importAgainstPolicy(specifier: string, policyPath: string) {
    vi.resetModules();
    vi.doMock('node:fs', async (importOriginal) => {
      const actual = await importOriginal<typeof import('node:fs')>();
      const readFileSync: typeof actual.readFileSync = ((
        file: Parameters<typeof actual.readFileSync>[0],
        options: Parameters<typeof actual.readFileSync>[1],
      ) =>
        actual.readFileSync(
          file === NEMOTRON_POLICY_PATH ? policyPath : file,
          options,
        )) as typeof actual.readFileSync;
      return { ...actual, readFileSync, default: { ...actual, readFileSync } };
    });
    return import(specifier);
  }

  it('returns the four nemotron keys from an explicit policy path', () => {
    const file = policyCopy((doc) => {
      doc.nemotron!['max_retries'] = FIXTURE_MAX_RETRIES;
    });
    const policy = loadNemotronPolicy(file);
    expect(policy.max_retries).toBe(FIXTURE_MAX_RETRIES);
    expect(policy.timeout_ms).toBe(NEMOTRON_POLICY.timeout_ms);
    expect(policy.temperature).toBe(NEMOTRON_POLICY.temperature);
    expect(policy.max_tokens).toBe(NEMOTRON_POLICY.max_tokens);
  });

  it('liveness: DEFAULT_NEMOTRON_CONFIG and a default client follow a rewritten max_retries', async () => {
    const file = policyCopy((doc) => {
      doc.nemotron!['max_retries'] = FIXTURE_MAX_RETRIES;
    });
    const client = await importAgainstPolicy(CLIENT_MODULE, file);
    expect(client.DEFAULT_NEMOTRON_CONFIG.maxRetries).toBe(FIXTURE_MAX_RETRIES);
    const instance = new client.NemotronClient({
      apiKey: 'nvapi-policy-wiring-test-key-1234567890',
    });
    expect(instance.config.maxRetries).toBe(FIXTURE_MAX_RETRIES);
  });

  it('throws naming the key when nemotron.max_retries is absent', () => {
    const file = policyCopy((doc) => {
      delete doc.nemotron!['max_retries'];
    });
    expect(() => loadNemotronPolicy(file)).toThrow(/nemotron\.max_retries/);
  });

  it('throws naming the key when a key is present but not a number', () => {
    const file = policyCopy((doc) => {
      doc.nemotron!['timeout_ms'] = '30000';
    });
    expect(() => loadNemotronPolicy(file)).toThrow(
      /nemotron\.timeout_ms is missing or not a number/,
    );
  });

  it('throws when the policy has no nemotron block at all', () => {
    const file = policyCopy((doc) => {
      delete doc.nemotron;
    });
    expect(() => loadNemotronPolicy(file)).toThrow(/no "nemotron" block/);
  });

  it('client module load rejects when the policy lacks nemotron.max_retries', async () => {
    const file = policyCopy((doc) => {
      delete doc.nemotron!['max_retries'];
    });
    await expect(importAgainstPolicy(CLIENT_MODULE, file)).rejects.toThrow(
      /nemotron\.max_retries/,
    );
  });

  it('the shipped policy loads and DEFAULT_NEMOTRON_CONFIG mirrors it', () => {
    const shipped = loadNemotronPolicy();
    expect(shipped).toEqual(NEMOTRON_POLICY);
    expect(DEFAULT_NEMOTRON_CONFIG.maxRetries).toBe(shipped.max_retries);
    expect(DEFAULT_NEMOTRON_CONFIG.timeoutMs).toBe(shipped.timeout_ms);
  });

  it('CLI help and default temperature come from the policy, not a literal', async () => {
    const file = policyCopy((doc) => {
      doc.nemotron!['temperature'] = 1.25;
      doc.nemotron!['timeout_ms'] = 4321;
    });
    const cli = await importAgainstPolicy(CLI_MODULE, file);
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    await cli.runNemotronCli(['--help']);
    const help = logSpy.mock.calls.map((call) => String(call[0])).join('\n');
    expect(help).toContain('default: 1.25');
    expect(help).toContain('default: 4321');
  });
});
