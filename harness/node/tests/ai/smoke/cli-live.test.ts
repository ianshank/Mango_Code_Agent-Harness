/**
 * NVIDIA Nemotron CLI Runner — Live Subprocess Validation.
 *
 * Exercises the CLI entrypoint as a real subprocess, validating
 * exit codes, stdout/stderr content, and secret safety.
 *
 * Requirement Citations:
 * - R-AI-NEMO-1: CLI invocation and execution interface
 * - C-AI-SEC-1: No raw API key leakage in subprocess output
 */

import { describe, it, expect } from 'vitest';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import {
  IS_LIVE,
  LIVE_API_KEY,
  LIVE_TEST_TIMEOUT_MS,
  assertNoSecretLeakage,
} from './_fixtures.js';

const execFileAsync = promisify(execFile);

const CLI_SCRIPT = path.resolve(
  import.meta.dirname,
  '../../../src/ai/nemotron/cli.ts',
);

/** Platform-portable execution options — uses shell on Windows for .cmd shims. */
const EXEC_OPTIONS = {
  shell: process.platform === 'win32',
  cwd: path.resolve(import.meta.dirname, '../../..'),
} as const;

describe('Nemotron CLI Subprocess Tests (R-AI-NEMO-1)', () => {
  it(
    'prints help documentation with --help flag',
    async () => {
      const { stdout } = await execFileAsync(
        'npx',
        ['tsx', CLI_SCRIPT, '--help'],
        EXEC_OPTIONS,
      );

      expect(stdout).toContain('NVIDIA Nemotron Ultra CLI Runner');
      expect(stdout).toContain('--prompt');
      expect(stdout).toContain('--model');
      expect(stdout).toContain('--stream');
      expect(stdout).toContain('--json');
    },
    LIVE_TEST_TIMEOUT_MS,
  );

  it(
    'prints usage when no --prompt is provided',
    async () => {
      const { stdout } = await execFileAsync(
        'npx',
        ['tsx', CLI_SCRIPT],
        EXEC_OPTIONS,
      );

      expect(stdout).toContain('Usage:');
      expect(stdout).toContain('--prompt');
    },
    LIVE_TEST_TIMEOUT_MS,
  );
});

describe.skipIf(!IS_LIVE)(
  'Nemotron CLI Live Subprocess Tests (R-AI-NEMO-1, C-AI-SEC-1)',
  () => {
    it(
      'completes a prompt in --json mode via subprocess',
      async () => {
        const { stdout, stderr } = await execFileAsync(
          'npx',
          [
            'tsx',
            CLI_SCRIPT,
            '--prompt',
            'Reply with exactly: CLI OK',
            '--json',
          ],
          {
            ...EXEC_OPTIONS,
            env: { ...process.env },
            timeout: LIVE_TEST_TIMEOUT_MS,
          },
        );

        // Secret leakage check on all output
        assertNoSecretLeakage(stdout);
        assertNoSecretLeakage(stderr);

        // stdout should be valid JSON
        const parsed = JSON.parse(stdout.trim());
        expect(parsed).toHaveProperty('content');
        expect(parsed).toHaveProperty('usage');
        expect(parsed).toHaveProperty('latencyMs');
        expect(parsed.content.length).toBeGreaterThan(0);
        expect(parsed.usage.totalTokens).toBeGreaterThan(0);
      },
      LIVE_TEST_TIMEOUT_MS,
    );

    it(
      'streams output via --stream flag without leaking secrets',
      async () => {
        const { stdout, stderr } = await execFileAsync(
          'npx',
          [
            'tsx',
            CLI_SCRIPT,
            '--prompt',
            'Reply with exactly: STREAM CLI OK',
            '--stream',
          ],
          {
            ...EXEC_OPTIONS,
            env: { ...process.env },
            timeout: LIVE_TEST_TIMEOUT_MS,
          },
        );

        // Secret leakage check
        assertNoSecretLeakage(stdout);
        assertNoSecretLeakage(stderr);

        // Should contain the streaming header and some content
        expect(stdout).toContain('Nemotron Streaming Response');
        expect(stdout.length).toBeGreaterThan(40);
      },
      LIVE_TEST_TIMEOUT_MS,
    );
  },
);
