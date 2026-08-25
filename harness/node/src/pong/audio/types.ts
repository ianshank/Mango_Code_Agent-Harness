/**
 * Audio Subsystem Types and Driver Interfaces.
 * Requirement Citations:
 * - R-PONG-AUDIO-6: Procedural sound synthesis abstraction for web and headless environments
 * - C-PONG-GOV-9: Safe fallback and zero hardware dependence
 */

import type { SoundEventType } from '../core/types.js';

export interface AudioDriver {
  playSound(type: SoundEventType): void;
  setVolume(volume: number): void;
  setMuted(muted: boolean): void;
  destroy(): void;
}
