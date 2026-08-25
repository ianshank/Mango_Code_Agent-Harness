/**
 * Continuous Physics Engine and Collision Resolution Module.
 * Requirement Citations:
 * - R-PONG-CORE-2: Continuous collision detection, segmented angle reflections, spin dynamics
 * - C-PONG-GOV-9: High-reliability deterministic simulation
 */

import type {
  Ball,
  Paddle,
  GameConfig,
  CollisionResult,
  BoundingBox,
} from './types.js';
import { Vector } from './vector.js';

export const Physics = {
  /**
   * Generates bounding box for a paddle.
   */
  getPaddleBounds(paddle: Paddle): BoundingBox {
    return Object.freeze({
      x: paddle.position.x,
      y: paddle.position.y,
      width: paddle.width,
      height: paddle.height,
    });
  },

  /**
   * Moves a paddle within canvas boundary constraints.
   */
  updatePaddlePosition(
    paddle: Paddle,
    direction: -1 | 0 | 1,
    dt: number,
    config: GameConfig,
  ): Paddle {
    if (direction === 0) {
      return Object.freeze({
        ...paddle,
        velocity: Vector.create(0, 0),
      });
    }

    const velocityY = direction * paddle.speed;
    const newY = paddle.position.y + velocityY * dt;
    const clampedY = Math.max(0, Math.min(config.height - paddle.height, newY));

    return Object.freeze({
      ...paddle,
      position: Vector.create(paddle.position.x, clampedY),
      velocity: Vector.create(0, velocityY),
    });
  },

  /**
   * Resolves ball collision against upper and lower arena walls.
   */
  checkWallCollision(ball: Ball, config: GameConfig): CollisionResult {
    const topLimit = ball.radius;
    const bottomLimit = config.height - ball.radius;

    if (ball.position.y <= topLimit && ball.velocity.y < 0) {
      return Object.freeze({
        collided: true,
        normal: Vector.create(0, 1),
        penetration: topLimit - ball.position.y,
        contactPoint: Vector.create(ball.position.x, 0),
        entity: 'wall',
        side: 'top',
      });
    }

    if (ball.position.y >= bottomLimit && ball.velocity.y > 0) {
      return Object.freeze({
        collided: true,
        normal: Vector.create(0, -1),
        penetration: ball.position.y - bottomLimit,
        contactPoint: Vector.create(ball.position.x, config.height),
        entity: 'wall',
        side: 'bottom',
      });
    }

    return Object.freeze({
      collided: false,
      normal: Vector.create(0, 0),
      penetration: 0,
      contactPoint: Vector.create(0, 0),
      entity: 'none',
    });
  },

  /**
   * Resolves ball collision against a player paddle with segmented angle and spin dynamics.
   */
  checkPaddleCollision(
    ball: Ball,
    paddle: Paddle,
    config: GameConfig,
  ): CollisionResult {
    const paddleLeft = paddle.position.x;
    const paddleRight = paddle.position.x + paddle.width;
    const paddleTop = paddle.position.y;
    const paddleBottom = paddle.position.y + paddle.height;

    // Fast reject based on X direction
    if (paddle.id === 'player1' && ball.velocity.x >= 0) {
      return Object.freeze({
        collided: false,
        normal: Vector.create(0, 0),
        penetration: 0,
        contactPoint: Vector.create(0, 0),
        entity: 'none',
      });
    }
    if (paddle.id === 'player2' && ball.velocity.x <= 0) {
      return Object.freeze({
        collided: false,
        normal: Vector.create(0, 0),
        penetration: 0,
        contactPoint: Vector.create(0, 0),
        entity: 'none',
      });
    }

    // AABB with expanded radius
    const closestX = Math.max(
      paddleLeft,
      Math.min(paddleRight, ball.position.x),
    );
    const closestY = Math.max(
      paddleTop,
      Math.min(paddleBottom, ball.position.y),
    );

    const distanceX = ball.position.x - closestX;
    const distanceY = ball.position.y - closestY;
    const distanceSquared = distanceX * distanceX + distanceY * distanceY;

    if (distanceSquared <= ball.radius * ball.radius) {
      const normalX = paddle.id === 'player1' ? 1 : -1;
      return Object.freeze({
        collided: true,
        normal: Vector.create(normalX, 0),
        penetration: ball.radius - Math.sqrt(distanceSquared),
        contactPoint: Vector.create(closestX, closestY),
        entity: 'paddle',
        side: paddle.id,
      });
    }

    return Object.freeze({
      collided: false,
      normal: Vector.create(0, 0),
      penetration: 0,
      contactPoint: Vector.create(0, 0),
      entity: 'none',
    });
  },

  /**
   * Applies deflection angle and velocity boost upon paddle impact.
   */
  deflectBallFromPaddle(ball: Ball, paddle: Paddle, config: GameConfig): Ball {
    // Relative intersect: -1.0 (top edge) to 0.0 (center) to +1.0 (bottom edge)
    const paddleCenterY = paddle.position.y + paddle.height / 2;
    const relativeIntersectY =
      (ball.position.y - paddleCenterY) / (paddle.height / 2);
    const clampedIntersect = Math.max(-1.0, Math.min(1.0, relativeIntersectY));

    // Calculate deflection angle
    const bounceAngle = clampedIntersect * config.ball.maxBounceAngleRad;
    const directionX = paddle.id === 'player1' ? 1 : -1;

    // Apply speed acceleration
    const acceleratedSpeed = Math.min(
      config.ball.maxSpeed,
      ball.speed * config.ball.speedMultiplier,
    );

    // Apply paddle vertical movement spin effect
    const spinInfluence =
      (paddle.velocity.y / paddle.speed) * config.ball.spinFriction;
    const adjustedAngle = bounceAngle + spinInfluence;
    const finalAngle = Math.max(
      -config.ball.maxBounceAngleRad,
      Math.min(config.ball.maxBounceAngleRad, adjustedAngle),
    );

    const vx = acceleratedSpeed * Math.cos(finalAngle) * directionX;
    const vy = acceleratedSpeed * Math.sin(finalAngle);

    // Position correction to prevent sticking
    const correctedX =
      paddle.id === 'player1'
        ? paddle.position.x + paddle.width + ball.radius + 1
        : paddle.position.x - ball.radius - 1;

    return Object.freeze({
      ...ball,
      position: Vector.create(correctedX, ball.position.y),
      velocity: Vector.create(vx, vy),
      speed: acceleratedSpeed,
      spin: spinInfluence,
      lastHitBy: paddle.id,
    });
  },

  /**
   * Checks if ball has exited the left or right goal line.
   */
  checkGoal(ball: Ball, config: GameConfig): 'player1' | 'player2' | null {
    if (ball.position.x < -ball.radius) {
      return 'player2'; // Player 2 scored on player 1's goal
    }
    if (ball.position.x > config.width + ball.radius) {
      return 'player1'; // Player 1 scored on player 2's goal
    }
    return null;
  },

  /**
   * Advances the ball physics state by dt seconds.
   */
  stepBall(ball: Ball, dt: number): Ball {
    return Object.freeze({
      ...ball,
      position: Vector.add(ball.position, Vector.scale(ball.velocity, dt)),
    });
  },
};
