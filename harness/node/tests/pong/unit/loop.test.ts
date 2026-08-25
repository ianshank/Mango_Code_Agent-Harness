/**
 * Game Loop Unit Tests.
 * Requirement Citations:
 * - R-PONG-LOOP-8: Fixed-timestep accumulator loop, frame pacing, and manual stepping
 * - C-PONG-GOV-9: High-precision execution
 */

import { describe, it, expect } from 'vitest';
import { GameLoop } from '../../../src/pong/loop/game-loop.js';

describe('Game Loop (R-PONG-LOOP-8)', () => {
  it('starts and stops loop timer lifecycle cleanly', async () => {
    let updateCount = 0;
    let renderCount = 0;

    const loop = new GameLoop(
      {
        update: () => updateCount++,
        render: () => renderCount++,
      },
      16,
      250,
    );

    expect(loop.running).toBe(false);
    loop.start();
    expect(loop.running).toBe(true);

    // Calling start again when running is a no-op
    loop.start();

    // Wait for at least 1 timer tick
    await new Promise((r) => setTimeout(r, 40));

    loop.stop();
    expect(loop.running).toBe(false);
    expect(updateCount).toBeGreaterThanOrEqual(1);
    expect(renderCount).toBeGreaterThanOrEqual(1);
  });

  it('exercises requestAnimationFrame and cancelAnimationFrame in browser environment', () => {
    let rafCallback: Function | null = null;
    let cancelledId = 0;

    const originalWindow = (globalThis as any).window;
    const originalRAF = (globalThis as any).requestAnimationFrame;
    const originalCAF = (globalThis as any).cancelAnimationFrame;

    (globalThis as any).window = {};
    (globalThis as any).requestAnimationFrame = (cb: Function) => {
      rafCallback = cb;
      return 42;
    };
    (globalThis as any).cancelAnimationFrame = (id: number) => {
      cancelledId = id;
    };

    try {
      let updateCalls = 0;
      const loop = new GameLoop({
        update: () => updateCalls++,
        render: () => {},
      });

      loop.start();
      expect(rafCallback).toBeDefined();

      // Trigger frame
      if (rafCallback) {
        (rafCallback as Function)(performance.now() + 20);
      }

      loop.stop();
      expect(cancelledId).toBe(42);
    } finally {
      (globalThis as any).window = originalWindow;
      (globalThis as any).requestAnimationFrame = originalRAF;
      (globalThis as any).cancelAnimationFrame = originalCAF;
    }
  });

  it('computes fractional alpha interpolation during manual steps', () => {
    let lastAlpha = 0;
    const loop = new GameLoop(
      {
        update: () => {},
        render: (alpha) => {
          lastAlpha = alpha;
        },
      },
      20, // 20ms fixed step
      200,
    );

    // Step by 10ms (half a tick)
    loop.stepManual(10);
    expect(lastAlpha).toBeCloseTo(0.5);

    // Step by 20ms (full tick) -> remaining accumulator is 10ms -> alpha is 0.5
    loop.stepManual(20);
    expect(lastAlpha).toBeCloseTo(0.5);
  });
});
