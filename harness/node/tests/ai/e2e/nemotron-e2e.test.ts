/**
 * NVIDIA Nemotron CLI End-to-End Tests.
 * Requirement Citations:
 * - R-AI-NEMO-1: CLI invocation and execution interface
 * - C-AI-SEC-1: Safe CLI parameter handling
 */

import { describe, it, expect, vi } from 'vitest';
import { runNemotronCli } from '../../../src/ai/nemotron/cli.js';
import { NemotronClient } from '../../../src/ai/nemotron/nemotron-client.js';

describe('Nemotron CLI E2E Tests (R-AI-NEMO-1, C-AI-SEC-1)', () => {
  it('displays help documentation when invoked with --help', async () => {
    let capturedOut = '';
    const origLog = console.log;
    console.log = (msg: string) => {
      capturedOut += msg + '\n';
    };

    try {
      await runNemotronCli(['--help']);
      expect(capturedOut).toContain('NVIDIA Nemotron Ultra CLI Runner');
      expect(capturedOut).toContain('--prompt');
      expect(capturedOut).toContain('--model');
    } finally {
      console.log = origLog;
    }
  });

  it('handles missing prompt argument gracefully by printing usage', async () => {
    let capturedOut = '';
    const origLog = console.log;
    console.log = (msg: string) => {
      capturedOut += msg + '\n';
    };

    try {
      await runNemotronCli([]);
      expect(capturedOut).toContain('Usage:');
    } finally {
      console.log = origLog;
    }
  });

  it('executes standard completion in JSON format', async () => {
    let capturedOut = '';
    const origLog = console.log;
    console.log = (msg: string) => {
      capturedOut += msg + '\n';
    };

    const origComplete = NemotronClient.prototype.complete;
    NemotronClient.prototype.complete = async () => ({
      id: 'mock-id',
      model: 'nvidia/llama-3.1-nemotron-70b-instruct',
      content: 'CLI response verified.',
      choices: [
        {
          index: 0,
          message: { role: 'assistant', content: 'CLI response verified.' },
          finishReason: 'stop',
        },
      ],
      usage: { promptTokens: 10, completionTokens: 5, totalTokens: 15 },
      latencyMs: 120,
    });

    try {
      await runNemotronCli(['--prompt', 'Test prompt', '--json']);
      expect(capturedOut).toContain('CLI response verified.');
      expect(capturedOut).toContain('"totalTokens": 15');
    } finally {
      console.log = origLog;
      NemotronClient.prototype.complete = origComplete;
    }
  });

  it('executes streaming completion and error path in CLI', async () => {
    let stdoutBuffer = '';
    const origWrite = process.stdout.write;
    (process.stdout as any).write = (chunk: string) => {
      stdoutBuffer += chunk;
      return true;
    };

    const origStream = NemotronClient.prototype.stream;
    NemotronClient.prototype.stream = async function* () {
      yield { id: '1', model: 'mock', delta: 'Streamed ', finishReason: null };
      yield { id: '2', model: 'mock', delta: 'Token', finishReason: 'stop' };
    };

    try {
      await runNemotronCli([
        '--prompt',
        'Test stream',
        '--system',
        'Custom system instruction',
        '--model',
        'nvidia/nemotron-4-340b-instruct',
        '--temperature',
        '0.5',
        '--stream',
      ]);
      expect(stdoutBuffer).toContain('Streamed Token');
    } finally {
      process.stdout.write = origWrite;
      NemotronClient.prototype.stream = origStream;
    }

    // Test error branch
    let capturedErr = '';
    const origErr = console.error;
    console.error = (msg: string) => {
      capturedErr += msg + '\n';
    };

    const origComplete = NemotronClient.prototype.complete;
    NemotronClient.prototype.complete = async () => {
      throw new Error('Simulated upstream network timeout');
    };

    try {
      await runNemotronCli(['--prompt', 'Fail test']);
      expect(capturedErr).toContain(
        '[Nemotron CLI Error]: Simulated upstream network timeout',
      );
    } finally {
      console.error = origErr;
      NemotronClient.prototype.complete = origComplete;
    }
  });
});
