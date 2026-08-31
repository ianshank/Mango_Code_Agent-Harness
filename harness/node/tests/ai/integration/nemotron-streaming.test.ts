/**
 * NVIDIA Nemotron SSE Streaming Integration Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: OpenAI-compatible SSE streaming integration
 * - R-AI-NEMO-2: Async iterable delta chunking and termination
 */

import { describe, it, expect } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

describe('Nemotron Streaming Integration (R-AI-NEMO-1, R-AI-NEMO-2)', () => {
  it('parses Server-Sent Events stream chunks and terminates on [DONE]', async () => {
    const ssePayload = [
      'data: {"id":"nemo-1","model":"nvidia/llama-3.1-nemotron-70b-instruct","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n',
      'data: {"id":"nemo-1","model":"nvidia/llama-3.1-nemotron-70b-instruct","choices":[{"index":0,"delta":{"content":" World"},"finish_reason":null}]}\n\n',
      'data: {"id":"nemo-1","model":"nvidia/llama-3.1-nemotron-70b-instruct","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":"stop"}]}\n\n',
      'data: [DONE]\n\n',
    ].join('');

    const mockFetch: typeof fetch = async () => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(ssePayload));
          controller.close();
        },
      });

      return new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    };

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-key-1234567890',
      },
      mockFetch,
    );

    const chunks: string[] = [];
    for await (const chunk of client.stream({
      messages: [{ role: 'user', content: 'Say Hello World' }],
    })) {
      chunks.push(chunk.delta);
    }

    expect(chunks.join('')).toBe('Hello World!');
  });

  it('handles stream HTTP error status and records failure', async () => {
    const mockFetch: typeof fetch = async () => {
      return new Response(JSON.stringify({ error: 'Service Unavailable' }), {
        status: 503,
      });
    };

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-key-1234567890',
      },
      mockFetch,
    );

    await expect(async () => {
      for await (const _ of client.stream({
        messages: [{ role: 'user', content: 'Test fail' }],
      })) {
        // empty
      }
    }).rejects.toThrow(/Nemotron API Stream Error HTTP 503/);
  });
});
