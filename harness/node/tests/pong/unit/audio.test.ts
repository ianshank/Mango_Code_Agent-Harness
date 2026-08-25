/**
 * Audio System & Driver Unit Tests.
 * Requirement Citations:
 * - R-PONG-AUDIO-6: Procedural audio synthesis, volume/mute control, and driver abstraction
 * - C-PONG-GOV-9: High-coverage safe audio testing
 */

import { describe, it, expect } from 'vitest';
import { AudioManager } from '../../../src/pong/audio/audio-manager.js';
import { NullAudioDriver } from '../../../src/pong/audio/null-audio-driver.js';
import { WebAudioDriver } from '../../../src/pong/audio/web-audio-driver.js';
import { createGameConfig } from '../../../src/pong/core/config.js';

describe('Audio Subsystem (R-PONG-AUDIO-6)', () => {
  const config = createGameConfig();

  it('manages sound events, volume, and mute states with NullAudioDriver', () => {
    const driver = new NullAudioDriver();
    const manager = new AudioManager(config, driver);

    manager.playSound('PADDLE_HIT');
    manager.playSound('WALL_BOUNCE');
    expect(driver.playedSounds).toEqual(['PADDLE_HIT', 'WALL_BOUNCE']);

    manager.setMuted(true);
    manager.playSound('SCORE_POINT');
    expect(driver.playedSounds.length).toBe(2);

    driver.setMuted(true);
    driver.playSound('SCORE_POINT');
    expect(driver.playedSounds.length).toBe(2);

    driver.setMuted(false);
    driver.setVolume(0.5);
    expect(driver.volume).toBe(0.5);

    manager.setMuted(false);
    manager.setVolume(0.8);
    expect(driver.volume).toBe(0.8);

    manager.playSound('MATCH_WIN');
    expect(driver.playedSounds.length).toBe(3);

    driver.clearHistory();
    expect(driver.playedSounds.length).toBe(0);

    driver.destroy();
    manager.destroy();
  });

  it('swaps audio drivers and handles null drivers safely', () => {
    const manager = new AudioManager(config);
    manager.playSound('PADDLE_HIT'); // No crash with null driver

    const driver1 = new NullAudioDriver();
    manager.setDriver(driver1);
    manager.playSound('WALL_BOUNCE');
    expect(driver1.playedSounds).toContain('WALL_BOUNCE');

    const driver2 = new NullAudioDriver();
    manager.setDriver(driver2);
    manager.playSound('SCORE_POINT');
    expect(driver2.playedSounds).toContain('SCORE_POINT');

    manager.destroy();
  });

  it('exercises WebAudioDriver fallback and safe mock context in Node/browser environments', () => {
    const webDriver = new WebAudioDriver(config);
    webDriver.setVolume(0.7);
    webDriver.setMuted(false);

    // Call all sound types (gracefully falls back when window/AudioContext is not present)
    webDriver.playSound('PADDLE_HIT');
    webDriver.playSound('WALL_BOUNCE');
    webDriver.playSound('SCORE_POINT');
    webDriver.playSound('MATCH_WIN');

    webDriver.setMuted(true);
    webDriver.playSound('PADDLE_HIT');

    webDriver.destroy();
  });

  it('exercises WebAudioDriver with a mocked AudioContext', () => {
    let resumeCalled = false;
    const mockOsc = {
      connect: () => {},
      type: 'square',
      frequency: { setValueAtTime: () => {} },
      start: () => {},
      stop: () => {},
    };
    const mockGain = {
      connect: () => {},
      gain: {
        setValueAtTime: () => {},
        exponentialRampToValueAtTime: () => {},
      },
    };
    const mockCtx = {
      currentTime: 100,
      state: 'suspended',
      destination: {},
      createOscillator: () => mockOsc,
      createGain: () => mockGain,
      resume: () => {
        resumeCalled = true;
        return Promise.reject(new Error('Mock resume error'));
      },
      close: () => Promise.resolve(),
    };

    const webDriver = new WebAudioDriver(config);
    (webDriver as any).audioCtx = mockCtx;

    webDriver.playSound('PADDLE_HIT');
    expect(resumeCalled).toBe(true);

    webDriver.playSound('WALL_BOUNCE');
    webDriver.playSound('SCORE_POINT');
    webDriver.playSound('MATCH_WIN');

    webDriver.destroy();
  });

  it('exercises WebAudioDriver with globalThis.window webkitAudioContext constructor', () => {
    const originalWindow = (globalThis as any).window;
    try {
      (globalThis as any).window = {
        webkitAudioContext: function () {
          return {
            currentTime: 100,
            state: 'running',
            destination: {},
            createOscillator: () => ({
              connect: () => {},
              type: 'sine',
              frequency: { setValueAtTime: () => {} },
              start: () => {},
              stop: () => {},
            }),
            createGain: () => ({
              connect: () => {},
              gain: {
                setValueAtTime: () => {},
                exponentialRampToValueAtTime: () => {},
              },
            }),
            close: () => Promise.resolve(),
          };
        },
      };

      const webDriver = new WebAudioDriver(config);
      webDriver.playSound('PADDLE_HIT');
      webDriver.destroy();
    } finally {
      (globalThis as any).window = originalWindow;
    }
  });
});
