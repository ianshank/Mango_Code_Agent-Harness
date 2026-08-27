/**
 * Mango Agent & Nemotron Delegation User Journey Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: Subagent delegation and structured output synthesis
 * - R-AI-NEMO-2: Streaming token accumulation during delegation
 * - INV-7: Bounded agent delegation and auditability
 */

import { describe, it, expect, vi } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

interface SubagentFinding {
  readonly id: string;
  readonly severity: string;
  readonly description: string;
}

interface SubagentReviewOutput {
  readonly status: string;
  readonly findings: readonly SubagentFinding[];
  readonly formalProof: string;
}

interface PlannerOutput {
  readonly steps: readonly string[];
}

interface VerifierOutput {
  readonly verified: boolean;
  readonly invariantEvidence: string;
}

interface RetryOutput {
  readonly status: string;
  readonly retrySuccessful: boolean;
}

describe('Mango Agent Delegation User Journey (R-AI-NEMO-1, R-AI-NEMO-2, INV-7)', () => {
  it('simulates Mango Agent delegating an architectural review task to Nemotron and receiving structured output', async () => {
    const reviewData: SubagentReviewOutput = {
      status: 'APPROVED',
      findings: [
        {
          id: 'ARCH-01',
          severity: 'LOW',
          description: 'Consider adding jitter to exponential backoff delay.',
        },
      ],
      formalProof:
        'All 6 state transitions in FSM are deterministic and acyclic.',
    };

    const mockReviewResponse = {
      id: 'nemo-review-999',
      model: 'nvidia/llama-3.1-nemotron-70b-instruct',
      choices: [
        {
          index: 0,
          message: {
            role: 'assistant',
            content: JSON.stringify(reviewData),
          },
          finish_reason: 'stop',
        },
      ],
      usage: {
        prompt_tokens: 150,
        completion_tokens: 65,
        total_tokens: 215,
      },
    };

    const mockFetch = vi.fn(async () => {
      return new Response(JSON.stringify(mockReviewResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-key-1234567890',
      },
      mockFetch as unknown as typeof fetch,
    );

    // Step 1: Mango Agent prepares subagent task payload
    const userGoal = 'Perform formal review of Pong FSM and backoff logic.';
    const subagentMessages = [
      {
        role: 'system' as const,
        content:
          'You are the nemotron-reasoner subagent. Output valid JSON with review status and formal proof.',
      },
      {
        role: 'user' as const,
        content: userGoal,
      },
    ];

    // Step 2: Invoke Nemotron
    const result = await client.complete({
      messages: subagentMessages,
      temperature: 0.1,
    });

    // Step 3: Parse and verify structured response
    const parsed = JSON.parse(result.content) as SubagentReviewOutput;
    expect(parsed.status).toBe('APPROVED');
    expect(parsed.findings.length).toBe(1);
    expect(parsed.formalProof).toContain('deterministic');
    expect(result.usage.totalTokens).toBe(215);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('simulates multi-agent reasoning chain (Planner -> Nemotron Reasoner -> Verifier)', async () => {
    let callCount = 0;
    const mockFetch = vi.fn(async () => {
      callCount++;
      const payload =
        callCount === 1
          ? {
              id: 'plan-1',
              model: 'nvidia/llama-3.1-nemotron-70b-instruct',
              choices: [
                {
                  index: 0,
                  message: {
                    role: 'assistant',
                    content: JSON.stringify({
                      steps: [
                        'Decompose requirements',
                        'Synthesize FSM invariants',
                        'Execute tests',
                      ],
                    } satisfies PlannerOutput),
                  },
                  finish_reason: 'stop',
                },
              ],
              usage: {
                prompt_tokens: 50,
                completion_tokens: 30,
                total_tokens: 80,
              },
            }
          : {
              id: 'verify-2',
              model: 'nvidia/llama-3.1-nemotron-70b-instruct',
              choices: [
                {
                  index: 0,
                  message: {
                    role: 'assistant',
                    content: JSON.stringify({
                      verified: true,
                      invariantEvidence: 'INV-1 through INV-7 satisfied.',
                    } satisfies VerifierOutput),
                  },
                  finish_reason: 'stop',
                },
              ],
              usage: {
                prompt_tokens: 80,
                completion_tokens: 40,
                total_tokens: 120,
              },
            };

      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-key-multiagent',
      },
      mockFetch as unknown as typeof fetch,
    );

    // Stage 1: Planning Phase
    const planRes = await client.complete({
      messages: [
        {
          role: 'system',
          content: 'You are the planner subagent in .mango/agents/planner.md.',
        },
        { role: 'user', content: 'Generate implementation roadmap for Pong.' },
      ],
    });
    const plan = JSON.parse(planRes.content) as PlannerOutput;
    expect(plan.steps).toHaveLength(3);

    // Stage 2: Verification Phase
    const verifyRes = await client.complete({
      messages: [
        {
          role: 'system',
          content:
            'You are the verifier subagent in .mango/agents/verifier.md.',
        },
        {
          role: 'user',
          content: `Verify execution of plan: ${JSON.stringify(plan.steps)}`,
        },
      ],
    });
    const verification = JSON.parse(verifyRes.content) as VerifierOutput;
    expect(verification.verified).toBe(true);
    expect(callCount).toBe(2);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('simulates streaming reasoning delegation with real-time token accumulation', async () => {
    const sseChunks = [
      'data: {"id":"s-1","model":"nemo","choices":[{"index":0,"delta":{"content":"Analyzing"},"finish_reason":null}]}\n\n',
      'data: {"id":"s-2","model":"nemo","choices":[{"index":0,"delta":{"content":" state transitions..."},"finish_reason":null}]}\n\n',
      'data: {"id":"s-3","model":"nemo","choices":[{"index":0,"delta":{"content":" Verified PASS."},"finish_reason":"stop"}]}\n\n',
      'data: [DONE]\n\n',
    ];

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        for (const chunk of sseChunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });

    const mockFetch = vi.fn(async () => {
      return new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    });

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-streaming-stream',
      },
      mockFetch as unknown as typeof fetch,
    );

    let accumulatedText = '';
    for await (const chunk of client.stream({
      messages: [
        { role: 'user', content: 'Stream reasoning trace for FSM audit.' },
      ],
    })) {
      accumulatedText += chunk.delta;
    }

    expect(accumulatedText).toBe(
      'Analyzing state transitions... Verified PASS.',
    );
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('recovers gracefully when subagent outputs malformed JSON on first try and retries', async () => {
    let attempts = 0;
    const mockFetch = vi.fn(async () => {
      attempts++;
      const content =
        attempts === 1
          ? 'Here is my review: status=APPROVED (not valid JSON)'
          : JSON.stringify({
              status: 'APPROVED',
              retrySuccessful: true,
            } satisfies RetryOutput);

      return new Response(
        JSON.stringify({
          id: `attempt-${attempts}`,
          model: 'nvidia/llama-3.1-nemotron-70b-instruct',
          choices: [
            {
              index: 0,
              message: { role: 'assistant', content },
              finish_reason: 'stop',
            },
          ],
          usage: {
            prompt_tokens: 30,
            completion_tokens: 20,
            total_tokens: 50,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });

    const client = new NemotronClient(
      {
        defaultModel: 'test-model',
        apiKey: 'nvapi-mock-retry-key',
      },
      mockFetch as unknown as typeof fetch,
    );

    async function executeWithJsonRetry(maxTries = 2): Promise<RetryOutput> {
      for (let i = 0; i < maxTries; i++) {
        const res = await client.complete({
          messages: [
            {
              role: 'user',
              content: 'Evaluate invariant status in JSON format.',
            },
          ],
        });
        try {
          return JSON.parse(res.content) as RetryOutput;
        } catch {
          if (i === maxTries - 1) {
            throw new Error('Failed to obtain JSON');
          }
        }
      }
      throw new Error('Failed to obtain JSON');
    }

    const finalOutput = await executeWithJsonRetry(2);
    expect(finalOutput.status).toBe('APPROVED');
    expect(finalOutput.retrySuccessful).toBe(true);
    expect(attempts).toBe(2);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});
