/**
 * Headless Null Audio Driver for CLI and automated testing.
 * Requirement Citations:
 * - R-PONG-AUDIO-6: Headless audio mock driver for deterministic test environments
 * - C-PONG-GOV-9: Safe test sink
 */

import type { AudioDriver } from './types.js';
import type { SoundEventType } from '../core/types.js';

export class NullAudioDriver implements AudioDriver {
  public readonly playedSounds: SoundEventType[] = [];
  public volume = 1.0;
  public muted = false;

  playSound(type: SoundEventType): void {
    if (!this.muted) {
      this.playedSounds.push(type);
    }
  }

  setVolume(volume: number): void {
    this.volume = volume;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  clearHistory(): void {
    this.playedSounds.length = 0;
  }

  destroy(): void {
    this.playedSounds.length = 0;
  }
}
