/**
 * ANSI Terminal 2D Text Renderer for Node.js CLI.
 * Requirement Citations:
 * - R-PONG-RENDER-7: Direct terminal ASCII / ANSI escape rendering for CLI gameplay
 * - C-PONG-GOV-9: Safe cross-platform terminal formatting
 */

import type { Renderer } from './types.js';
import type { GameStateSnapshot } from '../core/types.js';

export class TerminalRenderer implements Renderer {
  private readonly cols: number;
  private readonly rows: number;
  private lastRenderOutput = '';

  constructor(cols = 70, rows = 22) {
    this.cols = cols;
    this.rows = rows;
  }

  /**
   * Generates formatted ASCII screen string representation.
   */
  public generateAsciiFrame(snapshot: Readonly<GameStateSnapshot>): string {
    const grid: string[][] = Array.from({ length: this.rows }, () =>
      Array.from({ length: this.cols }, () => ' '),
    );

    const scaleX = this.cols / snapshot.config.width;
    const scaleY = this.rows / snapshot.config.height;

    // 1. Draw Arena Borders
    const topRow = grid[0];
    const bottomRow = grid[this.rows - 1];
    for (let x = 0; x < this.cols; x++) {
      if (topRow) topRow[x] = '─';
      if (bottomRow) bottomRow[x] = '─';
    }
    const midX = Math.floor(this.cols / 2);
    for (let y = 0; y < this.rows; y++) {
      const row = grid[y];
      if (row) row[midX] = '┆';
    }

    // 2. Draw Paddles
    const p1X = Math.max(
      0,
      Math.min(this.cols - 1, Math.floor(snapshot.player1.position.x * scaleX)),
    );
    const p1StartY = Math.max(
      1,
      Math.min(this.rows - 2, Math.floor(snapshot.player1.position.y * scaleY)),
    );
    const p1Height = Math.max(2, Math.floor(snapshot.player1.height * scaleY));

    for (
      let y = p1StartY;
      y < Math.min(this.rows - 1, p1StartY + p1Height);
      y++
    ) {
      const row = grid[y];
      if (row) row[p1X] = '█';
    }

    const p2X = Math.max(
      0,
      Math.min(this.cols - 1, Math.floor(snapshot.player2.position.x * scaleX)),
    );
    const p2StartY = Math.max(
      1,
      Math.min(this.rows - 2, Math.floor(snapshot.player2.position.y * scaleY)),
    );
    const p2Height = Math.max(2, Math.floor(snapshot.player2.height * scaleY));

    for (
      let y = p2StartY;
      y < Math.min(this.rows - 1, p2StartY + p2Height);
      y++
    ) {
      const row = grid[y];
      if (row) row[p2X] = '█';
    }

    // 3. Draw Ball
    const ballX = Math.max(
      0,
      Math.min(this.cols - 1, Math.floor(snapshot.ball.position.x * scaleX)),
    );
    const ballY = Math.max(
      1,
      Math.min(this.rows - 2, Math.floor(snapshot.ball.position.y * scaleY)),
    );
    const ballRow = grid[ballY];
    if (ballRow) ballRow[ballX] = '●';

    // 4. Header Score line
    const scoreText = ` P1: ${snapshot.score.player1}  |  Rally: ${snapshot.score.rallyCount}  |  P2 (AI): ${snapshot.score.player2} `;
    const statusText = ` [${snapshot.phase}] `;
    const header = scoreText
      .padStart(Math.floor((this.cols + scoreText.length) / 2), ' ')
      .padEnd(this.cols, ' ');

    const rowsStr = grid.map((r) => r.join('')).join('\n');
    return `\x1b[36m${header}\x1b[0m\n${rowsStr}\n\x1b[33m${statusText}\x1b[0m`;
  }

  render(
    snapshot: Readonly<GameStateSnapshot>,
    _interpolationAlpha?: number,
  ): void {
    const frame = this.generateAsciiFrame(snapshot);
    this.lastRenderOutput = frame;
    // Clear screen and redraw in terminal
    if (typeof process !== 'undefined' && process.stdout?.write) {
      process.stdout.write(`\x1b[H${frame}\n`);
    }
  }

  getLastRenderOutput(): string {
    return this.lastRenderOutput;
  }

  destroy(): void {
    this.lastRenderOutput = '';
  }
}
