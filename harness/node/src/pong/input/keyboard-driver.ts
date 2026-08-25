/**
 * DOM Keyboard Input Driver.
 * Requirement Citations:
 * - R-PONG-INPUT-4: Keyboard action mapping and event management
 * - C-PONG-GOV-9: Safe cleanup and defensive input binding
 */

import type { InputDriver, InputAction, KeyBindings } from './types.js';

export const DEFAULT_KEYBINDINGS: KeyBindings = Object.freeze({
  moveUp: ['KeyW', 'ArrowUp'],
  moveDown: ['KeyS', 'ArrowDown'],
  serve: ['Space', 'Enter'],
  pause: ['KeyP', 'Escape'],
  reset: ['KeyR'],
});

export class KeyboardDriver implements InputDriver {
  private readonly pressedKeys = new Set<string>();
  private readonly queuedActions: InputAction[] = [];
  private readonly bindings: KeyBindings;
  private readonly targetElement: {
    addEventListener: Function;
    removeEventListener: Function;
  } | null;
  private readonly handleKeyDown: (event: {
    code: string;
    preventDefault?: () => void;
  }) => void;
  private readonly handleKeyUp: (event: { code: string }) => void;

  constructor(
    bindings: KeyBindings = DEFAULT_KEYBINDINGS,
    targetElement: any = typeof (globalThis as any).window !== 'undefined'
      ? (globalThis as any).window
      : null,
  ) {
    this.bindings = bindings;
    this.targetElement = targetElement;

    this.handleKeyDown = (event) => {
      const code = event.code;
      this.pressedKeys.add(code);

      if (this.bindings.pause.includes(code)) {
        this.queuedActions.push('PAUSE');
        event.preventDefault?.();
      } else if (this.bindings.serve.includes(code)) {
        this.queuedActions.push('SERVE');
        event.preventDefault?.();
      } else if (this.bindings.reset.includes(code)) {
        this.queuedActions.push('RESET');
        event.preventDefault?.();
      }
    };

    this.handleKeyUp = (event) => {
      this.pressedKeys.delete(event.code);
    };

    if (this.targetElement?.addEventListener) {
      this.targetElement.addEventListener('keydown', this.handleKeyDown);
      this.targetElement.addEventListener('keyup', this.handleKeyUp);
    }
  }

  /**
   * Simulates a key down event for testing / programmatic control.
   */
  pressKey(code: string): void {
    this.handleKeyDown({ code });
  }

  /**
   * Simulates a key up event for testing / programmatic control.
   */
  releaseKey(code: string): void {
    this.handleKeyUp({ code });
  }

  /**
   * Polls currently active movement directions.
   */
  poll(): {
    player1Direction: -1 | 0 | 1;
    player2Direction: -1 | 0 | 1;
    actions: readonly InputAction[];
  } {
    let p1Dir: -1 | 0 | 1 = 0;
    let p2Dir: -1 | 0 | 1 = 0;

    // Player 1: W/S
    const p1Up = this.pressedKeys.has('KeyW');
    const p1Down = this.pressedKeys.has('KeyS');
    if (p1Up && !p1Down) p1Dir = -1;
    else if (p1Down && !p1Up) p1Dir = 1;

    // Player 2 / Arrows in single player
    const p2Up = this.pressedKeys.has('ArrowUp');
    const p2Down = this.pressedKeys.has('ArrowDown');
    if (p2Up && !p2Down) {
      p2Dir = -1;
      if (p1Dir === 0) p1Dir = -1; // Allow arrows for P1 if W/S not pressed
    } else if (p2Down && !p2Up) {
      p2Dir = 1;
      if (p1Dir === 0) p1Dir = 1;
    }

    const actions = [...this.queuedActions];
    this.queuedActions.length = 0;

    return {
      player1Direction: p1Dir,
      player2Direction: p2Dir,
      actions,
    };
  }

  /**
   * Cleans up event listeners.
   */
  destroy(): void {
    if (this.targetElement?.removeEventListener) {
      this.targetElement.removeEventListener('keydown', this.handleKeyDown);
      this.targetElement.removeEventListener('keyup', this.handleKeyUp);
    }
    this.pressedKeys.clear();
    this.queuedActions.length = 0;
  }
}
