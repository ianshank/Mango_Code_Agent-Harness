/**
 * Audio Manager Subsystem.
 * Requirement Citations:
 * - R-PONG-AUDIO-6: Sound event management, volume control, and driver abstraction
 * - C-PONG-GOV-9: Safe sound emission handling
 */

import type { SoundEventType, GameConfig } from '../core/types.js';
import type { AudioDriver } from './types.js';

export class AudioManager {
  private driver: AudioDriver | null = null;
  private volume: number;
  private muted = false;

  constructor(config: GameConfig, driver?: AudioDriver) {
    this.volume = config.audio.masterVolume;
    this.muted = !config.audio.enabled;
    if (driver) {
      this.driver = driver;
    }
  }

  setDriver(driver: AudioDriver): void {
    if (this.driver) {
      this.driver.destroy();
    }
    this.driver = driver;
    this.driver.setVolume(this.volume);
    this.driver.setMuted(this.muted);
  }

  playSound(type: SoundEventType): void {
    if (this.muted || !this.driver) {
      return;
    }
    this.driver.playSound(type);
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1.0, volume));
    this.driver?.setVolume(this.volume);
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.driver?.setMuted(this.muted);
  }

  destroy(): void {
    this.driver?.destroy();
    this.driver = null;
  }
}
