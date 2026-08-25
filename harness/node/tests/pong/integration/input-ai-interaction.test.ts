/**
 * Input & AI Controller Integration Tests.
 * Requirement Citations:
 * - R-PONG-INPUT-4: Decoupled input polling with keyboard driver
 * - R-PONG-AI-5: Autonomous AI opponent coordination
 * - C-PONG-GOV-9: High reliability cross-subsystem orchestration
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { InputManager } from '../../../src/pong/input/input-manager.js';
import { KeyboardDriver } from '../../../src/pong/input/keyboard-driver.js';
import { AIOpponent } from '../../../src/pong/ai/ai-opponent.js';

describe('Input & AI Integration (R-PONG-INPUT-4, R-PONG-AI-5)', () => {
  it('updates player 1 via simulated keyboard input while AI controls player 2', () => {
    const engine = new GameEngine();
    const inputManager = new InputManager();
    const keyboardDriver = new KeyboardDriver();
    inputManager.setDriver(keyboardDriver);

    const ai = new AIOpponent('player2', 'medium');
    engine.start();

    // Simulate holding 'KeyW' (Move Up)
    keyboardDriver.pressKey('KeyW');

    const dt = 0.016;
    for (let i = 0; i < 20; i++) {
      const input = inputManager.poll();
      engine.setPlayerDirection('player1', input.player1Direction, dt);

      const aiDir = ai.update(engine.getSnapshot());
      engine.setPlayerDirection('player2', aiDir, dt);

      engine.tick(dt);
    }

    const snapshot = engine.getSnapshot();
    // Player 1 should have moved up towards 0
    expect(snapshot.player1.position.y).toBeLessThan(
      (engine.config.height - engine.config.paddle.height) / 2,
    );

    inputManager.destroy();
  });
});
