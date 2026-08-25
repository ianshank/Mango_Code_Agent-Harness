/**
 * Security & Sanitization Unit & Attack Vector Tests.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Parameter tampering defense and validation boundaries
 * - R-PONG-CORE-2: Protection against NaN and Infinity vector corruption
 * - C-PONG-GOV-9: Safe fail-closed operation and state immutability
 */

import { describe, it, expect } from 'vitest';
import { Vector } from '../../../src/pong/core/vector.js';
import { createGameConfig } from '../../../src/pong/core/config.js';
import { GameEngine } from '../../../src/pong/core/game-engine.js';

describe('Security & Parameter Tampering Defense (R-PONG-CONFIG-1, R-PONG-CORE-2, C-PONG-GOV-9)', () => {
  it('prevents NaN and Infinity vector injection from corrupting state', () => {
    const corrupted = Vector.create(NaN, Infinity);
    expect(corrupted.x).toBe(0);
    expect(corrupted.y).toBe(0);

    const scaled = Vector.scale(Vector.create(10, 20), Infinity);
    expect(scaled.x).toBe(0);
    expect(scaled.y).toBe(0);

    const normalized = Vector.normalize(Vector.create(0, 0));
    expect(Number.isFinite(normalized.x)).toBe(true);
    expect(Number.isFinite(normalized.y)).toBe(true);
  });

  it('safely clamps maliciously negative or unbounded game configs', () => {
    const maliciousConfig = createGameConfig('classic', {
      width: -999999,
      height: 0,
      maxScore: -5,
      ball: {
        radius: -10,
        baseSpeed: -500,
        speedMultiplier: -2,
        maxSpeed: 0,
        maxBounceAngleRad: 999,
        spinFriction: -5,
      },
    });

    expect(maliciousConfig.width).toBeGreaterThanOrEqual(200);
    expect(maliciousConfig.height).toBeGreaterThanOrEqual(150);
    expect(maliciousConfig.maxScore).toBeGreaterThanOrEqual(1);
    expect(maliciousConfig.ball.radius).toBeGreaterThanOrEqual(1);
    expect(maliciousConfig.ball.baseSpeed).toBeGreaterThanOrEqual(50);
    expect(maliciousConfig.ball.speedMultiplier).toBeGreaterThanOrEqual(1.0);
    expect(maliciousConfig.ball.spinFriction).toBeGreaterThanOrEqual(0);
  });

  it('guarantees state immutability preventing external tampering of snapshots', () => {
    const engine = new GameEngine();
    engine.start();

    const snapshot = engine.getSnapshot();
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.ball)).toBe(true);
    expect(Object.isFrozen(snapshot.player1)).toBe(true);
    expect(Object.isFrozen(snapshot.score)).toBe(true);
  });
});
