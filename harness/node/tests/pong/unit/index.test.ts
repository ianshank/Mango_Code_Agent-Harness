/**
 * Unified Public Module Re-export Unit Tests.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Public API exports for configuration
 * - R-PONG-CORE-2: Public API exports for physics
 * - R-PONG-STATE-3: Public API exports for state machine
 * - R-PONG-INPUT-4: Public API exports for input subsystem
 * - R-PONG-AI-5: Public API exports for AI controller
 * - R-PONG-AUDIO-6: Public API exports for audio subsystem
 * - R-PONG-RENDER-7: Public API exports for rendering
 * - R-PONG-LOOP-8: Public API exports for game loop
 * - C-PONG-GOV-9: High-coverage validation
 */

import { describe, it, expect } from 'vitest';
import * as Pong from '../../../src/pong/index.js';

describe('Public Barrel Exports (C-PONG-GOV-9)', () => {
  it('exports all core modules and classes', () => {
    expect(Pong.GameEngine).toBeDefined();
    expect(Pong.Vector).toBeDefined();
    expect(Pong.Physics).toBeDefined();
    expect(Pong.StateMachine).toBeDefined();
    expect(Pong.createGameConfig).toBeDefined();
    expect(Pong.InputManager).toBeDefined();
    expect(Pong.KeyboardDriver).toBeDefined();
    expect(Pong.AIOpponent).toBeDefined();
    expect(Pong.AudioManager).toBeDefined();
    expect(Pong.WebAudioDriver).toBeDefined();
    expect(Pong.NullAudioDriver).toBeDefined();
    expect(Pong.CanvasRenderer).toBeDefined();
    expect(Pong.TerminalRenderer).toBeDefined();
    expect(Pong.NullRenderer).toBeDefined();
    expect(Pong.GameLoop).toBeDefined();
  });
});
