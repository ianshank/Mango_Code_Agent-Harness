/**
 * Engine Integration Tests.
 * Requirement Citations:
 * - R-PONG-CORE-2: Physical simulation step execution
 * - R-PONG-STATE-3: Multi-phase state engine coordination
 * - R-PONG-LOOP-8: Accumulator loop integration
 * - C-PONG-GOV-9: Robust multi-module integration
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { NullRenderer } from '../../../src/pong/render/null-renderer.js';
import { NullAudioDriver } from '../../../src/pong/audio/null-audio-driver.js';
import { AudioManager } from '../../../src/pong/audio/audio-manager.js';
import { GameLoop } from '../../../src/pong/loop/game-loop.js';

describe('Engine & Loop Integration (R-PONG-CORE-2, R-PONG-STATE-3, R-PONG-LOOP-8)', () => {
  it('integrates GameEngine with GameLoop, NullRenderer, and AudioManager over simulated time', () => {
    const audioDriver = new NullAudioDriver();
    const audioManager = new AudioManager(
      { audio: { enabled: true, masterVolume: 1.0 } } as any,
      audioDriver,
    );
    const renderer = new NullRenderer();

    const engine = new GameEngine({
      serveDelayMs: 50,
      maxScore: 3,
    });

    engine.subscribe({
      onSound: (event) => audioManager.playSound(event),
    });

    engine.start();

    const loop = new GameLoop({
      update: (dt) => {
        engine.tick(dt);
      },
      render: (alpha) => {
        renderer.render(engine.getSnapshot(), alpha);
      },
    });

    // Simulate 2 seconds of gameplay manually (120 frames at 16.6ms)
    for (let i = 0; i < 120; i++) {
      loop.stepManual(1000 / 60);
    }

    expect(renderer.frameCount).toBe(120);
    expect(renderer.lastSnapshot).toBeDefined();
    expect(engine.getSnapshot().tick).toBeGreaterThanOrEqual(100);
  });
});
