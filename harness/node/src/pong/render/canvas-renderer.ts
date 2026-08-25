/**
 * HTML5 Canvas 2D High-DPI Responsive Renderer.
 * Requirement Citations:
 * - R-PONG-RENDER-7: Hardware-accelerated Canvas 2D rendering with high-DPI and particle effects
 * - C-PONG-GOV-9: High visual polish conforming to 2026 web design standards
 */

import type { Renderer } from './types.js';
import type { GameStateSnapshot } from '../core/types.js';

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  color: string;
  size: number;
}

export class CanvasRenderer implements Renderer {
  private readonly canvas: any;
  private readonly ctx: any;
  private readonly particles: Particle[] = [];
  private lastScoreP1 = 0;
  private lastScoreP2 = 0;

  constructor(canvas: any) {
    this.canvas = canvas;
    const context = canvas.getContext ? canvas.getContext('2d') : null;
    if (!context) {
      throw new Error('CanvasRenderer: Unable to obtain 2D rendering context');
    }
    this.ctx = context;
  }

  resize(width: number, height: number): void {
    const dpr =
      typeof (globalThis as any).window !== 'undefined'
        ? (globalThis as any).window.devicePixelRatio || 1
        : 1;
    this.canvas.width = width * dpr;
    this.canvas.height = height * dpr;
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.ctx.scale(dpr, dpr);
  }

  private spawnScoreParticles(
    x: number,
    y: number,
    color: string,
    count: number,
  ): void {
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = Math.random() * 220 + 60;
      this.particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 0,
        maxLife: Math.random() * 0.5 + 0.3,
        color,
        size: Math.random() * 4 + 2,
      });
    }
  }

  render(
    snapshot: Readonly<GameStateSnapshot>,
    _interpolationAlpha = 1.0,
  ): void {
    const { width, height, theme } = snapshot.config;
    const ctx = this.ctx;

    // Check for score events to trigger particles
    if (snapshot.score.player1 > this.lastScoreP1) {
      this.spawnScoreParticles(
        width,
        snapshot.ball.position.y,
        theme.accent,
        theme.particleCount,
      );
      this.lastScoreP1 = snapshot.score.player1;
    }
    if (snapshot.score.player2 > this.lastScoreP2) {
      this.spawnScoreParticles(
        0,
        snapshot.ball.position.y,
        theme.accent,
        theme.particleCount,
      );
      this.lastScoreP2 = snapshot.score.player2;
    }

    // 1. Clear background
    ctx.fillStyle = theme.background;
    ctx.fillRect(0, 0, width, height);

    // 2. Draw Center Net (Dashed Line)
    ctx.strokeStyle = theme.netColor;
    ctx.lineWidth = 4;
    ctx.setLineDash([12, 12]);
    ctx.beginPath();
    ctx.moveTo(width / 2, 0);
    ctx.lineTo(width / 2, height);
    ctx.stroke();
    ctx.setLineDash([]);

    // 3. Draw Scoreboard
    ctx.fillStyle = theme.foreground;
    ctx.font = 'bold 48px "Courier New", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(`${snapshot.score.player1}`, width / 2 - 80, 25);
    ctx.fillText(`${snapshot.score.player2}`, width / 2 + 80, 25);

    // 4. Draw Paddles
    // Player 1
    ctx.fillStyle = theme.foreground;
    ctx.shadowColor = theme.foreground;
    ctx.shadowBlur = 12;
    ctx.fillRect(
      snapshot.player1.position.x,
      snapshot.player1.position.y,
      snapshot.player1.width,
      snapshot.player1.height,
    );

    // Player 2
    ctx.fillStyle = theme.accent;
    ctx.shadowColor = theme.accent;
    ctx.fillRect(
      snapshot.player2.position.x,
      snapshot.player2.position.y,
      snapshot.player2.width,
      snapshot.player2.height,
    );

    // 5. Draw Ball
    ctx.fillStyle = '#ffffff';
    ctx.shadowColor = '#ffffff';
    ctx.shadowBlur = 16;
    ctx.beginPath();
    ctx.arc(
      snapshot.ball.position.x,
      snapshot.ball.position.y,
      snapshot.ball.radius,
      0,
      Math.PI * 2,
    );
    ctx.fill();
    ctx.shadowBlur = 0; // Reset shadow

    // 6. Update and Draw Particles
    const dt = 1 / 60;
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      if (!p) continue;
      p.life += dt;
      if (p.life >= p.maxLife) {
        this.particles.splice(i, 1);
        continue;
      }
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      const alpha = 1.0 - p.life / p.maxLife;
      ctx.fillStyle = p.color;
      ctx.globalAlpha = alpha;
      ctx.fillRect(p.x, p.y, p.size, p.size);
    }
    ctx.globalAlpha = 1.0;

    // 7. Overlay State Text
    if (snapshot.phase === 'MENU') {
      ctx.fillStyle = 'rgba(10, 14, 23, 0.85)';
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = theme.foreground;
      ctx.font = 'bold 36px monospace';
      ctx.fillText('PONG v2.0', width / 2, height / 2 - 50);
      ctx.font = '18px monospace';
      ctx.fillStyle = '#ffffff';
      ctx.fillText(
        'Press SPACE or ENTER to Start Match',
        width / 2,
        height / 2 + 10,
      );
      ctx.font = '14px monospace';
      ctx.fillStyle = '#888888';
      ctx.fillText(
        'W/S: Player 1 | Up/Down: Player 2 | P: Pause',
        width / 2,
        height / 2 + 50,
      );
    } else if (snapshot.phase === 'PAUSED') {
      ctx.fillStyle = 'rgba(10, 14, 23, 0.7)';
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = '#ffcc00';
      ctx.font = 'bold 36px monospace';
      ctx.fillText('PAUSED', width / 2, height / 2);
    } else if (snapshot.phase === 'GAME_OVER') {
      ctx.fillStyle = 'rgba(10, 14, 23, 0.85)';
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle =
        snapshot.score.winner === 'player1' ? theme.foreground : theme.accent;
      ctx.font = 'bold 36px monospace';
      const winnerName =
        snapshot.score.winner === 'player1' ? 'PLAYER 1' : 'PLAYER 2 (AI)';
      ctx.fillText(`${winnerName} WINS!`, width / 2, height / 2 - 30);
      ctx.font = '18px monospace';
      ctx.fillStyle = '#ffffff';
      ctx.fillText('Press SPACE or R for Rematch', width / 2, height / 2 + 30);
    }
  }

  destroy(): void {
    this.particles.length = 0;
  }
}
