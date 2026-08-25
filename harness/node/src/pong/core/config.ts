/**
 * Dynamic Game Configuration Builder and Presets.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Elimination of hardcoded constants; dynamic injection of game configurations
 * - C-PONG-GOV-9: Safe fallback and validation of all runtime properties
 */

import type { GameConfig } from './types.js';

/**
 * Default base configuration settings.
 */
export const DEFAULT_CONFIG: GameConfig = Object.freeze({
  width: 800,
  height: 500,
  targetFps: 60,
  fixedTimestepMs: 1000 / 60, // ~16.666ms
  maxScore: 11,
  serveDelayMs: 1000,
  ball: Object.freeze({
    radius: 7,
    baseSpeed: 380,
    speedMultiplier: 1.05,
    maxSpeed: 850,
    maxBounceAngleRad: (Math.PI / 180) * 60, // 60 degrees
    spinFriction: 0.25,
  }),
  paddle: Object.freeze({
    width: 14,
    height: 80,
    speed: 420,
    wallOffset: 25,
  }),
  ai: Object.freeze({
    enabled: true,
    difficulty: 'medium' as const,
    reactionDelayTicks: 4,
    predictionAccuracy: 0.85,
    jitterAmount: 12,
  }),
  audio: Object.freeze({
    enabled: true,
    masterVolume: 0.6,
    frequencies: Object.freeze({
      paddleHit: 220,
      wallBounce: 440,
      score: 880,
      win: 1200,
    }),
  }),
  theme: Object.freeze({
    background: '#0a0e17',
    foreground: '#00ffcc',
    accent: '#ff007f',
    netColor: 'rgba(0, 255, 204, 0.25)',
    particleCount: 20,
  }),
});

/**
 * Predefined profile configurations.
 */
export const PRESETS: Record<string, Partial<GameConfig>> = Object.freeze({
  classic: {
    ball: {
      radius: 6,
      baseSpeed: 300,
      speedMultiplier: 1.02,
      maxSpeed: 600,
      maxBounceAngleRad: (Math.PI / 180) * 45,
      spinFriction: 0.1,
    },
    paddle: {
      width: 12,
      height: 70,
      speed: 350,
      wallOffset: 20,
    },
    maxScore: 11,
  },
  fast: {
    ball: {
      radius: 8,
      baseSpeed: 500,
      speedMultiplier: 1.08,
      maxSpeed: 1100,
      maxBounceAngleRad: (Math.PI / 180) * 65,
      spinFriction: 0.35,
    },
    paddle: {
      width: 14,
      height: 90,
      speed: 550,
      wallOffset: 25,
    },
    maxScore: 7,
  },
  arcade: {
    ball: {
      radius: 10,
      baseSpeed: 420,
      speedMultiplier: 1.06,
      maxSpeed: 950,
      maxBounceAngleRad: (Math.PI / 180) * 70,
      spinFriction: 0.4,
    },
    theme: {
      background: '#120024',
      foreground: '#ff00aa',
      accent: '#00e5ff',
      netColor: 'rgba(255, 0, 170, 0.3)',
      particleCount: 35,
    },
  },
  tournament: {
    maxScore: 21,
    serveDelayMs: 1200,
    ai: {
      enabled: true,
      difficulty: 'expert',
      reactionDelayTicks: 1,
      predictionAccuracy: 0.98,
      jitterAmount: 2,
    },
  },
});

/**
 * Validates and deep merges game configurations.
 */
