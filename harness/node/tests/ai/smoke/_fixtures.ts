/**
 * Shared Live Test Fixtures for Nemotron Smoke Tests.
 *
 * Provides a single source of truth for:
 * - Live API gating (IS_LIVE)
 * - Cost-conscious client factory
 * - Post-test secret leakage assertions
 *
 * Requirement Citations:
 * - C-AI-SEC-1: Secret sanitization enforcement in test output
 */

import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';
import type { NemotronConfig } from '../../../src/ai/nemotron/types.js';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Resolves the NVIDIA API key from process.env or .env files,
 * mirroring the NemotronClient.resolveEnvironment() logic.
 */
function resolveApiKey(): string {
  const envKey = process.env['NVIDIA_API_KEY'];
  if (envKey) return envKey;

  // Walk up from cwd looking for .env (same as NemotronClient)
  const candidates = [
    path.resolve(process.cwd(), '.env'),
    path.resolve(process.cwd(), '../../.env'),
    path.resolve(process.cwd(), '../.env'),
  ];

  for (const p of candidates) {
    if (fs.existsSync(p)) {
      try {
        const content = fs.readFileSync(p, 'utf-8');
        for (const line of content.split('\n')) {
          const trimmed = line.trim();
          if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
            const idx = trimmed.indexOf('=');
            const k = trimmed.slice(0, idx).trim();
            const v = trimmed.slice(idx + 1).trim();
            if (k === 'NVIDIA_API_KEY') return v;
          }
        }
      } catch {
        // Best-effort ignore
      }
    }
  }

  return '';
}

/** The live API key resolved from environment or .env files. */
export const LIVE_API_KEY: string = resolveApiKey();

/** Whether live API tests should run. */
export const IS_LIVE: boolean = LIVE_API_KEY.length > 0;

/** Default token budget for smoke tests — minimizes cost. */
export const SMOKE_MAX_TOKENS = 50;

/** Token budget for agent delegation tests — needs more room for structured responses. */
export const AGENT_MAX_TOKENS = 128;

/** Maximum acceptable latency in milliseconds for a single API call in smoke tests. */
export const LATENCY_CEILING_MS = 25_000;

/** Timeout for individual test cases (ms). */
export const LIVE_TEST_TIMEOUT_MS = 90_000;

/**
 * Creates a NemotronClient configured for live smoke testing.
 * Uses real API key from environment with cost-conscious defaults.
 */
export function createLiveClient(
  overrides?: Partial<NemotronConfig>,
): NemotronClient {
  return new NemotronClient({
    apiKey: LIVE_API_KEY,
    timeoutMs: LATENCY_CEILING_MS,
    maxRetries: 1,
    baseBackoffMs: 500,
    maxBackoffMs: 2000,
    ...overrides,
  });
}

/**
 * Asserts that no raw API key substring appears in captured output.
 * Satisfies DevSecOps finding S-1: prevent secret leakage in test output.
 *
 * @throws Error if the raw API key is found in the output string.
 */
export function assertNoSecretLeakage(
  output: string,
  apiKey: string = LIVE_API_KEY,
): void {
  if (!apiKey || apiKey.length < 10) return; // Skip for short/empty keys

  // Check the full key
  if (output.includes(apiKey)) {
    throw new Error(
      `SECRET LEAKAGE DETECTED: Raw API key found in test output. ` +
        `Key prefix: ${apiKey.slice(0, 10)}...`,
    );
  }

  // Also check the middle portion (excludes prefix/suffix that masker shows)
  const middle = apiKey.slice(10, -4);
  if (middle.length > 8 && output.includes(middle)) {
    throw new Error(
      `SECRET LEAKAGE DETECTED: API key middle segment found in test output. ` +
        `This indicates incomplete masking.`,
    );
  }
}

/**
 * Reads the body content from a .mango agent markdown file,
 * stripping YAML frontmatter.
 */
export function loadAgentSystemPrompt(agentFilePath: string): string {
  // Dynamically import fs to keep this module lightweight
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('fs') as typeof import('fs');
  const content = fs.readFileSync(agentFilePath, 'utf-8');

  // Strip YAML frontmatter (--- ... ---)
  const frontmatterEnd = content.indexOf('---', 3);
  if (frontmatterEnd !== -1) {
    return content.slice(frontmatterEnd + 3).trim();
  }
  return content.trim();
}
