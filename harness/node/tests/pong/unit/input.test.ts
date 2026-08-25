/**
 * Input Subsystem Unit Tests.
 * Requirement Citations:
 * - R-PONG-INPUT-4: Multi-device input mapping, keyboard listener binding, and action polling
 * - C-PONG-GOV-9: High-coverage input validation
 */

import { describe, it, expect } from 'vitest';
import { InputManager } from '../../../src/pong/input/input-manager.js';
import { KeyboardDriver } from '../../../src/pong/input/keyboard-driver.js';
import type { InputDriver } from '../../../src/pong/input/types.js';

describe('Input Subsystem (R-PONG-INPUT-4)', () => {
  it('manages input actions and drivers with manual fallback', () => {
    const manager = new InputManager();
    const actions: string[] = [];

    const unsubscribe = manager.onAction((a) => actions.push(a));
    manager.dispatchAction('PAUSE');
    expect(actions).toEqual(['PAUSE']);

    unsubscribe();
    manager.dispatchAction('SERVE');
    expect(actions).toEqual(['PAUSE']); // No new action recorded

    // Poll with no driver
    const pollResult = manager.poll();
    expect(pollResult.player1Direction).toBe(0);
    expect(pollResult.player2Direction).toBe(0);

    const mockDriver1: InputDriver = {
      poll: () => ({ player1Direction: 0, player2Direction: 0, actions: [] }),
      destroy: () => {},
    };
    const mockDriver2: InputDriver = {
      poll: () => ({
        player1Direction: -1,
        player2Direction: 1,
        actions: ['SERVE', 'RESET'],
      }),
      destroy: () => {},
    };

    manager.setDriver(mockDriver1);
    manager.setDriver(mockDriver2); // Covers if (this.driver) this.driver.destroy()
    const driverActions: string[] = [];
    manager.onAction((a) => driverActions.push(a));

    const pollWithDriver = manager.poll();
    expect(pollWithDriver.player1Direction).toBe(-1);
    expect(pollWithDriver.player2Direction).toBe(1);
    expect(driverActions).toEqual(['SERVE', 'RESET']);

    manager.destroy();
  });

  it('handles keyboard keydown/keyup events and action dispatching', () => {
    const listeners: Record<string, Function> = {};
    const mockElement = {
      addEventListener: (evt: string, cb: Function) => {
        listeners[evt] = cb;
      },
      removeEventListener: (evt: string) => {
        delete listeners[evt];
      },
    };

    const driver = new KeyboardDriver(undefined, mockElement);

    // Press P -> triggers PAUSE action
    let prevented = false;
    listeners['keydown']?.({
      code: 'KeyP',
      preventDefault: () => (prevented = true),
    });
    expect(prevented).toBe(true);

    // Press Space -> triggers SERVE
    listeners['keydown']?.({ code: 'Space', preventDefault: () => {} });

    // Press R -> triggers RESET
    listeners['keydown']?.({ code: 'KeyR', preventDefault: () => {} });

    // Press KeyW -> Player 1 Up
    driver.pressKey('KeyW');
    const p1UpState = driver.poll();
    expect(p1UpState.player1Direction).toBe(-1);
    expect(p1UpState.actions).toEqual(['PAUSE', 'SERVE', 'RESET']);

    // Release KeyW and Press KeyS -> Player 1 Down
    driver.releaseKey('KeyW');
    driver.pressKey('KeyS');
    expect(driver.poll().player1Direction).toBe(1);

    // Player 2 ArrowUp / ArrowDown
    driver.releaseKey('KeyS');
    driver.pressKey('ArrowUp');
    expect(driver.poll().player2Direction).toBe(-1);

    driver.releaseKey('ArrowUp');
    driver.pressKey('ArrowDown');
    expect(driver.poll().player2Direction).toBe(1);

    driver.destroy();
    expect(Object.keys(listeners).length).toBe(0);
  });
});
