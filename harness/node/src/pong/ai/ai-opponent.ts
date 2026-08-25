/**
 * Multi-Tier Predictive AI Opponent Controller.
 * Requirement Citations:
 * - R-PONG-AI-5: Multi-tier predictive AI opponent with reaction latency and trajectory raycasting
 * - C-PONG-GOV-9: High-precision deterministic calculation
 */

import type { GameStateSnapshot, Vector2D } from '../core/types.js';
import type { AIController, AIDifficulty, AIStrategyConfig } from './types.js';

export class AIOpponent implements AIController {
  private difficulty: AIDifficulty;
  private readonly controlledPlayer: 'player1' | 'player2';
  private targetY: number | null = null;
  private reactionBuffer: Array<{ ballPos: Vector2D; ballVel: Vector2D }> = [];
  private tickCount = 0;

  constructor(
    controlledPlayer: 'player2' | 'player1' = 'player2',
    difficulty: AIDifficulty = 'medium',
  ) {
    this.controlledPlayer = controlledPlayer;
    this.difficulty = difficulty;
  }

  setDifficulty(difficulty: AIDifficulty): void {
    this.difficulty = difficulty;
    this.reactionBuffer = [];
  }

  reset(): void {
    this.targetY = null;
    this.reactionBuffer = [];
    this.tickCount = 0;
  }

  private getStrategyConfig(): AIStrategyConfig {
    switch (this.difficulty) {
      case 'easy':
        return {
          difficulty: 'easy',
          reactionDelayTicks: 8,
          predictionAccuracy: 0.6,
          jitterAmount: 35,
        };
      case 'medium':
        return {
          difficulty: 'medium',
          reactionDelayTicks: 4,
          predictionAccuracy: 0.85,
          jitterAmount: 14,
        };
      case 'hard':
        return {
          difficulty: 'hard',
          reactionDelayTicks: 2,
          predictionAccuracy: 0.95,
          jitterAmount: 5,
        };
      case 'expert':
      default:
        return {
          difficulty: 'expert',
          reactionDelayTicks: 0,
          predictionAccuracy: 1.0,
          jitterAmount: 0,
        };
    }
  }

  /**
   * Raycasts the ball trajectory to compute predicted Y coordinate at the paddle X plane.
   */
  public predictInterceptY(
    snapshot: Readonly<GameStateSnapshot>,
    config: AIStrategyConfig,
  ): number {
    const ball = snapshot.ball;
    const paddle =
      this.controlledPlayer === 'player1' ? snapshot.player1 : snapshot.player2;
    const arenaHeight = snapshot.config.height;

    // If ball is moving away from AI, return to center
    const isMovingTowardAI =
      (this.controlledPlayer === 'player2' && ball.velocity.x > 0) ||
      (this.controlledPlayer === 'player1' && ball.velocity.x < 0);

    if (!isMovingTowardAI || ball.velocity.x === 0) {
      return (arenaHeight - paddle.height) / 2;
    }

    const targetX = paddle.position.x;
    const dx = targetX - ball.position.x;
    const timeToIntercept = dx / ball.velocity.x;

    if (timeToIntercept <= 0) {
      return (arenaHeight - paddle.height) / 2;
    }

    // Easy mode: simple direct tracking without bounce raycasting
    if (config.difficulty === 'easy') {
      return ball.position.y;
    }

    // Medium/Hard/Expert: Calculate reflections against top/bottom walls
    let currentX = ball.position.x;
    let currentY = ball.position.y;
    let currentVy = ball.velocity.y;
    let remainingTime = timeToIntercept;

    while (remainingTime > 0) {
      // Time to hit top or bottom wall
      let timeToWall = Infinity;
      if (currentVy < 0) {
        timeToWall = (ball.radius - currentY) / currentVy;
      } else if (currentVy > 0) {
        timeToWall = (arenaHeight - ball.radius - currentY) / currentVy;
      }

      if (timeToWall >= remainingTime || timeToWall <= 0) {
        currentY += currentVy * remainingTime;
        break;
      } else {
        currentX += ball.velocity.x * timeToWall;
        currentY += currentVy * timeToWall;
        currentVy = -currentVy; // Reflect
        remainingTime -= timeToWall;
      }
    }

    // Add difficulty-based prediction noise and targeting
    if (config.predictionAccuracy < 1.0) {
      const errorFactor =
        (1.0 - config.predictionAccuracy) *
        (Math.sin(this.tickCount * 0.1) * config.jitterAmount);
      currentY += errorFactor;
    }

    // In hard/expert mode, position paddle offset to aim for angular corner deflections
    if (config.difficulty === 'expert') {
      const offset =
        Math.sin(this.tickCount * 0.05) > 0
          ? paddle.height * 0.35
          : -paddle.height * 0.35;
      currentY -= offset;
    }

    return Math.max(
      0,
      Math.min(arenaHeight - paddle.height, currentY - paddle.height / 2),
    );
  }

  /**
   * Updates AI steering command.
   */
  update(snapshot: Readonly<GameStateSnapshot>): -1 | 0 | 1 {
    this.tickCount++;
    const config = this.getStrategyConfig();
    const paddle =
      this.controlledPlayer === 'player1' ? snapshot.player1 : snapshot.player2;

    // Buffer states for reaction latency
    this.reactionBuffer.push({
      ballPos: snapshot.ball.position,
      ballVel: snapshot.ball.velocity,
    });

    if (this.reactionBuffer.length > config.reactionDelayTicks + 1) {
      this.reactionBuffer.shift();
    }

    // Compute target position
    this.targetY = this.predictInterceptY(snapshot, config);

    // Steer paddle towards target
    const paddleCenterY = paddle.position.y + paddle.height / 2;
    const desiredCenterY = this.targetY + paddle.height / 2;
    const deadzone =
      config.difficulty === 'easy'
        ? 12
        : config.difficulty === 'medium'
          ? 6
          : 2;

    const diff = desiredCenterY - paddleCenterY;

    if (Math.abs(diff) <= deadzone) {
      return 0;
    }

    return diff > 0 ? 1 : -1;
  }
}
