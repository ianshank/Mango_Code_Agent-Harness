/**
 * Pause, Resume, and Reset Functional Tests.
 * Requirement Citations:
 * - R-PONG-STATE-3: Mid-game state persistence, pause behavior, and complete resets
 * - C-PONG-GOV-9: Deterministic state lifecycle
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';

describe('Pause, Resume & Reset Lifecycle (R-PONG-STATE-3)', () => {
  it('freezes simulation ticks during pause and resumes seamlessly', () => {
    const engine = new GameEngine();
    engine.start();

    // Fast-forward to PLAYING
    engine.tick(2.0);
    const prePauseBallPos = { ...engine.getSnapshot().ball.position };

    // Pause
    const isPaused = engine.togglePause();
    expect(isPaused).toBe(true);
    expect(engine.getSnapshot().phase).toBe('PAUSED');

    // Tick while paused should not advance ball
    engine.tick(1.0);
    expect(engine.getSnapshot().ball.position).toEqual(prePauseBallPos);

    // Resume
    const isResumed = engine.togglePause();
    expect(isResumed).toBe(false);
    expect(engine.getSnapshot().phase).toBe('PLAYING');

    // Tick should now advance
    engine.tick(0.1);
    expect(engine.getSnapshot().ball.position).not.toEqual(prePauseBallPos);
  });

  it('resets entire state back to MENU on reset()', () => {
    const engine = new GameEngine();
    engine.start();
    engine.tick(1.0);

    engine.reset();
    expect(engine.getSnapshot().phase).toBe('MENU');
    expect(engine.getSnapshot().score.player1).toBe(0);
    expect(engine.getSnapshot().score.player2).toBe(0);
  });
});
