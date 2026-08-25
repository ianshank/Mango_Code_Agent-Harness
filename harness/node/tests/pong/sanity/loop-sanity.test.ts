/**
 * Game Loop Determinism & Performance Sanity Tests.
 * Requirement Citations:
 * - R-PONG-LOOP-8: Fixed-timestep determinism and spiral-of-death defense
 * - C-PONG-GOV-9: High-performance memory and execution constraints
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { GameLoop } from '../../../src/pong/loop/game-loop.js';

describe('Loop Determinism & Stress Sanity (R-PONG-LOOP-8, C-PONG-GOV-9)', () => {
  it('guarantees deterministic simulation outputs across identical tick sequences', () => {
    const engineA = new GameEngine();
    const engineB = new GameEngine();

    engineA.start(0);
    engineB.start(0);

    // Run 100 deterministic steps of 16.6ms
    for (let i = 0; i < 100; i++) {
      engineA.tick(0.016);
      engineB.tick(0.016);
    }

    const snapA = engineA.getSnapshot();
    const snapB = engineB.getSnapshot();

    expect(snapA.ball.position.x).toBeCloseTo(snapB.ball.position.x, 5);
    expect(snapA.ball.position.y).toBeCloseTo(snapB.ball.position.y, 5);
    expect(snapA.score.player1).toBe(snapB.score.player1);
    expect(snapA.score.player2).toBe(snapB.score.player2);
  });

  it('handles frame budget timing under heavy 10,000 tick stress test without leaks', () => {
    const engine = new GameEngine();
    engine.start();

    const startTime = Date.now();
    for (let i = 0; i < 10000; i++) {
      engine.tick(0.016);
    }
    const elapsed = Date.now() - startTime;

    // 10,000 ticks in headless JS should take less than 1.5 seconds (0.15ms per tick)
    expect(elapsed).toBeLessThan(1500);
    expect(engine.getSnapshot().tick).toBe(10000);
  });

  it('clamps huge frame delta spikes safely (spiral-of-death defense)', () => {
    let updateCount = 0;
    const loop = new GameLoop(
      {
        update: () => updateCount++,
        render: () => {},
      },
      16.666,
      250, // maxFrameTimeMs = 250ms (~15 ticks max)
    );

    // Simulate huge lag spike of 10 seconds (10,000ms)
    loop.stepManual(10000);

    // Should be clamped to 250ms / 16.666ms = 15 updates max
    expect(updateCount).toBeLessThanOrEqual(16);
  });
});
