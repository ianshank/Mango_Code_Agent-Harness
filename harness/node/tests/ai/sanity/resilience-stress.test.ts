/**
 * Nemotron Resilience & Stress Sanity Tests.
 * Requirement Citations:
 * - R-AI-RES-3: Exponential backoff with jitter and circuit breaker resilience
 */

import { describe, it, expect } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

describe('Nemotron Resilience & Stress Tests (R-AI-RES-3)', () => {
  it('retries automatically on HTTP 429 rate limits with exponential backoff and succeeds', async () => {
    let callCount = 0;

    const mockFetch: typeof fetch = async () => {
      callCount++;
      if (callCount < 3) {
        return new Response('Rate limit exceeded. Please retry.', {
          status: 429,
        });
      }
      return new Response(
        JSON.stringify({
          choices: [
            { message: { role: 'assistant', content: 'Success after 429' } },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };

    const client = new NemotronClient(
      {
        apiKey: 'nvapi-mock-key-1234567890',
        defaultModel: 'test-model',
        maxRetries: 3,
        baseBackoffMs: 10,
        maxBackoffMs: 50,
      },
      mockFetch,
    );

    const result = await client.complete({
      messages: [{ role: 'user', content: 'Test rate limit recovery' }],
    });

    expect(callCount).toBe(3);
    expect(result.content).toBe('Success after 429');
  });

  it('trips circuit breaker on repeated non-retryable failures and fast-fails subsequent calls', async () => {
    const mockFetch: typeof fetch = async () => {
      return new Response('Fatal Internal Server Error', {
        status: 500,
      });
    };

    const client = new NemotronClient(
      {
        apiKey: 'nvapi-mock-key-1234567890',
        defaultModel: 'test-model',
        maxRetries: 1,
        baseBackoffMs: 5,
      },
      mockFetch,
    );

    // Call 1 fails
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'Fail 1' }] }),
    ).rejects.toThrow();

    // Call 2 fails
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'Fail 2' }] }),
    ).rejects.toThrow();

    // Call 3 fails
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'Fail 3' }] }),
    ).rejects.toThrow();

    // Call 4 fails
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'Fail 4' }] }),
    ).rejects.toThrow();

    // Call 5 fails -> Circuit Breaker trips to OPEN
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'Fail 5' }] }),
    ).rejects.toThrow();

    // Call 6 should fail immediately via Circuit Breaker
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'Fast fail' }] }),
    ).rejects.toThrow(/Circuit breaker is OPEN/);
  });
});
