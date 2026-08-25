/**
 * Rendering Subsystem Interfaces and Types.
 * Requirement Citations:
 * - R-PONG-RENDER-7: Multi-target rendering abstraction (Canvas 2D, Terminal ANSI, Headless)
 * - C-PONG-GOV-9: Safe presentation layer isolation
 */

import type { GameStateSnapshot } from '../core/types.js';

export interface Renderer {
  render(
    snapshot: Readonly<GameStateSnapshot>,
    interpolationAlpha?: number,
  ): void;
  resize?(width: number, height: number): void;
  destroy(): void;
}
