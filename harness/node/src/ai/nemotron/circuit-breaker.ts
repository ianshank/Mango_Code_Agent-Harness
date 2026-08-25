/**
 * Circuit Breaker Resilience Utility for AI Model Invocations.
 *
 * Requirement Citations:
 * - R-AI-NEMO-1: Fault-tolerant network transport and outage isolation
 * - R-AI-RES-3: Circuit breaker with CLOSED, OPEN, and HALF_OPEN state transitions
 */

export type CircuitState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

export interface CircuitBreakerOptions {
  /** Failure count threshold before opening the circuit (default: 5) */
  readonly failureThreshold?: number;
  /** Cooldown time in ms before transitioning from OPEN to HALF_OPEN (default: 10000) */
  readonly resetTimeoutMs?: number;
  /** Number of consecutive successes in HALF_OPEN to close the circuit (default: 2) */
  readonly halfOpenSuccessThreshold?: number;
}

export class CircuitBreaker {
  private state: CircuitState = 'CLOSED';
  private failureCount = 0;
  private halfOpenSuccessCount = 0;
  private lastStateChangeTime = Date.now();

  private readonly failureThreshold: number;
  private readonly resetTimeoutMs: number;
  private readonly halfOpenSuccessThreshold: number;

  constructor(options: CircuitBreakerOptions = {}) {
    this.failureThreshold = options.failureThreshold ?? 5;
    this.resetTimeoutMs = options.resetTimeoutMs ?? 10000;
    this.halfOpenSuccessThreshold = options.halfOpenSuccessThreshold ?? 2;
  }

  getState(): CircuitState {
    if (this.state === 'OPEN') {
      const elapsed = Date.now() - this.lastStateChangeTime;
      if (elapsed >= this.resetTimeoutMs) {
        this.transitionTo('HALF_OPEN');
      }
    }
    return this.state;
  }

  canExecute(): boolean {
    const currentState = this.getState();
    return currentState === 'CLOSED' || currentState === 'HALF_OPEN';
  }

  recordSuccess(): void {
    const currentState = this.getState();
    if (currentState === 'HALF_OPEN') {
      this.halfOpenSuccessCount++;
      if (this.halfOpenSuccessCount >= this.halfOpenSuccessThreshold) {
        this.transitionTo('CLOSED');
      }
    } else if (currentState === 'CLOSED') {
      this.failureCount = 0;
    }
  }

  recordFailure(): void {
    const currentState = this.getState();
    if (currentState === 'HALF_OPEN') {
      this.transitionTo('OPEN');
    } else if (currentState === 'CLOSED') {
      this.failureCount++;
      if (this.failureCount >= this.failureThreshold) {
        this.transitionTo('OPEN');
      }
    }
  }

  reset(): void {
    this.transitionTo('CLOSED');
    this.failureCount = 0;
    this.halfOpenSuccessCount = 0;
  }

  private transitionTo(newState: CircuitState): void {
    this.state = newState;
    this.lastStateChangeTime = Date.now();
    if (newState === 'CLOSED') {
      this.failureCount = 0;
      this.halfOpenSuccessCount = 0;
    } else if (newState === 'HALF_OPEN') {
      this.halfOpenSuccessCount = 0;
    }
  }
}
