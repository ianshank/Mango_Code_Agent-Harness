/**
 * Configuration & Preset Unit Tests.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Dynamic configuration validation, profile presets, zero hardcoded values
 * - C-PONG-GOV-9: Safe configuration fallbacks
 */

import { describe, it, expect } from 'vitest';
import {
  createGameConfig,
  DEFAULT_CONFIG,
  PRESETS,
} from '../../../src/pong/core/config.js';

describe('Game Configuration & Presets (R-PONG-CONFIG-1)', () => {
  it('creates valid default configuration matching schema constraints', () => {
    const config = createGameConfig();
    expect(config.width).toBe(DEFAULT_CONFIG.width);
    expect(config.height).toBe(DEFAULT_CONFIG.height);
    expect(config.maxScore).toBe(DEFAULT_CONFIG.maxScore);
    expect(config.ball.baseSpeed).toBeGreaterThan(0);
    expect(config.paddle.height).toBeGreaterThan(0);
    expect(Object.isFrozen(config)).toBe(true);
  });

  it('loads predefined profile presets correctly', () => {
    const fastConfig = createGameConfig('fast');
    expect(fastConfig.ball.baseSpeed).toBe(PRESETS['fast']?.ball?.baseSpeed);
    expect(fastConfig.maxScore).toBe(PRESETS['fast']?.maxScore);

    const arcadeConfig = createGameConfig('arcade');
    expect(arcadeConfig.theme.foreground).toBe(
      PRESETS['arcade']?.theme?.foreground,
    );
  });

  it('merges deep overrides and clamps invalid/out-of-bound inputs safely', () => {
    const custom = createGameConfig('classic', {
      width: -50, // Clamped to min 200
      maxScore: 0, // Clamped to min 1
      ball: {
        radius: 15,
        baseSpeed: 10, // Clamped to min 50
        speedMultiplier: 0.5, // Clamped to min 1.0
        maxSpeed: 2000,
        maxBounceAngleRad: 1.2,
        spinFriction: 0.5,
      },
    });

    expect(custom.width).toBe(200);
    expect(custom.maxScore).toBe(1);
    expect(custom.ball.radius).toBe(15);
    expect(custom.ball.baseSpeed).toBe(50);
    expect(custom.ball.speedMultiplier).toBe(1.0);
  });
});
