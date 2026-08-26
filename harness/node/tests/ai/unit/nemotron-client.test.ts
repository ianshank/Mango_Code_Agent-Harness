/**
 * NVIDIA Nemotron Client Unit Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: OpenAI-compatible wire protocol with endpoint abstraction
 * - R-AI-NEMO-2: Strict type contracts for streaming, chat messages, and token telemetry
 * - C-AI-SEC-1: Secret sanitization and fail-closed configuration contracts
 */

import { describe, it, expect, vi } from 'vitest';
import {
  NemotronClient,
  DEFAULT_NEMOTRON_CONFIG,
} from '../../../src/ai/nemotron/nemotron-client.js';
import { SecretMasker } from '../../../src/ai/nemotron/secret-masker.js';
import { CircuitBreaker } from '../../../src/ai/nemotron/circuit-breaker.js';
import { runNemotronCli } from '../../../src/ai/nemotron/cli.js';
import * as fs from 'node:fs';

describe('Nemotron Unit Tests (R-AI-NEMO-1, C-AI-SEC-1)', () => {
  it('initializes with default configuration values', () => {
    const originalEnv = process.env['NEMOTRON_DEFAULT_MODEL'];
    delete process.env['NEMOTRON_DEFAULT_MODEL'];

    // Change cwd to prevent reading the workspace .env
    const originalCwd = process.cwd();
    process.chdir(fs.mkdtempSync('test-'));

    let client;
    try {
      client = new NemotronClient({
        apiKey: 'nvapi-test-dummy-key-1234567890',
      });
    } finally {
      process.chdir(originalCwd);
    }

    expect(client.config.baseUrl).toBe(DEFAULT_NEMOTRON_CONFIG.baseUrl);
    expect(client.config.defaultModel).toBeUndefined();

    if (originalEnv !== undefined) {
      process.env['NEMOTRON_DEFAULT_MODEL'] = originalEnv;
    }
    expect(client.config.timeoutMs).toBe(30000);
    expect(client.config.maxRetries).toBe(3);
  });

  it('allows overriding base URL, model, and retry timeouts', () => {
    const client = new NemotronClient({
      baseUrl: 'https://custom.api.nvidia.com/v1',
      apiKey: 'nvapi-custom-key-1234567890',
      defaultModel: 'nvidia/nemotron-4-340b-instruct',
      timeoutMs: 15000,
      maxRetries: 5,
    });

    expect(client.config.baseUrl).toBe('https://custom.api.nvidia.com/v1');
    expect(client.config.defaultModel).toBe('nvidia/nemotron-4-340b-instruct');
    expect(client.config.timeoutMs).toBe(15000);
    expect(client.config.maxRetries).toBe(5);
  });

  it('masks secret keys correctly without leaking raw token', () => {
    const rawKey =
      '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';
    const masked = SecretMasker.mask(rawKey);

    expect(masked).toBe('nvapi-sSeC...NcWq');
    expect(masked).not.toContain('5bhpL7H0NutynoON');

    expect(SecretMasker.mask('short')).toBe('****');
    expect(SecretMasker.mask('')).toBe('<UNSET>');
    expect(SecretMasker.mask(null)).toBe('<UNSET>');
    expect(SecretMasker.mask(undefined)).toBe('<UNSET>');
  });

  it('sanitizes secrets from error text and handles empty inputs', () => {
    const rawKey = 'nvapi-secret-key-to-redact-9999';
    const errorText = `Authentication failed for token ${rawKey} on endpoint`;
    const sanitized = SecretMasker.sanitize(errorText, [rawKey]);

    expect(sanitized).not.toContain(rawKey);
    expect(sanitized).toContain('nvapi-secr...9999');

    expect(SecretMasker.sanitize('', [rawKey])).toBe('');
    expect(
      SecretMasker.sanitize('Normal error', [null, undefined, 'short']),
    ).toBe('Normal error');
  });

  it('exercises circuit breaker transitions from OPEN to HALF_OPEN to CLOSED or OPEN', async () => {
    const cb = new CircuitBreaker({
      failureThreshold: 2,
      resetTimeoutMs: 20,
      halfOpenSuccessThreshold: 2,
    });

    expect(cb.getState()).toBe('CLOSED');
    expect(cb.canExecute()).toBe(true);

    cb.recordFailure();
    expect(cb.getState()).toBe('CLOSED');

    cb.recordFailure();
    expect(cb.getState()).toBe('OPEN');
    expect(cb.canExecute()).toBe(false);

    // Wait for cooldown to transition to HALF_OPEN
    await new Promise((res) => setTimeout(res, 35));
    expect(cb.getState()).toBe('HALF_OPEN');
    expect(cb.canExecute()).toBe(true);

    // In HALF_OPEN: 1 success
    cb.recordSuccess();
    expect(cb.getState()).toBe('HALF_OPEN');

    // In HALF_OPEN: 2nd success -> closes circuit
    cb.recordSuccess();
    expect(cb.getState()).toBe('CLOSED');

    // Fail again into OPEN
    cb.recordFailure();
    cb.recordFailure();
    expect(cb.getState()).toBe('OPEN');

    await new Promise((res) => setTimeout(res, 35));
    expect(cb.getState()).toBe('HALF_OPEN');

    // In HALF_OPEN: 1 failure -> trips immediately back to OPEN
    cb.recordFailure();
    expect(cb.getState()).toBe('OPEN');
  });
});
