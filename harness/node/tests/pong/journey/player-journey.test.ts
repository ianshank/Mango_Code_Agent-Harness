/**
 * Player User Journey Tests.
 * Requirement Citations:
 * - R-PONG-INPUT-4: Player input interaction during journey
 * - R-PONG-STATE-3: Flow through Menu, Gameplay, Scoring, Game Over, and Rematch
 * - C-PONG-GOV-9: Complete player journey verification
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { InputManager } from '../../../src/pong/input/input-manager.js';
import { KeyboardDriver } from '../../../src/pong/input/keyboard-driver.js';
import { AIOpponent } from '../../../src/pong/ai/ai-opponent.js';
import { Vector } from '../../../src/pong/core/vector.js';

describe('Player User Journey (R-PONG-INPUT-4, R-PONG-STATE-3, C-PONG-GOV-9)', () => {
  it('navigates complete journey: Menu -> Start -> Playing -> Scoring -> Game Over -> Rematch', () => {
    const engine = new GameEngine({ maxScore: 1, serveDelayMs: 10 });
    const inputManager = new InputManager();
    const keyboardDriver = new KeyboardDriver();
    inputManager.setDriver(keyboardDriver);
    const ai = new AIOpponent('player2', 'medium');

    // Step 1: In Menu
    expect(engine.getSnapshot().phase).toBe('MENU');

    // Step 2: Player presses Serve / Space to start
    keyboardDriver.pressKey('Space');
    inputManager.onAction((action) => {
      if (action === 'SERVE' && engine.getSnapshot().phase === 'MENU') {
        engine.start();
      }
    });
    inputManager.poll();
    keyboardDriver.releaseKey('Space');

    expect(engine.getSnapshot().phase).toBe('SERVING');

    // Step 3: Advance to PLAYING
    engine.tick(0.05);
    expect(engine.getSnapshot().phase).toBe('PLAYING');

    // Step 4: Player moves paddle Up
    keyboardDriver.pressKey('KeyW');
    const input = inputManager.poll();
    engine.setPlayerDirection('player1', input.player1Direction, 0.016);
    const aiDir = ai.update(engine.getSnapshot());
    engine.setPlayerDirection('player2', aiDir, 0.016);
    engine.tick(0.016);

    // Step 5: Player scores point -> Victory Screen
    (engine as any).ball = {
      ...(engine as any).ball,
      position: Vector.create(engine.config.width + 20, 250),
    };
    engine.tick(0.016);

    expect(engine.getSnapshot().phase).toBe('GAME_OVER');
    expect(engine.getSnapshot().score.winner).toBe('player1');

    // Step 6: Rematch Trigger (Press R)
    keyboardDriver.pressKey('KeyR');
    inputManager.onAction((action) => {
      if (action === 'RESET') {
        engine.reset();
      }
    });
    inputManager.poll();
    expect(engine.getSnapshot().phase).toBe('MENU');

    inputManager.destroy();
  });
});
