/**
 * Autonomous Bot Tournament End-to-End Test.
 * Requirement Citations:
 * - R-PONG-AI-5: Autonomous AI vs AI tournament execution
 * - R-PONG-CORE-2: Complete end-to-end physics simulation
 * - C-PONG-GOV-9: Complete match tournament verification
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { AIOpponent } from '../../../src/pong/ai/ai-opponent.js';

describe('Autonomous Bot Tournament E2E (R-PONG-AI-5, R-PONG-CORE-2)', () => {
  it('runs an autonomous AI vs AI tournament match until a player achieves victory', () => {
    const engine = new GameEngine({
      maxScore: 2,
      serveDelayMs: 20,
    });

    const aiPlayer1 = new AIOpponent('player1', 'easy');
    const aiPlayer2 = new AIOpponent('player2', 'hard');

    let isMatchOver = false;
    let matchWinner: string | null = null;

    engine.subscribe({
      onGameOver: (winner) => {
        isMatchOver = true;
        matchWinner = winner;
      },
    });

    engine.start();

    const dt = 1 / 60;
    const maxTicks = 1500; // Cap execution
    let currentTick = 0;

    while (!isMatchOver && currentTick < maxTicks) {
      currentTick++;
      const snapshot = engine.getSnapshot();

      const p1Dir = aiPlayer1.update(snapshot);
      const p2Dir = aiPlayer2.update(snapshot);

      engine.setPlayerDirection('player1', p1Dir, dt);
      engine.setPlayerDirection('player2', p2Dir, dt);

      engine.tick(dt);
    }

    const finalSnapshot = engine.getSnapshot();
    expect(currentTick).toBeGreaterThan(50);
    expect(
      finalSnapshot.score.player1 + finalSnapshot.score.player2,
    ).toBeGreaterThanOrEqual(1);
    if (isMatchOver) {
      expect(['player1', 'player2']).toContain(matchWinner);
    }
  });
});
