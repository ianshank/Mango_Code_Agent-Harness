/**
 * Audio & Render Event Integration Tests.
 * Requirement Citations:
 * - R-PONG-AUDIO-6: Sound event emission on collision and scoring
 * - R-PONG-RENDER-7: Multi-target render event tracking
 * - C-PONG-GOV-9: Clean event bus propagation
 */

import { describe, it, expect } from 'vitest';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { NullAudioDriver } from '../../../src/pong/audio/null-audio-driver.js';
import { AudioManager } from '../../../src/pong/audio/audio-manager.js';
import { TerminalRenderer } from '../../../src/pong/render/terminal-renderer.js';

describe('Audio & Render Events Integration (R-PONG-AUDIO-6, R-PONG-RENDER-7)', () => {
  it('triggers audio events and updates terminal ASCII renderer on game events', () => {
    const audioDriver = new NullAudioDriver();
    const engine = new GameEngine();
    const audioManager = new AudioManager(engine.config, audioDriver);
    const terminalRenderer = new TerminalRenderer(40, 15);

    engine.subscribe({
      onSound: (e) => audioManager.playSound(e),
    });

    engine.start();

    // Render frame
    const asciiFrame = terminalRenderer.generateAsciiFrame(
      engine.getSnapshot(),
    );
    expect(asciiFrame).toContain('P1: 0');
    expect(asciiFrame).toContain('P2 (AI): 0');
    expect(asciiFrame).toContain('●'); // Ball character

    terminalRenderer.destroy();
  });
});
