/**
 * Domain types and interfaces for the Pong Game Engine.
 * Requirement Citations:
 * - R-PONG-CONFIG-1: Dynamic configuration schemas and profile definitions
 * - R-PONG-CORE-2: 2D vector and physical entity interfaces
 * - R-PONG-STATE-3: Finite state machine states, transitions and score models
 * - C-PONG-GOV-9: Governance conformance and strict typed contract definitions
 */

/**
 * 2D Vector representation.
 */
export interface Vector2D {
  readonly x: number;
  readonly y: number;
}

/**
 * Bounding box representation for collisions.
 */
export interface BoundingBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/**
 * Paddle entity definition.
 */
export interface Paddle {
  readonly id: 'player1' | 'player2';
  readonly position: Vector2D;
  readonly velocity: Vector2D;
  readonly width: number;
  readonly height: number;
  readonly speed: number;
  readonly score: number;
}

/**
 * Ball entity definition.
 */
export interface Ball {
  readonly position: Vector2D;
  readonly velocity: Vector2D;
  readonly radius: number;
  readonly speed: number;
  readonly spin: number;
  readonly lastHitBy: 'player1' | 'player2' | null;
}

/**
 * Game lifecycle states.
 */
export type GameStatePhase =
  'MENU' | 'SERVING' | 'PLAYING' | 'PAUSED' | 'ROUND_OVER' | 'GAME_OVER';

/**
 * Game score state.
 */
export interface ScoreState {
  readonly player1: number;
  readonly player2: number;
  readonly maxScore: number;
  readonly winner: 'player1' | 'player2' | null;
  readonly rallyCount: number;
  readonly totalRallies: number;
}

/**
 * Game configuration model.
 */
export interface GameConfig {
  readonly width: number;
  readonly height: number;
  readonly targetFps: number;
  readonly fixedTimestepMs: number;
  readonly maxScore: number;
  readonly serveDelayMs: number;
  readonly ball: {
    readonly radius: number;
    readonly baseSpeed: number;
    readonly speedMultiplier: number;
    readonly maxSpeed: number;
    readonly maxBounceAngleRad: number;
    readonly spinFriction: number;
  };
  readonly paddle: {
    readonly width: number;
    readonly height: number;
    readonly speed: number;
    readonly wallOffset: number;
  };
  readonly ai: {
    readonly enabled: boolean;
    readonly difficulty: 'easy' | 'medium' | 'hard' | 'expert';
    readonly reactionDelayTicks: number;
    readonly predictionAccuracy: number;
    readonly jitterAmount: number;
  };
  readonly audio: {
    readonly enabled: boolean;
    readonly masterVolume: number;
    readonly frequencies: {
      readonly paddleHit: number;
      readonly wallBounce: number;
      readonly score: number;
      readonly win: number;
    };
  };
  readonly theme: {
    readonly background: string;
    readonly foreground: string;
    readonly accent: string;
    readonly netColor: string;
    readonly particleCount: number;
  };
}

/**
 * Collision interaction result.
 */
export interface CollisionResult {
  readonly collided: boolean;
  readonly normal: Vector2D;
  readonly penetration: number;
  readonly contactPoint: Vector2D;
  readonly entity: 'paddle' | 'wall' | 'goal' | 'none';
  readonly side?: 'top' | 'bottom' | 'player1' | 'player2';
}

/**
 * Sound trigger events.
 */
export type SoundEventType =
  'PADDLE_HIT' | 'WALL_BOUNCE' | 'SCORE_POINT' | 'MATCH_WIN';

/**
 * Event listener callback types.
 */
export interface GameEvents {
  onStateChange?: (
    phase: GameStatePhase,
    state: Readonly<GameStateSnapshot>,
  ) => void;
  onScore?: (
    scoringPlayer: 'player1' | 'player2',
    score: Readonly<ScoreState>,
  ) => void;
  onCollision?: (result: CollisionResult) => void;
  onSound?: (event: SoundEventType) => void;
  onGameOver?: (
    winner: 'player1' | 'player2',
    score: Readonly<ScoreState>,
  ) => void;
}

/**
 * Complete immutable snapshot of game simulation state.
 */
export interface GameStateSnapshot {
  readonly phase: GameStatePhase;
  readonly tick: number;
  readonly timestamp: number;
  readonly ball: Readonly<Ball>;
  readonly player1: Readonly<Paddle>;
  readonly player2: Readonly<Paddle>;
  readonly score: Readonly<ScoreState>;
  readonly config: Readonly<GameConfig>;
}
