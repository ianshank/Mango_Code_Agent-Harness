/**
 * Core Game Engine Orchestrator.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Parameterized game initialization
 * - R-PONG-CORE-2: Physics tick step execution
 * - R-PONG-STATE-3: State management and score tracking
 * - C-PONG-GOV-9: Complete governance conformance and type-safe event routing
 */

import type {
  GameConfig,
  GameStateSnapshot,
  Paddle,
  Ball,
  GameEvents,
  SoundEventType,
  CollisionResult,
} from './types.js';
import { Vector } from './vector.js';
import { Physics } from './physics.js';
import { StateMachine } from './state-machine.js';
import { createGameConfig } from './config.js';

export class GameEngine {
  public readonly config: GameConfig;
  private readonly stateMachine: StateMachine;
  private ball: Ball;
  private player1: Paddle;
  private player2: Paddle;
  private tickCount = 0;
  private serveTimerMs = 0;
  private readonly listeners: GameEvents = {};

  constructor(configOverrides?: Partial<GameConfig>, events?: GameEvents) {
    this.config = createGameConfig('classic', configOverrides);
    this.stateMachine = new StateMachine(this.config);

    if (events) {
      this.listeners = { ...events };
    }

    const midY = (this.config.height - this.config.paddle.height) / 2;
    this.player1 = Object.freeze({
      id: 'player1',
      position: Vector.create(this.config.paddle.wallOffset, midY),
      velocity: Vector.create(0, 0),
      width: this.config.paddle.width,
      height: this.config.paddle.height,
      speed: this.config.paddle.speed,
      score: 0,
    });

    this.player2 = Object.freeze({
      id: 'player2',
      position: Vector.create(
        this.config.width -
          this.config.paddle.wallOffset -
          this.config.paddle.width,
        midY,
      ),
      velocity: Vector.create(0, 0),
      width: this.config.paddle.width,
      height: this.config.paddle.height,
      speed: this.config.paddle.speed,
      score: 0,
    });

    this.ball = this.createInitialBall('player1');
  }

  /**
   * Registers event handlers.
   */
  subscribe(events: GameEvents): void {
    Object.assign(this.listeners, events);
  }

  /**
   * Spawns ball in serving position.
   */
  public createInitialBall(
    servedToward: 'player1' | 'player2' = 'player1',
    launchAngle = 0,
  ): Ball {
    const directionX = servedToward === 'player1' ? -1 : 1;
    const angle = Number.isFinite(launchAngle) ? launchAngle : 0;
    const vx = Math.cos(angle) * this.config.ball.baseSpeed * directionX;
    const vy = Math.sin(angle) * this.config.ball.baseSpeed;

    return Object.freeze({
      position: Vector.create(this.config.width / 2, this.config.height / 2),
      velocity: Vector.create(vx, vy),
      radius: this.config.ball.radius,
      speed: this.config.ball.baseSpeed,
      spin: 0,
      lastHitBy: null,
    });
  }

  /**
   * Starts a new match.
   */
  start(launchAngle = 0): void {
    this.stateMachine.startMatch();
    this.serveTimerMs = this.config.serveDelayMs;
    this.ball = this.createInitialBall('player1', launchAngle);
    this.notifyStateChange();
  }

  /**
   * Resets the entire match.
   */
  reset(): void {
    this.stateMachine.resetToMenu();
    this.tickCount = 0;
    this.serveTimerMs = 0;
    const midY = (this.config.height - this.config.paddle.height) / 2;
    this.player1 = Object.freeze({
      ...this.player1,
      position: Vector.create(this.config.paddle.wallOffset, midY),
      velocity: Vector.create(0, 0),
      score: 0,
    });
    this.player2 = Object.freeze({
      ...this.player2,
      position: Vector.create(
        this.config.width -
          this.config.paddle.wallOffset -
          this.config.paddle.width,
        midY,
      ),
      velocity: Vector.create(0, 0),
      score: 0,
    });
    this.ball = this.createInitialBall('player1', 0);
    this.notifyStateChange();
  }

  /**
   * Toggles pause state.
   */
  togglePause(): boolean {
    const isPaused = this.stateMachine.togglePause();
    this.notifyStateChange();
    return isPaused;
  }

