/**
 * Input Abstraction Types.
 * Requirement Citations:
 * - R-PONG-INPUT-4: Decoupled input subsystem supporting keyboard, touch, and automated AI actions
 * - C-PONG-GOV-9: Safe input action contracts conforming to governance
 */

export type InputAction = 'MOVE_UP' | 'MOVE_DOWN' | 'SERVE' | 'PAUSE' | 'RESET';

export interface KeyBindings {
  readonly moveUp: readonly string[];
  readonly moveDown: readonly string[];
  readonly serve: readonly string[];
  readonly pause: readonly string[];
  readonly reset: readonly string[];
}

export interface InputDriver {
  poll(): {
    player1Direction: -1 | 0 | 1;
    player2Direction: -1 | 0 | 1;
    actions: readonly InputAction[];
  };
  destroy(): void;
}
