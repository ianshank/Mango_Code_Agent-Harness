/**
 * Fixed-Timestep Accumulator Game Loop.
 * Requirement Citations:
 * - R-PONG-LOOP-8: Frame-rate independent fixed-timestep physics accumulator pattern
 * - C-PONG-GOV-9: High-performance deterministic frame execution
 */

export interface GameLoopCallbacks {
  update: (dt: number) => void;
  render: (interpolationAlpha: number) => void;
}

export class GameLoop {
  private isRunning = false;
  private lastTime = 0;
  private accumulator = 0;
  private readonly fixedTimestepSec: number;
  private readonly maxFrameTimeSec: number;
  private readonly callbacks: GameLoopCallbacks;
  private timerId: any = null;

  constructor(
    callbacks: GameLoopCallbacks,
    fixedTimestepMs = 1000 / 60,
    maxFrameTimeMs = 250,
  ) {
    this.callbacks = callbacks;
    this.fixedTimestepSec = fixedTimestepMs / 1000;
    this.maxFrameTimeSec = maxFrameTimeMs / 1000;
  }

  /**
   * Starts loop execution.
   */
  start(): void {
    if (this.isRunning) return;
    this.isRunning = true;
    this.lastTime =
      typeof performance !== 'undefined' ? performance.now() : Date.now();
    this.accumulator = 0;
    this.scheduleNextFrame();
  }

  /**
   * Stops loop execution.
   */
  stop(): void {
    this.isRunning = false;
    if (this.timerId !== null) {
      const gCaf = (globalThis as any).cancelAnimationFrame;
      if (typeof gCaf === 'function') {
        gCaf(this.timerId);
      } else {
        clearTimeout(this.timerId);
      }
      this.timerId = null;
    }
  }

  get running(): boolean {
    return this.isRunning;
  }

  /**
   * Advances a single frame manually (for test execution and deterministic simulation).
   */
  stepManual(elapsedMs: number): void {
    let frameTime = elapsedMs / 1000;
    if (frameTime > this.maxFrameTimeSec) {
      frameTime = this.maxFrameTimeSec; // Clamp spiral of death
    }

    this.accumulator += frameTime;

    while (this.accumulator >= this.fixedTimestepSec) {
      this.callbacks.update(this.fixedTimestepSec);
      this.accumulator -= this.fixedTimestepSec;
    }

    const alpha = this.accumulator / this.fixedTimestepSec;
    this.callbacks.render(alpha);
  }

  private scheduleNextFrame(): void {
    if (!this.isRunning) return;

    const gRaf = (globalThis as any).requestAnimationFrame;
    if (typeof gRaf === 'function') {
      this.timerId = gRaf((timestamp: number) => this.onFrame(timestamp));
    } else {
      this.timerId = setTimeout(() => {
        const now =
          typeof performance !== 'undefined' ? performance.now() : Date.now();
        this.onFrame(now);
      }, this.fixedTimestepSec * 1000);
    }
  }

  private onFrame(currentTime: number): void {
    if (!this.isRunning) return;

    let deltaMs = currentTime - this.lastTime;
    this.lastTime = currentTime;

    this.stepManual(deltaMs);
    this.scheduleNextFrame();
  }
}
