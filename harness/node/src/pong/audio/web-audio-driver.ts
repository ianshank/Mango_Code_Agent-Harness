/**
 * Web Audio API Procedural Sound Synthesizer.
 * Requirement Citations:
 * - R-PONG-AUDIO-6: Procedural audio synthesis without external assets
 * - C-PONG-GOV-9: Safe audio context initialization and cleanup
 */

import type { AudioDriver } from './types.js';
import type { SoundEventType, GameConfig } from '../core/types.js';

export class WebAudioDriver implements AudioDriver {
  private audioCtx: any = null;
  private volume = 0.5;
  private muted = false;
  private readonly config: GameConfig;

  constructor(config: GameConfig) {
    this.config = config;
  }

  private ensureContext(): any {
    if (!this.audioCtx && typeof (globalThis as any).window !== 'undefined') {
      const gWindow = (globalThis as any).window;
      const AudioContextClass =
        gWindow.AudioContext || gWindow.webkitAudioContext;
      if (AudioContextClass) {
        this.audioCtx = new AudioContextClass();
      }
    }
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume?.().catch(() => {});
    }
    return this.audioCtx;
  }

  playSound(type: SoundEventType): void {
    if (this.muted) return;
    const ctx = this.ensureContext();
    if (!ctx) return;

    try {
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.connect(gain);
      gain.connect(ctx.destination);

      let freq = 440;
      let duration = 0.08;
      let waveType: any = 'square';

      switch (type) {
        case 'PADDLE_HIT':
          freq = this.config.audio.frequencies.paddleHit;
          duration = 0.06;
          waveType = 'square';
          break;
        case 'WALL_BOUNCE':
          freq = this.config.audio.frequencies.wallBounce;
          duration = 0.04;
          waveType = 'sine';
          break;
        case 'SCORE_POINT':
          freq = this.config.audio.frequencies.score;
          duration = 0.2;
          waveType = 'sawtooth';
          break;
        case 'MATCH_WIN':
          freq = this.config.audio.frequencies.win;
          duration = 0.4;
          waveType = 'triangle';
          break;
      }

      osc.type = waveType;
      osc.frequency.setValueAtTime(freq, now);

      gain.gain.setValueAtTime(this.volume * 0.3, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

      osc.start(now);
      osc.stop(now + duration);
    } catch {
      // Ignore audio synthesis errors on unsupported environments
    }
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1.0, volume));
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  destroy(): void {
    if (this.audioCtx) {
      this.audioCtx.close?.().catch(() => {});
      this.audioCtx = null;
    }
  }
}
