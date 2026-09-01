/**
 * NVIDIA Nemotron CLI Live API End-to-End Tests.
 * Requirement Citations:
 * - R-AI-NEMO-3: Live E2E test to detect model deprecations
 * - R-AI-NEMO-4: Skipped dynamically if API key is not present
 * - C-AI-SEC-2: Do not leak API key to stdout
 */

import { describe, it, expect } from 'vitest';
import { runNemotronCli } from '../../../src/ai/nemotron/cli.js';
import * as fs from 'node:fs';
import * as path from 'node:path';

// Attempt to load .env from repo root to populate process.env for the test environment.
const envPath = path.resolve(__dirname, '../../../../../.env');
if (fs.existsSync(envPath)) {
  const content = fs.readFileSync(envPath, 'utf-8');
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
      const idx = trimmed.indexOf('=');
      const k = trimmed.slice(0, idx).trim();
      const v = trimmed.slice(idx + 1).trim();
      const allowedKeys = ['NVIDIA_API_KEY', 'NEMOTRON_DEFAULT_MODEL', 'NEMOTRON_BASE_URL'];
      if (allowedKeys.includes(k) && !process.env[k]) {
        process.env[k] = v;
      }
    }
  }
}

// Skip the suite entirely if there is no API key in the environment,
// ensuring we do not break uncredentialed CI jobs (R-AI-NEMO-4).
const hasApiKey = Boolean(process.env['NVIDIA_API_KEY']);

// This suite gates on its own key check rather than IS_LIVE, so it declares its
// egress intent independently (R-EGF-5).
if (hasApiKey) process.env['NEMOTRON_MODE'] ??= 'online';

describe.skipIf(!hasApiKey)('Nemotron CLI Live E2E (R-AI-NEMO-3, C-AI-SEC-2)', () => {
  it('executes a live completion request against the configured default model', async () => {
    let capturedOut = '';
    const origLog = console.log;
    console.log = (msg: string) => {
      capturedOut += msg + '\n';
    };

    let capturedErr = '';
    const origErr = console.error;
    console.error = (msg: string) => {
      capturedErr += msg + '\n';
    };

    const origProcessExitCode = process.exitCode;
    process.exitCode = undefined;

    try {
      // Execute the CLI natively. By not providing --model, it relies on NEMOTRON_DEFAULT_MODEL
      // which we are testing to ensure it is not deprecated (410 Gone) or otherwise broken.
      await runNemotronCli(['--prompt', 'Reply with exactly the word: LIVE_OK']);

      const apiKey = process.env['NVIDIA_API_KEY'] ?? '';
      if (apiKey) {
        expect(capturedOut).not.toContain(apiKey);
        expect(capturedErr).not.toContain(apiKey);
      }
      
      // If it failed with 410, capturedErr would contain the error and process.exitCode would be 1.
      expect(capturedErr).toBe('');
      expect(process.exitCode).toBeUndefined();
      
      // We expect the CLI to render its success format.
      expect(capturedOut).toContain('--- Nemotron Response');
      expect(capturedOut.toUpperCase()).toContain('LIVE_OK');
    } finally {
      console.log = origLog;
      console.error = origErr;
      process.exitCode = origProcessExitCode;
    }
  }, 60000); // 60s timeout for live API
});
