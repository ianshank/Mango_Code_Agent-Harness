#!/usr/bin/env node
/**
 * Standalone Interactive CLI Pong Executable.
 * Requirement Citations:
 * - R-PONG-RENDER-7: ANSI Terminal game runner
 * - R-PONG-AI-5: Autonomous bot tournament support
 * - C-PONG-GOV-9: Clean CLI lifecycle management
 */

import { GameEngine } from '../core/game-engine.js';
import { TerminalRenderer } from '../render/terminal-renderer.js';
import { AIOpponent } from '../ai/ai-opponent.js';
import { GameLoop } from '../loop/game-loop.js';
import type { AIDifficulty } from '../ai/types.js';

export function runCli(args: string[] = process.argv.slice(2)): Promise<void> {
  return new Promise((resolve) => {
    const isAutoplay = args.includes('--autoplay');
    const ticksIndex = args.indexOf('--ticks');
    const rawTicks = ticksIndex !== -1 ? args[ticksIndex + 1] : undefined;
    const maxTicks = rawTicks ? parseInt(rawTicks, 10) : 300;

    const diffIndex = args.indexOf('--difficulty');
    const rawDiff = diffIndex !== -1 ? args[diffIndex + 1] : undefined;
    const difficulty: AIDifficulty = rawDiff
      ? (rawDiff as AIDifficulty)
      : 'medium';

    const engine = new GameEngine({
      maxScore: 3,
      serveDelayMs: 200,
    });

    const renderer = new TerminalRenderer(64, 20);
    const aiPlayer1 = isAutoplay ? new AIOpponent('player1', difficulty) : null;
    const aiPlayer2 = new AIOpponent('player2', difficulty);

    let executedTicks = 0;

    engine.start();

    const loop = new GameLoop(
      {
        update: (dt) => {
          executedTicks++;

          const snapshot = engine.getSnapshot();

          // AI Updates
          if (aiPlayer1) {
            const p1Dir = aiPlayer1.update(snapshot);
            engine.setPlayerDirection('player1', p1Dir, dt);
          }
          const p2Dir = aiPlayer2.update(snapshot);
          engine.setPlayerDirection('player2', p2Dir, dt);

          engine.tick(dt);

          if (snapshot.phase === 'GAME_OVER' || executedTicks >= maxTicks) {
            loop.stop();
            renderer.render(engine.getSnapshot());
            console.log(
              `\n\x1b[32mMatch Finished in ${executedTicks} ticks!\x1b[0m`,
            );
            console.log(
              `Final Score: P1: ${snapshot.score.player1} - P2: ${snapshot.score.player2}`,
            );
            console.log(
              `Winner: ${snapshot.score.winner ?? 'Draw/MaxTicks'}\n`,
            );
            renderer.destroy();
            resolve();
          }
        },
        render: () => {
          renderer.render(engine.getSnapshot());
        },
      },
      1000 / 30, // 30 FPS for terminal
    );

    loop.start();
  });
}

// Auto-run if executed directly
if (
  typeof process !== 'undefined' &&
  process.argv[1] &&
  process.argv[1].endsWith('pong-cli.ts')
) {
  runCli().catch(console.error);
}