export function createGameConfig(
  preset = 'classic',
  overrides?: Partial<GameConfig>,
): GameConfig {
  const selectedPreset = PRESETS[preset] ?? {};

  // Deep clone and merge
  const merged: GameConfig = {
    width: Math.max(
      200,
      overrides?.width ?? selectedPreset.width ?? DEFAULT_CONFIG.width,
    ),
    height: Math.max(
      150,
      overrides?.height ?? selectedPreset.height ?? DEFAULT_CONFIG.height,
    ),
    targetFps: Math.max(
      15,
      Math.min(
        240,
        overrides?.targetFps ??
          selectedPreset.targetFps ??
          DEFAULT_CONFIG.targetFps,
      ),
    ),
    fixedTimestepMs: Math.max(
      1,
      overrides?.fixedTimestepMs ??
        selectedPreset.fixedTimestepMs ??
        DEFAULT_CONFIG.fixedTimestepMs,
    ),
    maxScore: Math.max(
      1,
      overrides?.maxScore ?? selectedPreset.maxScore ?? DEFAULT_CONFIG.maxScore,
    ),
    serveDelayMs: Math.max(
      0,
      overrides?.serveDelayMs ??
        selectedPreset.serveDelayMs ??
        DEFAULT_CONFIG.serveDelayMs,
    ),
    ball: {
      radius: Math.max(
        1,
        overrides?.ball?.radius ??
          selectedPreset.ball?.radius ??
          DEFAULT_CONFIG.ball.radius,
      ),
      baseSpeed: Math.max(
        50,
        overrides?.ball?.baseSpeed ??
          selectedPreset.ball?.baseSpeed ??
          DEFAULT_CONFIG.ball.baseSpeed,
      ),
      speedMultiplier: Math.max(
        1.0,
        overrides?.ball?.speedMultiplier ??
          selectedPreset.ball?.speedMultiplier ??
          DEFAULT_CONFIG.ball.speedMultiplier,
      ),
      maxSpeed: Math.max(
        100,
        overrides?.ball?.maxSpeed ??
          selectedPreset.ball?.maxSpeed ??
          DEFAULT_CONFIG.ball.maxSpeed,
      ),
      maxBounceAngleRad: Math.max(
        0.1,
        Math.min(
          Math.PI / 2 - 0.05,
          overrides?.ball?.maxBounceAngleRad ??
            selectedPreset.ball?.maxBounceAngleRad ??
            DEFAULT_CONFIG.ball.maxBounceAngleRad,
        ),
      ),
      spinFriction: Math.max(
        0,
        Math.min(
          1.0,
          overrides?.ball?.spinFriction ??
            selectedPreset.ball?.spinFriction ??
            DEFAULT_CONFIG.ball.spinFriction,
        ),
      ),
    },
    paddle: {
      width: Math.max(
        2,
        overrides?.paddle?.width ??
          selectedPreset.paddle?.width ??
          DEFAULT_CONFIG.paddle.width,
      ),
      height: Math.max(
        10,
        overrides?.paddle?.height ??
          selectedPreset.paddle?.height ??
          DEFAULT_CONFIG.paddle.height,
      ),
      speed: Math.max(
        50,
        overrides?.paddle?.speed ??
          selectedPreset.paddle?.speed ??
          DEFAULT_CONFIG.paddle.speed,
      ),
      wallOffset: Math.max(
        0,
        overrides?.paddle?.wallOffset ??
          selectedPreset.paddle?.wallOffset ??
          DEFAULT_CONFIG.paddle.wallOffset,
      ),
    },
    ai: {
      enabled:
        overrides?.ai?.enabled ??
        selectedPreset.ai?.enabled ??
        DEFAULT_CONFIG.ai.enabled,
      difficulty:
        overrides?.ai?.difficulty ??
        selectedPreset.ai?.difficulty ??
        DEFAULT_CONFIG.ai.difficulty,
      reactionDelayTicks: Math.max(
        0,
        overrides?.ai?.reactionDelayTicks ??
          selectedPreset.ai?.reactionDelayTicks ??
          DEFAULT_CONFIG.ai.reactionDelayTicks,
      ),
      predictionAccuracy: Math.max(
        0.1,
        Math.min(
          1.0,
          overrides?.ai?.predictionAccuracy ??
            selectedPreset.ai?.predictionAccuracy ??
            DEFAULT_CONFIG.ai.predictionAccuracy,
        ),
      ),
      jitterAmount: Math.max(
        0,
        overrides?.ai?.jitterAmount ??
          selectedPreset.ai?.jitterAmount ??
          DEFAULT_CONFIG.ai.jitterAmount,
      ),
    },
    audio: {
      enabled:
        overrides?.audio?.enabled ??
        selectedPreset.audio?.enabled ??
        DEFAULT_CONFIG.audio.enabled,
      masterVolume: Math.max(
        0,
        Math.min(
          1.0,
          overrides?.audio?.masterVolume ??
            selectedPreset.audio?.masterVolume ??
            DEFAULT_CONFIG.audio.masterVolume,
        ),
      ),
      frequencies: {
        paddleHit:
          overrides?.audio?.frequencies?.paddleHit ??
          selectedPreset.audio?.frequencies?.paddleHit ??
          DEFAULT_CONFIG.audio.frequencies.paddleHit,
        wallBounce:
          overrides?.audio?.frequencies?.wallBounce ??
          selectedPreset.audio?.frequencies?.wallBounce ??
          DEFAULT_CONFIG.audio.frequencies.wallBounce,
        score:
          overrides?.audio?.frequencies?.score ??
          selectedPreset.audio?.frequencies?.score ??
          DEFAULT_CONFIG.audio.frequencies.score,
        win:
          overrides?.audio?.frequencies?.win ??
          selectedPreset.audio?.frequencies?.win ??
          DEFAULT_CONFIG.audio.frequencies.win,
      },
    },
    theme: {
      background:
        overrides?.theme?.background ??
        selectedPreset.theme?.background ??
        DEFAULT_CONFIG.theme.background,
      foreground:
        overrides?.theme?.foreground ??
        selectedPreset.theme?.foreground ??
        DEFAULT_CONFIG.theme.foreground,
      accent:
        overrides?.theme?.accent ??
        selectedPreset.theme?.accent ??
        DEFAULT_CONFIG.theme.accent,
      netColor:
        overrides?.theme?.netColor ??
        selectedPreset.theme?.netColor ??
        DEFAULT_CONFIG.theme.netColor,
      particleCount: Math.max(
        0,
        overrides?.theme?.particleCount ??
          selectedPreset.theme?.particleCount ??
          DEFAULT_CONFIG.theme.particleCount,
      ),
    },
  };

  return Object.freeze(merged);
}
