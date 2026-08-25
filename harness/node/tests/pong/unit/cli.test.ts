/**
 * CLI Runner Unit Tests.
 * Requirement Citations:
 * - R-PONG-RENDER-7: ANSI terminal runner CLI execution
 * - R-PONG-AI-5: Autonomous bot tournament support
 * - C-PONG-GOV-9: Safe CLI arguments parsing and execution
 */

import { describe, it, expect } from 'vitest';
import { runCli } from '../../../src/pong/cli/pong-cli.js';

describe('Pong CLI Runner (R-PONG-RENDER-7, R-PONG-AI-5)', () => {
  it('executes standalone CLI runner in autoplay mode for specified ticks', async () => {
    // Run CLI with fast ticks
    await expect(
      runCli(['--autoplay', '--ticks', '5', '--difficulty', 'easy']),
    ).resolves.toBeUndefined();
    await expect(
      runCli(['--ticks', '5', '--difficulty', 'hard']),
    ).resolves.toBeUndefined();
    await expect(runCli(['--ticks', '2'])).resolves.toBeUndefined();
  });
});
