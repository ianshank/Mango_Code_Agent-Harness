/**
 * Headless Null Renderer for testing and benchmarking.
 * Requirement Citations:
 * - R-PONG-RENDER-7: Headless mock renderer for automated testing
 * - C-PONG-GOV-9: Safe test presentation sink
 */

import type { Renderer } from './types.js';
import type { GameStateSnapshot } from '../core/types.js';

export class NullRenderer implements Renderer {
  public frameCount = 0;
  public lastSnapshot: GameStateSnapshot | null = null;
  public lastAlpha = 1.0;

  render(
    snapshot: Readonly<GameStateSnapshot>,
    interpolationAlpha = 1.0,
  ): void {
    this.frameCount++;
    this.lastSnapshot = snapshot;
    this.lastAlpha = interpolationAlpha;
  }

  resize(_width: number, _height: number): void {
    // No-op
  }

  destroy(): void {
    this.frameCount = 0;
    this.lastSnapshot = null;
  }
}
