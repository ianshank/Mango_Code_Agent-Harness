/**
 * Match Progression Functional Tests.
 * Requirement Citations:
 * - R-PONG-STATE-3: Multi-round match progression, serve alternation, and point scoring
 * - C-PONG-GOV-9: High-level game rule enforcement
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { Vector } from '../../../src/pong/core/vector.js';

describe('Match Progression (R-PONG-STATE-3)', () => {
  it('progresses through serves, scoring rounds, and concludes with a definitive winner', () => {
    const engine = new GameEngine({
      maxScore: 2,
      serveDelayMs: 10,
    });

    let recordedWinner: string | null = null;
    engine.subscribe({
      onGameOver: (winner) => {
        recordedWinner = winner;
      },
    });

    engine.start();

    // Fast-forward serve
    engine.tick(0.1);
    expect(engine.getSnapshot().phase).toBe('PLAYING');

    // Force score for Player 1 (ball out of bounds past P2)
    (engine as any).ball = {
      ...(engine as any).ball,
      position: Vector.create(engine.config.width + 20, 250),
    };
    engine.tick(0.016);

    expect(engine.getSnapshot().score.player1).toBe(1);
    expect(engine.getSnapshot().phase).toBe('ROUND_OVER');

    // Fast-forward next serve
    engine.tick(0.05); // SERVING
    engine.tick(0.1); // PLAYING

    // Force second score for Player 1 -> Match Victory
    (engine as any).ball = {
      ...(engine as any).ball,
      position: Vector.create(engine.config.width + 20, 250),
    };
    engine.tick(0.016);

    expect(engine.getSnapshot().score.player1).toBe(2);
    expect(engine.getSnapshot().phase).toBe('GAME_OVER');
    expect(recordedWinner).toBe('player1');
  });
});
