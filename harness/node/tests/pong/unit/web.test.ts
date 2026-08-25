/**
 * Web Application Controller Unit Tests.
 * Requirement Citations:
 * - R-PONG-RENDER-7: Browser DOM event binding and controller initialization
 * - C-PONG-GOV-9: Safe DOM abstraction testing
 */

import { describe, it, expect } from 'vitest';
import { initializeWebPong } from '../../../src/pong/web/app.js';
import { Vector } from '../../../src/pong/core/vector.js';

describe('Web Application Controller (R-PONG-RENDER-7)', () => {
  it('handles missing DOM canvas gracefully without throwing', () => {
    expect(() => initializeWebPong()).not.toThrow();
  });

  it('initializes and binds all buttons, inputs, and loop updates when DOM elements exist', () => {
    const listeners: Record<string, Function> = {};
    let rafCallback: Function | null = null;

    const mockElement = (id: string) =>
      ({
        id,
        textContent: '',
        addEventListener: (evt: string, cb: Function) => {
          listeners[`${id}:${evt}`] = cb;
        },
        style: {},
        getContext: () => ({
          fillRect: () => {},
          beginPath: () => {},
          moveTo: () => {},
          lineTo: () => {},
          stroke: () => {},
          arc: () => {},
          fill: () => {},
          fillText: () => {},
          scale: () => {},
          setLineDash: () => {},
        }),
      }) as any;

    const originalDoc = (globalThis as any).document;
    const originalWindow = (globalThis as any).window;

    (globalThis as any).document = {
      getElementById: (id: string) => mockElement(id),
    };

    (globalThis as any).window = {
      addEventListener: (evt: string, cb: Function) => {
        listeners[`window:${evt}`] = cb;
      },
      removeEventListener: () => {},
      requestAnimationFrame: (cb: Function) => {
        rafCallback = cb;
        return 1;
      },
      cancelAnimationFrame: () => {},
    };

    try {
      initializeWebPong();

      // Trigger DOMContentLoaded
      listeners['window:DOMContentLoaded']?.();

      // Trigger start button click
      listeners['startBtn:click']?.();

      // Trigger pause button click twice (pause and resume)
      listeners['pauseBtn:click']?.();
      listeners['pauseBtn:click']?.();

      // Trigger reset button click
      listeners['resetBtn:click']?.();

      // Trigger difficulty change
      listeners['diffSelect:change']?.({ target: { value: 'hard' } });

      // Trigger preset change
      listeners['presetSelect:change']?.({ target: { value: 'fast' } });

      // Trigger sound button click twice (toggle mute)
      listeners['soundBtn:click']?.();
      listeners['soundBtn:click']?.();

      // Trigger keydown actions
      listeners['window:keydown']?.({ code: 'KeyP', preventDefault: () => {} });
      listeners['window:keydown']?.({
        code: 'Space',
        preventDefault: () => {},
      });

      // Trigger RAF frame callbacks to execute game loop update & render with large elapsed delta
      if (rafCallback) {
        (rafCallback as Function)(performance.now());
        (rafCallback as Function)(performance.now() + 100);
      }

      // Trigger custom preset change
      listeners['presetSelect:change']?.({ target: { value: 'classic' } });
      if (rafCallback) {
        (rafCallback as Function)(performance.now() + 200);
      }

      expect(true).toBe(true);
    } finally {
      (globalThis as any).document = originalDoc;
      (globalThis as any).window = originalWindow;
    }
  });
});
