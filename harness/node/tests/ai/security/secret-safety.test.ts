/**
 * Nemotron Security & Secret Sanitization Tests.
 * Requirement Citations:
 * - C-AI-SEC-1: Secret sanitization and prevention of sensitive key leakage
 * - INV-1: Secret scan covers working tree and full history
 */

import { describe, it, expect } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

describe('Nemotron Security & Secret Safety (C-AI-SEC-1, INV-1)', () => {
  it('fails closed with a clear error when NVIDIA_API_KEY is not configured', async () => {
    const origKey = process.env['NVIDIA_API_KEY'];
    delete process.env['NVIDIA_API_KEY'];

    try {
      const client = new NemotronClient({
        apiKey: '',
      });

      await expect(async () => {
        await client.complete({
          messages: [{ role: 'user', content: 'Test key presence' }],
        });
      }).rejects.toThrow(/NVIDIA_API_KEY is not configured/);
    } finally {
      if (origKey) process.env['NVIDIA_API_KEY'] = origKey;
    }
  });

  it('redacts sensitive API tokens from server error response messages', async () => {
    const rawSecret = 'nvapi-super-sensitive-secret-token-abcdef123456';

    const mockFetch: typeof fetch = async () => {
      // Simulate an upstream server returning an error body containing the raw key
      return new Response(
        `Error: Provided token [${rawSecret}] is expired or unauthorized.`,
        { status: 401 },
      );
    };

    const client = new NemotronClient(
      { apiKey: rawSecret, defaultModel: 'test-model' },
      mockFetch,
    );

    try {
      await client.complete({
        messages: [{ role: 'user', content: 'Test redaction' }],
      });
      expect.fail('Should have thrown HTTP 401 error');
    } catch (err: any) {
      expect(err.message).not.toContain(rawSecret);
      expect(err.message).toContain('nvapi-supe...3456');
    }
  });
});
