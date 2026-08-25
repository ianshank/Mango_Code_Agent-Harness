/**
 * Rendering Subsystem Unit Tests.
 * Requirement Citations:
 * - R-PONG-RENDER-7: Multi-target rendering (Canvas 2D, Terminal ANSI, Null)
 * - C-PONG-GOV-9: High-coverage rendering validation
 */

import { describe, it, expect } from 'vitest';
import { TerminalRenderer } from '../../../src/pong/render/terminal-renderer.js';
import { NullRenderer } from '../../../src/pong/render/null-renderer.js';
import { CanvasRenderer } from '../../../src/pong/render/canvas-renderer.js';
import { GameEngine } from '../../../src/pong/core/game-engine.js';
import { Vector } from '../../../src/pong/core/vector.js';

describe('Render Subsystem (R-PONG-RENDER-7)', () => {
  const engine = new GameEngine();
  engine.start();

  it('generates ASCII frames with TerminalRenderer', () => {
    const term = new TerminalRenderer(50, 16);
    const snapshot = engine.getSnapshot();

    term.render(snapshot);
    const output = term.getLastRenderOutput();
    expect(output).toContain('─');
    expect(output).toContain('P1: 0');
    expect(output).toContain('●');

    // Render snapshot with score and game over phase
    const endSnapshot = {
      ...snapshot,
      phase: 'GAME_OVER' as const,
      score: {
        player1: 3,
        player2: 1,
        maxScore: 3,
        rallyCount: 5,
        totalRallies: 5,
        winner: 'player1' as const,
      },
    };
    term.render(endSnapshot);
    expect(term.getLastRenderOutput()).toContain('P1: 3');
    expect(term.getLastRenderOutput()).toContain('Rally: 5');

    term.destroy();
    expect(term.getLastRenderOutput()).toBe('');
  });

  it('tracks frames and state in NullRenderer', () => {
    const nullRenderer = new NullRenderer();
    nullRenderer.resize(800, 500);

    nullRenderer.render(engine.getSnapshot(), 0.75);
    expect(nullRenderer.frameCount).toBe(1);
    expect(nullRenderer.lastAlpha).toBe(0.75);
    expect(nullRenderer.lastSnapshot).toBeDefined();

    nullRenderer.destroy();
    expect(nullRenderer.frameCount).toBe(0);
    expect(nullRenderer.lastSnapshot).toBeNull();
  });

  it('handles CanvasRenderer initialization errors safely', () => {
    expect(() => new CanvasRenderer({ getContext: () => null } as any)).toThrow(
      'CanvasRenderer: Unable to obtain 2D rendering context',
    );
  });

  it('renders states, particles, and overlay screens with CanvasRenderer', () => {
    const calls: string[] = [];
    const mockCtx = {
      fillRect: (...args: any[]) => calls.push(`fillRect:${args.join(',')}`),
      beginPath: () => calls.push('beginPath'),
      moveTo: () => calls.push('moveTo'),
      lineTo: () => calls.push('lineTo'),
      stroke: () => calls.push('stroke'),
      arc: () => calls.push('arc'),
      fill: () => calls.push('fill'),
      fillText: (text: string) => calls.push(`fillText:${text}`),
      scale: () => calls.push('scale'),
      setLineDash: () => {},
      style: {},
    };

    const mockCanvas = {
      getContext: () => mockCtx,
      style: {},
      width: 800,
      height: 500,
    } as any;

    const renderer = new CanvasRenderer(mockCanvas);
    renderer.resize(800, 500);

    // 1. Render MENU phase
    engine.reset();
    renderer.render(engine.getSnapshot());
    expect(calls).toContain('fillText:PONG v2.0');

    // 2. Render PLAYING phase
    engine.start();
    engine.tick(2.0); // Transition to playing
    renderer.render(engine.getSnapshot());

    // 3. Render PAUSED phase
    engine.togglePause();
    renderer.render(engine.getSnapshot());
    expect(calls).toContain('fillText:PAUSED');

    // 4. Render Score particle trigger (P1 scores)
    engine.togglePause();
    (engine as any).ball = {
      ...(engine as any).ball,
      position: Vector.create(engine.config.width + 10, 250),
    };
    engine.tick(0.016);
    renderer.render(engine.getSnapshot());

    // 5. Render Score particle trigger (P2 scores)
    (engine as any).ball = {
      ...(engine as any).ball,
      position: Vector.create(-10, 250),
    };
    engine.tick(0.016);
    renderer.render(engine.getSnapshot());

    // 6. Age particles until removal
    for (let i = 0; i < 40; i++) {
      renderer.render(engine.getSnapshot());
    }

    // 7. Render GAME_OVER phase with AI winner
    const gameOverEngine = new GameEngine({ maxScore: 1, serveDelayMs: 0 });
    gameOverEngine.start();
    gameOverEngine.tick(0.016);
    (gameOverEngine as any).ball = {
      ...(gameOverEngine as any).ball,
      position: Vector.create(-10, 250),
    };
    gameOverEngine.tick(0.016);
    renderer.render(gameOverEngine.getSnapshot());
    expect(calls).toContain('fillText:PLAYER 2 (AI) WINS!');

    renderer.destroy();
  });
});
