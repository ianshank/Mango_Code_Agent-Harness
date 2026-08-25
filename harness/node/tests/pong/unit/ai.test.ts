/**
 * AI Opponent Unit Tests.
 * Requirement Citations:
 * - R-PONG-AI-5: Multi-tier AI opponent, trajectory prediction, and latency simulation
 * - C-PONG-GOV-9: High-precision deterministic calculation
 */

import { describe, it, expect } from 'vitest';
import { AIOpponent } from '../../../src/pong/ai/ai-opponent.js';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { Vector } from '../../../src/pong/core/vector.js';

describe('AI Opponent Controller (R-PONG-AI-5)', () => {
  it('initializes with default medium difficulty and allows dynamic difficulty switching', () => {
    const ai = new AIOpponent('player2', 'medium');
    expect(ai).toBeDefined();

    ai.setDifficulty('expert');
    ai.setDifficulty('easy');
    ai.reset();
  });

  it('predicts intercept Y position when ball is heading towards AI', () => {
    const engine = new GameEngine();
    engine.start();

    const ai = new AIOpponent('player2', 'expert');
    const snapshot = engine.getSnapshot();

    // Set ball moving towards player 2
    const customSnapshot = {
      ...snapshot,
      ball: {
        ...snapshot.ball,
        position: Vector.create(400, 250),
        velocity: Vector.create(300, 100),
      },
    };

    const predictedY = ai.predictInterceptY(customSnapshot, {
      difficulty: 'expert',
      reactionDelayTicks: 0,
      predictionAccuracy: 1.0,
      jitterAmount: 0,
    });

    expect(predictedY).toBeGreaterThanOrEqual(0);
    expect(predictedY).toBeLessThanOrEqual(engine.config.height);
  });

  it('returns steering direction toward targeted position', () => {
    const engine = new GameEngine();
    engine.start();
    const ai = new AIOpponent('player2', 'expert');

    // Position ball near bottom
    const bottomBallSnapshot = {
      ...engine.getSnapshot(),
      player2: {
        ...engine.getSnapshot().player2,
        position: Vector.create(750, 50), // Paddle at top
      },
      ball: {
        ...engine.getSnapshot().ball,
        position: Vector.create(400, 400), // Ball at bottom moving right
        velocity: Vector.create(300, 0),
      },
    };

    const direction = ai.update(bottomBallSnapshot);
    expect(direction).toBe(1); // Steer Down
  });
});
