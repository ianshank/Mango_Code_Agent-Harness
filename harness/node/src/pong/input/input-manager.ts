/**
 * Input Manager Subsystem.
 * Requirement Citations:
 * - R-PONG-INPUT-4: Decoupled input abstraction and action dispatcher
 * - C-PONG-GOV-9: Safe input action validation
 */

import type { InputAction, InputDriver } from './types.js';

export class InputManager {
  private driver: InputDriver | null = null;
  private readonly actionListeners = new Set<(action: InputAction) => void>();
  private readonly manualP1Direction: -1 | 0 | 1 = 0;
  private readonly manualP2Direction: -1 | 0 | 1 = 0;

  /**
   * Attaches an active hardware or virtual input driver.
   */
  setDriver(driver: InputDriver): void {
    if (this.driver) {
      this.driver.destroy();
    }
    this.driver = driver;
  }

  /**
   * Subscribes to discrete trigger actions (e.g. Pause, Serve, Reset).
   */
  onAction(callback: (action: InputAction) => void): () => void {
    this.actionListeners.add(callback);
    return () => this.actionListeners.delete(callback);
  }

  /**
   * Triggers a discrete action directly.
   */
  dispatchAction(action: InputAction): void {
    for (const listener of this.actionListeners) {
      listener(action);
    }
  }

  /**
   * Polls continuous movement directions and processes actions.
   */
  poll(): {
    player1Direction: -1 | 0 | 1;
    player2Direction: -1 | 0 | 1;
  } {
    if (!this.driver) {
      return {
        player1Direction: this.manualP1Direction,
        player2Direction: this.manualP2Direction,
      };
    }

    const state = this.driver.poll();

    // Dispatch any buffered discrete actions
    for (const action of state.actions) {
      this.dispatchAction(action);
    }

    return {
      player1Direction: state.player1Direction,
      player2Direction: state.player2Direction,
    };
  }

  /**
   * Cleans up resources.
   */
  destroy(): void {
    if (this.driver) {
      this.driver.destroy();
      this.driver = null;
    }
    this.actionListeners.clear();
  }
}
