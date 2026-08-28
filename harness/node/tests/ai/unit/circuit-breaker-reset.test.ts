/**
 * Circuit Breaker Manual Reset Unit Tests.
 * Requirement Citations:
 * - R-AI-RES-3: Circuit breaker with CLOSED, OPEN, and HALF_OPEN state transitions
 */

import { describe, it, expect } from 'vitest';
import { CircuitBreaker } from '../../../src/ai/nemotron/circuit-breaker.js';

describe('Circuit Breaker Manual Reset (R-AI-RES-3)', () => {
  it('reset() force-closes an OPEN circuit and restores execution', () => {
    const cb = new CircuitBreaker({
      failureThreshold: 1,
      resetTimeoutMs: 60000,
    });

    cb.recordFailure();
    expect(cb.getState()).toBe('OPEN');
    expect(cb.canExecute()).toBe(false);

    cb.reset();
    expect(cb.getState()).toBe('CLOSED');
    expect(cb.canExecute()).toBe(true);
  });

  it('reset() clears the accumulated failure count', () => {
    const cb = new CircuitBreaker({
      failureThreshold: 2,
      resetTimeoutMs: 60000,
    });

    cb.recordFailure();
    expect(cb.getState()).toBe('CLOSED');

    cb.reset();

    // If the counter survived reset, this second failure would trip the
    // breaker; a cleared counter keeps it CLOSED.
    cb.recordFailure();
    expect(cb.getState()).toBe('CLOSED');

    cb.recordFailure();
    expect(cb.getState()).toBe('OPEN');
  });

  it('reset() from a fresh CLOSED breaker is a safe no-op', () => {
    const cb = new CircuitBreaker();
    cb.reset();
    expect(cb.getState()).toBe('CLOSED');
    expect(cb.canExecute()).toBe(true);
  });
});
