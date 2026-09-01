/**
 * NVIDIA Nemotron SSE Streaming Edge-Case Integration Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: OpenAI-compatible SSE streaming integration
 * - R-AI-NEMO-2: Async iterable delta chunking and termination
 * - R-AI-RES-3: Circuit breaker isolation for streaming requests
 */

import { describe, it, expect } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

function sseResponse(payload: string): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(payload));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

function makeClient(mockFetch: typeof fetch): NemotronClient {
  return new NemotronClient(
    {
      apiKey: 'nvapi-mock-key-1234567890',
      defaultModel: 'test-model',
      maxRetries: 0,
      baseBackoffMs: 1,
      maxBackoffMs: 5,
    },
    mockFetch,
  );
}

describe('Nemotron Streaming Edge Cases (R-AI-NEMO-1, R-AI-NEMO-2, R-AI-RES-3)', () => {
  it('yields nothing when the upstream response has no body', async () => {
    const mockFetch: typeof fetch = async () =>
      new Response(null, { status: 200 });

    const client = makeClient(mockFetch);
    const chunks: string[] = [];
    for await (const chunk of client.stream({
      messages: [{ role: 'user', content: 'empty body' }],
    })) {
      chunks.push(chunk.delta);
    }

    expect(chunks).toEqual([]);
  });

  it('skips comments, non-data lines, and malformed frames, and ends cleanly without [DONE]', async () => {
    const ssePayload = [
      ': keepalive comment must be skipped',
      'event: ping',
      '',
      'data: {"choices":[{"index":0,"delta":{},"finish_reason":null}]}',
      'data: this-is-not-json{',
      'data: {"id":"s-9","model":"srv-model","choices":[{"index":0,"delta":{"content":"tail"},"finish_reason":"stop"}]}',
      '',
    ].join('\n');

    const mockFetch: typeof fetch = async () => sseResponse(ssePayload);

    const client = makeClient(mockFetch);
    const chunks: { id: string; model: string; delta: string }[] = [];
    for await (const chunk of client.stream({
      messages: [{ role: 'user', content: 'edge frames' }],
    })) {
      chunks.push({ id: chunk.id, model: chunk.model, delta: chunk.delta });
    }

    // The malformed frame is dropped; the empty-delta frame yields '' and the
    // final frame carries its own id/model. Stream terminates on reader close.
    expect(chunks).toEqual([
      { id: '', model: 'test-model', delta: '' },
      { id: 's-9', model: 'srv-model', delta: 'tail' },
    ]);
  });

  it('trips the circuit breaker on repeated stream failures and fast-fails afterwards', async () => {
    const mockFetch: typeof fetch = async () =>
      new Response('Fatal Internal Server Error', { status: 500 });

    const client = makeClient(mockFetch);

    const consume = async (): Promise<void> => {
      for await (const chunk of client.stream({
        messages: [{ role: 'user', content: 'fail' }],
      })) {
        void chunk;
      }
    };

    // Default failure threshold is 5; each non-retried 500 records one failure.
    for (let i = 0; i < 5; i++) {
      await expect(consume()).rejects.toThrow(
        /Nemotron API Stream Error HTTP 500/,
      );
    }

    await expect(consume()).rejects.toThrow(/Circuit breaker is OPEN/);
  });
});
