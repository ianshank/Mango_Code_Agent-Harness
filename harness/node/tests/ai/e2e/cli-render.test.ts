/**
 * NVIDIA Nemotron CLI Rendering End-to-End Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: CLI invocation of Nemotron reasoning models
 * - C-AI-SEC-1: Safe argument parsing and secret protection
 */

import { describe, it, expect, vi } from 'vitest';
import { runNemotronCli } from '../../../src/ai/nemotron/cli.js';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

describe('Nemotron CLI Rendering E2E (R-AI-NEMO-1, C-AI-SEC-1)', () => {
  it('renders the human-readable completion summary with model, latency, and token totals', async () => {
    let capturedOut = '';
    const origLog = console.log;
    console.log = (msg: string) => {
      capturedOut += msg + '\n';
    };

    const origComplete = NemotronClient.prototype.complete;
    NemotronClient.prototype.complete = async () => ({
      id: 'mock-id',
      model: 'nvidia/llama-3.1-nemotron-70b-instruct',
      content: 'Readable CLI answer.',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: 'Readable CLI answer.' },
          finishReason: 'stop',
        },
      ],
      usage: { promptTokens: 10, completionTokens: 5, totalTokens: 15 },
      latencyMs: 120,
    });

    try {
      await runNemotronCli(['--prompt', 'Render human output']);
      expect(capturedOut).toContain(
        '--- Nemotron Response [nvidia/llama-3.1-nemotron-70b-instruct] (120ms) ---',
      );
      expect(capturedOut).toContain('Readable CLI answer.');
      expect(capturedOut).toContain(
        'Tokens: 10 prompt + 5 completion = 15 total',
      );
    } finally {
      console.log = origLog;
      NemotronClient.prototype.complete = origComplete;
    }
  });

  it('auto-runs when the module is loaded as the process entrypoint', async () => {
    let capturedOut = '';
    const origLog = console.log;
    const origArgv1 = process.argv[1];
    console.log = (msg: string) => {
      capturedOut += msg + '\n';
    };

    try {
      // Simulate `node cli.js` (no --prompt in the process args) so the
      // entrypoint guard fires and the auto-run lands on the help path
      // without any network or client construction.
      process.argv[1] = '/virtual/entrypoint/cli.js';
      vi.resetModules();
      await import('../../../src/ai/nemotron/cli.js');
      expect(capturedOut).toContain('NVIDIA Nemotron Ultra CLI Runner');
      expect(capturedOut).toContain('Usage:');
    } finally {
      console.log = origLog;
      if (origArgv1 !== undefined) {
        process.argv[1] = origArgv1;
      }
      vi.resetModules();
    }
  });
});