  /**
   * Sets paddle movement direction (-1 = Up, 0 = Stop, 1 = Down).
   */
  setPlayerDirection(
    playerId: 'player1' | 'player2',
    direction: -1 | 0 | 1,
    dt = this.config.fixedTimestepMs / 1000,
  ): void {
    if (playerId === 'player1') {
      this.player1 = Physics.updatePaddlePosition(
        this.player1,
        direction,
        dt,
        this.config,
      );
    } else {
      this.player2 = Physics.updatePaddlePosition(
        this.player2,
        direction,
        dt,
        this.config,
      );
    }
  }

  /**
   * Advances the simulation by dt seconds (fixed timestep).
   */
  tick(dt = this.config.fixedTimestepMs / 1000): void {
    this.tickCount++;
    const phase = this.stateMachine.phase;

    if (phase === 'PAUSED' || phase === 'MENU' || phase === 'GAME_OVER') {
      return;
    }

    if (phase === 'SERVING') {
      this.serveTimerMs -= dt * 1000;
      if (this.serveTimerMs <= 0) {
        this.stateMachine.startRally();
        this.notifyStateChange();
      }
      return;
    }

    if (phase === 'ROUND_OVER') {
      this.serveTimerMs -= dt * 1000;
      if (this.serveTimerMs <= 0) {
        this.stateMachine.prepareServe();
        this.serveTimerMs = this.config.serveDelayMs;
        this.ball = this.createInitialBall(
          this.ball.lastHitBy === 'player1' ? 'player2' : 'player1',
        );
        this.notifyStateChange();
      }
      return;
    }

    if (phase === 'PLAYING') {
      // 1. Check Wall collisions
      const wallCollision = Physics.checkWallCollision(this.ball, this.config);
      if (wallCollision.collided) {
        this.ball = Object.freeze({
          ...this.ball,
          velocity: Vector.reflect(this.ball.velocity, wallCollision.normal),
        });
        this.emitSound('WALL_BOUNCE');
        this.emitCollision(wallCollision);
      }

      // 2. Check Paddle collisions
      const p1Collision = Physics.checkPaddleCollision(
        this.ball,
        this.player1,
        this.config,
      );
      if (p1Collision.collided) {
        this.ball = Physics.deflectBallFromPaddle(
          this.ball,
          this.player1,
          this.config,
        );
        this.stateMachine.incrementRally();
        this.emitSound('PADDLE_HIT');
        this.emitCollision(p1Collision);
      }

      const p2Collision = Physics.checkPaddleCollision(
        this.ball,
        this.player2,
        this.config,
      );
      if (p2Collision.collided) {
        this.ball = Physics.deflectBallFromPaddle(
          this.ball,
          this.player2,
          this.config,
        );
        this.stateMachine.incrementRally();
        this.emitSound('PADDLE_HIT');
        this.emitCollision(p2Collision);
      }

      // 3. Step Ball
      this.ball = Physics.stepBall(this.ball, dt);

      // 4. Check Goals
      const scoringPlayer = Physics.checkGoal(this.ball, this.config);
      if (scoringPlayer) {
        const { winner, gameOver } =
          this.stateMachine.recordPoint(scoringPlayer);

        if (scoringPlayer === 'player1') {
          this.player1 = Object.freeze({
            ...this.player1,
            score: this.stateMachine.score.player1,
          });
        } else {
          this.player2 = Object.freeze({
            ...this.player2,
            score: this.stateMachine.score.player2,
          });
        }

        if (gameOver && winner) {
          this.emitSound('MATCH_WIN');
          this.listeners.onGameOver?.(winner, this.stateMachine.score);
        } else {
          this.emitSound('SCORE_POINT');
          this.listeners.onScore?.(scoringPlayer, this.stateMachine.score);
          this.serveTimerMs = this.config.serveDelayMs;
        }

        this.notifyStateChange();
      }
    }
  }

  /**
   * Generates an immutable snapshot of the current state.
   */
  getSnapshot(): GameStateSnapshot {
    return Object.freeze({
      phase: this.stateMachine.phase,
      tick: this.tickCount,
      timestamp: Date.now(),
      ball: this.ball,
      player1: this.player1,
      player2: this.player2,
      score: this.stateMachine.score,
      config: this.config,
    });
  }

  private notifyStateChange(): void {
    this.listeners.onStateChange?.(this.stateMachine.phase, this.getSnapshot());
  }

  private emitSound(type: SoundEventType): void {
    this.listeners.onSound?.(type);
  }

  private emitCollision(result: CollisionResult): void {
    this.listeners.onCollision?.(result);
  }
}
