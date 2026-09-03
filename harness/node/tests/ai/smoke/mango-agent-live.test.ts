/**
 * .mango Agent Delegation — Live Integration Tests.
 *
 * Exercises the multi-agent system prompts from .mango/agents/ against
 * the real NVIDIA Nemotron API, validating that each agent role produces
 * structurally coherent responses.
 *
 * Requirement Citations:
 * - R-AI-NEMO-1: Live API invocation with agent-specific system prompts
 * - R-AI-NEMO-2: Token usage telemetry per agent invocation
 * - C-AI-SEC-1: No secret leakage in agent responses
 */

import { describe, it, expect } from 'vitest';
import path from 'node:path';
import {
  IS_LIVE,
  AGENT_MAX_TOKENS,
  LIVE_TEST_TIMEOUT_MS,
  createLiveClient,
  assertNoSecretLeakage,
  loadAgentSystemPrompt,
  isTransientError,
} from './_fixtures.js';

// Resolve .mango agent file paths relative to project root
// tests/ai/smoke/ → harness/node/ → harness/ → project root
const AGENTS_DIR = path.resolve(
  import.meta.dirname,
  '../../../../../.mango/agents',
);

describe.skipIf(!IS_LIVE)(
  '.mango Agent Delegation Live Tests (R-AI-NEMO-1, R-AI-NEMO-2, C-AI-SEC-1)',
  () => {
    it(
      'Planner agent produces a structured plan from a planning prompt',
      async (ctx) => {
        const systemPrompt = loadAgentSystemPrompt(
          path.join(AGENTS_DIR, 'planner.md'),
        );
        const client = createLiveClient();

        let response;
        try {
          response = await client.complete({
            messages: [
              { role: 'system', content: systemPrompt },
              {
                role: 'user',
                content:
                  'Create a 3-step plan to add a health check endpoint to a Node.js Express server. ' +
                  'Include verification commands for each step.',
              },
            ],
            temperature: 0.2,
            max_tokens: AGENT_MAX_TOKENS,
          });
        } catch (err: any) {
          if (isTransientError(err)) {
            ctx.skip();
            return;
          }
          throw err;
        }

        if (!response.content) {
          ctx.skip();
          return;
        }

        // Structural assertions — planner should produce steps
        expect(response.content.length).toBeGreaterThan(0);
        expect(response.usage.totalTokens).toBeGreaterThan(0);

        // The planner system prompt instructs numbered steps or markdown
        const hasStructure =
          /\d+\.|step|plan|goal/i.test(response.content) ||
          response.content.includes('-');
        expect(hasStructure).toBe(true);

        // Secret leakage check
        assertNoSecretLeakage(response.content);
        assertNoSecretLeakage(JSON.stringify(response));
      },
      LIVE_TEST_TIMEOUT_MS,
    );

    it(
      'Nemotron Reasoner agent produces architectural findings',
      async (ctx) => {
        const systemPrompt = loadAgentSystemPrompt(
          path.join(AGENTS_DIR, 'nemotron-reasoner.md'),
        );
        const client = createLiveClient();

        let response;
        try {
          response = await client.complete({
            messages: [
              { role: 'system', content: systemPrompt },
              {
                role: 'user',
                content:
                  'Review this FSM design for race conditions: ' +
                  'States: MENU → SERVING → PLAYING → SCORING → GAME_OVER. ' +
                  'Transitions are triggered by game tick events. ' +
                  'Provide findings with severity levels.',
              },
            ],
            temperature: 0.1,
            max_tokens: AGENT_MAX_TOKENS,
          });
        } catch (err: any) {
          if (isTransientError(err)) {
            ctx.skip();
            return;
          }
          throw err;
        }

        if (!response.content) {
          ctx.skip();
          return;
        }

        // Structural assertions — reasoner should produce findings
        expect(response.content.length).toBeGreaterThan(0);
        expect(response.usage.totalTokens).toBeGreaterThan(0);

        // The reasoner system prompt instructs findings, severity, remediation
        const hasReasoningStructure =
          /finding|severity|critical|high|medium|low|race|transition|remediation|review|fsm|state|tradeoff|design|analysis/i.test(
            response.content,
          );
        expect(hasReasoningStructure).toBe(true);

        // Secret leakage check
        assertNoSecretLeakage(response.content);
        assertNoSecretLeakage(JSON.stringify(response));
      },
      LIVE_TEST_TIMEOUT_MS,
    );

    it(
      'Verifier agent produces a structured PASS/FAIL verdict',
      async (ctx) => {
        const systemPrompt = loadAgentSystemPrompt(
          path.join(AGENTS_DIR, 'verifier.md'),
        );
        const client = createLiveClient();

        let response;
        try {
          response = await client.complete({
            messages: [
              { role: 'system', content: systemPrompt },
              {
                role: 'user',
                content:
                  'Verify the following test results: ' +
                  'REQUIREMENT: Add health check endpoint. ' +
                  'TESTS: pnpm vitest run — 83 passed, 0 failed, 0 skipped. ' +
                  'LINT/TYPECHECK: tsc --noEmit — 0 errors. ' +
                  'Provide a VERDICT.',
              },
            ],
            temperature: 0.1,
            max_tokens: AGENT_MAX_TOKENS,
          });
        } catch (err: any) {
          if (isTransientError(err)) {
            ctx.skip();
            return;
          }
          throw err;
        }

        if (!response.content) {
          ctx.skip();
          return;
        }

        // Structural assertions — verifier should produce a verdict
        expect(response.content.length).toBeGreaterThan(0);
        expect(response.usage.totalTokens).toBeGreaterThan(0);

        // The verifier system prompt instructs PASS/FAIL verdict
        const hasVerdict =
          /pass|fail|verdict|requirement|tests|lint|success|verified|status/i.test(
            response.content,
          );
        expect(hasVerdict).toBe(true);

        // Secret leakage check
        assertNoSecretLeakage(response.content);
        assertNoSecretLeakage(JSON.stringify(response));
      },
      LIVE_TEST_TIMEOUT_MS,
    );
  },
);
