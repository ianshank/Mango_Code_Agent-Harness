/**
 * NVIDIA Nemotron Functional Completion Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: Multi-turn prompt completion and parameter clamping
 * - R-AI-NEMO-2: Token usage metrics and latency telemetry
 */

import { describe, it, expect } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

describe('Nemotron Functional Tests (R-AI-NEMO-1, R-AI-NEMO-2)', () => {
  it('executes multi-turn chat completion with telemetry metrics', async () => {
    let capturedBody: any = null;

    const mockFetch: typeof fetch = async (_url, init) => {
      capturedBody = JSON.parse(init?.body as string);
      const mockResponse = {
        id: 'nemo-chat-12345',
        model: 'nvidia/llama-3.1-nemotron-70b-instruct',
        choices: [
          {
            index: 0,
            message: {
              role: 'assistant',
              content: 'Deterministic state synchronization verified.',
            },
            finish_reason: 'stop',
          },
        ],
        usage: {
          prompt_tokens: 42,
          completion_tokens: 8,
          total_tokens: 50,
        },
      };

      return new Response(JSON.stringify(mockResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-key-1234567890',
      },
      mockFetch,
    );

    const response = await client.complete({
      messages: [
        { role: 'system', content: 'You are a formal verification architect.' },
        { role: 'user', content: 'Verify physics simulation.' },
      ],
      temperature: 0.1,
      top_p: 0.8,
      max_tokens: 1024,
    });

    expect(response.content).toBe(
      'Deterministic state synchronization verified.',
    );
    expect(response.usage.promptTokens).toBe(42);
    expect(response.usage.completionTokens).toBe(8);
    expect(response.usage.totalTokens).toBe(50);
    expect(response.latencyMs).toBeGreaterThanOrEqual(0);

    expect(capturedBody.temperature).toBe(0.1);
    expect(capturedBody.top_p).toBe(0.8);
    expect(capturedBody.max_tokens).toBe(1024);
  });

  it('clamps extreme temperature and top_p parameters within safe boundaries', async () => {
    let capturedBody: any = null;

    const mockFetch: typeof fetch = async (_url, init) => {
      capturedBody = JSON.parse(init?.body as string);
      return new Response(
        JSON.stringify({
          choices: [{ message: { role: 'assistant', content: 'OK' } }],
        }),
        { status: 200 },
      );
    };

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-key-1234567890',
      },
      mockFetch,
    );

    await client.complete({
      messages: [{ role: 'user', content: 'Test parameters' }],
      temperature: 5.0, // Should clamp to 2.0
      top_p: 2.0, // Should clamp to 1.0
    });

    expect(capturedBody.temperature).toBe(2.0);
    expect(capturedBody.top_p).toBe(1.0);
  });
});
