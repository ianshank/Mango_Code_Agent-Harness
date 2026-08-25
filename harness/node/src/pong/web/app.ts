/**
 * Browser Game Application Controller.
 * Requirement Citations:
 * - R-PONG-RENDER-7: HTML5 Canvas rendering lifecycle
 * - R-PONG-AUDIO-6: Web audio integration
 * - R-PONG-INPUT-4: Keyboard driver binding
 * - C-PONG-GOV-9: Safe DOM lifecycle management
 */

import { GameEngine } from '../core/game-engine.js';
import { CanvasRenderer } from '../render/canvas-renderer.js';
import { KeyboardDriver } from '../input/keyboard-driver.js';
import { InputManager } from '../input/input-manager.js';
import { AudioManager } from '../audio/audio-manager.js';
import { WebAudioDriver } from '../audio/web-audio-driver.js';
import { AIOpponent } from '../ai/ai-opponent.js';
import { GameLoop } from '../loop/game-loop.js';
import type { AIDifficulty } from '../ai/types.js';

export function initializeWebPong(): void {
  const doc = (globalThis as any).document;
  if (!doc) return;

  const canvas = doc.getElementById('pongCanvas');
  if (!canvas) return;

  const startBtn = doc.getElementById('startBtn');
  const pauseBtn = doc.getElementById('pauseBtn');
  const resetBtn = doc.getElementById('resetBtn');
  const diffSelect = doc.getElementById('diffSelect');
  const presetSelect = doc.getElementById('presetSelect');
  const soundBtn = doc.getElementById('soundBtn');

  const renderer = new CanvasRenderer(canvas);
  renderer.resize(800, 500);

  let engine = new GameEngine();
  const inputManager = new InputManager();
  const keyboardDriver = new KeyboardDriver(
    undefined,
    (globalThis as any).window,
  );
  inputManager.setDriver(keyboardDriver);

  const audioDriver = new WebAudioDriver(engine.config);
  const audioManager = new AudioManager(engine.config, audioDriver);
  let aiOpponent = new AIOpponent('player2', 'medium');
  let soundMuted = false;

  engine.subscribe({
    onSound: (event) => audioManager.playSound(event),
  });

  inputManager.onAction((action) => {
    if (action === 'PAUSE') {
      const isPaused = engine.togglePause();
      if (pauseBtn)
        pauseBtn.textContent = isPaused ? 'Resume (P)' : 'Pause (P)';
    } else if (action === 'SERVE' || action === 'RESET') {
      if (
        engine.getSnapshot().phase === 'MENU' ||
        engine.getSnapshot().phase === 'GAME_OVER'
      ) {
        engine.start();
        if (startBtn) startBtn.textContent = 'Restart Match';
      }
    }
  });

  startBtn?.addEventListener('click', () => {
    engine.start();
    if (startBtn) startBtn.textContent = 'Restart Match';
  });

  pauseBtn?.addEventListener('click', () => {
    const isPaused = engine.togglePause();
    if (pauseBtn) pauseBtn.textContent = isPaused ? 'Resume (P)' : 'Pause (P)';
  });

  resetBtn?.addEventListener('click', () => {
    engine.reset();
    if (startBtn) startBtn.textContent = 'Start Game (Space)';
    if (pauseBtn) pauseBtn.textContent = 'Pause (P)';
  });

  diffSelect?.addEventListener('change', (e: any) => {
    const val = e.target.value as AIDifficulty;
    aiOpponent.setDifficulty(val);
  });

  presetSelect?.addEventListener('change', (e: any) => {
    const preset = e.target.value;
    engine = new GameEngine({ preset } as any);
    engine.subscribe({
      onSound: (event) => audioManager.playSound(event),
    });
    engine.reset();
  });

  soundBtn?.addEventListener('click', () => {
    soundMuted = !soundMuted;
    audioManager.setMuted(soundMuted);
    if (soundBtn)
      soundBtn.textContent = soundMuted ? '🔇 Sound: OFF' : '🔊 Sound: ON';
  });

  const loop = new GameLoop({
    update: (dt) => {
      const input = inputManager.poll();
      engine.setPlayerDirection('player1', input.player1Direction, dt);

      const snapshot = engine.getSnapshot();
      if (engine.config.ai.enabled) {
        const aiDir = aiOpponent.update(snapshot);
        engine.setPlayerDirection('player2', aiDir, dt);
      } else {
        engine.setPlayerDirection('player2', input.player2Direction, dt);
      }

      engine.tick(dt);
    },
    render: (alpha) => {
      renderer.render(engine.getSnapshot(), alpha);
    },
  });

  loop.start();
}

if (typeof (globalThis as any).window !== 'undefined') {
  (globalThis as any).window.addEventListener?.(
    'DOMContentLoaded',
    initializeWebPong,
  );
}
