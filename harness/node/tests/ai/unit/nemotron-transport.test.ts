/**
 * NVIDIA Nemotron Transport and Response-Mapping Unit Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: Fault-tolerant network transport and outage isolation
 * - R-AI-NEMO-2: Strict type contracts for chat messages and token telemetry
 * - R-AI-RES-3: Timeout abort handling without hung requests
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

function makeClient(mockFetch?: typeof fetch, timeoutMs?: number) {
  return new NemotronClient(
    {
      apiKey: 'nvapi-mock-key-1234567890',
      defaultModel: 'test-model',
      maxRetries: 0,
      baseBackoffMs: 1,
      maxBackoffMs: 5,
      ...(timeoutMs !== undefined ? { timeoutMs } : {}),
    },
    mockFetch,
  );
}

describe('Nemotron Transport & Mapping (R-AI-NEMO-1, R-AI-NEMO-2, R-AI-RES-3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('converts an abort on timeout into a descriptive TimeoutError', async () => {
    // A fetch that never resolves on its own and rejects with AbortError once
    // the client-side timeout fires, matching real fetch semantics.
    const hangingFetch: typeof fetch = (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const err = new Error('This operation was aborted');
          err.name = 'AbortError';
          reject(err);
        });
      });

    const client = makeClient(hangingFetch, 10);
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'hang' }] }),
    ).rejects.toThrow(/timed out after 10ms/);
  });

  it('rethrows non-abort transport failures unchanged', async () => {
    const failingFetch: typeof fetch = async () => {
      throw new Error('socket hang up');
    };

    const client = makeClient(failingFetch);
    await expect(
      client.complete({ messages: [{ role: 'user', content: 'boom' }] }),
    ).rejects.toThrow('socket hang up');
  });

  it('falls back to globalThis.fetch when no custom fetch is injected', async () => {
    const stubbedFetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            choices: [
              { message: { role: 'assistant', content: 'via global fetch' } },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
    );
    vi.stubGlobal('fetch', stubbedFetch);

    const client = makeClient(undefined);
    const result = await client.complete({
      messages: [{ role: 'user', content: 'use global' }],
    });

    expect(result.content).toBe('via global fetch');
    expect(stubbedFetch).toHaveBeenCalledTimes(1);
  });

  it('maps a minimal upstream payload onto safe response defaults', async () => {
    const emptyFetch: typeof fetch = async () =>
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });

    const client = makeClient(emptyFetch);
    const result = await client.complete({
      messages: [{ role: 'user', content: 'minimal' }],
    });

    expect(result.id).toMatch(/^nemo-/);
    expect(result.model).toBe('test-model');
    expect(result.content).toBe('');
    expect(result.choices).toEqual([]);
    expect(result.usage).toEqual({
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
    });
  });

  it('fills per-choice defaults for sparse choice objects', async () => {
    const sparseFetch: typeof fetch = async () =>
      new Response(JSON.stringify({ id: 'srv-id', choices: [{}] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });

    const client = makeClient(sparseFetch);
    const result = await client.complete({
      messages: [{ role: 'user', content: 'sparse' }],
    });

    expect(result.id).toBe('srv-id');
    expect(result.choices).toEqual([
      {
        index: 0,
        message: { role: 'assistant', content: '' },
        finishReason: null,
      },
    ]);
  });
});
