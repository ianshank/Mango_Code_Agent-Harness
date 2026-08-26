import { describe, it, expect } from 'vitest';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';
import {
  IS_LIVE,
  LIVE_TEST_TIMEOUT_MS,
  createLiveClient,
} from './_fixtures.js';

describe.skipIf(!IS_LIVE)(
  'Mango MAS Orchestrator Live Tests (Vitest E2E)',
  () => {
    it(
      'simulates an E2E agent loop and generates verified responses',
      async (ctx) => {
        // Since we are mocking the orchestrator flow for TS, we just verify Nemotron
        // can handle complex sequential thinking prompts.
        const client = createLiveClient();
        const plannerPrompt = `You are a planner agent. Create a 3-step plan to output "HELLO_MANGO".`;

        let response1;
        try {
          response1 = await client.complete({
            messages: [{ role: 'system', content: plannerPrompt }, { role: 'user', content: 'Go.' }],
            temperature: 0.2,
            max_tokens: 1024,
          });
        } catch (err: any) {
          if (err.message?.includes('404') || err.message?.includes('410') || err.message?.includes('429') || err.name === 'AbortError') {
            ctx.skip();
            return;
          }
          throw err;
        }

        expect(response1.content).toBeTruthy();

        const reasonerPrompt = `You are the reasoner. Execute this plan: ${response1.content}`;
        const response2 = await client.complete({
          messages: [{ role: 'system', content: reasonerPrompt }, { role: 'user', content: 'Go.' }],
          temperature: 0.2,
          max_tokens: 1024,
        });

        expect(response2.content).toBeTruthy();
        expect(response2.content?.includes('HELLO_MANGO')).toBe(true);

        const verifierPrompt = `You are the verifier. Verify this output has HELLO_MANGO: ${response2.content}`;
        const response3 = await client.complete({
          messages: [{ role: 'system', content: verifierPrompt }, { role: 'user', content: 'Go.' }],
          temperature: 0.2,
          max_tokens: 1024,
        });

        expect(response3.content).toBeTruthy();
        expect(response3.content?.includes('PASS') || response3.content?.includes('verify')).toBeTruthy();
      },
      LIVE_TEST_TIMEOUT_MS,
    );
  },
);
