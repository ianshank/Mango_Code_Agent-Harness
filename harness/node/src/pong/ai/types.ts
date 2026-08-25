/**
 * AI Opponent Subsystem Types.
 * Requirement Citations:
 * - R-PONG-AI-5: Multi-tier predictive AI algorithms and difficulty configurations
 * - C-PONG-GOV-9: Deterministic behavior guarantees for AI strategies
 */

import type { GameStateSnapshot } from '../core/types.js';

export type AIDifficulty = 'easy' | 'medium' | 'hard' | 'expert';

export interface AIStrategyConfig {
  readonly difficulty: AIDifficulty;
  readonly reactionDelayTicks: number;
  readonly predictionAccuracy: number;
  readonly jitterAmount: number;
}

export interface AIController {
  update(snapshot: Readonly<GameStateSnapshot>): -1 | 0 | 1;
  setDifficulty(difficulty: AIDifficulty): void;
  reset(): void;
}
