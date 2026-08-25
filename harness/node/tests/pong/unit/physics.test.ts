/**
 * Physics Simulation & Collision Unit Tests.
 * Requirement Citations:
 * - R-PONG-CORE-2: Continuous collision detection, segmented angle reflections, spin dynamics
 * - C-PONG-GOV-9: Deterministic physical calculations
 */

import { describe, it, expect } from 'vitest';
import { Physics } from '../../../src/pong/core/physics.js';
import { Vector } from '../../../src/pong/core/vector.js';
import { createGameConfig } from '../../../src/pong/core/config.js';
import type { Ball, Paddle } from '../../../src/pong/core/types.js';

describe('Physics Simulation (R-PONG-CORE-2)', () => {
  const config = createGameConfig('classic');

  it('updates paddle position within boundary constraints', () => {
    const paddle: Paddle = {
      id: 'player1',
      position: Vector.create(20, 100),
      velocity: Vector.create(0, 0),
      width: 12,
      height: 70,
      speed: 300,
      score: 0,
    };

    // Move Up
    const upPaddle = Physics.updatePaddlePosition(paddle, -1, 0.1, config);
    expect(upPaddle.position.y).toBe(70); // 100 - 300 * 0.1

    // Clamps at top boundary
    const topClamped = Physics.updatePaddlePosition(paddle, -1, 1.0, config);
    expect(topClamped.position.y).toBe(0);

    // Clamps at bottom boundary
    const bottomClamped = Physics.updatePaddlePosition(paddle, 1, 2.0, config);
    expect(bottomClamped.position.y).toBe(config.height - paddle.height);
  });

  it('detects wall collisions on top and bottom boundaries', () => {
    const topBall: Ball = {
      position: Vector.create(400, 5),
      velocity: Vector.create(100, -200),
      radius: 6,
      speed: 200,
      spin: 0,
      lastHitBy: null,
    };

    const topCollision = Physics.checkWallCollision(topBall, config);
    expect(topCollision.collided).toBe(true);
    expect(topCollision.side).toBe('top');

    const bottomBall: Ball = {
      position: Vector.create(400, config.height - 4),
      velocity: Vector.create(100, 200),
      radius: 6,
      speed: 200,
      spin: 0,
      lastHitBy: null,
    };

    const bottomCollision = Physics.checkWallCollision(bottomBall, config);
    expect(bottomCollision.collided).toBe(true);
    expect(bottomCollision.side).toBe('bottom');
  });

  it('detects paddle collisions and resolves deflection angles with spin', () => {
    const paddle: Paddle = {
      id: 'player1',
      position: Vector.create(20, 200),
      velocity: Vector.create(0, 100),
      width: 12,
      height: 70,
      speed: 350,
      score: 0,
    };

    const ball: Ball = {
      position: Vector.create(32, 235), // Hit center
      velocity: Vector.create(-300, 0),
      radius: 6,
      speed: 300,
      spin: 0,
      lastHitBy: null,
    };

    const collision = Physics.checkPaddleCollision(ball, paddle, config);
    expect(collision.collided).toBe(true);
    expect(collision.side).toBe('player1');

    const deflected = Physics.deflectBallFromPaddle(ball, paddle, config);
    expect(deflected.velocity.x).toBeGreaterThan(0); // Bounced to the right
    expect(deflected.speed).toBeGreaterThan(ball.speed); // Accelerated
    expect(deflected.lastHitBy).toBe('player1');
  });

  it('calculates paddle bounds and handles stationary paddle update', () => {
    const paddle: Paddle = {
      id: 'player1',
      position: Vector.create(20, 100),
      velocity: Vector.create(0, 50),
      width: 12,
      height: 70,
      speed: 300,
      score: 0,
    };
    const bounds = Physics.getPaddleBounds(paddle);
    expect(bounds).toEqual({ x: 20, y: 100, width: 12, height: 70 });

    const stationary = Physics.updatePaddlePosition(paddle, 0, 0.1, config);
    expect(stationary.velocity).toEqual({ x: 0, y: 0 });
    expect(stationary.position.y).toBe(100);
  });

  it('detects goals when ball crosses goal lines', () => {
    const p1GoalBall: Ball = {
      position: Vector.create(-10, 250),
      velocity: Vector.create(-300, 0),
      radius: 6,
      speed: 300,
      spin: 0,
      lastHitBy: null,
    };
    expect(Physics.checkGoal(p1GoalBall, config)).toBe('player2');

    const p2GoalBall: Ball = {
      position: Vector.create(config.width + 10, 250),
      velocity: Vector.create(300, 0),
      radius: 6,
      speed: 300,
      spin: 0,
      lastHitBy: null,
    };
    expect(Physics.checkGoal(p2GoalBall, config)).toBe('player1');

    const insideBall: Ball = {
      position: Vector.create(400, 250),
      velocity: Vector.create(100, 0),
      radius: 6,
      speed: 100,
      spin: 0,
      lastHitBy: null,
    };
    expect(Physics.checkGoal(insideBall, config)).toBeNull();
  });

  it('handles player 2 paddle collision and deflection correctly', () => {
    const p2Paddle: Paddle = {
      id: 'player2',
      position: Vector.create(config.width - 40, 200),
      velocity: Vector.create(0, -100),
      width: 12,
      height: 70,
      speed: 350,
      score: 0,
    };

    const ball: Ball = {
      position: Vector.create(config.width - 40, 235),
      velocity: Vector.create(300, 0),
      radius: 6,
      speed: 300,
      spin: 0,
      lastHitBy: null,
    };

    const collision = Physics.checkPaddleCollision(ball, p2Paddle, config);
    expect(collision.collided).toBe(true);
    expect(collision.side).toBe('player2');

    const deflected = Physics.deflectBallFromPaddle(ball, p2Paddle, config);
    expect(deflected.velocity.x).toBeLessThan(0); // Bounced to the left
    expect(deflected.lastHitBy).toBe('player2');
  });
});
